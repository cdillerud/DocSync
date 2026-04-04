"""
Duplicate Intelligence Service — Learn to eliminate false-positive duplicate flags.

When a document is flagged as `possible_duplicate` during ingestion, this is a
fuzzy match (same vendor + same invoice_number_clean). Many of these are FALSE
POSITIVES:
  - Re-ingested documents after field corrections
  - Multi-page document parts with overlapping references
  - Same vendor, similar invoice numbers for different POs
  - Intentionally resubmitted after rejection

This service:
  1. Tracks every duplicate flag resolution (confirmed duplicate vs cleared)
  2. Computes per-vendor false-positive rates for duplicate detection
  3. Provides a "safe to clear" recommendation for the readiness engine
  4. Auto-clears duplicate flags when vendor history proves they are unreliable
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger("duplicate_intelligence")

DUPLICATE_INTEL_COL = "duplicate_intelligence"
DUPLICATE_OUTCOMES_COL = "duplicate_outcomes"


def _now():
    return datetime.now(timezone.utc).isoformat()


# =========================================================================
# 1. RECORD DUPLICATE OUTCOMES
# =========================================================================

async def record_duplicate_outcome(
    db,
    doc_id: str,
    vendor_no: str,
    was_flagged_duplicate: bool,
    actual_outcome: str,
    resolution_source: str = "system",
):
    """
    Record the outcome of a duplicate flag.

    actual_outcome:
      - "confirmed_duplicate"  — Human or BC confirmed it IS a duplicate
      - "false_positive"       — Human cleared the flag, it was NOT a duplicate
      - "auto_cleared"         — System cleared via BC validation (dup check passed)
      - "different_po"         — Same invoice # but different PO (not a real dup)

    resolution_source:
      - "human_override"
      - "bc_validation"
      - "auto_clear"
      - "system"
    """
    record = {
        "doc_id": doc_id,
        "vendor_no": vendor_no,
        "was_flagged": was_flagged_duplicate,
        "outcome": actual_outcome,
        "resolution_source": resolution_source,
        "is_false_positive": actual_outcome in ("false_positive", "auto_cleared", "different_po"),
        "recorded_at": _now(),
    }

    await db[DUPLICATE_OUTCOMES_COL].update_one(
        {"doc_id": doc_id},
        {"$set": record},
        upsert=True,
    )

    # Update vendor-level duplicate intelligence
    await _update_vendor_duplicate_intel(db, vendor_no)

    logger.info(
        "[DupIntel] doc=%s vendor=%s outcome=%s source=%s",
        doc_id[:8], vendor_no, actual_outcome, resolution_source,
    )
    return record


# =========================================================================
# 2. VENDOR-LEVEL DUPLICATE INTELLIGENCE
# =========================================================================

async def _update_vendor_duplicate_intel(db, vendor_no: str):
    """Recompute vendor-level duplicate intelligence from all outcomes."""
    if not vendor_no:
        return

    pipeline = [
        {"$match": {"vendor_no": vendor_no, "was_flagged": True}},
        {"$group": {
            "_id": "$vendor_no",
            "total_flags": {"$sum": 1},
            "false_positives": {"$sum": {"$cond": ["$is_false_positive", 1, 0]}},
            "confirmed_duplicates": {
                "$sum": {"$cond": [{"$eq": ["$outcome", "confirmed_duplicate"]}, 1, 0]}
            },
        }},
    ]

    results = await db[DUPLICATE_OUTCOMES_COL].aggregate(pipeline).to_list(1)
    if not results:
        return

    r = results[0]
    total = r.get("total_flags", 0)
    false_pos = r.get("false_positives", 0)
    confirmed = r.get("confirmed_duplicates", 0)

    false_positive_rate = round(false_pos / max(total, 1), 4)

    # Determine trust level
    if total < 3:
        trust_level = "insufficient_data"
        safe_to_auto_clear = False
    elif false_positive_rate >= 0.80:
        trust_level = "unreliable"  # 80%+ false positives — don't trust dup flags
        safe_to_auto_clear = True
    elif false_positive_rate >= 0.50:
        trust_level = "low_confidence"  # More wrong than right
        safe_to_auto_clear = total >= 5  # Only if we have enough data
    elif false_positive_rate >= 0.20:
        trust_level = "moderate"
        safe_to_auto_clear = False
    else:
        trust_level = "reliable"  # Low false-positive rate — trust the flags
        safe_to_auto_clear = False

    intel = {
        "vendor_no": vendor_no,
        "total_flags": total,
        "false_positives": false_pos,
        "confirmed_duplicates": confirmed,
        "false_positive_rate": false_positive_rate,
        "trust_level": trust_level,
        "safe_to_auto_clear": safe_to_auto_clear,
        "updated_at": _now(),
    }

    await db[DUPLICATE_INTEL_COL].update_one(
        {"vendor_no": vendor_no},
        {"$set": intel},
        upsert=True,
    )


# =========================================================================
# 3. READINESS INTEGRATION — Should this duplicate flag be trusted?
# =========================================================================

async def evaluate_duplicate_flag(db, doc: Dict) -> Dict:
    """
    Evaluate whether a document's duplicate flag should be trusted.

    Returns:
      - should_block: True if the duplicate flag should block processing
      - should_auto_clear: True if the system should auto-clear the flag
      - reason: Human-readable explanation
      - confidence: How confident we are in this recommendation
    """
    vendor_no = (
        doc.get("bc_vendor_number")
        or doc.get("vendor_no")
        or doc.get("matched_vendor_no")
        or ""
    )

    # If no vendor, we can't look up history — trust the flag
    if not vendor_no:
        return {
            "should_block": True,
            "should_auto_clear": False,
            "reason": "No vendor identified — cannot evaluate duplicate history",
            "confidence": 0.5,
        }

    intel = await db[DUPLICATE_INTEL_COL].find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )

    if not intel or intel.get("trust_level") == "insufficient_data":
        return {
            "should_block": True,
            "should_auto_clear": False,
            "reason": f"Vendor {vendor_no}: insufficient duplicate history (need 3+ outcomes)",
            "confidence": 0.3,
        }

    fpr = intel.get("false_positive_rate", 0)
    total = intel.get("total_flags", 0)
    trust = intel.get("trust_level", "")

    if intel.get("safe_to_auto_clear"):
        return {
            "should_block": False,
            "should_auto_clear": True,
            "reason": (
                f"Vendor {vendor_no}: {fpr:.0%} false-positive rate over {total} flags — "
                f"duplicate detection is {trust}. Safe to auto-clear."
            ),
            "confidence": min(0.95, 0.5 + (total / 20) * 0.45),
            "vendor_intel": {
                "false_positive_rate": fpr,
                "total_flags": total,
                "trust_level": trust,
            },
        }

    if trust == "moderate":
        return {
            "should_block": True,
            "should_auto_clear": False,
            "reason": (
                f"Vendor {vendor_no}: {fpr:.0%} false-positive rate — "
                f"moderate reliability. Keeping flag for human review."
            ),
            "confidence": 0.6,
        }

    # Reliable — trust the flag
    return {
        "should_block": True,
        "should_auto_clear": False,
        "reason": (
            f"Vendor {vendor_no}: {fpr:.0%} false-positive rate over {total} flags — "
            f"duplicate detection is reliable."
        ),
        "confidence": 0.8,
    }


# =========================================================================
# 4. AUTO-LEARN FROM DOCUMENT LIFECYCLE
# =========================================================================

async def learn_from_readiness_correction(db, doc_id: str, doc: Dict):
    """
    Called when readiness re-evaluation clears a duplicate_risk signal.
    This means BC validation proved it's NOT a duplicate.
    """
    vendor_no = (
        doc.get("bc_vendor_number")
        or doc.get("vendor_no")
        or doc.get("matched_vendor_no")
        or ""
    )

    was_flagged = bool(doc.get("possible_duplicate") or doc.get("is_duplicate"))
    if was_flagged:
        await record_duplicate_outcome(
            db,
            doc_id=doc_id,
            vendor_no=vendor_no,
            was_flagged_duplicate=True,
            actual_outcome="auto_cleared",
            resolution_source="bc_validation",
        )


async def learn_from_human_override(db, doc_id: str, doc: Dict, action: str):
    """
    Called when a human approves/clears a document that was flagged as duplicate.
    action: "approved" or "confirmed_duplicate"
    """
    vendor_no = (
        doc.get("bc_vendor_number")
        or doc.get("vendor_no")
        or doc.get("matched_vendor_no")
        or ""
    )

    was_flagged = bool(doc.get("possible_duplicate") or doc.get("is_duplicate"))
    if not was_flagged:
        return

    if action == "approved":
        outcome = "false_positive"
    elif action == "confirmed_duplicate":
        outcome = "confirmed_duplicate"
    else:
        outcome = "false_positive"

    await record_duplicate_outcome(
        db,
        doc_id=doc_id,
        vendor_no=vendor_no,
        was_flagged_duplicate=True,
        actual_outcome=outcome,
        resolution_source="human_override",
    )


# =========================================================================
# 5. BATCH INTELLIGENCE — Auto-clear safe vendors
# =========================================================================

async def batch_auto_clear_safe_duplicates(db, limit: int = 100) -> Dict:
    """
    Find documents blocked by duplicate_risk where the vendor's duplicate
    detection is known to be unreliable, and auto-clear them.
    """
    # Find vendors with safe-to-clear intelligence
    safe_vendors = await db[DUPLICATE_INTEL_COL].find(
        {"safe_to_auto_clear": True},
        {"_id": 0, "vendor_no": 1}
    ).to_list(500)

    safe_vendor_nos = [v["vendor_no"] for v in safe_vendors if v.get("vendor_no")]
    if not safe_vendor_nos:
        return {"cleared": 0, "message": "No vendors with safe-to-clear intelligence"}

    # Find blocked documents from these vendors
    query = {
        "possible_duplicate": True,
        "status": {"$nin": ["Completed", "Posted", "Archived", "Deleted"]},
        "$or": [
            {"bc_vendor_number": {"$in": safe_vendor_nos}},
            {"vendor_no": {"$in": safe_vendor_nos}},
            {"matched_vendor_no": {"$in": safe_vendor_nos}},
        ],
    }

    docs = await db.hub_documents.find(
        query, {"_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_no": 1, "matched_vendor_no": 1}
    ).limit(limit).to_list(limit)

    cleared = 0
    for d in docs:
        doc_id = d.get("id", "")
        vendor_no = d.get("bc_vendor_number") or d.get("vendor_no") or d.get("matched_vendor_no") or ""

        try:
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "possible_duplicate": False,
                    "duplicate_auto_cleared": True,
                    "duplicate_cleared_reason": f"Vendor {vendor_no} has unreliable duplicate detection",
                    "duplicate_cleared_at": _now(),
                }},
            )

            await record_duplicate_outcome(
                db,
                doc_id=doc_id,
                vendor_no=vendor_no,
                was_flagged_duplicate=True,
                actual_outcome="auto_cleared",
                resolution_source="batch_intelligence",
            )

            cleared += 1
        except Exception as e:
            logger.warning("[DupIntel] Failed to clear %s: %s", doc_id[:8], e)

    logger.info("[DupIntel] Batch auto-clear: %d/%d docs cleared", cleared, len(docs))
    return {
        "safe_vendors": len(safe_vendor_nos),
        "candidates_found": len(docs),
        "cleared": cleared,
    }


# =========================================================================
# 6. QUERY APIs
# =========================================================================

async def get_duplicate_intelligence_summary(db) -> Dict:
    """Summary of duplicate intelligence across all vendors."""
    total_outcomes = await db[DUPLICATE_OUTCOMES_COL].count_documents({})
    total_vendors = await db[DUPLICATE_INTEL_COL].count_documents({})

    # Trust level distribution
    trust_pipe = [
        {"$group": {"_id": "$trust_level", "count": {"$sum": 1}}},
    ]
    trust_dist = {
        r["_id"]: r["count"]
        for r in await db[DUPLICATE_INTEL_COL].aggregate(trust_pipe).to_list(10)
    }

    # Global false positive rate
    global_pipe = [
        {"$match": {"was_flagged": True}},
        {"$group": {
            "_id": None,
            "total": {"$sum": 1},
            "false_positives": {"$sum": {"$cond": ["$is_false_positive", 1, 0]}},
        }},
    ]
    global_stats = await db[DUPLICATE_OUTCOMES_COL].aggregate(global_pipe).to_list(1)
    global_fpr = 0
    global_total = 0
    if global_stats:
        g = global_stats[0]
        global_total = g.get("total", 0)
        global_fpr = round(g.get("false_positives", 0) / max(global_total, 1), 4)

    # Top problem vendors (highest false positive rates)
    problem_vendors = await db[DUPLICATE_INTEL_COL].find(
        {"total_flags": {"$gte": 3}},
        {"_id": 0}
    ).sort("false_positive_rate", -1).limit(10).to_list(10)

    # Safe-to-clear vendors
    safe_count = await db[DUPLICATE_INTEL_COL].count_documents({"safe_to_auto_clear": True})

    # Currently blocked by duplicate
    blocked_count = await db.hub_documents.count_documents({
        "possible_duplicate": True,
        "status": {"$nin": ["Completed", "Posted", "Archived", "Deleted"]},
    })

    return {
        "total_outcomes_tracked": total_outcomes,
        "vendors_with_intel": total_vendors,
        "trust_distribution": trust_dist,
        "global_false_positive_rate": global_fpr,
        "global_flags_evaluated": global_total,
        "problem_vendors": problem_vendors,
        "safe_to_clear_vendors": safe_count,
        "currently_blocked_by_duplicate": blocked_count,
        "generated_at": _now(),
    }
