"""
HTTP document intake orchestration.

The non-bytes intake handler and its preserved Step 4d.7 server-shim call
site are kept together here. The parity-sensitive intake_document_from_bytes
implementation remains in services.document_handlers.
"""

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import File, Form, UploadFile

from deps import get_db
from services.ap_computation import (
    compute_ap_validation as _compute_ap_validation,
    is_eligible_for_draft_creation as _is_eligible_for_draft,
)
from services.bc_api_helpers import (
    get_bc_companies as _get_bc_companies,
)
from services.bc_draft_service import (
    check_duplicate_purchase_invoice as _check_duplicate_purchase_invoice,
    create_purchase_invoice_header as _create_purchase_invoice_header,
)
from services.bc_link_service import (
    link_document_to_bc as _link_document_to_bc,
)
from services.classification_helpers import (
    classify_document_type as _classify_document_type,
)
from services.config_service import (
    get_bc_token as _get_bc_token,
)
from services.document_intel_helpers import (
    classify_document_with_ai as _classify_with_ai,
    compute_ap_normalized_fields as _compute_ap_normalized,
    make_automation_decision as _make_automation_decision,
)
from services.sharepoint_service import (
    create_sharing_link as _create_sharing_link,
    upload_to_sharepoint as _upload_to_sharepoint,
)
from services.vendor_matching import (
    check_duplicate_document as _check_duplicate,
    lookup_vendor_alias as _lookup_vendor_alias,
)

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(
    os.environ.get("UPLOAD_DIR", "/app/backend/uploads")
)
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _derive_workflow_status_simple(
    final_status: str,
    decision: str,
) -> str:
    """Map processing results to the persisted workflow status."""
    status = (final_status or "").lower()

    if status in ("completed", "posted", "archived"):
        return "completed"

    if status == "exception":
        return "exception"

    if status in ("readytolink", "linkedtobc"):
        return "ready_for_approval"

    if status == "storedinsp":
        return "processed"

    if decision == "auto_link":
        return "validation_passed"

    if status == "needsreview":
        return "needs_review"

    return "classified"


def _get_workflow_enums():
    from workflows.core.engine import (
        CaptureChannel,
        DocType,
        DocumentClassifier,
        SourceSystem,
        WorkflowEvent,
        WorkflowStatus,
    )

    return (
        DocType,
        SourceSystem,
        CaptureChannel,
        WorkflowStatus,
        WorkflowEvent,
        DocumentClassifier,
    )


def _get_transaction_action():
    from models.document_types import TransactionAction

    return TransactionAction


def _get_default_job_types():
    from models.document_types import DEFAULT_JOB_TYPES

    return DEFAULT_JOB_TYPES


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
    classification_result = await _classify_document_type(
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
        sp_result = await _upload_to_sharepoint(file_content, final_filename, folder)
        share_link = await _create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
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
        "bc_vendor_number": (
            vendor_alias_result.get("vendor_no")
            or (validation_results.get("bc_record_info") or {}).get("number")
        ),
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

    # ---------------------------------------------------------------
    # Persist evidence-based AP routing decision (mission-aligned audit).
    # See services.folder_routing_service.determine_ap_routing_decision.
    # ---------------------------------------------------------------
    try:
        from services.folder_routing_service import determine_ap_routing_decision
        _routing_input_doc = {
            "document_type": suggested_type,
            "doc_type": doc_type_value,
            "suggested_job_type": suggested_type,
            "mailbox_category": doc.get("mailbox_category"),
            "mailbox_lane_needs_review": bool(classification_result.get("mailbox_lane_needs_review")),
            "classification_method": classification_method,
            "ai_confidence": confidence,
            "vendor_canonical": vendor_alias_result.get("vendor_canonical"),
            "vendor_match_method": vendor_alias_result.get("vendor_match_method"),
            "po_number_clean": normalized_fields.get("po_number_clean"),
            "po_number_extracted": normalized_fields.get("po_number_clean") or extracted_fields.get("po_number"),
            "invoice_number_clean": normalized_fields.get("invoice_number_clean"),
            "amount_float": normalized_fields.get("amount_float"),
            "validation_results": validation_results,
            "possible_duplicate": duplicate_result.get("possible_duplicate", False),
            "extracted_fields": extracted_fields,
            "normalized_fields": normalized_fields,
            "file_name": doc.get("file_name", ""),
            "bc_po_resolved": validation_results.get("bc_po_resolved"),
            "accounting_routing_override": False,
            "approved": False,
        }
        _routing_decision = determine_ap_routing_decision(_routing_input_doc)
        update_data["routing_status"] = _routing_decision["routing_status"]
        update_data["routing_reason"] = _routing_decision["routing_reason"]
        update_data["routing_details"] = _routing_decision["routing_details"]
    except Exception as _re:
        logger.warning("Routing decision persistence failed for %s: %s", doc_id, _re)
        update_data["routing_status"] = "needs_review"
        update_data["routing_reason"] = f"routing_decision_error: {_re}"
        update_data["routing_details"] = {"error": str(_re)}

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
                token = await _get_bc_token()
                companies = await _get_bc_companies()
                company_id = companies[0]["id"] if companies else None

                dup_check = await _check_duplicate_purchase_invoice(
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
                    draft_result = await _create_purchase_invoice_header(
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
                        link_result = await _link_document_to_bc(
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
                link_result = await _link_document_to_bc(
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

    # Preserve the existing non-bytes intake workflow-status call site.
    # Step 4d.7 only migrated the import inside intake_document_from_bytes.
    if suggested_type not in ("AP_Invoice", "AP Invoice"):
        from server import _update_standard_workflow_status
        await _update_standard_workflow_status(
            doc_id,
            doc_type_value,
            confidence,
            normalized_fields,
        )

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})

    # Incremental vendor profile update
    try:
        vendor_name = (
            update_data.get("vendor_canonical")
            or update_data.get("matched_vendor_name")
            or update_data.get("vendor_raw")
        )
        if vendor_name:
            # Orchestration Extraction (v2.5.2) — imports direct from service
            # module; no more `from server import ...` late-resolution.
            from workflows.ap_invoice.rules.vendor_profile import update_vendor_profile_incremental
            await update_vendor_profile_incremental(db, doc_id, vendor_name, update_data, final_status)
    except Exception as e:
        logger.error("[VendorProfile] Error updating profile for doc %s: %s", doc_id, str(e))

    return {
        "document": updated_doc,
        "classification": classification,
        "validation": validation_results,
        "decision": decision,
        "reasoning": reasoning,
        "draft_result": draft_result,
        "transaction_action": transaction_action,
    }
