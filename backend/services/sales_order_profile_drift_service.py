"""
GPI Document Hub — Sales Order Profile Drift & Change History Service

Monitors customer profile evolution, detects drift risk from
over-broadening, and provides change history for governance.

GOVERNANCE/VISIBILITY ONLY: Never reverts or blocks changes.
"""

import logging
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

# Drift-risk thresholds
MAX_CHANGES_30D = 8
MAX_SHIP_TOS = 8
MAX_OCCASIONAL_ITEMS = 15
MAX_VARIABILITY = 0.90
RICHNESS_JUMP_THRESHOLD = 25  # points in one apply batch


async def get_customer_drift_detail(db, customer_no: str) -> Dict[str, Any]:
    """Detailed drift analysis for a single customer."""
    audits = await db.so_learning_apply_audit.find(
        {"customer_no": customer_no}, {"_id": 0}
    ).sort("applied_at", -1).to_list(100)

    profile = await db.customer_posting_profiles.find_one(
        {"customer_no": customer_no}, {"_id": 0}
    )

    if not audits and not profile:
        return {"error": f"No data for customer {customer_no}"}

    assessment = _assess_customer_drift(customer_no, audits, profile or {})

    # Build timeline
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
            "invoices_analyzed": (profile or {}).get("invoices_analyzed"),
            "template_confidence": (profile or {}).get("template_confidence"),
            "common_items": len((profile or {}).get("common_items", [])),
            "occasional_valid_items": len((profile or {}).get("occasional_valid_items", [])),
            "alternate_ship_tos": len((profile or {}).get("alternate_ship_tos", [])),
            "alternate_uom_items": len((profile or {}).get("alternate_valid_uoms_by_item", {})),
            "variability_index": (profile or {}).get("customer_variability_index"),
            "richness_score": (profile or {}).get("profile_richness_score"),
            "amount_range": (profile or {}).get("amount_range"),
        },
    }


# =============================================================================
# Drift assessment
# =============================================================================

def _assess_customer_drift(
    customer_no: str,
    audits: List[Dict],
    profile: Dict,
) -> Dict[str, Any]:
    """Assess drift risk for a single customer."""
    total_changes = len(audits)
    effective_changes = sum(1 for a in audits if not a.get("no_op", False))

    # Recent cadence (last 30 days)
    cutoff_30d = (datetime.now(timezone.utc) - timedelta(days=30)).isoformat()
    recent = [a for a in audits if (a.get("applied_at") or "") >= cutoff_30d]
    recent_count = len(recent)

    # Type breakdown
    type_counts = Counter(a.get("suggestion_type", "") for a in audits)

    # Current profile metrics
    ship_to_count = len(profile.get("alternate_ship_tos", []))
    occasional_count = len(profile.get("occasional_valid_items", []))
    variability = profile.get("customer_variability_index", 0)
    richness = profile.get("profile_richness_score", 0)

    # Pre/post richness delta from snapshots
    richness_deltas = []
    for a in audits:
        pre = (a.get("pre_change_snapshot") or {}).get("profile_richness_score")
        post = (a.get("post_change_snapshot") or {}).get("profile_richness_score")
        if pre is not None and post is not None:
            richness_deltas.append(post - pre)

    # Compute risk signals
    signals = []
    risk_score = 0

    if recent_count > MAX_CHANGES_30D:
        signals.append(f"{recent_count} changes in last 30d (threshold: {MAX_CHANGES_30D})")
        risk_score += 2

    if ship_to_count > MAX_SHIP_TOS:
        signals.append(f"{ship_to_count} alternate ship-tos (threshold: {MAX_SHIP_TOS})")
        risk_score += 1

    if occasional_count > MAX_OCCASIONAL_ITEMS:
        signals.append(f"{occasional_count} occasional items (threshold: {MAX_OCCASIONAL_ITEMS})")
        risk_score += 1

    if variability > MAX_VARIABILITY:
        signals.append(f"Variability index {variability:.2f} (threshold: {MAX_VARIABILITY})")
        risk_score += 1

    if richness_deltas and max(richness_deltas) > RICHNESS_JUMP_THRESHOLD:
        signals.append(f"Richness jump of {max(richness_deltas)} in single apply (threshold: {RICHNESS_JUMP_THRESHOLD})")
        risk_score += 2

    # Classify risk
    if risk_score >= 3:
        drift_risk = "high"
    elif risk_score >= 1:
        drift_risk = "medium"
    else:
        drift_risk = "low"

    return {
        "customer_no": customer_no,
        "customer_name": profile.get("customer_name", ""),
        "drift_risk": drift_risk,
        "risk_score": risk_score,
        "risk_signals": signals,
        "total_changes": total_changes,
        "effective_changes": effective_changes,
        "recent_30d_changes": recent_count,
        "change_types": dict(type_counts),
        "ship_to_count": ship_to_count,
        "occasional_item_count": occasional_count,
        "variability_index": variability,
        "richness_score": richness,
    }
