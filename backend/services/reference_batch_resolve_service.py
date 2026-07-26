"""
Batch reference-intelligence auto-resolution orchestration.

This is the authoritative route-facing implementation for enqueueing
documents through the auto-resolution service.
"""

from fastapi import HTTPException, Query

from database import db
from services.auto_resolution_service import (
    get_auto_resolve_service,
)


async def batch_auto_resolve(
    limit: int = Query(50, le=500),
    status_filter: str = Query("NeedsReview"),
):
    """Batch enqueue pending documents for full auto-resolution (ref intel + PO resolution)."""
    svc = get_auto_resolve_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Auto-resolution service not initialized")

    query = {}
    if status_filter == "NeedsReview":
        query["status"] = "NeedsReview"
    elif status_filter == "not_run":
        query["reference_intelligence_status"] = {"$in": [None, "not_run"]}

    docs = await db.hub_documents.find(query, {"id": 1, "_id": 0}).limit(limit).to_list(limit)
    enqueued = 0
    for doc in docs:
        doc_id = doc["id"]
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {"reference_intelligence_status": "not_run"}}
        )
        await svc.enqueue(doc_id)
        enqueued += 1

    return {"status": "batch_queued", "enqueued": enqueued, "filter": status_filter}

__all__ = ["batch_auto_resolve"]
