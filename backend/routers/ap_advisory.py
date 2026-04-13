"""
GPI Document Hub — AP Invoice Advisory Routes

Endpoints for the AP vendor advisory workflow: review, explain,
feedback, and consolidated advisory view.
"""

import os
import logging
from fastapi import APIRouter, HTTPException, Header, Query
from pydantic import BaseModel
from typing import Dict, List, Optional
from bson import ObjectId
from deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ap-advisory", tags=["AP Advisory"])


def _verify_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(status_code=401, detail="Missing or invalid Authorization header")
    token = authorization.split(" ", 1)[1]
    try:
        import jwt as pyjwt
        secret = os.environ.get("JWT_SECRET", "gpi-hub-secret-key")
        payload = pyjwt.decode(token, secret, algorithms=["HS256"])
        return payload.get("sub", "unknown")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


# =============================================================================
# Advisory Review (on-demand for a document)
# =============================================================================

@router.post("/review/{document_id}")
async def review_ap_document(
    document_id: str,
    authorization: Optional[str] = Header(None),
):
    """Run AP advisory review on a document. Stores result, returns it."""
    _verify_token(authorization)
    db = get_db()

    doc = await db.hub_documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_canonical") or ""
    vendor_profile = None
    if vendor_no:
        vendor_profile = await db.vendor_invoice_profiles.find_one(
            {"vendor_no": vendor_no}, {"_id": 0}
        )

    from services.ap_invoice_advisory_reviewer import review_ap_invoice_readiness
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}

    result = await review_ap_invoice_readiness(
        extracted_invoice={
            "vendor_name": doc.get("vendor_raw") or ef.get("vendor"),
            "vendor_number": vendor_no,
            "invoice_number": doc.get("invoice_number_clean") or ef.get("invoice_number"),
            "invoice_date": nf.get("invoice_date") or ef.get("invoice_date"),
            "due_date": ef.get("due_date"),
            "total_amount": doc.get("amount_float") or ef.get("amount"),
            "po_number": doc.get("po_number_clean") or ef.get("po_number"),
            "line_items": nf.get("line_items") or ef.get("line_items") or [],
        },
        vendor_profile=vendor_profile,
        validation_results=doc.get("validation_results"),
        document_context={"doc_id": document_id, "doc_type": doc.get("doc_type"), "file_name": doc.get("file_name")},
    )

    await db.hub_documents.update_one(
        {"id": document_id}, {"$set": {"ap_advisory_review": result.to_dict()}}
    )

    return result.to_dict()


# =============================================================================
# Explainer
# =============================================================================

@router.get("/explain/{document_id}")
async def explain_ap_document(
    document_id: str,
    authorization: Optional[str] = Header(None),
):
    """Plain-English explanation of AP advisory result."""
    _verify_token(authorization)
    db = get_db()

    doc = await db.hub_documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    from services.ap_invoice_decision_explainer import explain_ap_invoice_decision
    result = await explain_ap_invoice_decision(doc, db=db)
    return result.to_dict()


# =============================================================================
# Consolidated Advisory (review + explain + profile + feedback)
# =============================================================================

@router.get("/advisory/{document_id}")
async def get_ap_advisory(
    document_id: str,
    authorization: Optional[str] = Header(None),
):
    """Consolidated AP advisory: review + explainer + vendor profile + feedback."""
    _verify_token(authorization)
    db = get_db()

    doc = await db.hub_documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    review = doc.get("ap_advisory_review") or {}

    # Explainer
    from services.ap_invoice_decision_explainer import explain_ap_invoice_decision
    explainer = (await explain_ap_invoice_decision(doc, db=db)).to_dict()

    # Vendor profile summary
    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_canonical") or ""
    profile_summary = None
    if vendor_no:
        vp = await db.vendor_invoice_profiles.find_one({"vendor_no": vendor_no}, {"_id": 0})
        if vp:
            amt = vp.get("amount_stats") or {}
            profile_summary = {
                "vendor_no": vp.get("vendor_no"),
                "vendor_name": vp.get("vendor_name", ""),
                "bc_invoice_count": vp.get("bc_invoice_count", 0),
                "posting_confidence": vp.get("posting_confidence", vp.get("template_confidence")),
                "default_item_code": vp.get("default_item_code"),
                "description_pattern": vp.get("description_pattern"),
                "amount_avg": amt.get("mean"),
                "amount_min": amt.get("min"),
                "amount_max": amt.get("max"),
            }

    # Feedback
    from services.ap_invoice_feedback_service import get_ap_feedback
    feedback = await get_ap_feedback(db, document_id)

    return {
        "document_id": document_id,
        "has_review": bool(review and not review.get("error")),
        "has_profile": profile_summary is not None,
        "has_feedback": len(feedback) > 0,
        "explainer": explainer,
        "review": review if review else None,
        "vendor_profile": profile_summary,
        "feedback": feedback,
    }


# =============================================================================
# Feedback
# =============================================================================

class APFeedbackBody(BaseModel):
    reviewer_assessment: str
    final_human_decision: Optional[str] = None
    disagreed_fields: Optional[List[str]] = None
    notes: Optional[str] = None


@router.post("/feedback/{document_id}")
async def submit_ap_feedback(
    document_id: str,
    body: APFeedbackBody,
    authorization: Optional[str] = Header(None),
):
    """Submit feedback on an AP advisory review."""
    user = _verify_token(authorization)
    db = get_db()

    from services.ap_invoice_feedback_service import submit_ap_feedback as _submit
    result = await _submit(
        db, document_id, user,
        body.reviewer_assessment, body.final_human_decision,
        body.disagreed_fields, body.notes,
    )
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/feedback/{document_id}")
async def get_feedback(
    document_id: str,
    authorization: Optional[str] = Header(None),
):
    """Get feedback for an AP document."""
    _verify_token(authorization)
    db = get_db()

    from services.ap_invoice_feedback_service import get_ap_feedback
    records = await get_ap_feedback(db, document_id)
    return {"document_id": document_id, "feedback": records, "total": len(records)}


@router.get("/feedback-summary")
async def feedback_summary():
    """AP advisory feedback analytics summary."""
    db = get_db()

    from services.ap_invoice_feedback_service import get_ap_feedback_summary
    return await get_ap_feedback_summary(db)


# =============================================================================
# Phase 2: Diagnostics, Calibration, Learning Suggestions
# =============================================================================

@router.get("/diagnostics")
async def ap_disagreement_diagnostics(
    date_from: str = Query(None), date_to: str = Query(None),
    vendor_no: str = Query(None), assessment: str = Query(None),
    root_cause: str = Query(None),
):
    """AP disagreement root-cause diagnostics."""
    db = get_db()
    from services.ap_invoice_disagreement_diagnostics_service import run_ap_disagreement_diagnostics
    return await run_ap_disagreement_diagnostics(
        db, date_from=date_from, date_to=date_to,
        vendor_no=vendor_no, assessment=assessment, root_cause=root_cause,
    )


@router.post("/calibrate/{document_id}")
async def calibrate_ap_document(
    document_id: str,
    authorization: Optional[str] = Header(None),
):
    """Run confidence calibration on a single AP document."""
    _verify_token(authorization)
    db = get_db()
    from services.ap_invoice_confidence_calibration_service import calibrate_ap_document as _cal
    result = await _cal(db, document_id)
    if result.error:
        raise HTTPException(status_code=404, detail=result.error)
    return result.to_dict()


@router.post("/generate-suggestions")
async def generate_ap_suggestions(
    vendor_no: str = Query(None),
    limit: int = Query(50, ge=1, le=500),
    sync: bool = Query(True),
):
    """Generate AP learning suggestions from reviewer feedback."""
    db = get_db()
    from services.ap_invoice_feedback_learning_service import generate_ap_learning_suggestions
    return await generate_ap_learning_suggestions(db, vendor_no=vendor_no, limit=limit)


@router.get("/suggestions")
async def list_ap_suggestions(
    vendor_no: str = Query(None),
    suggestion_type: str = Query(None),
    status: str = Query(None),
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    """List AP learning suggestions with filters."""
    db = get_db()
    from services.ap_invoice_feedback_learning_service import get_ap_suggestions
    return await get_ap_suggestions(
        db, vendor_no=vendor_no, suggestion_type=suggestion_type,
        status=status, limit=limit, skip=skip,
    )


# =============================================================================
# Phase 3: Suggestion Approve/Reject/Apply, Impact Review, Drift, Hotspots
# =============================================================================

@router.post("/suggestions/{suggestion_id}/approve")
async def approve_ap_suggestion_endpoint(
    suggestion_id: str,
    authorization: Optional[str] = Header(None),
):
    """Approve an AP learning suggestion."""
    user = _verify_token(authorization)
    db = get_db()
    from services.ap_invoice_learning_suggestion_apply_service import approve_ap_suggestion
    result = await approve_ap_suggestion(db, suggestion_id, user)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/suggestions/{suggestion_id}/reject")
async def reject_ap_suggestion_endpoint(
    suggestion_id: str,
    authorization: Optional[str] = Header(None),
):
    """Reject an AP learning suggestion."""
    user = _verify_token(authorization)
    db = get_db()
    from services.ap_invoice_learning_suggestion_apply_service import reject_ap_suggestion
    result = await reject_ap_suggestion(db, suggestion_id, user)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.post("/suggestions/{suggestion_id}/apply")
async def apply_ap_suggestion_endpoint(
    suggestion_id: str,
    authorization: Optional[str] = Header(None),
):
    """Apply an approved AP learning suggestion to the vendor profile."""
    user = _verify_token(authorization)
    db = get_db()
    from services.ap_invoice_learning_suggestion_apply_service import apply_ap_suggestion
    result = await apply_ap_suggestion(db, suggestion_id, user)
    if result.get("error"):
        raise HTTPException(status_code=422, detail=result["error"])
    return result


@router.get("/learning-impact-review")
async def ap_learning_impact_review(
    date_from: str = Query(None), date_to: str = Query(None),
    vendor_no: str = Query(None), suggestion_type: str = Query(None),
    applied_by: str = Query(None),
):
    """AP learning impact review — pre/post apply outcomes."""
    db = get_db()
    from services.ap_invoice_learning_impact_review_service import run_ap_learning_impact_review
    return await run_ap_learning_impact_review(
        db, date_from=date_from, date_to=date_to,
        vendor_no=vendor_no, suggestion_type=suggestion_type, applied_by=applied_by,
    )


@router.get("/learning-impact-review/details")
async def ap_learning_impact_details(
    vendor_no: str = Query(None), suggestion_type: str = Query(None),
    limit: int = Query(50, ge=1, le=500), skip: int = Query(0, ge=0),
):
    """Per-suggestion impact detail records for AP."""
    db = get_db()
    from services.ap_invoice_learning_impact_review_service import get_ap_impact_details
    return await get_ap_impact_details(db, limit=limit, skip=skip, vendor_no=vendor_no, suggestion_type=suggestion_type)


@router.get("/profile-drift")
async def ap_profile_drift(
    date_from: str = Query(None), date_to: str = Query(None),
    vendor_no: str = Query(None), drift_risk: str = Query(None),
    suggestion_type: str = Query(None), applied_by: str = Query(None),
):
    """Vendor profile drift summary for AP."""
    db = get_db()
    from services.ap_invoice_profile_drift_service import get_ap_profile_drift_summary
    return await get_ap_profile_drift_summary(
        db, date_from=date_from, date_to=date_to, vendor_no=vendor_no,
        drift_risk=drift_risk, suggestion_type=suggestion_type, applied_by=applied_by,
    )


@router.get("/profile-drift/{vendor_no}")
async def ap_vendor_drift_detail(vendor_no: str):
    """Detailed drift analysis for one AP vendor."""
    db = get_db()
    from services.ap_invoice_profile_drift_service import get_ap_vendor_drift_detail
    return await get_ap_vendor_drift_detail(db, vendor_no)


@router.get("/profile-change-history/{vendor_no}")
async def ap_change_history(vendor_no: str, limit: int = Query(50, ge=1, le=200)):
    """Full change history with pre/post snapshots for an AP vendor."""
    db = get_db()
    from services.ap_invoice_profile_drift_service import get_ap_change_history
    return await get_ap_change_history(db, vendor_no, limit=limit)


@router.get("/vendor-hotspots")
async def ap_vendor_hotspots(
    date_from: str = Query(None), date_to: str = Query(None),
    severity: str = Query(None), root_cause: str = Query(None),
    vendor_no: str = Query(None), limit: int = Query(30, ge=1, le=100),
):
    """AP vendor hotspots — friction ranking and root-cause diagnosis."""
    db = get_db()
    from services.ap_invoice_vendor_hotspot_review_service import get_ap_vendor_hotspots
    return await get_ap_vendor_hotspots(
        db, date_from=date_from, date_to=date_to,
        severity=severity, root_cause=root_cause, vendor_no=vendor_no, limit=limit,
    )


@router.get("/vendor-hotspots/{vendor_no}")
async def ap_vendor_hotspot_detail(vendor_no: str):
    """Detailed hotspot analysis for one AP vendor."""
    db = get_db()
    from services.ap_invoice_vendor_hotspot_review_service import get_ap_vendor_hotspot_detail
    return await get_ap_vendor_hotspot_detail(db, vendor_no)
