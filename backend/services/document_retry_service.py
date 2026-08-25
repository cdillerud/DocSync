"""Idempotent document retry orchestration for parity delivery."""

import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from deps import get_db

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def _retry_existing_sharepoint_item(db, doc: dict) -> dict:
    """Refresh resolution/metadata on an existing file without uploading it again."""
    from services.sharepoint_service import (
        _prepare_routing_document,
        build_square9_parity_metadata,
        write_sharepoint_parity_metadata,
    )

    routing_doc, _, po_result = await _prepare_routing_document(doc)
    previous_metadata = doc.get("sharepoint_parity_metadata") or {}
    metadata = build_square9_parity_metadata(
        routing_doc=routing_doc,
        po_result=po_result,
        original_file_name=(
            previous_metadata.get("GPI_OriginalFileName")
            or doc.get("file_name")
            or ""
        ),
        sharepoint_file_name=(
            previous_metadata.get("GPI_SharePointFileName")
            or doc.get("uploaded_file_name")
            or doc.get("file_name")
            or ""
        ),
        sharepoint_path=(
            previous_metadata.get("GPI_SharePointPath")
            or doc.get("sharepoint_folder_path")
            or ""
        ),
        sharepoint_url=(
            doc.get("sharepoint_web_url")
            or previous_metadata.get("GPI_SharePointURL")
            or ""
        ),
    )
    metadata_write = await write_sharepoint_parity_metadata(
        doc["sharepoint_drive_id"],
        doc["sharepoint_item_id"],
        metadata,
    )
    await db.hub_documents.update_one(
        {"id": doc["id"]},
        {"$set": {
            "sharepoint_parity_metadata": metadata,
            "sharepoint_metadata_written_at": datetime.now(timezone.utc).isoformat(),
            "delivery_status": metadata["GPI_Status"],
            "import_ready": bool(metadata["ImportReady"]),
            "sharepoint_metadata_error": None,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }},
    )
    return {
        "drive_id": doc["sharepoint_drive_id"],
        "item_id": doc["sharepoint_item_id"],
        "web_url": doc.get("sharepoint_web_url", ""),
        "parity_metadata": metadata,
        "metadata_write": metadata_write,
        "import_ready": bool(metadata["ImportReady"]),
        "delivery_status": metadata["GPI_Status"],
        "reused_existing_sharepoint_item": True,
    }


async def retry_document(doc_id: str):
    """Retry delivery without bypassing parity metadata or duplicating a prior upload."""
    db = get_db()
    from services.square9_workflow import (
        DEFAULT_WORKFLOW_CONFIG,
        increment_retry,
        should_retry,
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

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found for retry")

    doc = increment_retry(doc)
    retry_started = datetime.now(timezone.utc).isoformat()
    workflow_id = str(uuid.uuid4())
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "retry_count": doc["retry_count"],
            "last_retry_utc": doc["last_retry_utc"],
            "retry_history": doc.get("retry_history", []),
            "status": "Retrying",
            "last_error": None,
            "updated_utc": retry_started,
        }},
    )

    try:
        if doc.get("sharepoint_drive_id") and doc.get("sharepoint_item_id"):
            delivery = await _retry_existing_sharepoint_item(db, doc)
        else:
            from services.sharepoint_service import upload_to_sharepoint_with_routing

            delivery = await upload_to_sharepoint_with_routing(
                file_content=file_path.read_bytes(),
                file_name=doc.get("file_name") or f"{doc_id}.pdf",
                doc=doc,
            )
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "sharepoint_drive_id": delivery.get("drive_id"),
                    "sharepoint_item_id": delivery.get("item_id"),
                    "sharepoint_web_url": delivery.get("web_url"),
                    "sharepoint_folder_path": delivery.get("folder_path"),
                    "uploaded_file_name": delivery.get("uploaded_file_name"),
                    "delivery_status": delivery.get("delivery_status"),
                    "import_ready": bool(delivery.get("import_ready")),
                    "updated_utc": datetime.now(timezone.utc).isoformat(),
                }},
            )

        final_status = delivery.get("delivery_status") or "NotImportReady"
        document_status = "Delivered" if delivery.get("import_ready") else "NeedsReview"
        ended = datetime.now(timezone.utc).isoformat()
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "status": document_status,
                "last_error": None,
                "last_retry_delivery_status": final_status,
                "updated_utc": ended,
            }},
        )
        await db.hub_workflow_runs.insert_one({
            "id": workflow_id,
            "document_id": doc_id,
            "workflow_name": "parity_delivery_retry",
            "started_utc": retry_started,
            "ended_utc": ended,
            "status": "Completed" if delivery.get("import_ready") else "CompletedWithWarnings",
            "delivery_status": final_status,
            "import_ready": bool(delivery.get("import_ready")),
            "reused_existing_sharepoint_item": bool(
                delivery.get("reused_existing_sharepoint_item")
            ),
        })
    except Exception as error:
        ended = datetime.now(timezone.utc).isoformat()
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "status": "Exception",
                "last_error": str(error),
                "import_ready": False,
                "updated_utc": ended,
            }},
        )
        await db.hub_workflow_runs.insert_one({
            "id": workflow_id,
            "document_id": doc_id,
            "workflow_name": "parity_delivery_retry",
            "started_utc": retry_started,
            "ended_utc": ended,
            "status": "Failed",
            "error": str(error),
        })
        raise

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "success": True,
        "document": updated_doc,
        "workflow_id": workflow_id,
        "retry_count": doc["retry_count"],
        "delivery_status": final_status,
        "import_ready": bool(delivery.get("import_ready")),
        "reused_existing_sharepoint_item": bool(
            delivery.get("reused_existing_sharepoint_item")
        ),
    }
