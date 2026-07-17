"""
reprocess_budget_error_documents.py
=====================================
Recovers documents that never got a real classification because the
LLM budget was exhausted at the moment they were processed - not
because they were genuinely hard to classify.

Why this exists (2026-07-17): investigating why a manually-labeled
Credit_Memo document had empty extracted_fields led to its actual
ai_classification.error field: "Budget has been exceeded! Current
cost: 1136.84..., Max budget: 1136.84...". Checked the full scope
before building anything: 2,530 documents hit this exact error
between 2026-04-28 and 2026-07-14, spread intermittently across
specific bad days (61 in one day alone) rather than constantly -
consistent with contention on a shared LLM budget pool used by other
processes, not a permanent limit. Confirmed via a daily breakdown that
recent volume (163 docs in the last 24h, up to 382/day across the last
week) has zero budget errors - the underlying issue is genuinely
resolved, not just quiet. Of the 2,530, 2,487 are STILL sitting at
doc_type=OTHER today, never reclassified since - this script exists
to give them the classification pass they never actually got.

Reuses services.document_handlers.reprocess_document(doc_id,
reclassify=True) directly rather than reimplementing classification
logic - that function is already proven in production (it's what
backs the manual "reprocess" action in the UI). Its reclassify step
requires the file to exist on local disk at UPLOAD_DIR/doc_id, which
is empty (confirmed: 0 files) for documents this old - but every one
of these 2,487 documents has its full original file content stored
directly in Mongo (file_content_b64, confirmed 100% coverage), so this
script reconstructs the file on disk immediately before calling
reprocess_document(), then removes it afterward rather than leaving
2,487+ files accumulated in the upload directory.

COST AND SCALE WARNING: this makes one real LLM API call per document
processed. Defaults to --limit 10 specifically so the first run is a
small, cheap, easily-reviewed test rather than an accidental full run
across all 2,487 documents. Also has a real, hard safety feature: if
the SAME "Budget has been exceeded" error is detected again on any
document during a run, the batch stops immediately rather than
burning through the remaining documents against an exhausted budget -
this is the one failure mode the whole script exists to work around,
so it must never blindly repeat it at scale.

--dry-run shows exactly which documents would be processed (with
their original vendor/date/size context) without calling the LLM or
spending anything, so scope can be reviewed before committing budget.
"""

from __future__ import annotations

import argparse
import asyncio
import base64
import json
import os
import sys
import time
from typing import Any, Dict, List, Optional

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

BUDGET_ERROR_PATTERN = "Budget has been exceeded"


async def find_affected_documents(db, limit: Optional[int]) -> List[Dict[str, Any]]:
    query = {
        "ai_classification.error": {"$regex": BUDGET_ERROR_PATTERN, "$options": "i"},
        "doc_type": "OTHER",
    }
    projection = {
        "_id": 0, "id": 1, "file_name": 1, "file_content_b64": 1,
        "email_sender": 1, "created_utc": 1, "file_size": 1,
    }
    cursor = db.hub_documents.find(query, projection).sort("created_utc", 1)
    if limit:
        cursor = cursor.limit(limit)
    return await cursor.to_list(length=None)


def write_temp_file(upload_dir, doc_id: str, file_content_b64: str) -> str:
    path = os.path.join(str(upload_dir), doc_id)
    with open(path, "wb") as f:
        f.write(base64.b64decode(file_content_b64))
    return path


async def run(limit: Optional[int], dry_run: bool, delay_seconds: float) -> Dict[str, Any]:
    from motor.motor_asyncio import AsyncIOMotorClient
    from services.document_handlers import reprocess_document, UPLOAD_DIR

    client = AsyncIOMotorClient(os.environ["MONGO_URL"])
    db = client[os.environ["DB_NAME"]]

    docs = await find_affected_documents(db, limit)

    results = {
        "dry_run": dry_run,
        "total_candidates": len(docs),
        "processed": 0,
        "recovered": 0,       # doc_type changed away from OTHER
        "still_other": 0,     # reprocessed but still couldn't classify
        "budget_error_again": 0,
        "other_error": 0,
        "stopped_early": False,
        "stop_reason": None,
        "details": [],
    }

    if dry_run:
        for d in docs:
            results["details"].append({
                "doc_id": d["id"], "file_name": d.get("file_name"),
                "email_sender": d.get("email_sender"),
                "created_utc": d.get("created_utc"),
                "file_size": d.get("file_size"),
                "status": "would_process",
            })
        return results

    for d in docs:
        doc_id = d["id"]
        file_name = d.get("file_name")
        entry = {"doc_id": doc_id, "file_name": file_name}

        b64 = d.get("file_content_b64")
        if not b64:
            entry["status"] = "no_file_content"
            results["other_error"] += 1
            results["details"].append(entry)
            continue

        temp_path = None
        try:
            temp_path = write_temp_file(UPLOAD_DIR, doc_id, b64)
            outcome = await reprocess_document(doc_id, reclassify=True)
            results["processed"] += 1

            new_doc = outcome.get("document") or {}
            new_doc_type = new_doc.get("doc_type") or new_doc.get("document_type")
            error_text = str(outcome.get("error") or "")

            if BUDGET_ERROR_PATTERN.lower() in error_text.lower():
                entry["status"] = "budget_error_again"
                results["budget_error_again"] += 1
                results["details"].append(entry)
                results["stopped_early"] = True
                results["stop_reason"] = (
                    f"Budget error recurred on {file_name} ({doc_id}) - "
                    "stopping the batch rather than burning through the "
                    "rest against an exhausted budget. Re-run later."
                )
                break

            if new_doc_type and new_doc_type != "OTHER":
                entry["status"] = "recovered"
                entry["new_doc_type"] = new_doc_type
                results["recovered"] += 1
            else:
                entry["status"] = "still_other"
                results["still_other"] += 1

        except Exception as e:
            entry["status"] = "error"
            entry["error"] = str(e)[:300]
            results["other_error"] += 1
        finally:
            if temp_path and os.path.exists(temp_path):
                os.remove(temp_path)

        results["details"].append(entry)
        if delay_seconds:
            await asyncio.sleep(delay_seconds)

    return results


def main() -> int:
    ap = argparse.ArgumentParser(
        description="Reprocess documents that failed classification "
                     "due to past LLM budget exhaustion, not genuine "
                     "difficulty. Makes real LLM API calls - defaults "
                     "to a small test batch.",
    )
    ap.add_argument(
        "--limit", type=int, default=10,
        help="Max documents to process (default 10, a small safe test "
             "batch). Pass 0 for no limit - processes all remaining "
             "affected documents.",
    )
    ap.add_argument("--dry-run", action="store_true",
                     help="List what would be processed without calling the LLM.")
    ap.add_argument("--delay-seconds", type=float, default=0.5,
                     help="Pause between documents to avoid hammering the LLM API.")
    ap.add_argument("--json", action="store_true")
    args = ap.parse_args()

    limit = None if args.limit == 0 else args.limit
    result = asyncio.run(run(limit, args.dry_run, args.delay_seconds))

    if args.json:
        print(json.dumps(result, default=str, indent=2))
        return 0

    print("=== reprocess_budget_error_documents ===")
    print(f"  mode:              {'DRY RUN (no LLM calls)' if result['dry_run'] else 'LIVE (real LLM calls)'}")
    print(f"  total_candidates:  {result['total_candidates']}")
    if not result["dry_run"]:
        print(f"  processed:         {result['processed']}")
        print(f"  recovered:         {result['recovered']}  (doc_type successfully assigned)")
        print(f"  still_other:       {result['still_other']}  (reprocessed, genuinely still OTHER)")
        print(f"  budget_error_again:{result['budget_error_again']}")
        print(f"  other_error:       {result['other_error']}")
        if result["stopped_early"]:
            print()
            print(f"  STOPPED EARLY: {result['stop_reason']}")
    print()
    for d in result["details"][:20]:
        if result["dry_run"]:
            print(f"    {d['file_name']}  sender={d.get('email_sender')!r}  created={d.get('created_utc')}")
        else:
            extra = f" -> {d.get('new_doc_type')}" if d.get("new_doc_type") else ""
            print(f"    [{d['status']}] {d['file_name']}{extra}")

    if result["total_candidates"] > 20:
        print(f"    ... and {result['total_candidates'] - 20} more")

    if result["dry_run"]:
        print()
        print("  Re-run without --dry-run to actually reprocess (makes real LLM calls).")

    return 0


if __name__ == "__main__":
    sys.exit(main())
