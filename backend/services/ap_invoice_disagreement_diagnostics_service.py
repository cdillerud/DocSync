"""
GPI Document Hub — AP Invoice Disagreement Diagnostics

Classifies reviewer disagreements into AP-specific root-cause
categories for system tuning.

DIAGNOSTICS ONLY: Never changes workflow or advisory logic.
"""

import logging
from collections import Counter
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

AP_FIELD_TO_CAUSE = {
    "vendor_match": "vendor_match_ambiguity",
    "amount_range": "amount_tolerance_sensitivity",
    "po_reference": "po_reference_mismatch",
    "invoice_number": "extraction_ambiguity",
    "duplicate": "duplicate_sensitivity",
    "invoice_date": "extraction_ambiguity",
    "line_items": "extraction_ambiguity",
    "readiness_status": "confidence_overestimation",
    "confidence": "confidence_overestimation",
    "other": "other_unknown",
}

AP_ROOT_CAUSES = [
    "no_vendor_profile", "weak_vendor_profile",
    "extraction_ambiguity", "vendor_match_ambiguity",
    "po_reference_mismatch", "amount_tolerance_sensitivity",
    "duplicate_sensitivity", "confidence_overestimation",
    "explanation_wording", "other_unknown",
]


def _classify_ap_causes(fb: Dict) -> List[str]:
    causes = set()
    fields = fb.get("disagreed_fields") or []
    review = fb.get("linked_review") or {}
    assessment = fb.get("reviewer_assessment", "")

    for f in fields:
        causes.add(AP_FIELD_TO_CAUSE.get(f, "other_unknown"))

    profile_state = review.get("profile_state")
    profile_id = review.get("vendor_profile_id")
    if not profile_id and not profile_state:
        causes.add("no_vendor_profile")
    elif profile_state == "weak":
        causes.add("weak_vendor_profile")

    if assessment == "incorrect" and float(review.get("confidence", 0)) >= 0.8:
        causes.add("confidence_overestimation")

    if assessment == "not_helpful" and not fields:
        causes.add("explanation_wording")

    if not causes:
        causes.add("other_unknown")
    return sorted(causes)


async def run_ap_disagreement_diagnostics(
    db,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    vendor_no: Optional[str] = None,
    assessment: Optional[str] = None,
    root_cause: Optional[str] = None,
) -> Dict[str, Any]:
    match: Dict[str, Any] = {
        "reviewer_assessment": {"$in": ["incorrect", "partially_correct", "not_helpful"]},
    }
    if date_from or date_to:
        ts: Dict[str, Any] = {}
        if date_from:
            ts["$gte"] = date_from
        if date_to:
            ts["$lte"] = date_to
        match["timestamp"] = ts
    if vendor_no:
        match["vendor_no"] = vendor_no
    if assessment:
        match["reviewer_assessment"] = assessment

    records = await db.ap_reviewer_feedback.find(match, {"_id": 0}).to_list(2000)
    if not records:
        return {"total_analyzed": 0, "message": "No AP disagreement feedback found"}

    cause_counter = Counter()
    field_counter = Counter()
    classified = []

    for fb in records:
        causes = _classify_ap_causes(fb)
        if root_cause and root_cause not in causes:
            continue
        for c in causes:
            cause_counter[c] += 1
        for f in (fb.get("disagreed_fields") or []):
            field_counter[f] += 1
        classified.append(fb)

    n = len(classified)
    total_all = await db.ap_reviewer_feedback.count_documents(
        {k: v for k, v in match.items() if k != "reviewer_assessment"}
    )

    return {
        "total_analyzed": n,
        "total_feedback": total_all,
        "disagreement_rate": round(n / max(total_all, 1) * 100, 1),
        "root_cause_ranked": [
            {"cause": c, "count": cnt, "pct": round(cnt / max(n, 1) * 100, 1)}
            for c, cnt in cause_counter.most_common()
        ],
        "top_disagreed_fields": [
            {"field": f, "count": c} for f, c in field_counter.most_common(10)
        ],
        "filters_applied": {k: v for k, v in {
            "date_from": date_from, "date_to": date_to,
            "vendor_no": vendor_no, "assessment": assessment, "root_cause": root_cause,
        }.items() if v},
    }
