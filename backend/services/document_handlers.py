"""
GPI Document Hub - Document Domain Handlers

Authoritative implementations of document-domain route handlers, extracted
from server.py during the "Document Handler Extraction" remediation pass.

These are route-facing orchestration functions consumed by
routers/documents.py via add_api_route().

Dependencies are sourced from proper service modules where available.
Functions still imported from server.py are documented inline as
extraction targets for future passes.
"""

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import List, Optional

from fastapi import (
    BackgroundTasks,
    File,
    Form,
    HTTPException,
    Query,
    UploadFile,
)
from pydantic import BaseModel

from deps import get_db

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _derive_workflow_status_simple(final_status: str, decision: str) -> str:
    """Map processing result to workflow_status so docs don't stay 'captured'."""
    s = (final_status or "").lower()
    if s in ("completed", "posted", "archived"):
        return "completed"
    if s == "exception":
        return "exception"
    if s in ("readytolink", "linkedtobc"):
        return "ready_for_approval"
    if s == "storedinsp":
        return "processed"
    if decision == "auto_link":
        return "validation_passed"
    if s == "needsreview":
        return "needs_review"
    return "classified"



# ---------------------------------------------------------------------------
# Pydantic models (moved from server.py)
# ---------------------------------------------------------------------------


class ResolveRequest(BaseModel):
    selected_vendor_id: Optional[str] = None
    selected_customer_id: Optional[str] = None
    selected_po_number: Optional[str] = None
    mark_no_po: bool = False
    notes: Optional[str] = None


class DryRunPreviewRequest(BaseModel):
    """Request for dry-run preview with optional BC environment override."""
    use_production_bc: bool = True
    bc_tenant_id: Optional[str] = None
    bc_environment: Optional[str] = None


# ---------------------------------------------------------------------------
# Lazy imports from proper service modules
# ---------------------------------------------------------------------------

def _get_workflow_enums():
    from services.workflow_engine import (
        DocType,
        SourceSystem,
        CaptureChannel,
        WorkflowStatus,
        WorkflowEvent,
        DocumentClassifier,
    )
    return DocType, SourceSystem, CaptureChannel, WorkflowStatus, WorkflowEvent, DocumentClassifier


def _get_transaction_action():
    from models.document_types import TransactionAction
    return TransactionAction


def _get_default_job_types():
    from models.document_types import DEFAULT_JOB_TYPES
    return DEFAULT_JOB_TYPES


# ---------------------------------------------------------------------------
# Direct imports from authoritative service modules
# ---------------------------------------------------------------------------
from services.document_intel_helpers import (
    classify_document_with_ai as _classify_with_ai,
    compute_ap_normalized_fields as _compute_ap_normalized,
    make_automation_decision as _make_automation_decision,
)
from services.vendor_matching import (
    lookup_vendor_alias as _lookup_vendor_alias,
    check_duplicate_document as _check_duplicate,
)
from services.ap_computation import (
    compute_ap_validation as _compute_ap_validation,
    is_eligible_for_draft_creation as _is_eligible_for_draft,
)
from services.bc_api_helpers import get_bc_companies as _get_bc_companies

# ---------------------------------------------------------------------------
# Server.py functions still needed (remaining extraction targets)
# Used for: run_upload_and_link_workflow, link_document_to_bc,
#   classify_document_type, upload_to_sharepoint, create_sharing_link,
#   get_bc_token, check_duplicate_purchase_invoice, create_purchase_invoice_header
# ---------------------------------------------------------------------------

def _server():
    """Lazy import of server module for functions not yet extracted."""
    import server
    return server


# ---------------------------------------------------------------------------
# Handler implementations
# ---------------------------------------------------------------------------


async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form("Other"),
    bc_record_id: str = Form(None),
    bc_document_no: str = Form(None),
    bc_company_id: str = Form(None),
    source: str = Form("manual_upload"),
):
    db = get_db()
    srv = _server()
    DocType, SourceSystem, CaptureChannel, WorkflowStatus, WorkflowEvent, DocumentClassifier = _get_workflow_enums()

    file_content = await file.read()
    sha256_hash = hashlib.sha256(file_content).hexdigest()
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    correlation_id = str(uuid.uuid4())

    file_path = UPLOAD_DIR / doc_id
    file_path.write_bytes(file_content)

    doc_type_value = DocumentClassifier.classify_from_ai_result(document_type or "").value if document_type else DocType.OTHER.value

    from services.pilot_config import PILOT_MODE_ENABLED, get_pilot_capture_channel, get_pilot_metadata
    base_capture_channel = CaptureChannel.UPLOAD.value
    capture_channel = get_pilot_capture_channel(base_capture_channel) if PILOT_MODE_ENABLED else base_capture_channel

    from services.square9_workflow import initialize_retry_state

    doc = {
        "id": doc_id, "source": source, "file_name": file.filename,
        "sha256_hash": sha256_hash, "file_size": len(file_content),
        "content_type": file.content_type,
        "sharepoint_drive_id": None, "sharepoint_item_id": None,
        "sharepoint_web_url": None, "sharepoint_share_link_url": None,
        "document_type": document_type,
        "category": None,
        "doc_type": doc_type_value,
        "source_system": SourceSystem.GPI_HUB_NATIVE.value,
        "capture_channel": capture_channel,
        "bc_record_type": "SalesOrder" if document_type == "SalesOrder" else None,
        "bc_company_id": bc_company_id, "bc_record_id": bc_record_id,
        "bc_document_no": bc_document_no,
        "workflow_status": WorkflowStatus.CAPTURED.value,
        "workflow_history": [{
            "timestamp": now,
            "from_status": None,
            "to_status": WorkflowStatus.CAPTURED.value,
            "event": WorkflowEvent.ON_CAPTURE.value,
            "actor": "system",
            "reason": f"Document captured from {source}",
            "metadata": {"source": source, "doc_type": doc_type_value},
        }],
        "workflow_status_updated_utc": now,
        **initialize_retry_state({}),
        "status": "Received", "created_utc": now, "updated_utc": now, "last_error": None,
        "validation_state": "pending",
        "workflow_state": "received",
        "automation_state": "manual",
        **get_pilot_metadata(),
    }
    await db.hub_documents.insert_one(doc)

    from services.event_service import get_event_service, emit_document_received
    event_service = get_event_service()
    if event_service:
        await emit_document_received(
            event_service, doc_id, source,
            file.filename, file.content_type or "application/octet-stream",
            len(file_content), correlation_id,
        )

    workflow_id, final_status = await srv.run_upload_and_link_workflow(
        doc_id, file_content, file.filename, document_type, bc_record_id, bc_document_no,
    )

    from services.derived_state_service import get_derived_state_service
    derived_state_service = get_derived_state_service()
    if derived_state_service:
        await derived_state_service.update_document_derived_state(doc_id)

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "workflow_id": workflow_id}


async def retry_document(doc_id: str):
    db = get_db()
    srv = _server()

    from services.square9_workflow import (
        should_retry, increment_retry, DEFAULT_WORKFLOW_CONFIG,
        determine_square9_stage,
    )

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if not should_retry(doc):
        max_retries = DEFAULT_WORKFLOW_CONFIG.get("max_retries", 3)
        return {
            "success": False,
            "reason": f"Maximum retries ({max_retries}) reached",
            "retry_count": doc.get("retry_count", 0),
            "max_retries": max_retries,
        }

    doc = increment_retry(doc)

    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "retry_count": doc["retry_count"],
        "last_retry_utc": doc["last_retry_utc"],
        "retry_history": doc.get("retry_history", []),
        "status": "Retrying",
        "last_error": None,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }})

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found for retry")

    file_content = file_path.read_bytes()

    workflow_id, final_status = await srv.run_upload_and_link_workflow(
        doc_id, file_content, doc["file_name"],
        doc.get("document_type", "Other"),
        doc.get("bc_record_id"), doc.get("bc_document_no"),
    )

    new_stage = determine_square9_stage(final_status, doc.get("doc_type"))
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "square9_stage": new_stage,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }})

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "success": True,
        "document": updated_doc,
        "workflow_id": workflow_id,
        "retry_count": doc["retry_count"],
    }


async def resubmit_document(doc_id: str):
    db = get_db()
    srv = _server()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found")

    file_content = file_path.read_bytes()

    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "status": "Received",
        "last_error": None,
        "retry_count": 0,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }})

    workflow_id, final_status = await srv.run_upload_and_link_workflow(
        doc_id, file_content, doc["file_name"],
        doc.get("document_type", "Other"),
        doc.get("bc_record_id"), doc.get("bc_document_no"),
    )

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "workflow_id": workflow_id}


async def link_document(doc_id: str, bc_record_id: str):
    db = get_db()
    srv = _server()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found")

    file_content = file_path.read_bytes()
    share_link = doc.get("sharepoint_share_link_url", "")
    bc_entity = doc.get("bc_entity", "salesOrders")

    link_result = await srv.link_document_to_bc(
        bc_record_id=bc_record_id,
        share_link=share_link,
        file_name=doc["file_name"],
        file_content=file_content,
        bc_entity=bc_entity,
    )

    if link_result.get("success"):
        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "bc_record_id": bc_record_id,
            "status": "LinkedToBC",
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }})

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "link_result": link_result}


async def intake_document(
    file: UploadFile = File(...),
    source: str = Form("email"),
    sender: Optional[str] = Form(None),
    subject: Optional[str] = Form(None),
    attachment_name: Optional[str] = Form(None),
    content_hash: Optional[str] = Form(None),
    email_id: Optional[str] = Form(None),
    email_received_utc: Optional[str] = Form(None),
):
    db = get_db()
    srv = _server()
    DocType, SourceSystem, CaptureChannel, WorkflowStatus, WorkflowEvent, _DC = _get_workflow_enums()
    TransactionAction = _get_transaction_action()
    DEFAULT_JOB_TYPES = _get_default_job_types()

    from services.pilot_config import PILOT_MODE_ENABLED, get_pilot_capture_channel, get_pilot_metadata

    file_content = await file.read()
    computed_hash = hashlib.sha256(file_content).hexdigest()
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    final_filename = attachment_name or file.filename

    file_path = UPLOAD_DIR / doc_id
    file_path.write_bytes(file_content)

    doc = {
        "id": doc_id,
        "source": source,
        "file_name": final_filename,
        "sha256_hash": computed_hash,
        "file_size": len(file_content),
        "content_type": file.content_type,
        "email_sender": sender,
        "email_subject": subject,
        "email_id": email_id,
        "email_received_utc": email_received_utc,
        "sharepoint_drive_id": None, "sharepoint_item_id": None,
        "sharepoint_web_url": None, "sharepoint_share_link_url": None,
        "document_type": None, "category": None,
        "suggested_job_type": None, "ai_confidence": None,
        "extracted_fields": None, "validation_results": None,
        "automation_decision": None,
        "bc_record_type": None, "bc_company_id": None,
        "bc_record_id": None, "bc_document_no": None,
        "status": "Received",
        "doc_type": DocType.OTHER.value,
        "source_system": SourceSystem.GPI_HUB_NATIVE.value,
        "capture_channel": get_pilot_capture_channel(
            CaptureChannel.EMAIL.value if "email" in source.lower() else CaptureChannel.UPLOAD.value,
        ) if PILOT_MODE_ENABLED else (
            CaptureChannel.EMAIL.value if "email" in source.lower() else CaptureChannel.UPLOAD.value
        ),
        "workflow_status": WorkflowStatus.CAPTURED.value,
        "workflow_history": [{
            "timestamp": now,
            "from_status": None,
            "to_status": WorkflowStatus.CAPTURED.value,
            "event": WorkflowEvent.ON_CAPTURE.value,
            "actor": "system",
            "reason": f"Document captured from {source}",
            "metadata": {"source": source, "sender": sender},
        }],
        "workflow_status_updated_utc": now,
        "created_utc": now, "updated_utc": now, "last_error": None,
        **get_pilot_metadata(),
    }
    await db.hub_documents.insert_one(doc)

    # AI classification
    logger.info("Running AI field extraction for document %s", doc_id)
    classification = await _classify_with_ai(str(file_path), final_filename)

    suggested_type = classification.get("suggested_job_type", "Unknown")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})

    # Deterministic-first classification
    classification_result = await srv.classify_document_type(
        document=doc, extracted_fields=extracted_fields,
        suggested_type=suggested_type, confidence=confidence,
        metadata={
            "mailbox_category": doc.get("mailbox_category"),
            "zetadocs_set": doc.get("zetadocs_set_code"),
            "square9_workflow": doc.get("square9_workflow_name"),
        },
    )

    doc_type_value = classification_result["doc_type"]
    category = classification_result["category"]
    ai_classification_audit = classification_result.get("ai_classification")
    classification_method = classification_result.get("classification_method", "unknown")

    logger.info("Document %s classified as %s (category: %s, method: %s)",
                doc_id, doc_type_value, category, classification_method)

    # Phase 7 normalization
    normalized_fields = _compute_ap_normalized(extracted_fields)
    vendor_alias_result = await _lookup_vendor_alias(normalized_fields.get("vendor_normalized"))
    duplicate_result = await _check_duplicate(
        vendor_normalized=normalized_fields.get("vendor_normalized"),
        vendor_canonical=vendor_alias_result.get("vendor_canonical"),
        invoice_number_clean=normalized_fields.get("invoice_number_clean"),
        current_doc_id=doc_id,
    )
    ap_validation = _compute_ap_validation(
        document_type=suggested_type,
        vendor_normalized=normalized_fields.get("vendor_normalized"),
        invoice_number_clean=normalized_fields.get("invoice_number_clean"),
        amount_float=normalized_fields.get("amount_float"),
        po_number_clean=normalized_fields.get("po_number_clean"),
        ai_confidence=confidence,
        possible_duplicate=duplicate_result.get("possible_duplicate", False),
    )

    # BC validation
    job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])

    from services.bc_validation_service import validate_bc_match
    validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)

    decision, reasoning, decision_metadata = _make_automation_decision(job_configs, confidence, validation_results)

    bc_entity = job_configs.get("bc_entity", "salesOrders")

    # SharePoint upload
    folder = job_configs.get("sharepoint_folder", "Incoming")
    sp_result = None
    share_link = None
    sp_error = None

    try:
        sp_result = await srv.upload_to_sharepoint(file_content, final_filename, folder)
        share_link = await srv.create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
        logger.info("Document %s stored in SharePoint: %s", doc_id, sp_result.get("web_url"))
    except Exception as e:
        sp_error = str(e)
        logger.error("SharePoint upload failed for document %s: %s", doc_id, sp_error)

    # Determine status
    if suggested_type in ("AP_Invoice", "AP Invoice"):
        final_status = "NeedsReview"
    else:
        final_status = "StoredInSP" if sp_result else "Classified"

    # Build update payload
    update_data = {
        "suggested_job_type": suggested_type,
        "document_type": suggested_type,
        "ai_confidence": confidence,
        "extracted_fields": extracted_fields,
        "doc_type": doc_type_value,
        "category": category,
        "classification_method": classification_method,
        "vendor_raw": normalized_fields.get("vendor_raw"),
        "vendor_normalized": normalized_fields.get("vendor_normalized"),
        "invoice_number_raw": normalized_fields.get("invoice_number_raw"),
        "invoice_number_clean": normalized_fields.get("invoice_number_clean"),
        "amount_raw": normalized_fields.get("amount_raw"),
        "amount_float": normalized_fields.get("amount_float"),
        "due_date_raw": normalized_fields.get("due_date_raw"),
        "due_date_iso": normalized_fields.get("due_date_iso"),
        "po_number_raw": normalized_fields.get("po_number_raw"),
        "po_number_clean": normalized_fields.get("po_number_clean"),
        "invoice_date": normalized_fields.get("invoice_date"),
        "invoice_date_raw": normalized_fields.get("invoice_date_raw"),
        "line_items": normalized_fields.get("line_items", []),
        "vendor_canonical": vendor_alias_result.get("vendor_canonical"),
        "vendor_match_method": vendor_alias_result.get("vendor_match_method"),
        "possible_duplicate": duplicate_result.get("possible_duplicate", False),
        "duplicate_of_document_id": duplicate_result.get("duplicate_of_document_id"),
        "validation_errors": ap_validation.get("validation_errors", []),
        "validation_warnings": ap_validation.get("validation_warnings", []),
        "draft_candidate": ap_validation.get("draft_candidate", False),
        "canonical_fields": normalized_fields,
        "normalized_fields": validation_results.get("normalized_fields", {}),
        "validation_results": validation_results,
        "automation_decision": decision,
        "match_method": validation_results.get("match_method", "none"),
        "match_score": validation_results.get("match_score", 0.0),
        "vendor_candidates": decision_metadata.get("vendor_candidates", []),
        "customer_candidates": decision_metadata.get("customer_candidates", []),
        "warnings": decision_metadata.get("warnings", []),
        "status": final_status,
        "workflow_status": _derive_workflow_status_simple(final_status, decision),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }

    if sp_result:
        update_data["sharepoint_drive_id"] = sp_result["drive_id"]
        update_data["sharepoint_item_id"] = sp_result["item_id"]
        update_data["sharepoint_web_url"] = sp_result["web_url"]
        update_data["sharepoint_share_link_url"] = share_link
    else:
        update_data["last_error"] = f"SharePoint upload failed: {sp_error}"

    if ai_classification_audit:
        update_data["ai_classification"] = ai_classification_audit

    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})

    # Workflow log
    workflow_steps = [
        {"step": "receive_document", "status": "completed", "result": {"source": source, "hash": computed_hash}},
        {"step": "ai_classification", "status": "completed", "result": classification},
        {"step": "sharepoint_upload", "status": "completed" if sp_result else "failed",
         "result": sp_result if sp_result else {"error": sp_error}},
        {"step": "bc_validation", "status": "completed", "result": {
            "all_passed": validation_results.get("all_passed"),
            "match_method": validation_results.get("match_method", "none"),
            "checks_count": len(validation_results.get("checks", [])),
            "vendor_candidates_count": len(validation_results.get("vendor_candidates", [])),
            "warnings_count": len(validation_results.get("warnings", [])),
        }},
        {"step": "automation_decision", "status": "completed", "result": {"decision": decision, "reasoning": reasoning}},
    ]

    workflow = {
        "id": str(uuid.uuid4()),
        "document_id": doc_id,
        "workflow_name": "email_intake",
        "started_utc": now,
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Completed",
        "steps": workflow_steps,
        "correlation_id": str(uuid.uuid4()),
        "error": None,
    }
    await db.hub_workflow_runs.insert_one(workflow)

    # BC action
    final_status = update_data["status"]
    transaction_action = TransactionAction.NONE
    draft_result = None

    if sp_result and (decision == "auto_link" or decision == "auto_create"):
        bc_record_id = validation_results.get("bc_record_id")
        match_method = validation_results.get("match_method", "none")
        match_score = validation_results.get("match_score", 0.0)

        current_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        is_draft_eligible, draft_reason = _is_eligible_for_draft(
            job_type=suggested_type, match_method=match_method,
            match_score=match_score, ai_confidence=confidence,
            validation_results=validation_results, doc=current_doc,
        )

        if is_draft_eligible and suggested_type == "AP_Invoice":
            logger.info("Document %s eligible for draft creation: %s", doc_id, draft_reason)
            vendor_info = validation_results.get("bc_record_info", {})
            vendor_no = vendor_info.get("number", "")
            norm_fields = validation_results.get("normalized_fields", {})
            external_doc_no = norm_fields.get("invoice_number") or extracted_fields.get("invoice_number", "")

            if vendor_no and external_doc_no:
                token = await srv.get_bc_token()
                companies = await _get_bc_companies()
                company_id = companies[0]["id"] if companies else None

                dup_check = await srv.check_duplicate_purchase_invoice(
                    vendor_no=vendor_no, external_doc_no=external_doc_no,
                    company_id=company_id, token=token,
                )

                if dup_check.get("found"):
                    logger.warning("Duplicate invoice found during draft for doc %s", doc_id)
                    final_status = "NeedsReview"
                    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                        "status": "NeedsReview",
                        "transaction_action": TransactionAction.NONE,
                        "last_error": f"Duplicate invoice exists: {dup_check.get('existing_invoice_no')}",
                        "updated_utc": datetime.now(timezone.utc).isoformat(),
                    }})
                else:
                    draft_result = await srv.create_purchase_invoice_header(
                        vendor_no=vendor_no, external_doc_no=external_doc_no,
                        document_date=norm_fields.get("invoice_date") or norm_fields.get("due_date_raw"),
                        due_date=norm_fields.get("due_date"),
                        posting_date=None, company_id=company_id, token=token,
                    )

                    if draft_result.get("success"):
                        final_status = "LinkedToBC"
                        transaction_action = TransactionAction.DRAFT_CREATED
                        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                            "bc_record_id": draft_result.get("invoice_id"),
                            "bc_document_no": draft_result.get("invoice_no"),
                            "bc_record_type": "PurchaseInvoice",
                            "transaction_action": TransactionAction.DRAFT_CREATED,
                            "draft_creation_result": draft_result,
                            "status": "LinkedToBC",
                            "updated_utc": datetime.now(timezone.utc).isoformat(),
                        }})
                        logger.info("Draft created for doc %s: %s", doc_id, draft_result.get("invoice_no"))
                    else:
                        logger.error("Draft creation failed for doc %s: %s", doc_id, draft_result.get("error"))
                        final_status = "NeedsReview"
                        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                            "status": "NeedsReview",
                            "transaction_action": TransactionAction.NONE,
                            "last_error": f"Draft creation failed: {draft_result.get('error')}",
                            "updated_utc": datetime.now(timezone.utc).isoformat(),
                        }})
            else:
                logger.warning("Missing vendor_no or external_doc_no for draft, falling back to link")
                if bc_record_id:
                    try:
                        link_result = await srv.link_document_to_bc(
                            bc_record_id=bc_record_id, share_link=share_link,
                            file_name=final_filename, file_content=file_content,
                            bc_entity=bc_entity,
                        )
                        if link_result.get("success"):
                            final_status = "LinkedToBC"
                            transaction_action = TransactionAction.LINKED_ONLY
                            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                                "bc_record_id": bc_record_id,
                                "transaction_action": TransactionAction.LINKED_ONLY,
                                "status": "LinkedToBC",
                                "updated_utc": datetime.now(timezone.utc).isoformat(),
                            }})
                    except Exception as e:
                        logger.error("BC linking failed for document %s: %s", doc_id, str(e))

        elif bc_record_id:
            try:
                link_result = await srv.link_document_to_bc(
                    bc_record_id=bc_record_id, share_link=share_link,
                    file_name=final_filename, file_content=file_content,
                    bc_entity=bc_entity,
                )
                if link_result.get("success"):
                    final_status = "LinkedToBC"
                    transaction_action = TransactionAction.LINKED_ONLY
                    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                        "bc_record_id": bc_record_id,
                        "transaction_action": TransactionAction.LINKED_ONLY,
                        "status": "LinkedToBC",
                        "updated_utc": datetime.now(timezone.utc).isoformat(),
                    }})
            except Exception as e:
                logger.error("BC linking failed for document %s: %s", doc_id, str(e))

    elif decision == "needs_review":
        final_status = "NeedsReview"
        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "status": "NeedsReview",
            "transaction_action": TransactionAction.NONE,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }})

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "document": updated_doc,
        "classification": classification,
        "validation": validation_results,
        "decision": decision,
        "reasoning": reasoning,
        "draft_result": draft_result,
        "transaction_action": transaction_action,
    }


async def classify_document(doc_id: str):
    """Re-run AI classification on an existing document."""
    db = get_db()
    DEFAULT_JOB_TYPES = _get_default_job_types()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found")

    classification = await _classify_with_ai(str(file_path), doc["file_name"])

    suggested_type = classification.get("suggested_job_type", "Unknown")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})

    job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])

    from services.bc_validation_service import validate_bc_match
    validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)

    decision, reasoning, decision_metadata = _make_automation_decision(job_configs, confidence, validation_results)

    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "suggested_job_type": suggested_type,
        "document_type": suggested_type,
        "ai_confidence": confidence,
        "classification_method": f"ai:{classification.get('model', 'gemini-3-flash-preview')}",
        "ai_model": classification.get("model", "gemini-3-flash-preview"),
        "extracted_fields": extracted_fields,
        "normalized_fields": validation_results.get("normalized_fields", {}),
        "validation_results": validation_results,
        "automation_decision": decision,
        "vendor_candidates": decision_metadata.get("vendor_candidates", []),
        "customer_candidates": decision_metadata.get("customer_candidates", []),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }})

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "document": updated_doc,
        "classification": classification,
        "validation": validation_results,
        "decision": decision,
        "reasoning": reasoning,
        "candidates": {
            "vendors": decision_metadata.get("vendor_candidates", []),
            "customers": decision_metadata.get("customer_candidates", []),
        },
    }


async def resolve_and_link_document(doc_id: str, resolve: ResolveRequest):
    """Resolve a NeedsReview document and link to BC."""
    db = get_db()
    srv = _server()
    DEFAULT_JOB_TYPES = _get_default_job_types()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.get("status") not in ("NeedsReview", "StoredInSP", "Classified"):
        raise HTTPException(
            status_code=400,
            detail=f"Document status must be NeedsReview, StoredInSP, or Classified. Current: {doc.get('status')}",
        )

    file_path = UPLOAD_DIR / doc_id
    file_content = file_path.read_bytes() if file_path.exists() else None

    bc_record_id = None
    bc_record_type = doc.get("suggested_job_type", "AP_Invoice")

    if resolve.selected_vendor_id:
        bc_record_id = resolve.selected_vendor_id
    elif resolve.selected_customer_id:
        bc_record_id = resolve.selected_customer_id
    elif doc.get("validation_results", {}).get("bc_record_id"):
        bc_record_id = doc["validation_results"]["bc_record_id"]

    share_link = doc.get("sharepoint_share_link_url")
    bc_entity = "salesOrders"  # default
    if not share_link and file_content:
        job_configs = await db.hub_job_types.find_one({"job_type": bc_record_type}, {"_id": 0})
        if not job_configs:
            job_configs = DEFAULT_JOB_TYPES.get(bc_record_type, DEFAULT_JOB_TYPES["AP_Invoice"])

        folder = job_configs.get("sharepoint_folder", "Incoming")
        bc_entity = job_configs.get("bc_entity", "salesOrders")
        try:
            sp_result = await srv.upload_to_sharepoint(file_content, doc["file_name"], folder)
            share_link = await srv.create_sharing_link(sp_result["drive_id"], sp_result["item_id"])

            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "sharepoint_drive_id": sp_result["drive_id"],
                "sharepoint_item_id": sp_result["item_id"],
                "sharepoint_web_url": sp_result["web_url"],
                "sharepoint_share_link_url": share_link,
                "status": "StoredInSP",
                "updated_utc": datetime.now(timezone.utc).isoformat(),
            }})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"SharePoint upload failed: {str(e)}")

    link_success = False
    link_error = None

    if bc_record_id and file_content:
        try:
            link_result = await srv.link_document_to_bc(
                bc_record_id=bc_record_id, share_link=share_link or "",
                file_name=doc["file_name"], file_content=file_content,
                bc_entity=bc_entity,
            )
            link_success = link_result.get("success", False)
            if not link_success:
                link_error = link_result.get("error", "Unknown error")
        except Exception as e:
            link_error = str(e)

    final_status = "LinkedToBC" if link_success else "StoredInSP"
    update_data = {
        "status": final_status,
        "bc_record_id": bc_record_id,
        "resolve_notes": resolve.notes,
        "resolved_utc": datetime.now(timezone.utc).isoformat(),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }

    if resolve.mark_no_po:
        update_data["po_status"] = "not_applicable"
    if link_error:
        update_data["last_error"] = link_error

    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})

    workflow = {
        "id": str(uuid.uuid4()),
        "document_id": doc_id,
        "workflow_name": "resolve_and_link",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Completed" if link_success else "PartialSuccess",
        "steps": [
            {"step": "resolve_selection", "status": "completed", "result": {
                "vendor_id": resolve.selected_vendor_id,
                "customer_id": resolve.selected_customer_id,
                "mark_no_po": resolve.mark_no_po,
            }},
            {"step": "bc_link", "status": "completed" if link_success else "failed",
             "result": {"success": link_success, "error": link_error}},
        ],
        "correlation_id": str(uuid.uuid4()),
        "error": link_error,
    }
    await db.hub_workflow_runs.insert_one(workflow)

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "success": link_success,
        "document": updated_doc,
        "message": "Document linked to BC" if link_success else f"Document stored in SharePoint. BC linking failed: {link_error}",
    }


async def reprocess_document(doc_id: str, reclassify: bool = Query(False)):
    """Safe reprocess — re-runs validation + vendor match only."""
    db = get_db()
    TransactionAction = _get_transaction_action()
    DEFAULT_JOB_TYPES = _get_default_job_types()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    if doc.get("status") == "LinkedToBC":
        return {"reprocessed": False, "reason": "Document already linked to BC - no reprocessing needed", "document": doc}

    if doc.get("bc_record_id"):
        return {"reprocessed": False, "reason": f"BC record already exists ({doc.get('bc_record_id')}) - idempotency guard", "document": doc}

    file_path = UPLOAD_DIR / doc_id
    if reclassify and file_path.exists():
        logger.info("Re-running AI classification for document %s", doc_id)
        classification = await _classify_with_ai(str(file_path), doc["file_name"])
        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "document_type": classification.get("suggested_job_type", "Unknown"),
            "suggested_job_type": classification.get("suggested_job_type", "Unknown"),
            "ai_confidence": classification.get("confidence", 0.0),
            "extracted_fields": classification.get("extracted_fields", {}),
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }})
        doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})

    job_type = doc.get("suggested_job_type", "AP_Invoice")
    job_configs = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(job_type, DEFAULT_JOB_TYPES["AP_Invoice"])

    extracted_fields = doc.get("extracted_fields", {})

    old_match_method = doc.get("match_method", "none")
    from services.bc_validation_service import validate_bc_match
    validation_results = await validate_bc_match(job_type, extracted_fields, job_configs)
    new_match_method = validation_results.get("match_method", "none")

    confidence = doc.get("ai_confidence", 0.0)
    decision, reasoning, decision_metadata = _make_automation_decision(job_configs, confidence, validation_results)

    old_status = doc.get("status")
    new_status = old_status
    transaction_action = doc.get("transaction_action", TransactionAction.NONE)
    share_link = doc.get("sharepoint_share_link_url")

    if validation_results.get("all_passed"):
        if share_link:
            new_status = "Validated"
            transaction_action = TransactionAction.VALIDATED
        else:
            new_status = "ValidationPassed"
    elif decision == "needs_review":
        new_status = "NeedsReview"

    workflow_status_map = {
        "Validated": "validated", "ValidationPassed": "validation_passed",
        "NeedsReview": "needs_review", "LinkedToBC": "linked_to_bc",
        "Posted": "posted", "ReadyForPost": "ready_for_post",
    }
    new_workflow_status = workflow_status_map.get(new_status, new_status.lower() if new_status else "pending")

    update_data = {
        "validation_results": validation_results,
        "automation_decision": decision,
        "match_method": new_match_method,
        "match_score": validation_results.get("match_score", 0.0),
        "vendor_candidates": decision_metadata.get("vendor_candidates", []),
        "customer_candidates": decision_metadata.get("customer_candidates", []),
        "status": new_status,
        "workflow_status": new_workflow_status,
        "square9_stage": new_workflow_status,
        "transaction_action": transaction_action,
        "reprocessed_utc": datetime.now(timezone.utc).isoformat(),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "last_error": None,
    }

    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})

    workflow = {
        "id": str(uuid.uuid4()),
        "document_id": doc_id,
        "workflow_name": "reprocess",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Completed",
        "steps": [
            {"step": "revalidation", "status": "completed", "result": {
                "old_match_method": old_match_method,
                "new_match_method": new_match_method,
                "validation_passed": validation_results.get("all_passed"),
                "decision": decision,
                "square9_aligned": True,
                "reason": "Square9 workflow: validate data, confirm SharePoint storage. BC attachment handled separately.",
            }},
            {"step": "status_transition", "status": "completed" if new_status != old_status else "no_change", "result": {
                "old_status": old_status, "new_status": new_status, "sharepoint_stored": bool(share_link),
            }},
        ],
        "correlation_id": str(uuid.uuid4()),
        "error": None,
    }
    await db.hub_workflow_runs.insert_one(workflow)

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "reprocessed": True,
        "status_changed": old_status != new_status,
        "old_status": old_status, "new_status": new_status,
        "match_method_changed": old_match_method != new_match_method,
        "old_match_method": old_match_method, "new_match_method": new_match_method,
        "validation_passed": validation_results.get("all_passed"),
        "sharepoint_stored": bool(share_link),
        "document": updated_doc,
        "reasoning": reasoning,
    }


async def batch_revalidate_documents(
    doc_types: List[str] = Query(default=["AP_Invoice", "AP_INVOICE", "Remittance"]),
    limit: int = Query(default=500, le=1000),
    skip_completed: bool = Query(default=True),
    background_tasks: BackgroundTasks = None,
):
    """Batch re-validate all documents against Production BC."""
    db = get_db()
    DEFAULT_JOB_TYPES = _get_default_job_types()

    query = {"doc_type": {"$in": doc_types}}
    if skip_completed:
        query["status"] = {"$nin": ["Completed", "Posted", "Archived", "LinkedToBC"]}

    cursor = db.hub_documents.find(query, {"_id": 0}).limit(limit)
    docs = await cursor.to_list(limit)

    if not docs:
        return {"message": "No documents to revalidate", "count": 0}

    from services.bc_validation_service import validate_bc_match

    results = {"total": len(docs), "success": 0, "failed": 0, "improved": 0, "unchanged": 0, "details": []}

    for doc in docs:
        doc_id = doc.get("id")
        try:
            job_type = doc.get("suggested_job_type", doc.get("doc_type", "AP_Invoice"))
            job_configs = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
            if not job_configs:
                job_configs = DEFAULT_JOB_TYPES.get(job_type, DEFAULT_JOB_TYPES.get("AP_Invoice", {}))

            extracted_fields = doc.get("extracted_fields", {})
            vendor_name = extracted_fields.get("vendor", doc.get("vendor_canonical", ""))

            old_match_method = doc.get("match_method", doc.get("validation_results", {}).get("match_method", "none"))
            old_validation_passed = doc.get("validation_results", {}).get("all_passed", False)

            validation_results = await validate_bc_match(job_type, extracted_fields, job_configs)
            new_match_method = validation_results.get("match_method", "none")
            new_validation_passed = validation_results.get("all_passed", False)

            confidence = doc.get("ai_confidence", 0.0)
            decision, reasoning, decision_metadata = _make_automation_decision(job_configs, confidence, validation_results)

            update_data = {
                "validation_results": validation_results,
                "match_method": new_match_method,
                "match_score": validation_results.get("match_score", 0.0),
                "automation_decision": decision,
                "vendor_candidates": decision_metadata.get("vendor_candidates", []),
                "revalidated_utc": datetime.now(timezone.utc).isoformat(),
                "revalidated_from": "batch_revalidate_production",
            }

            if validation_results.get("bc_record_info"):
                bc_info = validation_results["bc_record_info"]
                update_data["vendor_canonical"] = bc_info.get("displayName", vendor_name)
                update_data["bc_vendor_number"] = bc_info.get("number")

            if validation_results.get("unified_vendor_match"):
                update_data["unified_vendor_match"] = validation_results["unified_vendor_match"]

            await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})

            improved = (not old_validation_passed and new_validation_passed) or \
                       (old_match_method == "none" and new_match_method != "none")

            results["success"] += 1
            if improved:
                results["improved"] += 1
            else:
                results["unchanged"] += 1

            results["details"].append({
                "doc_id": doc_id[:8] + "...",
                "vendor": vendor_name[:30] if vendor_name else "N/A",
                "old_match": old_match_method, "new_match": new_match_method,
                "improved": improved, "validation_passed": new_validation_passed,
            })

        except Exception as e:
            results["failed"] += 1
            results["details"].append({"doc_id": doc_id[:8] + "...", "error": str(e)[:100]})
            logger.error("Batch revalidate error for %s: %s", doc_id, str(e))

    return results


async def preview_post_to_bc(doc_id: str, request: DryRunPreviewRequest = None):
    """DRY-RUN PREVIEW: Shows what would be posted to BC without writing."""
    import httpx
    db = get_db()

    def _parse_amount(value):
        if value is None:
            return None
        if isinstance(value, (int, float)):
            return float(value)
        try:
            cleaned = str(value).replace(",", "").replace("$", "").replace(" ", "").strip()
            return float(cleaned) if cleaned else None
        except (ValueError, TypeError):
            return None

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    PROD_TENANT_ID = request.bc_tenant_id if request and request.bc_tenant_id else os.environ.get("BC_PROD_TENANT_ID", "")
    PROD_ENVIRONMENT = request.bc_environment if request and request.bc_environment else os.environ.get("BC_PROD_ENVIRONMENT", "Production")
    PROD_CLIENT_ID = os.environ.get("BC_PROD_CLIENT_ID", "")
    PROD_CLIENT_SECRET = os.environ.get("BC_PROD_CLIENT_SECRET", "")

    if not PROD_TENANT_ID or not PROD_CLIENT_ID or not PROD_CLIENT_SECRET:
        return {
            "doc_id": doc_id, "dry_run": True,
            "error": "Production BC credentials not configured.",
            "errors": ["Missing BC_PROD_* environment variables"],
        }

    preview_result = {
        "doc_id": doc_id,
        "file_name": doc.get("file_name"),
        "document_type": doc.get("document_type") or doc.get("suggested_job_type"),
        "dry_run": True, "would_write_to_bc": False,
        "bc_environment_used": f"{PROD_TENANT_ID[:8]}.../{PROD_ENVIRONMENT}",
        "validation": {"passed": False, "checks": [], "warnings": []},
        "extracted_data": {},
        "purchase_invoice_preview": None,
        "sales_order_match": None,
        "folder_routing": None,
        "errors": [],
    }

    try:
        async with httpx.AsyncClient(timeout=30) as client:
            token_resp = await client.post(
                f"https://login.microsoftonline.com/{PROD_TENANT_ID}/oauth2/v2.0/token",
                data={
                    "client_id": PROD_CLIENT_ID, "client_secret": PROD_CLIENT_SECRET,
                    "scope": "https://api.businesscentral.dynamics.com/.default",
                    "grant_type": "client_credentials",
                },
            )

            if token_resp.status_code != 200:
                preview_result["errors"].append(f"Failed to get BC token: {token_resp.status_code}")
                return preview_result

            token = token_resp.json().get("access_token")

            companies_resp = await client.get(
                f"https://api.businesscentral.dynamics.com/v2.0/{PROD_TENANT_ID}/{PROD_ENVIRONMENT}/api/v2.0/companies",
                headers={"Authorization": f"Bearer {token}"},
            )

            if companies_resp.status_code != 200:
                preview_result["errors"].append(f"Failed to get BC companies: {companies_resp.status_code}")
                return preview_result

            companies = companies_resp.json().get("value", [])
            company_id = None
            for c in companies:
                if "Gamer" in c.get("name", ""):
                    company_id = c.get("id")
                    break
            if not company_id and companies:
                company_id = companies[0].get("id")

            if not company_id:
                preview_result["errors"].append("No BC company found")
                return preview_result

            # Extract data
            extracted_fields = doc.get("extracted_fields", {})
            normalized_fields = doc.get("normalized_fields", {})
            ai_extraction = doc.get("ai_extraction", {})

            vendor_name = (doc.get("vendor_canonical") or normalized_fields.get("vendor")
                           or extracted_fields.get("vendor") or ai_extraction.get("vendor"))
            invoice_number = (doc.get("invoice_number_clean") or normalized_fields.get("invoice_number")
                              or extracted_fields.get("invoice_number") or ai_extraction.get("invoice_number"))
            invoice_date = (doc.get("invoice_date") or normalized_fields.get("invoice_date")
                            or extracted_fields.get("invoice_date") or ai_extraction.get("invoice_date"))
            total_amount = (doc.get("amount_float") or normalized_fields.get("amount")
                            or extracted_fields.get("amount") or ai_extraction.get("total_amount"))
            order_reference = (doc.get("bol_number_extracted") or doc.get("po_number_extracted")
                               or normalized_fields.get("bol_number") or normalized_fields.get("po_number")
                               or extracted_fields.get("bol_number") or extracted_fields.get("po_number")
                               or extracted_fields.get("order_number") or ai_extraction.get("bol_number")
                               or ai_extraction.get("po_number"))

            preview_result["extracted_data"] = {
                "vendor": vendor_name, "invoice_number": invoice_number,
                "invoice_date": invoice_date, "total_amount": _parse_amount(total_amount),
                "order_reference": order_reference, "currency": doc.get("currency", "USD"),
            }

            # Vendor validation
            if vendor_name:
                from services.unified_vendor_matcher import match_vendor_unified
                unified_result = await match_vendor_unified(db, vendor_name, min_score=0.7)

                if unified_result.get("matched"):
                    best_match = unified_result.get("best_match", {})
                    preview_result["validation"]["checks"].append({
                        "check": "vendor_match", "passed": True,
                        "details": f"Found vendor via {unified_result.get('source')}: {best_match.get('name')} (score: {unified_result.get('score', 0):.0%})",
                        "sources_checked": unified_result.get("sources_checked", []),
                        "is_freight_carrier": unified_result.get("is_freight_carrier", False),
                    })
                    preview_result["extracted_data"]["vendor_number"] = best_match.get("vendor_number") or unified_result.get("bc_vendor_number")
                    preview_result["extracted_data"]["vendor_id"] = best_match.get("vendor_id") or unified_result.get("bc_vendor_id")
                    preview_result["extracted_data"]["vendor_display_name"] = best_match.get("name")
                    preview_result["extracted_data"]["is_freight_carrier"] = unified_result.get("is_freight_carrier", False)
                    preview_result["extracted_data"]["vendor_match_source"] = unified_result.get("source")
                else:
                    all_matches = unified_result.get("all_matches", [])
                    candidate_info = ""
                    if all_matches:
                        top = all_matches[0]
                        candidate_info = f" Best candidate: {top.get('name')} ({top.get('score', 0):.0%}) from {top.get('source')}"
                    preview_result["validation"]["checks"].append({
                        "check": "vendor_match", "passed": False,
                        "details": f"No vendor found matching '{vendor_name}' (checked: {', '.join(unified_result.get('sources_checked', []))}).{candidate_info}",
                        "sources_checked": unified_result.get("sources_checked", []),
                        "candidates": [{"name": m.get("name"), "score": m.get("score"), "source": m.get("source")} for m in all_matches[:3]],
                    })

            # Freight direction
            bc_base = f"https://api.businesscentral.dynamics.com/v2.0/{PROD_TENANT_ID}/{PROD_ENVIRONMENT}/api/v2.0/companies({company_id})"
            freight_direction = "unknown"

            if order_reference:
                order_str = str(order_reference).strip()

                order_resp = await client.get(
                    f"{bc_base}/salesOrders",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$filter": f"number eq '{order_str}'"},
                )
                if order_resp.status_code == 200:
                    orders = order_resp.json().get("value", [])
                    if orders:
                        matched_order = orders[0]
                        freight_direction = "outbound"
                        preview_result["freight_direction"] = "outbound"
                        preview_result["freight_direction_details"] = {
                            "direction": "outbound", "reason": "Order reference matches a Sales Order",
                            "description": "Freight cost for shipping TO customer",
                        }
                        preview_result["sales_order_match"] = {
                            "found": True, "number": matched_order.get("number"),
                            "customer_name": matched_order.get("customerName"),
                            "customer_number": matched_order.get("customerNumber"),
                            "order_date": matched_order.get("orderDate"),
                            "status": matched_order.get("status"),
                            "total_amount": matched_order.get("totalAmountIncludingTax"),
                        }
                        preview_result["validation"]["checks"].append({
                            "check": "freight_direction", "passed": True,
                            "details": f"OUTBOUND freight - Order {order_str} matches Sales Order for {matched_order.get('customerName')}",
                        })

                if freight_direction == "unknown":
                    po_resp = await client.get(
                        f"{bc_base}/purchaseOrders",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$filter": f"number eq '{order_str}'"},
                    )
                    if po_resp.status_code == 200:
                        pos = po_resp.json().get("value", [])
                        if pos:
                            matched_po = pos[0]
                            freight_direction = "inbound"
                            preview_result["freight_direction"] = "inbound"
                            preview_result["freight_direction_details"] = {
                                "direction": "inbound", "reason": "Order reference matches a Purchase Order",
                                "description": "Freight cost for receiving FROM vendor/supplier",
                            }
                            preview_result["purchase_order_match"] = {
                                "found": True, "number": matched_po.get("number"),
                                "vendor_name": matched_po.get("vendorName"),
                                "vendor_number": matched_po.get("vendorNumber"),
                                "order_date": matched_po.get("orderDate"),
                                "status": matched_po.get("status"),
                                "total_amount": matched_po.get("totalAmountIncludingTax"),
                            }
                            preview_result["validation"]["checks"].append({
                                "check": "freight_direction", "passed": True,
                                "details": f"INBOUND freight - Order {order_str} matches Purchase Order from {matched_po.get('vendorName')}",
                            })

                if freight_direction == "unknown":
                    preview_result["freight_direction"] = "unknown"
                    preview_result["freight_direction_details"] = {
                        "direction": "unknown",
                        "reason": f"Order reference '{order_str}' not found in Sales Orders or Purchase Orders",
                        "description": "Could not determine freight direction - manual review needed",
                    }
                    preview_result["validation"]["warnings"].append({
                        "check": "freight_direction",
                        "details": f"Could not determine freight direction - '{order_str}' not found as Sales Order or Purchase Order",
                    })
            else:
                preview_result["freight_direction"] = "unknown"
                preview_result["freight_direction_details"] = {
                    "direction": "unknown", "reason": "No order reference extracted from document",
                    "description": "Cannot determine freight direction without BOL/Order number",
                }
                preview_result["validation"]["warnings"].append({
                    "check": "freight_direction",
                    "details": "No order reference found - cannot determine if inbound or outbound freight",
                })

            # Duplicate check
            if invoice_number:
                dup_resp = await client.get(
                    f"{bc_base}/purchaseInvoices",
                    headers={"Authorization": f"Bearer {token}"},
                    params={"$filter": f"vendorInvoiceNumber eq '{invoice_number}'"},
                )
                if dup_resp.status_code == 200:
                    existing = dup_resp.json().get("value", [])
                    if existing:
                        preview_result["validation"]["checks"].append({
                            "check": "duplicate_check", "passed": False,
                            "details": f"DUPLICATE: Invoice {invoice_number} already exists in BC",
                        })
                    else:
                        preview_result["validation"]["checks"].append({
                            "check": "duplicate_check", "passed": True,
                            "details": "No duplicate invoice found",
                        })

            # Build preview
            line_description = order_reference if order_reference else "Freight"
            preview_result["purchase_invoice_preview"] = {
                "header": {
                    "vendorNumber": preview_result["extracted_data"].get("vendor_number", "[VENDOR NOT MATCHED]"),
                    "vendorInvoiceNumber": invoice_number,
                    "invoiceDate": invoice_date,
                    "dueDate": doc.get("due_date_iso"),
                    "currencyCode": doc.get("currency", "USD"),
                },
                "lines": [{
                    "lineType": "Item", "itemNumber": "FREIGHT",
                    "description": str(line_description)[:100],
                    "quantity": 1, "unitCost": _parse_amount(total_amount) or 0,
                }],
                "note": "This is what WOULD be posted. No data was written.",
            }

            # Folder routing
            from services.folder_routing_service import determine_folder_path
            folder_path, routing_reason, routing_details = determine_folder_path(
                doc, freight_direction=preview_result.get("freight_direction"), is_international=False,
            )
            preview_result["folder_routing"] = {
                "folder_path": folder_path, "routing_reason": routing_reason, "routing_details": routing_details,
            }

            all_checks_passed = all(c.get("passed", False) for c in preview_result["validation"]["checks"])
            preview_result["validation"]["passed"] = all_checks_passed

            if all_checks_passed:
                preview_result["would_write_to_bc"] = True
                preview_result["ready_to_post"] = True
            else:
                preview_result["ready_to_post"] = False
                preview_result["blocking_issues"] = [
                    c["details"] for c in preview_result["validation"]["checks"] if not c.get("passed")
                ]

    except Exception as e:
        logger.error("Preview-post error for %s: %s", doc_id, str(e))
        preview_result["errors"].append(str(e))

    return preview_result
