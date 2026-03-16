"""GPI Document Hub - Auto-Clear Router"""

from fastapi import APIRouter, HTTPException, Body, Query
from deps import get_db
from datetime import datetime, timezone

router = APIRouter(prefix="/auto-clear", tags=["Auto-Clear"])


@router.get("/config")
async def get_auto_clear_configuration():
    """
    Get the current auto-clear configuration.
    Shows thresholds and rules for each document type.
    """
    config = get_auto_clear_config()
    return {
        "enabled": config.get("enabled", True),
        "default_threshold": config.get("default_confidence_threshold", 0.90),
        "thresholds": config.get("thresholds", {}),
        "require_sharepoint": config.get("require_sharepoint_upload", True),
        "require_bc_validation": config.get("require_bc_validation", True)
    }



@router.put("/config/threshold/{doc_type}")
async def update_auto_clear_threshold(doc_type: str, threshold: float = Query(..., ge=0.0, le=1.0)):
    """
    Update the confidence threshold for a specific document type.
    Threshold must be between 0.0 and 1.0 (e.g., 0.90 for 90%).
    """
    success = update_threshold(doc_type, threshold)
    return {
        "success": success,
        "doc_type": doc_type,
        "new_threshold": threshold,
        "message": f"Threshold for {doc_type} updated to {threshold:.1%}"
    }



@router.post("/evaluate/{doc_id}")
async def evaluate_document_auto_clear(doc_id: str):
    db = get_db()
    """
    Manually evaluate a document for auto-clear eligibility.
    Does not apply the result - just shows what would happen.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    decision, reason, details = evaluate_auto_clear(doc)
    
    return {
        "doc_id": doc_id,
        "file_name": doc.get("file_name"),
        "current_status": doc.get("status"),
        "already_cleared": doc.get("auto_cleared", False),
        "evaluation": {
            "decision": decision.value,
            "reason": reason,
            "would_clear": decision == AutoClearDecision.CLEARED,
            "checks": details.get("checks", []),
            "summary": get_auto_clear_summary(details)
        }
    }



@router.post("/apply/{doc_id}")
async def apply_auto_clear(doc_id: str, force: bool = Query(False)):
    db = get_db()
    """
    Apply auto-clear to a document.
    Use force=true to clear even if below threshold (manual clear).
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    if doc.get("auto_cleared") and not force:
        return {
            "success": False,
            "message": "Document already auto-cleared",
            "doc_id": doc_id
        }
    
    if force:
        # Manual clear - bypass evaluation
        decision = AutoClearDecision.CLEARED
        reason = "Manually cleared by user"
        details = {"manual_clear": True, "cleared_by": "user", "checks": []}
    else:
        decision, reason, details = evaluate_auto_clear(doc)
    
    if decision == AutoClearDecision.CLEARED or force:
        update = get_auto_clear_update(AutoClearDecision.CLEARED, details)
        await db.hub_documents.update_one({"id": doc_id}, {"$set": update})
        
        return {
            "success": True,
            "message": f"Document cleared: {reason}",
            "doc_id": doc_id,
            "new_status": "Completed"
        }
    else:
        return {
            "success": False,
            "message": f"Cannot auto-clear: {reason}",
            "doc_id": doc_id,
            "decision": decision.value,
            "checks": details.get("checks", [])
        }



@router.get("/stats")
async def get_auto_clear_stats():
    db = get_db()
    """
    Get statistics about auto-cleared documents.
    """
    total_docs = await db.hub_documents.count_documents({})
    auto_cleared = await db.hub_documents.count_documents({"auto_cleared": True})
    pending = await db.hub_documents.count_documents({
        "$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}],
        "status": {"$nin": ["Completed", "Posted", "Archived"]}
    })
    
    # Get counts by document type
    pipeline = [
        {"$match": {"auto_cleared": True}},
        {"$group": {"_id": "$document_type", "count": {"$sum": 1}}}
    ]
    by_type = await db.hub_documents.aggregate(pipeline).to_list(50)
    
    # Get counts by decision reason
    pipeline_reasons = [
        {"$match": {"auto_clear_decision": {"$exists": True}}},
        {"$group": {"_id": "$auto_clear_decision", "count": {"$sum": 1}}}
    ]
    by_reason = await db.hub_documents.aggregate(pipeline_reasons).to_list(20)
    
    return {
        "total_documents": total_docs,
        "auto_cleared": auto_cleared,
        "pending_review": pending,
        "clear_rate": f"{(auto_cleared/total_docs*100):.1f}%" if total_docs > 0 else "0%",
        "by_document_type": {item["_id"]: item["count"] for item in by_type if item["_id"]},
        "by_decision": {item["_id"]: item["count"] for item in by_reason if item["_id"]}
    }


# ==================== SPIRO VENDOR MATCHING ====================


# ==================== DOCUMENT ROUTING (Auto-Clear Gate) ====================


@router.post("/route/{doc_id}")
async def route_single_document(doc_id: str):
    """Evaluate and apply routing decision for a single document."""
    from services.document_routing_service import route_document
    try:
        result = await route_document(doc_id)
        return {"success": True, "doc_id": doc_id, **result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/route-batch")
async def route_batch_documents(limit: int = Query(100, ge=1, le=1000)):
    """Route all unrouted documents (backfill). Returns counts."""
    db = get_db()
    from services.document_routing_service import route_document

    cursor = db.hub_documents.find(
        {"$or": [
            {"routing_status": {"$exists": False}},
            {"routing_status": None},
        ]},
        {"_id": 0, "id": 1},
    ).limit(limit)
    docs = await cursor.to_list(length=limit)

    results = {"total": len(docs), "auto_process": 0, "review": 0, "blocked": 0, "errors": 0}
    for d in docs:
        try:
            r = await route_document(d["id"])
            status = r.get("routing_status", "unknown")
            if status in results:
                results[status] += 1
        except Exception:
            results["errors"] += 1
    return results


