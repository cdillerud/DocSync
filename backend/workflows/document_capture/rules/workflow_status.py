"""
GPI Document Hub — document-capture rule: non-AP workflow-status routing.

Phase 3 Step 4d.7 carve-out home for the non-AP workflow-status helper
(warehouse, sales, etc.). Moved verbatim from server.py:1811. The
original `server` site is retained as a delegating compatibility shim
during the carve-out window.

Single public function: ``update_standard_workflow_status``.
"""
import asyncio
import logging
import uuid
from datetime import datetime, timezone
from typing import Dict

from database import db
from workflows.core.engine import DocType, WorkflowEngine, WorkflowEvent
from services.square9_workflow import Square9Stage, validate_location_code
from services.auto_post_service import (
    attempt_auto_create_sales_order,
    AUTO_CREATE_SALES_ORDER_ENABLED,
)
from services.business_central_service import get_bc_service

# Phase 3 Step 4d.8 — reverse-arrow cleanup.
# Sub-task A retired ``AUTO_CREATE_SALES_ORDER_ENABLED`` (now imported
# from its canonical home ``services.auto_post_service`` together with
# ``attempt_auto_create_sales_order`` above). Sub-task B retired
# ``_run_pilot_enrichment`` by co-migrating it (and its only callee
# ``_maybe_stage_inventory_xls``) to the sibling
# ``workflows.document_capture.rules.pilot_enrichment`` module. The
# alias preserves ``_run_pilot_enrichment`` as the bare-name binding at
# the call site below — body byte-identity unchanged from 4d.7.
from workflows.document_capture.rules.pilot_enrichment import (
    run_pilot_enrichment as _run_pilot_enrichment,
)

logger = logging.getLogger(__name__)


async def update_standard_workflow_status(
    doc_id: str,
    doc_type: str,
    confidence: float,
    normalized_fields: Dict
):
    """
    Update workflow status for non-AP document types.
    Implements Square9-style workflow for warehouse and sales documents.
    
    Warehouse Workflow (SHIPMENT, RECEIPT):
    - Import -> Classification -> PO Validation -> Location Validation -> Export
    
    Sales Workflow (SALES_ORDER, SALES_INVOICE):
    - Import -> Classification -> Customer Match -> BC Validation -> Export/Create
    """
    from services.square9_workflow import (
        initialize_retry_state, increment_retry, determine_square9_stage, reset_retry_counter
    )

    # Phase B.0 — observability tick so the Phase B extraction can see
    # which callers + doc_types actually exercise this function in
    # production. Fire-and-forget; never blocks the primary workflow.
    try:
        from services.workflow_state_observer import record_workflow_call
        await record_workflow_call(
            db,
            doc_id=doc_id,
            doc_type=doc_type,
            confidence=confidence,
            has_normalized_fields=bool(normalized_fields),
        )
    except Exception:
        pass

    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        return
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Initialize retry state if not present
    if "retry_count" not in doc:
        retry_state = initialize_retry_state(doc)
        doc.update(retry_state)
        await db.hub_documents.update_one({"id": doc_id}, {"$set": retry_state})
    
    # Step 1: Classification done - move from captured to classified
    # FIX: Also check doc_type — if document was classified by deterministic rules,
    # treat it as successful even if AI extraction confidence was 0.
    has_valid_type = doc_type and doc_type not in ("Other", "Unknown", "Unknown_Document", "")
    if confidence > 0 or has_valid_type:
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value,
            context={"reason": f"AI classification completed with confidence {confidence:.2f}"}
        )
    else:
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value,
            context={"reason": "Classification failed or returned Unknown"}
        )
        # Save and return early for failed classification
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "workflow_status": doc.get("workflow_status"),
                "workflow_history": doc.get("workflow_history", []),
                "workflow_status_updated_utc": now,
                "square9_stage": Square9Stage.UNCLASSIFIED.value
            }}
        )
        return
    
    # =============== WAREHOUSE WORKFLOW (Square9-aligned) ===============
    # Follows Square9 diagram exactly:
    # 1. PO Number Is Empty? -> Set WF Status to "Missing PO Number"
    # 2. Invoice Number Is Empty? -> Set WF Status to "Missing Invoice Number" (BOL# for shipping)
    # 3. Document Date Is Empty? -> Set WF Status to "Missing Location"
    # 4. Counter >= 4? -> Delete Document
    # 5. All pass -> Send to SharePoint
    
    if doc_type in ["Shipping_Document", "Warehouse_Document", "SHIPPING_DOCUMENT", "WAREHOUSE_DOCUMENT"]:
        
        # Shipping docs store key fields in extracted_fields, not normalized_fields
        # (compute_ap_normalized_fields only processes AP-specific fields)
        ef = doc.get("extracted_fields") or {}

        # Helper function to handle validation failure with retry/delete logic
        async def handle_warehouse_validation_failure(doc, doc_id, field_name, stage, status_label):
            """Handle validation failure - increment retry, delete if max reached"""
            update_dict, should_delete, message = increment_retry(doc, status_label, stage)
            
            if should_delete and update_dict.get("square9_stage") == Square9Stage.DELETED.value:
                # Counter >= 4: DELETE DOCUMENT (Square9 behavior)
                logger.warning("[Warehouse Workflow] Doc %s: MAX RETRIES REACHED - DELETING. Reason: %s", doc_id, status_label)
                await db.hub_documents.delete_one({"id": doc_id})
                # Also delete from workflows collection
                await db.hub_workflows.delete_many({"document_id": doc_id})
                return True  # Document deleted
            else:
                # Counter < 4: Set status and wait for retry
                update_dict["workflow_status"] = "data_correction_pending"
                update_dict["status"] = "NeedsReview"
                update_dict["square9_stage"] = stage
                update_dict["workflow_status_updated_utc"] = now
                await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})
                logger.info("[Warehouse Workflow] Doc %s: %s - %s", doc_id, status_label, message)
                return False  # Document not deleted, needs review
        
        # Extract fields — check normalized_fields first, fall back to extracted_fields
        po_number = (normalized_fields.get("po_number_clean") or 
                    normalized_fields.get("po_number_raw") or 
                    normalized_fields.get("po_number") or
                    ef.get("po_number"))
        
        # For shipping docs, "Invoice Number" = BOL Number
        bol_number = (normalized_fields.get("bol_number") or 
                     normalized_fields.get("tracking_number") or
                     normalized_fields.get("pro_number") or
                     ef.get("bol_number") or
                     ef.get("tracking_number") or
                     ef.get("pro_number"))
        
        # Document Date = Ship Date
        document_date = (normalized_fields.get("ship_date") or 
                        normalized_fields.get("document_date") or
                        normalized_fields.get("delivery_date") or
                        ef.get("ship_date") or
                        ef.get("ship_date_raw") or
                        ef.get("document_date") or
                        ef.get("delivery_date"))
        
        # ===== STEP 1: PO Number Is Empty? =====
        if not po_number or str(po_number).strip() == "":
            deleted = await handle_warehouse_validation_failure(
                doc, doc_id, "po_number", 
                Square9Stage.MISSING_PO.value, 
                "Missing PO Number"
            )
            if deleted:
                return  # Document was deleted
            return  # Needs review
        
        # ===== STEP 2: Invoice Number (BOL#) Is Empty? =====
        if not bol_number or str(bol_number).strip() == "":
            deleted = await handle_warehouse_validation_failure(
                doc, doc_id, "bol_number",
                Square9Stage.MISSING_INVOICE.value,
                "Missing Invoice Number"  # Square9 label (BOL# for shipping docs)
            )
            if deleted:
                return
            return
        
        # ===== STEP 3: Document Date Is Empty? -> "Missing Location" (Square9 quirk) =====
        if not document_date or str(document_date).strip() == "":
            deleted = await handle_warehouse_validation_failure(
                doc, doc_id, "document_date",
                Square9Stage.MISSING_LOCATION.value,  # Square9 uses "Missing Location" for date
                "Missing Location"  # Square9 label
            )
            if deleted:
                return
            return
        
        # ===== ALL VALIDATIONS PASSED - Send to SharePoint =====
        
        # Location code validation (optional, use fallback if missing)
        location_code = normalized_fields.get("location_code") or normalized_fields.get("warehouse")
        is_valid_location, location_msg, resolved_location = validate_location_code(location_code, doc_type)
        
        if not is_valid_location:
            normalized_fields["location_code_resolved"] = resolved_location
            logger.info("[Warehouse Workflow] Doc %s: %s - using fallback: %s", doc_id, location_msg, resolved_location)
        
        # Reset retry counter on success
        reset_update = reset_retry_counter(doc, "Validation passed")
        
        # Advance workflow to exported
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value,
            context={"reason": "Warehouse document validated - PO, BOL, Date all present"}
        )
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_REVIEW_COMPLETE.value,
            context={"reason": "Warehouse validation complete - sending to SharePoint"}
        )
        
        # Mark as completed and archived
        final_update = {
            **reset_update,
            "workflow_status": "exported",
            "status": "Completed",
            "square9_stage": Square9Stage.EXPORTED.value,
            "workflow_history": doc.get("workflow_history", []),
            "workflow_status_updated_utc": now,
            "location_code_resolved": resolved_location if not is_valid_location else location_code,
            "bol_number_extracted": bol_number,
            "po_number_extracted": po_number,
            "document_date_extracted": document_date,
            "archived": True,
            "archived_utc": now
        }
        
        await db.hub_documents.update_one({"id": doc_id}, {"$set": final_update})
        logger.info("[Warehouse Workflow] Doc %s: COMPLETED - PO=%s, BOL=%s, Date=%s, archived to SharePoint", 
                   doc_id, po_number, bol_number, document_date)
        
        # Emit events for derived state tracking
        try:
            from services.event_service import get_event_service
            evt_svc = get_event_service()
            if evt_svc:
                await evt_svc.emit(
                    document_id=doc_id,
                    event_type="automation.decision.completed",
                    status="completed",
                    source_service="warehouse_workflow",
                    payload={
                        "decision": "Cleared",
                        "auto_clear": True,
                        "reason": f"Warehouse workflow: PO={po_number}, BOL={bol_number}, Date={document_date}",
                    },
                )
            else:
                # Fallback: write event directly to DB
                await db.workflow_events.insert_one({
                    "event_id": str(uuid.uuid4()),
                    "document_id": doc_id,
                    "event_type": "automation.decision.completed",
                    "status": "completed",
                    "source_service": "warehouse_workflow",
                    "timestamp": now,
                    "payload": {
                        "decision": "Cleared",
                        "auto_clear": True,
                        "reason": f"Warehouse workflow: PO={po_number}, BOL={bol_number}, Date={document_date}",
                    },
                })
        except Exception as evt_err:
            logger.warning("[Warehouse Workflow] Event emission error for %s: %s", doc_id[:8], str(evt_err))
        
        return
    
    # =============== SALES WORKFLOW ===============
    elif doc_type in [DocType.SALES_INVOICE.value, "SALES_ORDER", "Sales_Order", "SalesOrder", "SalesInvoice"]:
        # SAFETY: Inside Sales Pilot documents stop here — observation only
        _is_pilot_doc = doc.get("inside_sales_pilot") or doc.get("source") == "inside_sales_pilot"
        if _is_pilot_doc:
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "workflow_status": "pilot_review",
                    "status": "PilotReview",
                    "square9_stage": "pilot_observation",
                    "bc_create_ready": False,
                    "auto_create_so_blocked": True,
                    "pilot_note": "Ingest-only pilot — no BC writes, no workflow progression",
                    "workflow_status_updated_utc": now,
                }}
            )
            logger.info("[Sales Workflow] Doc %s: PILOT doc — parked at pilot_review (no BC writes)", doc_id)

            # Auto-run pilot enrichment pipeline (fire-and-forget)
            asyncio.create_task(_run_pilot_enrichment(doc_id))
            return

        # Step 2: Check Customer
        customer = normalized_fields.get("customer") or normalized_fields.get("customer_raw")
        if not customer:
            update_dict, escalated, message = increment_retry(doc, "Missing Customer", Square9Stage.MISSING_VENDOR.value)
            update_dict["workflow_status"] = "data_correction_pending"
            update_dict["status"] = "NeedsReview"
            update_dict["square9_stage"] = Square9Stage.MISSING_VENDOR.value
            await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})
            logger.info("[Sales Workflow] Doc %s: Missing Customer - %s", doc_id, message)
            return
        
        # Step 3: Check Order/Invoice Number
        order_number = (normalized_fields.get("order_number") or 
                       normalized_fields.get("invoice_number_clean") or
                       normalized_fields.get("customer_po"))
        if not order_number:
            update_dict, escalated, message = increment_retry(doc, "Missing Order/Invoice Number", Square9Stage.MISSING_INVOICE.value)
            update_dict["workflow_status"] = "data_correction_pending"
            update_dict["status"] = "NeedsReview"
            update_dict["square9_stage"] = Square9Stage.MISSING_INVOICE.value
            await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})
            logger.info("[Sales Workflow] Doc %s: Missing Order Number - %s", doc_id, message)
            return
        
        # All sales validations passed - mark as validated
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value,
            context={"reason": "Sales document validated successfully"}
        )
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_REVIEW_COMPLETE.value,
            context={"reason": "Sales validation complete - ready for BC creation"}
        )
        
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "workflow_status": "validated",
                "status": "Validated",
                "square9_stage": Square9Stage.VALID.value,
                "workflow_history": doc.get("workflow_history", []),
                "workflow_status_updated_utc": now,
                "bc_create_ready": True,
                "customer_extracted": customer,
                "order_number_extracted": order_number
            }}
        )
        logger.info("[Sales Workflow] Doc %s: VALIDATED - ready for BC Sales Order creation", doc_id)
        
        # ── Advisory: LLM Sales Order Readiness Review ──
        try:
            from services.sales_order_readiness_reviewer import review_sales_order_readiness
            customer_no = doc.get("matched_customer_no") or doc.get("customer_no") or ""
            cust_profile = None
            if customer_no:
                cust_profile = await db.customer_posting_profiles.find_one(
                    {"customer_no": customer_no, "status": "analyzed"}, {"_id": 0}
                )

            so_extracted = {
                "customer_name": customer,
                "customer_number": customer_no,
                "order_number": order_number,
                "po_number": normalized_fields.get("customer_po") or normalized_fields.get("po_number"),
                "order_date": normalized_fields.get("order_date") or normalized_fields.get("invoice_date"),
                "ship_to_name": normalized_fields.get("ship_to") or normalized_fields.get("ship_to_name"),
                "total_amount": normalized_fields.get("amount_float") or normalized_fields.get("amount"),
                "line_items": normalized_fields.get("line_items") or doc.get("line_items") or [],
            }
            review = await review_sales_order_readiness(
                extracted_order=so_extracted,
                customer_profile=cust_profile,
                validation_results=doc.get("validation_results"),
                document_context={"doc_id": doc_id, "doc_type": doc_type, "file_name": doc.get("file_name")},
            )
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {"so_readiness_review": review.to_dict()}}
            )
            logger.info("[Sales Workflow] Doc %s: SO readiness review: status=%s confidence=%.2f",
                        doc_id[:8], review.readiness_status, review.confidence)
        except Exception as rev_err:
            logger.warning("[Sales Workflow] SO readiness review failed for %s: %s", doc_id[:8], rev_err)

        # AUTO-CREATE: Attempt to create BC Sales Order
        # SAFETY: Skip for Inside Sales Pilot documents (ingest-only mode)
        _is_pilot = doc.get("inside_sales_pilot") or doc.get("source") == "inside_sales_pilot"
        if AUTO_CREATE_SALES_ORDER_ENABLED and not _is_pilot:
            try:
                # Refresh document after validation update
                updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
                if updated_doc:
                    bc_service = get_bc_service()
                    auto_create_result = await attempt_auto_create_sales_order(doc_id, updated_doc, db, bc_service)
                    
                    if auto_create_result.eligible:
                        if auto_create_result.success:
                            logger.info("AUTO-CREATE: Document %s auto-created as BC Sales Order %s", 
                                       doc_id, auto_create_result.bc_document_number)
                        else:
                            logger.warning("AUTO-CREATE: Document %s eligible but failed: %s", 
                                          doc_id, auto_create_result.error)
                    else:
                        logger.debug("AUTO-CREATE: Document %s not eligible: %s", 
                                    doc_id, auto_create_result.reason)
            except Exception as e:
                logger.error("AUTO-CREATE: Exception for %s: %s", doc_id, str(e))
        
        return
    
    # =============== DEFAULT/OTHER WORKFLOW ===============
    # Step 2: Check extraction quality
    vendor = normalized_fields.get("vendor_normalized") or normalized_fields.get("vendor_raw")
    invoice_number = normalized_fields.get("invoice_number_clean")
    amount = normalized_fields.get("amount_float")
    
    # For non-AP types, we're more lenient on required fields
    has_basic_data = any([vendor, invoice_number, amount is not None])
    
    if not has_basic_data or confidence < 0.3:
        # Low confidence or no data - needs review
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_FAILED.value,
            context={
                "reason": "Extraction incomplete or very low confidence",
                "metadata": {
                    "has_vendor": bool(vendor),
                    "has_invoice_number": bool(invoice_number),
                    "has_amount": amount is not None,
                    "confidence": confidence
                }
            }
        )
    else:
        # Extraction succeeded
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value,
            context={"reason": "Extraction completed successfully"}
        )
        
        # For standard workflow types (not AP), skip vendor/BC validation
        # Move directly to ready_for_approval or auto-approve based on doc_type
        if doc_type in [DocType.STATEMENT.value, DocType.REMINDER.value, 
                        DocType.FINANCE_CHARGE_MEMO.value, DocType.QUALITY_DOC.value,
                        DocType.OTHER.value]:
            # Simplified types can go directly to extracted -> exportable
            pass  # Stay at extracted, can be approved/exported manually
        else:
            # Standard business docs (Sales, PO, Credit Memo) advance to ready_for_approval
            WorkflowEngine.advance_workflow(
                doc,
                WorkflowEvent.ON_REVIEW_COMPLETE.value,
                context={"reason": f"Automatic review complete for {doc_type}"}
            )
    
    # Save workflow updates
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": doc.get("workflow_status"),
            "workflow_history": doc.get("workflow_history", []),
            "workflow_status_updated_utc": now,
            "square9_stage": determine_square9_stage(doc)
        }}
    )
