"""
GPI Document Hub — Unified Governance Dashboard API

Single consolidated endpoint serving the Governance Dashboard with
cross-pipeline metrics: SO + AP learning, drift, hotspots, and
overall system health.

READ-ONLY: Never changes profiles, thresholds, or workflow.
"""

import logging
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

from fastapi import APIRouter, Query
from deps import get_db

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/governance", tags=["Governance"])


@router.get("/dashboard")
async def governance_dashboard():
    """Consolidated governance dashboard data — SO + AP + system health."""
    db = get_db()
    now = datetime.now(timezone.utc)
    thirty_days_ago = (now - timedelta(days=30)).isoformat()

    # ── SO Metrics ──
    so_pending = await db.so_learning_suggestions.count_documents({"status": "pending"})
    so_approved = await db.so_learning_suggestions.count_documents({"status": "approved"})
    so_applied = await db.so_learning_suggestions.count_documents({"status": "applied"})
    so_rejected = await db.so_learning_suggestions.count_documents({"status": "rejected"})

    so_fb_total = await db.so_reviewer_feedback.count_documents({})
    so_fb_correct = await db.so_reviewer_feedback.count_documents({"reviewer_assessment": "correct"})
    so_agreement_pct = round(so_fb_correct / max(so_fb_total, 1) * 100, 1)

    so_drift_audits = await db.so_learning_apply_audit.find(
        {"applied_at": {"$gte": thirty_days_ago}}, {"_id": 0, "customer_no": 1}
    ).to_list(500)
    so_recent_changes = len(so_drift_audits)
    so_customers_changed = len(set(a.get("customer_no", "") for a in so_drift_audits))

    # ── AP Metrics ──
    ap_pending = await db.ap_learning_suggestions.count_documents({"status": "pending"})
    ap_approved = await db.ap_learning_suggestions.count_documents({"status": "approved"})
    ap_applied = await db.ap_learning_suggestions.count_documents({"status": "applied"})
    ap_rejected = await db.ap_learning_suggestions.count_documents({"status": "rejected"})

    ap_fb_total = await db.ap_reviewer_feedback.count_documents({})
    ap_fb_correct = await db.ap_reviewer_feedback.count_documents({"reviewer_assessment": "correct"})
    ap_agreement_pct = round(ap_fb_correct / max(ap_fb_total, 1) * 100, 1)

    ap_drift_audits = await db.ap_learning_apply_audit.find(
        {"applied_at": {"$gte": thirty_days_ago}}, {"_id": 0, "vendor_no": 1}
    ).to_list(500)
    ap_recent_changes = len(ap_drift_audits)
    ap_vendors_changed = len(set(a.get("vendor_no", "") for a in ap_drift_audits))

    # ── Drift Risk Distribution (combined) ──
    so_drift = await _get_drift_distribution(db, "so")
    ap_drift = await _get_drift_distribution(db, "ap")

    # ── Top Hotspots ──
    so_hotspots = await _get_top_hotspots(db, "so", limit=5)
    ap_hotspots = await _get_top_hotspots(db, "ap", limit=5)

    # ── System Health ──
    seven_days_ago = (now - timedelta(days=7)).isoformat()
    total_docs = await db.hub_documents.count_documents({"is_duplicate": {"$ne": True}})
    pending_review = await db.hub_documents.count_documents({
        "status": "NeedsReview", "is_duplicate": {"$ne": True}
    })
    completed = await db.hub_documents.count_documents({
        "status": {"$in": ["Completed", "AutoCleared", "Archived"]},
        "is_duplicate": {"$ne": True}
    })
    posted_7d = await db.hub_documents.count_documents({
        "posted_to_bc": True,
        "posted_to_bc_at": {"$gte": seven_days_ago},
    })
    ready_to_post = await db.hub_documents.count_documents({
        "status": "ReadyForPost", "is_duplicate": {"$ne": True}
    })

    vendor_profiles = await db.vendor_invoice_profiles.count_documents({})
    customer_profiles = await db.customer_posting_profiles.count_documents({})

    return {
        "generated_at": now.isoformat(),
        "sales_orders": {
            "suggestions": {
                "pending": so_pending,
                "approved": so_approved,
                "applied": so_applied,
                "rejected": so_rejected,
                "total_actionable": so_pending + so_approved,
            },
            "feedback": {
                "total": so_fb_total,
                "agreement_pct": so_agreement_pct,
            },
            "drift_30d": {
                "changes": so_recent_changes,
                "entities_changed": so_customers_changed,
                "risk_distribution": so_drift,
            },
            "hotspots": so_hotspots,
        },
        "ap_invoices": {
            "suggestions": {
                "pending": ap_pending,
                "approved": ap_approved,
                "applied": ap_applied,
                "rejected": ap_rejected,
                "total_actionable": ap_pending + ap_approved,
            },
            "feedback": {
                "total": ap_fb_total,
                "agreement_pct": ap_agreement_pct,
            },
            "drift_30d": {
                "changes": ap_recent_changes,
                "entities_changed": ap_vendors_changed,
                "risk_distribution": ap_drift,
            },
            "hotspots": ap_hotspots,
        },
        "system_health": {
            "total_documents": total_docs,
            "pending_review": pending_review,
            "completed": completed,
            "posted_to_bc_7d": posted_7d,
            "ready_to_post": ready_to_post,
            "vendor_profiles": vendor_profiles,
            "customer_profiles": customer_profiles,
            "automation_rate": round(completed / max(total_docs, 1) * 100, 1),
        },
        "combined_drift": {
            "low": so_drift.get("low", 0) + ap_drift.get("low", 0),
            "medium": so_drift.get("medium", 0) + ap_drift.get("medium", 0),
            "high": so_drift.get("high", 0) + ap_drift.get("high", 0),
        },
    }


async def _get_drift_distribution(db, pipeline: str) -> Dict[str, int]:
    """Compute drift risk distribution for a pipeline."""
    if pipeline == "so":
        audit_col = db.so_learning_apply_audit
        profile_col = db.customer_posting_profiles
        entity_key = "customer_no"
    else:
        audit_col = db.ap_learning_apply_audit
        profile_col = db.vendor_invoice_profiles
        entity_key = "vendor_no"

    audits = await audit_col.find({}, {"_id": 0, entity_key: 1}).to_list(2000)
    entities = list(set(a.get(entity_key, "") for a in audits if a.get(entity_key)))

    if not entities:
        return {"low": 0, "medium": 0, "high": 0}

    cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    risk_counts = Counter()

    for eid in entities:
        entity_audits = [a for a in audits if a.get(entity_key) == eid]
        recent = sum(1 for a in entity_audits if True)  # all audits for this entity
        recent_30d = await audit_col.count_documents({
            entity_key: eid, "applied_at": {"$gte": cutoff_30d}
        })

        risk_score = 0
        if recent_30d > 8:
            risk_score += 2
        if len(entity_audits) > 15:
            risk_score += 1

        if risk_score >= 3:
            risk_counts["high"] += 1
        elif risk_score >= 1:
            risk_counts["medium"] += 1
        else:
            risk_counts["low"] += 1

    return {"low": risk_counts.get("low", 0), "medium": risk_counts.get("medium", 0), "high": risk_counts.get("high", 0)}


async def _get_top_hotspots(db, pipeline: str, limit: int = 5):
    """Get top hotspot entities by feedback friction."""
    if pipeline == "so":
        fb_col = db.so_reviewer_feedback
        entity_key = "customer_no"
        name_key = "customer_name"
    else:
        fb_col = db.ap_reviewer_feedback
        entity_key = "vendor_no"
        name_key = "vendor_name"

    pipeline_agg = [
        {"$group": {
            "_id": f"${entity_key}",
            "name": {"$first": f"${name_key}"},
            "total": {"$sum": 1},
            "incorrect": {"$sum": {"$cond": [
                {"$in": ["$reviewer_assessment", ["incorrect", "not_helpful"]]}, 1, 0
            ]}},
        }},
        {"$addFields": {
            "disagree_rate": {"$round": [{"$multiply": [{"$divide": ["$incorrect", {"$max": ["$total", 1]}]}, 100]}, 1]},
            "score": {"$add": [{"$multiply": ["$incorrect", 3]}, "$total"]},
        }},
        {"$sort": {"score": -1}},
        {"$limit": limit},
    ]

    results = await fb_col.aggregate(pipeline_agg).to_list(limit)
    return [{
        "entity_id": r["_id"],
        "entity_name": r.get("name", ""),
        "feedback_count": r["total"],
        "incorrect_count": r["incorrect"],
        "disagree_rate": r.get("disagree_rate", 0),
        "score": r.get("score", 0),
    } for r in results]
