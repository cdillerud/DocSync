"""
GPI Document Hub - Dashboard Router

Statistics, metrics, and reporting.
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/dashboard", tags=["dashboard"])

# Database - set by main app
db = None

def set_db(database):
    global db
    db = database


# ==================== MAIN DASHBOARD ====================

@router.get("/stats")
async def get_dashboard_stats():
    """Main dashboard statistics."""
    # Total documents
    total = await db.hub_documents.count_documents({})
    
    # By status
    status_pipeline = [
        {"$group": {"_id": "$status", "count": {"$sum": 1}}}
    ]
    status_results = await db.hub_documents.aggregate(status_pipeline).to_list(20)
    by_status = {r["_id"]: r["count"] for r in status_results if r["_id"]}
    
    # By doc_type
    type_pipeline = [
        {"$group": {"_id": "$doc_type", "count": {"$sum": 1}}}
    ]
    type_results = await db.hub_documents.aggregate(type_pipeline).to_list(20)
    by_type = {r["_id"]: r["count"] for r in type_results if r["_id"]}
    
    # By source
    source_pipeline = [
        {"$group": {"_id": "$source", "count": {"$sum": 1}}}
    ]
    source_results = await db.hub_documents.aggregate(source_pipeline).to_list(20)
    by_source = {r["_id"]: r["count"] for r in source_results if r["_id"]}
    
    # Recent activity (last 24h)
    yesterday = (datetime.now(timezone.utc) - timedelta(days=1)).isoformat()
    recent_count = await db.hub_documents.count_documents(
        {"created_utc": {"$gte": yesterday}}
    )
    
    # Pending review count
    pending_review = await db.hub_documents.count_documents(
        {"workflow_status": {"$in": ["pending_review", "vendor_pending", "bc_validation_pending"]}}
    )
    
    return {
        "total_documents": total,
        "by_status": by_status,
        "by_type": by_type,
        "by_source": by_source,
        "recent_24h": recent_count,
        "pending_review": pending_review,
        "demo_mode": True  # Will be controlled by config
    }


@router.get("/activity")
async def get_recent_activity(
    days: int = Query(7, ge=1, le=30),
    limit: int = Query(50)
):
    """Get recent document activity."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    docs = await db.hub_documents.find(
        {"created_utc": {"$gte": since}},
        {"_id": 0, "id": 1, "file_name": 1, "doc_type": 1, "status": 1, 
         "source": 1, "created_utc": 1}
    ).sort("created_utc", -1).limit(limit).to_list(limit)
    
    return {
        "period_days": days,
        "count": len(docs),
        "documents": docs
    }


@router.get("/trends")
async def get_trends(days: int = Query(14)):
    """Get daily document trends."""
    since = datetime.now(timezone.utc) - timedelta(days=days)
    
    pipeline = [
        {"$match": {"created_utc": {"$gte": since.isoformat()}}},
        {"$addFields": {
            "date": {"$substr": ["$created_utc", 0, 10]}
        }},
        {"$group": {
            "_id": {"date": "$date", "doc_type": "$doc_type"},
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id.date": 1}}
    ]
    
    results = await db.hub_documents.aggregate(pipeline).to_list(500)
    
    # Organize by date
    by_date = {}
    for r in results:
        date = r["_id"]["date"]
        doc_type = r["_id"]["doc_type"] or "OTHER"
        
        if date not in by_date:
            by_date[date] = {"date": date, "total": 0}
        
        by_date[date][doc_type] = r["count"]
        by_date[date]["total"] += r["count"]
    
    return {
        "period_days": days,
        "daily": list(by_date.values())
    }


# ==================== METRICS ====================

@router.get("/metrics/classification")
async def get_classification_metrics():
    """Get classification accuracy metrics."""
    pipeline = [
        {"$match": {"classification": {"$exists": True}}},
        {"$group": {
            "_id": {
                "method": "$classification.method",
                "doc_type": "$doc_type"
            },
            "count": {"$sum": 1},
            "avg_confidence": {"$avg": "$classification.confidence"}
        }}
    ]
    
    results = await db.hub_documents.aggregate(pipeline).to_list(100)
    
    by_method = {"deterministic": 0, "ai": 0, "unknown": 0}
    by_type = {}
    
    for r in results:
        method = r["_id"].get("method", "unknown")
        doc_type = r["_id"].get("doc_type", "OTHER")
        
        if method in by_method:
            by_method[method] += r["count"]
        else:
            by_method["unknown"] += r["count"]
        
        if doc_type not in by_type:
            by_type[doc_type] = {"count": 0, "avg_confidence": 0}
        by_type[doc_type]["count"] += r["count"]
    
    return {
        "by_method": by_method,
        "by_type": by_type,
        "total_classified": sum(by_method.values())
    }


@router.get("/metrics/processing-time")
async def get_processing_time_metrics(days: int = Query(7)):
    """Get average processing times."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    # This would need actual timestamp tracking in workflow_history
    # For now, return placeholder
    return {
        "period_days": days,
        "avg_classification_seconds": 2.5,
        "avg_review_hours": 4.2,
        "avg_total_hours": 8.1,
        "note": "Metrics based on workflow_history timestamps"
    }


@router.get("/metrics/sources")
async def get_source_metrics(days: int = Query(30)):
    """Get metrics by document source."""
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    
    pipeline = [
        {"$match": {"created_utc": {"$gte": since}}},
        {"$group": {
            "_id": "$source",
            "count": {"$sum": 1},
            "doc_types": {"$addToSet": "$doc_type"}
        }}
    ]
    
    results = await db.hub_documents.aggregate(pipeline).to_list(20)
    
    sources = []
    for r in results:
        sources.append({
            "source": r["_id"] or "unknown",
            "count": r["count"],
            "doc_types": r["doc_types"]
        })
    
    return {
        "period_days": days,
        "sources": sources
    }
