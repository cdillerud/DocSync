"""GPI Document Hub - AP Validation Router"""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException
from deps import get_db
from services.ap_validation_service import APValidationService

router = APIRouter(prefix="/ap-validation", tags=["AP Validation"])


def _get_bc_service():
    from services.business_central_service import get_bc_service
    return get_bc_service()


def _get_event_service():
    from services.event_service import get_event_service
    return get_event_service()


@router.post("/validate/{doc_id}")
async def validate_document_ap(doc_id: str):
    """
    Manually trigger AP validation for a document.
    This runs the full APValidationService pipeline and stores results.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    bc_service = _get_bc_service()
    event_service = _get_event_service()
    svc = APValidationService(db, bc_service=bc_service, event_service=event_service)
    
    # Build vendor match result from document
    vendor_no = doc.get("matched_vendor_no") or doc.get("vendor_id")
    vendor_name = doc.get("matched_vendor_name") or doc.get("vendor_canonical")
    uvm = doc.get("unified_vendor_match") or {}
    if not vendor_no and uvm.get("bc_vendor_number"):
        vendor_no = uvm["bc_vendor_number"]
        vendor_name = uvm.get("best_match", {}).get("name") or vendor_name
    
    # Cross-reference BC validation results — if BC resolved the vendor, use that
    bc_val = doc.get("validation_results") or {}
    bc_record = bc_val.get("bc_record_info") or {}
    if not vendor_no and bc_record.get("number"):
        vendor_no = bc_record["number"]
        vendor_name = bc_record.get("displayName") or vendor_name
    
    vendor_match = None
    if vendor_no:
        vendor_match = {
            "matched": True,
            "bc_vendor_number": vendor_no,
            "best_match": {"vendor_number": vendor_no, "name": vendor_name},
            "source": doc.get("vendor_match_method") or uvm.get("source") or "manual",
            "score": doc.get("match_score") or uvm.get("score", 0.0),
        }
    elif vendor_name:
        vendor_match = {"matched": False, "vendor_raw": vendor_name}
    
    # Build extracted fields
    extracted_fields = doc.get("extracted_fields") or {}
    for key, doc_key in [("invoice_number", "invoice_number_clean"), ("invoice_date", "invoice_date"), 
                          ("amount", "amount_float"), ("vendor", "vendor_raw"), ("po_number", "po_number_clean")]:
        if doc.get(doc_key) and not extracted_fields.get(key):
            extracted_fields[key] = doc[doc_key]
    
    result = await svc.validate_ap_invoice(
        document=doc,
        extracted_fields=extracted_fields,
        vendor_match_result=vendor_match,
    )
    
    result_dict = result.to_dict()
    result_dict["validation_version"] = "2.0.0"
    result_dict["validation_source"] = "manual_trigger"
    
    # Determine derived states
    v_state = result_dict["validation_state"]
    workflow_state = "reviewing"
    automation_state = "manual"
    if v_state == "pass":
        workflow_state = "ready"
        automation_state = "assisted"
    elif v_state == "warning":
        workflow_state = "reviewing"
        automation_state = "assisted"
    elif v_state == "fail":
        workflow_state = "needs_review"
        automation_state = "manual"
    
    # Store on document
    update = {
        "ap_validation_result": result_dict,
        "validation_state": v_state,
        "validation_passed": v_state in ("pass", "warning"),
        "validation_errors": result_dict.get("blocking_issues", []),
        "validation_warnings": [w.get("details", str(w)) if isinstance(w, dict) else str(w) for w in result_dict.get("warnings", [])],
        "validation_summary": f"{'Validated' if v_state in ('pass', 'warning') else 'Failed'}: {len([c for c in result_dict.get('checks', []) if c.get('passed')])}/{len(result_dict.get('checks', []))} checks",
        "validation_version": "2.0.0",
        "validation_last_run": datetime.now(timezone.utc).isoformat(),
        "derived_workflow_state": workflow_state,
        "derived_automation_state": automation_state,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update})
    
    # Emit event
    if event_service:
        await event_service.emit(
            event_type="validation.completed",
            document_id=doc_id,
            status="completed",
            source_service="ap_validation_manual",
            payload={
                "document_type": doc.get("document_type"),
                "validation_state": v_state,
                "all_passed": result_dict.get("all_passed", False),
                "blocking_issues_count": len(result_dict.get("blocking_issues", [])),
                "warnings_count": len(result_dict.get("warnings", [])),
                "vendor_resolved": result_dict.get("vendor_resolved", False),
                "invoice_number_present": result_dict.get("invoice_number_present", False),
                "invoice_date_present": result_dict.get("invoice_date_present", False),
                "total_amount_present": result_dict.get("total_amount_present", False),
                "is_duplicate": result_dict.get("is_duplicate", False),
            }
        )
    
    return result_dict


@router.get("/status/{doc_id}")
async def get_ap_validation_status(doc_id: str):
    """Get AP validation status for a document."""
    db = get_db()
    doc = await db.hub_documents.find_one(
        {"id": doc_id},
        {"_id": 0, "ap_validation_result": 1, "validation_state": 1, 
         "validation_passed": 1, "validation_errors": 1, "validation_warnings": 1,
         "validation_summary": 1, "validation_version": 1, "validation_last_run": 1,
         "derived_workflow_state": 1, "derived_automation_state": 1}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc
