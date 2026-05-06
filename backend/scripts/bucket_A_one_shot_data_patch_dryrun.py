"""
bucket_A_one_shot_data_patch_dryrun.py
======================================
READ-ONLY dry-run preview of the Bucket A one-shot data patch.

Consumes BOTH:
  --plan-json        prod_reports/bucket_A_remediation_plan.json
                     (cohort filter; only ``one_shot_data_patch`` cohorts
                     are considered)
  --root-cause-csv   prod_reports/bucket_A_root_cause.csv
                     (authoritative per-document doc-id list)

For every per-doc row in the root-cause CSV whose cohort key matches an
``actionable`` cohort with ``change_type == "one_shot_data_patch"``, this
script emits the EXACT ``update_one`` MongoDB call that *would* run if
the patch were applied. It does NOT touch Mongo, the classifier, the
routing service, mailbox sources, or hub_documents in any way.

Each printed update has the shape::

    db.hub_documents.update_one(
        {"_id": <doc_id>},
        {"$set": {
            "mailbox_category":     "AP",
            "doc_type":             "AP_INVOICE",
            "suggested_job_type":   "AP_Invoice",
            "remediation_audit":    {
                "source":     "bucket_A_one_shot_patch",
                "cohort_key": {...},
                "applied_at": null,
            },
        }},
    )

Outputs:
  prod_reports/bucket_A_one_shot_data_patch_dryrun.csv
  prod_reports/bucket_A_one_shot_data_patch_dryrun.json

Exit codes:
  0  no plan rows OR no ``one_shot_data_patch`` cohorts at all
  1  cohorts present but zero matching rows in the root-cause CSV
  2  cohorts present and at least one per-doc update preview emitted
"""
from __future__ import annotations

import argparse
import csv
import json
import os
import sys
from typing import Any, Dict, List

# ---------------------------------------------------------------------------
# Constants
# ---------------------------------------------------------------------------

PATCH_SOURCE = "bucket_A_one_shot_patch"

PROPOSED_FIELDS = {
    "mailbox_category": "AP",
    "doc_type": "AP_INVOICE",
    "suggested_job_type": "AP_Invoice",
}

# Cohort-key field on the plan JSON  ->  column on the root-cause CSV
COHORT_KEY_TO_CSV_COL = {
    "email_sender": "email_sender",
    "classification_method": "classification_method",
    "current_mailbox_category": "best_hub_mailbox_category",
    "current_doc_type": "best_hub_doc_type",
    "current_suggested_job_type": "best_hub_suggested_job_type",
    "sharepoint_folder_root": "sharepoint_folder_root",
}

CSV_COLUMNS = [
    "cohort_index",
    "doc_id",
    "file_name",
    "current_mailbox_category",
    "current_doc_type",
    "current_suggested_job_type",
    "proposed_mailbox_category",
    "proposed_doc_type",
    "proposed_suggested_job_type",
    "email_sender",
    "classification_method",
    "sharepoint_folder_root",
    "best_match_score",
    "dominant_root_cause",
    "patch_source",
]


# ---------------------------------------------------------------------------
# Loaders
# ---------------------------------------------------------------------------

def load_plan(path: str) -> Dict[str, Any]:
    with open(path, "r", encoding="utf-8") as f:
        return json.load(f)


def load_rows(path: str) -> List[Dict[str, str]]:
    with open(path, "r", newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

def _norm(val: Any) -> str:
    return (val if isinstance(val, str) else ("" if val is None else str(val))).strip()


def select_one_shot_cohorts(plan: Dict[str, Any]) -> List[Dict[str, Any]]:
    cohorts = plan.get("actionable_cohorts") or []
    return [c for c in cohorts if c.get("change_type") == "one_shot_data_patch"]


def row_matches_cohort_key(row: Dict[str, str],
                           cohort_key: Dict[str, str]) -> bool:
    for ck_field, csv_col in COHORT_KEY_TO_CSV_COL.items():
        if _norm(cohort_key.get(ck_field)) != _norm(row.get(csv_col)):
            return False
    return True


def build_update_preview(doc_id: str,
                         cohort_key: Dict[str, str]) -> Dict[str, Any]:
    return {
        "filter": {"_id": doc_id},
        "update": {
            "$set": {
                **PROPOSED_FIELDS,
                "remediation_audit": {
                    "source": PATCH_SOURCE,
                    "cohort_key": dict(cohort_key),
                    "applied_at": None,
                },
            }
        },
    }


def build_doc_record(cohort_index: int,
                     row: Dict[str, str],
                     cohort_key: Dict[str, str]) -> Dict[str, Any]:
    doc_id = _norm(row.get("best_hub_doc_id"))
    return {
        "cohort_index": cohort_index,
        "doc_id": doc_id,
        "file_name": _norm(row.get("best_hub_file_name")),
        "current_mailbox_category": _norm(row.get("best_hub_mailbox_category")),
        "current_doc_type": _norm(row.get("best_hub_doc_type")),
        "current_suggested_job_type": _norm(row.get("best_hub_suggested_job_type")),
        "proposed_mailbox_category": PROPOSED_FIELDS["mailbox_category"],
        "proposed_doc_type": PROPOSED_FIELDS["doc_type"],
        "proposed_suggested_job_type": PROPOSED_FIELDS["suggested_job_type"],
        "email_sender": _norm(row.get("email_sender")),
        "classification_method": _norm(row.get("classification_method")),
        "sharepoint_folder_root": _norm(row.get("sharepoint_folder_root")),
        "best_match_score": _norm(row.get("best_match_score")),
        "dominant_root_cause": _norm(row.get("root_cause")),
        "patch_source": PATCH_SOURCE,
        "update_preview": build_update_preview(doc_id, cohort_key),
    }


# ---------------------------------------------------------------------------
# Pure analyzer
# ---------------------------------------------------------------------------

def analyze(plan: Dict[str, Any],
            rows: List[Dict[str, str]]) -> Dict[str, Any]:
    one_shot_cohorts = select_one_shot_cohorts(plan)

    cohort_summaries: List[Dict[str, Any]] = []
    doc_records: List[Dict[str, Any]] = []
    skipped_no_doc_id = 0

    for idx, c in enumerate(one_shot_cohorts):
        ck = c.get("cohort_key") or {}
        matched = [r for r in rows if row_matches_cohort_key(r, ck)]
        cohort_doc_records: List[Dict[str, Any]] = []
        for r in matched:
            doc_id = _norm(r.get("best_hub_doc_id"))
            if not doc_id:
                skipped_no_doc_id += 1
                continue
            cohort_doc_records.append(build_doc_record(idx, r, ck))

        cohort_summaries.append({
            "cohort_index": idx,
            "cohort_key": ck,
            "expected_doc_count": int(c.get("affected_doc_count") or 0),
            "matched_row_count": len(matched),
            "patch_doc_count": len(cohort_doc_records),
            "avg_score": c.get("avg_score"),
            "confidence_band": c.get("confidence_band"),
            "dominant_root_cause": c.get("dominant_root_cause"),
            "update_many_preview": {
                "filter": {
                    f"cohort_key.{k}": v for k, v in ck.items() if v
                } or {"_note": "cohort_key empty"},
                "update": {
                    "$set": {
                        **PROPOSED_FIELDS,
                        "remediation_audit": {
                            "source": PATCH_SOURCE,
                            "cohort_key": dict(ck),
                            "applied_at": None,
                        },
                    }
                },
                "$comment": (
                    "INDICATIVE ONLY — actual apply step iterates the "
                    "per-doc update_one calls below."
                ),
            },
        })
        doc_records.extend(cohort_doc_records)

    return {
        "patch_source": PATCH_SOURCE,
        "proposed_fields": PROPOSED_FIELDS,
        "cohort_count_total_actionable": len(plan.get("actionable_cohorts") or []),
        "cohort_count_one_shot_data_patch": len(one_shot_cohorts),
        "doc_record_count": len(doc_records),
        "skipped_no_doc_id": skipped_no_doc_id,
        "cohort_summaries": cohort_summaries,
        "doc_records": doc_records,
    }


# ---------------------------------------------------------------------------
# IO
# ---------------------------------------------------------------------------

def write_csv(path: str, result: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", newline="", encoding="utf-8") as f:
        w = csv.DictWriter(f, fieldnames=CSV_COLUMNS, extrasaction="ignore")
        w.writeheader()
        for d in result["doc_records"]:
            w.writerow({k: d.get(k, "") for k in CSV_COLUMNS})


def write_json(path: str, result: Dict[str, Any]) -> None:
    os.makedirs(os.path.dirname(path) or ".", exist_ok=True)
    with open(path, "w", encoding="utf-8") as f:
        json.dump(result, f, default=str, indent=2)


def _exit_code(result: Dict[str, Any]) -> int:
    if result["cohort_count_one_shot_data_patch"] == 0:
        return 0
    if result["doc_record_count"] == 0:
        return 1
    return 2


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def _print_summary(result: Dict[str, Any], top: int, csv_path: str,
                   json_path: str) -> None:
    print()
    print("=== bucket_A_one_shot_data_patch_dryrun ===")
    print(f"  cohort_count_total_actionable:    {result['cohort_count_total_actionable']}")
    print(f"  cohort_count_one_shot_data_patch: {result['cohort_count_one_shot_data_patch']}")
    print(f"  doc_record_count:                 {result['doc_record_count']}")
    print(f"  skipped_no_doc_id:                {result['skipped_no_doc_id']}")
    print()
    print(f"  TOP {min(top, len(result['cohort_summaries']))} ONE-SHOT COHORTS:")
    for cs in result["cohort_summaries"][:top]:
        ck = cs["cohort_key"]
        print(
            f"    idx={cs['cohort_index']:3d}  "
            f"expected={cs['expected_doc_count']:4d}  "
            f"matched={cs['matched_row_count']:4d}  "
            f"patched={cs['patch_doc_count']:4d}  "
            f"band={cs['confidence_band']!s:6s}  "
            f"sender={ck.get('email_sender')!r}  "
            f"cat={ck.get('current_mailbox_category')!r}  "
            f"type={ck.get('current_doc_type')!r}"
        )
    print()
    print("  SAMPLE update_one PREVIEWS (first 3):")
    for d in result["doc_records"][:3]:
        print(
            "    db.hub_documents.update_one("
            f"{json.dumps(d['update_preview']['filter'], default=str)}, "
            f"{json.dumps(d['update_preview']['update'], default=str)})"
        )
    print()
    print(f"  out_csv:  {csv_path}")
    print(f"  json:     {json_path}")
    print("  NOTE: dry-run only — no Mongo writes performed.")


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bucket A one-shot data patch DRY RUN (read-only).",
    )
    p.add_argument("--plan-json",
                   default="prod_reports/bucket_A_remediation_plan.json")
    p.add_argument("--root-cause-csv",
                   default="prod_reports/bucket_A_root_cause.csv")
    p.add_argument("--out-csv",
                   default="prod_reports/bucket_A_one_shot_data_patch_dryrun.csv")
    p.add_argument("--json",
                   default="prod_reports/bucket_A_one_shot_data_patch_dryrun.json")
    p.add_argument("--top", type=int, default=25)
    args = p.parse_args()

    plan = load_plan(args.plan_json)
    rows = load_rows(args.root_cause_csv)
    print(
        f"Loaded plan from {args.plan_json}: "
        f"{len(plan.get('actionable_cohorts') or [])} actionable cohorts",
        file=sys.stderr,
    )
    print(
        f"Loaded {len(rows)} per-doc row(s) from {args.root_cause_csv}",
        file=sys.stderr,
    )

    result = analyze(plan, rows)
    write_csv(args.out_csv, result)
    write_json(args.json, result)
    _print_summary(result, args.top, args.out_csv, args.json)
    return _exit_code(result)


if __name__ == "__main__":
    raise SystemExit(main())
