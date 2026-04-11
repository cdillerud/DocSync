"""
Auto-Escalation Intelligence Service — Learn which documents always fail automation.

Tracks patterns of repeated automation failures per vendor + doc type combination.
When a combination consistently fails (e.g., vendor X's shipping docs ALWAYS need
manual review), the system preemptively routes future docs to review without wasting
cycles on doomed automation attempts.

This saves processing time and reduces false confidence in automation.

Integration points:
  - Called by per_document_learning_service on every outcome
  - Queried by document_readiness_service before automation decision
  - Exposed via posting_patterns API for the Learning Dashboard
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger("escalation_intel")

ESCALATION_COL = "escalation_intelligence"


def _now():
    return datetime.now(timezone.utc).isoformat()


def _escalation_key(vendor_no: str, doc_type: str) -> str:
    """Build a unique key for vendor + doc_type combination."""
    return f"{vendor_no or 'unknown'}::{doc_type or 'unknown'}"


# =========================================================================
# 1. LEARN FROM OUTCOMES
# =========================================================================

async def record_automation_outcome(
    db,
    vendor_no: str,
    doc_type: str,
    outcome: str,
    doc_id: str = "",
):
    """
    Record an automation attempt outcome for a vendor + doc_type.

    outcome: "success" | "failure" | "review" | "correction"
    """
    key = _escalation_key(vendor_no, doc_type)
    is_success = outcome == "success"

    inc_ops = {"total_attempts": 1}
    if is_success:
        inc_ops["success_count"] = 1
    elif outcome == "failure":
        inc_ops["failure_count"] = 1
    elif outcome == "review":
        inc_ops["review_count"] = 1
    elif outcome == "correction":
        inc_ops["correction_count"] = 1

    await db[ESCALATION_COL].update_one(
        {"escalation_key": key},
        {
            "$inc": inc_ops,
            "$set": {
                "escalation_key": key,
                "vendor_no": vendor_no,
                "doc_type": doc_type,
                "last_outcome": outcome,
                "last_doc_id": doc_id,
                "updated_at": _now(),
            },
        },
        upsert=True,
    )

    # Recompute rates
    await _recompute_escalation(db, key)


async def _recompute_escalation(db, key: str):
    """Recompute escalation decision for a vendor+doc_type."""
    record = await db[ESCALATION_COL].find_one(
        {"escalation_key": key}, {"_id": 0}
    )
    if not record:
        return

    total = record.get("total_attempts", 0)
    successes = record.get("success_count", 0)
    failures = record.get("failure_count", 0)
    reviews = record.get("review_count", 0)
    corrections = record.get("correction_count", 0)

    if total < 3:
        decision = "insufficient_data"
        should_escalate = False
    else:
        success_rate = successes / total

        if success_rate >= 0.85:
            decision = "automate"
            should_escalate = False
        elif success_rate >= 0.60:
            decision = "monitor"
            should_escalate = False
        elif success_rate >= 0.30:
            decision = "escalate_warning"
            should_escalate = total >= 5
        else:
            decision = "always_escalate"
            should_escalate = True

    await db[ESCALATION_COL].update_one(
        {"escalation_key": key},
        {"$set": {
            "success_rate": round(successes / max(total, 1), 4),
            "failure_rate": round((failures + reviews + corrections) / max(total, 1), 4),
            "decision": decision,
            "should_escalate": should_escalate,
            "rates_updated_at": _now(),
        }},
    )


# =========================================================================
# 2. QUERY — Should this doc be pre-escalated?
# =========================================================================

async def should_pre_escalate(db, vendor_no: str, doc_type: str) -> Dict:
    """
    Check if this vendor + doc_type combination should be pre-escalated
    to manual review based on historical failure patterns.

    Returns:
      - should_escalate: bool
      - reason: str
      - success_rate: float
      - total_attempts: int
    """
    key = _escalation_key(vendor_no, doc_type)

    record = await db[ESCALATION_COL].find_one(
        {"escalation_key": key}, {"_id": 0}
    )

    if not record or record.get("decision") == "insufficient_data":
        return {
            "should_escalate": False,
            "reason": "Insufficient history for this vendor + doc type",
            "success_rate": None,
            "total_attempts": (record or {}).get("total_attempts", 0),
        }

    if record.get("should_escalate"):
        return {
            "should_escalate": True,
            "reason": (
                f"Vendor {vendor_no} + {doc_type}: {record.get('success_rate', 0):.0%} success rate "
                f"over {record.get('total_attempts', 0)} attempts — pre-routing to review"
            ),
            "success_rate": record.get("success_rate", 0),
            "total_attempts": record.get("total_attempts", 0),
            "decision": record.get("decision", ""),
        }

    return {
        "should_escalate": False,
        "reason": f"Vendor {vendor_no} + {doc_type}: {record.get('success_rate', 0):.0%} success rate — OK",
        "success_rate": record.get("success_rate", 0),
        "total_attempts": record.get("total_attempts", 0),
        "decision": record.get("decision", ""),
    }


# =========================================================================
# 3. SUMMARY API
# =========================================================================

async def get_escalation_summary(db) -> Dict:
    """Summary of escalation intelligence."""
    total = await db[ESCALATION_COL].count_documents({})
    escalated = await db[ESCALATION_COL].count_documents({"should_escalate": True})
    automate = await db[ESCALATION_COL].count_documents({"decision": "automate"})
    monitor = await db[ESCALATION_COL].count_documents({"decision": "monitor"})

    # Top escalated combos
    top_escalated = await db[ESCALATION_COL].find(
        {"should_escalate": True},
        {"_id": 0}
    ).sort("failure_rate", -1).limit(10).to_list(10)

    # Top automated combos
    top_automated = await db[ESCALATION_COL].find(
        {"decision": "automate"},
        {"_id": 0, "vendor_no": 1, "doc_type": 1, "success_rate": 1, "total_attempts": 1}
    ).sort("success_rate", -1).limit(10).to_list(10)

    return {
        "total_combinations_tracked": total,
        "always_escalate": escalated,
        "fully_automated": automate,
        "monitoring": monitor,
        "top_escalated": top_escalated,
        "top_automated": top_automated,
        "generated_at": _now(),
    }


# =========================================================================
# 4. RECALIBRATE — Rebuild escalation data from actual document outcomes
# =========================================================================

async def recalibrate_escalation_intelligence(db, limit: int = 5000) -> Dict:
    """
    Rebuild escalation intelligence from actual document outcomes.
    Clears inflated counts from repeated re-evaluations and recalculates
    from each document's CURRENT state (counted once per doc, not per cycle).

    Returns: {combos_recalibrated, combos_escalated, combos_automated}
    """
    # Step 1: Aggregate actual per-doc RESOLVED outcomes grouped by vendor+doc_type
    # IMPORTANT: Only count docs with definitive outcomes (completed, posted, or explicitly failed)
    # Docs in intermediate states (NeedsReview, ReadyForPost, Captured) are PENDING, not failures
    pipeline = [
        {"$match": {
            "is_duplicate": {"$ne": True},
            "status": {"$nin": ["batch_parent"]},
            "$or": [
                {"bc_vendor_number": {"$exists": True, "$ne": ""}},
                {"vendor_no": {"$exists": True, "$ne": ""}},
            ],
        }},
        {"$project": {
            "_id": 0,
            "vendor_no": {"$ifNull": ["$bc_vendor_number", "$vendor_no"]},
            "doc_type": {"$ifNull": ["$document_type", "$suggested_job_type"]},
            "status": 1,
            "automation_decision": 1,
            "auto_cleared": 1,
            "readiness_status": "$readiness.status",
        }},
        {"$match": {"vendor_no": {"$ne": None}, "doc_type": {"$ne": None}}},
        {"$group": {
            "_id": {"vendor_no": "$vendor_no", "doc_type": "$doc_type"},
            "total": {"$sum": 1},
            "completed": {"$sum": {"$cond": [
                {"$in": ["$status", ["Completed", "completed", "Posted", "posted"]]},
                1, 0
            ]}},
            "auto_processed": {"$sum": {"$cond": [
                {"$or": [
                    {"$in": ["$automation_decision", ["auto_filed", "auto_linked", "auto_approved", "auto_drafted"]]},
                    {"$eq": ["$auto_cleared", True]},
                ]},
                1, 0
            ]}},
            "needs_review": {"$sum": {"$cond": [
                {"$eq": ["$status", "NeedsReview"]},
                1, 0
            ]}},
        }},
        {"$match": {"total": {"$gte": 2}}},
    ]

    combos = await db.hub_documents.aggregate(pipeline).to_list(limit)

    recalibrated = 0
    for combo in combos:
        vendor_no = combo["_id"]["vendor_no"]
        doc_type = combo["_id"]["doc_type"]
        key = _escalation_key(vendor_no, doc_type)

        completed = combo["completed"]
        auto_processed = combo["auto_processed"]

        # Successes = completed/posted OR auto-processed (take max to avoid double-counting)
        successes = max(completed, auto_processed)
        needs_review = combo["needs_review"]

        # Only count RESOLVED outcomes for escalation calculation
        # resolved = successes (made it through) + explicit_review (stuck in review)
        resolved_total = successes + needs_review
        if resolved_total < 2:
            continue  # Not enough resolved data to make a decision

        # The success rate is: successes / resolved_total
        # NOT total_docs, because pending docs aren't failures
        # Failure = NeedsReview docs that never made it through (not pending, but genuinely stuck)
        failures = needs_review  # These are the docs that couldn't be auto-processed

        await db[ESCALATION_COL].update_one(
            {"escalation_key": key},
            {"$set": {
                "escalation_key": key,
                "vendor_no": vendor_no,
                "doc_type": doc_type,
                "total_attempts": resolved_total,
                "success_count": successes,
                "failure_count": 0,  # No explicit failures, just reviews
                "review_count": failures,
                "correction_count": 0,
                "recalibrated_at": _now(),
                "updated_at": _now(),
            }},
            upsert=True,
        )
        await _recompute_escalation(db, key)
        recalibrated += 1

    # Get post-recalibration summary
    escalated = await db[ESCALATION_COL].count_documents({"should_escalate": True})
    automated = await db[ESCALATION_COL].count_documents({"decision": "automate"})

    logger.info(
        "[Escalation] Recalibrated %d combos from actual data. Escalated: %d, Automated: %d",
        recalibrated, escalated, automated,
    )

    return {
        "combos_recalibrated": recalibrated,
        "combos_escalated": escalated,
        "combos_automated": automated,
    }
