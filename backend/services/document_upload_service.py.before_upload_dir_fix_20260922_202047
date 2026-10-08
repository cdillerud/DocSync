"""
Manual document upload orchestration.

Extracted from services.document_handlers so the route-facing handler module
imports the authoritative implementation directly.
"""

import hashlib
import logging
import os
import uuid
from datetime import datetime, timezone
from pathlib import Path

from fastapi import File, Form, UploadFile

from deps import get_db
from services.document_orchestration_service import (
    run_upload_and_link_workflow as _run_upload_and_link_workflow,
)

logger = logging.getLogger(__name__)

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _get_workflow_enums():
    from workflows.core.engine import (
        DocType,
        SourceSystem,
        CaptureChannel,
        WorkflowStatus,
        WorkflowEvent,
        DocumentClassifier,
    )
    return (
        DocType,
        SourceSystem,
        CaptureChannel,
        WorkflowStatus,
        WorkflowEvent,
        DocumentClassifier,
    )


async def upload_document(
    file: UploadFile = File(...),
    document_type: str = Form("Other"),
    bc_record_id: str = Form(None),
    bc_document_no: str = Form(None),
    bc_company_id: str = Form(None),
    source: str = Form("manual_upload"),
):
    db = get_db()
    DocType, SourceSystem, CaptureChannel, WorkflowStatus, WorkflowEvent, DocumentClassifier = _get_workflow_enums()

    file_content = await file.read()
    sha256_hash = hashlib.sha256(file_content).hexdigest()

    # ---- Content-hash dedup gate ----
    existing_by_hash = await db.hub_documents.find_one(
        {"sha256_hash": sha256_hash, "is_duplicate": {"$ne": True}},
        {"_id": 0, "id": 1, "file_name": 1}
    )
    if existing_by_hash:
        return {
            "document": existing_by_hash,
            "skipped_duplicate": True,
            "message": f"Duplicate of {existing_by_hash['id']} by content hash",
        }

    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    correlation_id = str(uuid.uuid4())

    file_path = UPLOAD_DIR / doc_id
    file_path.write_bytes(file_content)

    doc_type_value = DocumentClassifier.classify_from_ai_result(document_type or "").value if document_type else DocType.OTHER.value

    from services.pilot_config import PILOT_MODE_ENABLED, get_pilot_capture_channel, get_pilot_metadata
    base_capture_channel = CaptureChannel.UPLOAD.value
    capture_channel = get_pilot_capture_channel(base_capture_channel) if PILOT_MODE_ENABLED else base_capture_channel

    from services.square9_workflow import initialize_retry_state

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
            "metadata": {"source": source, "doc_type": doc_type_value},
        }],
        "workflow_status_updated_utc": now,
        **initialize_retry_state({}),
        "status": "Received", "created_utc": now, "updated_utc": now, "last_error": None,
        "validation_state": "pending",
        "workflow_state": "received",
        "automation_state": "manual",
        **get_pilot_metadata(),
    }
    await db.hub_documents.insert_one(doc)

    from services.event_service import get_event_service, emit_document_received
    event_service = get_event_service()
    if event_service:
        await emit_document_received(
            event_service, doc_id, source,
            file.filename, file.content_type or "application/octet-stream",
            len(file_content), correlation_id,
        )

    workflow_id, final_status = await _run_upload_and_link_workflow(
        doc_id, file_content, file.filename, document_type, bc_record_id, bc_document_no,
    )

    from services.derived_state_service import get_derived_state_service
    derived_state_service = get_derived_state_service()
    if derived_state_service:
        await derived_state_service.update_document_derived_state(doc_id)

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "workflow_id": workflow_id}
