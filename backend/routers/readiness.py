"""
GPI Document Hub - Readiness Router

Endpoints:
  GET /api/readiness/metrics       - Readiness analytics
  GET /api/readiness/queue         - Filterable readiness queue
  POST /api/readiness/evaluate/{id} - Evaluate single document
  POST /api/readiness/batch        - Batch evaluate documents
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

router = APIRouter(prefix="/readiness", tags=["Readiness"])


@router.get("/metrics")
async def get_readiness_metrics():
    """Get readiness analytics: counts by status/action, top reasons, trends."""
    from services.document_readiness_service import get_readiness_metrics as _get
    return await _get()


@router.get("/queue")
async def get_readiness_queue(
    status: Optional[str] = Query(None, description="Filter: ready_auto_draft|ready_auto_link|needs_review|blocked|ambiguous"),
    action: Optional[str] = Query(None, description="Filter: auto_draft|auto_link|review|hold"),
    reason: Optional[str] = Query(None, description="Filter by blocking or warning reason"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    """Get documents filtered by readiness status for review queues."""
    from services.document_readiness_service import get_readiness_queue as _get
    return await _get(status=status, action=action, reason=reason, limit=limit, skip=skip)


@router.post("/evaluate/{doc_id}")
async def evaluate_document_readiness(doc_id: str):
    """Evaluate and persist readiness for a single document."""
    from services.document_readiness_service import evaluate_and_persist
    try:
        result = await evaluate_and_persist(doc_id)
        return {"success": True, "doc_id": doc_id, "readiness": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/batch")
async def batch_evaluate_readiness(limit: int = Query(200, ge=1, le=1000)):
    """Evaluate readiness for all documents that don't have it yet."""
    from services.document_readiness_service import batch_evaluate
    return await batch_evaluate(limit=limit)


@router.post("/reevaluate-all")
async def reevaluate_all_readiness(limit: int = Query(5000, ge=1, le=10000)):
    """
    Re-evaluate ALL documents — finds and fixes signal contradictions.
    Every correction feeds into the learning pipeline.
    Returns: status transitions, signal corrections, per-vendor breakdown.
    """
    from services.document_readiness_service import batch_reevaluate_all
    return await batch_reevaluate_all(limit=limit)



@router.post("/sync-status")
async def sync_readiness_to_status(limit: int = Query(5000, le=10000)):
    """
    One-time sync: For all docs where readiness says 'ready' but document status
    is still 'NeedsReview' — update status to 'ReadyForPost'.
    Also syncs auto-approved drafts to 'ReadyForPost'.
    This is the fix for the inbox not shrinking despite good readiness scores.
    """
    from deps import get_db
    from datetime import datetime, timezone

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # 1. Docs with ready readiness but stuck status
    ready_stuck = await db.hub_documents.update_many(
        {
            "readiness.status": {"$in": ["ready_auto_draft", "ready_auto_link", "ready"]},
            "status": {"$in": ["NeedsReview", "Captured", None, ""]},
            "is_duplicate": {"$ne": True},
        },
        {"$set": {
            "status": "ReadyForPost",
            "automation_decision": "auto_process",
            "status_synced_at": now,
        }},
    )

    # 2. Auto-approved drafts still showing as NeedsReview
    approved_stuck = await db.hub_documents.update_many(
        {
            "draft_review_status": "approved",
            "status": {"$in": ["NeedsReview", "Captured", None, ""]},
        },
        {"$set": {
            "status": "ReadyForPost",
            "automation_decision": "auto_process",
            "status_synced_at": now,
        }},
    )

    return {
        "readiness_synced": ready_stuck.modified_count,
        "approved_synced": approved_stuck.modified_count,
        "total_fixed": ready_stuck.modified_count + approved_stuck.modified_count,
        "message": f"Moved {ready_stuck.modified_count + approved_stuck.modified_count} documents from inbox to ReadyForPost",
    }


@router.get("/automation-rate")
async def get_automation_rate(days: int = Query(30, ge=1, le=90)):
    """
    Automation rate dashboard data:
    - Current automation rate %
    - Daily trend of auto-processed vs manual-review
    - Queue size breakdown
    - Top vendors still requiring manual review
    """
    from deps import get_db
    from datetime import datetime, timezone, timedelta

    db = get_db()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()

    # --- Current snapshot ---
    total = await db.hub_documents.count_documents({"is_duplicate": {"$ne": True}})
    auto_statuses = ["ready_auto_draft", "ready_auto_link"]
    manual_statuses = ["needs_review", "ambiguous"]

    auto_count = await db.hub_documents.count_documents({
        "is_duplicate": {"$ne": True},
        "$or": [
            {"readiness.status": {"$in": auto_statuses}},
            {"status": {"$in": ["Completed", "Posted"]}},
            {"bc_purchase_invoice_no": {"$exists": True, "$nin": [None, ""]}},
        ],
    })
    manual_count = await db.hub_documents.count_documents({
        "is_duplicate": {"$ne": True},
        "readiness.status": {"$in": manual_statuses},
    })
    blocked_count = await db.hub_documents.count_documents({
        "is_duplicate": {"$ne": True},
        "readiness.status": "blocked",
    })

    # Docs with BC PI = successfully auto-processed
    bc_posted = await db.hub_documents.count_documents({
        "bc_purchase_invoice_no": {"$exists": True, "$nin": [None, ""]},
    })

    automation_rate = round(auto_count / max(total, 1) * 100, 1)
    posting_rate = round(bc_posted / max(total, 1) * 100, 1)

    # --- Daily trend (bucketed by readiness.last_evaluated_at or updated_utc) ---
    daily_pipeline = [
        {"$match": {
            "is_duplicate": {"$ne": True},
            "readiness.last_evaluated_at": {"$exists": True, "$gte": cutoff},
        }},
        {"$addFields": {
            "eval_date": {"$substr": ["$readiness.last_evaluated_at", 0, 10]},
        }},
        {"$group": {
            "_id": "$eval_date",
            "total": {"$sum": 1},
            "auto_ready": {"$sum": {"$cond": [
                {"$in": ["$readiness.status", auto_statuses]}, 1, 0
            ]}},
            "manual_review": {"$sum": {"$cond": [
                {"$in": ["$readiness.status", manual_statuses]}, 1, 0
            ]}},
            "blocked": {"$sum": {"$cond": [
                {"$eq": ["$readiness.status", "blocked"]}, 1, 0
            ]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    daily_raw = await db.hub_documents.aggregate(daily_pipeline).to_list(days + 5)
    daily_trend = [
        {
            "date": r["_id"],
            "auto": r["auto_ready"],
            "manual": r["manual_review"],
            "blocked": r["blocked"],
            "total": r["total"],
            "rate": round(r["auto_ready"] / max(r["total"], 1) * 100, 1),
        }
        for r in daily_raw if r["_id"]
    ]

    # --- Top vendors requiring manual review ---
    vendor_manual_pipeline = [
        {"$match": {
            "is_duplicate": {"$ne": True},
            "readiness.status": {"$in": manual_statuses + ["blocked"]},
        }},
        {"$group": {
            "_id": {"$ifNull": ["$bc_vendor_number", {"$ifNull": ["$vendor_canonical", "Unknown"]}]},
            "count": {"$sum": 1},
            "top_reasons": {"$push": {"$arrayElemAt": [{"$ifNull": ["$readiness.blocking_reasons", ["$readiness.warning_reasons"]]}, 0]}},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    vendor_manual_raw = await db.hub_documents.aggregate(vendor_manual_pipeline).to_list(10)
    top_manual_vendors = []
    for v in vendor_manual_raw:
        vendor_id = v["_id"] or "Unknown"
        reasons = [r for r in (v.get("top_reasons") or []) if r]
        # Count most common reason
        reason_counts = {}
        for r in reasons:
            if isinstance(r, list):
                for sub_r in r:
                    reason_counts[sub_r] = reason_counts.get(sub_r, 0) + 1
            elif isinstance(r, str):
                reason_counts[r] = reason_counts.get(r, 0) + 1
        top_reason = max(reason_counts, key=reason_counts.get) if reason_counts else "unknown"
        top_manual_vendors.append({
            "vendor": vendor_id,
            "count": v["count"],
            "primary_reason": top_reason,
        })

    # --- Readiness distribution ---
    dist_pipeline = [
        {"$match": {"is_duplicate": {"$ne": True}, "readiness.status": {"$exists": True}}},
        {"$group": {"_id": "$readiness.status", "count": {"$sum": 1}}},
    ]
    dist_raw = await db.hub_documents.aggregate(dist_pipeline).to_list(10)
    distribution = {r["_id"]: r["count"] for r in dist_raw if r["_id"]}

    return {
        "automation_rate": automation_rate,
        "posting_rate": posting_rate,
        "total_documents": total,
        "auto_processed": auto_count,
        "manual_review": manual_count,
        "blocked": blocked_count,
        "bc_posted": bc_posted,
        "distribution": distribution,
        "daily_trend": daily_trend,
        "top_manual_vendors": top_manual_vendors,
        "period_days": days,
    }