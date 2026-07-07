"""
Document CRUD + Square9 workflow-alignment endpoints.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 5). No logic changed - same
Mongo collections, same field names, same response shapes.
"""
from fastapi import APIRouter, UploadFile, File, Form, HTTPException, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel
from typing import Optional
from datetime import datetime, timezone
import hashlib
import uuid

from core.db import db
from core.paths import UPLOAD_DIR
from core.legacy_hub_helpers import (
    run_upload_and_link_workflow, get_bc_sales_orders, link_document_to_bc,
)
from services.workflow_engine import (
    WorkflowStatus, WorkflowEvent, DocType, SourceSystem, CaptureChannel,
    DocumentClassifier,
)
from services.square9_workflow import (
    Square9Stage, DEFAULT_WORKFLOW_CONFIG,
    initialize_retry_state, increment_retry, reset_retry_counter,
    determine_square9_stage, get_square9_stage_info,
    should_retry, get_workflow_summary,
)
from services import pilot_config

router = APIRouter(prefix="/api")


class DocumentUpdate(BaseModel):
    document_type: Optional[str] = None
    bc_record_type: Optional[str] = None
    bc_record_id: Optional[str] = None
    bc_document_no: Optional[str] = None


@router.post("/documents/upload")
async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form("Other"),
    bc_record_id: str = Form(None),
    bc_document_no: str = Form(None),
    bc_company_id: str = Form(None),
    source: str = Form("manual_upload")
):
    file_content = await file.read()
    sha256_hash = hashlib.sha256(file_content).hexdigest()
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    file_path = UPLOAD_DIR / doc_id
    file_path.write_bytes(file_content)

    doc_type_value = DocumentClassifier.classify_from_ai_result(document_type or "").value if document_type else DocType.OTHER.value

    base_capture_channel = CaptureChannel.UPLOAD.value
    capture_channel = pilot_config.get_pilot_capture_channel(base_capture_channel) if pilot_config.PILOT_MODE_ENABLED else base_capture_channel

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
            "metadata": {"source": source, "doc_type": doc_type_value}
        }],
        "workflow_status_updated_utc": now,
        **initialize_retry_state({}),
        "status": "Received", "created_utc": now, "updated_utc": now, "last_error": None,
        **pilot_config.get_pilot_metadata()
    }
    await db.hub_documents.insert_one(doc)

    workflow_id, final_status = await run_upload_and_link_workflow(
        doc_id, file_content, file.filename, document_type, bc_record_id, bc_document_no
    )
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "workflow_id": workflow_id}


@router.get("/documents")
async def list_documents(
    status: str = Query(None), document_type: str = Query(None),
    category: str = Query(None),
    search: str = Query(None), skip: int = Query(0), limit: int = Query(50)
):
    fq = {}
    if status:
        fq["status"] = status
    if document_type:
        fq["document_type"] = document_type
    if category:
        fq["category"] = category
    if search:
        fq["file_name"] = {"$regex": search, "$options": "i"}
    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    return {"documents": docs, "total": total}


@router.get("/documents/{doc_id}")
async def get_document(doc_id: str):
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    workflows = await db.hub_workflow_runs.find({"document_id": doc_id}, {"_id": 0}).sort("started_utc", -1).to_list(100)
    return {"document": doc, "workflows": workflows}


@router.put("/documents/{doc_id}")
async def update_document(doc_id: str, update: DocumentUpdate):
    update_data = {k: v for k, v in update.model_dump().items() if v is not None}
    update_data["updated_utc"] = datetime.now(timezone.utc).isoformat()
    result = await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return doc


@router.delete("/documents/{doc_id}")
async def delete_document(doc_id: str):
    """Delete a document, its workflows, and stored file."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.hub_documents.delete_one({"id": doc_id})
    await db.hub_workflow_runs.delete_many({"document_id": doc_id})
    file_path = UPLOAD_DIR / doc_id
    if file_path.exists():
        file_path.unlink()
    return {"message": "Document deleted", "id": doc_id}


@router.get("/documents/{doc_id}/file")
async def get_document_file(doc_id: str):
    """
    Serve the document file for preview/download.
    Returns the raw file with appropriate content type.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    content_type = doc.get("content_type", "application/octet-stream")
    filename = doc.get("file_name", f"{doc_id}.bin")

    return FileResponse(
        path=file_path,
        media_type=content_type,
        filename=filename,
        headers={
            "Content-Disposition": f'inline; filename="{filename}"'
        }
    )


# =============================================================================
# SQUARE9 WORKFLOW ENDPOINTS
# =============================================================================

@router.get("/documents/{doc_id}/square9-status")
async def get_square9_status(doc_id: str):
    """Get Square9-style workflow status for a document."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    summary = get_workflow_summary(doc)
    return {
        "document_id": doc_id,
        **summary,
        "retry_history": doc.get("retry_history", []),
    }


@router.post("/documents/{doc_id}/retry")
async def retry_document(doc_id: str, reason: str = "Manual retry"):
    """
    Retry a document's workflow processing.
    Increments retry counter and re-runs workflow if within limits.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    can_do_retry, retry_reason = should_retry(doc)
    if not can_do_retry:
        return {
            "success": False,
            "message": retry_reason,
            "document_id": doc_id,
            "retry_count": doc.get("retry_count", 0),
            "max_retries": doc.get("max_retries", DEFAULT_WORKFLOW_CONFIG["max_retry_attempts"]),
        }

    update_dict, escalated, message = increment_retry(doc, reason)
    update_dict["updated_utc"] = datetime.now(timezone.utc).isoformat()

    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})

    if escalated:
        return {
            "success": False,
            "escalated": True,
            "message": message,
            "document_id": doc_id,
            "retry_count": update_dict["retry_count"],
        }

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        return {
            "success": False,
            "message": "Stored file not found - cannot retry",
            "document_id": doc_id,
        }

    file_content = file_path.read_bytes()
    file_name = doc.get("file_name", f"{doc_id}.pdf")
    document_type = doc.get("document_type", "Invoice")
    bc_record_id = doc.get("bc_record_id")
    bc_document_no = doc.get("bc_document_no")

    workflow_id, final_status = await run_upload_and_link_workflow(
        doc_id, file_content, file_name, document_type, bc_record_id, bc_document_no
    )

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    new_stage = determine_square9_stage(updated_doc) if updated_doc else None

    if new_stage:
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {"square9_stage": new_stage}}
        )

    return {
        "success": True,
        "message": message,
        "document_id": doc_id,
        "workflow_id": workflow_id,
        "final_status": final_status,
        "retry_count": update_dict["retry_count"],
        "square9_stage": new_stage,
    }


@router.post("/documents/{doc_id}/reset-retries")
async def reset_document_retries(doc_id: str, reason: str = "Manual reset"):
    """Reset retry counter for a document (after manual intervention)."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    update_dict = reset_retry_counter(doc, reason)
    update_dict["updated_utc"] = datetime.now(timezone.utc).isoformat()

    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})

    return {
        "success": True,
        "message": f"Retry counter reset: {reason}",
        "document_id": doc_id,
        "retry_count": 0,
    }


@router.get("/square9/config")
async def get_square9_config():
    """Get Square9 workflow configuration."""
    return {
        "config": DEFAULT_WORKFLOW_CONFIG,
        "stages": [
            {"value": stage.value, **get_square9_stage_info(stage.value)}
            for stage in Square9Stage
        ],
    }


@router.get("/square9/stage-counts")
async def get_square9_stage_counts():
    """Get document counts by Square9 stage."""
    docs = await db.hub_documents.find({}, {"_id": 0, "id": 1, "workflow_status": 1, "validation_results": 1, "auto_escalated": 1, "square9_stage": 1}).to_list(10000)

    stage_counts = {}
    for doc in docs:
        stage = doc.get("square9_stage") or determine_square9_stage(doc)
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

    result = []
    for stage in Square9Stage:
        count = stage_counts.get(stage.value, 0)
        info = get_square9_stage_info(stage.value)
        result.append({
            "stage": stage.value,
            "count": count,
            **info,
        })

    return {
        "stages": result,
        "total_documents": len(docs),
    }


@router.post("/documents/{doc_id}/resubmit")
async def resubmit_document(doc_id: str):
    """Re-submit a failed document: re-run the full workflow using the stored file."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found on server. Please upload again via the Upload page.")
    file_content = file_path.read_bytes()
    now = datetime.now(timezone.utc).isoformat()

    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "status": "Received",
        "sharepoint_drive_id": None,
        "sharepoint_item_id": None,
        "sharepoint_web_url": None,
        "sharepoint_share_link_url": None,
        "last_error": None,
        "updated_utc": now,
    }})

    workflow_id, final_status = await run_upload_and_link_workflow(
        doc_id, file_content, doc["file_name"],
        doc.get("document_type", "Other"),
        doc.get("bc_record_id"),
        doc.get("bc_document_no")
    )

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "workflow_id": workflow_id}


@router.post("/documents/{doc_id}/link")
async def link_document(doc_id: str):
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not doc.get("sharepoint_share_link_url"):
        raise HTTPException(status_code=400, detail="Document has no SharePoint link yet")
    bc_record_id = doc.get("bc_record_id")
    bc_document_no = doc.get("bc_document_no")
    if not bc_record_id and not bc_document_no:
        raise HTTPException(status_code=400, detail="No BC record reference set on this document")

    file_path = UPLOAD_DIR / doc_id
    file_content = None
    if file_path.exists():
        file_content = file_path.read_bytes()

    doc_type = doc.get("document_type", "Other")
    job_type = doc.get("suggested_job_type", "")

    job_config = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
    if job_config:
        bc_entity = job_config.get("bc_entity", "salesOrders")
    else:
        doc_type_to_bc_entity = {
            "SalesOrder": "salesOrders",
            "SalesInvoice": "salesInvoices",
            "PurchaseInvoice": "purchaseInvoices",
            "PurchaseOrder": "purchaseOrders",
            "AP_Invoice": "purchaseInvoices"
        }
        bc_entity = doc_type_to_bc_entity.get(doc_type, doc_type_to_bc_entity.get(job_type, "salesOrders"))

    workflow_id = str(uuid.uuid4())
    correlation_id = str(uuid.uuid4())
    started = datetime.now(timezone.utc).isoformat()
    steps = []

    try:
        steps.append({"step": "validate_bc_record", "status": "running", "started": datetime.now(timezone.utc).isoformat()})
        orders = await get_bc_sales_orders(order_no=bc_document_no)
        if orders:
            steps[-1]["status"] = "completed"
            steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
            steps.append({"step": "link_to_bc", "status": "running", "started": datetime.now(timezone.utc).isoformat()})
            link_result = await link_document_to_bc(
                bc_record_id=bc_record_id or orders[0]["id"],
                share_link=doc["sharepoint_share_link_url"],
                file_name=doc["file_name"],
                file_content=file_content,
                bc_entity=bc_entity
            )
            if link_result.get("success"):
                steps[-1]["status"] = "completed"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["result"] = link_result
                await db.hub_documents.update_one({"id": doc_id}, {"$set": {"status": "LinkedToBC", "updated_utc": datetime.now(timezone.utc).isoformat(), "last_error": None}})
                wf_status = "Completed"
            else:
                steps[-1]["status"] = "failed"
                steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
                steps[-1]["error"] = link_result.get("error", "Unknown error")
                await db.hub_documents.update_one({"id": doc_id}, {"$set": {"status": "Exception", "last_error": link_result.get("error"), "updated_utc": datetime.now(timezone.utc).isoformat()}})
                wf_status = "Failed"
        else:
            steps[-1]["status"] = "failed"
            steps[-1]["ended"] = datetime.now(timezone.utc).isoformat()
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {"status": "Exception", "last_error": "BC record not found", "updated_utc": datetime.now(timezone.utc).isoformat()}})
            wf_status = "Failed"

        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "link_to_bc",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": wf_status, "steps": steps, "correlation_id": correlation_id,
            "error": None if wf_status == "Completed" else steps[-1].get("error", "BC record not found")
        }
        await db.hub_workflow_runs.insert_one(workflow)
    except Exception as e:
        steps.append({"step": "error", "status": "failed", "error": str(e)})
        workflow = {
            "id": workflow_id, "document_id": doc_id, "workflow_name": "link_to_bc",
            "started_utc": started, "ended_utc": datetime.now(timezone.utc).isoformat(),
            "status": "Failed", "steps": steps, "correlation_id": correlation_id, "error": str(e)
        }
        await db.hub_workflow_runs.insert_one(workflow)

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": doc, "workflow_id": workflow_id}
