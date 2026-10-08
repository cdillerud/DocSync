"""
Document retry orchestration.

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


async def retry_document(doc_id: str):
    db = get_db()

    from services.square9_workflow import (
        should_retry, increment_retry, DEFAULT_WORKFLOW_CONFIG,
        determine_square9_stage,
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

    doc = increment_retry(doc)

    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "retry_count": doc["retry_count"],
        "last_retry_utc": doc["last_retry_utc"],
        "retry_history": doc.get("retry_history", []),
        "status": "Retrying",
        "last_error": None,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }})

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found for retry")

    file_content = file_path.read_bytes()

    workflow_id, final_status = await _run_upload_and_link_workflow(
        doc_id, file_content, doc["file_name"],
        doc.get("document_type", "Other"),
        doc.get("bc_record_id"), doc.get("bc_document_no"),
    )

    new_stage = determine_square9_stage(final_status, doc.get("doc_type"))
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "square9_stage": new_stage,
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }})

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "success": True,
        "document": updated_doc,
        "workflow_id": workflow_id,
        "retry_count": doc["retry_count"],
    }
