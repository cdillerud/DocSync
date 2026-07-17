"""
bucket_A_routing_rule_addition_apply.py
=========================================
APPLY companion to bucket_A_routing_rule_addition_dryrun.py. Writes
the proposed sender routing rules into hub_sender_routing_overrides,
the collection email_polling_service.py's live "dynamic" intake path
now consults (see services/sender_routing_overrides.py) before
finalizing a document's mailbox_category.

This is the piece that closes the actual learning loop for routing:
bucket_A_high_confidence_routing_fix.py corrects mailbox_category on
documents that already exist; this script prevents the same sender's
FUTURE emails from being misrouted again in the first place. Without
this, every correction is temporary - the next email from the same
vendor lands in the wrong mailbox exactly the same way, forever.

IMPORTANT: this script has a live write path, gated the same way as
bucket_A_one_shot_data_patch_apply.py and bucket_A_high_confidence_
routing_fix.py:

  default (no flag)         : dry-run; prints what would be written.
  --apply --confirm CUTOVER : writes rules live to Mongo.

Idempotent via upsert on sender_email: re-running after a future
readiness check either confirms an existing rule is still current
(no-op if unchanged) or updates it if the target category genuinely
changed - never creates a duplicate rule for the same sender.

Inputs:
  --plan-json   prod_reports/bucket_A_remediation_plan.json
  --apply / --confirm CUTOVER  gate for live writes

Exit codes:
  0  no routing_rule_addition cohorts in the plan (nothing to do)
  1  cohorts present but every one lacks a usable sender (nothing emittable)
  2  dry-run preview emitted (no DB writes)
  3  apply attempted but refused (missing/wrong --confirm)
  4  apply succeeded, at least one rule written or updated
  5  apply ran but every rule was already current (zero writes needed)
"""

from __future__ import annotations

import argparse
import datetime as dt
import json
import os
import sys
from typing import Any, Dict, List

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
from bucket_A_routing_rule_addition_dryrun import (  # type: ignore
    load_plan, analyze, select_routing_rule_cohorts,
)
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
from services.sender_routing_overrides import (  # type: ignore
    COLLECTION_NAME, normalize_sender_email,
)

CONFIRM_TOKEN = "CUTOVER"
RULE_SOURCE = "bucket_A_routing_rule_addition_apply"


def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def apply_rules(emitted_rules: List[Dict[str, Any]], collection, confirm: bool,
                 applied_at: str = None) -> Dict[str, Any]:
    applied_at = applied_at or utc_now_iso()
    written = 0
    already_current = 0
    would_write = 0
    details: List[Dict[str, Any]] = []

    for rule in emitted_rules:
        sender_key = normalize_sender_email(rule.get("source_cohort_email_sender"))
        if not sender_key:
            continue
        target = rule.get("target_mailbox_category")

        existing = collection.find_one({"sender_email": sender_key})
        if existing is not None and existing.get("target_mailbox_category") == target:
            already_current += 1
            details.append({"sender_email": sender_key, "status": "already_current",
                             "target_mailbox_category": target})
            continue

        entry = {
            "sender_email": sender_key,
            "target_mailbox_category": target,
            "status": "would_write" if not confirm else "written",
        }

        if confirm:
            collection.update_one(
                {"sender_email": sender_key},
                {"$set": {
                    "sender_email": sender_key,
                    "target_mailbox_category": target,
                    "source": RULE_SOURCE,
                    "source_cohort_key": {
                        "email_sender": rule.get("source_cohort_email_sender"),
                        "classification_method": rule.get("source_cohort_classification_method"),
                        "current_mailbox_category": rule.get("source_cohort_current_mailbox_category"),
                        "current_doc_type": rule.get("source_cohort_current_doc_type"),
                        "current_suggested_job_type": rule.get("source_cohort_current_suggested_job_type"),
                        "sharepoint_folder_root": rule.get("source_cohort_sharepoint_folder_root"),
                    },
                    "affected_doc_count_at_creation": rule.get("affected_doc_count"),
                    "created_at": applied_at,
                }},
                upsert=True,
            )
            written += 1
        else:
            would_write += 1

        details.append(entry)

    return {
        "confirm": confirm,
        "applied_at": applied_at,
        "total_emitted_rules": len(emitted_rules),
        "already_current": already_current,
        "would_write": would_write,
        "written": written,
        "details": details,
    }


def get_collection():
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise RuntimeError("MONGO_URL / DB_NAME env vars are required.")
    client = MongoClient(mongo_url)
    return client[db_name][COLLECTION_NAME]


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Apply Bucket A routing-rule-addition cohorts as "
                     "live sender routing overrides. Dry-run by default.",
    )
    ap.add_argument("--plan-json", default="prod_reports/bucket_A_remediation_plan.json")
    ap.add_argument("--apply", action="store_true",
                     help="OPT-IN: write live to MongoDB. Without this, dry-run only.")
    ap.add_argument("--confirm", default="",
                     help=f"Required when --apply is set. Must equal {CONFIRM_TOKEN!r}.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    plan = load_plan(args.plan_json)
    cohort_count = len(select_routing_rule_cohorts(plan))
    if cohort_count == 0:
        print("No routing_rule_addition cohorts in the plan. Nothing to do.")
        return 0

    analysis = analyze(plan)
    emitted = analysis["emitted_rules"]
    if not emitted:
        print("Cohorts present but none had a usable sender. Nothing emittable.")
        return 1

    confirm = False
    if args.apply:
        if args.confirm != CONFIRM_TOKEN:
            print(f"REFUSED: --apply requires --confirm {CONFIRM_TOKEN}. "
                  "No DB writes performed.", file=sys.stderr)
            return 3
        confirm = True

    coll = get_collection()
    result = apply_rules(emitted, coll, confirm)

    if args.json:
        print(json.dumps(result, default=str, indent=2))
    else:
        print("=== bucket_A_routing_rule_addition_apply ===")
        print(f"  mode:                {'CONFIRM (writing)' if confirm else 'DRY RUN (no writes)'}")
        print(f"  total_emitted_rules: {result['total_emitted_rules']}")
        print(f"  already_current:     {result['already_current']}")
        key = "written" if confirm else "would_write"
        print(f"  {key}:          {result[key]}")
        print()
        for d in result["details"]:
            if d["status"] != "already_current":
                print(f"    [{d['status']}] sender={d['sender_email']}  -> {d['target_mailbox_category']}")
        if not confirm and result["would_write"] > 0:
            print()
            print(f"  Re-run with --apply --confirm {CONFIRM_TOKEN} to write.")

    if not confirm:
        return 2
    return 4 if result["written"] > 0 else 5


if __name__ == "__main__":
    sys.exit(main())
