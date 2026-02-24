"""
GPI Document Hub - Ingestion Router

Unified ingestion from all sources:
- Manual file upload
- Email attachments
- CSV/Excel file import
- Legacy system imports
"""

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query, BackgroundTasks
from typing import Optional
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid
import hashlib
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/ingest", tags=["ingestion"])

# Database and services - set by main app
db = None
classify_fn = None
workflow_fn = None

def set_dependencies(database, classify_func, workflow_func):
    global db, classify_fn, workflow_fn
    db = database
    classify_fn = classify_func
    workflow_fn = workflow_func


# ==================== MODELS ====================

class IngestResult(BaseModel):
    success: bool
    document_id: str
    doc_type: str
    status: str
    message: str


# ==================== CORE INGESTION ====================

async def ingest_document(
    file_content: bytes,
    file_name: str,
    source: str,
    source_metadata: dict = None,
    category_hint: str = None,
    skip_classification: bool = False
) -> dict:
    """
    Core ingestion function - all sources funnel through here.
    
    1. Create document record
    2. Classify (AI or deterministic)
    3. Route to workflow based on doc_type
    
    Returns the created document.
    """
    doc_id = str(uuid.uuid4())
    content_hash = hashlib.sha256(file_content).hexdigest()
    now = datetime.now(timezone.utc).isoformat()
    
    # Create base document
    doc = {
        "id": doc_id,
        "file_name": file_name,
        "content_hash": content_hash,
        "source": source,
        "source_metadata": source_metadata or {},
        "category": category_hint or "UNKNOWN",
        "doc_type": "OTHER",
        "status": "received",
        "workflow_status": "captured",
        "workflow_history": [{
            "status": "captured",
            "timestamp": now,
            "event": "document_received",
            "source": source
        }],
        "classification": {},
        "extracted_fields": {},
        "created_utc": now,
        "updated_utc": now
    }
    
    # Insert document
    await db.hub_documents.insert_one(doc)
    
    # Classify if not skipped
    if not skip_classification and classify_fn:
        try:
            classification = await classify_fn(file_content, file_name, category_hint)
            
            doc["doc_type"] = classification.get("doc_type", "OTHER")
            doc["category"] = classification.get("category", doc["category"])
            doc["classification"] = classification
            doc["extracted_fields"] = classification.get("extracted_fields", {})
            doc["status"] = "classified"
            doc["workflow_status"] = "classified"
            doc["workflow_history"].append({
                "status": "classified",
                "timestamp": datetime.now(timezone.utc).isoformat(),
                "event": "classification_complete",
                "doc_type": doc["doc_type"],
                "confidence": classification.get("confidence", 0)
            })
            
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "doc_type": doc["doc_type"],
                    "category": doc["category"],
                    "classification": doc["classification"],
                    "extracted_fields": doc["extracted_fields"],
                    "status": doc["status"],
                    "workflow_status": doc["workflow_status"],
                    "workflow_history": doc["workflow_history"],
                    "updated_utc": datetime.now(timezone.utc).isoformat()
                }}
            )
        except Exception as e:
            logger.error(f"Classification failed for {doc_id}: {e}")
            doc["classification"] = {"error": str(e)}
    
    # Route to workflow
    if workflow_fn:
        try:
            await workflow_fn(doc_id, doc["doc_type"])
        except Exception as e:
            logger.error(f"Workflow routing failed for {doc_id}: {e}")
    
    # Return without _id
    doc.pop("_id", None)
    return doc


# ==================== ENDPOINTS ====================

@router.post("/upload")
async def upload_document(
    background_tasks: BackgroundTasks,
    file: UploadFile = File(...),
    category: Optional[str] = Form(None),
    doc_type: Optional[str] = Form(None),
    notes: Optional[str] = Form(None)
):
    """Manual document upload."""
    content = await file.read()
    
    if len(content) > 50 * 1024 * 1024:  # 50MB limit
        raise HTTPException(status_code=400, detail="File too large (max 50MB)")
    
    doc = await ingest_document(
        file_content=content,
        file_name=file.filename,
        source="upload",
        source_metadata={"notes": notes} if notes else {},
        category_hint=category,
        skip_classification=bool(doc_type)  # Skip if type provided
    )
    
    # Override doc_type if explicitly provided
    if doc_type:
        await db.hub_documents.update_one(
            {"id": doc["id"]},
            {"$set": {
                "doc_type": doc_type,
                "status": "classified",
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }}
        )
        doc["doc_type"] = doc_type
        doc["status"] = "classified"
    
    return {
        "success": True,
        "document": doc,
        "message": f"Document uploaded and classified as {doc['doc_type']}"
    }


@router.post("/email")
async def ingest_from_email(
    file_content: bytes,
    file_name: str,
    email_id: str,
    mailbox: str,
    subject: str = None,
    sender: str = None,
    received_date: str = None,
    category: str = "AP"
):
    """Ingest document from email attachment."""
    doc = await ingest_document(
        file_content=file_content,
        file_name=file_name,
        source="email",
        source_metadata={
            "email_id": email_id,
            "mailbox": mailbox,
            "subject": subject,
            "sender": sender,
            "received_date": received_date
        },
        category_hint=category
    )
    
    return {"success": True, "document_id": doc["id"]}


@router.post("/batch")
async def ingest_batch(
    files: list[UploadFile] = File(...),
    source: str = Form("batch_upload"),
    category: Optional[str] = Form(None)
):
    """Batch ingest multiple documents."""
    results = []
    
    for file in files:
        try:
            content = await file.read()
            doc = await ingest_document(
                file_content=content,
                file_name=file.filename,
                source=source,
                category_hint=category
            )
            results.append({
                "file_name": file.filename,
                "success": True,
                "document_id": doc["id"],
                "doc_type": doc["doc_type"]
            })
        except Exception as e:
            results.append({
                "file_name": file.filename,
                "success": False,
                "error": str(e)
            })
    
    return {
        "total": len(files),
        "successful": sum(1 for r in results if r["success"]),
        "failed": sum(1 for r in results if not r["success"]),
        "results": results
    }


@router.get("/duplicate-check")
async def check_duplicate(
    content_hash: str = Query(...),
    file_name: Optional[str] = Query(None)
):
    """Check if document already exists."""
    query = {"content_hash": content_hash}
    
    existing = await db.hub_documents.find_one(query, {"id": 1, "file_name": 1, "created_utc": 1, "_id": 0})
    
    if existing:
        return {
            "is_duplicate": True,
            "existing_document": existing
        }
    
    return {"is_duplicate": False}
