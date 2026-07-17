"""
bucket_A_high_confidence_routing_fix.py
========================================
Fixes an isolated, single-document routing gap that no existing
automation covers: a Hub document that Hub's own classifier already
correctly identified as doc_type == "AP_INVOICE", sitting in a
mailbox_category other than "AP" (Operations, Sales, blank, etc).

Why this exists (2026-07-17): confirmed live that bucket_A_misrouting_
remediation_plan.py's --min-cohort defaults to 2 - by design, it only
auto-remediates RECURRING patterns (2+ documents sharing the same
sender/cohort key), a deliberate and sensible guardrail against
over-correcting a genuine one-off anomaly. But that leaves a real gap:
an isolated, single-document case with score >= 0.90 - Hub's highest
confidence tier, meaning the classifier already got doc_type right and
the only thing wrong is which mailbox lane it landed in - never gets
touched by anything. It just sits there, correctly identified as an
AP invoice, permanently mis-filed, until enough similar cases from the
same sender happen to accumulate.

This is deliberately narrower in scope than the general one-shot-
patch mechanism: it ONLY ever sets mailbox_category. It does not
touch doc_type or suggested_job_type, since those are already
correct for every row this targets (that's the entire premise of the
root_cause == "high_confidence_AP_invoice_misrouted" classification
in bucket_A_root_cause_report.py - re-setting an already-correct
field would be a no-op at best and risks masking a real problem if
that assumption is ever wrong for a given row, which is why this
script still re-checks the condition itself rather than trusting the
CSV blindly).

Same safety pattern as bucket_A_one_shot_data_patch_apply.py,
deliberately mirrored rather than reinvented:
  - default (no flag): dry-run preview, no writes
  - --apply --confirm CUTOVER: live write, both required
  - rollback.json snapshot of prior mailbox_category values written
    BEFORE any update, so this can be reversed
  - idempotent via remediation_audit.source - re-running after every
    future readiness check never re-patches the same document twice
  - uses the confirmed-correct document id field ("id", not Mongo's
    auto-generated "_id" ObjectId) - same verified fact
    bucket_A_one_shot_data_patch_apply.py already established
"""

from __future__ import annotations

import argparse
import csv
import datetime as dt
import json
import os
import sys
from typing import Any, Dict, List, Optional, Tuple

PATCH_SOURCE = "bucket_A_high_confidence_routing_fix"
HUB_DOC_ID_FIELD = "id"
MIN_SCORE = 0.90
TARGET_ROOT_CAUSE = "high_confidence_AP_invoice_misrouted"
CONFIRM_TOKEN = "CUTOVER"


# ---------------------------------------------------------------------------
# Pure helpers (testable without Mongo)
# ---------------------------------------------------------------------------

def utc_now_iso() -> str:
    return dt.datetime.now(dt.timezone.utc).isoformat()


def load_rows(path: str) -> List[Dict[str, str]]:
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def select_candidates(rows: List[Dict[str, str]], min_score: float) -> List[Dict[str, str]]:
    """Re-derives the qualifying condition directly (root_cause ==
    the target AND score >= min_score AND doc_type is genuinely
    AP_INVOICE AND mailbox_category is genuinely not AP) rather than
    trusting the CSV's root_cause column alone - defense in depth for
    a script with a live write path, mirroring bucket_A_root_cause_
    report.py's own classify_row condition exactly rather than
    assuming the label is always trustworthy."""
    out = []
    for r in rows:
        if (r.get("root_cause") or "").strip() != TARGET_ROOT_CAUSE:
            continue
        try:
            score = float(r.get("best_match_score") or 0.0)
        except ValueError:
            continue
        if score < min_score:
            continue
        doc_type = (r.get("best_hub_doc_type") or "").strip().upper()
        mailbox_cat = (r.get("best_hub_mailbox_category") or "").strip().upper()
        if doc_type != "AP_INVOICE":
            continue
        if mailbox_cat == "AP":
            continue
        doc_id = (r.get("best_hub_doc_id") or "").strip()
        if not doc_id:
            continue
        out.append(r)
    return out


def is_already_applied(doc: Dict[str, Any]) -> bool:
    audit = doc.get("remediation_audit")
    if not isinstance(audit, dict):
        return False
    return audit.get("source") == PATCH_SOURCE and bool(audit.get("applied_at"))


def build_set_payload(applied_at: str, prior_mailbox_category: Optional[str]) -> Dict[str, Any]:
    return {
        "mailbox_category": "AP",
        "remediation_audit": {
            "source": PATCH_SOURCE,
            "prior_mailbox_category": prior_mailbox_category,
            "applied_at": applied_at,
        },
    }


# ---------------------------------------------------------------------------
# Mongo (lazy import so pure-logic tests never need pymongo)
# ---------------------------------------------------------------------------

def get_hub_documents_collection():
    from pymongo import MongoClient
    mongo_url = os.environ.get("MONGO_URL")
    db_name = os.environ.get("DB_NAME")
    if not mongo_url or not db_name:
        raise RuntimeError("MONGO_URL / DB_NAME env vars are required for --apply.")
    client = MongoClient(mongo_url)
    return client[db_name]["hub_documents"]


def apply_routing_fix(
    candidates: List[Dict[str, str]], collection, rollback_dir: str,
    confirm: bool, applied_at: Optional[str] = None,
) -> Dict[str, Any]:
    applied_at = applied_at or utc_now_iso()

    rollback: List[Dict[str, Any]] = []
    skipped_missing_in_db = 0
    skipped_already_applied = 0
    to_update: List[Tuple[str, Optional[str]]] = []  # (doc_id, prior_mailbox_category)

    for r in candidates:
        doc_id = (r.get("best_hub_doc_id") or "").strip()
        existing = collection.find_one({HUB_DOC_ID_FIELD: doc_id})
        if existing is None:
            skipped_missing_in_db += 1
            continue
        if is_already_applied(existing):
            skipped_already_applied += 1
            continue
        prior_cat = existing.get("mailbox_category")
        rollback.append({
            HUB_DOC_ID_FIELD: doc_id,
            "mailbox_category": prior_cat,
            "file_name": r.get("best_hub_file_name"),
        })
        to_update.append((doc_id, prior_cat))

    if confirm:
        os.makedirs(rollback_dir, exist_ok=True)
        rollback_path = os.path.join(rollback_dir, "rollback.json")
        with open(rollback_path, "w", encoding="utf-8") as f:
            json.dump({
                "patch_source": PATCH_SOURCE,
                "applied_at": applied_at,
                "doc_count": len(rollback),
                "field_patched": "mailbox_category",
                "rollback_records": rollback,
            }, f, default=str, indent=2)
    else:
        rollback_path = None

    modified = 0
    if confirm:
        for doc_id, prior_cat in to_update:
            result = collection.update_one(
                {HUB_DOC_ID_FIELD: doc_id},
                {"$set": build_set_payload(applied_at, prior_cat)},
            )
            modified += int(getattr(result, "modified_count", 0) or 0)

    return {
        "confirm": confirm,
        "applied_at": applied_at,
        "rollback_path": rollback_path,
        "candidate_count": len(candidates),
        "skipped_missing_in_db": skipped_missing_in_db,
        "skipped_already_applied": skipped_already_applied,
        "would_update": len(to_update) if not confirm else 0,
        "updated_count": modified if confirm else 0,
        "to_update_preview": [
            {"doc_id": d, "prior_mailbox_category": p} for d, p in to_update
        ],
    }


# ---------------------------------------------------------------------------
# CLI
# ---------------------------------------------------------------------------

def main() -> int:
    ap = argparse.ArgumentParser(
        description="Fix isolated, single-document, high-confidence "
                     "(score>=0.90) AP-invoice-misrouted-to-wrong-"
                     "mailbox cases that no existing cohort-based "
                     "remediation covers. Dry-run by default.",
    )
    ap.add_argument("--root-cause-csv", default="prod_reports/bucket_A_root_cause.csv")
    ap.add_argument("--min-score", type=float, default=MIN_SCORE)
    ap.add_argument("--apply", action="store_true",
                     help="OPT-IN: apply live to MongoDB. Without this, "
                          "dry-run preview only.")
    ap.add_argument("--confirm", default="",
                     help=f"Required when --apply is set. Must equal {CONFIRM_TOKEN!r}.")
    ap.add_argument("--rollback-dir", default=None)
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    rows = load_rows(args.root_cause_csv)
    candidates = select_candidates(rows, args.min_score)

    confirm = False
    if args.apply:
        if args.confirm != CONFIRM_TOKEN:
            print(f"REFUSED: --apply requires --confirm {CONFIRM_TOKEN}. "
                  "No DB writes performed.", file=sys.stderr)
            return 3
        confirm = True

    rollback_dir = args.rollback_dir or os.path.join(
        "prod_reports",
        f"apply_bucket_A_routing_fix_{dt.datetime.now(dt.timezone.utc).strftime('%Y-%m-%dT%H-%M-%SZ')}",
    )

    if confirm:
        coll = get_hub_documents_collection()
        result = apply_routing_fix(candidates, coll, rollback_dir, confirm=True)
    else:
        # Dry-run still needs Mongo read access to check idempotency/
        # existence, same as the apply path - only the write is gated.
        coll = get_hub_documents_collection()
        result = apply_routing_fix(candidates, coll, rollback_dir, confirm=False)

    if args.json:
        print(json.dumps(result, default=str, indent=2))
        return 0

    print("=== bucket_A_high_confidence_routing_fix ===")
    print(f"  mode:                   {'CONFIRM (writing)' if result['confirm'] else 'DRY RUN (no writes)'}")
    print(f"  candidate_count:        {result['candidate_count']}")
    print(f"  skipped_missing_in_db:  {result['skipped_missing_in_db']}")
    print(f"  skipped_already_applied:{result['skipped_already_applied']}")
    key = "updated_count" if result["confirm"] else "would_update"
    print(f"  {key}:            {result[key]}")
    print()
    for p in result["to_update_preview"]:
        print(f"    doc_id={p['doc_id']}  prior_mailbox_category={p['prior_mailbox_category']!r} -> 'AP'")
    if result["rollback_path"]:
        print()
        print(f"  rollback_path: {result['rollback_path']}")
    if not result["confirm"] and result["candidate_count"] > 0:
        print()
        print(f"  Re-run with --apply --confirm {CONFIRM_TOKEN} to write.")

    return 0


if __name__ == "__main__":
    sys.exit(main())
