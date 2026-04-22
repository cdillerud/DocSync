"""
GPI Document Hub - AP Review Routes

API endpoints for AP Invoice review workflow:
- Vendor search
- PO search  
- Save AP review edits
- Post to Business Central
- AI-powered invoice data extraction
"""

import os
import logging
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, Depends

from services.auth_deps import get_current_user
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Create router
ap_review_router = APIRouter(prefix="/ap-review", tags=["AP Review"])

# Upload directory for document files
UPLOAD_DIR = os.path.join(os.path.dirname(os.path.dirname(__file__)), "uploads")


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class APReviewData(BaseModel):
    """Data for saving AP review edits."""
    vendor_id: Optional[str] = None
    vendor_name_resolved: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = "USD"
    total_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    po_number: Optional[str] = None
    line_items: Optional[List[dict]] = None
    notes: Optional[str] = None
    document_type: Optional[str] = None
    bc_document_no: Optional[str] = None


class PostToBCRequest(BaseModel):
    """Request to post document to BC."""
    vendor_id: str
    vendor_number: Optional[str] = None
    invoice_number: str
    invoice_date: str
    due_date: Optional[str] = None
    currency: str = "USD"
    total_amount: float
    line_items: Optional[List[dict]] = None


class PostToBCResponse(BaseModel):
    """Response from posting to BC."""
    success: bool
    bc_document_id: Optional[str] = None
    bc_document_number: Optional[str] = None
    bc_posting_status: str
    message: str
    error: Optional[str] = None
    # Link writeback status
    sharepoint_url: Optional[str] = None
    bc_link_writeback_status: Optional[str] = None  # "success", "failed", "skipped"
    bc_link_writeback_error: Optional[str] = None


# =============================================================================
# DEPENDENCIES
# =============================================================================

from deps import get_db
from services.business_central_service import get_bc_service


# =============================================================================
# VENDOR SEARCH ENDPOINTS
# =============================================================================

@ap_review_router.get("/vendors")
async def search_vendors(
    q: Optional[str] = Query(None, description="Search text for vendor name/number"),
    limit: int = Query(50, description="Max results to return")
):
    """
    Search vendors from Business Central.
    Returns list of vendors matching the search criteria.
    """
    try:
        service = get_bc_service()
        result = await service.get_vendors(filter_text=q, limit=limit)
        return {
            "vendors": result.get("vendors", []),
            "total": result.get("total", 0),
            "mock": result.get("mock", False)
        }
    except Exception as e:
        logger.error("Vendor search failed: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Vendor search failed: {str(e)}")


@ap_review_router.get("/vendors/{vendor_id}")
async def get_vendor(vendor_id: str):
    """Get a specific vendor by ID or number."""
    try:
        service = get_bc_service()
        vendor = await service.get_vendor_by_id(vendor_id)
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return vendor
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Get vendor failed: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Get vendor failed: {str(e)}")


# =============================================================================
# PURCHASE ORDER SEARCH ENDPOINTS
# =============================================================================

@ap_review_router.get("/purchase-orders")
async def search_purchase_orders(
    vendor_id: Optional[str] = Query(None, description="Filter by vendor ID/number"),
    limit: int = Query(50, description="Max results to return")
):
    """
    Search open purchase orders from Business Central.
    Optionally filter by vendor.
    """
    try:
        service = get_bc_service()
        result = await service.get_open_purchase_orders(vendor_id=vendor_id, limit=limit)
        return {
            "purchaseOrders": result.get("purchaseOrders", []),
            "total": result.get("total", 0),
            "mock": result.get("mock", False)
        }
    except Exception as e:
        logger.error("PO search failed: %s", str(e))
        raise HTTPException(status_code=500, detail=f"PO search failed: {str(e)}")


# =============================================================================
# AP REVIEW SAVE/UPDATE ENDPOINTS
# =============================================================================

@ap_review_router.put("/documents/{doc_id}")
async def save_ap_review(doc_id: str, data: APReviewData):
    """
    Save AP review edits to a document.
    Updates vendor, invoice details, line items, etc.
    """
    logger.info(f"AP Review Save: doc_id={doc_id}, vendor_id={data.vendor_id}, invoice={data.invoice_number}")
    
    db = get_db()
    
    # Find document
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Build update data
    update_data = {
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }
    
    # Map AP review fields to document fields
    if data.vendor_id is not None:
        update_data["vendor_id"] = data.vendor_id
        update_data["vendor_canonical"] = data.vendor_id
    if data.vendor_name_resolved is not None:
        update_data["vendor_name_resolved"] = data.vendor_name_resolved
        update_data["vendor_raw"] = data.vendor_name_resolved
    if data.invoice_number is not None:
        update_data["invoice_number_clean"] = data.invoice_number
        # Also update extracted_fields
        extracted = doc.get("extracted_fields", {})
        extracted["invoice_number"] = data.invoice_number
        update_data["extracted_fields"] = extracted
    if data.invoice_date is not None:
        update_data["invoice_date"] = data.invoice_date
        extracted = update_data.get("extracted_fields") or doc.get("extracted_fields", {})
        extracted["invoice_date"] = data.invoice_date
        update_data["extracted_fields"] = extracted
    if data.due_date is not None:
        update_data["due_date_iso"] = data.due_date
        extracted = update_data.get("extracted_fields") or doc.get("extracted_fields", {})
        extracted["due_date"] = data.due_date
        update_data["extracted_fields"] = extracted
    if data.currency is not None:
        update_data["currency"] = data.currency
    if data.total_amount is not None:
        update_data["amount_float"] = data.total_amount
        extracted = update_data.get("extracted_fields") or doc.get("extracted_fields", {})
        extracted["amount"] = str(data.total_amount)
        update_data["extracted_fields"] = extracted
    if data.tax_amount is not None:
        update_data["tax_amount"] = data.tax_amount
    if data.po_number is not None:
        update_data["po_number_clean"] = data.po_number
        extracted = update_data.get("extracted_fields") or doc.get("extracted_fields", {})
        extracted["po_number"] = data.po_number
        update_data["extracted_fields"] = extracted
    if data.line_items is not None:
        update_data["line_items"] = data.line_items
    if data.notes is not None:
        update_data["ap_review_notes"] = data.notes
    if data.bc_document_no is not None:
        update_data["bc_document_no"] = data.bc_document_no
    
    # Handle document_type change — record correction for learning
    if data.document_type is not None:
        original_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
        if data.document_type != original_type:
            update_data["document_type"] = data.document_type
            update_data["suggested_job_type"] = data.document_type
            update_data["document_type_source"] = "manual"
            update_data["classification_override"] = {
                "original_type": original_type,
                "corrected_type": data.document_type,
                "corrected_at": datetime.now(timezone.utc).isoformat(),
            }
            
            # Record correction for AI learning loop
            try:
                from services.classification_feedback_service import record_correction
                # Extract first 500 chars of text for few-shot example
                text_snippet = ""
                try:
                    raw_text = doc.get("raw_text") or doc.get("extracted_text") or ""
                    if not raw_text:
                        ef = doc.get("extracted_fields") or {}
                        parts = [str(v) for v in ef.values() if v and not isinstance(v, (list, dict))]
                        raw_text = " | ".join(parts)
                    text_snippet = raw_text[:500]
                except Exception:
                    pass
                
                await record_correction(
                    doc_id=doc_id,
                    original_type=original_type,
                    corrected_type=data.document_type,
                    corrected_by="user",
                    doc_context={
                        "file_name": doc.get("file_name", ""),
                        "vendor_raw": doc.get("vendor_raw", ""),
                        "vendor_canonical": doc.get("vendor_canonical", ""),
                        "text_snippet": text_snippet,
                        "classification_method": doc.get("classification_method", ""),
                        "classification_confidence": doc.get("classification_confidence", 0),
                    },
                )
                logger.info("Classification correction recorded: %s → %s for doc %s", original_type, data.document_type, doc_id)
            except Exception as e:
                logger.warning("Failed to record classification correction: %s", e)
        else:
            update_data["document_type"] = data.document_type
    
    # ── UNIFIED FEEDBACK LOOP: Record corrections for learning ──
    try:
        from services.feedback_loop_service import record_feedback
        vendor_id = doc.get("vendor_canonical") or doc.get("vendor_no") or ""
        
        # Classification correction — feed into unified feedback loop
        if data.document_type is not None:
            original_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
            if data.document_type != original_type:
                await record_feedback(db, "classification_correction", doc_id, vendor_id,
                    before={"doc_type": original_type},
                    after={"doc_type": data.document_type},
                    metadata={
                        "file_name": doc.get("file_name", ""),
                        "vendor_canonical": doc.get("vendor_canonical", ""),
                    })
    except Exception as e:
        logger.debug("AP Review feedback recording skipped: %s", e)
    
    # Update document
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": update_data}
    )
    
    # ── UNIFIED FEEDBACK LOOP: Record ALL AP review corrections ──
    try:
        from services.feedback_loop_service import record_feedback
        vendor_id = data.vendor_id or doc.get("vendor_canonical") or ""
        
        if data.vendor_id and data.vendor_id != doc.get("vendor_canonical"):
            await record_feedback(db, "vendor_correction", doc_id, vendor_id,
                before={"vendor": doc.get("vendor_canonical", "")},
                after={"vendor": data.vendor_id},
                source="ap_review")
        
        if data.total_amount is not None and data.total_amount != doc.get("amount_float"):
            await record_feedback(db, "amount_correction", doc_id, vendor_id,
                before={"amount": doc.get("amount_float")},
                after={"amount": data.total_amount},
                source="ap_review")
        
        if data.po_number and data.po_number != doc.get("po_number_clean"):
            await record_feedback(db, "po_correction", doc_id, vendor_id,
                before={"po": doc.get("po_number_clean", "")},
                after={"po": data.po_number},
                source="ap_review")
        
        if data.invoice_number and data.invoice_number != doc.get("invoice_number_clean"):
            await record_feedback(db, "field_edit", doc_id, vendor_id,
                before={"invoice_number": doc.get("invoice_number_clean", "")},
                after={"invoice_number": data.invoice_number},
                source="ap_review")
        
        # The act of completing an AP review = approval signal
        await record_feedback(db, "approval", doc_id, vendor_id,
            metadata={"review_type": "ap_review"},
            source="ap_review")
    except Exception as e:
        logger.debug("Feedback recording skipped: %s", e)
    
    # Fetch updated document
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    
    logger.info(f"AP Review Save SUCCESS: doc_id={doc_id}")
    
    return {
        "success": True,
        "message": "AP review saved",
        "document": updated_doc
    }


@ap_review_router.post("/documents/{doc_id}/mark-ready")
async def mark_ready_for_post(doc_id: str):
    """
    Mark a document as ready and AUTO-POST to BC.
    
    After human review + corrections, this triggers the actual BC posting.
    Sets manual_po_override so the PO check is skipped — the reviewer has
    confirmed the document is ready regardless of PO match status.
    """
    logger.info(f"AP Review Mark Ready → Auto-Post: doc_id={doc_id}")
    
    db = get_db()
    
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Validate minimum required fields
    ef = doc.get("extracted_fields") or {}
    missing_fields = []
    if not doc.get("bc_vendor_number") and not doc.get("vendor_canonical"):
        missing_fields.append("vendor")
    if not doc.get("invoice_number_clean") and not ef.get("invoice_number"):
        missing_fields.append("invoice_number")
    if not doc.get("amount_float") and not ef.get("amount"):
        missing_fields.append("amount")
    
    if missing_fields:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot post: missing required fields: {', '.join(missing_fields)}"
        )
    
    # Set manual override flag — persists through reprocessing
    from datetime import datetime, timezone
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "manual_po_override": True,
        "manual_override": True,
        "manual_override_by": "reviewer",
        "manual_override_at": datetime.now(timezone.utc).isoformat(),
    }})
    
    # Attempt auto-post to BC — source="mark_ready" skips PO check
    from services.ap_auto_post_service import attempt_ap_auto_post
    result = await attempt_ap_auto_post(doc_id, db, source="mark_ready")
    
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    
    return {
        "success": result.get("success", False),
        "posted": result.get("posted", False),
        "message": result.get("reason", ""),
        "status": result.get("status", ""),
        "bc_record_no": result.get("bc_record_no"),
        "review_status": "posted" if result.get("posted") else "ready_for_post",
        "document": updated_doc,
    }


@ap_review_router.post("/documents/{doc_id}/override-po")
async def override_po_check(doc_id: str):
    """
    Override the PO validation check for a document.
    
    Sets manual_po_override=True which persists through reprocessing.
    Use this when the PO reference is correct but doesn't match a BC Purchase Order
    (e.g., freight carriers with internal reference numbers).
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    from datetime import datetime, timezone
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "manual_po_override": True,
        "manual_override": True,
        "manual_override_by": "reviewer",
        "manual_override_at": datetime.now(timezone.utc).isoformat(),
    }})
    
    # Re-run auto-post check now that override is set
    from services.ap_auto_post_service import attempt_ap_auto_post
    result = await attempt_ap_auto_post(doc_id, db, source="manual_override")
    
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    
    return {
        "success": True,
        "overridden": True,
        "auto_post_result": result,
        "document": updated_doc,
    }




# =============================================================================
# CANONICAL AP WORKFLOW MUTATIONS (formerly /api/workflows/ap_invoice/*)
# =============================================================================
#
# Per AP_PATH_CONSOLIDATION.md (Phase 2, 2026-04-21):
#   These routes are the canonical AP workflow mutation surface. They delegate
#   to services.workflow_handlers (the authoritative state-machine driver) so
#   every transition goes through WorkflowEngine.advance_workflow.
#
#   The old /api/workflows/ap_invoice/* routes in routers/workflows.py are kept
#   live for one release with deprecated=True + X-Deprecated response header,
#   then retired in Phase 4.
# =============================================================================

from services.workflow_handlers import (
    SetVendorRequest,
    UpdateFieldsRequest,
    BCValidationOverrideRequest,
    ApprovalActionRequest,
    set_vendor_for_document as _wf_set_vendor,
    update_document_fields as _wf_update_fields,
    override_bc_validation as _wf_override_bc,
    start_approval as _wf_start_approval,
    approve_document as _wf_approve,
    reject_document as _wf_reject,
)


@ap_review_router.post("/documents/{doc_id}/set-vendor")
async def ap_review_set_vendor(
    doc_id: str,
    request: SetVendorRequest,
    _user: dict = Depends(get_current_user),
):
    """Canonical Path A: manually resolve vendor for a VENDOR_PENDING document.

    Drives the workflow through ON_VENDOR_RESOLVED -> BC_VALIDATION_PENDING.
    """
    return await _wf_set_vendor(doc_id, request)


@ap_review_router.post("/documents/{doc_id}/update-fields")
async def ap_review_update_fields(
    doc_id: str,
    request: UpdateFieldsRequest,
    _user: dict = Depends(get_current_user),
):
    """Canonical Path A: update extracted fields on a document in a correction state.

    Advances the workflow via ON_DATA_CORRECTED when applicable.
    """
    return await _wf_update_fields(doc_id, request)


@ap_review_router.post("/documents/{doc_id}/override-bc-validation")
async def ap_review_override_bc_validation(
    doc_id: str,
    request: BCValidationOverrideRequest,
    _user: dict = Depends(get_current_user),
):
    """Canonical Path A: privileged override of a failed BC validation.

    Drives the workflow through ON_BC_VALIDATION_OVERRIDE -> READY_FOR_APPROVAL.
    """
    return await _wf_override_bc(doc_id, request)


@ap_review_router.post("/documents/{doc_id}/start-approval")
async def ap_review_start_approval(
    doc_id: str,
    request: ApprovalActionRequest,
    _user: dict = Depends(get_current_user),
):
    """Canonical Path A: begin the approval process.

    READY_FOR_APPROVAL -> APPROVAL_IN_PROGRESS (via ON_APPROVAL_STARTED).
    """
    return await _wf_start_approval(doc_id, request)


@ap_review_router.post("/documents/{doc_id}/approve")
async def ap_review_approve(
    doc_id: str,
    request: ApprovalActionRequest,
    _user: dict = Depends(get_current_user),
):
    """Canonical Path A: approve a document.

    Transitions via ON_APPROVED to APPROVED status, with vendor-alias learning.
    """
    return await _wf_approve(doc_id, request)


@ap_review_router.post("/documents/{doc_id}/reject")
async def ap_review_reject(
    doc_id: str,
    request: ApprovalActionRequest,
    _user: dict = Depends(get_current_user),
):
    """Canonical Path A: reject a document with a required reason.

    Transitions via ON_REJECTED to REJECTED status.
    """
    return await _wf_reject(doc_id, request)


# =============================================================================
# POST TO BC ENDPOINT
# =============================================================================

@ap_review_router.post("/documents/{doc_id}/post-to-bc")
async def post_document_to_bc(
    doc_id: str,
    request: Optional[PostToBCRequest] = None,
    auto_mark_ready: bool = Query(
        False,
        description="Demo/admin safety valve: if the doc has status='ReadyForPost' "
                    "but review_status is not yet 'ready_for_post' (the two-step "
                    "workflow was half-completed), set review_status inline before "
                    "posting. Defaults to False so the normal review gate still "
                    "applies in production."
    ),
    _user: dict = Depends(get_current_user),
):
    """
    Post a document to Business Central as a purchase invoice.
    Creates a purchase invoice in BC with the document's extracted data.
    On success, stores the BC document ID and updates posting status.
    On failure, records error details for retry.
    """
    logger.info(f"AP Review Post to BC: doc_id={doc_id}")

    db = get_db()

    # Find document
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check document is ready for posting
    review_status = doc.get("review_status", "")
    queue_status = doc.get("status", "")

    if review_status not in ("ready_for_post", "data_correction_pending"):
        # Safety valve: queue-status-says-ready but review_status is stale.
        # A known workflow gap where status="ReadyForPost" ≠ review_status.
        if auto_mark_ready and queue_status == "ReadyForPost":
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "review_status": "ready_for_post",
                    "review_marked_ready_by": "auto_mark_ready",
                    "review_marked_ready_at": datetime.now(timezone.utc).isoformat(),
                    "updated_utc": datetime.now(timezone.utc).isoformat(),
                }},
            )
            review_status = "ready_for_post"
            logger.info(
                f"post-to-bc auto-promoted review_status for doc_id={doc_id} "
                f"(queue_status=ReadyForPost but review_status was stale)"
            )
        elif doc.get("bc_posting_status") != "failed":
            # Clearer, actionable error — tells the UI exactly which button
            # to click next instead of showing raw internal state.
            if queue_status == "ReadyForPost":
                detail = (
                    "This invoice is in the ReadyForPost queue but hasn't been "
                    "reviewer-approved yet. Click 'Mark Ready for Post' in the "
                    "AP Review panel, then retry Post to BC."
                )
            else:
                detail = (
                    f"This invoice is not yet ready for posting. "
                    f"Current queue status: '{queue_status or 'n/a'}'. "
                    f"Please complete review first (Mark Ready for Post)."
                )
            raise HTTPException(status_code=400, detail=detail)
    
    # Check not already posted
    if doc.get("bc_posting_status") == "posted":
        raise HTTPException(
            status_code=400,
            detail=f"Document already posted to BC. BC Document ID: {doc.get('bc_document_id')}"
        )
    
    # Get BC service
    service = get_bc_service()
    
    # Build invoice data from document or request
    extracted = doc.get("extracted_fields", {})
    
    if request:
        invoice_data = {
            "vendorNumber": request.vendor_number or doc.get("vendor_id") or doc.get("vendor_canonical"),
            "invoiceNumber": request.invoice_number,
            "invoiceDate": request.invoice_date,
            "dueDate": request.due_date,
            "currencyCode": request.currency,
            "lines": request.line_items or doc.get("line_items", [])
        }
    else:
        # Build from document data
        invoice_data = {
            "vendorNumber": doc.get("vendor_id") or doc.get("vendor_canonical") or extracted.get("vendor_no"),
            "invoiceNumber": doc.get("invoice_number_clean") or extracted.get("invoice_number"),
            "invoiceDate": doc.get("invoice_date") or extracted.get("invoice_date"),
            "dueDate": doc.get("due_date_iso") or extracted.get("due_date"),
            "currencyCode": doc.get("currency", "USD"),
            "lines": doc.get("line_items", [])
        }
    
    # Validate required fields
    if not invoice_data.get("vendorNumber"):
        raise HTTPException(status_code=400, detail="Vendor is required for posting")
    if not invoice_data.get("invoiceNumber"):
        raise HTTPException(status_code=400, detail="Invoice number is required for posting")
    if not invoice_data.get("invoiceDate"):
        raise HTTPException(status_code=400, detail="Invoice date is required for posting")
    
    # ── ATOMIC CLAIM — manual Post-to-BC ──────────────────────────────────
    # Replaces the pre-existing "update status then call BC" pattern which
    # allowed a double-click / two-tab race to create duplicate BC invoices.
    from services.bc_post_claim import (
        claim_for_bc_post, release_claim, ClaimRejectionReason,
    )
    from services.bc_posting_attempts import (
        build_attempt, new_correlation_id, next_attempt_n,
    )
    from workflows.core.engine import WorkflowEngine, WorkflowEvent

    # A4: drive the workflow engine through ON_BC_POSTING_STARTED BEFORE the
    # claim. Fetches the doc, advances the engine, and then folds the new
    # workflow_status + workflow_history into the claim's atomic $set so
    # the engine state and the claim land in a single Mongo operation.
    pre_claim_doc = await db.hub_documents.find_one({"id": doc_id})
    if not pre_claim_doc:
        raise HTTPException(status_code=404, detail="Document not found")

    actor = f"user:{_user.get('email', 'unknown')}" if isinstance(_user, dict) else "user:unknown"
    mutated_doc, history_entry, engine_ok = WorkflowEngine.advance_workflow(
        pre_claim_doc,
        event=WorkflowEvent.ON_BC_POSTING_STARTED.value,
        context={"reason": "Post to BC initiated", "metadata": {"source": "manual_post_to_bc"}},
        actor=actor,
    )
    if not engine_ok:
        raise HTTPException(
            status_code=409,
            detail=(
                f"Workflow engine refused ON_BC_POSTING_STARTED from status "
                f"'{pre_claim_doc.get('workflow_status')}'. Expected APPROVED "
                f"or READY_FOR_APPROVAL."
            ),
        )

    claim = await claim_for_bc_post(
        db,
        doc_id=doc_id,
        target_state="posting",
        worker_id=f"ap_review.post_to_bc-{os.getpid()}",
        extra_set={
            # A4: keep engine state in lockstep with the claim.
            "workflow_status": mutated_doc["workflow_status"],
            "workflow_status_updated_utc": mutated_doc["workflow_status_updated_utc"],
            "workflow_history": mutated_doc.get("workflow_history", []),
        },
    )
    if not claim.claimed:
        # Engine already advanced but claim was rejected — roll the engine
        # state back so we don't strand the doc in BC_POSTING_IN_PROGRESS
        # without an actual in-flight post. Revert via direct write (no
        # engine rollback event — the transition never actually happened
        # from the doc's perspective).
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "workflow_status": pre_claim_doc.get("workflow_status"),
                "workflow_status_updated_utc": pre_claim_doc.get("workflow_status_updated_utc"),
            }},
        )
        if claim.reason == ClaimRejectionReason.NOT_FOUND:
            raise HTTPException(status_code=404, detail="Document not found")
        if claim.reason == ClaimRejectionReason.ALREADY_TERMINAL:
            raise HTTPException(
                status_code=409,
                detail=(
                    f"Document already posted (status={claim.existing_status}). "
                    f"Refusing to re-post to avoid duplicate BC records."
                ),
            )
        # ACTIVE_CLAIM — another worker or click holds it
        raise HTTPException(
            status_code=409,
            detail=(
                f"Another Post-to-BC request is already in flight for this "
                f"document (held by {claim.existing_holder}). Wait for it to "
                f"complete or retry after the claim TTL expires."
            ),
        )

    # A1: posting-attempts history bookkeeping. Each call to this endpoint is
    # one logical post — allocate an attempt_n + correlation_id and we'll
    # build the attempt dict at the release_claim() boundary.
    attempt_n = await next_attempt_n(db, doc_id)
    correlation_id = new_correlation_id()
    started_utc = datetime.now(timezone.utc).isoformat()

    try:
        # Call BC service to create purchase invoice
        result = await service.create_purchase_invoice(invoice_data)
        
        if result.get("success"):
            bc_document_id = result.get("bcDocumentId")
            bc_document_number = result.get("bcDocumentNumber")
            
            # Get SharePoint URL from document (if uploaded)
            sharepoint_url = doc.get("sharepoint_share_link_url") or doc.get("sharepoint_web_url")
            
            # Attempt to write SharePoint link back to BC (non-blocking)
            link_writeback_status = "skipped"
            link_writeback_error = None
            
            if sharepoint_url and bc_document_id:
                try:
                    # Get additional SharePoint details from document
                    sp_drive_id = doc.get("sharepoint_drive_id")
                    sp_item_id = doc.get("sharepoint_item_id")
                    
                    writeback_result = await service.update_purchase_invoice_link(
                        invoice_id=bc_document_id,
                        sharepoint_url=sharepoint_url,
                        bc_document_no=bc_document_number,
                        sharepoint_drive_id=sp_drive_id,
                        sharepoint_item_id=sp_item_id,
                        uploaded_by="GPI Hub"
                    )
                    if writeback_result.get("success"):
                        link_writeback_status = "success"
                        if writeback_result.get("fallback"):
                            link_writeback_status = "success_fallback"
                        logger.info("SharePoint link written to BC for invoice %s (action: %s)", 
                                   bc_document_id, writeback_result.get("action", "unknown"))
                    elif writeback_result.get("skipped"):
                        link_writeback_status = "skipped"
                        link_writeback_error = writeback_result.get("reason")
                    else:
                        link_writeback_status = "failed"
                        link_writeback_error = writeback_result.get("error") or writeback_result.get("details")
                        logger.warning("BC link writeback failed for doc %s: %s", doc_id, link_writeback_error)
                except Exception as wb_err:
                    link_writeback_status = "failed"
                    link_writeback_error = str(wb_err)
                    logger.warning("BC link writeback exception for doc %s: %s", doc_id, wb_err)
            elif not sharepoint_url:
                link_writeback_status = "skipped"
                link_writeback_error = "No SharePoint URL available"
            
            # Success — release claim into terminal "posted" state atomically,
            # and append the successful attempt to bc_posting_attempts in the
            # same $push so the audit entry can never drift from the state.
            finished_utc = datetime.now(timezone.utc).isoformat()
            attempt = build_attempt(
                attempt_n=attempt_n,
                status="posted",
                actor=actor,
                source="manual_post_to_bc",
                correlation_id=correlation_id,
                started_utc=started_utc,
                finished_utc=finished_utc,
                bc_record_no=bc_document_number,
                bc_document_id=bc_document_id,
            )
            # A4: advance the engine from BC_POSTING_IN_PROGRESS to BC_POSTED.
            posted_doc = dict(mutated_doc)
            posted_doc, posted_history, _ok = WorkflowEngine.advance_workflow(
                posted_doc,
                event=WorkflowEvent.ON_BC_POSTED.value,
                context={"metadata": {"bc_record_no": bc_document_number,
                                      "bc_document_id": bc_document_id}},
                actor=actor,
            )
            await release_claim(
                db,
                doc_id=doc_id,
                final_state="posted",
                extra_set={
                    "bc_document_id": bc_document_id,
                    "bc_document_number": bc_document_number,
                    "bc_posting_error": None,
                    "bc_link_writeback_status": link_writeback_status,
                    "bc_link_writeback_error": link_writeback_error,
                    "review_status": "posted",
                    "status": "Posted",
                    "workflow_status": posted_doc["workflow_status"],
                    "workflow_status_updated_utc": posted_doc["workflow_status_updated_utc"],
                    "workflow_history": posted_doc.get("workflow_history", []),
                    "posted_to_bc_utc": finished_utc,
                },
                attempt=attempt,
            )

            updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
            
            return PostToBCResponse(
                success=True,
                bc_document_id=bc_document_id,
                bc_document_number=bc_document_number,
                bc_posting_status="posted",
                message=result.get("message", "Posted successfully"),
                sharepoint_url=sharepoint_url,
                bc_link_writeback_status=link_writeback_status,
                bc_link_writeback_error=link_writeback_error
            )
        else:
            # Failure — release claim into "failed" state so the doc is
            # retry-eligible but no longer actively held. Append the failed
            # attempt atomically; the partial-post case flags it.
            error_msg = result.get("error") or result.get("details") or "Unknown error"
            is_partial = bool(result.get("partial_post")) or result.get("error") == "partial_post"
            attempt_status = "partial" if is_partial else "failed"
            partial_lines = None
            if is_partial:
                partial_lines = {
                    "added": result.get("linesAdded", 0),
                    "total": result.get("linesTotal", 0),
                }
            attempt = build_attempt(
                attempt_n=attempt_n,
                status=attempt_status,
                actor=actor,
                source="manual_post_to_bc",
                correlation_id=correlation_id,
                started_utc=started_utc,
                finished_utc=datetime.now(timezone.utc).isoformat(),
                error=error_msg,
                retry_reason="bc_rejection",
                bc_response_snippet=str(result)[:2000],
                partial_lines=partial_lines,
            )
            # A4: drive engine ON_BC_PARTIAL_POSTED vs ON_BC_POST_FAILED.
            terminal_doc = dict(mutated_doc)
            terminal_event = (
                WorkflowEvent.ON_BC_PARTIAL_POSTED.value if is_partial
                else WorkflowEvent.ON_BC_POST_FAILED.value
            )
            terminal_doc, _hist, _ok = WorkflowEngine.advance_workflow(
                terminal_doc, event=terminal_event,
                context={"metadata": {"error": error_msg}}, actor=actor,
            )
            await release_claim(
                db,
                doc_id=doc_id,
                final_state="failed",
                extra_set={
                    "bc_posting_error": error_msg,
                    "review_status": "ready_for_post",  # Keep ready for retry
                    "workflow_status": terminal_doc["workflow_status"],
                    "workflow_status_updated_utc": terminal_doc["workflow_status_updated_utc"],
                    "workflow_history": terminal_doc.get("workflow_history", []),
                },
                attempt=attempt,
            )

            return PostToBCResponse(
                success=False,
                bc_posting_status="failed",
                message="Failed to post to Business Central",
                error=error_msg
            )
            
    except Exception as e:
        # Exception — always release the claim so a crashed attempt doesn't
        # strand the document in-flight forever (TTL would eventually rescue
        # it, but explicit release is cleaner).
        error_msg = str(e)
        logger.error("Post to BC failed for doc %s: %s", doc_id, error_msg)

        try:
            attempt = build_attempt(
                attempt_n=attempt_n,
                status="failed",
                actor=actor,
                source="manual_post_to_bc",
                correlation_id=correlation_id,
                started_utc=started_utc,
                finished_utc=datetime.now(timezone.utc).isoformat(),
                error=error_msg,
                retry_reason="exception",
            )
            # A4: drive engine via ON_BC_POST_FAILED so workflow_status rolls
            # back to APPROVED (retry-eligible).
            terminal_doc = dict(mutated_doc)
            terminal_doc, _hist, _ok = WorkflowEngine.advance_workflow(
                terminal_doc,
                event=WorkflowEvent.ON_BC_POST_FAILED.value,
                context={"metadata": {"error": error_msg, "source": "exception"}},
                actor=actor,
            )
            await release_claim(
                db,
                doc_id=doc_id,
                final_state="failed",
                extra_set={
                    "bc_posting_error": error_msg,
                    "review_status": "ready_for_post",
                    "workflow_status": terminal_doc["workflow_status"],
                    "workflow_status_updated_utc": terminal_doc["workflow_status_updated_utc"],
                    "workflow_history": terminal_doc.get("workflow_history", []),
                },
                attempt=attempt,
            )
        except Exception as release_err:
            logger.error(
                "Post-to-BC release_claim after exception failed for %s: %s",
                doc_id, release_err,
            )

        return PostToBCResponse(
            success=False,
            bc_posting_status="failed",
            message="Error posting to Business Central",
            error=error_msg
        )


@ap_review_router.get("/documents/{doc_id}/bc-status")
async def get_bc_posting_status(
    doc_id: str,
    _user: dict = Depends(get_current_user),
):
    """Get the BC posting status for a document. JWT-protected (hygiene patch 2026-04-22)."""
    db = get_db()
    
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return {
        "document_id": doc_id,
        "review_status": doc.get("review_status"),
        "bc_posting_status": doc.get("bc_posting_status"),
        "bc_document_id": doc.get("bc_document_id"),
        "bc_document_number": doc.get("bc_document_number"),
        "bc_posting_error": doc.get("bc_posting_error"),
        "posted_to_bc_utc": doc.get("posted_to_bc_utc"),
        # A1: full append-only attempt history. Newest entry is last in
        # the array (Mongo $push semantics); frontend reverses for display.
        "bc_posting_attempts": doc.get("bc_posting_attempts", []),
    }



# =============================================================================
# AI INVOICE DATA EXTRACTION ENDPOINTS
# =============================================================================

@ap_review_router.post("/documents/{doc_id}/extract-invoice-data")
async def extract_invoice_data_endpoint(doc_id: str):
    """
    Extract invoice data from PDF using AI/OCR.
    
    Uses Gemini vision to extract:
    - Invoice number, date, due date
    - Vendor name
    - PO number
    - Line items (description, quantity, unit price, total)
    - Total amount, tax amount
    
    The extracted data is saved to the document and returned.
    """
    logger.info(f"AI Invoice Extraction: doc_id={doc_id}")
    
    db = get_db()
    
    # Find document
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Get file path - check uploads directory
    file_path = None
    
    # Try to find file in uploads directory
    upload_path = os.path.join(UPLOAD_DIR, doc_id)
    if os.path.exists(upload_path):
        file_path = upload_path
    else:
        # Try with file extension
        file_name = doc.get("file_name", "")
        if file_name:
            ext = os.path.splitext(file_name)[1]
            upload_path_with_ext = os.path.join(UPLOAD_DIR, f"{doc_id}{ext}")
            if os.path.exists(upload_path_with_ext):
                file_path = upload_path_with_ext
    
    # Check if we have local_file_path stored
    if not file_path and doc.get("local_file_path"):
        if os.path.exists(doc["local_file_path"]):
            file_path = doc["local_file_path"]
    
    if not file_path:
        raise HTTPException(
            status_code=400, 
            detail=f"Document file not found on disk. Doc ID: {doc_id}"
        )
    
    # Import and run extraction
    try:
        from services.invoice_extractor import extract_and_update_document
        
        result = await extract_and_update_document(doc_id, file_path, db)
        
        if result.get("success"):
            logger.info(f"AI Invoice Extraction SUCCESS: doc_id={doc_id}, confidence={result.get('confidence')}, lines={result.get('line_items_count')}")
            
            # Fetch updated document
            updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
            
            return {
                "success": True,
                "document_id": doc_id,
                "confidence": result.get("confidence"),
                "can_auto_post": result.get("can_auto_post"),
                "extracted_fields": result.get("extracted_fields"),
                "line_items": result.get("line_items"),
                "line_items_count": result.get("line_items_count"),
                "document": updated_doc
            }
        else:
            logger.error(f"AI Invoice Extraction FAILED: doc_id={doc_id}, error={result.get('error')}")
            return {
                "success": False,
                "document_id": doc_id,
                "error": result.get("error")
            }
            
    except ImportError as e:
        logger.error(f"AI Invoice Extraction import error: {e}")
        raise HTTPException(status_code=500, detail=f"Invoice extractor not available: {str(e)}")
    except Exception as e:
        logger.error(f"AI Invoice Extraction exception: {e}")
        raise HTTPException(status_code=500, detail=f"Extraction failed: {str(e)}")


@ap_review_router.get("/documents/{doc_id}/extraction-status")
async def get_extraction_status(doc_id: str):
    """Get the AI extraction status for a document."""
    db = get_db()
    
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    ai_extraction = doc.get("ai_extraction", {})
    
    return {
        "document_id": doc_id,
        "has_extraction": bool(ai_extraction),
        "extraction_timestamp": ai_extraction.get("extracted_at"),
        "confidence": ai_extraction.get("confidence"),
        "can_auto_post": ai_extraction.get("can_auto_post", False),
        "line_items_count": len(doc.get("line_items", [])),
        "extracted_fields": doc.get("extracted_fields", {}),
        "line_items": doc.get("line_items", [])
    }


@ap_review_router.get("/vendor-profile/{vendor_no}")
async def get_vendor_profile(vendor_no: str, refresh: bool = False):
    """Get the vendor's invoice profile (learned from BC history).
    
    Shows what GL accounts, line types, description patterns, and amounts
    are typical for this vendor — used to auto-populate PI lines.
    """
    from services.vendor_invoice_profile_service import build_vendor_profile, get_or_build_profile
    
    db = get_db()
    if refresh:
        profile = await build_vendor_profile(db, vendor_no, force_refresh=True)
    else:
        profile = await get_or_build_profile(db, vendor_no)
    
    return {
        "vendor_no": profile.get("vendor_no"),
        "vendor_name": profile.get("vendor_name"),
        "bc_invoice_count": profile.get("bc_invoice_count", 0),
        "local_posting_count": profile.get("local_posting_count", 0),
        "po_expected": profile.get("po_expected", True),
        "default_line_type": profile.get("default_line_type"),
        "default_gl_account": profile.get("default_gl_account"),
        "default_item_code": profile.get("default_item_code"),
        "description_pattern": profile.get("description_pattern"),
        "line_patterns": profile.get("line_patterns", {}),
        "amount_stats": profile.get("amount_stats", {}),
        "vendor_card": profile.get("vendor_card", {}),
        "sources": profile.get("sources", {}),
        "last_updated": profile.get("last_updated"),
    }


@ap_review_router.post("/vendor-profile/{vendor_no}/overrides")
async def set_vendor_profile_overrides(vendor_no: str, data: dict):
    """Manually set profile defaults for vendors whose BC tenant doesn't
    expose line-level history (e.g. freight carriers where posted invoices
    live outside v2.0 API).

    Body: ``{"default_line_type": "Account", "default_gl_account": "60500",
             "default_item_code": "", "description_pattern": "po_reference",
             "actor": "admin@example.com"}``

    Any omitted key is left unchanged. The override is written directly to
    the cached profile and marked in ``sources.manual_override`` so
    downstream consumers can surface the provenance to reviewers.
    """
    from services.vendor_invoice_profile_service import get_or_build_profile

    db = get_db()
    # Ensure a base profile exists before merging overrides
    await get_or_build_profile(db, vendor_no)

    allowed = {
        "default_line_type", "default_gl_account",
        "default_item_code", "description_pattern",
    }
    updates = {k: v for k, v in data.items() if k in allowed and v is not None}
    if not updates:
        raise HTTPException(
            status_code=400,
            detail=f"No valid override keys provided. Allowed: {sorted(allowed)}",
        )

    actor = data.get("actor") or "admin"
    override_meta = {
        "set_by": actor,
        "set_at": datetime.now(timezone.utc).isoformat(),
        "fields": list(updates.keys()),
    }
    # Merge overrides into the cached profile and flag provenance
    await db.vendor_invoice_profiles.update_one(
        {"vendor_no": vendor_no},
        {
            "$set": {
                **updates,
                "sources.manual_override": override_meta,
                "last_updated": datetime.now(timezone.utc).isoformat(),
            }
        },
        upsert=True,
    )

    refreshed = await db.vendor_invoice_profiles.find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    return {
        "vendor_no": vendor_no,
        "applied": updates,
        "override_meta": override_meta,
        "profile": {
            "default_line_type": refreshed.get("default_line_type"),
            "default_gl_account": refreshed.get("default_gl_account"),
            "default_item_code": refreshed.get("default_item_code"),
            "description_pattern": refreshed.get("description_pattern"),
            "bc_invoice_count": refreshed.get("bc_invoice_count", 0),
            "sources": refreshed.get("sources", {}),
        },
    }


@ap_review_router.get("/pi-preflight/{doc_id}")
async def pi_preflight(doc_id: str):
    """Preview what the Purchase Invoice will look like before posting to BC.
    
    Shows the planned header, lines (with source — profile vs default vs extracted),
    and any deviation flags from the vendor's historical pattern.
    """
    from services.vendor_invoice_profile_service import (
        get_or_build_profile, build_smart_pi_lines, detect_deviations
    )
    
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    
    # Resolve vendor
    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
    vendor_name = doc.get("vendor_canonical") or ef.get("vendor") or ""
    
    if not vendor_no:
        return {
            "doc_id": doc_id,
            "ready": False,
            "reason": "Vendor not resolved — cannot build PI without a BC vendor number.",
        }
    
    # Get vendor profile
    profile = await get_or_build_profile(db, vendor_no)
    
    # Build lines using the profile
    from routers.gpi_integration import _resolve_po_reference
    po_ref = _resolve_po_reference(doc)
    planned_lines = build_smart_pi_lines(doc, profile, po_reference=po_ref)
    
    # Detect deviations
    deviations = detect_deviations(doc, profile, planned_lines)
    
    # Build planned header
    invoice_number = ef.get("invoice_number") or nf.get("invoice_number") or ""
    invoice_date = ef.get("invoice_date") or nf.get("invoice_date") or ""
    total_amount = sum(l.get("unitCost", 0) * l.get("quantity", 1) for l in planned_lines)
    
    has_critical = any(d["severity"] == "critical" for d in deviations)
    critical_list = [d for d in deviations if d["severity"] == "critical"]
    
    return {
        "doc_id": doc_id,
        "ready": not has_critical,
        "needs_review": has_critical,
        "critical_deviations": critical_list or None,
        "vendor": {
            "vendor_no": vendor_no,
            "vendor_name": vendor_name,
            "profile_available": profile.get("bc_invoice_count", 0) > 0,
            "bc_invoices_analyzed": profile.get("bc_invoice_count", 0),
        },
        "planned_header": {
            "vendorNo": vendor_no,
            "vendorInvoiceNo": invoice_number,
            "documentDate": invoice_date,
            "postingDate": invoice_date,
            "po_reference": po_ref,
        },
        "planned_lines": [
            {
                "lineType": line.get("lineType"),
                "lineObjectNumber": line.get("lineObjectNumber"),
                "description": line.get("description"),
                "quantity": line.get("quantity"),
                "unitCost": line.get("unitCost"),
                "source": line.get("source", "unknown"),
            }
            for line in planned_lines
        ],
        "total_amount": round(total_amount, 2),
        "deviations": deviations,
        "profile_summary": {
            "default_line_type": profile.get("default_line_type"),
            "default_gl_account": profile.get("default_gl_account"),
            "default_item_code": profile.get("default_item_code"),
            "description_pattern": profile.get("description_pattern"),
            "amount_stats": profile.get("amount_stats", {}),
        },
    }
