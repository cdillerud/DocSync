"""
Document resolution and Business Central linking orchestration.

Extracted from services.document_handlers so the route-facing handler module
imports the authoritative implementation and request model directly.
"""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import HTTPException
from pydantic import BaseModel

from deps import get_db
from services.bc_link_service import (
    link_document_to_bc as _link_document_to_bc,
)
from services.sharepoint_service import (
    create_sharing_link as _create_sharing_link,
    upload_to_sharepoint as _upload_to_sharepoint,
)
from services.document_learning_hooks import (
    record_document_learning,
)

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _get_default_job_types():
    from models.document_types import DEFAULT_JOB_TYPES
    return DEFAULT_JOB_TYPES


class ResolveRequest(BaseModel):
    selected_vendor_id: Optional[str] = None
    selected_customer_id: Optional[str] = None
    selected_po_number: Optional[str] = None
    mark_no_po: bool = False
    notes: Optional[str] = None


async def resolve_and_link_document(doc_id: str, resolve: ResolveRequest):
    """Resolve a NeedsReview document and link to BC."""
    db = get_db()
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
            sp_result = await _upload_to_sharepoint(file_content, doc["file_name"], folder)
            share_link = await _create_sharing_link(sp_result["drive_id"], sp_result["item_id"])

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
            link_result = await _link_document_to_bc(
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

    await record_document_learning(
        db,
        doc_id,
        "link",
    )

    return {
        "success": link_success,
        "document": updated_doc,
        "message": "Document linked to BC" if link_success else f"Document stored in SharePoint. BC linking failed: {link_error}",
    }
