"""
GPI Document Hub — Sales Order Customer Hotspot Review Service

Identifies customers that generate the most advisory friction and
diagnoses the likely root cause per customer for prioritized action.

ANALYSIS ONLY: Never changes profiles, overrides, thresholds, or workflow.
"""

import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT_CAUSES = [
    "low_profile_richness",
    "override_dependence",
    "extraction_quality",
    "threshold_tuning_needed",
    "ship_to_friction",
    "item_uom_friction",
    "profile_drift_risk",
    "high_volume_low_learning",
    "monitor_only",
]

FIX_PATHS = {
    "low_profile_richness":    "profile_improvement",
    "override_dependence":     "override_management",
    "extraction_quality":      "extraction_improvement",
    "threshold_tuning_needed": "threshold_tuning",
    "ship_to_friction":        "profile_improvement",
    "item_uom_friction":       "profile_improvement",
    "profile_drift_risk":      "monitor_only",
    "high_volume_low_learning": "profile_improvement",
    "monitor_only":            "monitor_only",
}


async def get_customer_hotspots(
    db,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    rep: Optional[str] = None,
    severity: Optional[str] = None,
    root_cause: Optional[str] = None,
    customer_no: Optional[str] = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """Rank customers by advisory friction and diagnose likely causes."""

    # ── Gather all signals ──
    fb_match: Dict[str, Any] = {}
    if date_from or date_to:
        ts: Dict[str, Any] = {}
        if date_from:
            ts["$gte"] = date_from
        if date_to:
            ts["$lte"] = date_to
        fb_match["timestamp"] = ts
    if customer_no:
        fb_match["customer_no"] = customer_no

    # Feedback
    all_fb = await db.so_reviewer_feedback.find(fb_match, {"_id": 0}).to_list(5000)
    fb_by_cust = defaultdict(list)
    for fb in all_fb:
        fb_by_cust[fb.get("customer_no", "")].append(fb)

    # Overrides
    all_overrides = await db.customer_rep_overrides.find({"active": True}, {"_id": 0}).to_list(500)
    overrides_by_cust = defaultdict(list)
    for o in all_overrides:
        overrides_by_cust[o.get("customer_no", "")].append(o)
    if rep:
        overrides_by_cust = {k: [o for o in v if o.get("rep_email") == rep] for k, v in overrides_by_cust.items()}

    # Applied suggestions
    all_suggestions = await db.so_learning_suggestions.find(
        {"status": "applied"}, {"_id": 0, "customer_no": 1, "suggestion_type": 1}
    ).to_list(1000)
    suggestions_by_cust = defaultdict(list)
    for s in all_suggestions:
        suggestions_by_cust[s.get("customer_no", "")].append(s)

    # Drift audits
    all_audits = await db.so_learning_apply_audit.find({}, {"_id": 0, "customer_no": 1}).to_list(2000)
    audit_count_by_cust = Counter(a.get("customer_no", "") for a in all_audits)

    # Profiles
    all_profiles = {}
    async for p in db.customer_posting_profiles.find({"status": "analyzed"}, {"_id": 0}):
        all_profiles[p.get("customer_no", "")] = p

    # ── Build hotspot scores ──
    all_customers = set(fb_by_cust) | set(overrides_by_cust) | set(suggestions_by_cust)
    if customer_no:
        all_customers = {customer_no}

    results = []
    for cno in all_customers:
        if not cno:
            continue
        assessment = _assess_customer(
            cno,
            fb_by_cust.get(cno, []),
            overrides_by_cust.get(cno, []),
            suggestions_by_cust.get(cno, []),
            audit_count_by_cust.get(cno, 0),
            all_profiles.get(cno),
        )
        # Apply filters
        if severity and assessment["severity"] != severity:
            continue
        if root_cause and root_cause not in assessment["root_causes"]:
            continue
        results.append(assessment)

    results.sort(key=lambda x: x["hotspot_score"], reverse=True)
    top = results[:limit]

    severity_dist = Counter(r["severity"] for r in results)

    return {
        "total_customers_analyzed": len(results),
        "severity_distribution": dict(severity_dist),
        "hotspots": top,
        "filters_applied": {k: v for k, v in {
            "date_from": date_from, "date_to": date_to, "rep": rep,
            "severity": severity, "root_cause": root_cause, "customer_no": customer_no,
        }.items() if v},
    }


async def get_customer_hotspot_detail(db, customer_no: str) -> Dict[str, Any]:
    """Detailed hotspot analysis for one customer."""
    result = await get_customer_hotspots(db, customer_no=customer_no, limit=1)
    hotspots = result.get("hotspots", [])
    if not hotspots:
        return {"error": f"No data for customer {customer_no}"}

    detail = hotspots[0]

    # Enrich with recent feedback
    recent_fb = await db.so_reviewer_feedback.find(
        {"customer_no": customer_no}, {"_id": 0}
    ).sort("timestamp", -1).limit(10).to_list(10)
    detail["recent_feedback"] = [{
        "document_id": fb.get("document_id"),
        "assessment": fb.get("reviewer_assessment"),
        "disagreed_fields": fb.get("disagreed_fields", []),
        "timestamp": fb.get("timestamp"),
    } for fb in recent_fb]

    # Enrich with pending suggestions
    pending = await db.so_learning_suggestions.find(
        {"customer_no": customer_no, "status": {"$in": ["pending", "approved"]}}, {"_id": 0}
    ).limit(10).to_list(10)
    detail["pending_suggestions"] = [{
        "suggestion_id": s.get("suggestion_id"),
        "type": s.get("suggestion_type"),
        "confidence": s.get("confidence"),
        "status": s.get("status"),
    } for s in pending]

    return detail


# =============================================================================
# Per-customer assessment
# =============================================================================

def _assess_customer(
    customer_no: str,
    feedback: List[Dict],
    overrides: List[Dict],
    applied_suggestions: List[Dict],
    audit_count: int,
    profile: Optional[Dict],
) -> Dict[str, Any]:
    n_fb = len(feedback)
    incorrect = sum(1 for fb in feedback if fb.get("reviewer_assessment") in ("incorrect", "not_helpful"))
    partial = sum(1 for fb in feedback if fb.get("reviewer_assessment") == "partially_correct")
    disagree_rate = round(incorrect / max(n_fb, 1) * 100, 1)

    # Disagreed field frequency
    field_counter = Counter()
    for fb in feedback:
        if fb.get("reviewer_assessment") in ("incorrect", "partially_correct", "not_helpful"):
            for f in (fb.get("disagreed_fields") or []):
                field_counter[f] += 1

    ship_to_issues = field_counter.get("ship_to", 0)
    item_issues = field_counter.get("item_match", 0) + field_counter.get("uom", 0)

    n_overrides = len(overrides)
    n_applied = len(applied_suggestions)

    richness = profile.get("profile_richness_score", 0) if profile else 0
    analyzed = profile.get("invoices_analyzed", 0) if profile else 0
    confidence = profile.get("template_confidence", "none") if profile else "none"
    customer_name = profile.get("customer_name", "") if profile else ""
    if not customer_name:
        customer_name = feedback[0].get("customer_name", "") if feedback else ""

    # ── Hotspot score ──
    score = 0
    score += incorrect * 3
    score += partial * 1
    score += ship_to_issues * 2
    score += item_issues * 2
    score += min(n_overrides * 2, 10)
    score += min(audit_count, 10)
    if richness < 40 and analyzed >= 10:
        score += 5  # high volume but low learning
    if disagree_rate > 50:
        score += 5

    # ── Root causes ──
    causes = []
    if richness < 30 and analyzed < 5:
        causes.append("low_profile_richness")
    if n_overrides >= 3:
        causes.append("override_dependence")
    if ship_to_issues >= 2:
        causes.append("ship_to_friction")
    if item_issues >= 2:
        causes.append("item_uom_friction")
    if audit_count >= 8:
        causes.append("profile_drift_risk")
    if analyzed >= 20 and richness < 40:
        causes.append("high_volume_low_learning")
    if disagree_rate > 40 and n_fb >= 3 and not causes:
        causes.append("threshold_tuning_needed")
    if not causes:
        causes.append("monitor_only")

    # ── Severity ──
    if score >= 15:
        sev = "high"
    elif score >= 6:
        sev = "medium"
    else:
        sev = "low"

    # ── Fix path ──
    primary_cause = causes[0] if causes else "monitor_only"
    fix_path = FIX_PATHS.get(primary_cause, "monitor_only")

    return {
        "customer_no": customer_no,
        "customer_name": customer_name,
        "hotspot_score": score,
        "severity": sev,
        "root_causes": causes,
        "recommended_fix_path": fix_path,
        "feedback_count": n_fb,
        "disagree_rate": disagree_rate,
        "incorrect_count": incorrect,
        "ship_to_issues": ship_to_issues,
        "item_uom_issues": item_issues,
        "override_count": n_overrides,
        "applied_suggestions": n_applied,
        "audit_changes": audit_count,
        "profile_richness": richness,
        "profile_confidence": confidence,
        "orders_analyzed": analyzed,
        "top_disagreed_fields": [{"field": f, "count": c} for f, c in field_counter.most_common(5)],
    }
