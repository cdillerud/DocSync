"""
GPI Document Hub — AP Invoice Vendor Hotspot Review Service

Identifies vendors that generate the most advisory friction and
diagnoses the likely root cause per vendor for prioritized action.

ANALYSIS ONLY: Never changes profiles, thresholds, or workflow.
"""

import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

ROOT_CAUSES = [
    "low_profile_maturity",
    "vendor_match_ambiguity",
    "extraction_quality",
    "amount_sensitivity",
    "po_reference_friction",
    "duplicate_sensitivity",
    "profile_drift_risk",
    "high_volume_low_learning",
    "monitor_only",
]

FIX_PATHS = {
    "low_profile_maturity":     "profile_improvement",
    "vendor_match_ambiguity":   "alias_management",
    "extraction_quality":       "extraction_improvement",
    "amount_sensitivity":       "threshold_tuning",
    "po_reference_friction":    "po_rule_tuning",
    "duplicate_sensitivity":    "threshold_tuning",
    "profile_drift_risk":       "monitor_only",
    "high_volume_low_learning": "profile_improvement",
    "monitor_only":             "monitor_only",
}


async def get_ap_vendor_hotspots(
    db,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    severity: Optional[str] = None,
    root_cause: Optional[str] = None,
    vendor_no: Optional[str] = None,
    limit: int = 30,
) -> Dict[str, Any]:
    """Rank vendors by advisory friction and diagnose likely causes."""

    fb_match: Dict[str, Any] = {}
    if date_from or date_to:
        ts: Dict[str, Any] = {}
        if date_from:
            ts["$gte"] = date_from
        if date_to:
            ts["$lte"] = date_to
        fb_match["timestamp"] = ts
    if vendor_no:
        fb_match["vendor_no"] = vendor_no

    all_fb = await db.ap_reviewer_feedback.find(fb_match, {"_id": 0}).to_list(5000)
    fb_by_vendor = defaultdict(list)
    for fb in all_fb:
        fb_by_vendor[fb.get("vendor_no", "")].append(fb)

    all_suggestions = await db.ap_learning_suggestions.find(
        {"status": "applied"}, {"_id": 0, "vendor_no": 1, "suggestion_type": 1}
    ).to_list(1000)
    suggestions_by_vendor = defaultdict(list)
    for s in all_suggestions:
        suggestions_by_vendor[s.get("vendor_no", "")].append(s)

    all_audits = await db.ap_learning_apply_audit.find({}, {"_id": 0, "vendor_no": 1}).to_list(2000)
    audit_count_by_vendor = Counter(a.get("vendor_no", "") for a in all_audits)

    all_profiles = {}
    async for p in db.vendor_invoice_profiles.find({}, {"_id": 0}):
        all_profiles[p.get("vendor_no", "")] = p

    all_vendors = set(fb_by_vendor) | set(suggestions_by_vendor)
    if vendor_no:
        all_vendors = {vendor_no}

    results = []
    for vno in all_vendors:
        if not vno:
            continue
        assessment = _assess_vendor(
            vno,
            fb_by_vendor.get(vno, []),
            suggestions_by_vendor.get(vno, []),
            audit_count_by_vendor.get(vno, 0),
            all_profiles.get(vno),
        )
        if severity and assessment["severity"] != severity:
            continue
        if root_cause and root_cause not in assessment["root_causes"]:
            continue
        results.append(assessment)

    results.sort(key=lambda x: x["hotspot_score"], reverse=True)
    top = results[:limit]

    severity_dist = Counter(r["severity"] for r in results)

    return {
        "total_vendors_analyzed": len(results),
        "severity_distribution": dict(severity_dist),
        "hotspots": top,
        "filters_applied": {k: v for k, v in {
            "date_from": date_from, "date_to": date_to,
            "severity": severity, "root_cause": root_cause, "vendor_no": vendor_no,
        }.items() if v},
    }


async def get_ap_vendor_hotspot_detail(db, vendor_no: str) -> Dict[str, Any]:
    """Detailed hotspot analysis for one vendor."""
    result = await get_ap_vendor_hotspots(db, vendor_no=vendor_no, limit=1)
    hotspots = result.get("hotspots", [])
    if not hotspots:
        return {"error": f"No data for vendor {vendor_no}"}

    detail = hotspots[0]

    recent_fb = await db.ap_reviewer_feedback.find(
        {"vendor_no": vendor_no}, {"_id": 0}
    ).sort("timestamp", -1).limit(10).to_list(10)
    detail["recent_feedback"] = [{
        "document_id": fb.get("document_id"),
        "assessment": fb.get("reviewer_assessment"),
        "disagreed_fields": fb.get("disagreed_fields", []),
        "timestamp": fb.get("timestamp"),
    } for fb in recent_fb]

    pending = await db.ap_learning_suggestions.find(
        {"vendor_no": vendor_no, "status": {"$in": ["pending", "approved"]}}, {"_id": 0}
    ).limit(10).to_list(10)
    detail["pending_suggestions"] = [{
        "suggestion_id": s.get("suggestion_id"),
        "type": s.get("suggestion_type"),
        "confidence": s.get("confidence"),
        "status": s.get("status"),
    } for s in pending]

    return detail


def _assess_vendor(
    vendor_no: str,
    feedback: List[Dict],
    applied_suggestions: List[Dict],
    audit_count: int,
    profile: Optional[Dict],
) -> Dict[str, Any]:
    n_fb = len(feedback)
    incorrect = sum(1 for fb in feedback if fb.get("reviewer_assessment") in ("incorrect", "not_helpful"))
    partial = sum(1 for fb in feedback if fb.get("reviewer_assessment") == "partially_correct")
    disagree_rate = round(incorrect / max(n_fb, 1) * 100, 1)

    field_counter = Counter()
    for fb in feedback:
        if fb.get("reviewer_assessment") in ("incorrect", "partially_correct", "not_helpful"):
            for f in (fb.get("disagreed_fields") or []):
                field_counter[f] += 1

    vendor_match_issues = field_counter.get("vendor_match", 0)
    po_issues = field_counter.get("po_reference", 0)
    amount_issues = field_counter.get("amount_range", 0)
    dup_issues = field_counter.get("duplicate", 0)

    n_applied = len(applied_suggestions)

    bc_count = profile.get("bc_invoice_count", 0) if profile else 0
    confidence = profile.get("posting_confidence", profile.get("template_confidence", "none")) if profile else "none"
    vendor_name = profile.get("vendor_name", "") if profile else ""
    if not vendor_name:
        vendor_name = feedback[0].get("vendor_name", "") if feedback else ""

    score = 0
    score += incorrect * 3
    score += partial * 1
    score += vendor_match_issues * 2
    score += po_issues * 2
    score += amount_issues * 2
    score += dup_issues * 1
    score += min(audit_count, 10)
    if bc_count < 5 and n_fb >= 3:
        score += 5
    if disagree_rate > 50:
        score += 5

    causes = []
    if bc_count < 5:
        causes.append("low_profile_maturity")
    if vendor_match_issues >= 2:
        causes.append("vendor_match_ambiguity")
    if po_issues >= 2:
        causes.append("po_reference_friction")
    if amount_issues >= 2:
        causes.append("amount_sensitivity")
    if dup_issues >= 2:
        causes.append("duplicate_sensitivity")
    if audit_count >= 8:
        causes.append("profile_drift_risk")
    if bc_count >= 20 and disagree_rate > 30:
        causes.append("high_volume_low_learning")
    if disagree_rate > 40 and n_fb >= 3 and not causes:
        causes.append("extraction_quality")
    if not causes:
        causes.append("monitor_only")

    if score >= 15:
        sev = "high"
    elif score >= 6:
        sev = "medium"
    else:
        sev = "low"

    primary_cause = causes[0] if causes else "monitor_only"
    fix_path = FIX_PATHS.get(primary_cause, "monitor_only")

    return {
        "vendor_no": vendor_no,
        "vendor_name": vendor_name,
        "hotspot_score": score,
        "severity": sev,
        "root_causes": causes,
        "recommended_fix_path": fix_path,
        "feedback_count": n_fb,
        "disagree_rate": disagree_rate,
        "incorrect_count": incorrect,
        "vendor_match_issues": vendor_match_issues,
        "po_issues": po_issues,
        "amount_issues": amount_issues,
        "applied_suggestions": n_applied,
        "audit_changes": audit_count,
        "bc_invoice_count": bc_count,
        "profile_confidence": confidence,
        "top_disagreed_fields": [{"field": f, "count": c} for f, c in field_counter.most_common(5)],
    }
