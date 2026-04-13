"""
GPI Document Hub — AP Invoice Vendor Profile Drift & Change History Service

Monitors vendor profile evolution, detects drift risk from
over-broadening, and provides change history for governance.

GOVERNANCE/VISIBILITY ONLY: Never reverts or blocks changes.
"""

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MAX_CHANGES_30D = 8
MAX_ALIASES = 10
MAX_VARIABILITY = 0.90
AMOUNT_SWING_THRESHOLD = 0.50  # >50% range change in one apply


async def get_ap_profile_drift_summary(
    db,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    vendor_no: Optional[str] = None,
    drift_risk: Optional[str] = None,
    suggestion_type: Optional[str] = None,
    applied_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Summarize vendor profile drift across all vendors with applied changes."""

    match: Dict[str, Any] = {}
    if date_from or date_to:
        ts: Dict[str, Any] = {}
        if date_from:
            ts["$gte"] = date_from
        if date_to:
            ts["$lte"] = date_to
        match["applied_at"] = ts
    if vendor_no:
        match["vendor_no"] = vendor_no
    if suggestion_type:
        match["suggestion_type"] = suggestion_type
    if applied_by:
        match["applied_by"] = applied_by

    audits = await db.ap_learning_apply_audit.find(match, {"_id": 0}).to_list(2000)

    if not audits:
        return {"total_vendors": 0, "message": "No applied AP changes found"}

    by_vendor: Dict[str, List[Dict]] = defaultdict(list)
    for a in audits:
        by_vendor[a.get("vendor_no", "")].append(a)

    vendor_nos = list(by_vendor.keys())
    profiles = {}
    if vendor_nos:
        async for p in db.vendor_invoice_profiles.find(
            {"vendor_no": {"$in": vendor_nos}}, {"_id": 0}
        ):
            profiles[p["vendor_no"]] = p

    vendors = []
    risk_dist = Counter()
    type_dist = Counter()

    for vno, changes in sorted(by_vendor.items(), key=lambda x: len(x[1]), reverse=True):
        profile = profiles.get(vno, {})
        assessment = _assess_vendor_drift(vno, changes, profile)
        risk_dist[assessment["drift_risk"]] += 1
        for c in changes:
            type_dist[c.get("suggestion_type", "unknown")] += 1

        if drift_risk and assessment["drift_risk"] != drift_risk:
            continue
        vendors.append(assessment)

    return {
        "total_vendors": len(by_vendor),
        "total_applied_changes": len(audits),
        "drift_risk_distribution": dict(risk_dist),
        "change_type_distribution": dict(type_dist),
        "vendors": vendors[:30],
        "high_risk_count": risk_dist.get("high", 0),
        "filters_applied": {k: v for k, v in {
            "date_from": date_from, "date_to": date_to, "vendor_no": vendor_no,
            "drift_risk": drift_risk, "suggestion_type": suggestion_type, "applied_by": applied_by,
        }.items() if v},
    }


async def get_ap_vendor_drift_detail(db, vendor_no: str) -> Dict[str, Any]:
    """Detailed drift analysis for a single vendor."""
    audits = await db.ap_learning_apply_audit.find(
        {"vendor_no": vendor_no}, {"_id": 0}
    ).sort("applied_at", -1).to_list(100)

    profile = await db.vendor_invoice_profiles.find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )

    if not audits and not profile:
        return {"error": f"No data for vendor {vendor_no}"}

    assessment = _assess_vendor_drift(vendor_no, audits, profile or {})

    timeline = []
    for a in sorted(audits, key=lambda x: x.get("applied_at", "")):
        timeline.append({
            "date": a.get("applied_at"),
            "type": a.get("suggestion_type"),
            "summary": a.get("change_summary"),
            "no_op": a.get("no_op", False),
            "applied_by": a.get("applied_by"),
        })

    return {
        **assessment,
        "timeline": timeline,
        "current_profile": {
            "bc_invoice_count": (profile or {}).get("bc_invoice_count"),
            "posting_confidence": (profile or {}).get("posting_confidence", (profile or {}).get("template_confidence")),
            "known_aliases": len((profile or {}).get("known_aliases", [])),
            "accepted_reference_patterns": len((profile or {}).get("accepted_reference_patterns", [])),
            "po_expected": (profile or {}).get("po_expected", True),
            "vendor_variability_index": (profile or {}).get("vendor_variability_index"),
            "amount_stats": (profile or {}).get("amount_stats"),
            "default_item_code": (profile or {}).get("default_item_code"),
        },
    }


async def get_ap_change_history(db, vendor_no: str, limit: int = 50) -> Dict[str, Any]:
    """Full change history with pre/post snapshots."""
    audits = await db.ap_learning_apply_audit.find(
        {"vendor_no": vendor_no}, {"_id": 0}
    ).sort("applied_at", -1).limit(limit).to_list(limit)

    total = await db.ap_learning_apply_audit.count_documents({"vendor_no": vendor_no})
    return {"vendor_no": vendor_no, "total": total, "showing": len(audits), "changes": audits}


def _assess_vendor_drift(
    vendor_no: str,
    audits: List[Dict],
    profile: Dict,
) -> Dict[str, Any]:
    total_changes = len(audits)
    effective_changes = sum(1 for a in audits if not a.get("no_op", False))

    cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent = [a for a in audits if (a.get("applied_at") or "") >= cutoff_30d]
    recent_count = len(recent)

    type_counts = Counter(a.get("suggestion_type", "") for a in audits)

    alias_count = len(profile.get("known_aliases", []))
    variability = profile.get("vendor_variability_index", 0)

    # Amount swing detection from audit snapshots
    amount_swings = []
    for a in audits:
        pre_stats = (a.get("pre_change_snapshot") or {}).get("amount_stats") or {}
        post_stats = (a.get("post_change_snapshot") or {}).get("amount_stats") or {}
        pre_range = (pre_stats.get("max", 0) or 0) - (pre_stats.get("min", 0) or 0)
        post_range = (post_stats.get("max", 0) or 0) - (post_stats.get("min", 0) or 0)
        if pre_range > 0:
            swing = abs(post_range - pre_range) / pre_range
            amount_swings.append(swing)

    signals = []
    risk_score = 0

    if recent_count > MAX_CHANGES_30D:
        signals.append(f"{recent_count} changes in last 30d (threshold: {MAX_CHANGES_30D})")
        risk_score += 2

    if alias_count > MAX_ALIASES:
        signals.append(f"{alias_count} known aliases (threshold: {MAX_ALIASES})")
        risk_score += 1

    if variability > MAX_VARIABILITY:
        signals.append(f"Variability index {variability:.2f} (threshold: {MAX_VARIABILITY})")
        risk_score += 1

    if amount_swings and max(amount_swings) > AMOUNT_SWING_THRESHOLD:
        signals.append(f"Amount range swing of {max(amount_swings):.0%} in single apply (threshold: {AMOUNT_SWING_THRESHOLD:.0%})")
        risk_score += 2

    if risk_score >= 3:
        drift_risk = "high"
    elif risk_score >= 1:
        drift_risk = "medium"
    else:
        drift_risk = "low"

    return {
        "vendor_no": vendor_no,
        "vendor_name": profile.get("vendor_name", ""),
        "drift_risk": drift_risk,
        "risk_score": risk_score,
        "risk_signals": signals,
        "total_changes": total_changes,
        "effective_changes": effective_changes,
        "recent_30d_changes": recent_count,
        "change_types": dict(type_counts),
        "alias_count": alias_count,
        "variability_index": variability,
    }
