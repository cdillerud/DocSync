"""
bucket_A_routing_rule_addition_dryrun.py
========================================
READ-ONLY dry-run preview of the Bucket A routing-rule additions.

Consumes:
  --plan-json   prod_reports/bucket_A_remediation_plan.json

Filters the plan's ``actionable_cohorts`` to those with
``change_type == "routing_rule_addition"`` and emits one proposed
routing-rule row per cohort. This script proposes nothing live — it
does not touch the routing service, mailbox sources, transport rules,
hub_documents, or any production config.

Each proposed routing rule has the shape::

    sender_glob                       <-- exact email_sender from cohort
    target_mailbox_category           "AP"
    target_doc_type                   "AP_INVOICE"
    target_suggested_job_type         "AP_Invoice"
    priority                          10 (high) / 20 (medium) / 30 (low)
    affected_doc_count                cohort.affected_doc_count
    source_cohort_*                   full cohort_key for traceability

Outputs:
  prod_reports/bucket_A_routing_rule_addition_dryrun.csv
  prod_reports/bucket_A_routing_rule_addition_dryrun.json

Exit codes:
  0  no ``routing_rule_addition`` cohorts in the plan
  1  cohorts present but every cohort lacks a usable email_sender
  2  at least one routing-rule preview emitted
"""
from __future__ import annotations

import argparse
import json
import csv
import os
import sys
from collections import Counter
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

TARGET_FIELDS = {
    "target_mailbox_category": "AP",
    "target_doc_type": "AP_INVOICE",
    "target_suggested_job_type": "AP_Invoice",
}

PRIORITY_BY_BAND = {
    "high": 10,
    "medium": 20,
    "low": 30,
}

CSV_COLUMNS = [
    "rule_index",
    "sender_glob",
    "target_mailbox_category",
    "target_doc_type",
    "target_suggested_job_type",
    "priority",
    "affected_doc_count",
    "avg_score",
    "confidence_band",
    "dominant_root_cause",
    "source_cohort_email_sender",
    "source_cohort_classification_method",
    "source_cohort_current_mailbox_category",
    "source_cohort_current_doc_type",
    "source_cohort_current_suggested_job_type",
    "source_cohort_sharepoint_folder_root",
    "skipped_reason",
]


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _norm(val: Any) -> str:
    return (val if isinstance(val, str) else ("" if val is None else str(val))).strip()


def select_routing_rule_cohorts(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    cohorts = plan.get("actionable_cohorts") or []
    return [c for c in cohorts if c.get("change_type") == "routing_rule_addition"]


def derive_priority(confidence_band: str, avg_score: Any) -> int:
    band = (confidence_band or "").lower()
    if band in PRIORITY_BY_BAND:
        return PRIORITY_BY_BAND[band]
    try:
        score = float(avg_score or 0.0)
    except (TypeError, ValueError):
        score = 0.0
    if score >= 0.90:
        return PRIORITY_BY_BAND["high"]
    if score >= 0.60:
        return PRIORITY_BY_BAND["medium"]
    return PRIORITY_BY_BAND["low"]


def derive_sender_glob(email_sender: str) -> str:
    """Exact-match sender today; we keep the column glob-shaped so the
    apply step can swap to ``*@domain`` later without a CSV churn."""
    s = _norm(email_sender)
    return s


def build_rule(idx: int, cohort: Dict[str, Any]) -> Dict[str, Any]:
    ck = cohort.get("cohort_key") or {}
    sender = _norm(ck.get("email_sender"))
    sender_glob = derive_sender_glob(sender)
    skipped_reason = "" if sender_glob else "no_email_sender_in_cohort_key"
    return {
        "rule_index": idx,
        "sender_glob": sender_glob,
        **TARGET_FIELDS,
        "priority": derive_priority(
            cohort.get("confidence_band"), cohort.get("avg_score")
        ),
        "affected_doc_count": int(cohort.get("affected_doc_count") or 0),
        "avg_score": cohort.get("avg_score"),
        "confidence_band": cohort.get("confidence_band"),
        "dominant_root_cause": cohort.get("dominant_root_cause"),
        "source_cohort_email_sender": sender,
        "source_cohort_classification_method": _norm(ck.get("classification_method")),
        "source_cohort_current_mailbox_category": _norm(
            ck.get("current_mailbox_category")
        ),
        "source_cohort_current_doc_type": _norm(ck.get("current_doc_type")),
        "source_cohort_current_suggested_job_type": _norm(
            ck.get("current_suggested_job_type")
        ),
        "source_cohort_sharepoint_folder_root": _norm(
            ck.get("sharepoint_folder_root")
        ),
        "skipped_reason": skipped_reason,
    }


# ---------------------------------------------------------------------------
# Pure analyzer
# ---------------------------------------------------------------------------

def analyze(plan: Dict[str, Any]) -> Dict[str, Any]:
    cohorts = select_routing_rule_cohorts(plan)
    cohorts_sorted = sorted(
        cohorts,
        key=lambda c: (-int(c.get("affected_doc_count") or 0),
                       -float(c.get("avg_score") or 0.0)),
    )
    rules = [build_rule(idx, c) for idx, c in enumerate(cohorts_sorted)]
    emitted = [r for r in rules if not r["skipped_reason"]]
    skipped = [r for r in rules if r["skipped_reason"]]

    priority_counts = Counter(r["priority"] for r in emitted).most_common()
    return {
        "cohort_count_total_actionable": len(plan.get("actionable_cohorts") or []),
        "cohort_count_routing_rule_addition": len(cohorts),
        "rule_count_emitted": len(emitted),
        "rule_count_skipped": len(skipped),
        "priority_counts": priority_counts,
        "rules": rules,
        "emitted_rules": emitted,
        "skipped_rules": skipped,
    }


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def write_csv(path: str, result: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for r in result["rules"]:
            w.writerow({k: r.get(k, "") for k in CSV_COLUMNS})


def write_json(path: str, result: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, default=str, indent=2)


def _exit_code(result: Dict[str, Any]) -> int:
    if result["cohort_count_routing_rule_addition"] == 0:
        return 0
    if result["rule_count_emitted"] == 0:
        return 1
    return 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(result: Dict[str, Any], top: int, csv_path: str,
                   json_path: str) -> None:
    print()
    print("=== bucket_A_routing_rule_addition_dryrun ===")
    print(f"  cohort_count_total_actionable:        {result['cohort_count_total_actionable']}")
    print(f"  cohort_count_routing_rule_addition:   {result['cohort_count_routing_rule_addition']}")
    print(f"  rule_count_emitted:                   {result['rule_count_emitted']}")
    print(f"  rule_count_skipped:                   {result['rule_count_skipped']}")
    print()
    print("  priority_counts:")
    for k, v in result["priority_counts"]:
        print(f"    pri={k:>3d}  rules={v}")
    print()
    print(f"  TOP {min(top, len(result['emitted_rules']))} EMITTED RULES:")
    for r in result["emitted_rules"][:top]:
        print(
            f"    idx={r['rule_index']:3d}  "
            f"pri={r['priority']:>3d}  "
            f"affected={r['affected_doc_count']:4d}  "
            f"band={r['confidence_band']!s:6s}  "
            f"sender_glob={r['sender_glob']!r}  "
            f"current_cat={r['source_cohort_current_mailbox_category']!r}"
        )
    if result["skipped_rules"]:
        print()
        print(f"  SKIPPED RULES ({len(result['skipped_rules'])}):")
        for r in result["skipped_rules"][:top]:
            print(
                f"    idx={r['rule_index']:3d}  "
                f"reason={r['skipped_reason']}  "
                f"affected={r['affected_doc_count']:4d}"
            )
    print()
    print(f"  out_csv:  {csv_path}")
    print(f"  json:     {json_path}")
    print("  NOTE: dry-run only — no routing rules were registered.")


def load_plan(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bucket A routing-rule addition DRY RUN (read-only).",
    )
    p.add_argument("--plan-json",
                   default="prod_reports/bucket_A_remediation_plan.json")
    p.add_argument("--out-csv",
                   default="prod_reports/bucket_A_routing_rule_addition_dryrun.csv")
    p.add_argument("--json",
                   default="prod_reports/bucket_A_routing_rule_addition_dryrun.json")
    p.add_argument("--top", type=int, default=25)
    args = p.parse_args()

    plan = load_plan(args.plan_json)
    print(
        f"Loaded plan from {args.plan_json}: "
        f"{len(plan.get('actionable_cohorts') or [])} actionable cohorts",
        file=sys.stderr,
    )
    result = analyze(plan)
    write_csv(args.out_csv, result)
    write_json(args.json, result)
    _print_summary(result, args.top, args.out_csv, args.json)
    return _exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
