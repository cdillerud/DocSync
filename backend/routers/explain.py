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


@router.get("/{document_id}/sales-order-advisory")
async def get_sales_order_advisory(
    document_id: str,
    authorization: Optional[str] = Header(None),
):
    """
    Consolidated SO advisory endpoint: combines readiness review,
    explainer, customer profile context, and reviewer feedback
    into a single response for the unified panel.
    """
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

    # 1. Explainer
    from services.sales_order_decision_explainer import explain_sales_order_decision
    explainer = (await explain_sales_order_decision(doc, db=db)).to_dict()

    # 2. Raw readiness review (from document)
    review = doc.get("so_readiness_review") or {}

    # If no review exists for a pilot sales doc, run it on-demand
    is_sales_type = doc.get("doc_type") in ("Sales_Order", "SalesOrder", "SALES_ORDER", "SALES_INVOICE", "SalesInvoice")
    is_pilot = doc.get("inside_sales_pilot", False)
    if (not review or review.get("error")) and is_sales_type and is_pilot:
        try:
            from services.pilot_readiness_review_service import review_pilot_document
            review = await review_pilot_document(document_id)
        except Exception:
            pass

    # 3. Customer profile summary — use unified resolution service
    from services.entity_resolution_service import resolve_customer
    cr = await resolve_customer(doc)
    customer_no = cr.customer_no

    # Also try pilot readiness review context
    if not customer_no and review:
        pc = review.get("pilot_context") or {}
        if pc.get("profile_customer_no"):
            customer_no = pc["profile_customer_no"]

    profile_summary = None
    if customer_no:
        profile = await db.customer_posting_profiles.find_one(
            {"customer_no": customer_no, "status": "analyzed"}, {"_id": 0}
        )
        if profile:
            profile_summary = {
                "customer_no": profile.get("customer_no"),
                "customer_name": profile.get("customer_name"),
                "template_confidence": profile.get("template_confidence"),
                "invoices_analyzed": profile.get("invoices_analyzed"),
                "typical_order_value": profile.get("typical_order_value"),
                "amount_range": profile.get("amount_range"),
                "common_items_count": len(profile.get("common_items", [])),
                "top_items": profile.get("common_items", [])[:5],
            }

    # 4. Feedback
    from services.sales_order_reviewer_feedback_service import get_feedback_for_document
    feedback_records = await get_feedback_for_document(db, document_id)

    # 5. Confidence calibration (run on-demand if review exists)
    calibration = None
    if review and not review.get("error"):
        existing_cal = doc.get("so_confidence_calibration")
        if existing_cal and not existing_cal.get("error"):
            calibration = existing_cal
        else:
            from services.sales_order_confidence_calibration_service import calibrate_confidence as _calibrate
            profile_for_cal = None
            if customer_no:
                profile_for_cal = await db.customer_posting_profiles.find_one(
                    {"customer_no": customer_no, "status": "analyzed"}, {"_id": 0}
                )
            cal_result = _calibrate(review, profile_for_cal)
            calibration = cal_result.to_dict()

    return {
        "document_id": document_id,
        "has_review": bool(review and not review.get("error")),
        "has_profile": profile_summary is not None,
        "has_feedback": len(feedback_records) > 0,
        "has_calibration": calibration is not None,
        "explainer": explainer,
        "review": {
            "readiness_status": review.get("readiness_status"),
            "confidence": review.get("confidence"),
            "blocking_issues": review.get("blocking_issues", []),
            "warnings": review.get("warnings", []),
            "unusual_patterns": review.get("unusual_patterns", []),
            "profile_matches": review.get("profile_matches", []),
            "model_used": review.get("model_used"),
            "reviewed_at": review.get("reviewed_at"),
            "profile_state": review.get("profile_state"),
            "ship_to_analysis": review.get("ship_to_analysis"),
            "item_uom_analysis": review.get("item_uom_analysis"),
        } if review else None,
        "calibration": calibration,
        "customer_profile": profile_summary,
        "feedback": feedback_records,
    }


@router.get("/sales-orders/draft-context/{customer_id}")
async def get_so_draft_context(
    customer_id: str,
    authorization: Optional[str] = Header(None),
):
    """Return profile-based draft-assist context for SO creation."""
    _verify_token(authorization)
    db = get_db()

    from services.sales_order_draft_context_service import get_draft_context
    return await get_draft_context(db, customer_id)
