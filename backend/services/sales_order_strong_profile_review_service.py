"""
GPI Document Hub — Strong-Profile Validation Review Service

Validates whether strong-profile tuning improved reviewer agreement
and reduced false positives for mature-customer scenarios.

ANALYSIS ONLY: Never changes workflow, severity weights, or prompts.
"""

import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Timestamp marking when strong-profile tuning was deployed
STRONG_PROFILE_TUNING_CUTOFF = "2026-04-13T01:30:00Z"


async def run_strong_profile_review(
    db,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    customer_no: Optional[str] = None,
    reviewer: Optional[str] = None,
    model: Optional[str] = None,
    readiness_status: Optional[str] = None,
    disagreement_field: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare strong-profile outcomes pre vs post tuning."""

    # Fetch all feedback where the linked review had a strong profile
    match: Dict[str, Any] = {}
    if date_from or date_to:
        ts: Dict[str, Any] = {}
        if date_from:
            ts["$gte"] = date_from
        if date_to:
            ts["$lte"] = date_to
        match["timestamp"] = ts
    if customer_no:
        match["customer_no"] = customer_no
    if reviewer:
        match["reviewer_user_id"] = reviewer
    if model:
        match["linked_review.model_used"] = model
    if readiness_status:
        match["linked_review.readiness_status"] = readiness_status

    all_feedback = await db.so_reviewer_feedback.find(match, {"_id": 0}).to_list(5000)
    if not all_feedback:
        return {"total_feedback": 0, "message": "No feedback found matching filters"}

    # Enrich with document data to get profile_state
    doc_ids = list({f.get("document_id") for f in all_feedback if f.get("document_id")})
    docs_map = {}
    if doc_ids:
        async for d in db.hub_documents.find(
            {"id": {"$in": doc_ids}},
            {"_id": 0, "id": 1, "so_readiness_review": 1, "so_confidence_calibration": 1}
        ):
            docs_map[d["id"]] = d

    # Filter to strong-profile only
    strong_feedback = []
    for fb in all_feedback:
        doc = docs_map.get(fb.get("document_id"), {})
        review = doc.get("so_readiness_review") or {}
        ps = review.get("profile_state", "unknown")
        if ps == "strong":
            fb["_profile_state"] = ps
            fb["_review"] = review
            fb["_cal"] = doc.get("so_confidence_calibration") or {}
            strong_feedback.append(fb)

    if not strong_feedback:
        return {"total_strong_profile": 0, "message": "No strong-profile feedback found"}

    # Apply disagreement_field filter
    if disagreement_field:
        strong_feedback = [fb for fb in strong_feedback if disagreement_field in (fb.get("disagreed_fields") or [])]

    # Split pre vs post tuning
    pre = [fb for fb in strong_feedback if (fb.get("timestamp") or "") < STRONG_PROFILE_TUNING_CUTOFF]
    post = [fb for fb in strong_feedback if (fb.get("timestamp") or "") >= STRONG_PROFILE_TUNING_CUTOFF]

    pre_metrics = _compute_metrics(pre, docs_map)
    post_metrics = _compute_metrics(post, docs_map)
    all_metrics = _compute_metrics(strong_feedback, docs_map)

    # Customer-level breakdown
    customer_breakdown = _customer_breakdown(strong_feedback)

    # Remaining disagreement drivers
    remaining_drivers = _disagreement_drivers(post if post else strong_feedback)

    # Examples
    improved = _find_improved_examples(pre, post, docs_map)
    problematic = _find_problematic_examples(post if post else strong_feedback, docs_map)

    # Verdict
    verdict = _assess_tuning_impact(pre_metrics, post_metrics)

    return {
        "total_strong_profile": len(strong_feedback),
        "pre_tuning_count": len(pre),
        "post_tuning_count": len(post),
        "cutoff_timestamp": STRONG_PROFILE_TUNING_CUTOFF,
        "overall": all_metrics,
        "pre_tuning": pre_metrics if pre else None,
        "post_tuning": post_metrics if post else None,
        "customer_breakdown": customer_breakdown[:15],
        "remaining_disagreement_drivers": remaining_drivers,
        "improved_examples": improved[:5],
        "still_problematic_examples": problematic[:5],
        "verdict": verdict,
        "filters_applied": {k: v for k, v in {
            "date_from": date_from, "date_to": date_to,
            "customer_no": customer_no, "reviewer": reviewer,
            "model": model, "readiness_status": readiness_status,
            "disagreement_field": disagreement_field,
        }.items() if v},
    }


async def get_strong_profile_details(
    db, limit: int = 50, skip: int = 0,
    date_from: Optional[str] = None, date_to: Optional[str] = None,
    customer_no: Optional[str] = None,
) -> Dict[str, Any]:
    """Individual strong-profile feedback records with enrichment."""
    match: Dict[str, Any] = {}
    if date_from or date_to:
        ts: Dict[str, Any] = {}
        if date_from:
            ts["$gte"] = date_from
        if date_to:
            ts["$lte"] = date_to
        match["timestamp"] = ts
    if customer_no:
        match["customer_no"] = customer_no

    records = await db.so_reviewer_feedback.find(
        match, {"_id": 0}
    ).sort("timestamp", -1).limit(limit + skip).to_list(limit + skip)

    # Filter to strong-profile
    doc_ids = list({r.get("document_id") for r in records if r.get("document_id")})
    docs_map = {}
    if doc_ids:
        async for d in db.hub_documents.find(
            {"id": {"$in": doc_ids}},
            {"_id": 0, "id": 1, "so_readiness_review": 1, "so_confidence_calibration": 1}
        ):
            docs_map[d["id"]] = d

    enriched = []
    for fb in records:
        doc = docs_map.get(fb.get("document_id"), {})
        review = doc.get("so_readiness_review") or {}
        if review.get("profile_state") != "strong":
            continue
        cal = doc.get("so_confidence_calibration") or {}
        ship = review.get("ship_to_analysis") or {}
        item = review.get("item_uom_analysis") or {}
        enriched.append({
            **fb,
            "ship_to_severity": ship.get("severity"),
            "ship_to_match": ship.get("match_type"),
            "item_uom_severity": item.get("overall_severity"),
            "items_exact": item.get("lines_exact"),
            "items_unknown": item.get("lines_unknown"),
            "raw_confidence": (fb.get("linked_review") or {}).get("confidence"),
            "calibrated_confidence": cal.get("calibrated_confidence"),
            "readiness_status": (fb.get("linked_review") or {}).get("readiness_status"),
            "period": "post" if (fb.get("timestamp") or "") >= STRONG_PROFILE_TUNING_CUTOFF else "pre",
        })

    # Apply pagination after filtering
    page = enriched[skip:skip + limit]
    return {"total": len(enriched), "showing": len(page), "skip": skip, "records": page}


# =============================================================================
# Metrics computation
# =============================================================================

def _compute_metrics(feedback: List[Dict], docs_map: Dict) -> Dict[str, Any]:
    if not feedback:
        return {"count": 0}
    n = len(feedback)
    assess = Counter(fb.get("reviewer_assessment") for fb in feedback)
    correct = assess.get("correct", 0)
    partial = assess.get("partially_correct", 0)
    incorrect = assess.get("incorrect", 0)
    helpful = assess.get("helpful_but_not_decisive", 0)
    not_helpful = assess.get("not_helpful", 0)

    ship_to_disagree = sum(1 for fb in feedback if "ship_to" in (fb.get("disagreed_fields") or []))
    item_uom_disagree = sum(1 for fb in feedback if any(f in (fb.get("disagreed_fields") or []) for f in ("item_match", "uom")))

    status_dist = Counter()
    conf_sum = 0.0
    cal_sum = 0.0
    cal_count = 0
    for fb in feedback:
        status_dist[(fb.get("linked_review") or {}).get("readiness_status", "?")] += 1
        conf_sum += float((fb.get("linked_review") or {}).get("confidence", 0))
        doc = docs_map.get(fb.get("document_id"), {})
        cal_conf = (doc.get("so_confidence_calibration") or {}).get("calibrated_confidence")
        if cal_conf:
            cal_sum += float(cal_conf)
            cal_count += 1

    def pct(v):
        return round(v / max(n, 1) * 100, 1)

    return {
        "count": n,
        "agreement_pct": pct(correct),
        "partial_pct": pct(partial),
        "incorrect_pct": pct(incorrect),
        "helpful_pct": pct(helpful),
        "not_helpful_pct": pct(not_helpful),
        "ship_to_disagree": ship_to_disagree,
        "item_uom_disagree": item_uom_disagree,
        "avg_raw_confidence": round(conf_sum / max(n, 1), 4),
        "avg_calibrated_confidence": round(cal_sum / max(cal_count, 1), 4) if cal_count else None,
        "status_distribution": dict(status_dist),
    }


def _customer_breakdown(feedback: List[Dict]) -> List[Dict]:
    by_customer = defaultdict(list)
    for fb in feedback:
        by_customer[fb.get("customer_no", "")].append(fb)

    results = []
    for cno, fbs in sorted(by_customer.items(), key=lambda x: len(x[1]), reverse=True):
        n = len(fbs)
        correct = sum(1 for fb in fbs if fb.get("reviewer_assessment") == "correct")
        incorrect = sum(1 for fb in fbs if fb.get("reviewer_assessment") in ("incorrect", "not_helpful"))
        ship_to_d = sum(1 for fb in fbs if "ship_to" in (fb.get("disagreed_fields") or []))
        item_d = sum(1 for fb in fbs if any(f in (fb.get("disagreed_fields") or []) for f in ("item_match", "uom")))
        results.append({
            "customer_no": cno,
            "customer_name": fbs[0].get("customer_name", ""),
            "total": n,
            "agreement_pct": round(correct / max(n, 1) * 100, 1),
            "incorrect_pct": round(incorrect / max(n, 1) * 100, 1),
            "ship_to_disagree": ship_to_d,
            "item_uom_disagree": item_d,
        })
    return results


def _disagreement_drivers(feedback: List[Dict]) -> List[Dict]:
    field_counter = Counter()
    for fb in feedback:
        if fb.get("reviewer_assessment") in ("incorrect", "partially_correct", "not_helpful"):
            for f in (fb.get("disagreed_fields") or []):
                field_counter[f] += 1
    return [{"field": f, "count": c} for f, c in field_counter.most_common(10)]


def _find_improved_examples(pre: List[Dict], post: List[Dict], docs_map: Dict) -> List[Dict]:
    """Find customers where post-tuning outcomes improved."""
    pre_by_cust = defaultdict(list)
    post_by_cust = defaultdict(list)
    for fb in pre:
        pre_by_cust[fb.get("customer_no")].append(fb)
    for fb in post:
        post_by_cust[fb.get("customer_no")].append(fb)

    examples = []
    for cno in set(pre_by_cust) & set(post_by_cust):
        pre_correct = sum(1 for fb in pre_by_cust[cno] if fb.get("reviewer_assessment") == "correct")
        post_correct = sum(1 for fb in post_by_cust[cno] if fb.get("reviewer_assessment") == "correct")
        pre_rate = pre_correct / max(len(pre_by_cust[cno]), 1)
        post_rate = post_correct / max(len(post_by_cust[cno]), 1)
        if post_rate > pre_rate:
            examples.append({
                "customer_no": cno,
                "customer_name": pre_by_cust[cno][0].get("customer_name", ""),
                "pre_agreement": round(pre_rate * 100, 1),
                "post_agreement": round(post_rate * 100, 1),
                "improvement": round((post_rate - pre_rate) * 100, 1),
            })
    return sorted(examples, key=lambda x: x["improvement"], reverse=True)


def _find_problematic_examples(feedback: List[Dict], docs_map: Dict) -> List[Dict]:
    """Find cases still generating disagreement."""
    examples = []
    for fb in feedback:
        if fb.get("reviewer_assessment") in ("incorrect", "not_helpful"):
            doc = docs_map.get(fb.get("document_id"), {})
            review = doc.get("so_readiness_review") or {}
            ship = review.get("ship_to_analysis") or {}
            item = review.get("item_uom_analysis") or {}
            examples.append({
                "document_id": fb.get("document_id"),
                "customer_no": fb.get("customer_no"),
                "assessment": fb.get("reviewer_assessment"),
                "disagreed_fields": fb.get("disagreed_fields", []),
                "notes": (fb.get("notes") or "")[:100],
                "ship_to_severity": ship.get("severity"),
                "item_uom_severity": item.get("overall_severity"),
                "readiness_status": (fb.get("linked_review") or {}).get("readiness_status"),
                "confidence": (fb.get("linked_review") or {}).get("confidence"),
            })
    return examples


def _assess_tuning_impact(pre: Dict, post: Dict) -> Dict[str, Any]:
    """Produce a verdict on whether tuning helped."""
    if not pre or pre.get("count", 0) == 0 or not post or post.get("count", 0) == 0:
        return {
            "verdict": "insufficient_comparison_data",
            "note": "Need both pre and post-tuning feedback to compare. Run evaluation after collecting more post-tuning feedback.",
            "recommendations": ["Continue collecting reviewer feedback on strong-profile cases"],
        }

    pre_agree = pre.get("agreement_pct", 0)
    post_agree = post.get("agreement_pct", 0)
    delta = post_agree - pre_agree

    recommendations = []

    if delta > 10:
        verdict = "positive"
        note = f"Strong improvement: agreement rose from {pre_agree}% to {post_agree}% (+{delta:.1f}pp)"
    elif delta > 0:
        verdict = "marginally_positive"
        note = f"Slight improvement: agreement rose from {pre_agree}% to {post_agree}% (+{delta:.1f}pp)"
        recommendations.append("Continue monitoring — more data will confirm the trend")
    elif delta > -5:
        verdict = "neutral"
        note = f"No meaningful change: agreement was {pre_agree}%, now {post_agree}%"
        recommendations.append("Investigate remaining disagreement drivers for further tuning opportunities")
    else:
        verdict = "needs_investigation"
        note = f"Agreement dropped from {pre_agree}% to {post_agree}% ({delta:.1f}pp)"
        recommendations.append("Review post-tuning severity assignments — tuning may have been too aggressive")

    # Ship-to improvement
    pre_ship = pre.get("ship_to_disagree", 0)
    post_ship = post.get("ship_to_disagree", 0)
    if pre_ship > 0 and post_ship < pre_ship:
        recommendations.append(f"Ship-to disagreements reduced from {pre_ship} to {post_ship}")
    elif post_ship > 0:
        recommendations.append(f"Ship-to still generating {post_ship} disagreement(s) — further tolerance may help")

    # Item/UOM improvement
    pre_item = pre.get("item_uom_disagree", 0)
    post_item = post.get("item_uom_disagree", 0)
    if pre_item > 0 and post_item < pre_item:
        recommendations.append(f"Item/UOM disagreements reduced from {pre_item} to {post_item}")
    elif post_item > 0:
        recommendations.append(f"Item/UOM still generating {post_item} disagreement(s)")

    return {"verdict": verdict, "note": note, "recommendations": recommendations}
