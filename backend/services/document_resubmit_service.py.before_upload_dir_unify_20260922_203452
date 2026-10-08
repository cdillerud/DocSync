"""
Document resubmission orchestration.

Extracted from services.document_handlers so the route-facing handler module
imports the authoritative implementation directly.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from deps import get_db
from services.document_orchestration_service import (
    run_upload_and_link_workflow as _run_upload_and_link_workflow,
)

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def resubmit_document(doc_id: str):
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found")

    file_content = file_path.read_bytes()

    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "status": "Received",
        "last_error": None,
        "retry_count": 0,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }})

    workflow_id, final_status = await _run_upload_and_link_workflow(
        doc_id, file_content, doc["file_name"],
        doc.get("document_type", "Other"),
        doc.get("bc_record_id"), doc.get("bc_document_no"),
    )

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "workflow_id": workflow_id}
