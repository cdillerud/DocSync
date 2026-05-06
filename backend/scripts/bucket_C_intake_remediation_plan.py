"""
bucket_C_intake_remediation_plan.py
===================================
READ-ONLY plan generator. Consumes the per-row CSV produced by
``bucket_C_intake_gap_report.py`` (Bucket C = Square9 has the doc, Hub
never received it) and emits a per-cohort remediation plan partitioned
into two sections:

  parity_exclusions
      Rows tagged ``not_expected_in_hub`` by the diagnostic — PSTs,
      treasury files, monthly recs, templates, "DO NOT PAY" markers,
      etc. Recommended action: drop from cutover parity denominator.

  intake_channel_changes
      Real intake gaps. Cohorted by ``(likely_vendor,
      candidate_intake_channel)`` with a recommended_intake_change
      drawn from a closed taxonomy plus an owner_hint.

This script proposes nothing live. It does not touch:
  - the classifier
  - routing logic
  - mailbox sources / transport rules
  - the parity report
  - hub_documents (no Mongo writes)

Inputs:
  --in-csv   prod_reports/bucket_C_intake_gap.csv (default)

Outputs:
  prod_reports/bucket_C_remediation_plan.csv
  prod_reports/bucket_C_remediation_plan.json
  prod_reports/bucket_C_remediation_plan.yaml

Exit codes:
  0  no Bucket C rows found
  1  rows present but only parity exclusions (no actionable intake gaps)
  2  rows present and at least one intake-channel-change cohort emitted
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, List, Tuple

try:
    import yaml  # type: ignore
    _YAML_AVAILABLE = True
except Exception:
    _YAML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Channel → recommendation taxonomy
# ---------------------------------------------------------------------------

# Closed taxonomy for recommended_intake_change. Anything unmapped falls
# back to "manual_followup".
CHANNEL_RECOMMENDATION: Dict[str, Tuple[str, str]] = {
    # channel: (recommended_intake_change, owner_hint)
    "fedex_billing_email": ("add_sender_to_AP_transport_rule", "IT"),
    "cogent_billing_portal": ("enable_portal_download", "AP"),
    "rl_carriers_email": ("forward_billing_alias_to_hub_ap_intake", "AP"),
    "oi_packaging_solutions_email": (
        "add_sender_to_AP_transport_rule", "IT"),
    "britton_email": ("forward_billing_alias_to_hub_ap_intake", "AP"),
    "boyer_email": ("forward_billing_alias_to_hub_ap_intake", "AP"),
    "hawkemedia_email": ("forward_billing_alias_to_hub_ap_intake", "AP"),
    "mdi_email": ("forward_billing_alias_to_hub_ap_intake", "AP"),
    "mra_email": ("forward_billing_alias_to_hub_ap_intake", "AP"),
    "closure_systems_email": ("forward_billing_alias_to_hub_ap_intake", "AP"),
    "tdlines_email": ("forward_billing_alias_to_hub_ap_intake", "AP"),
    "monitored_ap_lane_unknown_sender": ("manual_followup", "AP"),
    "unknown": ("manual_followup", "AP"),
}


def recommend_for_channel(channel: str,
                          fallback_action: str = "") -> Tuple[str, str]:
    """Return ``(recommended_intake_change, owner_hint)`` for a channel."""
    if channel in CHANNEL_RECOMMENDATION:
        return CHANNEL_RECOMMENDATION[channel]
    if fallback_action.startswith("add_") and "sender" in fallback_action:
        return ("add_sender_to_AP_transport_rule", "IT")
    if fallback_action.startswith("confirm_"):
        return ("forward_billing_alias_to_hub_ap_intake", "AP")
    if fallback_action.startswith("investigate_"):
        return ("manual_followup", "AP")
    return ("manual_followup", "AP")


# ---------------------------------------------------------------------------
# Row → bool
# ---------------------------------------------------------------------------

def _is_exclusion(row: Dict[str, str]) -> bool:
    val = (row.get("is_parity_exclusion") or "").strip().lower()
    if val in ("true", "1", "yes", "y"):
        return True
    if val in ("false", "0", "no", "n", ""):
        # Fallback: channel says so
        return (row.get("candidate_intake_channel") or "").strip() == \
            "not_expected_in_hub"
    return False


# ---------------------------------------------------------------------------
# Cohort building
# ---------------------------------------------------------------------------

INTAKE_COHORT_KEYS = ("likely_vendor", "candidate_intake_channel")
EXCLUSION_COHORT_KEYS = ("doc_type_guess",)


def _evidence_sample(rows: List[Dict[str, str]],
                     n: int = 3) -> List[Dict[str, str]]:
    return [
        {
            "square9_name": r.get("square9_name") or "",
            "square9_parent_path": r.get("square9_parent_path") or "",
            "square9_modified": r.get("square9_modified") or "",
            "filename_pattern": r.get("filename_pattern") or "",
        }
        for r in rows[:n]
    ]


def build_intake_cohort(members: List[Dict[str, str]],
                        cohort_key: Dict[str, str]) -> Dict[str, Any]:
    sample = members[0]
    fallback_action = sample.get("recommended_action") or ""
    channel = cohort_key.get("candidate_intake_channel") or "unknown"
    rec, owner = recommend_for_channel(channel, fallback_action)
    parent_roots = Counter(
        (r.get("square9_parent_root") or "") for r in members
    ).most_common(3)
    return {
        "section": "intake_channel_changes",
        "cohort_key": cohort_key,
        "affected_doc_count": len(members),
        "current_arrival_channel": "none",
        "candidate_intake_channel": channel,
        "recommended_intake_change": rec,
        "owner_hint": owner,
        "top_square9_parent_roots": parent_roots,
        "evidence_sample": _evidence_sample(members),
    }


def build_exclusion_cohort(members: List[Dict[str, str]],
                           cohort_key: Dict[str, str]) -> Dict[str, Any]:
    parent_roots = Counter(
        (r.get("square9_parent_root") or "") for r in members
    ).most_common(3)
    return {
        "section": "parity_exclusions",
        "cohort_key": cohort_key,
        "affected_doc_count": len(members),
        "exclusion_reason": cohort_key.get("doc_type_guess") or "unknown",
        "recommended_intake_change": "exclude_from_parity_denominator",
        "owner_hint": "AP",
        "top_square9_parent_roots": parent_roots,
        "evidence_sample": _evidence_sample(members),
    }


# ---------------------------------------------------------------------------
# Pure analyzer
# ---------------------------------------------------------------------------

def analyze(rows: List[Dict[str, str]]) -> Dict[str, Any]:
    exclusion_rows: List[Dict[str, str]] = []
    intake_rows: List[Dict[str, str]] = []
    for r in rows:
        (exclusion_rows if _is_exclusion(r) else intake_rows).append(r)

    intake_grouped: Dict[Tuple[str, ...], List[Dict[str, str]]] = defaultdict(list)
    intake_cohort_keys: Dict[Tuple[str, ...], Dict[str, str]] = {}
    for r in intake_rows:
        ck = {
            "likely_vendor": (r.get("likely_vendor") or "<unknown>").strip()
                or "<unknown>",
            "candidate_intake_channel": (
                r.get("candidate_intake_channel") or "unknown"
            ).strip() or "unknown",
        }
        kt = tuple(ck[k] for k in INTAKE_COHORT_KEYS)
        intake_grouped[kt].append(r)
        intake_cohort_keys[kt] = ck

    intake_cohorts = [
        build_intake_cohort(members, intake_cohort_keys[kt])
        for kt, members in intake_grouped.items()
    ]
    intake_cohorts.sort(key=lambda c: -c["affected_doc_count"])

    exclusion_grouped: Dict[Tuple[str, ...], List[Dict[str, str]]] = defaultdict(list)
    exclusion_cohort_keys: Dict[Tuple[str, ...], Dict[str, str]] = {}
    for r in exclusion_rows:
        ck = {
            "doc_type_guess": (r.get("doc_type_guess") or "unknown").strip()
                or "unknown",
        }
        kt = tuple(ck[k] for k in EXCLUSION_COHORT_KEYS)
        exclusion_grouped[kt].append(r)
        exclusion_cohort_keys[kt] = ck

    exclusion_cohorts = [
        build_exclusion_cohort(members, exclusion_cohort_keys[kt])
        for kt, members in exclusion_grouped.items()
    ]
    exclusion_cohorts.sort(key=lambda c: -c["affected_doc_count"])

    intake_change_counts = Counter(
        c["recommended_intake_change"] for c in intake_cohorts
    ).most_common()
    owner_counts = Counter(
        c["owner_hint"] for c in intake_cohorts
    ).most_common()

    return {
        "total_bucket_C_rows": len(rows),
        "parity_exclusion_row_count": len(exclusion_rows),
        "real_intake_gap_row_count": len(intake_rows),
        "parity_exclusion_cohort_count": len(exclusion_cohorts),
        "intake_channel_change_cohort_count": len(intake_cohorts),
        "recommended_intake_change_counts": intake_change_counts,
        "owner_hint_counts": owner_counts,
        "parity_exclusions": exclusion_cohorts,
        "intake_channel_changes": intake_cohorts,
    }


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "section",
    "likely_vendor",
    "candidate_intake_channel",
    "doc_type_guess",
    "current_arrival_channel",
    "recommended_intake_change",
    "owner_hint",
    "affected_doc_count",
    "exclusion_reason",
    "top_parent_root",
    "evidence_filename_1",
    "evidence_filename_2",
    "evidence_filename_3",
]


def _flatten_intake(c: Dict[str, Any]) -> Dict[str, Any]:
    ev = c["evidence_sample"]
    parent_roots = c["top_square9_parent_roots"]
    return {
        "section": c["section"],
        "likely_vendor": c["cohort_key"]["likely_vendor"],
        "candidate_intake_channel": c["cohort_key"]["candidate_intake_channel"],
        "doc_type_guess": "",
        "current_arrival_channel": c["current_arrival_channel"],
        "recommended_intake_change": c["recommended_intake_change"],
        "owner_hint": c["owner_hint"],
        "affected_doc_count": c["affected_doc_count"],
        "exclusion_reason": "",
        "top_parent_root": parent_roots[0][0] if parent_roots else "",
        "evidence_filename_1": ev[0]["square9_name"] if len(ev) > 0 else "",
        "evidence_filename_2": ev[1]["square9_name"] if len(ev) > 1 else "",
        "evidence_filename_3": ev[2]["square9_name"] if len(ev) > 2 else "",
    }


def _flatten_exclusion(c: Dict[str, Any]) -> Dict[str, Any]:
    ev = c["evidence_sample"]
    parent_roots = c["top_square9_parent_roots"]
    return {
        "section": c["section"],
        "likely_vendor": "",
        "candidate_intake_channel": "not_expected_in_hub",
        "doc_type_guess": c["cohort_key"]["doc_type_guess"],
        "current_arrival_channel": "",
        "recommended_intake_change": c["recommended_intake_change"],
        "owner_hint": c["owner_hint"],
        "affected_doc_count": c["affected_doc_count"],
        "exclusion_reason": c["exclusion_reason"],
        "top_parent_root": parent_roots[0][0] if parent_roots else "",
        "evidence_filename_1": ev[0]["square9_name"] if len(ev) > 0 else "",
        "evidence_filename_2": ev[1]["square9_name"] if len(ev) > 1 else "",
        "evidence_filename_3": ev[2]["square9_name"] if len(ev) > 2 else "",
    }


def load_bucket_C_rows(path: str) -> List[Dict[str, str]]:
    out: List[Dict[str, str]] = []
    with open(path, newline="", encoding="utf-8") as f:
        for r in csv.DictReader(f):
            out.append(r)
    return out


def write_csv(path: str, result: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for c in result["intake_channel_changes"]:
            w.writerow(_flatten_intake(c))
        for c in result["parity_exclusions"]:
            w.writerow(_flatten_exclusion(c))


def write_json(path: str, result: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, default=str, indent=2)


def write_yaml(path: str, result: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not _YAML_AVAILABLE:
        with open(path, "w", encoding="utf-8") as f:
            json.dump(result, f, default=str, indent=2)
        return
    safe = json.loads(json.dumps(result, default=str))
    with open(path, "w", encoding="utf-8") as f:
        yaml.safe_dump(safe, f, sort_keys=False, default_flow_style=False)


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _exit_code(result: Dict[str, Any]) -> int:
    if result["total_bucket_C_rows"] == 0:
        return 0
    if result["intake_channel_change_cohort_count"] == 0:
        return 1
    return 2


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bucket C intake remediation plan (read-only).",
    )
    p.add_argument("--in-csv",
                   default="prod_reports/bucket_C_intake_gap.csv")
    p.add_argument("--out-csv",
                   default="prod_reports/bucket_C_remediation_plan.csv")
    p.add_argument("--json",
                   default="prod_reports/bucket_C_remediation_plan.json")
    p.add_argument("--yaml",
                   default="prod_reports/bucket_C_remediation_plan.yaml")
    p.add_argument("--top", type=int, default=25)
    args = p.parse_args()

    rows = load_bucket_C_rows(args.in_csv)
    print(f"Loaded {len(rows)} Bucket C row(s) from {args.in_csv}",
          file=sys.stderr)

    result = analyze(rows)
    write_csv(args.out_csv, result)
    write_json(args.json, result)
    write_yaml(args.yaml, result)

    print()
    print("=== bucket_C_intake_remediation_plan ===")
    print(f"  total_bucket_C_rows:                  {result['total_bucket_C_rows']}")
    print(f"  parity_exclusion_row_count:           {result['parity_exclusion_row_count']}")
    print(f"  real_intake_gap_row_count:            {result['real_intake_gap_row_count']}")
    print(f"  parity_exclusion_cohort_count:        {result['parity_exclusion_cohort_count']}")
    print(f"  intake_channel_change_cohort_count:   {result['intake_channel_change_cohort_count']}")
    print()
    print("  recommended_intake_change_counts:")
    for k, v in result["recommended_intake_change_counts"]:
        print(f"    {v:4d}  {k}")
    print()
    print("  owner_hint_counts:")
    for k, v in result["owner_hint_counts"]:
        print(f"    {v:4d}  {k}")
    print()
    print(f"  TOP {min(args.top, len(result['intake_channel_changes']))} INTAKE-CHANNEL-CHANGE COHORTS:")
    for c in result["intake_channel_changes"][:args.top]:
        ck = c["cohort_key"]
        print(f"    n={c['affected_doc_count']:4d}  "
              f"vendor={ck['likely_vendor']!r}  "
              f"channel={ck['candidate_intake_channel']!r}  "
              f"recommend={c['recommended_intake_change']!r}  "
              f"owner={c['owner_hint']!r}")
    print()
    print(f"  TOP {min(args.top, len(result['parity_exclusions']))} PARITY-EXCLUSION COHORTS:")
    for c in result["parity_exclusions"][:args.top]:
        print(f"    n={c['affected_doc_count']:4d}  "
              f"reason={c['exclusion_reason']!r}  "
              f"recommend={c['recommended_intake_change']!r}")
    print()
    print(f"  out_csv:  {args.out_csv}")
    print(f"  json:     {args.json}")
    print(f"  yaml:     {args.yaml}")
    return _exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
