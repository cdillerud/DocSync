"""
bucket_A_misrouting_remediation_plan.py
=======================================
READ-ONLY plan generator. Consumes the per-row root-cause CSV produced
by ``bucket_A_root_cause_report.py`` (Bucket A = Hub HAS the doc but it
is classified outside AP) and emits a per-cohort remediation plan that
specifies, for each ``(email_sender, classification_method,
current_mailbox_category, current_doc_type, current_suggested_job_type,
sharepoint_folder_root)`` cohort, the proposed AP-routing target and
the recommended ``change_type``.

This script proposes nothing live. It does not touch:
  - the classifier
  - routing logic
  - mailbox sources / transport rules
  - the parity report
  - hub_documents (no Mongo writes)

Inputs:
  --in-csv      prod_reports/bucket_A_root_cause.csv (default)
  --min-cohort  minimum affected_doc_count to be "actionable" (default 2)
  --min-score   minimum avg_score to be "actionable" (default 0.60)

Outputs:
  prod_reports/bucket_A_remediation_plan.csv
  prod_reports/bucket_A_remediation_plan.json
  prod_reports/bucket_A_remediation_plan.yaml

Exit codes:
  0  no Bucket A rows found
  1  rows present but no actionable cohorts
  2  rows present and at least one actionable cohort emitted
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from collections import Counter, defaultdict
from typing import Any, Dict, Iterable, List, Tuple

try:
    import yaml  # type: ignore
    _YAML_AVAILABLE = True
except Exception:
    _YAML_AVAILABLE = False


# ---------------------------------------------------------------------------
# Cohort key
# ---------------------------------------------------------------------------

COHORT_KEYS = (
    "email_sender",
    "classification_method",
    "current_mailbox_category",
    "current_doc_type",
    "current_suggested_job_type",
    "sharepoint_folder_root",
)


def _coerce_score(val: Any) -> float:
    try:
        return float(val or 0.0)
    except (TypeError, ValueError):
        return 0.0


def _confidence_band(avg_score: float) -> str:
    if avg_score >= 0.90:
        return "high"
    if avg_score >= 0.60:
        return "medium"
    return "low"


# ---------------------------------------------------------------------------
# change_type decision matrix
# ---------------------------------------------------------------------------

def decide_change_type(cohort_key: Dict[str, str],
                       root_cause_top: str,
                       avg_score: float,
                       count: int) -> Tuple[str, str]:
    """Decide ``(change_type, risk_notes)`` for the cohort.

    Strict, declarative rules driven by the cohort's dominant root cause
    plus its confidence band. Never proposes runtime mutations.
    """
    sender = (cohort_key.get("email_sender") or "").strip()
    cat = (cohort_key.get("current_mailbox_category") or "").strip().upper()
    cls_method = (cohort_key.get("classification_method") or "").strip().lower()

    if root_cause_top == "high_confidence_AP_invoice_misrouted":
        if sender and count >= 3 and avg_score >= 0.90:
            return (
                "routing_rule_addition",
                "Sender is consistent and Hub already classified these as "
                "AP_INVOICE; a sender-pinned routing rule will close the gap. "
                "One-shot data patch can backfill the existing rows.",
            )
        return (
            "one_shot_data_patch",
            "High-confidence AP evidence already on each row; a one-shot "
            "mailbox_category=AP backfill is sufficient. Sender too sparse "
            "or inconsistent for a routing rule.",
        )

    if root_cause_top == "sales_mailbox_captured_AP_invoice":
        if cls_method.startswith("mailbox:"):
            return (
                "routing_rule_addition",
                "Classifier deferred to mailbox identity; AP-folder origin "
                "in Square9 contradicts Sales mailbox. Sender-pinned or "
                "filename-pattern routing rule needed before reclass.",
            )
        return (
            "classifier_signal_uplift",
            "Classifier produced SALES verdict despite AP-folder origin. "
            "Add AP-vendor signal (vendor_canonical match against AP master) "
            "before reclass to avoid Sales-side regressions.",
        )

    if root_cause_top == "operations_mailbox_captured_AP_invoice":
        return (
            "classifier_signal_uplift",
            "Operations capture suggests no vendor signal reached the "
            "classifier; needs AP-vendor signal uplift OR a sender→AP "
            "intake-rule expansion. Do not blind-flip cat=AP.",
        )

    if root_cause_top == "classifier_overrode_AP_evidence":
        return (
            "classifier_signal_uplift",
            "Classifier overrode AP-folder + vendor evidence. Investigate "
            "why; a blind data patch will likely re-misclassify next time.",
        )

    if root_cause_top == "square9_ap_folder_contains_non_ap_document":
        return (
            "manual_review",
            "Document is not AP-shaped (allocation sheet, template, PST, "
            "DO NOT PAY, etc.). Recommend exclude_from_parity_denominator "
            "rather than reclass.",
        )

    if root_cause_top == "low_confidence_match_ambiguous":
        return (
            "manual_review",
            "Match score below 0.60 — cannot trust the Hub-side row "
            "identification. Manual triage required before any patch.",
        )

    if cat and cat != "AP" and avg_score >= 0.85:
        return (
            "one_shot_data_patch",
            "Cohort has high avg score but root_cause is uncertain; a "
            "data-patch is plausible only after manual sample review.",
        )

    return (
        "manual_review",
        "Insufficient evidence for an automated remediation; route to AP "
        "ops for human triage.",
    )


# ---------------------------------------------------------------------------
# Cohort building
# ---------------------------------------------------------------------------

def _row_to_cohort_key(row: Dict[str, str]) -> Dict[str, str]:
    return {
        "email_sender": (row.get("email_sender") or "").strip(),
        "classification_method": (row.get("classification_method") or "").strip(),
        "current_mailbox_category": (
            row.get("best_hub_mailbox_category") or ""
        ).strip(),
        "current_doc_type": (row.get("best_hub_doc_type") or "").strip(),
        "current_suggested_job_type": (
            row.get("best_hub_suggested_job_type") or ""
        ).strip(),
        "sharepoint_folder_root": (
            row.get("sharepoint_folder_root") or ""
        ).strip(),
    }


def build_cohort(members: List[Dict[str, str]],
                 cohort_key: Dict[str, str]) -> Dict[str, Any]:
    scores = [_coerce_score(m.get("best_match_score")) for m in members]
    avg_score = round(sum(scores) / len(scores), 3) if scores else 0.0
    rc_counts = Counter(
        (m.get("root_cause") or "uncertain") for m in members
    )
    rc_top, _ = rc_counts.most_common(1)[0]
    change_type, risk_notes = decide_change_type(
        cohort_key, rc_top, avg_score, len(members),
    )
    parent_roots = Counter(
        (m.get("square9_parent_root") or "") for m in members
    ).most_common(3)
    evidence = [
        {
            "best_hub_doc_id": m.get("best_hub_doc_id") or "",
            "best_hub_file_name": m.get("best_hub_file_name") or "",
            "square9_name": m.get("square9_name") or "",
            "square9_parent_path": m.get("square9_parent_path") or "",
            "best_match_score": _coerce_score(m.get("best_match_score")),
            "root_cause": m.get("root_cause") or "uncertain",
        }
        for m in members[:3]
    ]
    return {
        "cohort_key": cohort_key,
        "affected_doc_count": len(members),
        "avg_score": avg_score,
        "confidence_band": _confidence_band(avg_score),
        "root_cause_distribution": rc_counts.most_common(),
        "dominant_root_cause": rc_top,
        "proposed_mailbox_category": "AP",
        "proposed_doc_type": "AP_INVOICE",
        "proposed_suggested_job_type": "AP_Invoice",
        "change_type": change_type,
        "risk_notes": risk_notes,
        "top_square9_parent_roots": parent_roots,
        "evidence_sample": evidence,
    }


def _is_actionable(cohort: Dict[str, Any],
                   min_cohort: int,
                   min_score: float) -> bool:
    if cohort["affected_doc_count"] < min_cohort:
        return False
    if cohort["avg_score"] < min_score:
        return False
    if cohort["change_type"] == "manual_review":
        return False
    return True


# ---------------------------------------------------------------------------
# Pure analyzer
# ---------------------------------------------------------------------------

def analyze(rows: List[Dict[str, str]],
            min_cohort: int = 2,
            min_score: float = 0.60) -> Dict[str, Any]:
    grouped: Dict[Tuple[str, ...], List[Dict[str, str]]] = defaultdict(list)
    cohort_keys: Dict[Tuple[str, ...], Dict[str, str]] = {}
    for r in rows:
        ck = _row_to_cohort_key(r)
        key_tuple = tuple(ck[k] for k in COHORT_KEYS)
        grouped[key_tuple].append(r)
        cohort_keys[key_tuple] = ck

    cohorts: List[Dict[str, Any]] = []
    for key_tuple, members in grouped.items():
        cohorts.append(build_cohort(members, cohort_keys[key_tuple]))
    cohorts.sort(
        key=lambda c: (-c["affected_doc_count"], -c["avg_score"]),
    )

    actionable = [c for c in cohorts if _is_actionable(c, min_cohort, min_score)]
    manual_review = [c for c in cohorts if c not in actionable]

    actionable_doc_count = sum(c["affected_doc_count"] for c in actionable)
    manual_doc_count = sum(c["affected_doc_count"] for c in manual_review)

    change_type_counts = Counter(
        c["change_type"] for c in actionable
    ).most_common()
    confidence_band_counts = Counter(
        c["confidence_band"] for c in actionable
    ).most_common()

    return {
        "total_bucket_A_rows": len(rows),
        "min_cohort": min_cohort,
        "min_score": min_score,
        "cohort_count_total": len(cohorts),
        "cohort_count_actionable": len(actionable),
        "cohort_count_manual_review": len(manual_review),
        "actionable_doc_count": actionable_doc_count,
        "manual_review_doc_count": manual_doc_count,
        "change_type_counts": change_type_counts,
        "confidence_band_counts": confidence_band_counts,
        "actionable_cohorts": actionable,
        "manual_review_cohorts": manual_review,
    }


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

CSV_COLUMNS = [
    "section",
    "email_sender",
    "classification_method",
    "current_mailbox_category",
    "current_doc_type",
    "current_suggested_job_type",
    "sharepoint_folder_root",
    "proposed_mailbox_category",
    "proposed_doc_type",
    "proposed_suggested_job_type",
    "affected_doc_count",
    "avg_score",
    "confidence_band",
    "dominant_root_cause",
    "change_type",
    "risk_notes",
    "evidence_doc_id_1",
    "evidence_doc_id_2",
    "evidence_doc_id_3",
]


def _flatten_cohort(c: Dict[str, Any], section: str) -> Dict[str, Any]:
    ev = c["evidence_sample"]
    out: Dict[str, Any] = {"section": section}
    out.update(c["cohort_key"])
    out["proposed_mailbox_category"] = c["proposed_mailbox_category"]
    out["proposed_doc_type"] = c["proposed_doc_type"]
    out["proposed_suggested_job_type"] = c["proposed_suggested_job_type"]
    out["affected_doc_count"] = c["affected_doc_count"]
    out["avg_score"] = c["avg_score"]
    out["confidence_band"] = c["confidence_band"]
    out["dominant_root_cause"] = c["dominant_root_cause"]
    out["change_type"] = c["change_type"]
    out["risk_notes"] = c["risk_notes"]
    for i in range(3):
        out[f"evidence_doc_id_{i+1}"] = (
            ev[i]["best_hub_doc_id"] if i < len(ev) else ""
        )
    return out


def load_bucket_A_rows(path: str) -> List[Dict[str, str]]:
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
        for c in result["actionable_cohorts"]:
            w.writerow(_flatten_cohort(c, "actionable"))
        for c in result["manual_review_cohorts"]:
            w.writerow(_flatten_cohort(c, "manual_review"))


def write_json(path: str, result: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, default=str, indent=2)


def write_yaml(path: str, result: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    if not _YAML_AVAILABLE:
        # Degrade to JSON-with-yaml-extension; tests will not require yaml.
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
    if result["total_bucket_A_rows"] == 0:
        return 0
    if result["cohort_count_actionable"] == 0:
        return 1
    return 2


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bucket A misrouting remediation plan (read-only).",
    )
    p.add_argument("--in-csv",
                   default="prod_reports/bucket_A_root_cause.csv")
    p.add_argument("--out-csv",
                   default="prod_reports/bucket_A_remediation_plan.csv")
    p.add_argument("--json",
                   default="prod_reports/bucket_A_remediation_plan.json")
    p.add_argument("--yaml",
                   default="prod_reports/bucket_A_remediation_plan.yaml")
    p.add_argument("--min-cohort", type=int, default=2)
    p.add_argument("--min-score", type=float, default=0.60)
    p.add_argument("--top", type=int, default=25)
    args = p.parse_args()

    rows = load_bucket_A_rows(args.in_csv)
    print(f"Loaded {len(rows)} Bucket A row(s) from {args.in_csv}",
          file=sys.stderr)

    result = analyze(rows, args.min_cohort, args.min_score)
    write_csv(args.out_csv, result)
    write_json(args.json, result)
    write_yaml(args.yaml, result)

    print()
    print("=== bucket_A_misrouting_remediation_plan ===")
    print(f"  total_bucket_A_rows:          {result['total_bucket_A_rows']}")
    print(f"  cohort_count_total:           {result['cohort_count_total']}")
    print(f"  cohort_count_actionable:      {result['cohort_count_actionable']}")
    print(f"  cohort_count_manual_review:   {result['cohort_count_manual_review']}")
    print(f"  actionable_doc_count:         {result['actionable_doc_count']}")
    print(f"  manual_review_doc_count:      {result['manual_review_doc_count']}")
    print()
    print("  change_type_counts (actionable):")
    for k, v in result["change_type_counts"]:
        print(f"    {v:4d}  {k}")
    print()
    print("  confidence_band_counts (actionable):")
    for k, v in result["confidence_band_counts"]:
        print(f"    {v:4d}  {k}")
    print()
    print(f"  TOP {min(args.top, len(result['actionable_cohorts']))} ACTIONABLE COHORTS:")
    for c in result["actionable_cohorts"][:args.top]:
        ck = c["cohort_key"]
        print(f"    n={c['affected_doc_count']:4d}  "
              f"avg={c['avg_score']:.3f}  "
              f"band={c['confidence_band']:6s}  "
              f"change={c['change_type']:25s}  "
              f"sender={ck['email_sender']!r}  "
              f"cat={ck['current_mailbox_category']!r}  "
              f"type={ck['current_doc_type']!r}  "
              f"cls={ck['classification_method']!r}")
    print()
    print(f"  out_csv:  {args.out_csv}")
    print(f"  json:     {args.json}")
    print(f"  yaml:     {args.yaml}")
    return _exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
