"""
Dedup Router — Find and mark duplicate documents.

Groups documents by sha256_hash, keeps the "best" copy (most processed),
and marks the rest as is_duplicate=True so they're excluded from queue counts.

Endpoints:
  POST /api/dedup/dry-run   — Preview duplicate groups and what would be marked
  POST /api/dedup/run       — Mark duplicates
  GET  /api/dedup/stats     — Quick duplicate summary
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from deps import get_db

logger = logging.getLogger("dedup")
router = APIRouter(prefix="/dedup", tags=["Dedup"])

# Priority: higher = keep this copy over others
_STATUS_PRIORITY = {
    "Completed": 100, "Posted": 95, "Archived": 90,
    "StoredInSP": 80, "ReadyToLink": 75, "LinkedToBC": 75,
    "ValidationPassed": 70, "Validated": 70,
    "NeedsReview": 50, "Classified": 40,
    "Received": 10, "captured": 5,
}


def _doc_score(doc: dict) -> int:
    """Score a document — higher means more processed / more valuable."""
    score = _STATUS_PRIORITY.get(doc.get("status", ""), 0)
    if doc.get("auto_cleared"):
        score += 50
    if doc.get("vendor_canonical"):
        score += 20
    if doc.get("extracted_fields"):
        score += 10
    if doc.get("validation_results"):
        score += 10
    if doc.get("bc_record_id"):
        score += 30
    return score


@router.get("/stats")
async def dedup_stats():
    """Quick summary of duplicate groups."""
    db = get_db()

    pipeline = [
        {"$match": {"is_duplicate": {"$ne": True}}},
        {"$group": {
            "_id": "$sha256_hash",
            "count": {"$sum": 1},
            "sample_name": {"$first": "$file_name"},
        }},
        {"$match": {"count": {"$gt": 1}, "_id": {"$ne": None}}},
        {"$sort": {"count": -1}},
        {"$limit": 50},
    ]
    groups = await db.hub_documents.aggregate(pipeline).to_list(50)

    total_dupes = sum(g["count"] - 1 for g in groups)
    return {
        "duplicate_groups": len(groups),
        "total_extra_copies": total_dupes,
        "top_groups": [
            {"hash": g["_id"][:12], "copies": g["count"], "file": g["sample_name"]}
            for g in groups[:20]
        ],
    }


@router.post("/dry-run")
async def dry_run():
    """Preview what would be marked as duplicate."""
    db = get_db()

    pipeline = [
        {"$match": {"is_duplicate": {"$ne": True}, "sha256_hash": {"$ne": None}}},
        {"$group": {
            "_id": "$sha256_hash",
            "count": {"$sum": 1},
            "doc_ids": {"$push": "$id"},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]
    groups = await db.hub_documents.aggregate(pipeline).to_list(5000)

    would_mark = 0
    by_status = {}

    for group in groups:
        doc_ids = group["doc_ids"]
        docs = await db.hub_documents.find(
            {"id": {"$in": doc_ids}},
            {"_id": 0, "id": 1, "status": 1, "auto_cleared": 1,
             "vendor_canonical": 1, "extracted_fields": 1,
             "validation_results": 1, "bc_record_id": 1, "file_name": 1},
        ).to_list(len(doc_ids))

        # Sort by score descending — keep the best one
        docs.sort(key=_doc_score, reverse=True)

        for dup_doc in docs[1:]:  # All except the best
            would_mark += 1
            s = dup_doc.get("status", "unknown")
            by_status.setdefault(s, 0)
            by_status[s] += 1

    return {
        "duplicate_groups": len(groups),
        "would_mark_as_duplicate": would_mark,
        "by_status": by_status,
    }


@router.post("/run")
async def run_dedup():
    """Mark duplicate documents (keeps the best copy per hash group)."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    pipeline = [
        {"$match": {"is_duplicate": {"$ne": True}, "sha256_hash": {"$ne": None}}},
        {"$group": {
            "_id": "$sha256_hash",
            "count": {"$sum": 1},
            "doc_ids": {"$push": "$id"},
        }},
        {"$match": {"count": {"$gt": 1}}},
    ]
    groups = await db.hub_documents.aggregate(pipeline).to_list(5000)

    marked = 0
    kept = 0

    for group in groups:
        doc_ids = group["doc_ids"]
        docs = await db.hub_documents.find(
            {"id": {"$in": doc_ids}},
            {"_id": 0, "id": 1, "status": 1, "auto_cleared": 1,
             "vendor_canonical": 1, "extracted_fields": 1,
             "validation_results": 1, "bc_record_id": 1},
        ).to_list(len(doc_ids))

        docs.sort(key=_doc_score, reverse=True)
        kept += 1  # Keep the best one

        dup_ids = [d["id"] for d in docs[1:]]
        if dup_ids:
            await db.hub_documents.update_many(
                {"id": {"$in": dup_ids}},
                {"$set": {
                    "is_duplicate": True,
                    "duplicate_of": docs[0]["id"],
                    "duplicate_marked_utc": now,
                    "status": "Duplicate",
                    "workflow_status": "duplicate",
                }},
            )
            marked += len(dup_ids)

    return {
        "duplicate_groups": len(groups),
        "kept": kept,
        "marked_as_duplicate": marked,
        "timestamp": now,
    }
