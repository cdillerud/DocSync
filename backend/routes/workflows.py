"""
GPI Document Hub - Workflows Router

Workflow state transitions and queue management.
"""

from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from typing import Optional, List
from datetime import datetime, timezone
from pydantic import BaseModel
import logging

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/workflows", tags=["workflows"])

# Database and workflow engine - set by main app
db = None
workflow_engine = None

def set_dependencies(database, engine):
    global db, workflow_engine
    db = database
    workflow_engine = engine


# ==================== MODELS ====================

class WorkflowAction(BaseModel):
    action: str
    data: Optional[dict] = None
    notes: Optional[str] = None


# ==================== QUEUE ENDPOINTS ====================

@router.get("/queue")
async def get_workflow_queue(
    doc_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None),
    skip: int = Query(0),
    limit: int = Query(50)
):
    """Get documents in workflow queues."""
    query = {}
    
    if doc_type:
        query["doc_type"] = doc_type
    if status:
        query["workflow_status"] = status
    
    # Exclude completed/archived by default
    if not status:
        query["workflow_status"] = {"$nin": ["archived", "exported", "completed"]}
    
    total = await db.hub_documents.count_documents(query)
    docs = await db.hub_documents.find(
        query,
        {"_id": 0, "id": 1, "file_name": 1, "doc_type": 1, "workflow_status": 1, 
         "extracted_fields": 1, "created_utc": 1, "updated_utc": 1}
    ).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)
    
    return {"documents": docs, "total": total}


@router.get("/queue/counts")
async def get_queue_counts():
    """Get counts by workflow status and doc_type."""
    pipeline = [
        {"$match": {"workflow_status": {"$nin": ["archived", "exported", "completed"]}}},
        {"$group": {
            "_id": {"doc_type": "$doc_type", "status": "$workflow_status"},
            "count": {"$sum": 1}
        }}
    ]
    
    results = await db.hub_documents.aggregate(pipeline).to_list(100)
    
    # Organize by doc_type
    by_type = {}
    for r in results:
        doc_type = r["_id"]["doc_type"] or "OTHER"
        status = r["_id"]["status"] or "unknown"
        
        if doc_type not in by_type:
            by_type[doc_type] = {}
        by_type[doc_type][status] = r["count"]
    
    # Calculate totals
    total_pending = sum(
        count for type_counts in by_type.values() 
        for count in type_counts.values()
    )
    
    return {
        "total_pending": total_pending,
        "by_type": by_type
    }


# ==================== DOCUMENT WORKFLOW ACTIONS ====================

@router.post("/{doc_id}/transition")
async def transition_document(doc_id: str, action: WorkflowAction):
    """
    Transition a document to a new workflow state.
    
    Common actions:
    - approve: Move to approved state
    - reject: Move to rejected state
    - request_review: Send for review
    - complete: Mark as complete
    - archive: Archive document
    """
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    now = datetime.now(timezone.utc).isoformat()
    current_status = doc.get("workflow_status", "captured")
    doc_type = doc.get("doc_type", "OTHER")
    
    # Define valid transitions
    transitions = {
        "approve": {
            "from": ["ready_for_approval", "pending_review", "extracted"],
            "to": "approved"
        },
        "reject": {
            "from": ["ready_for_approval", "pending_review"],
            "to": "rejected"
        },
        "request_review": {
            "from": ["classified", "extracted"],
            "to": "pending_review"
        },
        "complete": {
            "from": ["approved"],
            "to": "completed"
        },
        "archive": {
            "from": ["completed", "rejected", "approved"],
            "to": "archived"
        },
        "export": {
            "from": ["approved"],
            "to": "exported"
        },
        "ready_for_approval": {
            "from": ["extracted", "bc_validation_pending", "vendor_pending"],
            "to": "ready_for_approval"
        }
    }
    
    if action.action not in transitions:
        raise HTTPException(
            status_code=400, 
            detail=f"Unknown action: {action.action}. Valid actions: {list(transitions.keys())}"
        )
    
    transition = transitions[action.action]
    
    if current_status not in transition["from"]:
        raise HTTPException(
            status_code=400,
            detail=f"Cannot {action.action} from status '{current_status}'. Valid from: {transition['from']}"
        )
    
    new_status = transition["to"]
    
    # Update document
    history_entry = {
        "status": new_status,
        "timestamp": now,
        "event": action.action,
        "previous_status": current_status,
        "notes": action.notes,
        "data": action.data
    }
    
    update = {
        "$set": {
            "workflow_status": new_status,
            "status": new_status,  # Keep in sync
            "updated_utc": now
        },
        "$push": {
            "workflow_history": history_entry
        }
    }
    
    await db.hub_documents.update_one({"id": doc_id}, update)
    
    updated = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    
    return {
        "success": True,
        "document_id": doc_id,
        "previous_status": current_status,
        "new_status": new_status,
        "action": action.action
    }


@router.get("/{doc_id}/history")
async def get_workflow_history(doc_id: str):
    """Get workflow history for a document."""
    doc = await db.hub_documents.find_one(
        {"id": doc_id}, 
        {"_id": 0, "id": 1, "workflow_history": 1, "workflow_status": 1}
    )
    
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return {
        "document_id": doc_id,
        "current_status": doc.get("workflow_status"),
        "history": doc.get("workflow_history", [])
    }


# ==================== BULK ACTIONS ====================

@router.post("/bulk/approve")
async def bulk_approve(doc_ids: List[str], notes: Optional[str] = None):
    """Approve multiple documents at once."""
    results = []
    
    for doc_id in doc_ids:
        try:
            result = await transition_document(
                doc_id, 
                WorkflowAction(action="approve", notes=notes)
            )
            results.append({"doc_id": doc_id, "success": True})
        except HTTPException as e:
            results.append({"doc_id": doc_id, "success": False, "error": e.detail})
    
    return {
        "total": len(doc_ids),
        "successful": sum(1 for r in results if r["success"]),
        "results": results
    }


@router.post("/bulk/archive")
async def bulk_archive(doc_ids: List[str]):
    """Archive multiple documents."""
    results = []
    
    for doc_id in doc_ids:
        try:
            result = await transition_document(
                doc_id,
                WorkflowAction(action="archive")
            )
            results.append({"doc_id": doc_id, "success": True})
        except HTTPException as e:
            results.append({"doc_id": doc_id, "success": False, "error": e.detail})
    
    return {
        "total": len(doc_ids),
        "successful": sum(1 for r in results if r["success"]),
        "results": results
    }
