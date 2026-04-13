"""
GPI Document Hub — AP Invoice Reviewer Feedback Service

Reuses the generic feedback-capture pattern for AP vendor advisory.
Stores in `ap_reviewer_feedback` collection.

FEEDBACK CAPTURE ONLY: Never alters posting or routing.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

VALID_ASSESSMENTS = {"correct", "partially_correct", "incorrect", "helpful_but_not_decisive", "not_helpful"}
VALID_DECISIONS = {"ready", "needs_review", "suspicious", "incomplete", "other"}


async def submit_ap_feedback(
    db, document_id: str, reviewer_user_id: str,
    reviewer_assessment: str,
    final_human_decision: Optional[str] = None,
    disagreed_fields: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    if reviewer_assessment not in VALID_ASSESSMENTS:
        return {"error": f"Invalid assessment: {reviewer_assessment}"}

    doc = await db.hub_documents.find_one({"id": document_id}, {
        "_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_canonical": 1,
        "vendor_raw": 1, "ap_advisory_review": 1,
    })
    if not doc:
        return {"error": "Document not found"}

    review = doc.get("ap_advisory_review") or {}
    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_canonical") or ""
    now = datetime.now(timezone.utc).isoformat()

    feedback = {
        "document_id": document_id,
        "vendor_no": vendor_no,
        "vendor_name": doc.get("vendor_raw", ""),
        "reviewer_user_id": reviewer_user_id,
        "reviewer_assessment": reviewer_assessment,
        "final_human_decision": final_human_decision,
        "disagreed_fields": disagreed_fields or [],
        "notes": notes or "",
        "timestamp": now,
        "linked_review": {
            "readiness_status": review.get("readiness_status"),
            "confidence": review.get("confidence"),
            "model_used": review.get("model_used"),
            "profile_state": review.get("profile_state"),
            "vendor_profile_id": review.get("vendor_profile_id"),
        },
    }

    await db.ap_reviewer_feedback.insert_one(feedback)
    feedback.pop("_id", None)

    await db.hub_documents.update_one({"id": document_id}, {"$set": {
        "ap_review_feedback_latest": {
            "assessment": reviewer_assessment,
            "decision": final_human_decision,
            "reviewer": reviewer_user_id,
            "timestamp": now,
        }
    }})

    logger.info("[AP-Feedback] doc=%s vendor=%s assessment=%s", document_id[:8], vendor_no, reviewer_assessment)
    return feedback


async def get_ap_feedback(db, document_id: str) -> List[Dict]:
    cursor = db.ap_reviewer_feedback.find(
        {"document_id": document_id}, {"_id": 0}
    ).sort("timestamp", -1)
    return await cursor.to_list(50)


async def get_ap_feedback_summary(db) -> Dict[str, Any]:
    """Basic analytics — agreement rates."""
    pipeline = [
        {"$facet": {
            "totals": [
                {"$group": {
                    "_id": None, "total": {"$sum": 1},
                    "correct": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "correct"]}, 1, 0]}},
                    "incorrect": {"$sum": {"$cond": [{"$in": ["$reviewer_assessment", ["incorrect", "not_helpful"]]}, 1, 0]}},
                }},
            ],
            "by_vendor": [
                {"$group": {"_id": "$vendor_no", "total": {"$sum": 1},
                             "correct": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "correct"]}, 1, 0]}}}},
                {"$sort": {"total": -1}}, {"$limit": 20},
            ],
        }}
    ]
    results = await db.ap_reviewer_feedback.aggregate(pipeline).to_list(1)
    if not results:
        return {"total": 0}

    f = results[0]
    totals = f["totals"][0] if f["totals"] else {}
    total = totals.get("total", 0)

    return {
        "total_feedback": total,
        "agreement_rate": round(totals.get("correct", 0) / max(total, 1) * 100, 1),
        "incorrect_rate": round(totals.get("incorrect", 0) / max(total, 1) * 100, 1),
        "top_vendors": [
            {"vendor_no": v["_id"], "total": v["total"],
             "agreement_pct": round(v["correct"] / max(v["total"], 1) * 100, 1)}
            for v in f["by_vendor"]
        ],
    }
