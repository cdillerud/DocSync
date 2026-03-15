"""
GPI Document Hub - Document Intelligence Router

Exposes the document intelligence pipeline as a coherent API:
  POST /api/document-intelligence/process/{doc_id}
  GET  /api/document-intelligence/review-queue
  GET  /api/document-intelligence/{doc_id}
  PATCH /api/document-intelligence/{doc_id}
  GET  /api/document-intelligence/summary
"""

import logging
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.document_intelligence_service import (
    process_document,
    get_intelligence_result,
    get_review_queue,
    apply_correction,
    get_intelligence_summary,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/document-intelligence", tags=["Document Intelligence"])


# ── Request/Response Models ──────────────────────────────────────────────────

class CorrectionRequest(BaseModel):
    corrected_type: Optional[str] = None
    corrected_fields: Optional[Dict[str, Any]] = None
    corrected_by: str = "admin"
    notes: str = ""


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/process/{doc_id}")
async def api_process_document(doc_id: str):
    """
    Run the full document intelligence pipeline on a document.
    Classify → Extract → Validate → Derive Automation Readiness → Store.
    Can be called multiple times to re-process.
    """
    try:
        result = await process_document(doc_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Document intelligence processing failed for %s: %s", doc_id, e)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.get("/review-queue")
async def api_get_review_queue(
    status: Optional[str] = Query(None, description="Filter: needs_review, blocked, ready"),
    doc_type: Optional[str] = Query(None, description="Filter by document type"),
    sort_by: str = Query("readiness_score", description="Sort field"),
    sort_order: int = Query(1, description="1=asc, -1=desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Get documents requiring human review.
    Returns items with automation_readiness = needs_review or blocked.
    """
    return await get_review_queue(
        status_filter=status,
        doc_type_filter=doc_type,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )


@router.get("/summary")
async def api_get_summary():
    """Get summary statistics for the intelligence pipeline."""
    return await get_intelligence_summary()


@router.get("/{doc_id}")
async def api_get_intelligence(doc_id: str):
    """Get the latest intelligence result for a document."""
    result = await get_intelligence_result(doc_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"No intelligence result for document: {doc_id}")
    return result


@router.patch("/{doc_id}")
async def api_correct_intelligence(doc_id: str, body: CorrectionRequest):
    """
    Apply manual corrections to classification and/or extracted fields.
    Re-derives automation readiness after correction.
    """
    try:
        result = await apply_correction(
            doc_id=doc_id,
            corrected_type=body.corrected_type,
            corrected_fields=body.corrected_fields,
            corrected_by=body.corrected_by,
            correction_notes=body.notes,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Correction failed for %s: %s", doc_id, e)
        raise HTTPException(status_code=500, detail=f"Correction failed: {str(e)}")
