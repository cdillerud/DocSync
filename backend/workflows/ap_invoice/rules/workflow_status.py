"""
GPI Document Hub — AP-Invoice rule: workflow-status routing.

Phase 3 Step 4d.6 carve-out home for the AP-Invoice-specific workflow-status
helper. Moved verbatim from server.py:2253. The original `server` site is
retained as a 4-statement compatibility shim during the carve-out window.

Single public function: ``update_ap_workflow_status``.
"""
from typing import Dict
from datetime import datetime, timezone
import logging

from database import db
from workflows.core.engine import WorkflowEngine, WorkflowEvent

logger = logging.getLogger(__name__)


async def update_ap_workflow_status(
    doc_id: str,
    confidence: float,
    normalized_fields: Dict,
    vendor_alias_result: Dict,
    validation_results: Dict,
    ap_validation: Dict
):
    """
    Update workflow status for AP_Invoice documents based on processing results.
    This implements the Square9-style workflow routing.
    """
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        return
    
    now = datetime.now(timezone.utc).isoformat()
    workflow_updates = []
    
    # Step 1: Classification done - move from captured to classified
    WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value,
        context={"reason": f"AI classification completed with confidence {confidence:.2f}"}
    )
    workflow_updates.append("classified")
    
    # Step 2: Check extraction quality
    vendor = normalized_fields.get("vendor_normalized")
    invoice_number = normalized_fields.get("invoice_number_clean")
    amount = normalized_fields.get("amount_float")
    
    if not all([vendor, invoice_number, amount is not None]) or confidence < 0.5:
        # Low confidence or missing required fields - needs data correction
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_LOW_CONFIDENCE.value,
            context={
                "reason": "Extraction incomplete or low confidence",
                "metadata": {
                    "has_vendor": bool(vendor),
                    "has_invoice_number": bool(invoice_number),
                    "has_amount": amount is not None,
                    "confidence": confidence
                }
            }
        )
        workflow_updates.append("data_correction_pending")
    else:
        # Extraction succeeded
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value,
            context={"reason": "Extraction completed successfully"}
        )
        workflow_updates.append("extracted")
        
        # Step 3: Check vendor match
        vendor_canonical = vendor_alias_result.get("vendor_canonical")
        vendor_match_method = vendor_alias_result.get("vendor_match_method")
        
        if not vendor_canonical or vendor_match_method == "none":
            # Vendor not matched - needs manual resolution
            WorkflowEngine.advance_workflow(
                doc,
                WorkflowEvent.ON_VENDOR_MISSING.value,
                context={
                    "reason": "Vendor could not be matched automatically",
                    "metadata": {"vendor_raw": normalized_fields.get("vendor_raw")}
                }
            )
            workflow_updates.append("vendor_pending")
        else:
            # Vendor matched
            WorkflowEngine.advance_workflow(
                doc,
                WorkflowEvent.ON_VENDOR_MATCHED.value,
                context={
                    "reason": f"Vendor matched via {vendor_match_method}",
                    "metadata": {
                        "vendor_canonical": vendor_canonical,
                        "match_method": vendor_match_method
                    }
                }
            )
            workflow_updates.append("bc_validation_pending")
            
            # Step 4: Check BC validation
            all_passed = validation_results.get("all_passed", False)
            draft_candidate = ap_validation.get("draft_candidate", False)
            
            if all_passed or draft_candidate:
                # BC validation passed - ready for approval
                WorkflowEngine.advance_workflow(
                    doc,
                    WorkflowEvent.ON_BC_VALID.value,
                    context={
                        "reason": "BC validation passed",
                        "metadata": {
                            "all_passed": all_passed,
                            "draft_candidate": draft_candidate
                        }
                    }
                )
                workflow_updates.append("ready_for_approval")
            else:
                # BC validation failed
                validation_errors = ap_validation.get("validation_errors", [])
                WorkflowEngine.advance_workflow(
                    doc,
                    WorkflowEvent.ON_BC_INVALID.value,
                    context={
                        "reason": "BC validation failed",
                        "metadata": {"validation_errors": validation_errors}
                    }
                )
                workflow_updates.append("bc_validation_failed")
    
    # Save workflow updates
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": doc.get("workflow_status"),
            "workflow_history": doc.get("workflow_history", []),
            "workflow_status_updated_utc": now
        }}
    )
    
    logger.info("[Workflow] Document %s workflow updated: %s", doc_id, " -> ".join(workflow_updates))
