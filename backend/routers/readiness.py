"""
GPI Document Hub - Readiness Router

Endpoints:
  GET /api/readiness/metrics       - Readiness analytics
  GET /api/readiness/queue         - Filterable readiness queue
  POST /api/readiness/evaluate/{id} - Evaluate single document
  POST /api/readiness/batch        - Batch evaluate documents
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

router = APIRouter(prefix="/readiness", tags=["Readiness"])


@router.get("/metrics")
async def get_readiness_metrics():
    """Get readiness analytics: counts by status/action, top reasons, trends."""
    from services.document_readiness_service import get_readiness_metrics as _get
    return await _get()


@router.get("/queue")
async def get_readiness_queue(
    status: Optional[str] = Query(None, description="Filter: ready_auto_draft|ready_auto_link|needs_review|blocked|ambiguous"),
    action: Optional[str] = Query(None, description="Filter: auto_draft|auto_link|review|hold"),
    reason: Optional[str] = Query(None, description="Filter by blocking or warning reason"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    """Get documents filtered by readiness status for review queues."""
    from services.document_readiness_service import get_readiness_queue as _get
    return await _get(status=status, action=action, reason=reason, limit=limit, skip=skip)


@router.post("/evaluate/{doc_id}")
async def evaluate_document_readiness(doc_id: str):
    """Evaluate and persist readiness for a single document."""
    from services.document_readiness_service import evaluate_and_persist
    try:
        result = await evaluate_and_persist(doc_id)
        return {"success": True, "doc_id": doc_id, "readiness": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/batch")
async def batch_evaluate_readiness(limit: int = Query(200, ge=1, le=1000)):
    """Evaluate readiness for all documents that don't have it yet."""
    from services.document_readiness_service import batch_evaluate
    return await batch_evaluate(limit=limit)


@router.post("/reevaluate-all")
async def reevaluate_all_readiness(limit: int = Query(5000, ge=1, le=10000)):
    """
    Re-evaluate ALL documents — finds and fixes signal contradictions.
    Every correction feeds into the learning pipeline.
    Returns: status transitions, signal corrections, per-vendor breakdown.
    """
    from services.document_readiness_service import batch_reevaluate_all
    return await batch_reevaluate_all(limit=limit)
