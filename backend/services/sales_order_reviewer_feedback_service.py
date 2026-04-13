"""
GPI Document Hub — Sales Order Reviewer Feedback Service

Captures human reviewer feedback on advisory readiness reviews.
Stores in `so_reviewer_feedback` collection for analysis and tuning.

FEEDBACK CAPTURE ONLY: Never alters posting, routing, or validation.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

VALID_ASSESSMENTS = {
    "correct",
    "partially_correct",
    "incorrect",
    "helpful_but_not_decisive",
    "not_helpful",
}

VALID_DECISIONS = {
    "ready",
    "needs_review",
    "suspicious",
    "incomplete",
    "other",
}

VALID_DISAGREED_FIELDS = {
    "ship_to",
    "amount_range",
    "item_match",
    "uom",
    "po_pattern",
    "customer_profile_assumption",
    "line_count",
    "readiness_status",
    "confidence",
    "other",
}


async def submit_feedback(
    db,
    document_id: str,
    reviewer_user_id: str,
    reviewer_assessment: str,
    final_human_decision: Optional[str] = None,
    disagreed_fields: Optional[List[str]] = None,
    notes: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Record reviewer feedback on a sales order advisory review.

    Returns the stored feedback record (without _id).
    """
    now = datetime.now(timezone.utc).isoformat()

    if reviewer_assessment not in VALID_ASSESSMENTS:
        return {"error": f"Invalid assessment: {reviewer_assessment}. Must be one of {sorted(VALID_ASSESSMENTS)}"}

    if final_human_decision and final_human_decision not in VALID_DECISIONS:
        return {"error": f"Invalid decision: {final_human_decision}. Must be one of {sorted(VALID_DECISIONS)}"}

    # Load the document to snapshot the review state
    doc = await db.hub_documents.find_one({"id": document_id}, {"_id": 0,
        "id": 1, "doc_type": 1, "status": 1, "workflow_status": 1,
        "matched_customer_no": 1, "customer_no": 1, "customer_extracted": 1,
        "so_readiness_review": 1})

    if not doc:
        return {"error": "Document not found"}

    review = doc.get("so_readiness_review") or {}
    customer_no = doc.get("matched_customer_no") or doc.get("customer_no") or ""

    feedback = {
        "document_id": document_id,
        "customer_no": customer_no,
        "customer_name": doc.get("customer_extracted", ""),
        "reviewer_user_id": reviewer_user_id,
        "reviewer_assessment": reviewer_assessment,
        "final_human_decision": final_human_decision,
        "disagreed_fields": disagreed_fields or [],
        "notes": notes or "",
        "timestamp": now,
        # Snapshot of what was reviewed
        "linked_review": {
            "readiness_status": review.get("readiness_status"),
            "confidence": review.get("confidence"),
            "model_used": review.get("model_used"),
            "reviewed_at": review.get("reviewed_at"),
            "profile_id": review.get("customer_profile_id"),
            "profile_version": review.get("customer_profile_version"),
        },
        "doc_status_at_feedback": doc.get("status"),
        "doc_type": doc.get("doc_type"),
    }

    await db.so_reviewer_feedback.insert_one(feedback)
    feedback.pop("_id", None)

    # Also store latest feedback summary on the document itself
    await db.hub_documents.update_one(
        {"id": document_id},
        {"$set": {
            "so_review_feedback_latest": {
                "assessment": reviewer_assessment,
                "decision": final_human_decision,
                "reviewer": reviewer_user_id,
                "timestamp": now,
            }
        }}
    )

    logger.info(
        "[SO-Feedback] doc=%s reviewer=%s assessment=%s decision=%s review_status=%s confidence=%s",
        document_id[:8], reviewer_user_id, reviewer_assessment,
        final_human_decision, review.get("readiness_status"), review.get("confidence"),
    )

    return feedback


async def get_feedback_for_document(
    db,
    document_id: str,
) -> List[Dict[str, Any]]:
    """Get all feedback records for a document, most recent first."""
    cursor = db.so_reviewer_feedback.find(
        {"document_id": document_id}, {"_id": 0}
    ).sort("timestamp", -1)
    return await cursor.to_list(50)
