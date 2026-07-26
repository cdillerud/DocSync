"""
GPI Document Hub - Documents Router

CRUD operations for hub_documents collection.
"""

from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form, BackgroundTasks, Depends
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import uuid
import hashlib
from motor.motor_asyncio import AsyncIOMotorDatabase

from dependencies import get_database

router = APIRouter(prefix="/documents", tags=["documents"])

# ==================== MODELS ====================

class DocumentUpdate(BaseModel):
    status: Optional[str] = None
    extracted_vendor: Optional[str] = None
    extracted_invoice_number: Optional[str] = None
    extracted_amount: Optional[str] = None
    extracted_po_number: Optional[str] = None
    notes: Optional[str] = None


# ==================== ENDPOINTS ====================

@router.get("")
async def list_documents(
    skip: int = Query(0),
    limit: int = Query(50),
    status: Optional[str] = Query(None),
    category: Optional[str] = Query(None),
    doc_type: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    search: Optional[str] = Query(None),
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    """List documents with filters."""
    query = {}
    
    if status:
        query["status"] = status
    if category:
        query["category"] = category
    if doc_type:
        query["doc_type"] = doc_type
    if source:
        query["source"] = source
    if search:
        query["$or"] = [
            {"file_name": {"$regex": search, "$options": "i"}},
            {"extracted_vendor": {"$regex": search, "$options": "i"}},
            {"extracted_invoice_number": {"$regex": search, "$options": "i"}}
        ]
    
    total = await database.hub_documents.count_documents(query)
    docs = await database.hub_documents.find(
        query, {"_id": 0}
    ).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"documents": docs, "total": total, "skip": skip, "limit": limit}


@router.get("/{doc_id}")
async def get_document(doc_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    """Get a single document by ID."""
    doc = await database.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    return doc


@router.put("/{doc_id}")
async def update_document(doc_id: str, update: DocumentUpdate,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    """Update document fields."""
    update_data = {k: v for k, v in update.model_dump().items() if v is not None}
    update_data["updated_utc"] = datetime.now(timezone.utc).isoformat()
    
    result = await database.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc = await database.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return doc


@router.delete("/{doc_id}")
async def delete_document(doc_id: str,
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    """Delete a document."""
    doc = await database.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    await database.hub_documents.delete_one({"id": doc_id})
    return {"message": "Document deleted", "id": doc_id}


@router.get("/stats/summary")
async def get_document_stats(
    database: AsyncIOMotorDatabase = Depends(get_database),
):
    """Get document statistics."""
    pipeline = [
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "by_status": {"$push": "$status"},
            "by_type": {"$push": "$doc_type"},
            "by_source": {"$push": "$source"}
        }}
    ]
    
    result = await database.hub_documents.aggregate(pipeline).to_list(1)
    
    if not result:
        return {"total": 0, "by_status": {}, "by_type": {}, "by_source": {}}
    
    data = result[0]
    
    # Count occurrences
    def count_items(items):
        counts = {}
        for item in items:
            if item:
                counts[item] = counts.get(item, 0) + 1
        return counts
    
    return {
        "total": data.get("total", 0),
        "by_status": count_items(data.get("by_status", [])),
        "by_type": count_items(data.get("by_type", [])),
        "by_source": count_items(data.get("by_source", []))
    }
