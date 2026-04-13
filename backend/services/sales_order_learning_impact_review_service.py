"""
GPI Document Hub — Sales Order Learning Apply-Impact Review Service

Measures whether applied learning suggestions improve future reviewer
agreement for the affected customers and suggestion types.

ANALYSIS ONLY: Never changes thresholds, profile behavior, or workflow.
"""

import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


async def run_learning_impact_review(
    db,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    customer_no: Optional[str] = None,
    suggestion_type: Optional[str] = None,
    applied_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare pre-apply vs post-apply outcomes for applied suggestions."""

    # Fetch applied suggestions
    match: Dict[str, Any] = {"status": "applied"}
    if customer_no:
        match["customer_no"] = customer_no
    if suggestion_type:
        match["suggestion_type"] = suggestion_type
    if applied_by:
        match["applied_by"] = applied_by

    applied = await db.so_learning_suggestions.find(match, {"_id": 0}).to_list(500)
    if not applied:
        return {"total_applied": 0, "message": "No applied suggestions found"}

    # Fetch all feedback for affected customers
    affected_customers = list({s.get("customer_no") for s in applied if s.get("customer_no")})
    all_feedback = await db.so_reviewer_feedback.find(
        {"customer_no": {"$in": affected_customers}}, {"_id": 0}
    ).to_list(5000)

    # Build per-customer, per-suggestion impact
    by_type = defaultdict(lambda: {"pre": [], "post": [], "applied_count": 0})
    by_customer = defaultdict(lambda: {"pre": [], "post": [], "suggestions": []})
    improved = []
    no_change = []
    regressed = []

    for suggestion in applied:
        cno = suggestion.get("customer_no", "")
        stype = suggestion.get("suggestion_type", "")
        applied_at = suggestion.get("applied_at", "")

        # Split feedback into pre and post apply
        cust_fb = [fb for fb in all_feedback if fb.get("customer_no") == cno]
        pre = [fb for fb in cust_fb if (fb.get("timestamp") or "") < applied_at]
        post = [fb for fb in cust_fb if (fb.get("timestamp") or "") >= applied_at]

        by_type[stype]["pre"].extend(pre)
        by_type[stype]["post"].extend(post)
        by_type[stype]["applied_count"] += 1

        by_customer[cno]["pre"].extend(pre)
        by_customer[cno]["post"].extend(post)
        by_customer[cno]["suggestions"].append(suggestion)

        # Classify impact
        pre_rate = _agreement_rate(pre)
        post_rate = _agreement_rate(post)
        delta = post_rate - pre_rate if pre_rate is not None and post_rate is not None else None

        entry = {
            "suggestion_id": suggestion.get("suggestion_id"),
            "suggestion_type": stype,
            "customer_no": cno,
            "customer_name": suggestion.get("customer_name", ""),
            "applied_at": applied_at,
            "pre_feedback_count": len(pre),
            "post_feedback_count": len(post),
            "pre_agreement_pct": pre_rate,
            "post_agreement_pct": post_rate,
            "delta": round(delta, 1) if delta is not None else None,
        }

        if delta is not None:
            if delta > 5:
                improved.append(entry)
            elif delta < -5:
                regressed.append(entry)
            else:
                no_change.append(entry)
        else:
            no_change.append(entry)

    # Type-level summary
    type_summary = {}
    for stype, data in by_type.items():
        pre_rate = _agreement_rate(data["pre"])
        post_rate = _agreement_rate(data["post"])
        pre_disagree_fields = _top_disagreed_fields(data["pre"])
        post_disagree_fields = _top_disagreed_fields(data["post"])

        type_summary[stype] = {
            "applied_count": data["applied_count"],
            "pre_feedback": len(data["pre"]),
            "post_feedback": len(data["post"]),
            "pre_agreement_pct": pre_rate,
            "post_agreement_pct": post_rate,
            "delta": round(post_rate - pre_rate, 1) if pre_rate is not None and post_rate is not None else None,
            "pre_top_disagreed": pre_disagree_fields[:3],
            "post_top_disagreed": post_disagree_fields[:3],
        }

    # Customer-level summary
    customer_summary = []
    for cno, data in sorted(by_customer.items(), key=lambda x: len(x[1]["suggestions"]), reverse=True):
        pre_rate = _agreement_rate(data["pre"])
        post_rate = _agreement_rate(data["post"])
        customer_summary.append({
            "customer_no": cno,
            "customer_name": data["suggestions"][0].get("customer_name", "") if data["suggestions"] else "",
            "suggestions_applied": len(data["suggestions"]),
            "pre_agreement_pct": pre_rate,
            "post_agreement_pct": post_rate,
            "delta": round(post_rate - pre_rate, 1) if pre_rate is not None and post_rate is not None else None,
        })

    # Recommendations
    recs = _build_recommendations(type_summary, improved, regressed, no_change)

    return {
        "total_applied": len(applied),
        "customers_affected": len(affected_customers),
        "improved_count": len(improved),
        "no_change_count": len(no_change),
        "regressed_count": len(regressed),
        "by_suggestion_type": type_summary,
        "by_customer": customer_summary[:20],
        "improved_examples": improved[:5],
        "no_benefit_examples": [e for e in no_change if e.get("post_feedback_count", 0) > 0][:5],
        "regressed_examples": regressed[:5],
        "recommendations": recs,
        "filters_applied": {k: v for k, v in {
            "date_from": date_from, "date_to": date_to,
            "customer_no": customer_no, "suggestion_type": suggestion_type,
            "applied_by": applied_by,
        }.items() if v},
    }


async def get_impact_details(
    db, limit: int = 50, skip: int = 0,
    customer_no: Optional[str] = None,
    suggestion_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Per-suggestion impact detail records."""
    match: Dict[str, Any] = {}
    if customer_no:
        match["customer_no"] = customer_no
    if suggestion_type:
        match["suggestion_type"] = suggestion_type

    audits = await db.so_learning_apply_audit.find(
        match, {"_id": 0}
    ).sort("applied_at", -1).skip(skip).limit(limit).to_list(limit)

    total = await db.so_learning_apply_audit.count_documents(match)
    return {"total": total, "showing": len(audits), "skip": skip, "records": audits}


# =============================================================================
# Helpers
# =============================================================================

def _agreement_rate(feedback: List[Dict]) -> Optional[float]:
    if not feedback:
        return None
    correct = sum(1 for fb in feedback if fb.get("reviewer_assessment") == "correct")
    return round(correct / len(feedback) * 100, 1)


def _top_disagreed_fields(feedback: List[Dict], top_n: int = 5) -> List[Dict]:
    counter = Counter()
    for fb in feedback:
        if fb.get("reviewer_assessment") in ("incorrect", "partially_correct", "not_helpful"):
            for f in (fb.get("disagreed_fields") or []):
                counter[f] += 1
    return [{"field": f, "count": c} for f, c in counter.most_common(top_n)]


def _build_recommendations(
    type_summary: Dict, improved: List, regressed: List, no_change: List,
) -> List[Dict[str, str]]:
    recs = []

    for stype, data in type_summary.items():
        delta = data.get("delta")
        if delta is not None and delta > 10:
            recs.append({"type": stype, "signal": "positive",
                         "note": f"+{delta}pp agreement — consider lowering evidence threshold for faster adoption"})
        elif delta is not None and delta < -5:
            recs.append({"type": stype, "signal": "investigate",
                         "note": f"{delta}pp agreement drop — review whether applied changes were too broad"})
        elif data.get("post_feedback", 0) == 0:
            recs.append({"type": stype, "signal": "insufficient_data",
                         "note": "No post-apply feedback yet — continue monitoring"})

    if len(improved) > len(regressed) * 2 and improved:
        recs.append({"type": "overall", "signal": "positive",
                     "note": f"{len(improved)} improvements vs {len(regressed)} regressions — learning pipeline is adding value"})
    elif regressed and len(regressed) >= len(improved):
        recs.append({"type": "overall", "signal": "caution",
                     "note": f"{len(regressed)} regressions vs {len(improved)} improvements — review approval criteria"})

    if not recs:
        recs.append({"type": "overall", "signal": "monitoring",
                     "note": "Continue collecting post-apply feedback to build evidence"})

    return recs
