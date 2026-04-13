"""
GPI Document Hub — Sales Order Draft Context Service

Provides customer profile intelligence to assist SO draft creation.
Returns suggestions, expected patterns, and early warnings.

ASSISTIVE ONLY: Never forces values or overrides user data.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def get_draft_context(
    db,
    customer_no: str,
) -> Dict[str, Any]:
    """
    Build draft-assist context from a customer's posting profile.
    Returns structured suggestions for the frontend.
    """
    if not customer_no:
        return _no_profile_response("No customer number provided")

    profile = await db.customer_posting_profiles.find_one(
        {"customer_no": customer_no, "status": "analyzed"}, {"_id": 0}
    )

    if not profile:
        return _no_profile_response(f"No profile for customer {customer_no}")

    analyzed = profile.get("invoices_analyzed", 0)
    confidence = profile.get("template_confidence", "low")
    richness = profile.get("profile_richness_score", 0)
    variability = profile.get("customer_variability_index", 0)

    # ── Ship-to suggestions ──
    ship_tos = []
    primary = profile.get("typical_ship_to")
    if primary:
        ship_tos.append({"name": primary, "rank": "primary", "note": "Most common destination"})
    for alt in profile.get("alternate_ship_tos", []):
        ship_tos.append({"name": alt, "rank": "alternate", "note": "Previously used"})

    # ── Item suggestions by frequency band ──
    items = []
    for item in profile.get("core_items", profile.get("common_items", []))[:10]:
        alt_uoms = profile.get("alternate_valid_uoms_by_item", {}).get(item, [])
        primary_uom = alt_uoms[0] if alt_uoms else _guess_default_uom(profile)
        items.append({
            "item_number": item,
            "band": "core",
            "primary_uom": primary_uom,
            "alternate_uoms": alt_uoms[1:] if len(alt_uoms) > 1 else [],
            "note": "Frequently ordered",
        })
    for item in profile.get("regular_items", [])[:5]:
        alt_uoms = profile.get("alternate_valid_uoms_by_item", {}).get(item, [])
        primary_uom = alt_uoms[0] if alt_uoms else _guess_default_uom(profile)
        items.append({
            "item_number": item, "band": "regular",
            "primary_uom": primary_uom,
            "alternate_uoms": alt_uoms[1:] if len(alt_uoms) > 1 else [],
            "note": "Regularly ordered",
        })
    for item in profile.get("occasional_valid_items", [])[:5]:
        alt_uoms = profile.get("alternate_valid_uoms_by_item", {}).get(item, [])
        primary_uom = alt_uoms[0] if alt_uoms else _guess_default_uom(profile)
        items.append({
            "item_number": item, "band": "occasional",
            "primary_uom": primary_uom,
            "alternate_uoms": alt_uoms[1:] if len(alt_uoms) > 1 else [],
            "note": "Occasionally ordered — valid",
        })

    # ── Order value context ──
    amt_range = profile.get("amount_range", {})
    value_context = {
        "typical": profile.get("typical_order_value", 0),
        "min": amt_range.get("min", 0),
        "max": amt_range.get("max", 0),
    }

    # ── Warnings / guidance ──
    guidance = []
    if confidence == "low":
        guidance.append({"level": "info", "text": f"Limited history ({analyzed} orders) — suggestions may not be representative"})
    if variability >= 0.5:
        guidance.append({"level": "info", "text": "This customer has diverse ordering patterns — new items/destinations are common"})
    po_pattern = profile.get("po_number_pattern", "unknown")
    if po_pattern != "unknown":
        guidance.append({"level": "hint", "text": f"PO numbers are typically {po_pattern} format"})

    logger.info(
        "[DraftContext] customer=%s profile=%s richness=%d items=%d ship_tos=%d guidance=%d",
        customer_no, confidence, richness, len(items), len(ship_tos), len(guidance),
    )

    return {
        "customer_no": customer_no,
        "customer_name": profile.get("customer_name", ""),
        "has_profile": True,
        "profile_confidence": confidence,
        "profile_richness_score": richness,
        "customer_variability_index": round(variability, 4),
        "orders_analyzed": analyzed,
        "ship_to_suggestions": ship_tos,
        "item_suggestions": items,
        "common_uoms": profile.get("common_uoms", []),
        "value_context": value_context,
        "typical_line_count": profile.get("typical_line_count"),
        "po_pattern": po_pattern,
        "guidance": guidance,
    }


def _no_profile_response(reason: str) -> Dict[str, Any]:
    return {
        "has_profile": False,
        "profile_confidence": None,
        "reason": reason,
        "ship_to_suggestions": [],
        "item_suggestions": [],
        "common_uoms": [],
        "value_context": {},
        "guidance": [{"level": "info", "text": "No customer history — draft will use extracted data only"}],
    }


def _guess_default_uom(profile: Dict) -> str:
    uoms = profile.get("common_uoms", [])
    return uoms[0] if uoms else "EA"
