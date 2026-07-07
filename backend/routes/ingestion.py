"""
Document ingestion HTTP endpoints: intake, classify, resolve, reprocess.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 9). No logic changed. The actual
business logic (classification, validation, matching) lives in
services/ingestion_engine.py; this module is the thin HTTP layer over it.
"""
import uuid
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from pydantic import BaseModel

from core.db import db
from core.paths import UPLOAD_DIR
from core.job_config import DEFAULT_JOB_TYPES, TransactionAction
from core.legacy_hub_helpers import (
    upload_to_sharepoint, create_sharing_link, get_bc_token, get_bc_companies,
    link_document_to_bc,
)
from services.workflow_engine import WorkflowStatus, WorkflowEvent, DocType, SourceSystem, CaptureChannel
from services.pilot_config import PILOT_MODE_ENABLED, get_pilot_capture_channel, get_pilot_metadata
from services.ingestion_engine import (
    classify_document_with_ai, classify_document_type,
    compute_ap_normalized_fields, lookup_vendor_alias, check_duplicate_document,
    compute_ap_validation, validate_bc_match, make_automation_decision,
    _update_ap_workflow_status, _update_standard_workflow_status,
)
from services.auto_post_service import AUTO_POST_ENABLED, attempt_auto_post
from services.business_central_service import get_bc_service

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

@router.post("/documents/intake")
async def intake_document(
    file: UploadFile = File(...),
    source: str = Form("email"),
    sender: Optional[str] = Form(None),
    subject: Optional[str] = Form(None),
    attachment_name: Optional[str] = Form(None),
    content_hash: Optional[str] = Form(None),
    email_id: Optional[str] = Form(None),
    email_received_utc: Optional[str] = Form(None)
):
    """
    Receive a document from email or other source.
    Runs AI classification and automation decision matrix.
    """
    file_content = await file.read()
    computed_hash = hashlib.sha256(file_content).hexdigest()
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # Use provided attachment name or fall back to filename
    final_filename = attachment_name or file.filename
    
    # Store file locally
    file_path = UPLOAD_DIR / doc_id
    file_path.write_bytes(file_content)
    
    # Create document record with workflow tracking
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
        "sharepoint_drive_id": None,
        "sharepoint_item_id": None,
        "sharepoint_web_url": None,
        "sharepoint_share_link_url": None,
        "document_type": None,
        "category": None,
        "suggested_job_type": None,
        "ai_confidence": None,
        "extracted_fields": None,
        "validation_results": None,
        "automation_decision": None,
        "bc_record_type": None,
        "bc_company_id": None,
        "bc_record_id": None,
        "bc_document_no": None,
        "status": "Received",
        # Document classification fields (will be updated after AI classification)
        "doc_type": DocType.OTHER.value,
        "source_system": SourceSystem.GPI_HUB_NATIVE.value,
        "capture_channel": get_pilot_capture_channel(CaptureChannel.EMAIL.value if "email" in source.lower() else CaptureChannel.UPLOAD.value) if PILOT_MODE_ENABLED else (CaptureChannel.EMAIL.value if "email" in source.lower() else CaptureChannel.UPLOAD.value),
        # Workflow tracking fields
        "workflow_status": WorkflowStatus.CAPTURED.value,
        "workflow_history": [{
            "timestamp": now,
            "from_status": None,
            "to_status": WorkflowStatus.CAPTURED.value,
            "event": WorkflowEvent.ON_CAPTURE.value,
            "actor": "system",
            "reason": f"Document captured from {source}",
            "metadata": {"source": source, "sender": sender}
        }],
        "workflow_status_updated_utc": now,
        "created_utc": now,
        "updated_utc": now,
        "last_error": None,
        # Pilot metadata (added if pilot mode enabled)
        **get_pilot_metadata()
    }
    await db.hub_documents.insert_one(doc)
    
    # Run AI field extraction (for extracting vendor, amount, etc.)
    logger.info("Running AI field extraction for document %s", doc_id)
    classification = await classify_document_with_ai(str(file_path), final_filename)
    
    suggested_type = classification.get("suggested_job_type", "Unknown")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})
    
    # Deterministic-first document type classification
    # Step 1: Try deterministic rules (Zetadocs, Square9, mailbox category)
    # Step 2: If still OTHER, try AI classification if enabled
    classification_result = await classify_document_type(
        document=doc,
        extracted_fields=extracted_fields,
        suggested_type=suggested_type,
        confidence=confidence,
        metadata={
            "mailbox_category": doc.get("mailbox_category"),
            "zetadocs_set": doc.get("zetadocs_set_code"),
            "square9_workflow": doc.get("square9_workflow_name")
        }
    )
    
    doc_type_value = classification_result["doc_type"]
    category = classification_result["category"]
    ai_classification_audit = classification_result.get("ai_classification")
    classification_method = classification_result.get("classification_method", "unknown")
    
    logger.info(
        "Document %s classified as %s (category: %s, method: %s)",
        doc_id, doc_type_value, category, classification_method
    )
    
    # Phase 7: Compute normalized fields (flat, stored on document)
    normalized_fields = compute_ap_normalized_fields(extracted_fields)
    
    # Phase 7: Vendor alias lookup
    vendor_alias_result = await lookup_vendor_alias(normalized_fields.get("vendor_normalized"))
    
    # Phase 7: Duplicate check
    duplicate_result = await check_duplicate_document(
        vendor_normalized=normalized_fields.get("vendor_normalized"),
        vendor_canonical=vendor_alias_result.get("vendor_canonical"),
        invoice_number_clean=normalized_fields.get("invoice_number_clean"),
        current_doc_id=doc_id
    )
    
    # Phase 7: Compute validation errors/warnings and draft_candidate
    ap_validation = compute_ap_validation(
        document_type=suggested_type,
        vendor_normalized=normalized_fields.get("vendor_normalized"),
        invoice_number_clean=normalized_fields.get("invoice_number_clean"),
        amount_float=normalized_fields.get("amount_float"),
        po_number_clean=normalized_fields.get("po_number_clean"),
        ai_confidence=confidence,
        possible_duplicate=duplicate_result.get("possible_duplicate", False)
    )
    
    # Get job type config
    job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])
    
    # Run BC validation
    validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)
    
    # Make automation decision (returns 3-tuple with metadata)
    decision, reasoning, decision_metadata = make_automation_decision(job_configs, confidence, validation_results)
    
    # Get BC entity for linking
    bc_entity = job_configs.get("bc_entity", "salesOrders")
    
    # ALWAYS upload to SharePoint first - regardless of validation status
    # This ensures document is preserved even if BC linking fails
    folder = job_configs.get("sharepoint_folder", "Incoming")
    sp_result = None
    share_link = None
    sp_error = None
    
    try:
        sp_result = await upload_to_sharepoint(file_content, final_filename, folder)
        share_link = await create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
        logger.info("Document %s stored in SharePoint: %s", doc_id, sp_result.get("web_url"))
    except Exception as e:
        sp_error = str(e)
        logger.error("SharePoint upload failed for document %s: %s", doc_id, sp_error)
    
    # Phase 7: Determine status for AP_Invoice using new logic
    if suggested_type in ("AP_Invoice", "AP Invoice"):
        # All AP_Invoice documents stay in NeedsReview during Phase 7
        final_status = "NeedsReview"
    else:
        # Non-AP documents use existing logic
        if sp_result:
            final_status = "StoredInSP"
        else:
            final_status = "Classified"
    
    # Update document with classification + SharePoint results
    update_data = {
        "suggested_job_type": suggested_type,
        "document_type": suggested_type,
        "ai_confidence": confidence,
        "extracted_fields": extracted_fields,
        # Document classification fields
        "doc_type": doc_type_value,
        "category": category,
        "classification_method": classification_method,
        # Phase 7: Flat normalized fields on document
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
        # Phase 8: Invoice date and line items for automatic BC posting
        "invoice_date": normalized_fields.get("invoice_date"),
        "invoice_date_raw": normalized_fields.get("invoice_date_raw"),
        "line_items": normalized_fields.get("line_items", []),
        # Phase 7: Vendor alias results
        "vendor_canonical": vendor_alias_result.get("vendor_canonical"),
        "vendor_match_method": vendor_alias_result.get("vendor_match_method"),
        # Phase 7: Duplicate detection
        "possible_duplicate": duplicate_result.get("possible_duplicate", False),
        "duplicate_of_document_id": duplicate_result.get("duplicate_of_document_id"),
        # Phase 7: Validation errors/warnings and draft_candidate
        "validation_errors": ap_validation.get("validation_errors", []),
        "validation_warnings": ap_validation.get("validation_warnings", []),
        "draft_candidate": ap_validation.get("draft_candidate", False),
        # Legacy fields for backward compat
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
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }
    
    # Add SharePoint info if successful
    if sp_result:
        update_data["sharepoint_drive_id"] = sp_result["drive_id"]
        update_data["sharepoint_item_id"] = sp_result["item_id"]
        update_data["sharepoint_web_url"] = sp_result["web_url"]
        update_data["sharepoint_share_link_url"] = share_link
    else:
        update_data["last_error"] = f"SharePoint upload failed: {sp_error}"
    
    # Add AI classification audit trail if AI was invoked
    if ai_classification_audit:
        update_data["ai_classification"] = ai_classification_audit
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    
    # Create workflow run for intake
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
            "warnings_count": len(validation_results.get("warnings", []))
        }},
        {"step": "automation_decision", "status": "completed", "result": {"decision": decision, "reasoning": reasoning}}
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
        "error": None
    }
    await db.hub_workflow_runs.insert_one(workflow)
    
    # Execute BC action based on decision (only if SharePoint upload succeeded)
    final_status = update_data["status"]
    transaction_action = TransactionAction.NONE
    draft_result = None
    
    if sp_result and (decision == "auto_link" or decision == "auto_create"):
        bc_record_id = validation_results.get("bc_record_id")
        match_method = validation_results.get("match_method", "none")
        match_score = validation_results.get("match_score", 0.0)
        
        # Check if eligible for draft creation (Phase 4)
        # Fetch current doc state for eligibility check
        current_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        is_draft_eligible, draft_reason = is_eligible_for_draft_creation(
            job_type=suggested_type,
            match_method=match_method,
            match_score=match_score,
            ai_confidence=confidence,
            validation_results=validation_results,
            doc=current_doc
        )
        
        if is_draft_eligible and suggested_type == "AP_Invoice":
            # CREATE DRAFT HEADER - Phase 4
            logger.info("Document %s eligible for draft creation: %s", doc_id, draft_reason)
            
            # Get vendor info for draft
            vendor_info = validation_results.get("bc_record_info", {})
            vendor_no = vendor_info.get("number", "")
            normalized_fields = validation_results.get("normalized_fields", {})
            external_doc_no = normalized_fields.get("invoice_number") or extracted_fields.get("invoice_number", "")
            
            if vendor_no and external_doc_no:
                # Run duplicate check one more time (defense in depth)
                token = await get_bc_token()
                companies = await get_bc_companies()
                company_id = companies[0]["id"] if companies else None
                
                dup_check = await check_duplicate_purchase_invoice(
                    vendor_no=vendor_no,
                    external_doc_no=external_doc_no,
                    company_id=company_id,
                    token=token
                )
                
                if dup_check.get("found"):
                    # Duplicate found - hard stop
                    logger.warning(
                        "Duplicate invoice found during draft creation for doc %s: %s",
                        doc_id, dup_check.get("existing_invoice_no")
                    )
                    final_status = "NeedsReview"
                    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                        "status": "NeedsReview",
                        "transaction_action": TransactionAction.NONE,
                        "last_error": f"Duplicate invoice exists: {dup_check.get('existing_invoice_no')}",
                        "updated_utc": datetime.now(timezone.utc).isoformat()
                    }})
                else:
                    # Create the draft
                    draft_result = await create_purchase_invoice_header(
                        vendor_no=vendor_no,
                        external_doc_no=external_doc_no,
                        document_date=normalized_fields.get("invoice_date") or normalized_fields.get("due_date_raw"),
                        due_date=normalized_fields.get("due_date"),
                        posting_date=None,  # Let BC use today
                        company_id=company_id,
                        token=token
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
                            "updated_utc": datetime.now(timezone.utc).isoformat()
                        }})
                        logger.info(
                            "Draft Purchase Invoice created for doc %s: %s",
                            doc_id, draft_result.get("invoice_no")
                        )
                    else:
                        # Draft creation failed - fallback to needs review
                        logger.error(
                            "Draft creation failed for doc %s: %s",
                            doc_id, draft_result.get("error")
                        )
                        final_status = "NeedsReview"
                        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                            "status": "NeedsReview",
                            "transaction_action": TransactionAction.NONE,
                            "last_error": f"Draft creation failed: {draft_result.get('error')}",
                            "updated_utc": datetime.now(timezone.utc).isoformat()
                        }})
            else:
                # Missing required fields for draft - fallback to link only
                logger.warning("Missing vendor_no or external_doc_no for draft creation, falling back to link")
                if bc_record_id:
                    try:
                        link_result = await link_document_to_bc(
                            bc_record_id=bc_record_id,
                            share_link=share_link,
                            file_name=final_filename,
                            file_content=file_content,
                            bc_entity=bc_entity
                        )
                        if link_result.get("success"):
                            final_status = "LinkedToBC"
                            transaction_action = TransactionAction.LINKED_ONLY
                            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                                "bc_record_id": bc_record_id,
                                "transaction_action": TransactionAction.LINKED_ONLY,
                                "status": "LinkedToBC",
                                "updated_utc": datetime.now(timezone.utc).isoformat()
                            }})
                    except Exception as e:
                        logger.error("BC linking failed for document %s: %s", doc_id, str(e))
        
        elif bc_record_id:
            # Standard auto-link flow (Level 1 or not eligible for draft)
            try:
                link_result = await link_document_to_bc(
                    bc_record_id=bc_record_id,
                    share_link=share_link,
                    file_name=final_filename,
                    file_content=file_content,
                    bc_entity=bc_entity
                )
                if link_result.get("success"):
                    final_status = "LinkedToBC"
                    transaction_action = TransactionAction.LINKED_ONLY
                    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                        "bc_record_id": bc_record_id,
                        "transaction_action": TransactionAction.LINKED_ONLY,
                        "status": "LinkedToBC",
                        "updated_utc": datetime.now(timezone.utc).isoformat()
                    }})
            except Exception as e:
                logger.error("BC linking failed for document %s: %s", doc_id, str(e))
    
    elif decision == "needs_review":
        final_status = "NeedsReview"
        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "status": "NeedsReview",
            "transaction_action": TransactionAction.NONE,
            "updated_utc": datetime.now(timezone.utc).isoformat()
        }})
    
    # Return result
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "document": updated_doc,
        "classification": classification,
        "validation": validation_results,
        "decision": decision,
        "reasoning": reasoning,
        "draft_result": draft_result,
        "transaction_action": transaction_action
    }

@router.post("/documents/{doc_id}/classify")
async def classify_document(doc_id: str):
    """Re-run AI classification on an existing document."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found")
    
    classification = await classify_document_with_ai(str(file_path), doc["file_name"])
    
    suggested_type = classification.get("suggested_job_type", "Unknown")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})
    
    # Get job type config
    job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])
    
    # Run BC validation
    validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)
    
    # Make automation decision
    decision, reasoning, decision_metadata = make_automation_decision(job_configs, confidence, validation_results)
    
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
        "updated_utc": datetime.now(timezone.utc).isoformat()
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
            "customers": decision_metadata.get("customer_candidates", [])
        }
    }

# ==================== RESOLVE AND LINK ENDPOINT ====================

class ResolveRequest(BaseModel):
    selected_vendor_id: Optional[str] = None
    selected_customer_id: Optional[str] = None
    selected_po_number: Optional[str] = None
    mark_no_po: bool = False  # Mark as non-PO invoice
    notes: Optional[str] = None

@router.post("/documents/{doc_id}/resolve")
async def resolve_and_link_document(doc_id: str, resolve: ResolveRequest):
    """
    Resolve a NeedsReview document by selecting vendor/customer from candidates.
    Then link to BC and update status.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc.get("status") not in ("NeedsReview", "StoredInSP", "Classified"):
        raise HTTPException(status_code=400, detail=f"Document status must be NeedsReview, StoredInSP, or Classified. Current: {doc.get('status')}")
    
    file_path = UPLOAD_DIR / doc_id
    file_content = None
    if file_path.exists():
        file_content = file_path.read_bytes()
    
    # Determine what BC record to link to
    bc_record_id = None
    bc_record_type = doc.get("suggested_job_type", "AP_Invoice")
    
    if resolve.selected_vendor_id:
        bc_record_id = resolve.selected_vendor_id
    elif resolve.selected_customer_id:
        bc_record_id = resolve.selected_customer_id
    elif doc.get("validation_results", {}).get("bc_record_id"):
        # Use existing validated record
        bc_record_id = doc["validation_results"]["bc_record_id"]
    
    # Ensure document is in SharePoint
    share_link = doc.get("sharepoint_share_link_url")
    if not share_link and file_content:
        # Upload to SharePoint now
        job_configs = await db.hub_job_types.find_one({"job_type": bc_record_type}, {"_id": 0})
        if not job_configs:
            job_configs = DEFAULT_JOB_TYPES.get(bc_record_type, DEFAULT_JOB_TYPES["AP_Invoice"])
        
        folder = job_configs.get("sharepoint_folder", "Incoming")
        bc_entity = job_configs.get("bc_entity", "salesOrders")
        try:
            sp_result = await upload_to_sharepoint(file_content, doc["file_name"], folder)
            share_link = await create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
            
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "sharepoint_drive_id": sp_result["drive_id"],
                "sharepoint_item_id": sp_result["item_id"],
                "sharepoint_web_url": sp_result["web_url"],
                "sharepoint_share_link_url": share_link,
                "status": "StoredInSP",
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }})
        except Exception as e:
            raise HTTPException(status_code=500, detail=f"SharePoint upload failed: {str(e)}")
    
    # Link to BC if we have a record and file content
    link_success = False
    link_error = None
    
    if bc_record_id and file_content:
        try:
            link_result = await link_document_to_bc(
                bc_record_id=bc_record_id,
                share_link=share_link or "",
                file_name=doc["file_name"],
                file_content=file_content,
                bc_entity=bc_entity
            )
            link_success = link_result.get("success", False)
            if not link_success:
                link_error = link_result.get("error", "Unknown error")
        except Exception as e:
            link_error = str(e)
    
    # Update document status
    final_status = "LinkedToBC" if link_success else "StoredInSP"
    update_data = {
        "status": final_status,
        "bc_record_id": bc_record_id,
        "resolve_notes": resolve.notes,
        "resolved_utc": datetime.now(timezone.utc).isoformat(),
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }
    
    if resolve.mark_no_po:
        update_data["po_status"] = "not_applicable"
    
    if link_error:
        update_data["last_error"] = link_error
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    
    # Log workflow
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
                "mark_no_po": resolve.mark_no_po
            }},
            {"step": "bc_link", "status": "completed" if link_success else "failed", 
             "result": {"success": link_success, "error": link_error}}
        ],
        "correlation_id": str(uuid.uuid4()),
        "error": link_error
    }
    await db.hub_workflow_runs.insert_one(workflow)
    
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "success": link_success,
        "document": updated_doc,
        "message": "Document linked to BC" if link_success else f"Document stored in SharePoint. BC linking failed: {link_error}"
    }

# ==================== SAFE REPROCESS ENDPOINT ====================

@router.post("/documents/{doc_id}/reprocess")
async def reprocess_document(doc_id: str, reclassify: bool = Query(False)):
    """
    Safe reprocess endpoint - re-runs validation + vendor match only.
    Set reclassify=true to also re-run AI classification.
    
    Rules:
    - Do NOT duplicate SharePoint uploads
    - Do NOT create new BC records if already linked
    - Do NOT create draft invoices (drafts only during initial intake)
    - If alias now matches → transition from NeedsReview → LinkedToBC (via linking, not draft)
    - Must be idempotent
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Cannot reprocess already-linked documents
    if doc.get("status") == "LinkedToBC":
        return {
            "reprocessed": False,
            "reason": "Document already linked to BC - no reprocessing needed",
            "document": doc
        }
    
    # Idempotency check: If bc_record_id exists, document was already processed
    if doc.get("bc_record_id"):
        return {
            "reprocessed": False,
            "reason": f"BC record already exists ({doc.get('bc_record_id')}) - idempotency guard",
            "document": doc
        }
    
    # Get the file content for BC linking (if needed)
    file_path = UPLOAD_DIR / doc_id
    file_content = None
    if file_path.exists():
        file_content = file_path.read_bytes()
    
    # Re-run AI classification if requested
    if reclassify and file_path.exists():
        logger.info("Re-running AI classification for document %s", doc_id)
        classification = await classify_document_with_ai(str(file_path), doc["file_name"])
        
        # Update document with new classification
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "document_type": classification.get("suggested_job_type", "Unknown"),
                "suggested_job_type": classification.get("suggested_job_type", "Unknown"),
                "ai_confidence": classification.get("confidence", 0.0),
                "extracted_fields": classification.get("extracted_fields", {}),
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }}
        )
        # Reload the document
        doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    
    # Get job config
    job_type = doc.get("suggested_job_type", "AP_Invoice")
    job_configs = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(job_type, DEFAULT_JOB_TYPES["AP_Invoice"])
    
    # Get extracted fields
    extracted_fields = doc.get("extracted_fields", {})
    
    # Re-run BC validation (this will use any new aliases)
    old_match_method = doc.get("match_method", "none")
    validation_results = await validate_bc_match(job_type, extracted_fields, job_configs)
    new_match_method = validation_results.get("match_method", "none")
    
    # Make new automation decision
    confidence = doc.get("ai_confidence", 0.0)
    decision, reasoning, decision_metadata = make_automation_decision(job_configs, confidence, validation_results)
    
    # Determine if status should change
    old_status = doc.get("status")
    new_status = old_status
    transaction_action = doc.get("transaction_action", TransactionAction.NONE)
    
    # Square9 Workflow Alignment:
    # Reprocess validates data and confirms SharePoint storage.
    # It does NOT create BC records or attach documents to BC.
    # BC record creation/attachment happens outside this workflow (manual or separate process).
    share_link = doc.get("sharepoint_share_link_url")
    
    if validation_results.get("all_passed"):
        # Validation passed - document is ready for downstream processing
        if share_link:
            # Document is validated AND stored in SharePoint - success per Square9 workflow
            new_status = "Validated"
            transaction_action = TransactionAction.VALIDATED
        else:
            # Validation passed but no SharePoint link yet - needs SP upload
            new_status = "ValidationPassed"
    elif decision == "needs_review":
        new_status = "NeedsReview"
    
    # Update document
    # Map status to workflow_status for consistency in queue display
    workflow_status_map = {
        "Validated": "validated",
        "ValidationPassed": "validation_passed",
        "NeedsReview": "needs_review",
        "LinkedToBC": "linked_to_bc",
        "Posted": "posted",
        "ReadyForPost": "ready_for_post"
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
        "workflow_status": new_workflow_status,  # Keep workflow_status in sync
        "square9_stage": new_workflow_status,    # Also update square9_stage
        "transaction_action": transaction_action,
        "reprocessed_utc": datetime.now(timezone.utc).isoformat(),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "last_error": None  # Clear any previous errors on successful reprocess
    }
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    
    # Log reprocess workflow (Square9 aligned)
    workflow = {
        "id": str(uuid.uuid4()),
        "document_id": doc_id,
        "workflow_name": "reprocess",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Completed",
        "steps": [
            {
                "step": "revalidation",
                "status": "completed",
                "result": {
                    "old_match_method": old_match_method,
                    "new_match_method": new_match_method,
                    "validation_passed": validation_results.get("all_passed"),
                    "decision": decision,
                    "square9_aligned": True,
                    "reason": "Square9 workflow: validate data, confirm SharePoint storage. BC attachment handled separately."
                }
            },
            {
                "step": "status_transition",
                "status": "completed" if new_status != old_status else "no_change",
                "result": {
                    "old_status": old_status,
                    "new_status": new_status,
                    "sharepoint_stored": bool(share_link)
                }
            }
        ],
        "correlation_id": str(uuid.uuid4()),
        "error": None
    }
    await db.hub_workflow_runs.insert_one(workflow)
    
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    
    return {
        "reprocessed": True,
        "status_changed": old_status != new_status,
        "old_status": old_status,
        "new_status": new_status,
        "match_method_changed": old_match_method != new_match_method,
        "old_match_method": old_match_method,
        "new_match_method": new_match_method,
        "validation_passed": validation_results.get("all_passed"),
        "sharepoint_stored": bool(share_link),
        "document": updated_doc,
        "reasoning": reasoning
    }
