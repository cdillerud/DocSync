"""
print_top_remediation_plans.py
==============================
Convenience CLI that prints the top cohorts from the Bucket A and
Bucket C remediation plan JSON outputs in a flat, terminal-friendly
format. Read-only.

Usage:
    python -m scripts.print_top_remediation_plans \
        [bucket_A_remediation_plan.json] \
        [bucket_C_remediation_plan.json] \
        [top]
"""
from __future__ import annotations

import json
import sys


def main() -> int:
    a_path = sys.argv[1] if len(sys.argv) > 1 \
        else "prod_reports/bucket_A_remediation_plan.json"
    c_path = sys.argv[2] if len(sys.argv) > 2 \
        else "prod_reports/bucket_C_remediation_plan.json"
    top = int(sys.argv[3]) if len(sys.argv) > 3 else 10

    with open(a_path) as f:
        a = json.load(f)
    print(f"BUCKET A PLAN: {a_path}")
    print(f"  total_rows={a['total_bucket_A_rows']}  "
          f"actionable_cohorts={a['cohort_count_actionable']}  "
          f"manual_review_cohorts={a['cohort_count_manual_review']}")
    print(f"  actionable_docs={a['actionable_doc_count']}  "
          f"manual_review_docs={a['manual_review_doc_count']}")
    print()
    print("  change_type_counts (actionable):")
    for k, v in a.get("change_type_counts", []):
        print(f"    {v:4d}  {k}")
    print()
    print(f"TOP {top} ACTIONABLE A COHORTS:")
    for i, c in enumerate(a["actionable_cohorts"][:top], 1):
        ck = c["cohort_key"]
        print(f"  [{i}] n={c['affected_doc_count']:4d}  "
              f"avg={c['avg_score']:.3f}  band={c['confidence_band']}  "
              f"change={c['change_type']}  "
              f"sender={ck['email_sender']}  "
              f"cat={ck['current_mailbox_category']}  "
              f"cls={ck['classification_method']}")
        print(f"        risk: {c['risk_notes']}")
    print()

    with open(c_path) as f:
        cdata = json.load(f)
    print(f"BUCKET C PLAN: {c_path}")
    print(f"  total_rows={cdata['total_bucket_C_rows']}  "
          f"intake_change_cohorts={cdata['intake_channel_change_cohort_count']}  "
          f"exclusion_cohorts={cdata['parity_exclusion_cohort_count']}")
    print(f"  intake_gap_rows={cdata['real_intake_gap_row_count']}  "
          f"exclusion_rows={cdata['parity_exclusion_row_count']}")
    print()
    print("  recommended_intake_change_counts:")
    for k, v in cdata.get("recommended_intake_change_counts", []):
        print(f"    {v:4d}  {k}")
    print()
    print(f"TOP {top} INTAKE-CHANNEL-CHANGE COHORTS:")
    for i, c in enumerate(cdata["intake_channel_changes"][:top], 1):
        ck = c["cohort_key"]
        print(f"  [{i}] n={c['affected_doc_count']:4d}  "
              f"vendor={ck['likely_vendor']}  "
              f"channel={ck['candidate_intake_channel']}  "
              f"recommend={c['recommended_intake_change']}  "
              f"owner={c['owner_hint']}")
    print()
    print(f"TOP {top} PARITY-EXCLUSION COHORTS:")
    for i, c in enumerate(cdata["parity_exclusions"][:top], 1):
        print(f"  [{i}] n={c['affected_doc_count']:4d}  "
              f"reason={c['exclusion_reason']}  "
              f"recommend={c['recommended_intake_change']}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
