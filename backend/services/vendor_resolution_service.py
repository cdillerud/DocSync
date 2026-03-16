"""
GPI Document Hub - Vendor Resolution Service

Provides:
  1. Structured vendor_resolution object builder for per-document tracking
  2. Negative feedback capture (rejected auto-matches)
  3. Guardrail checks (block repeat bad fuzzy matches)
  4. Resolution analytics aggregation
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from deps import get_db
from services.vendor_name_helpers import normalize_vendor_name

logger = logging.getLogger("vendor_resolution")


# ---------------------------------------------------------------------------
# Resolution statuses
# ---------------------------------------------------------------------------

STATUS_RESOLVED = "resolved"
STATUS_UNRESOLVED = "unresolved"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_NEEDS_REVIEW = "needs_review"


# ---------------------------------------------------------------------------
# 1. Build per-document vendor_resolution object
# ---------------------------------------------------------------------------

def build_resolution_object(
    vendor_raw: str,
    match_result: Dict[str, Any],
    status: Optional[str] = None,
    reason: Optional[str] = None,
) -> Dict[str, Any]:
    """Build a structured vendor_resolution object for a document.

    Args:
        vendor_raw: The raw vendor string from the document.
        match_result: The result dict from lookup_vendor_alias or match_vendor_in_bc.
        status: Override status (resolved/unresolved/ambiguous/needs_review).
        reason: Human-readable reason for the resolution outcome.

    Returns:
        A dict suitable for storing as doc["vendor_resolution"].
    """
    method = match_result.get("vendor_match_method", "none")
    vendor_canonical = match_result.get("vendor_canonical")
    score = match_result.get("match_score") or match_result.get("score")

    if not status:
        if vendor_canonical and method in ("alias_match", "bc_exact_match", "bc_search"):
            status = STATUS_RESOLVED
        elif vendor_canonical and method == "fuzzy_match":
            score_val = float(score) if score else 0
            status = STATUS_RESOLVED if score_val >= 0.95 else STATUS_NEEDS_REVIEW
        elif vendor_canonical:
            status = STATUS_RESOLVED
        else:
            status = STATUS_UNRESOLVED

    if not reason:
        if status == STATUS_RESOLVED:
            reason = f"Auto-resolved via {method}"
        elif status == STATUS_NEEDS_REVIEW:
            reason = f"Fuzzy match ({method}) below high-confidence threshold"
        elif status == STATUS_AMBIGUOUS:
            reason = "Multiple possible vendor matches"
        else:
            reason = "No vendor match found"

    normalized = normalize_vendor_name(vendor_raw) if vendor_raw else ""

    return {
        "status": status,
        "method": method,
        "raw": vendor_raw or "",
        "normalized": normalized,
        "matched_vendor_name": match_result.get("vendor_name"),
        "matched_vendor_no": match_result.get("vendor_no") or vendor_canonical,
        "score": float(score) if score else None,
        "reason": reason,
        "reviewed_override": False,
        "resolved_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# 2. Negative feedback capture
# ---------------------------------------------------------------------------

async def capture_rejection(
    doc_id: str,
    vendor_raw: str,
    proposed_vendor_id: str,
    proposed_vendor_name: str,
    proposed_method: str,
    proposed_score: float,
    corrected_vendor_id: str,
    corrected_vendor_name: str,
    actor: str = "reviewer",
) -> Dict[str, Any]:
    """Record a rejected auto-match for the negative feedback loop.

    Called when a reviewer overrides an auto-matched vendor.
    """
    db = get_db()
    normalized = normalize_vendor_name(vendor_raw) if vendor_raw else ""
    now = datetime.now(timezone.utc).isoformat()

    # Check if this pairing already has a rejection
    existing = await db.vendor_match_rejections.find_one({
        "normalized_raw": normalized,
        "proposed_vendor_id": proposed_vendor_id,
    }, {"_id": 0})

    if existing:
        # Increment rejection count
        await db.vendor_match_rejections.update_one(
            {
                "normalized_raw": normalized,
                "proposed_vendor_id": proposed_vendor_id,
            },
            {
                "$inc": {"rejection_count": 1},
                "$set": {
                    "last_rejected_at": now,
                    "last_corrected_vendor_id": corrected_vendor_id,
                    "last_corrected_vendor_name": corrected_vendor_name,
                    "last_actor": actor,
                },
                "$push": {
                    "rejection_history": {
                        "doc_id": doc_id,
                        "corrected_vendor_id": corrected_vendor_id,
                        "corrected_vendor_name": corrected_vendor_name,
                        "actor": actor,
                        "timestamp": now,
                    }
                },
            },
        )
        logger.info(
            '[VendorRejection] Reinforced rejection: raw="%s" proposed=%s (count=%d)',
            normalized, proposed_vendor_id, existing.get("rejection_count", 0) + 1,
        )
        return {**existing, "rejection_count": existing.get("rejection_count", 0) + 1}

    # Create new rejection record
    rejection = {
        "vendor_raw": vendor_raw,
        "normalized_raw": normalized,
        "proposed_vendor_id": proposed_vendor_id,
        "proposed_vendor_name": proposed_vendor_name,
        "proposed_method": proposed_method,
        "proposed_score": proposed_score,
        "corrected_vendor_id": corrected_vendor_id,
        "corrected_vendor_name": corrected_vendor_name,
        "rejection_count": 1,
        "first_rejected_at": now,
        "last_rejected_at": now,
        "last_corrected_vendor_id": corrected_vendor_id,
        "last_corrected_vendor_name": corrected_vendor_name,
        "last_actor": actor,
        "rejection_history": [{
            "doc_id": doc_id,
            "corrected_vendor_id": corrected_vendor_id,
            "corrected_vendor_name": corrected_vendor_name,
            "actor": actor,
            "timestamp": now,
        }],
    }
    await db.vendor_match_rejections.insert_one(rejection)
    rejection.pop("_id", None)

    logger.info(
        '[VendorRejection] New rejection: raw="%s" proposed=%s corrected=%s',
        normalized, proposed_vendor_id, corrected_vendor_id,
    )
    return rejection


# ---------------------------------------------------------------------------
# 3. Guardrail check — block repeat bad matches
# ---------------------------------------------------------------------------

async def check_rejection_guardrail(
    vendor_raw: str,
    proposed_vendor_id: str,
) -> Optional[Dict[str, Any]]:
    """Check if a proposed vendor match was previously rejected.

    Returns the rejection record if found, None if the match is safe.
    """
    db = get_db()
    normalized = normalize_vendor_name(vendor_raw) if vendor_raw else ""
    if not normalized or not proposed_vendor_id:
        return None

    rejection = await db.vendor_match_rejections.find_one({
        "normalized_raw": normalized,
        "proposed_vendor_id": proposed_vendor_id,
    }, {"_id": 0})

    if rejection:
        logger.info(
            '[VendorGuardrail] Blocked repeat match: raw="%s" vendor=%s (rejected %d times)',
            normalized, proposed_vendor_id, rejection.get("rejection_count", 0),
        )
    return rejection


# ---------------------------------------------------------------------------
# 4. Resolution analytics
# ---------------------------------------------------------------------------

async def get_resolution_metrics() -> Dict[str, Any]:
    """Compute vendor resolution analytics."""
    db = get_db()

    total = await db.hub_documents.count_documents({})

    # Count by resolution status
    status_pipeline = [
        {"$group": {
            "_id": "$vendor_resolution.status",
            "count": {"$sum": 1},
        }},
    ]
    status_raw = await db.hub_documents.aggregate(status_pipeline).to_list(10)
    status_counts = {r["_id"]: r["count"] for r in status_raw if r["_id"]}

    resolved = status_counts.get(STATUS_RESOLVED, 0)
    unresolved = status_counts.get(STATUS_UNRESOLVED, 0)
    ambiguous = status_counts.get(STATUS_AMBIGUOUS, 0)
    needs_review = status_counts.get(STATUS_NEEDS_REVIEW, 0)
    no_resolution = total - resolved - unresolved - ambiguous - needs_review

    resolution_rate = round((resolved / total * 100), 1) if total > 0 else 0

    # Count by match method
    method_pipeline = [
        {"$match": {"vendor_resolution.method": {"$exists": True, "$ne": None}}},
        {"$group": {
            "_id": "$vendor_resolution.method",
            "count": {"$sum": 1},
        }},
    ]
    method_raw = await db.hub_documents.aggregate(method_pipeline).to_list(20)
    by_method = {r["_id"]: r["count"] for r in method_raw if r["_id"]}

    # Fuzzy score buckets
    buckets = {"90-94": 0, "95-97": 0, "98-100": 0}
    fuzzy_pipeline = [
        {"$match": {
            "vendor_resolution.method": "fuzzy_match",
            "vendor_resolution.score": {"$exists": True, "$ne": None},
        }},
        {"$project": {"score": "$vendor_resolution.score"}},
    ]
    fuzzy_docs = await db.hub_documents.aggregate(fuzzy_pipeline).to_list(5000)
    for fd in fuzzy_docs:
        s = fd.get("score", 0)
        if s is None:
            continue
        pct = s * 100 if s <= 1 else s
        if 90 <= pct < 95:
            buckets["90-94"] += 1
        elif 95 <= pct < 98:
            buckets["95-97"] += 1
        elif pct >= 98:
            buckets["98-100"] += 1

    # Top 25 unresolved raw vendor strings
    unresolved_pipeline = [
        {"$match": {"vendor_resolution.status": STATUS_UNRESOLVED}},
        {"$group": {
            "_id": "$vendor_resolution.raw",
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 25},
    ]
    unresolved_raw = await db.hub_documents.aggregate(unresolved_pipeline).to_list(25)
    top_unresolved = [{"raw": r["_id"], "count": r["count"]} for r in unresolved_raw if r["_id"]]

    # Top 25 manually corrected vendor strings (potential alias candidates)
    corrected_pipeline = [
        {"$match": {"vendor_resolution.reviewed_override": True}},
        {"$group": {
            "_id": "$vendor_resolution.raw",
            "count": {"$sum": 1},
            "vendor_name": {"$first": "$vendor_canonical"},
            "vendor_no": {"$first": "$vendor_resolution.matched_vendor_no"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 25},
    ]
    corrected_raw = await db.hub_documents.aggregate(corrected_pipeline).to_list(25)
    top_corrected = [
        {"raw": r["_id"], "count": r["count"], "vendor_name": r.get("vendor_name"), "vendor_no": r.get("vendor_no")}
        for r in corrected_raw if r["_id"]
    ]

    # Rejection stats
    total_rejections = await db.vendor_match_rejections.count_documents({})

    return {
        "total_documents": total,
        "resolved_count": resolved,
        "unresolved_count": unresolved,
        "ambiguous_count": ambiguous,
        "needs_review_count": needs_review,
        "no_resolution_data": no_resolution,
        "resolution_rate": resolution_rate,
        "by_method": by_method,
        "fuzzy_score_buckets": buckets,
        "top_unresolved": top_unresolved,
        "top_corrected": top_corrected,
        "total_rejections": total_rejections,
    }


# ---------------------------------------------------------------------------
# 5. Get rejection history (admin)
# ---------------------------------------------------------------------------

async def get_rejections(limit: int = 50, skip: int = 0) -> List[Dict[str, Any]]:
    """Get vendor match rejection history for admin review."""
    db = get_db()
    cursor = db.vendor_match_rejections.find(
        {}, {"_id": 0}
    ).sort("last_rejected_at", -1).skip(skip).limit(limit)
    return await cursor.to_list(limit)


# ---------------------------------------------------------------------------
# 6. Ensure indexes
# ---------------------------------------------------------------------------

async def ensure_resolution_indexes():
    """Create indexes for vendor resolution collections."""
    db = get_db()
    try:
        await db.vendor_match_rejections.create_index(
            [("normalized_raw", 1), ("proposed_vendor_id", 1)],
            unique=True,
        )
        await db.vendor_match_rejections.create_index("last_rejected_at")
        await db.hub_documents.create_index("vendor_resolution.status")
        await db.hub_documents.create_index("vendor_resolution.method")
        logger.info("[VendorResolution] Indexes ensured")
    except Exception as e:
        logger.warning("[VendorResolution] Index creation note: %s", e)
