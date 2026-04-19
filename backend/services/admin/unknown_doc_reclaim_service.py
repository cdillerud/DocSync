"""
Unknown-Doc Reclaim Service (v2.5.5)
─────────────────────────────────────

One-shot sweep that rescues documents which slipped through the pipeline
before the v2.5.3 auto-clear `unclassified_guard`. Those docs are currently
sitting at `status = Completed` / `workflow_status = exported` even though
their `doc_type` is None / "" / "Unknown" / "Other" — bypassing manual
review with no extracted content.

Strategy:
  1. Query for candidates with a tight filter (see UNKNOWN_DOC_TYPES + the
     `auto_cleared=True` requirement — we only want docs cleared by the
     buggy old path, not new docs we already caught).
  2. Protect anything that has evidence of a real BC write
     (`bc_purchase_invoice_no`, `bc_record_no`, `bc_record_id`). We must
     never undo a posted invoice.
  3. Idempotent: once a doc has been reclaimed it carries
     `reclaim_to_needs_review_at` — a second run skips it.
  4. Dry-run by default. `execute=True` is required to actually mutate.

Preserves full audit:
  - Keeps `auto_cleared=True` + `auto_cleared_at` (history, don't wipe)
  - Sets `reclaim_to_needs_review_at`, `reclaim_reason`
  - Appends a workflow_history event
  - Also persists a per-doc row in `unknown_doc_reclaim_runs` for auditability
"""
from __future__ import annotations

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from deps import get_db

logger = logging.getLogger(__name__)

# Doc types we consider "unclassified" for reclaim purposes. Matches the
# guard set in services/auto_clear_service.py.
UNKNOWN_DOC_TYPES = [
    None, "", "DEFAULT",
    "Unknown", "UNKNOWN", "unknown",
    "Unknown_Document", "UNKNOWN_DOCUMENT",
    "Unknown_Sales", "UNKNOWN_SALES",
    "Other", "OTHER",
]

# Fields whose presence means a real BC record exists — never reclaim these.
BC_EVIDENCE_FIELDS = [
    "bc_purchase_invoice_no",
    "bc_record_no",
    "bc_document_no",
    "bc_record_id",
]

# Statuses that indicate the doc was previously auto-cleared.
CLEARED_STATUSES = ["Completed", "Exported", "Archived", "completed", "exported", "archived"]


def _build_filter() -> Dict[str, Any]:
    """Shared filter for preview + run. Both must see the exact same set."""
    # A doc is a reclaim candidate if:
    #   • EVERY type field is unclassified/missing (doc_type AND document_type
    #     AND suggested_job_type all ∈ UNKNOWN_DOC_TYPES) — $in matches missing
    #     fields against None, so this correctly catches both "field absent"
    #     and "field set to Unknown". Using $and prevents false-positives
    #     where doc_type="AP_Invoice" but document_type just happens to be
    #     missing.
    #   • status is a cleared/terminal status (not already NeedsReview) AND
    #   • auto_cleared == True (cleared by the pipeline, not manually posted) AND
    #   • no evidence of BC write AND
    #   • not already reclaimed
    bc_not_present = {
        "$and": [{f: {"$in": [None, ""]}} for f in BC_EVIDENCE_FIELDS]
    }
    return {
        "$and": [
            {"doc_type": {"$in": UNKNOWN_DOC_TYPES}},
            {"document_type": {"$in": UNKNOWN_DOC_TYPES}},
            {"suggested_job_type": {"$in": UNKNOWN_DOC_TYPES}},
            {"status": {"$in": CLEARED_STATUSES}},
            {"auto_cleared": True},
            bc_not_present,
            {"reclaim_to_needs_review_at": {"$in": [None, "", False]}},
        ],
    }


async def preview(
    *,
    limit: int = 50,
    db=None,
) -> Dict[str, Any]:
    """Dry-run: counts and a sample of what a real run would touch. No writes."""
    db = db if db is not None else get_db()
    q = _build_filter()

    total = await db.hub_documents.count_documents(q)

    projection = {
        "_id": 0, "id": 1, "doc_type": 1, "document_type": 1,
        "suggested_job_type": 1, "status": 1, "workflow_status": 1,
        "file_name": 1, "vendor_canonical": 1, "batch_parent_id": 1,
        "auto_cleared_at": 1, "created_utc": 1,
    }
    sample = await db.hub_documents.find(q, projection).limit(limit).to_list(limit)

    # Break down by source so operators can see what they're about to rescue
    by_batch_parent = sum(1 for d in sample if d.get("batch_parent_id"))
    by_doc_type: Dict[str, int] = {}
    for d in sample:
        t = d.get("doc_type") or d.get("document_type") or d.get("suggested_job_type") or "None"
        by_doc_type[str(t)] = by_doc_type.get(str(t), 0) + 1

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_candidates": total,
        "sample_size": len(sample),
        "sample_breakdown": {
            "from_batch_split": by_batch_parent,
            "by_doc_type": by_doc_type,
        },
        "sample": sample,
    }


async def run(
    *,
    execute: bool = False,
    limit: Optional[int] = None,
    actor: str = "admin",
    db=None,
) -> Dict[str, Any]:
    """Execute the reclaim. `execute=False` (default) returns the same report
    as preview() — requires explicit `execute=True` to mutate.

    Args:
        execute: If False, no writes happen regardless of other args.
        limit: Optional cap on number of docs to reclaim in this run. Useful
               for staged rollouts (e.g. reclaim 100 at a time to smoke-test).
        actor: Audit field — who / what triggered the run.
    """
    db = db if db is not None else get_db()

    if not execute:
        p = await preview(db=db, limit=50)
        return {
            **p,
            "execute": False,
            "hint": "Dry-run. Pass execute=true to actually reclaim.",
        }

    q = _build_filter()
    now = datetime.now(timezone.utc).isoformat()

    projection = {"_id": 0, "id": 1, "doc_type": 1, "status": 1,
                  "workflow_status": 1, "batch_parent_id": 1}
    cursor = db.hub_documents.find(q, projection)
    if limit:
        cursor = cursor.limit(int(limit))

    reclaimed: List[str] = []
    errors: List[Dict[str, Any]] = []
    async for doc in cursor:
        doc_id = doc.get("id")
        if not doc_id:
            continue
        try:
            update = {
                "$set": {
                    "status": "NeedsReview",
                    "workflow_status": "needs_review",
                    "square9_stage": "needs_review",
                    "queue_visible": True,
                    "reclaim_to_needs_review_at": now,
                    "reclaim_reason": (
                        "v2.5.5 reclaim: doc was auto-cleared before the "
                        "v2.5.3 unclassified_guard existed; restoring to "
                        "NeedsReview for human review."
                    ),
                    "reclaim_actor": actor,
                    "updated_utc": now,
                },
                "$push": {
                    "workflow_history": {
                        "timestamp": now,
                        "from_status": doc.get("status"),
                        "to_status": "NeedsReview",
                        "event": "reclaim_to_needs_review",
                        "actor": actor,
                        "reason": "v2.5.5 reclaim — unclassified auto-cleared doc",
                    },
                },
            }
            r = await db.hub_documents.update_one({"id": doc_id}, update)
            if r.modified_count:
                reclaimed.append(doc_id)
        except Exception as e:  # noqa: BLE001 — one failure must not abort run
            logger.warning("[UnknownDocReclaim] doc %s failed: %s", doc_id, e)
            errors.append({"doc_id": doc_id, "error": str(e)})

    result = {
        "generated_at": now,
        "execute": True,
        "actor": actor,
        "limit_applied": limit,
        "reclaimed_count": len(reclaimed),
        "reclaimed_ids": reclaimed[:50],  # cap payload
        "errors_count": len(errors),
        "errors": errors[:20],
    }

    # Audit log
    try:
        await db.unknown_doc_reclaim_runs.insert_one({**result, "ran_at": now})
    except Exception as e:  # noqa: BLE001
        logger.debug("[UnknownDocReclaim] audit insert failed: %s", e)

    logger.info(
        "[UnknownDocReclaim] actor=%s reclaimed=%d errors=%d limit=%s",
        actor, len(reclaimed), len(errors), limit,
    )
    return result


async def recent_runs(limit: int = 20, db=None) -> List[Dict[str, Any]]:
    db = db if db is not None else get_db()
    return await db.unknown_doc_reclaim_runs.find(
        {}, {"_id": 0},
    ).sort("ran_at", -1).limit(limit).to_list(limit)


__all__ = ["preview", "run", "recent_runs", "UNKNOWN_DOC_TYPES"]
