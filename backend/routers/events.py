"""GPI Document Hub - Events Router"""

from fastapi import APIRouter, Query
from typing import Optional
from datetime import datetime, timezone, timedelta
from deps import get_db

router = APIRouter(prefix="/events", tags=["Events"])


@router.get("/types")
async def get_event_types():
    """Get all supported event types and their descriptions."""
    from services.event_service import EVENT_TYPES
    return {"event_types": EVENT_TYPES}


@router.get("/recent")
async def get_recent_events(
    limit: int = Query(50, le=200),
    event_type: Optional[str] = Query(None),
    status: Optional[str] = Query(None)
):
    """Get recent events across all documents."""
    db = get_db()
    query = {}
    if event_type:
        query["event_type"] = event_type
    if status:
        query["status"] = status

    cursor = db.workflow_events.find(query, {"_id": 0}).sort("timestamp", -1).limit(limit)
    events = await cursor.to_list(limit)
    return {"events": events, "count": len(events)}


@router.get("/stats")
async def get_event_stats(since_hours: int = Query(24, le=168)):
    """Get event statistics for the specified time period."""
    db = get_db()
    since = (datetime.now(timezone.utc) - timedelta(hours=since_hours)).isoformat()

    pipeline = [
        {"$match": {"timestamp": {"$gte": since}}},
        {"$group": {
            "_id": "$event_type",
            "count": {"$sum": 1},
            "completed": {"$sum": {"$cond": [{"$eq": ["$status", "completed"]}, 1, 0]}},
            "failed": {"$sum": {"$cond": [{"$eq": ["$status", "failed"]}, 1, 0]}},
            "warning": {"$sum": {"$cond": [{"$eq": ["$status", "warning"]}, 1, 0]}}
        }},
        {"$sort": {"count": -1}}
    ]
    results = await db.workflow_events.aggregate(pipeline).to_list(100)
    total_events = sum(r["count"] for r in results)
    total_completed = sum(r["completed"] for r in results)
    total_failed = sum(r["failed"] for r in results)

    return {
        "since_hours": since_hours,
        "total_events": total_events,
        "total_completed": total_completed,
        "total_failed": total_failed,
        "by_type": results
    }
