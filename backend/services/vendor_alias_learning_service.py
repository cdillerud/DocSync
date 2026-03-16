"""
GPI Document Hub - Vendor Alias Learning Service

Automatically learns vendor name variations from human approvals
and reviewer actions. When a reviewer confirms or sets a vendor,
the system captures the mapping between the raw invoice vendor string
and the resolved BC vendor for future automatic matching.

Safety rules prevent learning from low-confidence or ambiguous scenarios.

Usage:
    from services.vendor_alias_learning_service import learn_alias_from_approval

    await learn_alias_from_approval(doc, vendor_id="V123", vendor_name="Acme Corp")
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from deps import get_db
from services.vendor_name_helpers import normalize_vendor_name

logger = logging.getLogger("vendor_alias_learning")


# ---------------------------------------------------------------------------
# Safety thresholds
# ---------------------------------------------------------------------------

MIN_CLASSIFICATION_CONFIDENCE = 0.8
MIN_VENDOR_RAW_LENGTH = 3


# ---------------------------------------------------------------------------
# Core learning function
# ---------------------------------------------------------------------------

async def learn_alias_from_approval(
    doc: Dict[str, Any],
    vendor_id: str,
    vendor_name: str,
    actor: str = "system",
) -> Optional[Dict[str, Any]]:
    """Learn a vendor alias from a reviewer approval action.

    Extracts the raw vendor string from the document, normalizes it,
    and stores/updates the alias mapping.

    Args:
        doc: The hub_documents record (needs vendor_raw, ai_confidence, etc.)
        vendor_id: The resolved BC vendor ID/number
        vendor_name: The resolved BC vendor display name
        actor: Who performed the approval

    Returns:
        The alias record if learned, None if skipped.
    """
    db = get_db()

    # Extract vendor_raw from document
    vendor_raw = (
        doc.get("vendor_raw")
        or doc.get("extracted_vendor")
        or (doc.get("extracted_fields") or {}).get("vendor")
        or ""
    ).strip()

    if not vendor_raw or len(vendor_raw) < MIN_VENDOR_RAW_LENGTH:
        logger.debug("[VendorAlias] Skipped: vendor_raw too short (%r)", vendor_raw)
        return None

    if not vendor_id:
        logger.debug("[VendorAlias] Skipped: no vendor_id provided")
        return None

    # Safety check: classification confidence
    classification_confidence = float(doc.get("ai_confidence", 0) or 0)
    if classification_confidence < MIN_CLASSIFICATION_CONFIDENCE:
        logger.debug(
            "[VendorAlias] Skipped: low classification confidence (%.2f < %.2f)",
            classification_confidence, MIN_CLASSIFICATION_CONFIDENCE,
        )
        return None

    # Normalize the raw vendor string
    normalized = normalize_vendor_name(vendor_raw)
    if not normalized:
        return None

    # Check if the normalized form is identical to the vendor_name (no alias needed)
    normalized_target = normalize_vendor_name(vendor_name)
    if normalized == normalized_target:
        logger.debug("[VendorAlias] Skipped: normalized forms are identical (%s)", normalized)
        return None

    now = datetime.now(timezone.utc).isoformat()

    # Check if alias already exists
    existing = await db.vendor_aliases.find_one(
        {"normalized_alias": normalized},
        {"_id": 0},
    )

    if existing:
        # Update existing alias
        if existing.get("vendor_id") == vendor_id or existing.get("canonical_vendor_id") == vendor_id or existing.get("vendor_no") == vendor_id:
            # Same vendor — increment usage
            await db.vendor_aliases.update_one(
                {"normalized_alias": normalized},
                {
                    "$inc": {"usage_count": 1},
                    "$set": {"last_seen": now},
                },
            )
            logger.info(
                "[VendorAlias] Reinforced alias=%r vendor=%r (usage_count +1)",
                normalized, vendor_name,
            )
            existing["usage_count"] = existing.get("usage_count", 0) + 1
            existing["last_seen"] = now
            return existing
        else:
            # Different vendor — conflict, skip learning
            logger.warning(
                "[VendorAlias] Conflict: alias=%r maps to %r but reviewer chose %r. Skipped.",
                normalized,
                existing.get("vendor_id") or existing.get("canonical_vendor_id") or existing.get("vendor_no"),
                vendor_id,
            )
            return None

    # Create new alias
    alias_doc = {
        "alias": vendor_raw,
        "normalized_alias": normalized,
        "alias_string": vendor_raw,
        "vendor_id": vendor_id,
        "canonical_vendor_id": vendor_id,
        "vendor_no": vendor_id,
        "vendor_name": vendor_name,
        "first_seen": now,
        "last_seen": now,
        "confidence": 1.0,
        "usage_count": 1,
        "source": "auto_learned",
        "learned_by": actor,
        "created_at": now,
    }

    await db.vendor_aliases.insert_one(alias_doc)
    alias_doc.pop("_id", None)

    # Update in-memory alias map
    try:
        from services.vendor_name_helpers import VENDOR_ALIAS_MAP
        VENDOR_ALIAS_MAP[vendor_raw] = vendor_name
        VENDOR_ALIAS_MAP[normalized] = vendor_name
    except Exception:
        pass

    logger.info(
        '[VendorAlias] Learned alias="%s" vendor="%s" vendor_id=%s',
        normalized, vendor_name, vendor_id,
    )
    return alias_doc


# ---------------------------------------------------------------------------
# Alias lookup with usage tracking
# ---------------------------------------------------------------------------

async def lookup_and_track_alias(vendor_raw: str) -> Optional[Dict[str, Any]]:
    """Look up a vendor alias and increment usage_count if found.

    Args:
        vendor_raw: The raw vendor string from the document.

    Returns:
        The alias record with vendor_id if found, None otherwise.
    """
    db = get_db()

    if not vendor_raw or len(vendor_raw.strip()) < MIN_VENDOR_RAW_LENGTH:
        return None

    normalized = normalize_vendor_name(vendor_raw.strip())
    if not normalized:
        return None

    alias = await db.vendor_aliases.find_one(
        {"normalized_alias": normalized},
        {"_id": 0},
    )

    if alias:
        # Track usage
        now = datetime.now(timezone.utc).isoformat()
        await db.vendor_aliases.update_one(
            {"normalized_alias": normalized},
            {
                "$inc": {"usage_count": 1},
                "$set": {"last_used_at": now, "last_seen": now},
            },
        )

        vendor_id = (
            alias.get("vendor_id")
            or alias.get("canonical_vendor_id")
            or alias.get("vendor_no")
        )

        logger.info(
            '[VendorAlias] Matched alias="%s" vendor_id=%s',
            normalized, vendor_id,
        )

        return {
            "vendor_id": vendor_id,
            "vendor_name": alias.get("vendor_name"),
            "vendor_no": alias.get("vendor_no") or vendor_id,
            "match_method": "learned_alias",
            "alias_record": alias,
        }

    return None


# ---------------------------------------------------------------------------
# Alias metrics for dashboard
# ---------------------------------------------------------------------------

async def get_alias_metrics() -> Dict[str, Any]:
    """Get vendor alias learning metrics for the dashboard."""
    db = get_db()

    total_aliases = await db.vendor_aliases.count_documents({})
    auto_learned = await db.vendor_aliases.count_documents({"source": "auto_learned"})
    manual_aliases = await db.vendor_aliases.count_documents({"source": {"$ne": "auto_learned"}})

    # Top aliases by usage
    top_aliases_cursor = db.vendor_aliases.find(
        {"usage_count": {"$gt": 0}},
        {"_id": 0, "alias": 1, "normalized_alias": 1, "vendor_name": 1, "usage_count": 1, "source": 1},
    ).sort("usage_count", -1).limit(10)
    top_aliases = await top_aliases_cursor.to_list(10)

    # Total alias matches (sum of usage_count)
    usage_pipeline = [
        {"$group": {
            "_id": None,
            "total_usage": {"$sum": "$usage_count"},
            "avg_usage": {"$avg": "$usage_count"},
        }},
    ]
    usage_raw = await db.vendor_aliases.aggregate(usage_pipeline).to_list(1)
    total_usage = usage_raw[0]["total_usage"] if usage_raw else 0
    avg_usage = round(usage_raw[0]["avg_usage"], 1) if usage_raw else 0

    # Alias match rate (docs matched by alias vs total docs with vendor)
    total_docs = await db.hub_documents.count_documents({})
    alias_matched = await db.hub_documents.count_documents({
        "vendor_match_method": {"$in": ["alias", "learned_alias"]},
    })
    direct_matched = await db.hub_documents.count_documents({
        "vendor_match_method": {"$in": ["exact_name", "bc_search", "normalized"]},
    })
    fuzzy_matched = await db.hub_documents.count_documents({
        "vendor_match_method": {"$in": ["fuzzy", "fuzzy_bc", "fuzzy_candidates"]},
    })
    total_with_vendor = await db.hub_documents.count_documents({
        "vendor_canonical": {"$exists": True, "$ne": None},
    })

    alias_match_rate = (alias_matched / total_docs * 100) if total_docs > 0 else 0
    direct_match_rate = (direct_matched / total_docs * 100) if total_docs > 0 else 0
    vendor_match_rate = (total_with_vendor / total_docs * 100) if total_docs > 0 else 0

    return {
        "total_aliases": total_aliases,
        "auto_learned": auto_learned,
        "manual_aliases": manual_aliases,
        "total_alias_usage": total_usage,
        "avg_alias_usage": avg_usage,
        "top_aliases": top_aliases,
        "alias_match_rate": round(alias_match_rate, 1),
        "direct_match_rate": round(direct_match_rate, 1),
        "vendor_match_rate": round(vendor_match_rate, 1),
        "alias_matched_docs": alias_matched,
        "direct_matched_docs": direct_matched,
        "fuzzy_matched_docs": fuzzy_matched,
        "total_with_vendor": total_with_vendor,
        "total_docs": total_docs,
    }


# ---------------------------------------------------------------------------
# Ensure indexes
# ---------------------------------------------------------------------------

async def ensure_alias_indexes():
    """Create indexes on vendor_aliases collection."""
    db = get_db()
    await db.vendor_aliases.create_index("normalized_alias", unique=True, sparse=True)
    await db.vendor_aliases.create_index("vendor_id")
    await db.vendor_aliases.create_index("canonical_vendor_id")
    await db.vendor_aliases.create_index("vendor_no")
    logger.info("[VendorAlias] Indexes ensured on vendor_aliases")
