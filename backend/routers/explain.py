"""
GPI Document Hub - Document Decision Explainer Route

GET /api/documents/{document_id}/explain
Returns a plain-English explanation of why a document is in its current status.
"""

import logging
from fastapi import APIRouter, HTTPException, Header
from pydantic import BaseModel
from typing import List, Optional
from bson import ObjectId
from deps import get_db
from services.decision_explainer_service import explain_document_status

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/documents", tags=["Documents"])


def _verify_token(authorization: Optional[str]) -> str:
    """Minimal JWT verification matching the existing auth.py pattern."""
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        import jwt as pyjwt
        import os
        secret = os.environ.get("JWT_SECRET", "gpi-hub-secret-key")
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("sub", "unknown")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@router.get("/{document_id}/explain")
async def explain_document(
    document_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return a plain-English explanation of a document's current workflow state."""
    _verify_token(authorization)

    db = get_db()

    # Try string id first (the convention used everywhere)
    doc = await db.hub_documents.find_one({"id": document_id}, {"_id": 0})

    # Fallback: try as ObjectId
    if doc is None:
        try:
            doc = await db.hub_documents.find_one({"_id": ObjectId(document_id)}, {"_id": 0})
        except Exception:
            pass

    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    result = await explain_document_status(doc)
    return result.to_dict()


@router.get("/{document_id}/sales-order-explainer")
async def explain_sales_order(
    document_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return a plain-English explanation of a sales order's readiness status."""
    _verify_token(authorization)

    db = get_db()
    doc = await db.hub_documents.find_one({"id": document_id}, {"_id": 0})
    if doc is None:
        try:
            doc = await db.hub_documents.find_one({"_id": ObjectId(document_id)}, {"_id": 0})
        except Exception:
            pass
    if doc is None:
        raise HTTPException(status_code=404, detail="Document not found")

    from services.sales_order_decision_explainer import explain_sales_order_decision
    result = await explain_sales_order_decision(doc, db=db)
    return result.to_dict()


class SOReviewFeedbackBody(BaseModel):
    reviewer_assessment: str
    final_human_decision: Optional[str] = None
    disagreed_fields: Optional[List[str]] = None
    notes: Optional[str] = None


@router.post("/{document_id}/sales-order-review-feedback")
async def submit_so_review_feedback(
    document_id: str,
    body: SOReviewFeedbackBody,
    authorization: Optional[str] = Header(None),
):
    """Submit reviewer feedback on a sales order advisory review. Changes nothing about the document's status."""
    user = _verify_token(authorization)
    db = get_db()

    from services.sales_order_reviewer_feedback_service import submit_feedback
    result = await submit_feedback(
        db=db,
        document_id=document_id,
        reviewer_user_id=user,
        reviewer_assessment=body.reviewer_assessment,
        final_human_decision=body.final_human_decision,
        disagreed_fields=body.disagreed_fields,
        notes=body.notes,
    )

    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/{document_id}/sales-order-review-feedback")
async def get_so_review_feedback(
    document_id: str,
    authorization: Optional[str] = Header(None),
):
    """Get all feedback records for a document's SO advisory review."""
    _verify_token(authorization)
    db = get_db()

    from services.sales_order_reviewer_feedback_service import get_feedback_for_document
    records = await get_feedback_for_document(db, document_id)
    return {"document_id": document_id, "feedback": records, "total": len(records)}
