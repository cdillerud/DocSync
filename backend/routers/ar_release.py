"""
AR Release Gate Router — Prepay & Terms Approval endpoints

Endpoints:
  GET  /api/ar-release/metrics           — Aggregate gate metrics
  POST /api/ar-release/evaluate/{doc_id} — Evaluate (or re-evaluate) a document
  POST /api/ar-release/override/{doc_id} — Manual human override of a held document
  GET  /api/ar-release/queue             — Documents currently held by the gate
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional

from deps import get_db
from services.ar_release_gate_service import (
    evaluate_and_store,
    override_gate,
    get_ar_release_metrics,
)

router = APIRouter(prefix="/ar-release", tags=["AR Release Gate"])


class OverrideRequest(BaseModel):
    approved_by: str
    notes: Optional[str] = ""


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

@router.get("/metrics")
async def ar_release_metrics():
    db = get_db()
    return await get_ar_release_metrics(db)


# ---------------------------------------------------------------------------
# Evaluate
# ---------------------------------------------------------------------------

@router.post("/evaluate/{document_id}")
async def evaluate_document(document_id: str):
    db = get_db()
    result = await evaluate_and_store(document_id, db)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# Override (Human approval)
# ---------------------------------------------------------------------------

@router.post("/override/{document_id}")
async def override_document(document_id: str, body: OverrideRequest):
    db = get_db()
    result = await override_gate(document_id, db, body.approved_by, body.notes)
    if "error" in result:
        raise HTTPException(status_code=404, detail=result["error"])
    return result


# ---------------------------------------------------------------------------
# Held queue
# ---------------------------------------------------------------------------

@router.get("/queue")
async def ar_held_queue(
    limit: int = Query(50, ge=1, le=200),
    status: str = Query("held", regex="^(held|released|override|all)$"),
):
    db = get_db()
    match_filter = {"ar_release_gate": {"$exists": True}}
    if status != "all":
        match_filter["ar_release_gate.status"] = status

    cursor = db.hub_documents.find(
        match_filter,
        {
            "_id": 0,
            "id": 1,
            "file_name": 1,
            "doc_type": 1,
            "suggested_job_type": 1,
            "customer_matched_name": 1,
            "total_amount": 1,
            "ar_release_gate": 1,
            "created_at": 1,
            "created_utc": 1,
        },
    ).sort("created_utc", -1).limit(limit)

    docs = await cursor.to_list(limit)
    return {"total": len(docs), "status_filter": status, "documents": docs}
