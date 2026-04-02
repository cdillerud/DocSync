"""
GPI Document Hub — Feedback Loop Health API

View-only endpoints that surface how much the system is learning
from user corrections. Reads from feedback_events, vendor_aliases,
classification_feedback, and routing_feedback collections.
"""

from fastapi import APIRouter
from deps import get_db
from services.feedback_loop_service import get_feedback_stats, replay_unapplied_events
from datetime import datetime, timezone, timedelta

router = APIRouter(prefix="/feedback-loop", tags=["feedback-loop"])


@router.get("/health")
async def feedback_loop_health():
    """
    Aggregated feedback loop health metrics.
    Returns totals, per-type breakdown, learning signal counts,
    recent events, and a daily activity timeline.
    """
    db = get_db()

    # Core stats from the service
    stats = await get_feedback_stats(db)

    # Recent events (last 20)
    recent_cursor = db.feedback_events.find(
        {},
        {"_id": 0, "event_type": 1, "vendor_id": 1, "document_id": 1,
         "source": 1, "created_at": 1, "applied": 1},
    ).sort("created_at", -1).limit(20)
    recent_events = await recent_cursor.to_list(20)

    # Daily activity (last 30 days)
    cutoff = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    daily_pipeline = [
        {"$match": {"created_at": {"$gte": cutoff}}},
        {"$addFields": {"day": {"$substr": ["$created_at", 0, 10]}}},
        {"$group": {"_id": "$day", "count": {"$sum": 1}}},
        {"$sort": {"_id": 1}},
    ]
    daily_activity = []
    async for doc in db.feedback_events.aggregate(daily_pipeline):
        daily_activity.append({"date": doc["_id"], "count": doc["count"]})

    # Top corrected vendors (by feedback event count)
    vendor_pipeline = [
        {"$match": {"vendor_id": {"$ne": ""}}},
        {"$group": {"_id": "$vendor_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    top_vendors = []
    async for doc in db.feedback_events.aggregate(vendor_pipeline):
        top_vendors.append({"vendor_id": doc["_id"], "event_count": doc["count"]})

    return {
        **stats,
        "recent_events": recent_events,
        "daily_activity": daily_activity,
        "top_corrected_vendors": top_vendors,
    }


@router.post("/replay")
async def replay_feedback():
    """
    Retroactively apply all unapplied feedback events.
    Use this after fixing handlers or to catch up on missed events.
    """
    db = get_db()
    result = await replay_unapplied_events(db)
    return result
