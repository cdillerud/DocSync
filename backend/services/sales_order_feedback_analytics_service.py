"""
GPI Document Hub — Sales Order Feedback Analytics Service

Aggregates human reviewer feedback on SO advisory reviews for
admin-level performance visibility.

ANALYTICS ONLY: Never changes workflow or posting decisions.
"""

import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def get_feedback_summary(
    db,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    customer_no: Optional[str] = None,
    reviewer: Optional[str] = None,
    model: Optional[str] = None,
    readiness_status: Optional[str] = None,
    assessment: Optional[str] = None,
    decision: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute aggregate metrics from so_reviewer_feedback collection.
    All parameters are optional filters.
    """
    match = _build_match(date_from, date_to, customer_no, reviewer,
                         model, readiness_status, assessment, decision)

    pipeline = [
        {"$match": match},
        {"$facet": {
            "assessment_dist": [
                {"$group": {"_id": "$reviewer_assessment", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ],
            "decision_dist": [
                {"$group": {"_id": "$final_human_decision", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ],
            "confidence_by_assessment": [
                {"$group": {
                    "_id": "$reviewer_assessment",
                    "avg_confidence": {"$avg": "$linked_review.confidence"},
                    "count": {"$sum": 1},
                }},
                {"$sort": {"count": -1}},
            ],
            "by_model": [
                {"$group": {
                    "_id": "$linked_review.model_used",
                    "total": {"$sum": 1},
                    "correct": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "correct"]}, 1, 0]}},
                    "incorrect": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "incorrect"]}, 1, 0]}},
                }},
                {"$sort": {"total": -1}},
            ],
            "by_customer": [
                {"$group": {
                    "_id": {"no": "$customer_no", "name": "$customer_name"},
                    "total": {"$sum": 1},
                    "correct": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "correct"]}, 1, 0]}},
                    "incorrect": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "incorrect"]}, 1, 0]}},
                }},
                {"$sort": {"total": -1}},
                {"$limit": 20},
            ],
            "by_reviewer": [
                {"$group": {
                    "_id": "$reviewer_user_id",
                    "total": {"$sum": 1},
                    "correct": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "correct"]}, 1, 0]}},
                    "incorrect": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "incorrect"]}, 1, 0]}},
                }},
                {"$sort": {"total": -1}},
            ],
            "disagreed_fields": [
                {"$unwind": "$disagreed_fields"},
                {"$group": {"_id": "$disagreed_fields", "count": {"$sum": 1}}},
                {"$sort": {"count": -1}},
            ],
            "totals": [
                {"$group": {
                    "_id": None,
                    "total": {"$sum": 1},
                    "correct": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "correct"]}, 1, 0]}},
                    "partially_correct": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "partially_correct"]}, 1, 0]}},
                    "incorrect": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "incorrect"]}, 1, 0]}},
                    "helpful": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "helpful_but_not_decisive"]}, 1, 0]}},
                    "not_helpful": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "not_helpful"]}, 1, 0]}},
                    "avg_confidence": {"$avg": "$linked_review.confidence"},
                }},
            ],
        }},
    ]

    results = await db.so_reviewer_feedback.aggregate(pipeline).to_list(1)
    if not results:
        return {"total": 0, "message": "No feedback records found"}

    facets = results[0]
    totals = facets["totals"][0] if facets["totals"] else {}
    total = totals.get("total", 0)

    def pct(n):
        return round(n / max(total, 1) * 100, 1)

    # Disagreed field combos — run a separate lightweight aggregation
    combos = await _get_disagreed_combos(db, match)

    return {
        "total_feedback": total,
        "rates": {
            "agreement": pct(totals.get("correct", 0)),
            "partial_agreement": pct(totals.get("partially_correct", 0)),
            "incorrect": pct(totals.get("incorrect", 0)),
            "helpful": pct(totals.get("helpful", 0)),
            "not_helpful": pct(totals.get("not_helpful", 0)),
        },
        "avg_model_confidence": round(totals.get("avg_confidence", 0) or 0, 4),
        "assessment_distribution": {r["_id"]: r["count"] for r in facets["assessment_dist"]},
        "decision_distribution": {(r["_id"] or "none"): r["count"] for r in facets["decision_dist"]},
        "confidence_by_assessment": {
            r["_id"]: {"avg": round(r["avg_confidence"] or 0, 4), "count": r["count"]}
            for r in facets["confidence_by_assessment"]
        },
        "by_model": [
            {"model": r["_id"] or "unknown", "total": r["total"],
             "agreement_pct": round(r["correct"] / max(r["total"], 1) * 100, 1)}
            for r in facets["by_model"]
        ],
        "by_customer": [
            {"customer_no": r["_id"]["no"], "customer_name": r["_id"]["name"],
             "total": r["total"],
             "agreement_pct": round(r["correct"] / max(r["total"], 1) * 100, 1)}
            for r in facets["by_customer"]
        ],
        "by_reviewer": [
            {"reviewer": r["_id"], "total": r["total"],
             "agreement_pct": round(r["correct"] / max(r["total"], 1) * 100, 1)}
            for r in facets["by_reviewer"]
        ],
        "top_disagreed_fields": [
            {"field": r["_id"], "count": r["count"]}
            for r in facets["disagreed_fields"][:10]
        ],
        "top_disagreed_combos": combos,
        "filters_applied": {k: v for k, v in {
            "date_from": date_from, "date_to": date_to,
            "customer_no": customer_no, "reviewer": reviewer,
            "model": model, "readiness_status": readiness_status,
            "assessment": assessment, "decision": decision,
        }.items() if v},
    }


async def get_feedback_details(
    db,
    limit: int = 100,
    skip: int = 0,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    customer_no: Optional[str] = None,
    reviewer: Optional[str] = None,
    assessment: Optional[str] = None,
) -> Dict[str, Any]:
    """Return individual feedback records with filters."""
    match = _build_match(date_from, date_to, customer_no, reviewer,
                         assessment=assessment)

    total = await db.so_reviewer_feedback.count_documents(match)
    cursor = db.so_reviewer_feedback.find(
        match, {"_id": 0}
    ).sort("timestamp", -1).skip(skip).limit(limit)
    records = await cursor.to_list(limit)

    return {"total": total, "showing": len(records), "skip": skip, "records": records}


async def get_feedback_by_customer(
    db,
    limit: int = 30,
) -> List[Dict[str, Any]]:
    """Per-customer feedback summary."""
    pipeline = [
        {"$group": {
            "_id": {"no": "$customer_no", "name": "$customer_name"},
            "total": {"$sum": 1},
            "correct": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "correct"]}, 1, 0]}},
            "partially_correct": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "partially_correct"]}, 1, 0]}},
            "incorrect": {"$sum": {"$cond": [{"$eq": ["$reviewer_assessment", "incorrect"]}, 1, 0]}},
            "avg_confidence": {"$avg": "$linked_review.confidence"},
        }},
        {"$sort": {"total": -1}},
        {"$limit": limit},
    ]
    results = await db.so_reviewer_feedback.aggregate(pipeline).to_list(limit)
    return [
        {
            "customer_no": r["_id"]["no"],
            "customer_name": r["_id"]["name"],
            "total": r["total"],
            "correct": r["correct"],
            "partially_correct": r["partially_correct"],
            "incorrect": r["incorrect"],
            "agreement_pct": round(r["correct"] / max(r["total"], 1) * 100, 1),
            "avg_confidence": round(r["avg_confidence"] or 0, 4),
        }
        for r in results
    ]


# =============================================================================
# Helpers
# =============================================================================

def _build_match(
    date_from=None, date_to=None, customer_no=None, reviewer=None,
    model=None, readiness_status=None, assessment=None, decision=None,
) -> Dict[str, Any]:
    match: Dict[str, Any] = {}
    if date_from or date_to:
        ts_filter: Dict[str, Any] = {}
        if date_from:
            ts_filter["$gte"] = date_from
        if date_to:
            ts_filter["$lte"] = date_to
        match["timestamp"] = ts_filter
    if customer_no:
        match["customer_no"] = customer_no
    if reviewer:
        match["reviewer_user_id"] = reviewer
    if model:
        match["linked_review.model_used"] = model
    if readiness_status:
        match["linked_review.readiness_status"] = readiness_status
    if assessment:
        match["reviewer_assessment"] = assessment
    if decision:
        match["final_human_decision"] = decision
    return match


async def _get_disagreed_combos(db, match: Dict, limit: int = 10) -> List[Dict]:
    """Find most common combinations of disagreed fields."""
    pipeline = [
        {"$match": {**match, "disagreed_fields.0": {"$exists": True}}},
        {"$project": {"combo": {
            "$reduce": {
                "input": {"$sortArray": {"input": "$disagreed_fields", "sortBy": 1}},
                "initialValue": "",
                "in": {"$cond": [
                    {"$eq": ["$$value", ""]},
                    "$$this",
                    {"$concat": ["$$value", " + ", "$$this"]},
                ]},
            }
        }}},
        {"$group": {"_id": "$combo", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": limit},
    ]
    try:
        results = await db.so_reviewer_feedback.aggregate(pipeline).to_list(limit)
        return [{"combo": r["_id"], "count": r["count"]} for r in results]
    except Exception:
        return []
