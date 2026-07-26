"""
Authoritative raw-bytes document intake orchestration.

The implementation was migrated from services.document_handlers after all
production callers were rewired through this dedicated service seam.
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional


logger = logging.getLogger(__name__)


# =============================================================================
# Phase 3 Step 4b — authoritative raw-bytes intake implementation
# =============================================================================
# Moved verbatim from ``server._internal_intake_document`` on 2026-04-23.
# Signature and return shape preserved byte-identical to the Step 4a wrapper
# so the 6 external callers (sales_pipeline_demo, pilot, email_polling,
# inside_sales_pilot, batch_po_splitter) require NO further changes. Helper
# dispatch is preserved via a lazy-import block from ``server`` at the top
# of the function body — substituting any of those imports is a Step-4c
# concern and must land with its own signed parity proof.
# =============================================================================
async def intake_document_from_bytes(
    file_content: bytes,
    filename: str,
    content_type: str,
    source: str = "email_poll",
    sender: Optional[str] = None,
    subject: Optional[str] = None,
    email_id: Optional[str] = None,
    mailbox_category: Optional[str] = None,
) -> dict:
    """Phase 3 Step 4b: authoritative raw-bytes intake implementation.

    Moved verbatim from ``server._internal_intake_document`` (2026-04-23).
    Behavior-preserving move — the body below is byte-identical to the
    pre-move source captured in ``tests/fixtures/intake_body_move_baseline.json``.
    Helper dispatch is preserved via the lazy-import block from ``server``
    below. A future Step 4c will migrate these helpers to their authoritative
    service-module homes one at a time, each with its own parity proof.
    """
    # Step 4b: conservative lazy-import cascade. DO NOT substitute any of these
    # with their same-named counterparts in services.* — that is a Step-4c
    # behavioral change and must land with its own signed parity proof.
    from server import (
        _attempt_llm_vendor_ranking,
        _build_vendor_resolution,
    )
    # Phase 3 Step 4c.1: direct authoritative imports for re-exported helpers
    from services.document_intel_helpers import compute_ap_normalized_fields
    from services.ap_computation import compute_ap_validation
    # Phase 3 Step 4c.2: direct authoritative imports for thin-shim helpers
    from services.document_intel_helpers import classify_document_with_ai, make_automation_decision
    from services.classification_helpers import classify_document_type
    from services.sharepoint_service import create_sharing_link
    # Phase 3 Step 4c.3: direct authoritative imports for Tier-3 shim helpers
    from services.vendor_matching import lookup_vendor_alias, check_duplicate_document
    # Phase 3 Step 4d.1: direct authoritative imports for enums/constants
    from workflows.core.engine import (
        CaptureChannel, DocType, SourceSystem, WorkflowEvent, WorkflowStatus,
    )
    from services.auto_clear_service import AutoClearDecision
    from services.pilot_config import PILOT_MODE_ENABLED
    from models.document_types import DEFAULT_JOB_TYPES
    # Phase 3 Step 4d.2a: direct authoritative import for UPLOAD_DIR
    from paths import UPLOAD_DIR
    # Phase 3 Step 4d.2b: direct authoritative import for `db`
    from database import db
    # Phase 3 Step 4d.3a: direct authoritative imports for auto_clear_service helpers
    from services.auto_clear_service import evaluate_auto_clear, get_auto_clear_update
    # Phase 3 Step 4d.3b: direct authoritative imports for event_service helpers
    from services.event_service import emit_document_received, get_event_service
    # Phase 3 Step 4d.3c: direct authoritative imports for pilot_config helpers
    from services.pilot_config import get_pilot_capture_channel, get_pilot_metadata
    # Phase 3 Step 4d.3d: direct authoritative import for auto_resolution_service helper
    from services.auto_resolution_service import get_auto_resolve_service
    # Phase 3 Step 4d.3e: direct authoritative import for sharepoint_service helper (THIN_SHIM migration)
    from services.sharepoint_service import upload_to_sharepoint_with_routing
    # Phase 3 Step 4d.4a: direct authoritative import for classification_helpers.derive_workflow_status
    # (alias preserves `_derive_workflow_status` call-site byte parity)
    from services.classification_helpers import derive_workflow_status as _derive_workflow_status
    # Phase 3 Step 4d.4b: direct authoritative import for
    # workflows.ap_invoice.rules.vendor_profile.update_vendor_profile_incremental
    # (alias preserves `_update_vendor_profile_incremental` call-site byte parity)
    from workflows.ap_invoice.rules.vendor_profile import (
        update_vendor_profile_incremental as _update_vendor_profile_incremental,
    )
    # Phase 3 Step 4d.5: direct authoritative import for
    # services.event_service.emit_intake_events (first body-bearing Class 3
    # carve-out; alias preserves `_emit_intake_events` call-site byte parity)
    from services.event_service import emit_intake_events as _emit_intake_events
    # Phase 3 Step 4d.6: direct authoritative import for
    # workflows.ap_invoice.rules.workflow_status.update_ap_workflow_status
    # (alias preserves `_update_ap_workflow_status` call-site byte parity)
    from workflows.ap_invoice.rules.workflow_status import (
        update_ap_workflow_status as _update_ap_workflow_status,
    )
    # Phase 3 Step 4d.7: direct authoritative import for
    # workflows.document_capture.rules.workflow_status.update_standard_workflow_status
    # (alias preserves `_update_standard_workflow_status` call-site byte parity)
    from workflows.document_capture.rules.workflow_status import (
        update_standard_workflow_status as _update_standard_workflow_status,
    )

    computed_hash = hashlib.sha256(file_content).hexdigest()

    # ---- Content-hash dedup gate ----
    existing_by_hash = await db.hub_documents.find_one(
        {"sha256_hash": computed_hash, "is_duplicate": {"$ne": True}},
        {"_id": 0, "id": 1, "file_name": 1}
    )
    if existing_by_hash:
        logger.info("[Intake] Skipped duplicate: %s (hash matches doc %s / %s)",
                     filename, existing_by_hash["id"], existing_by_hash.get("file_name"))
        return {
            "document_id": existing_by_hash["id"],
            "skipped_duplicate": True,
            "message": f"Duplicate of {existing_by_hash['id']} by content hash",
        }

    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    correlation_id = str(uuid.uuid4())  # For event correlation

    # Store file locally
    file_path = UPLOAD_DIR / doc_id
    file_path.write_bytes(file_content)

    # Also store file content in MongoDB as backup (survives container restarts)
    import base64 as b64mod
    file_content_b64 = b64mod.b64encode(file_content).decode("ascii")

    # Apply pilot capture channel if pilot mode is enabled
    base_capture_channel = CaptureChannel.EMAIL.value if "email" in source.lower() else CaptureChannel.UPLOAD.value
    capture_channel = get_pilot_capture_channel(base_capture_channel) if PILOT_MODE_ENABLED else base_capture_channel

    # Create document record with workflow tracking
    doc = {
        "id": doc_id,
        "source": source,
        "file_name": filename,
        "sha256_hash": computed_hash,
        "file_size": len(file_content),
        "file_content_b64": file_content_b64,
        "content_type": content_type,
        "email_sender": sender,
        "email_subject": subject,
        "email_id": email_id,
        "email_received_utc": now,
        "mailbox_category": mailbox_category,
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
        # Workflow tracking fields
        "workflow_status": WorkflowStatus.CAPTURED.value,
        "workflow_history": [{
            "timestamp": now,
            "from_status": None,
            "to_status": WorkflowStatus.CAPTURED.value,
            "event": WorkflowEvent.ON_CAPTURE.value,
            "actor": "system",
            "reason": "Document captured from " + source,
            "metadata": {"source": source, "sender": sender}
        }],
        "workflow_status_updated_utc": now,
        # Derived state fields (Phase 2)
        "validation_state": "pending",
        "workflow_state": "received",
        "automation_state": "manual",
        "created_utc": now,
        "updated_utc": now,
        "last_error": None,
        # Pilot metadata (added if pilot mode enabled)
        **get_pilot_metadata()
    }
    await db.hub_documents.insert_one(doc)

    # Emit document.received event (Phase 1)
    event_service = get_event_service()
    if event_service:
        await emit_document_received(
            event_service, doc_id, source,
            filename, content_type or "application/octet-stream",
            len(file_content), correlation_id
        )

    # Run AI extraction (for field extraction, not doc_type classification)
    logger.info("Running AI field extraction for document %s", doc_id)
    try:
        classification = await classify_document_with_ai(str(file_path), filename)
    except Exception as ai_err:
        logger.error("AI classification crashed for %s: %s", doc_id, str(ai_err))
        classification = {"suggested_job_type": "Unknown", "confidence": 0.0, "extracted_fields": {}, "error": str(ai_err)}

    suggested_type = classification.get("suggested_job_type", "Unknown")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})

    # Deterministic-first document type classification
    # Step 1: Try deterministic rules (Zetadocs, Square9, mailbox category)
    # Step 2: If still OTHER, try AI classification if enabled
    try:
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
    except Exception as cls_err:
        logger.error("Document type classification crashed for %s: %s", doc_id, str(cls_err))
        classification_result = {"doc_type": "Other", "category": "Other", "ai_classification": None, "classification_method": "fallback_error"}

    doc_type_value = classification_result["doc_type"]
    category = classification_result["category"]
    ai_classification_audit = classification_result.get("ai_classification")
    classification_method = classification_result.get("classification_method", "unknown")

    # CRITICAL: Sync suggested_type with deterministic classification result.
    # When AI extraction fails (suggested_type="Unknown") but deterministic classification
    # succeeds (e.g. mailbox:AP → AP_INVOICE), suggested_type must be updated so ALL
    # downstream code (status checks, auto-post routing, job configs) use the correct type.
    _DOC_TYPE_TO_SUGGESTED = {
        "AP_INVOICE": "AP_Invoice", "PURCHASE_ORDER": "Purchase_Order",
        "SALES_INVOICE": "AR_Invoice", "DS_SALES_ORDER": "DS_Sales_Order",
        "WH_SALES_ORDER": "WH_Sales_Order", "SH_INVOICE": "SH_Invoice",
        "SALES_CREDIT_MEMO": "Credit_Memo", "PURCHASE_CREDIT_MEMO": "Credit_Memo",
        "STATEMENT": "Statement", "QUALITY_DOC": "Quality_Document",
    }
    if doc_type_value not in ("Other", "Unknown", "OTHER", "Unknown_Document"):
        new_suggested = _DOC_TYPE_TO_SUGGESTED.get(doc_type_value, doc_type_value)
        if suggested_type in ("Unknown", "Other", "Unknown_Document") and new_suggested != suggested_type:
            logger.info(
                "Syncing suggested_type for %s: %s → %s (classified via %s)",
                doc_id, suggested_type, new_suggested, classification_method
            )
            suggested_type = new_suggested

    # FIX: If deterministic classification succeeded but AI extraction returned 0.0 confidence,
    # bump confidence so downstream workflow/auto-resolution don't treat this as a failure.
    if doc_type_value not in ("Other", "Unknown", "Unknown_Document") and confidence < 0.5:
        classification_confidence = 0.85  # Deterministic classification gets minimum 85%
        logger.info(
            "Bumping confidence for %s from %.2f to %.2f (classified as %s via %s)",
            doc_id, confidence, classification_confidence, doc_type_value, classification_method
        )
        confidence = classification_confidence

    logger.info(
        "Document %s classified as %s (category: %s, method: %s, suggested: %s)",
        doc_id, doc_type_value, category, classification_method, suggested_type
    )

    # Phase 7: Compute normalized fields (flat, stored on document)
    try:
        normalized_fields = compute_ap_normalized_fields(extracted_fields)
    except Exception as norm_err:
        logger.warning("Normalized fields computation failed for %s: %s", doc_id, str(norm_err))
        normalized_fields = {}

    # Phase 7: Vendor alias lookup — sender email first, then text lookup
    try:
        vendor_alias_result = {"vendor_canonical": None, "vendor_match_method": "none"}
        # Check sender email → vendor mapping first
        existing_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "email_sender": 1})
        sender_email = (existing_doc or {}).get("email_sender", "")
        if sender_email:
            from services.vendor_matching import lookup_vendor_by_sender

            extracted_vendor_for_sender_guard = (
                normalized_fields.get("vendor_raw")
                or normalized_fields.get("vendor")
                or extracted_fields.get("vendor")
                or extracted_fields.get("vendor_name")
            )
            sender_result = await lookup_vendor_by_sender(
                sender_email,
                extracted_vendor=extracted_vendor_for_sender_guard,
                document_id=doc_id,
            )
            if sender_result.get("vendor_canonical"):
                vendor_alias_result = sender_result
        if not vendor_alias_result.get("vendor_canonical"):
            vendor_alias_result = await lookup_vendor_alias(normalized_fields.get("vendor_normalized"))
    except Exception as va_err:
        logger.warning("Vendor alias lookup failed for %s: %s", doc_id, str(va_err))
        vendor_alias_result = {}

    # LLM Vendor Ranking gate (email intake path)
    llm_vendor_ranking_dict = None
    llm_vendor_ranking_event = None
    try:
        vendor_alias_result, llm_vendor_ranking_dict, llm_vendor_ranking_event = (
            await _attempt_llm_vendor_ranking(
                doc_id, vendor_alias_result,
                normalized_fields.get("vendor_raw", ""), normalized_fields,
            )
        )
    except Exception as lr_err:
        logger.warning("[LLM-VendorRank] Gate error for %s: %s", doc_id[:8], lr_err)

    # Phase 8: Spiro context enrichment (Shadow Mode - logs only, doesn't affect decisions)
    spiro_context_dict = None
    try:
        from services.spiro import get_spiro_context_for_document
        from services.spiro.spiro_client import is_spiro_enabled

        if is_spiro_enabled():
            doc_metadata = {
                "vendor_raw": normalized_fields.get("vendor_raw"),
                "vendor_normalized": normalized_fields.get("vendor_normalized"),
                "extracted_fields": extracted_fields
            }
            spiro_context = await get_spiro_context_for_document(doc_metadata)
            spiro_context_dict = spiro_context.to_dict()

            if spiro_context.matched_companies:
                best = spiro_context.matched_companies[0]
                logger.info("Spiro match for %s: %s (%.2f, ISR: %s)", 
                           doc_id[:8], best.name, best.match_score, best.data.get("assigned_isr"))
    except Exception as e:
        logger.debug("Spiro context skipped: %s", str(e))


    # Phase 7: Duplicate check
    try:
        duplicate_result = await check_duplicate_document(
            vendor_normalized=normalized_fields.get("vendor_normalized"),
            vendor_canonical=vendor_alias_result.get("vendor_canonical"),
            invoice_number_clean=normalized_fields.get("invoice_number_clean"),
            current_doc_id=doc_id
        )
    except Exception as dup_err:
        logger.warning("Duplicate check failed for %s: %s", doc_id, str(dup_err))
        duplicate_result = {"possible_duplicate": False}

    # Phase 7: Compute validation errors/warnings and draft_candidate
    try:
        ap_validation = compute_ap_validation(
            document_type=suggested_type,
            vendor_normalized=normalized_fields.get("vendor_normalized"),
            invoice_number_clean=normalized_fields.get("invoice_number_clean"),
            amount_float=normalized_fields.get("amount_float"),
            po_number_clean=normalized_fields.get("po_number_clean"),
            ai_confidence=confidence,
            possible_duplicate=duplicate_result.get("possible_duplicate", False)
        )
    except Exception as val_err:
        logger.warning("AP validation failed for %s: %s", doc_id, str(val_err))
        ap_validation = {"draft_candidate": False, "blocking_issues": [], "warnings": []}

    # Get job type config
    job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])

    # ── PO Resolution: ALL sources, ALL doc types ──
    # Extract PO candidates from every source (LLM extraction, filename, BOL, subject, description)
    # and match against BC cache (purchase orders + sales shipments).
    # This runs for EVERY document, not just shipping docs.
    try:
        from services.po_resolution_service import resolve_po_from_document, attempt_bc_link
        current_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        if current_doc:
            po_result = await resolve_po_from_document(current_doc)
            bc_link_result = await attempt_bc_link(doc_id, po_result)
            po_result["bc_link"] = bc_link_result
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "po_resolution": po_result,
                    "po_candidates": po_result.get("candidates_raw", []),
                }}
            )
            # Feed best resolved PO into validation
            if po_result.get("po_number"):
                extracted_fields["_po_resolution_number"] = po_result["po_number"]
            # Also feed ALL valid candidates so validation can try each one
            valid_candidates = po_result.get("candidates_valid", [])
            if isinstance(valid_candidates, list) and valid_candidates:
                if isinstance(valid_candidates[0], dict):
                    valid_candidates = [c["normalized"] for c in valid_candidates if c.get("valid_format") and not c.get("is_non_po")]
            if valid_candidates:
                extracted_fields["_po_all_candidates"] = valid_candidates
            logger.info(
                "[INTAKE] PO resolution for %s: status=%s po=%s candidates=%d bc_link=%s",
                doc_id[:8], po_result.get("status"), po_result.get("po_number"),
                len(valid_candidates), bc_link_result.get("status"),
            )
    except Exception as po_err:
        logger.warning("[INTAKE] PO resolution error for %s: %s", doc_id[:8], str(po_err))

    # Run BC validation (existing logic — now enriched with PO resolution candidates)
    try:
        from services.bc_validation_service import validate_bc_match
        # Pass vendor_canonical from ref intel if available
        vendor_canonical = doc.get("vendor_canonical") if doc else ""
        if vendor_canonical:
            extracted_fields.setdefault("_vendor_canonical", vendor_canonical)
        validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)
    except Exception as bc_err:
        logger.warning("BC validation failed for %s: %s", doc_id, str(bc_err))
        validation_results = {"all_passed": False}

    # Make automation decision
    try:
        decision, reasoning, decision_metadata = make_automation_decision(job_configs, confidence, validation_results)
    except Exception as dec_err:
        logger.warning("Automation decision failed for %s: %s", doc_id, str(dec_err))
        decision, reasoning, decision_metadata = "manual", "Decision engine error", {}

    # Get freight direction for routing
    freight_direction = validation_results.get("freight_direction")

    # Build doc dict for routing
    routing_doc = {
        "id": doc_id,
        "document_type": suggested_type,
        "suggested_job_type": suggested_type,
        "vendor_canonical": doc.get("vendor_canonical") or normalized_fields.get("vendor"),
        "po_number_extracted": normalized_fields.get("po_number") or extracted_fields.get("po_number"),
        "bol_number_extracted": normalized_fields.get("bol_number") or extracted_fields.get("bol_number"),
        "extracted_fields": extracted_fields,
        "normalized_fields": normalized_fields,
        "ai_extraction": doc.get("ai_extraction", {}),
        "file_name": filename,
        "status": doc.get("status"),
        "approved": doc.get("approved", False)
    }

    # Upload to SharePoint using accounting folder routing
    sp_result = None
    share_link = None
    sp_error = None
    folder_path = None
    routing_reason = None

    try:
        sp_result = await upload_to_sharepoint_with_routing(
            file_content, 
            filename, 
            routing_doc,
            freight_direction=freight_direction,
            is_international=False  # TODO: detect from document
        )
        share_link = await create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
        folder_path = sp_result.get("folder_path")
        routing_reason = sp_result.get("routing_reason")
        logger.info("Document %s stored in SharePoint: %s (folder: %s, reason: %s)", 
                   doc_id, sp_result.get("web_url"), folder_path, routing_reason)
    except Exception as e:
        sp_error = str(e)
        logger.error("SharePoint upload failed for document %s: %s", doc_id, sp_error)

    # Phase 7: Determine status for AP_Invoice using new logic
    if suggested_type in ("AP_Invoice", "AP Invoice"):
        # All AP_Invoice documents stay in NeedsReview during Phase 7
        # The draft_candidate flag indicates readiness
        final_status = "NeedsReview"
    else:
        # Non-AP documents use existing logic
        if decision == "auto_link" and validation_results.get("all_passed"):
            final_status = "ReadyToLink"
        elif decision in ("needs_review", "manual"):
            final_status = "NeedsReview"
        elif decision == "exception":
            final_status = "Exception"
        elif sp_result:
            final_status = "StoredInSP"
        else:
            final_status = "Classified"

    # Get the category from job type config (fallback to our computed category)
    doc_category = category if category != "Other" else job_configs.get("category", category)

    update_data = {
        "suggested_job_type": suggested_type,
        "document_type": suggested_type,
        "category": doc_category,
        # Document classification fields
        "doc_type": doc_type_value,
        "source_system": SourceSystem.GPI_HUB_NATIVE.value,
        "capture_channel": capture_channel,  # Use pilot-aware channel
        "classification_method": classification_method,
        "ai_confidence": confidence,
        "extracted_fields": extracted_fields,
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
        "bc_vendor_number": (
            vendor_alias_result.get("vendor_no")
            or (validation_results.get("bc_record_info") or {}).get("number")
        ),
        # Phase 7: Vendor resolution observability
        "vendor_resolution": _build_vendor_resolution(
            vendor_raw=normalized_fields.get("vendor_raw", ""),
            match_result=vendor_alias_result,
        ),
        # Phase 7: Duplicate detection
        "possible_duplicate": duplicate_result.get("possible_duplicate", False),
        "duplicate_of_document_id": duplicate_result.get("duplicate_of_document_id"),
        # Phase 7: Validation errors/warnings and draft_candidate
        "validation_errors": ap_validation.get("validation_errors", []),
        "validation_warnings": ap_validation.get("validation_warnings", []),
        "draft_candidate": ap_validation.get("draft_candidate", False),
        # Legacy fields (keep for backward compat)
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
        "workflow_status": _derive_workflow_status(final_status, doc_type_value, decision),
        "workflow_state": "Validated",
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }

    # ---------------------------------------------------------------
    # Persist evidence-based AP routing decision (mission-aligned audit).
    # See services.folder_routing_service.determine_ap_routing_decision.
    # This is independent of the SharePoint upload's folder selection
    # (sp_result.folder_path) — both are written so the persisted document
    # carries the full structured decision regardless of upload outcome.
    # ---------------------------------------------------------------
    try:
        from services.folder_routing_service import determine_ap_routing_decision
        _existing_for_routing = await db.hub_documents.find_one(
            {"id": doc_id}, {"_id": 0, "file_name": 1}
        ) or {}
        _routing_input_doc = {
            "document_type": suggested_type,
            "doc_type": doc_type_value,
            "suggested_job_type": suggested_type,
            "mailbox_category": mailbox_category,
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
            "file_name": _existing_for_routing.get("file_name", ""),
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
        # Folder routing info (accounting structure)
        update_data["sharepoint_folder_path"] = sp_result.get("folder_path")
        update_data["folder_routing_reason"] = sp_result.get("routing_reason")
        update_data["folder_routing_details"] = sp_result.get("routing_details")
        update_data["freight_direction"] = freight_direction
        # Square9-style filename convention: what actually got uploaded, and what
        # the original ingested filename was (for traceability — the ingest-time
        # "file_name" field is left untouched; this is upload-specific).
        if sp_result.get("uploaded_file_name"):
            update_data["sharepoint_file_name"] = sp_result["uploaded_file_name"]
            update_data["original_file_name"] = sp_result.get("original_file_name")
    else:
        update_data["last_error"] = f"SharePoint upload failed: {sp_error}"

    # Add AI classification audit trail if AI was invoked
    if ai_classification_audit:
        update_data["ai_classification"] = ai_classification_audit

    # Phase 8: Save Spiro context to document (Shadow Mode)
    if spiro_context_dict:
        update_data["spiro_context"] = spiro_context_dict

    # LLM Vendor Ranking: persist audit trail
    if llm_vendor_ranking_dict:
        update_data["llm_vendor_ranking"] = llm_vendor_ranking_dict
    if llm_vendor_ranking_event:
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$push": {"workflow_events": llm_vendor_ranking_event}}
        )

    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})

    # Update workflow status based on processing results and doc_type
    if doc_type_value == DocType.AP_INVOICE.value:
        # Full AP workflow with vendor matching, BC validation, etc.
        await _update_ap_workflow_status(
            doc_id, 
            confidence, 
            normalized_fields, 
            vendor_alias_result, 
            validation_results,
            ap_validation
        )

        # STRICT AP AUTO-POST: Binary decision — auto-post or NeedsReview.
        # Phase 3 Step 3: decision/status-flip lives in ap_auto_post_service.finalize_ap_decision.
        try:
            from services.ap_auto_post_service import finalize_ap_decision
            _ap_finalize = await finalize_ap_decision(doc_id, db, source="auto")
            final_status = _ap_finalize["status"]
        except Exception as e:
            logger.error("[AP Auto-Post] Exception for %s: %s", doc_id, str(e))
    else:
        # For non-AP documents, use simplified workflow
        await _update_standard_workflow_status(
            doc_id, 
            doc_type_value,
            confidence, 
            normalized_fields
        )

    # ── Sales Rep Auto-Assignment ──
    # For sales-eligible documents (Sales_Order, PurchaseOrder, etc.),
    # look up the customer → rep mapping and route to My Queue or Triage.
    sales_assign_result = None
    try:
        from services.sales_auto_assign import auto_assign_sales_rep
        # Build a minimal doc dict with all available data
        assign_doc = {
            "document_type": suggested_type,
            "suggested_job_type": suggested_type,
            "ai_confidence": confidence,
            "extracted_fields": extracted_fields,
            "normalized_fields": validation_results.get("normalized_fields", {}),
            "vendor_name": vendor_alias_result.get("vendor_canonical") or normalized_fields.get("vendor_raw"),
            "email_sender": sender,
        }
        sales_assign_result = await auto_assign_sales_rep(db, doc_id, assign_doc)
        if sales_assign_result:
            logger.info("[INTAKE] Sales auto-assign for %s: %s", doc_id[:8], sales_assign_result)
    except Exception as sa_err:
        logger.warning("[INTAKE] Sales auto-assign error for %s: %s", doc_id[:8], str(sa_err))

    # ── Batch Document Detection (all types) ──
    # If this is a multi-page document, detect boundaries and flag for splitting
    try:
        from services.batch_po_splitter import detect_batch_po
        batch_info = detect_batch_po(file_content, suggested_type)
        if batch_info.get("should_split"):
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "batch_detected": True,
                    "batch_page_count": batch_info["page_count"],
                    "batch_document_count": batch_info.get("document_count", batch_info["page_count"]),
                    "batch_split_suggested": True,
                    "batch_split_mode": batch_info.get("split_mode", "per_page"),
                    "batch_boundaries": batch_info.get("boundaries", []),
                    "batch_groups": batch_info.get("groups", []),
                    "status": "batch_parent",
                }},
            )
            logger.info("[INTAKE] Multi-page doc detected: %s (%d pages, %d logical docs) — auto-splitting",
                        doc_id[:8], batch_info["page_count"], batch_info.get("document_count", batch_info["page_count"]))

            # Auto-split: run each logical document through the full pipeline
            from services.batch_po_splitter import split_and_ingest_batch
            split_result = await split_and_ingest_batch(
                db=db,
                parent_doc_id=doc_id,
                parent_filename=filename,
                file_content=file_content,
                sender=sender,
                source="auto_split",
                subject=subject,
                groups=batch_info.get("groups"),
            )
            logger.info("[INTAKE] Auto-split complete for %s: %d children (%d errors)",
                        doc_id[:8], split_result["children_count"], split_result["children_errors"])
    except Exception as bd_err:
        logger.warning("[INTAKE] Batch detection/split error for %s: %s", doc_id[:8], str(bd_err))

    # Create workflow audit trail entry
    workflow_run_id = uuid.uuid4().hex[:8]
    workflow = {
        "id": str(uuid.uuid4()),
        "run_id": workflow_run_id,
        "document_id": doc_id,
        "workflow_name": source,
        "workflow_type": "intake_validation",
        "started_utc": now,
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Completed",
        "correlation_id": uuid.uuid4().hex[:8],
        "steps": [
            {"step": "AI Classification", "status": "Completed", "timestamp": now, 
             "details": {"document_type": suggested_type, "confidence": confidence}},
            {"step": "SharePoint Upload", "status": "Completed" if sp_result else "Failed", 
             "timestamp": datetime.now(timezone.utc).isoformat(),
             "details": sp_result if sp_result else {"error": sp_error}},
            {"step": "BC Validation", "status": "Completed", "timestamp": datetime.now(timezone.utc).isoformat(),
             "details": {
                 "match_method": validation_results.get("match_method", "none"),
                 "match_score": validation_results.get("match_score", 0.0),
                 "all_passed": validation_results.get("all_passed", False)
             }},
            {"step": "Automation Decision", "status": "Completed", "timestamp": datetime.now(timezone.utc).isoformat(),
             "details": {"decision": decision, "reasoning": reasoning, "final_status": final_status}}
        ],
        "error": None
    }
    await db.hub_workflow_runs.insert_one(workflow)

    logger.info("[Workflow:%s] Intake complete: %s → status=%s, decision=%s, score=%.2f", 
                workflow_run_id, filename, final_status, decision, validation_results.get("match_score", 0.0))

    # =================================================================
    # AUTO-CLEAR EVALUATION (Square9/Zetadocs aligned)
    # SKIP for AP_Invoice — handled by strict ap_auto_post_service above
    # =================================================================
    auto_clear_result = None
    is_ap_invoice = suggested_type in ("AP_Invoice", "AP Invoice") or doc_type_value == "AP_INVOICE"
    if is_ap_invoice:
        logger.info("[Auto-Clear] SKIPPED for AP_Invoice %s — using strict ap_auto_post_service", doc_id)
        auto_clear_result = {"decision": "skipped", "reason": "AP invoices use strict auto-post service", "cleared": False}
    else:
        try:
            doc_for_eval = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
            if doc_for_eval:
                auto_clear_decision, auto_clear_reason, auto_clear_details = evaluate_auto_clear(
                    doc_for_eval,
                    validation_results=validation_results
                )

                auto_clear_update = get_auto_clear_update(auto_clear_decision, auto_clear_details)

                if auto_clear_decision == AutoClearDecision.NEEDS_REVIEW:
                    auto_clear_update["status"] = "NeedsReview"
                    auto_clear_update["workflow_status"] = "needs_review"
                    auto_clear_update["square9_stage"] = "needs_review"
                    final_status = "NeedsReview"
                    logger.info("[Auto-Clear] BLOCKED for %s: %s — forcing NeedsReview", doc_id, auto_clear_reason)

                await db.hub_documents.update_one({"id": doc_id}, {"$set": auto_clear_update})

                auto_clear_result = {
                    "decision": auto_clear_decision.value,
                    "reason": auto_clear_reason,
                    "cleared": auto_clear_decision == AutoClearDecision.CLEARED
                }

                if auto_clear_decision == AutoClearDecision.CLEARED:
                    final_status = "Completed"
                    logger.info("[Auto-Clear] Document %s AUTO-CLEARED: %s", doc_id, auto_clear_reason)

                    try:
                        from services.classification_feedback_service import record_confirmation, _build_doc_context
                        doc_type_confirmed = (doc_for_eval.get("document_type") or 
                                              doc_for_eval.get("suggested_job_type") or "")
                        await record_confirmation(
                            doc_id=doc_id,
                            confirmed_type=doc_type_confirmed,
                            confirmation_source="auto_clear",
                            doc_context=_build_doc_context(doc_for_eval),
                        )
                    except Exception as cf_err:
                        logger.debug("[Auto-Clear] Classification confirmation failed for %s: %s", doc_id, cf_err)

                    # === PER-DOCUMENT LEARNING: Auto-clear is a positive signal ===
                    try:
                        from services.per_document_learning_service import learn_from_document
                        await learn_from_document(db, doc_id, trigger="auto_file")
                    except Exception:
                        pass

                    # AUTO-FILE shipping documents (non-AP only)
                    try:
                        doc_type = (doc_for_eval.get("document_type") or 
                                    doc_for_eval.get("suggested_job_type") or "")
                        if doc_type in ("Shipping_Document", "Warehouse_Receipt", "Warehouse_Document"):
                            from services.shipping_auto_file_service import auto_file_shipping_document
                            file_result = await auto_file_shipping_document(doc_id, db)
                            if file_result.get("success") and not file_result.get("skipped"):
                                logger.info("[AutoFile] Shipping doc %s auto-filed to '%s' (loc=%s, intl=%s)",
                                           doc_id, file_result.get("folder_path", ""),
                                           file_result.get("location_code", "?"),
                                           file_result.get("is_international", False))
                            elif file_result.get("skipped"):
                                logger.debug("[AutoFile] Skipped for doc %s: %s", doc_id, file_result.get("reason", ""))
                            else:
                                logger.warning("[AutoFile] Failed for doc %s: %s", doc_id, file_result.get("reason", ""))
                    except Exception as af_err:
                        logger.error("[AutoFile] Error auto-filing doc %s: %s", doc_id, str(af_err))
                else:
                    logger.debug("[Auto-Clear] Document %s NOT cleared: %s", doc_id, auto_clear_reason)
        except Exception as e:
            logger.error("[Auto-Clear] Error evaluating document %s: %s", doc_id, str(e))

    # =================================================================
    # DOCUMENT ROUTING (Auto-Clear Gate)
    # Evaluate document routing after auto-clear
    # =================================================================
    routing_result = None
    try:
        from services.document_routing_service import route_document
        routing_result = await route_document(doc_id)
        logger.info("[Routing] Document %s routed: status=%s score=%d",
                     doc_id, routing_result.get("routing_status"), routing_result.get("routing_score", 0))
    except Exception as e:
        logger.error("[Routing] Error routing document %s: %s", doc_id, str(e))

    # =================================================================
    # DOCUMENT READINESS EVALUATION
    # =================================================================
    readiness_result = None
    try:
        from services.unified_validation_service import run_readiness
        readiness_result = await run_readiness(doc_id)
        logger.info("[Readiness] Document %s: status=%s confidence=%.2f action=%s",
                     doc_id, readiness_result.get("status"), readiness_result.get("confidence", 0),
                     readiness_result.get("recommended_action"))
    except Exception as e:
        logger.error("[Readiness] Error evaluating document %s: %s", doc_id, str(e))

    # Emit workflow events (Phase 1)
    try:
        await _emit_intake_events(
            doc_id, correlation_id, classification, validation_results,
            sp_result, decision, auto_clear_result
        )
    except Exception as e:
        logger.error("[Events] Error emitting events for document %s: %s", doc_id, str(e))

    # =================================================================
    # AUTO-RESOLUTION: Queue background reference intelligence
    # Non-blocking — enqueue and return immediately
    # =================================================================
    try:
        auto_resolve = get_auto_resolve_service()
        if auto_resolve:
            await auto_resolve.enqueue(doc_id)
    except Exception as e:
        logger.error("[AutoResolve] Error queueing document %s: %s", doc_id, str(e))

    # =================================================================
    # INCREMENTAL VENDOR PROFILE UPDATE
    # Update the vendor's intelligence profile with this document's results
    # =================================================================
    try:
        vendor_name = (
            update_data.get("vendor_canonical")
            or update_data.get("matched_vendor_name")
            or update_data.get("vendor_raw")
        )
        if vendor_name:
            await _update_vendor_profile_incremental(db, doc_id, vendor_name, update_data, final_status)
    except Exception as e:
        logger.error("[VendorProfile] Error updating profile for doc %s: %s", doc_id, str(e))

    return {
        "document": {"id": doc_id, "status": final_status},
        "classification": classification,
        "automation_decision": decision,
        "sharepoint": sp_result,
        "auto_clear": auto_clear_result,
        "routing": routing_result,
        "readiness": readiness_result
    }


__all__ = ["intake_document_from_bytes"]
