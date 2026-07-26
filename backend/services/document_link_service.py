"""
Manual document-to-Business-Central linking orchestration.

Extracted from services.document_handlers so the route-facing handler module
imports the authoritative implementation directly.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from deps import get_db
from services.bc_link_service import (
    link_document_to_bc as _link_document_to_bc,
)

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


async def link_document(doc_id: str, bc_record_id: str):
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found")

    file_content = file_path.read_bytes()
    share_link = doc.get("sharepoint_share_link_url", "")
    bc_entity = doc.get("bc_entity", "salesOrders")

    link_result = await _link_document_to_bc(
        bc_record_id=bc_record_id,
        share_link=share_link,
        file_name=doc["file_name"],
        file_content=file_content,
        bc_entity=bc_entity,
    )

    if link_result.get("success"):
        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "bc_record_id": bc_record_id,
            "status": "LinkedToBC",
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }})

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "link_result": link_result}
