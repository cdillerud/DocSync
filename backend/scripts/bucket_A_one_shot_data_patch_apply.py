"""
bucket_A_one_shot_data_patch_apply.py
=====================================
Bucket A one-shot data patch — APPLY companion to the existing dry-run
script. Reclassifies misrouted Hub AP documents identified by the
``one_shot_data_patch`` cohorts in
``prod_reports/bucket_A_remediation_plan.json``.

IMPORTANT
---------
This script HAS A LIVE WRITE PATH. It is gated behind ``--apply`` and is
strictly idempotent:

  default (no flag)        : dry-run; prints update_one previews; no DB writes.
  --apply --confirm CUTOVER: actually applies the patch to MongoDB.

The patch sets, on each affected ``hub_documents`` row::

    mailbox_category     = "AP"
    doc_type             = "AP_INVOICE"
    suggested_job_type   = "AP_Invoice"
    remediation_audit    = {
        source     : "bucket_A_one_shot_patch",
        cohort_key : <cohort_key>,
        applied_at : <UTC ISO timestamp>,
    }

Idempotency:
  - The ``remediation_audit.source`` field is set to a fixed marker.
  - On apply, we also write a per-doc ``remediation_audit.applied_at``
    timestamp, so re-runs can be filtered out by the planner.
  - A rollback file is written FIRST: ``prod_reports/apply_bucket_A_<ts>/
    rollback.json`` containing the prior values of every field this
    script will set, keyed by ``_id``. To roll back, replay that JSON
    via the companion script (or hand-craft a Mongo restore).

Inputs:
  --plan-json        prod_reports/bucket_A_remediation_plan.json
  --root-cause-csv   prod_reports/bucket_A_root_cause.csv
  --apply            opt-in flag; without it the script is read-only.
  --confirm CUTOVER  required string when --apply is set; refuses otherwise.
  --dry-run-csv      writes the same per-doc preview CSV as the dry-run.
  --rollback-dir     dir to write rollback.json into (default
                     prod_reports/apply_bucket_A_<UTC-timestamp>).

Exit codes:
  0  no one-shot cohorts in the plan (nothing to do)
  1  cohorts present but zero matching rows in the root-cause CSV
  2  dry-run preview emitted (no DB writes)
  3  apply attempted but refused (missing --confirm or wrong value)
  4  apply succeeded and at least one document was updated
  5  apply ran but every doc was already idempotent (zero modifications)
"""
from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

# Reuse the dry-run module as the source of truth for the cohort/row
# matching logic. Apply only adds the live-write step on top.
sys.path.insert(0, os.path.dirname(os.path.dirname(
    os.path.abspath(__file__))))  # makes /app/scripts importable
from scripts import bucket_A_one_shot_data_patch_dryrun as ba_dryrun  # noqa: E402

PATCH_SOURCE = ba_dryrun.PATCH_SOURCE
PROPOSED_FIELDS = ba_dryrun.PROPOSED_FIELDS
PATCH_FIELD_NAMES = list(PROPOSED_FIELDS.keys()) + ["remediation_audit"]

# Canonical identifier on hub_documents. The Mongo _id is an auto-generated
# ObjectId; the parity / Bucket A pipeline keys off the UUID stored in `id`.
# Confirmed via scripts/diagnose_hub_documents_id_field.py against the live
# collection (5/5 probe IDs hit `id`, 0/5 hit `_id`).
HUB_DOC_ID_FIELD = "id"


# ---------------------------------------------------------------------------
# Mongo client construction (lazy import so tests can run without pymongo)
# ---------------------------------------------------------------------------

def get_hub_documents_collection():
    """Return the live ``hub_documents`` collection. Imported lazily so
    test runs (which inject a mongomock collection directly) don't pull
    pymongo at module load."""
    from pymongo import MongoClient  # noqa: WPS433
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise RuntimeError(
            "MONGO_URL / DB_NAME env vars are required for --apply.")
    client = MongoClient(mongo_url)
    return client[db_name]["hub_documents"]


# ---------------------------------------------------------------------------
# Pure helpers (testable without Mongo)
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def build_set_payload(cohort_key: Dict[str, Any],
                      applied_at: str) -> Dict[str, Any]:
    return {
        **PROPOSED_FIELDS,
        "remediation_audit": {
            "source": PATCH_SOURCE,
            "cohort_key": dict(cohort_key),
            "applied_at": applied_at,
        },
    }


def snapshot_doc_for_rollback(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Capture the fields this patch will overwrite, plus a marker for
    docs that lacked the field at all (so rollback can $unset them)."""
    snap: Dict[str, Any] = {HUB_DOC_ID_FIELD: str(doc.get(HUB_DOC_ID_FIELD))}
    for f in PATCH_FIELD_NAMES:
        if f in doc:
            snap[f] = doc[f]
        else:
            snap[f"__missing_{f}"] = True
    return snap


def is_already_applied(doc: Dict[str, Any]) -> bool:
    audit = doc.get("remediation_audit")
    if not isinstance(audit, dict):
        return False
    return audit.get("source") == PATCH_SOURCE and bool(audit.get("applied_at"))


# ---------------------------------------------------------------------------
# Apply core (collection injectable for tests)
# ---------------------------------------------------------------------------

def apply_one_shot_patch(plan: Dict[str, Any],
                         rows: List[Dict[str, str]],
                         collection,
                         rollback_dir: str,
                         applied_at: Optional[str] = None,
                         ) -> Dict[str, Any]:
    """Apply the one-shot patch to ``collection``. Writes the rollback
    snapshot BEFORE issuing any updates. Idempotent: docs already
    carrying ``remediation_audit.source == PATCH_SOURCE`` are skipped."""
    applied_at = applied_at or utc_now_iso()
    one_shot_cohorts = ba_dryrun.select_one_shot_cohorts(plan)

    planned: List[Tuple[str, Dict[str, Any]]] = []  # (doc_id, cohort_key)
    for c in one_shot_cohorts:
        ck = c.get("cohort_key") or {}
        for r in rows:
            if not ba_dryrun.row_matches_cohort_key(r, ck):
                continue
            doc_id = (r.get("best_hub_doc_id") or "").strip()
            if doc_id:
                planned.append((doc_id, ck))

    # Snapshot prior state for every planned doc that exists.
    rollback: List[Dict[str, Any]] = []
    skipped_already_applied = 0
    skipped_missing_in_db = 0
    to_update: List[Tuple[str, Dict[str, Any]]] = []
    for doc_id, ck in planned:
        existing = collection.find_one({HUB_DOC_ID_FIELD: doc_id})
        if existing is None:
            skipped_missing_in_db += 1
            continue
        if is_already_applied(existing):
            skipped_already_applied += 1
            continue
        rollback.append(snapshot_doc_for_rollback(existing))
        to_update.append((doc_id, ck))

    os.makedirs(rollback_dir, exist_ok=True)
    rollback_path = os.path.join(rollback_dir, "rollback.json")
    with open(rollback_path, "w", encoding="utf-8") as f:
        json.dump({
            "patch_source": PATCH_SOURCE,
            "applied_at": applied_at,
            "doc_count": len(rollback),
            "fields_patched": PATCH_FIELD_NAMES,
            "rollback_records": rollback,
        }, f, default=str, indent=2)

    modified = 0
    for doc_id, ck in to_update:
        result = collection.update_one(
            {HUB_DOC_ID_FIELD: doc_id},
            {"$set": build_set_payload(ck, applied_at)},
        )
        modified += int(getattr(result, "modified_count", 0) or 0)

    return {
        "patch_source": PATCH_SOURCE,
        "applied_at": applied_at,
        "rollback_path": rollback_path,
        "planned_count": len(planned),
        "skipped_missing_in_db": skipped_missing_in_db,
        "skipped_already_applied": skipped_already_applied,
        "updated_count": modified,
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

CONFIRM_TOKEN = "CUTOVER"


def main() -> int:
    p = argparse.ArgumentParser(
        description="Bucket A one-shot data patch — apply (gated).",
    )
    p.add_argument("--plan-json",
                   default="prod_reports/bucket_A_remediation_plan.json")
    p.add_argument("--root-cause-csv",
                   default="prod_reports/bucket_A_root_cause.csv")
    p.add_argument("--apply", action="store_true",
                   help=("OPT-IN: apply the patch live to MongoDB. "
                         "Without this flag the script behaves as a "
                         "dry-run preview (rc=2)."))
    p.add_argument("--confirm", default="",
                   help=f"Required when --apply is set. Must equal "
                        f"{CONFIRM_TOKEN!r}.")
    p.add_argument("--rollback-dir", default=None,
                   help="Where to write rollback.json. Defaults to "
                        "prod_reports/apply_bucket_A_<UTC-timestamp>/.")
    p.add_argument("--dry-run-csv",
                   default="prod_reports/bucket_A_one_shot_data_patch_dryrun.csv")
    args = p.parse_args()

    plan = ba_dryrun.load_plan(args.plan_json)
    rows = ba_dryrun.load_rows(args.root_cause_csv)

    if not args.apply:
        # Dry-run path: identical output to the dryrun module.
        result = ba_dryrun.analyze(plan, rows)
        ba_dryrun.write_csv(args.dry_run_csv, result)
        ba_dryrun._print_summary(result, 25, args.dry_run_csv,
                                 args.dry_run_csv.replace(".csv", ".json"))
        print()
        print("  NOTE: this is a DRY RUN. Pass --apply --confirm "
              f"{CONFIRM_TOKEN} to write to Mongo.")
        return ba_dryrun._exit_code(result)

    if args.confirm != CONFIRM_TOKEN:
        print()
        print("  REFUSED: --apply requires --confirm "
              f"{CONFIRM_TOKEN}. No DB writes performed.",
              file=sys.stderr)
        return 3

    rollback_dir = args.rollback_dir or os.path.join(
        "prod_reports",
        f"apply_bucket_A_{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ')}",
    )

    coll = get_hub_documents_collection()
    summary = apply_one_shot_patch(plan, rows, coll, rollback_dir)

    print()
    print("=== bucket_A_one_shot_data_patch_apply ===")
    for k in ("patch_source", "applied_at", "planned_count",
              "skipped_missing_in_db", "skipped_already_applied",
              "updated_count", "rollback_path"):
        print(f"  {k:25s}: {summary[k]}")
    print()
    if summary["updated_count"] > 0:
        return 4
    return 5


if __name__ == "__main__":
    raise SystemExit(main())
