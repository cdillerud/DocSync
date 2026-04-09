"""
GPI Document Hub - Readiness Router

Endpoints:
  GET  /api/readiness/metrics           - Readiness analytics
  GET  /api/readiness/queue             - Filterable readiness queue
  POST /api/readiness/evaluate/{id}     - Evaluate single document
  POST /api/readiness/batch             - Batch evaluate documents
  POST /api/readiness/reevaluate-all    - Re-evaluate ALL documents
  POST /api/readiness/sync-status       - Force cleanup Inbox (7-rule engine)
  GET  /api/readiness/inbox-diagnostic  - Preview what cleanup would do
  GET  /api/readiness/automation-rate   - Automation rate dashboard
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
    Aggressive force-cleanup: Directly moves documents OUT of the Inbox queue
    by setting terminal statuses or auto_cleared flags. Uses simple rules:

    Rule 1: Has bc_purchase_invoice_no → Completed (already posted to BC)
    Rule 2: draft_review_status == approved → Completed
    Rule 3: auto_draft_created == true → Completed (draft exists in BC)
    Rule 4: readiness.status is ready + no blockers → auto_cleared + processed
    Rule 5: Remaining non-terminal docs with vendor resolved → auto_cleared
    """
    from deps import get_db
    from datetime import datetime, timezone
    import logging

    logger = logging.getLogger("force_cleanup")
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Terminal statuses that already remove docs from the queue view
    TERMINAL = ["Completed", "Posted", "Archived", "completed", "posted",
                "archived", "FileMissing", "batch_parent"]
    DONE_WF = ["completed", "validation_passed", "processed",
               "ready_for_approval", "exported", "file_missing"]

    # Base conditions (used with $and to avoid $or key collisions)
    not_dup = {"is_duplicate": {"$ne": True}}
    not_terminal = {"status": {"$nin": TERMINAL}}
    not_cleared = {"$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}]}

    def base_and(*extra):
        """Build a query with base stuck conditions + extra filters using $and."""
        return {"$and": [not_dup, not_terminal, not_cleared, *extra]}

    def completed_update(rule):
        return {"$set": {
            "status": "Completed",
            "workflow_status": "completed",
            "auto_cleared": True,
            "automation_decision": "auto_process",
            "force_cleanup_rule": rule,
            "force_cleanup_at": now,
        }}

    results = {}

    # ── Rule 1: Has BC Purchase Invoice Number → mark Completed ──
    r1 = await db.hub_documents.update_many(
        base_and({"bc_purchase_invoice_no": {"$exists": True, "$nin": [None, ""]}}),
        completed_update("has_bc_pi"),
    )
    results["rule1_has_bc_pi"] = r1.modified_count
    logger.info("[ForceCleanup] Rule 1 (has BC PI): %d docs → Completed", r1.modified_count)

    # ── Rule 2: Draft approved → mark Completed ──
    r2 = await db.hub_documents.update_many(
        base_and({"draft_review_status": "approved"}),
        completed_update("draft_approved"),
    )
    results["rule2_draft_approved"] = r2.modified_count
    logger.info("[ForceCleanup] Rule 2 (draft approved): %d docs → Completed", r2.modified_count)

    # ── Rule 3: Auto-draft created in BC → mark Completed ──
    r3 = await db.hub_documents.update_many(
        base_and({"auto_draft_created": True}),
        completed_update("auto_draft_created"),
    )
    results["rule3_auto_draft_created"] = r3.modified_count
    logger.info("[ForceCleanup] Rule 3 (auto-draft created): %d docs → Completed", r3.modified_count)

    # ── Rule 4: Readiness says ready + no blocking reasons → Completed ──
    r4 = await db.hub_documents.update_many(
        base_and(
            {"readiness.status": {"$in": ["ready_auto_draft", "ready_auto_link", "ready"]}},
            {"$or": [
                {"readiness.blocking_reasons": {"$size": 0}},
                {"readiness.blocking_reasons": {"$exists": False}},
            ]},
        ),
        completed_update("readiness_ready_no_blockers"),
    )
    results["rule4_readiness_ready"] = r4.modified_count
    logger.info("[ForceCleanup] Rule 4 (readiness ready): %d docs → Completed", r4.modified_count)

    # ── Rule 5: Vendor resolved + fields present → Completed ──
    r5 = await db.hub_documents.update_many(
        base_and(
            {"readiness.signals.vendor_resolved": True},
            {"readiness.signals.required_fields_complete": True},
            {"readiness.signals.duplicate_risk": {"$ne": True}},
            {"readiness.signals.policy_blocked": {"$ne": True}},
        ),
        completed_update("vendor_resolved_fields_complete"),
    )
    results["rule5_vendor_resolved"] = r5.modified_count
    logger.info("[ForceCleanup] Rule 5 (vendor+fields): %d docs → Completed", r5.modified_count)

    # ── Rule 6: ReadyForPost status (from old sync) → mark Completed ──
    r6 = await db.hub_documents.update_many(
        {"$and": [not_dup, {"status": "ReadyForPost"}, not_cleared]},
        completed_update("readyforpost_to_completed"),
    )
    results["rule6_readyforpost"] = r6.modified_count
    logger.info("[ForceCleanup] Rule 6 (ReadyForPost→Completed): %d docs", r6.modified_count)

    # ── Rule 7: Readiness says ready (even with blockers) → Completed ──
    # Catch-all for docs the readiness engine marked as ready but other rules missed
    r7 = await db.hub_documents.update_many(
        base_and({"readiness.status": {"$in": ["ready_auto_draft", "ready_auto_link", "ready"]}}),
        completed_update("readiness_ready_catchall"),
    )
    results["rule7_readiness_catchall"] = r7.modified_count
    logger.info("[ForceCleanup] Rule 7 (readiness ready catchall): %d docs", r7.modified_count)

    # ── Count remaining stuck docs ──
    remaining = await db.hub_documents.count_documents({
        "$and": [
            {"is_duplicate": {"$ne": True}},
            {"$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}]},
            {"status": {"$nin": TERMINAL}},
            {"$or": [
                {"workflow_status": {"$nin": DONE_WF}},
                {"workflow_status": {"$exists": False}},
            ]},
        ]
    })

    total_fixed = sum(results.values())
    results["total_fixed"] = total_fixed
    results["remaining_in_inbox"] = remaining
    results["message"] = (
        f"Force cleanup complete: {total_fixed} documents moved out of Inbox. "
        f"{remaining} documents still need manual attention."
    )

    logger.info(
        "[ForceCleanup] DONE — total fixed: %d, remaining in inbox: %d",
        total_fixed, remaining,
    )
    return results



@router.get("/inbox-diagnostic")
async def inbox_diagnostic():
    """
    Shows exactly why documents are stuck in the Inbox and what force-cleanup
    would do for each category. Run this BEFORE sync-status to preview.
    """
    from deps import get_db
    db = get_db()

    TERMINAL = ["Completed", "Posted", "Archived", "completed", "posted",
                "archived", "FileMissing", "batch_parent"]
    DONE_WF = ["completed", "validation_passed", "processed",
               "ready_for_approval", "exported", "file_missing"]

    # Count all docs in the inbox view
    stuck_filter = {
        "$and": [
            {"is_duplicate": {"$ne": True}},
            {"$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}]},
            {"status": {"$nin": TERMINAL}},
            {"$or": [
                {"workflow_status": {"$nin": DONE_WF}},
                {"workflow_status": {"$exists": False}},
            ]},
        ]
    }
    total_stuck = await db.hub_documents.count_documents(stuck_filter)

    # Break down by status + readiness
    breakdown_pipe = [
        {"$match": stuck_filter},
        {"$group": {
            "_id": {
                "status": "$status",
                "readiness": "$readiness.status",
                "has_bc_pi": {"$cond": [
                    {"$and": [
                        {"$ifNull": ["$bc_purchase_invoice_no", False]},
                        {"$ne": ["$bc_purchase_invoice_no", ""]},
                    ]}, True, False
                ]},
                "has_draft": {"$ifNull": ["$auto_draft_created", False]},
                "draft_approved": {"$eq": ["$draft_review_status", "approved"]},
                "vendor_resolved": {"$ifNull": ["$readiness.signals.vendor_resolved", False]},
            },
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
    ]
    breakdown = await db.hub_documents.aggregate(breakdown_pipe).to_list(50)

    # Classify each group by which cleanup rule would catch it
    categories = []
    for b in breakdown:
        k = b["_id"]
        rule = "no_rule_yet"
        if k.get("has_bc_pi"):
            rule = "Rule 1: Has BC PI → Completed"
        elif k.get("draft_approved"):
            rule = "Rule 2: Draft approved → Completed"
        elif k.get("has_draft"):
            rule = "Rule 3: Auto-draft created → Completed"
        elif k.get("readiness") in ("ready_auto_draft", "ready_auto_link", "ready"):
            rule = "Rule 4: Readiness ready → Completed"
        elif k.get("vendor_resolved"):
            rule = "Rule 5: Vendor resolved + fields → Completed"
        else:
            rule = "Needs manual review"

        categories.append({
            "status": k.get("status"),
            "readiness_status": k.get("readiness"),
            "has_bc_pi": k.get("has_bc_pi"),
            "has_draft": k.get("has_draft"),
            "draft_approved": k.get("draft_approved"),
            "vendor_resolved": k.get("vendor_resolved"),
            "count": b["count"],
            "cleanup_rule": rule,
        })

    # Estimate cleanup impact
    would_fix = sum(c["count"] for c in categories if "Needs manual" not in c["cleanup_rule"])
    would_remain = sum(c["count"] for c in categories if "Needs manual" in c["cleanup_rule"])

    return {
        "total_in_inbox": total_stuck,
        "would_fix": would_fix,
        "would_remain_after_cleanup": would_remain,
        "breakdown": categories,
        "action": "POST /api/readiness/sync-status to execute cleanup",
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