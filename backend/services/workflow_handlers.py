"""
GPI Document Hub - Workflow Domain Handlers

Authoritative implementations of workflow-domain route handlers, extracted
from server.py during the "Workflow Handler Extraction" remediation pass.

These are route-facing orchestration functions consumed by
routers/workflows.py via add_api_route().

Dependencies:
  - deps.get_db() for database access
  - services.workflow_engine for WorkflowEngine, enums
  - services.pilot_config for pilot-mode guards
  - services.vendor_name_helpers for normalize_vendor_name
"""

import logging
import re
from datetime import datetime, timezone
from typing import List, Optional

from fastapi import HTTPException, Query
from pydantic import BaseModel

from deps import get_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Pydantic models (moved from server.py)
# ---------------------------------------------------------------------------

class SetVendorRequest(BaseModel):
    """Request body for manual vendor resolution."""
    vendor_id: str
    vendor_name: Optional[str] = None
    vendor_alias_used: Optional[str] = None
    reason: Optional[str] = None


class UpdateFieldsRequest(BaseModel):
    """Request body for manual data correction."""
    invoice_number: Optional[str] = None
    amount: Optional[float] = None
    po_number: Optional[str] = None
    due_date: Optional[str] = None
    vendor_name: Optional[str] = None
    reason: Optional[str] = None


class BCValidationOverrideRequest(BaseModel):
    """Request body for BC validation override."""
    override_reason: str
    override_user: str


class ApprovalActionRequest(BaseModel):
    """Request body for approval actions."""
    reason: Optional[str] = None
    approver: Optional[str] = None


# ---------------------------------------------------------------------------
# Lazy imports
# ---------------------------------------------------------------------------

def _get_workflow_deps():
    """Import workflow engine types (avoids circular imports at module level)."""
    from services.workflow_engine import (
        WorkflowEngine, WorkflowStatus, WorkflowEvent, DocType,
    )
    return WorkflowEngine, WorkflowStatus, WorkflowEvent, DocType


def _normalize_vendor_name(name: str) -> str:
    """Delegate to vendor_name_helpers (authoritative source)."""
    from services.vendor_name_helpers import normalize_vendor_name
    return normalize_vendor_name(name)


def _is_export_blocked(doc: dict) -> bool:
    """Lazy proxy for pilot_config.is_export_blocked."""
    from services.pilot_config import is_export_blocked
    return is_export_blocked(doc)


# ---------------------------------------------------------------------------
# AP Invoice mutation handlers
# ---------------------------------------------------------------------------

async def set_vendor_for_document(doc_id: str, request: SetVendorRequest):
    """
    Manually set/resolve vendor for a document in vendor_pending status.
    This moves the document from vendor_pending to bc_validation_pending.
    Only for AP_INVOICE documents.
    """
    db = get_db()
    WorkflowEngine, WorkflowStatus, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type") or (
        DocType.AP_INVOICE.value if doc.get("document_type") == "AP_Invoice" else None
    )
    if doc_type != DocType.AP_INVOICE.value:
        raise HTTPException(status_code=400, detail="This endpoint only supports AP_INVOICE documents")

    current_status = doc.get("workflow_status")
    if current_status != WorkflowStatus.VENDOR_PENDING.value:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', expected 'vendor_pending'",
        )

    update_data = {
        "vendor_canonical": request.vendor_id,
        "vendor_match_method": "manual",
        "vendor_match_score": 1.0,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }

    if request.vendor_name:
        update_data["vendor_resolved_name"] = request.vendor_name

    if request.vendor_alias_used and doc.get("vendor_normalized"):
        alias_doc = {
            "alias_string": request.vendor_alias_used,
            "normalized_alias": doc.get("vendor_normalized"),
            "canonical_vendor_id": request.vendor_id,
            "vendor_name": request.vendor_name,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source": "manual_resolution",
        }
        await db.vendor_aliases.update_one(
            {"normalized_alias": doc.get("vendor_normalized")},
            {"$set": alias_doc},
            upsert=True,
        )

    # Auto-learn vendor alias from this approval
    try:
        from services.vendor_alias_learning_service import learn_alias_from_approval
        await learn_alias_from_approval(
            doc,
            vendor_id=request.vendor_id,
            vendor_name=request.vendor_name or request.vendor_id,
            actor="reviewer",
        )
    except Exception as e:
        logger.warning("[VendorAlias] Learning failed in set_vendor: %s", e)

    # Negative feedback: capture rejection if reviewer overrides an auto-match
    prev_method = doc.get("vendor_match_method") or (doc.get("vendor_resolution") or {}).get("method")
    prev_vendor = doc.get("vendor_canonical")
    if (
        prev_method in ("fuzzy_match", "bc_exact_match", "fuzzy_bc", "fuzzy")
        and prev_vendor
        and prev_vendor != request.vendor_id
    ):
        try:
            from services.vendor_resolution_service import capture_rejection
            await capture_rejection(
                doc_id=doc_id,
                vendor_raw=doc.get("vendor_raw") or doc.get("extracted_vendor") or "",
                proposed_vendor_id=prev_vendor,
                proposed_vendor_name=doc.get("vendor_resolved_name") or prev_vendor,
                proposed_method=prev_method,
                proposed_score=float(doc.get("vendor_match_score") or (doc.get("vendor_resolution") or {}).get("score") or 0),
                corrected_vendor_id=request.vendor_id,
                corrected_vendor_name=request.vendor_name or request.vendor_id,
                actor="reviewer",
            )
        except Exception as e:
            logger.warning("[VendorRejection] Capture failed in set_vendor: %s", e)

    # Mark resolution as reviewed_override if vendor changed
    if prev_vendor and prev_vendor != request.vendor_id:
        update_data["vendor_resolution"] = {
            **(doc.get("vendor_resolution") or {}),
            "status": "resolved",
            "method": "manual_match",
            "matched_vendor_name": request.vendor_name or request.vendor_id,
            "matched_vendor_no": request.vendor_id,
            "score": 1.0,
            "reason": "Reviewer override",
            "reviewed_override": True,
        }
    else:
        update_data["vendor_resolution"] = {
            **(doc.get("vendor_resolution") or {}),
            "status": "resolved",
            "method": "manual_match",
            "matched_vendor_name": request.vendor_name or request.vendor_id,
            "matched_vendor_no": request.vendor_id,
            "score": 1.0,
            "reason": "Vendor manually confirmed",
            "reviewed_override": False,
        }

    doc.update(update_data)
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_VENDOR_RESOLVED.value,
        context={
            "reason": request.reason or "Vendor manually resolved",
            "metadata": {"vendor_id": request.vendor_id},
        },
        actor="user",
    )

    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")

    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc})
    doc.pop("_id", None)

    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Vendor set to {request.vendor_id}, document moved to bc_validation_pending",
    }


async def update_document_fields(doc_id: str, request: UpdateFieldsRequest):
    """
    Manually update/correct fields on a document.
    Re-runs validation and advances workflow based on new data.
    Works for any document type, but AP-specific validation only runs for AP_INVOICE.
    """
    db = get_db()
    WorkflowEngine, WorkflowStatus, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type") or (
        DocType.AP_INVOICE.value if doc.get("document_type") == "AP_Invoice" else DocType.OTHER.value
    )

    current_status = doc.get("workflow_status")
    valid_statuses = [
        WorkflowStatus.DATA_CORRECTION_PENDING.value,
        WorkflowStatus.BC_VALIDATION_FAILED.value,
        WorkflowStatus.VENDOR_PENDING.value,
        WorkflowStatus.REVIEW_PENDING.value,
        WorkflowStatus.EXTRACTED.value,
    ]

    if current_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', field updates allowed in: {valid_statuses}",
        )

    update_data = {"updated_utc": datetime.now(timezone.utc).isoformat()}
    extracted_fields = doc.get("extracted_fields", {})

    if request.invoice_number is not None:
        extracted_fields["invoice_number"] = request.invoice_number
        update_data["invoice_number_clean"] = re.sub(r'[^a-zA-Z0-9]', '', request.invoice_number.upper())

    if request.amount is not None:
        extracted_fields["amount"] = str(request.amount)
        update_data["amount_float"] = request.amount

    if request.po_number is not None:
        extracted_fields["po_number"] = request.po_number
        update_data["po_number_clean"] = (
            re.sub(r'[^a-zA-Z0-9]', '', request.po_number.upper()) if request.po_number else None
        )

    if request.due_date is not None:
        extracted_fields["due_date"] = request.due_date

    if request.vendor_name is not None:
        extracted_fields["vendor"] = request.vendor_name
        update_data["vendor_raw"] = request.vendor_name
        update_data["vendor_normalized"] = _normalize_vendor_name(request.vendor_name)

    update_data["extracted_fields"] = extracted_fields

    if current_status == WorkflowStatus.DATA_CORRECTION_PENDING.value:
        event = WorkflowEvent.ON_DATA_CORRECTED.value
    elif current_status == WorkflowStatus.BC_VALIDATION_FAILED.value:
        event = WorkflowEvent.ON_DATA_CORRECTED.value
    else:
        event = WorkflowEvent.ON_DATA_CORRECTED.value

    doc.update(update_data)
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        event,
        context={
            "reason": request.reason or "Fields manually updated",
            "metadata": {"updated_fields": list(request.model_dump(exclude_none=True).keys())},
        },
        actor="user",
    )

    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc})
    doc.pop("_id", None)

    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict() if success else None,
        "message": "Fields updated" + (", workflow advanced" if success else ""),
    }


async def override_bc_validation(doc_id: str, request: BCValidationOverrideRequest):
    """
    Override a failed BC validation and move document to ready_for_approval.
    This is a privileged action that bypasses normal validation rules.
    """
    db = get_db()
    WorkflowEngine, WorkflowStatus, WorkflowEvent, _DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    if doc.get("document_type") != "AP_Invoice":
        raise HTTPException(status_code=400, detail="This endpoint only supports AP_Invoice documents")

    current_status = doc.get("workflow_status")
    if current_status != WorkflowStatus.BC_VALIDATION_FAILED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', expected 'bc_validation_failed'",
        )

    override_record = {
        "override_reason": request.override_reason,
        "override_user": request.override_user,
        "override_utc": datetime.now(timezone.utc).isoformat(),
        "original_validation_errors": doc.get("validation_errors", []),
    }

    doc["bc_validation_override"] = override_record
    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()

    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_BC_VALIDATION_OVERRIDE.value,
        context={
            "reason": request.override_reason,
            "metadata": {"override_user": request.override_user},
        },
        actor=request.override_user,
    )

    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")

    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc})
    doc.pop("_id", None)

    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"BC validation overridden by {request.override_user}, document moved to ready_for_approval",
    }


# ---------------------------------------------------------------------------
# AP Invoice approval workflow
# ---------------------------------------------------------------------------

async def start_approval(doc_id: str, request: ApprovalActionRequest):
    """
    Start the approval process for a document.
    Moves from ready_for_approval to approval_in_progress.
    """
    db = get_db()
    WorkflowEngine, WorkflowStatus, WorkflowEvent, _DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    if doc.get("document_type") != "AP_Invoice":
        raise HTTPException(status_code=400, detail="This endpoint only supports AP_Invoice documents")

    current_status = doc.get("workflow_status")
    if current_status != WorkflowStatus.READY_FOR_APPROVAL.value:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', expected 'ready_for_approval'",
        )

    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    doc["approval_started_utc"] = datetime.now(timezone.utc).isoformat()

    if request.approver:
        doc["assigned_approver"] = request.approver

    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_APPROVAL_STARTED.value,
        context={
            "reason": request.reason or "Approval process started",
            "metadata": {"approver": request.approver},
        },
        actor=request.approver or "system",
    )

    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")

    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc})
    doc.pop("_id", None)

    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Approval process started",
    }


async def approve_document(doc_id: str, request: ApprovalActionRequest):
    """
    Approve a document. Moves to 'approved' status.
    Can be called from ready_for_approval (auto-approval) or approval_in_progress.
    Works for all document types.
    """
    db = get_db()
    WorkflowEngine, WorkflowStatus, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type") or (
        DocType.AP_INVOICE.value if doc.get("document_type") == "AP_Invoice" else DocType.OTHER.value
    )

    current_status = doc.get("workflow_status")
    valid_statuses = [
        WorkflowStatus.READY_FOR_APPROVAL.value,
        WorkflowStatus.APPROVAL_IN_PROGRESS.value,
        WorkflowStatus.EXTRACTED.value,
        WorkflowStatus.REVIEW_PENDING.value,
    ]

    if current_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', approval allowed from: {valid_statuses}",
        )

    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    doc["approved_utc"] = datetime.now(timezone.utc).isoformat()
    doc["approved_by"] = request.approver or "system"

    # Auto-learn vendor alias from approval (if vendor is resolved)
    if doc.get("vendor_canonical") and doc.get("vendor_raw"):
        try:
            from services.vendor_alias_learning_service import learn_alias_from_approval
            await learn_alias_from_approval(
                doc,
                vendor_id=doc.get("vendor_canonical"),
                vendor_name=doc.get("vendor_resolved_name") or doc.get("vendor_canonical"),
                actor=request.approver or "system",
            )
        except Exception as e:
            logger.warning("[VendorAlias] Learning failed in approve_document: %s", e)

    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_APPROVED.value,
        context={
            "reason": request.reason or "Document approved",
            "metadata": {"approver": request.approver, "doc_type": doc_type},
        },
        actor=request.approver or "system",
    )

    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")

    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc})
    doc.pop("_id", None)

    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Document approved by {request.approver or 'system'}",
    }


async def reject_document(doc_id: str, request: ApprovalActionRequest):
    """
    Reject a document. Moves to 'rejected' status.
    Works for all document types.
    """
    db = get_db()
    WorkflowEngine, WorkflowStatus, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type") or (
        DocType.AP_INVOICE.value if doc.get("document_type") == "AP_Invoice" else DocType.OTHER.value
    )

    current_status = doc.get("workflow_status")
    valid_statuses = [
        WorkflowStatus.READY_FOR_APPROVAL.value,
        WorkflowStatus.APPROVAL_IN_PROGRESS.value,
        WorkflowStatus.EXTRACTED.value,
        WorkflowStatus.REVIEW_PENDING.value,
    ]

    if current_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', rejection allowed from: {valid_statuses}",
        )

    if not request.reason:
        raise HTTPException(status_code=400, detail="Rejection reason is required")

    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    doc["rejected_utc"] = datetime.now(timezone.utc).isoformat()
    doc["rejected_by"] = request.approver or "system"
    doc["rejection_reason"] = request.reason

    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_REJECTED.value,
        context={
            "reason": request.reason,
            "metadata": {"rejector": request.approver, "doc_type": doc_type},
        },
        actor=request.approver or "system",
    )

    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")

    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc})
    doc.pop("_id", None)

    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Document rejected: {request.reason}",
    }


# ---------------------------------------------------------------------------
# Generic workflow mutation handlers
# ---------------------------------------------------------------------------

async def mark_ready_for_review(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None,
):
    """
    Mark a document as ready for review.
    Applicable to: STATEMENT, REMINDER, FINANCE_CHARGE_MEMO, QUALITY_DOC, OTHER

    Triggers: on_mark_ready_for_review event
    """
    db = get_db()
    WorkflowEngine, _WS, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"

    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_MARK_READY_FOR_REVIEW.value,
        context={
            "reason": reason or "Marked ready for review",
            "metadata": {"triggered_by": actor},
        },
        actor=actor,
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot transition to ready_for_review from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'",
        )

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
        }},
    )

    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Document marked ready for review",
    }


async def mark_reviewed(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None,
):
    """
    Mark a document as reviewed.
    Applicable to: STATEMENT, REMINDER, FINANCE_CHARGE_MEMO, QUALITY_DOC

    Triggers: on_reviewed event
    """
    db = get_db()
    WorkflowEngine, _WS, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"

    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_REVIEWED.value,
        context={
            "reason": reason or "Document reviewed",
            "metadata": {"triggered_by": actor},
        },
        actor=actor,
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot mark as reviewed from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'",
        )

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
        }},
    )

    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Document marked as reviewed",
    }


async def start_approval_generic(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None,
):
    """
    Start approval process for a document (generic version).
    Applicable to: SALES_INVOICE, PURCHASE_ORDER, SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO, QUALITY_DOC

    Triggers: on_approval_started event
    """
    db = get_db()
    WorkflowEngine, _WS, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"

    if doc_type == DocType.AP_INVOICE.value:
        raise HTTPException(
            status_code=400,
            detail="AP_INVOICE documents should use /api/workflows/ap_invoice/{doc_id}/start-approval",
        )

    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_APPROVAL_STARTED.value,
        context={
            "reason": reason or "Approval process started",
            "metadata": {"triggered_by": actor},
        },
        actor=actor,
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot start approval from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'",
        )

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
        }},
    )

    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Approval process started",
    }


async def approve_generic(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None,
):
    """
    Approve a document (generic version).
    Applicable to: SALES_INVOICE, PURCHASE_ORDER, SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO

    Triggers: on_approved event
    """
    db = get_db()
    WorkflowEngine, _WS, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"

    if doc_type == DocType.AP_INVOICE.value:
        raise HTTPException(
            status_code=400,
            detail="AP_INVOICE documents should use /api/workflows/ap_invoice/{doc_id}/approve",
        )

    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_APPROVED.value,
        context={
            "reason": reason or "Document approved",
            "metadata": {"triggered_by": actor},
        },
        actor=actor,
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot approve from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'",
        )

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
        }},
    )

    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Document approved",
    }


async def reject_generic(
    doc_id: str,
    reason: str = Query(..., description="Reason for rejection (required)"),
    user: Optional[str] = None,
):
    """
    Reject a document (generic version).
    Applicable to: SALES_INVOICE, PURCHASE_ORDER, SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO, QUALITY_DOC

    Triggers: on_rejected event
    """
    db = get_db()
    WorkflowEngine, _WS, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"

    if doc_type == DocType.AP_INVOICE.value:
        raise HTTPException(
            status_code=400,
            detail="AP_INVOICE documents should use /api/workflows/ap_invoice/{doc_id}/reject",
        )

    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_REJECTED.value,
        context={
            "reason": reason,
            "metadata": {"triggered_by": actor},
        },
        actor=actor,
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot reject from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'",
        )

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
        }},
    )

    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Document rejected: {reason}",
    }


async def complete_triage(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None,
):
    """
    Complete triage for an OTHER document.
    Applicable to: OTHER

    Triggers: on_triage_completed event
    """
    db = get_db()
    WorkflowEngine, _WS, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"

    if doc_type != DocType.OTHER.value:
        raise HTTPException(
            status_code=400,
            detail=f"Triage completion is only applicable to OTHER documents, not {doc_type}",
        )

    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_TRIAGE_COMPLETED.value,
        context={
            "reason": reason or "Triage completed",
            "metadata": {"triggered_by": actor},
        },
        actor=actor,
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot complete triage from status '{doc.get('workflow_status')}'",
        )

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
        }},
    )

    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Triage completed",
    }


async def link_credit_to_invoice(
    doc_id: str,
    invoice_id: str = Query(..., description="ID of the original invoice"),
    user: Optional[str] = None,
):
    """
    Link a credit memo to its original invoice.
    Applicable to: SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO

    Triggers: on_credit_linked_to_invoice event
    """
    db = get_db()
    WorkflowEngine, _WS, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"

    valid_types = [DocType.SALES_CREDIT_MEMO.value, DocType.PURCHASE_CREDIT_MEMO.value]
    if doc_type not in valid_types:
        raise HTTPException(
            status_code=400,
            detail=f"Invoice linkage is only applicable to credit memos, not {doc_type}",
        )

    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_CREDIT_LINKED_TO_INVOICE.value,
        context={
            "reason": f"Linked to invoice {invoice_id}",
            "metadata": {
                "triggered_by": actor,
                "linked_invoice_id": invoice_id,
            },
        },
        actor=actor,
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot link to invoice from status '{doc.get('workflow_status')}'",
        )

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
            "linked_invoice_id": invoice_id,
        }},
    )

    updated_doc["linked_invoice_id"] = invoice_id

    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Credit memo linked to invoice {invoice_id}",
    }


async def tag_quality_doc(
    doc_id: str,
    tags: List[str] = Query(..., description="Quality tags to apply"),
    user: Optional[str] = None,
):
    """
    Tag a quality document for categorization.
    Applicable to: QUALITY_DOC

    Triggers: on_quality_tagged event
    """
    db = get_db()
    WorkflowEngine, _WS, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"

    if doc_type != DocType.QUALITY_DOC.value:
        raise HTTPException(
            status_code=400,
            detail=f"Quality tagging is only applicable to QUALITY_DOC, not {doc_type}",
        )

    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_QUALITY_TAGGED.value,
        context={
            "reason": f"Tagged with: {', '.join(tags)}",
            "metadata": {
                "triggered_by": actor,
                "tags": tags,
            },
        },
        actor=actor,
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot tag from status '{doc.get('workflow_status')}'",
        )

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
            "quality_tags": tags,
        }},
    )

    updated_doc["quality_tags"] = tags

    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Quality document tagged: {', '.join(tags)}",
    }


async def export_document(
    doc_id: str,
    export_destination: Optional[str] = None,
    user: Optional[str] = None,
):
    """
    Mark a document as exported (generic version).
    Applicable to all document types.

    Triggers: on_exported event

    Note: During pilot mode, actual exports are blocked but status transitions
    are recorded for observation.
    """
    db = get_db()
    WorkflowEngine, _WS, WorkflowEvent, DocType = _get_workflow_deps()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")

    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"

    pilot_blocked = _is_export_blocked(doc)

    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_EXPORTED.value,
        context={
            "reason": f"Exported to: {export_destination or 'default'}"
            + (" [PILOT: actual export blocked]" if pilot_blocked else ""),
            "metadata": {
                "triggered_by": actor,
                "export_destination": export_destination,
                "pilot_mode": pilot_blocked,
                "pilot_blocked_action": "external_export" if pilot_blocked else None,
            },
        },
        actor=actor,
    )

    if not success:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot export from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'",
        )

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
            "exported_utc": datetime.now(timezone.utc).isoformat(),
            "export_destination": export_destination,
        }},
    )

    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Document exported",
    }
