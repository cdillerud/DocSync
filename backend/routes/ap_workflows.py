"""
AP-invoice workflow queues/mutations + generic multi-type workflow endpoints.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 13b). No logic changed.
"""
import re
from typing import Optional, List
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.db import db
from services.workflow_engine import WorkflowEngine, WorkflowStatus, WorkflowEvent, DocType
from services.ingestion_engine import normalize_vendor_name
from services.pilot_config import is_export_blocked

router = APIRouter(prefix="/api")


@router.get("/workflows/ap_invoice/metrics")
async def get_ap_workflow_metrics(days: int = Query(30)):
    """
    Get workflow metrics for AP_Invoice documents.
    Includes counts per status and time-in-status averages.
    """
    cutoff_date = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()

    status_pipeline = [
        {"$match": {"document_type": "AP_Invoice", "created_utc": {"$gte": cutoff_date}}},
        {"$group": {"_id": "$workflow_status", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ]
    status_results = await db.hub_documents.aggregate(status_pipeline).to_list(100)
    status_counts = {r["_id"] or "none": r["count"] for r in status_results}

    daily_pipeline = [
        {"$match": {"document_type": "AP_Invoice", "created_utc": {"$gte": cutoff_date}}},
        {"$unwind": {"path": "$workflow_history", "preserveNullAndEmptyArrays": True}},
        {"$addFields": {
            "history_date": {"$substr": ["$workflow_history.timestamp", 0, 10]}
        }},
        {"$group": {
            "_id": {"date": "$history_date", "to_status": "$workflow_history.to_status"},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id.date": -1}}
    ]
    daily_results = await db.hub_documents.aggregate(daily_pipeline).to_list(1000)

    daily_by_date = {}
    for r in daily_results:
        date = r["_id"]["date"]
        status = r["_id"]["to_status"]
        if date and status:
            if date not in daily_by_date:
                daily_by_date[date] = {}
            daily_by_date[date][status] = r["count"]

    return {
        "period_days": days,
        "status_counts": status_counts,
        "total_documents": sum(status_counts.values()),
        "exception_queue_count": sum(
            status_counts.get(s, 0) for s in WorkflowEngine.get_exception_statuses()
        ),
        "daily_transitions": daily_by_date,
        "all_statuses": WorkflowEngine.get_all_statuses()
    }

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


@router.get("/workflows/ap_invoice/status-counts")
async def get_ap_workflow_status_counts():
    """Get counts of AP_INVOICE documents by workflow status."""
    pipeline = [
        {"$match": {"$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}  # Backward compatibility
        ]}},
        {"$group": {"_id": "$workflow_status", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}}
    ]
    results = await db.hub_documents.aggregate(pipeline).to_list(100)
    
    # Convert to dict format
    counts = {r["_id"] or "none": r["count"] for r in results}
    
    return {
        "status_counts": counts,
        "total": sum(counts.values()),
        "exception_queue_total": sum(
            counts.get(s, 0) for s in WorkflowEngine.get_exception_statuses(DocType.AP_INVOICE.value)
        )
    }


@router.get("/workflows/ap_invoice/vendor-pending")
async def get_vendor_pending_queue(
    skip: int = Query(0),
    limit: int = Query(50),
    vendor_raw: Optional[str] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None)
):
    """
    Get AP_INVOICE documents in vendor_pending status.
    These are documents where the vendor could not be automatically matched.
    """
    fq = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.VENDOR_PENDING.value
    }
    
    if vendor_raw:
        fq["vendor_raw"] = {"$regex": vendor_raw, "$options": "i"}
    if min_amount is not None:
        fq["amount_float"] = {"$gte": min_amount}
    if max_amount is not None:
        fq.setdefault("amount_float", {})["$lte"] = max_amount
    if date_from:
        fq["created_utc"] = {"$gte": date_from}
    if date_to:
        fq.setdefault("created_utc", {})["$lte"] = date_to
    
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"documents": docs, "total": total, "queue": "vendor_pending"}


@router.get("/workflows/ap_invoice/bc-validation-pending")
async def get_bc_validation_pending_queue(
    skip: int = Query(0),
    limit: int = Query(50),
    vendor_canonical: Optional[str] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None)
):
    """
    Get AP_INVOICE documents awaiting BC validation.
    These documents have matched vendors and are being validated against BC.
    """
    fq = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.BC_VALIDATION_PENDING.value
    }
    
    if vendor_canonical:
        fq["vendor_canonical"] = vendor_canonical
    if min_amount is not None:
        fq["amount_float"] = {"$gte": min_amount}
    if max_amount is not None:
        fq.setdefault("amount_float", {})["$lte"] = max_amount
    
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"documents": docs, "total": total, "queue": "bc_validation_pending"}


@router.get("/workflows/ap_invoice/bc-validation-failed")
async def get_bc_validation_failed_queue(
    skip: int = Query(0),
    limit: int = Query(50),
    vendor_canonical: Optional[str] = Query(None),
    validation_error: Optional[str] = Query(None)
):
    """
    Get AP_INVOICE documents that failed BC validation.
    These need manual override or data correction.
    """
    fq = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.BC_VALIDATION_FAILED.value
    }
    
    if vendor_canonical:
        fq["vendor_canonical"] = vendor_canonical
    if validation_error:
        fq["validation_errors"] = {"$elemMatch": {"$regex": validation_error, "$options": "i"}}
    
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"documents": docs, "total": total, "queue": "bc_validation_failed"}


@router.get("/workflows/ap_invoice/data-correction-pending")
async def get_data_correction_pending_queue(
    skip: int = Query(0),
    limit: int = Query(50)
):
    """
    Get AP_INVOICE documents that need manual data correction.
    These have incomplete or low-confidence extraction results.
    """
    fq = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.DATA_CORRECTION_PENDING.value
    }
    
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"documents": docs, "total": total, "queue": "data_correction_pending"}


@router.get("/workflows/ap_invoice/ready-for-approval")
async def get_ready_for_approval_queue(
    skip: int = Query(0),
    limit: int = Query(50),
    vendor_canonical: Optional[str] = Query(None),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None)
):
    """
    Get AP_INVOICE documents ready for approval.
    These have passed all validations and are waiting for human approval.
    """
    fq = {
        "$or": [
            {"doc_type": DocType.AP_INVOICE.value},
            {"document_type": "AP_Invoice"}
        ],
        "workflow_status": WorkflowStatus.READY_FOR_APPROVAL.value
    }
    
    if vendor_canonical:
        fq["vendor_canonical"] = vendor_canonical
    if min_amount is not None:
        fq["amount_float"] = {"$gte": min_amount}
    if max_amount is not None:
        fq.setdefault("amount_float", {})["$lte"] = max_amount
    
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"documents": docs, "total": total, "queue": "ready_for_approval"}


# ==================== GENERIC WORKFLOW QUEUE API ====================

@router.get("/workflows/generic/queue")
async def get_workflow_queue(
    doc_type: str = Query(..., description="Document type (required): AP_INVOICE, SALES_INVOICE, PURCHASE_ORDER, etc."),
    status: Optional[str] = Query(None, description="Workflow status filter"),
    vendor: Optional[str] = Query(None, description="Vendor name filter"),
    min_amount: Optional[float] = Query(None),
    max_amount: Optional[float] = Query(None),
    date_from: Optional[str] = Query(None),
    date_to: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(50)
):
    """
    Generic workflow queue endpoint supporting all document types.
    Use this as a single entry point for building work queues for any doc_type.
    
    Required: doc_type
    Optional: status (workflow_status), vendor, amount range, date range
    """
    fq = {"doc_type": doc_type}
    
    if status:
        fq["workflow_status"] = status
    if vendor:
        fq["$or"] = [
            {"vendor_raw": {"$regex": vendor, "$options": "i"}},
            {"vendor_canonical": {"$regex": vendor, "$options": "i"}}
        ]
    if min_amount is not None:
        fq["amount_float"] = {"$gte": min_amount}
    if max_amount is not None:
        fq.setdefault("amount_float", {})["$lte"] = max_amount
    if date_from:
        fq["created_utc"] = {"$gte": date_from}
    if date_to:
        fq.setdefault("created_utc", {})["$lte"] = date_to
    
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {
        "documents": docs,
        "total": total,
        "doc_type": doc_type,
        "status": status,
        "skip": skip,
        "limit": limit
    }


@router.get("/workflows/generic/status-counts-by-type")
async def get_status_counts_by_doc_type():
    """
    Get document counts grouped by doc_type and workflow_status.
    Returns a nested structure for metrics dashboards.
    """
    pipeline = [
        {"$group": {
            "_id": {
                "doc_type": "$doc_type",
                "workflow_status": "$workflow_status"
            },
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id.doc_type": 1, "_id.workflow_status": 1}}
    ]
    results = await db.hub_documents.aggregate(pipeline).to_list(500)
    
    # Structure the results by doc_type
    documents_by_type_and_status = {}
    for r in results:
        doc_type = r["_id"].get("doc_type") or "unknown"
        status = r["_id"].get("workflow_status") or "none"
        count = r["count"]
        
        if doc_type not in documents_by_type_and_status:
            documents_by_type_and_status[doc_type] = {"statuses": {}, "total": 0}
        
        documents_by_type_and_status[doc_type]["statuses"][status] = count
        documents_by_type_and_status[doc_type]["total"] += count
    
    return {
        "documents_by_type_and_status": documents_by_type_and_status,
        "supported_doc_types": WorkflowEngine.get_all_doc_types(),
        "supported_statuses": WorkflowEngine.get_all_statuses()
    }


@router.get("/workflows/generic/metrics-by-type")
async def get_workflow_metrics_by_doc_type(
    days: int = Query(30, description="Number of days for metrics"),
    doc_type: Optional[str] = Query(None, description="Filter by specific doc_type")
):
    """
    Get workflow metrics grouped by document type.
    Includes extraction rates, time-in-status, and completion rates per type.
    """
    from datetime import timedelta
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # Build match filter
    match_filter = {"created_utc": {"$gte": cutoff}}
    if doc_type:
        match_filter["doc_type"] = doc_type
    
    # Aggregation for status distribution by type
    status_pipeline = [
        {"$match": match_filter},
        {"$group": {
            "_id": {
                "doc_type": "$doc_type",
                "workflow_status": "$workflow_status"
            },
            "count": {"$sum": 1}
        }}
    ]
    status_results = await db.hub_documents.aggregate(status_pipeline).to_list(500)
    
    # Aggregation for extraction rates by type
    extraction_pipeline = [
        {"$match": match_filter},
        {"$group": {
            "_id": "$doc_type",
            "total": {"$sum": 1},
            "extracted": {"$sum": {"$cond": [{"$ne": ["$extracted_fields", None]}, 1, 0]}},
            "high_confidence": {"$sum": {"$cond": [{"$gte": ["$ai_confidence", 0.8]}, 1, 0]}},
            "avg_confidence": {"$avg": {"$ifNull": ["$ai_confidence", 0]}}
        }}
    ]
    extraction_results = await db.hub_documents.aggregate(extraction_pipeline).to_list(50)
    
    # Structure results
    metrics_by_type = {}
    
    # Process status counts
    for r in status_results:
        dt = r["_id"].get("doc_type") or "unknown"
        status = r["_id"].get("workflow_status") or "none"
        
        if dt not in metrics_by_type:
            metrics_by_type[dt] = {
                "status_counts": {},
                "total": 0,
                "extraction_rate": 0,
                "high_confidence_rate": 0,
                "avg_confidence": 0
            }
        
        metrics_by_type[dt]["status_counts"][status] = r["count"]
        metrics_by_type[dt]["total"] += r["count"]
    
    # Add extraction metrics
    for r in extraction_results:
        dt = r["_id"] or "unknown"
        if dt in metrics_by_type:
            total = r["total"] or 1
            metrics_by_type[dt]["extraction_rate"] = round((r["extracted"] / total) * 100, 2)
            metrics_by_type[dt]["high_confidence_rate"] = round((r["high_confidence"] / total) * 100, 2)
            metrics_by_type[dt]["avg_confidence"] = round(r["avg_confidence"] * 100, 2)
    
    return {
        "period_days": days,
        "metrics_by_type": metrics_by_type,
        "cutoff_date": cutoff
    }


# ==================== AP INVOICE WORKFLOW MUTATIONS ====================

@router.post("/workflows/ap_invoice/{doc_id}/set-vendor")
async def set_vendor_for_document(doc_id: str, request: SetVendorRequest):
    """
    Manually set/resolve vendor for a document in vendor_pending status.
    This moves the document from vendor_pending to bc_validation_pending.
    Only for AP_INVOICE documents.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    # Check doc_type (with backward compatibility for document_type)
    doc_type = doc.get("doc_type") or (DocType.AP_INVOICE.value if doc.get("document_type") == "AP_Invoice" else None)
    if doc_type != DocType.AP_INVOICE.value:
        raise HTTPException(status_code=400, detail="This endpoint only supports AP_INVOICE documents")
    
    current_status = doc.get("workflow_status")
    if current_status != WorkflowStatus.VENDOR_PENDING.value:
        raise HTTPException(
            status_code=400, 
            detail=f"Document is in status '{current_status}', expected 'vendor_pending'"
        )
    
    # Update vendor fields
    update_data = {
        "vendor_canonical": request.vendor_id,
        "vendor_match_method": "manual",
        "vendor_match_score": 1.0,
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }
    
    if request.vendor_name:
        update_data["vendor_resolved_name"] = request.vendor_name
    
    # Create vendor alias if provided
    if request.vendor_alias_used and doc.get("vendor_normalized"):
        alias_doc = {
            "alias_string": request.vendor_alias_used,
            "normalized_alias": doc.get("vendor_normalized"),
            "canonical_vendor_id": request.vendor_id,
            "vendor_name": request.vendor_name,
            "created_utc": datetime.now(timezone.utc).isoformat(),
            "source": "manual_resolution"
        }
        await db.vendor_aliases.update_one(
            {"normalized_alias": doc.get("vendor_normalized")},
            {"$set": alias_doc},
            upsert=True
        )
    
    # Advance workflow
    doc.update(update_data)
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_VENDOR_RESOLVED.value,
        context={
            "reason": request.reason or "Vendor manually resolved",
            "metadata": {"vendor_id": request.vendor_id}
        },
        actor="user"
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")
    
    # Save to database
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": doc}
    )
    
    # Exclude _id from response
    doc.pop("_id", None)
    
    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Vendor set to {request.vendor_id}, document moved to bc_validation_pending"
    }


@router.post("/workflows/ap_invoice/{doc_id}/update-fields")
async def update_document_fields(doc_id: str, request: UpdateFieldsRequest):
    """
    Manually update/correct fields on a document.
    Re-runs validation and advances workflow based on new data.
    Works for any document type, but AP-specific validation only runs for AP_INVOICE.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    # Get doc_type with backward compatibility
    doc_type = doc.get("doc_type") or (DocType.AP_INVOICE.value if doc.get("document_type") == "AP_Invoice" else DocType.OTHER.value)
    
    current_status = doc.get("workflow_status")
    valid_statuses = [
        WorkflowStatus.DATA_CORRECTION_PENDING.value,
        WorkflowStatus.BC_VALIDATION_FAILED.value,
        WorkflowStatus.VENDOR_PENDING.value,
        WorkflowStatus.REVIEW_PENDING.value,
        WorkflowStatus.EXTRACTED.value
    ]
    
    if current_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', field updates allowed in: {valid_statuses}"
        )
    
    # Update fields
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
        update_data["po_number_clean"] = re.sub(r'[^a-zA-Z0-9]', '', request.po_number.upper()) if request.po_number else None
    
    if request.due_date is not None:
        extracted_fields["due_date"] = request.due_date
    
    if request.vendor_name is not None:
        extracted_fields["vendor"] = request.vendor_name
        update_data["vendor_raw"] = request.vendor_name
        update_data["vendor_normalized"] = normalize_vendor_name(request.vendor_name)
    
    update_data["extracted_fields"] = extracted_fields
    
    # Determine which event to fire based on current status
    if current_status == WorkflowStatus.DATA_CORRECTION_PENDING.value:
        event = WorkflowEvent.ON_DATA_CORRECTED.value
    elif current_status == WorkflowStatus.BC_VALIDATION_FAILED.value:
        event = WorkflowEvent.ON_DATA_CORRECTED.value
    else:
        event = WorkflowEvent.ON_DATA_CORRECTED.value
    
    # Apply updates and advance workflow
    doc.update(update_data)
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        event,
        context={
            "reason": request.reason or "Fields manually updated",
            "metadata": {"updated_fields": list(request.model_dump(exclude_none=True).keys())}
        },
        actor="user"
    )
    
    # Save to database
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": doc}
    )
    
    doc.pop("_id", None)
    
    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict() if success else None,
        "message": "Fields updated" + (", workflow advanced" if success else "")
    }


@router.post("/workflows/ap_invoice/{doc_id}/override-bc-validation")
async def override_bc_validation(doc_id: str, request: BCValidationOverrideRequest):
    """
    Override a failed BC validation and move document to ready_for_approval.
    This is a privileged action that bypasses normal validation rules.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    if doc.get("document_type") != "AP_Invoice":
        raise HTTPException(status_code=400, detail="This endpoint only supports AP_Invoice documents")
    
    current_status = doc.get("workflow_status")
    if current_status != WorkflowStatus.BC_VALIDATION_FAILED.value:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', expected 'bc_validation_failed'"
        )
    
    # Record the override
    override_record = {
        "override_reason": request.override_reason,
        "override_user": request.override_user,
        "override_utc": datetime.now(timezone.utc).isoformat(),
        "original_validation_errors": doc.get("validation_errors", [])
    }
    
    doc["bc_validation_override"] = override_record
    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    
    # Advance workflow
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_BC_VALIDATION_OVERRIDE.value,
        context={
            "reason": request.override_reason,
            "metadata": {"override_user": request.override_user}
        },
        actor=request.override_user
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")
    
    # Save to database
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": doc}
    )
    
    doc.pop("_id", None)
    
    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"BC validation overridden by {request.override_user}, document moved to ready_for_approval"
    }


# ==================== AP INVOICE APPROVAL WORKFLOW ====================

@router.post("/workflows/ap_invoice/{doc_id}/start-approval")
async def start_approval(doc_id: str, request: ApprovalActionRequest):
    """
    Start the approval process for a document.
    Moves from ready_for_approval to approval_in_progress.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    if doc.get("document_type") != "AP_Invoice":
        raise HTTPException(status_code=400, detail="This endpoint only supports AP_Invoice documents")
    
    current_status = doc.get("workflow_status")
    if current_status != WorkflowStatus.READY_FOR_APPROVAL.value:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', expected 'ready_for_approval'"
        )
    
    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    doc["approval_started_utc"] = datetime.now(timezone.utc).isoformat()
    
    if request.approver:
        doc["assigned_approver"] = request.approver
    
    # Advance workflow
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_APPROVAL_STARTED.value,
        context={
            "reason": request.reason or "Approval process started",
            "metadata": {"approver": request.approver}
        },
        actor=request.approver or "system"
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc})
    doc.pop("_id", None)
    
    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Approval process started"
    }


@router.post("/workflows/ap_invoice/{doc_id}/approve")
async def approve_document(doc_id: str, request: ApprovalActionRequest):
    """
    Approve a document. Moves to 'approved' status.
    Can be called from ready_for_approval (auto-approval) or approval_in_progress.
    Works for all document types.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    # Get doc_type with backward compatibility
    doc_type = doc.get("doc_type") or (DocType.AP_INVOICE.value if doc.get("document_type") == "AP_Invoice" else DocType.OTHER.value)
    
    current_status = doc.get("workflow_status")
    valid_statuses = [
        WorkflowStatus.READY_FOR_APPROVAL.value,
        WorkflowStatus.APPROVAL_IN_PROGRESS.value,
        WorkflowStatus.EXTRACTED.value,  # Allow approval from extracted for non-AP docs
        WorkflowStatus.REVIEW_PENDING.value
    ]
    
    if current_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', approval allowed from: {valid_statuses}"
        )
    
    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    doc["approved_utc"] = datetime.now(timezone.utc).isoformat()
    doc["approved_by"] = request.approver or "system"
    
    # Advance workflow
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_APPROVED.value,
        context={
            "reason": request.reason or "Document approved",
            "metadata": {"approver": request.approver, "doc_type": doc_type}
        },
        actor=request.approver or "system"
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc})
    doc.pop("_id", None)
    
    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Document approved by {request.approver or 'system'}"
    }


@router.post("/workflows/ap_invoice/{doc_id}/reject")
async def reject_document(doc_id: str, request: ApprovalActionRequest):
    """
    Reject a document. Moves to 'rejected' status.
    Works for all document types.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    # Get doc_type with backward compatibility
    doc_type = doc.get("doc_type") or (DocType.AP_INVOICE.value if doc.get("document_type") == "AP_Invoice" else DocType.OTHER.value)
    
    current_status = doc.get("workflow_status")
    valid_statuses = [
        WorkflowStatus.READY_FOR_APPROVAL.value,
        WorkflowStatus.APPROVAL_IN_PROGRESS.value,
        WorkflowStatus.EXTRACTED.value,
        WorkflowStatus.REVIEW_PENDING.value
    ]
    
    if current_status not in valid_statuses:
        raise HTTPException(
            status_code=400,
            detail=f"Document is in status '{current_status}', rejection allowed from: {valid_statuses}"
        )
    
    if not request.reason:
        raise HTTPException(status_code=400, detail="Rejection reason is required")
    
    doc["updated_utc"] = datetime.now(timezone.utc).isoformat()
    doc["rejected_utc"] = datetime.now(timezone.utc).isoformat()
    doc["rejected_by"] = request.approver or "system"
    doc["rejection_reason"] = request.reason
    
    # Advance workflow
    _, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_REJECTED.value,
        context={
            "reason": request.reason,
            "metadata": {"rejector": request.approver, "doc_type": doc_type}
        },
        actor=request.approver or "system"
    )
    
    if not success:
        raise HTTPException(status_code=400, detail="Failed to advance workflow")
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc})
    doc.pop("_id", None)
    
    return {
        "document": doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Document rejected: {request.reason}"
    }


# ==================== GENERIC WORKFLOW MUTATION ENDPOINTS ====================

@router.post("/workflows/{doc_id}/mark-ready-for-review")
async def mark_ready_for_review(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None
):
    """
    Mark a document as ready for review.
    Applicable to: STATEMENT, REMINDER, FINANCE_CHARGE_MEMO, QUALITY_DOC, OTHER
    
    Triggers: on_mark_ready_for_review event
    """
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
            "metadata": {"triggered_by": actor}
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot transition to ready_for_review from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"]
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Document marked ready for review"
    }


@router.post("/workflows/{doc_id}/mark-reviewed")
async def mark_reviewed(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None
):
    """
    Mark a document as reviewed.
    Applicable to: STATEMENT, REMINDER, FINANCE_CHARGE_MEMO, QUALITY_DOC
    
    Triggers: on_reviewed event
    """
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
            "metadata": {"triggered_by": actor}
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot mark as reviewed from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"]
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Document marked as reviewed"
    }


@router.post("/workflows/{doc_id}/start-approval")
async def start_approval_generic(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None
):
    """
    Start approval process for a document (generic version).
    Applicable to: SALES_INVOICE, PURCHASE_ORDER, SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO, QUALITY_DOC
    
    Triggers: on_approval_started event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    # For AP_INVOICE, redirect to the existing AP-specific endpoint
    if doc_type == DocType.AP_INVOICE.value:
        raise HTTPException(
            status_code=400, 
            detail="AP_INVOICE documents should use /api/workflows/ap_invoice/{doc_id}/start-approval"
        )
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_APPROVAL_STARTED.value,
        context={
            "reason": reason or "Approval process started",
            "metadata": {"triggered_by": actor}
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot start approval from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"]
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Approval process started"
    }


@router.post("/workflows/{doc_id}/approve")
async def approve_generic(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None
):
    """
    Approve a document (generic version).
    Applicable to: SALES_INVOICE, PURCHASE_ORDER, SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO
    
    Triggers: on_approved event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    # For AP_INVOICE, redirect to the existing AP-specific endpoint
    if doc_type == DocType.AP_INVOICE.value:
        raise HTTPException(
            status_code=400, 
            detail="AP_INVOICE documents should use /api/workflows/ap_invoice/{doc_id}/approve"
        )
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_APPROVED.value,
        context={
            "reason": reason or "Document approved",
            "metadata": {"triggered_by": actor}
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot approve from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"]
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Document approved"
    }


@router.post("/workflows/{doc_id}/reject")
async def reject_generic(
    doc_id: str,
    reason: str = Query(..., description="Reason for rejection (required)"),
    user: Optional[str] = None
):
    """
    Reject a document (generic version).
    Applicable to: SALES_INVOICE, PURCHASE_ORDER, SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO, QUALITY_DOC
    
    Triggers: on_rejected event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    # For AP_INVOICE, redirect to the existing AP-specific endpoint
    if doc_type == DocType.AP_INVOICE.value:
        raise HTTPException(
            status_code=400, 
            detail="AP_INVOICE documents should use /api/workflows/ap_invoice/{doc_id}/reject"
        )
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_REJECTED.value,
        context={
            "reason": reason,
            "metadata": {"triggered_by": actor}
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot reject from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"]
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Document rejected: {reason}"
    }


@router.post("/workflows/{doc_id}/complete-triage")
async def complete_triage(
    doc_id: str,
    reason: Optional[str] = None,
    user: Optional[str] = None
):
    """
    Complete triage for an OTHER document.
    Applicable to: OTHER
    
    Triggers: on_triage_completed event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    if doc_type != DocType.OTHER.value:
        raise HTTPException(
            status_code=400, 
            detail=f"Triage completion is only applicable to OTHER documents, not {doc_type}"
        )
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_TRIAGE_COMPLETED.value,
        context={
            "reason": reason or "Triage completed",
            "metadata": {"triggered_by": actor}
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot complete triage from status '{doc.get('workflow_status')}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"]
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Triage completed"
    }


@router.post("/workflows/{doc_id}/link-credit-to-invoice")
async def link_credit_to_invoice(
    doc_id: str,
    invoice_id: str = Query(..., description="ID of the original invoice"),
    user: Optional[str] = None
):
    """
    Link a credit memo to its original invoice.
    Applicable to: SALES_CREDIT_MEMO, PURCHASE_CREDIT_MEMO
    
    Triggers: on_credit_linked_to_invoice event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    valid_types = [DocType.SALES_CREDIT_MEMO.value, DocType.PURCHASE_CREDIT_MEMO.value]
    if doc_type not in valid_types:
        raise HTTPException(
            status_code=400, 
            detail=f"Invoice linkage is only applicable to credit memos, not {doc_type}"
        )
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_CREDIT_LINKED_TO_INVOICE.value,
        context={
            "reason": f"Linked to invoice {invoice_id}",
            "metadata": {
                "triggered_by": actor,
                "linked_invoice_id": invoice_id
            }
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot link to invoice from status '{doc.get('workflow_status')}'"
        )
    
    # Store the linked invoice reference
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
            "linked_invoice_id": invoice_id
        }}
    )
    
    updated_doc["linked_invoice_id"] = invoice_id
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Credit memo linked to invoice {invoice_id}"
    }


@router.post("/workflows/{doc_id}/tag-quality")
async def tag_quality_doc(
    doc_id: str,
    tags: List[str] = Query(..., description="Quality tags to apply"),
    user: Optional[str] = None
):
    """
    Tag a quality document for categorization.
    Applicable to: QUALITY_DOC
    
    Triggers: on_quality_tagged event
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    if doc_type != DocType.QUALITY_DOC.value:
        raise HTTPException(
            status_code=400, 
            detail=f"Quality tagging is only applicable to QUALITY_DOC, not {doc_type}"
        )
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_QUALITY_TAGGED.value,
        context={
            "reason": f"Tagged with: {', '.join(tags)}",
            "metadata": {
                "triggered_by": actor,
                "tags": tags
            }
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot tag from status '{doc.get('workflow_status')}'"
        )
    
    # Store the tags
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
            "quality_tags": tags
        }}
    )
    
    updated_doc["quality_tags"] = tags
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": f"Quality document tagged: {', '.join(tags)}"
    }


@router.post("/workflows/{doc_id}/export")
async def export_document(
    doc_id: str,
    export_destination: Optional[str] = None,
    user: Optional[str] = None
):
    """
    Mark a document as exported (generic version).
    Applicable to all document types.
    
    Triggers: on_exported event
    
    Note: During pilot mode, actual exports are blocked but status transitions
    are recorded for observation.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    
    doc_type = doc.get("doc_type", DocType.OTHER.value)
    actor = user or "system"
    
    # Pilot mode guard: Block actual export but allow workflow transition
    pilot_blocked = is_export_blocked(doc)
    
    updated_doc, history_entry, success = WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_EXPORTED.value,
        context={
            "reason": f"Exported to: {export_destination or 'default'}" + (" [PILOT: actual export blocked]" if pilot_blocked else ""),
            "metadata": {
                "triggered_by": actor,
                "export_destination": export_destination,
                "pilot_mode": pilot_blocked,
                "pilot_blocked_action": "external_export" if pilot_blocked else None
            }
        },
        actor=actor
    )
    
    if not success:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot export from status '{doc.get('workflow_status')}' for doc_type '{doc_type}'"
        )
    
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": updated_doc["workflow_status"],
            "workflow_history": updated_doc["workflow_history"],
            "workflow_status_updated_utc": updated_doc["workflow_status_updated_utc"],
            "exported_utc": datetime.now(timezone.utc).isoformat(),
            "export_destination": export_destination
        }}
    )
    
    return {
        "document": updated_doc,
        "workflow_transition": history_entry.to_dict(),
        "message": "Document exported"
    }

