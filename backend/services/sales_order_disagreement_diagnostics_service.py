"""
GPI Document Hub — Sales Order Disagreement Diagnostics Service

Analyzes reviewer feedback to identify root causes of advisory
disagreements and false positives for system tuning.

DIAGNOSTICS ONLY: Never changes workflow, routing, or advisory logic.
"""

import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Maps disagreed_fields to likely root-cause categories
FIELD_TO_ROOT_CAUSE = {
    "amount_range":                "order_value_range_too_strict",
    "ship_to":                     "ship_to_sensitivity_too_high",
    "item_match":                  "item_uom_sensitivity_too_high",
    "uom":                         "item_uom_sensitivity_too_high",
    "po_pattern":                  "upstream_extraction_weakness",
    "customer_profile_assumption": "profile_too_sparse",
    "line_count":                  "order_value_range_too_strict",
    "readiness_status":            "confidence_overestimation",
    "confidence":                  "confidence_overestimation",
    "other":                       "other_unknown",
}

ALL_ROOT_CAUSES = [
    "no_customer_profile",
    "profile_too_sparse",
    "order_value_range_too_strict",
    "ship_to_sensitivity_too_high",
    "item_uom_sensitivity_too_high",
    "upstream_extraction_weakness",
    "confidence_overestimation",
    "prompt_wording_issue",
    "new_customer_low_history",
    "other_unknown",
]


async def run_disagreement_diagnostics(
    db,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    customer_no: Optional[str] = None,
    reviewer: Optional[str] = None,
    model: Optional[str] = None,
    readiness_status: Optional[str] = None,
    assessment: Optional[str] = None,
    root_cause: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Analyze disagreement feedback and classify into root-cause buckets.
    """
    # Fetch disagreement feedback (exclude "correct")
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

    records = await db.so_reviewer_feedback.find(match, {"_id": 0}).to_list(1000)

    if not records:
        return {"total_analyzed": 0, "message": "No disagreement feedback found matching filters"}

    # Enrich each record with root-cause classification
    classified: List[Dict[str, Any]] = []
    cause_counter = Counter()
    customer_causes = defaultdict(Counter)
    model_causes = defaultdict(Counter)
    confidence_bands = defaultdict(lambda: {"total": 0, "disagreed": 0})
    profile_present = {"total": 0, "disagreed": 0}
    profile_absent = {"total": 0, "disagreed": 0}
    profile_confidence_bands = defaultdict(lambda: {"total": 0, "disagreed": 0})
    field_to_cause_counter = Counter()
    examples_by_cause: Dict[str, List[Dict]] = defaultdict(list)

    # Also load total feedback for rate calculations
    total_feedback = await db.so_reviewer_feedback.count_documents(
        {k: v for k, v in match.items() if k != "reviewer_assessment"}
    )

    for rec in records:
        causes = _classify_root_causes(rec)

        # Apply root_cause filter if specified
        if root_cause and root_cause not in causes:
            continue

        entry = {
            "document_id": rec.get("document_id"),
            "customer_no": rec.get("customer_no"),
            "customer_name": rec.get("customer_name"),
            "reviewer_assessment": rec.get("reviewer_assessment"),
            "disagreed_fields": rec.get("disagreed_fields", []),
            "root_causes": causes,
            "advisory_confidence": rec.get("linked_review", {}).get("confidence"),
            "advisory_status": rec.get("linked_review", {}).get("readiness_status"),
            "model_used": rec.get("linked_review", {}).get("model_used"),
            "timestamp": rec.get("timestamp"),
        }
        classified.append(entry)

        for c in causes:
            cause_counter[c] += 1
            customer_causes[rec.get("customer_no", "")][c] += 1
            model_causes[rec.get("linked_review", {}).get("model_used", "unknown")][c] += 1
            if len(examples_by_cause[c]) < 3:
                examples_by_cause[c].append({
                    "document_id": rec.get("document_id"),
                    "customer": f"{rec.get('customer_no', '')} ({rec.get('customer_name', '')})",
                    "assessment": rec.get("reviewer_assessment"),
                    "fields": rec.get("disagreed_fields", []),
                    "notes": (rec.get("notes") or "")[:100],
                })

        for f in rec.get("disagreed_fields", []):
            mapped = FIELD_TO_ROOT_CAUSE.get(f, "other_unknown")
            field_to_cause_counter[f"{f} -> {mapped}"] += 1

        # Confidence band tracking
        conf = rec.get("linked_review", {}).get("confidence") or 0
        band = _confidence_band(conf)
        confidence_bands[band]["disagreed"] += 1

    # Calculate rates with total feedback per band
    all_feedback = await db.so_reviewer_feedback.find(
        {k: v for k, v in match.items() if k != "reviewer_assessment"},
        {"_id": 0, "linked_review.confidence": 1}
    ).to_list(5000)
    for fb in all_feedback:
        conf = (fb.get("linked_review") or {}).get("confidence") or 0
        band = _confidence_band(conf)
        confidence_bands[band]["total"] += 1

    # Profile present/absent rates — check docs
    doc_ids = [r.get("document_id") for r in records if r.get("document_id")]
    if doc_ids:
        docs = await db.hub_documents.find(
            {"id": {"$in": doc_ids}},
            {"_id": 0, "id": 1, "matched_customer_no": 1, "customer_no": 1}
        ).to_list(len(doc_ids))
        cust_nos = {d["id"]: d.get("matched_customer_no") or d.get("customer_no") or "" for d in docs}

        profiles_found = set()
        for cno in set(cust_nos.values()):
            if cno:
                p = await db.customer_posting_profiles.find_one(
                    {"customer_no": cno, "status": "analyzed"}, {"_id": 0, "customer_no": 1, "template_confidence": 1}
                )
                if p:
                    profiles_found.add(cno)
                    band = p.get("template_confidence", "low")
                    profile_confidence_bands[band]["total"] += 1

        for rec in records:
            cno = rec.get("customer_no", "")
            if cno in profiles_found:
                profile_present["disagreed"] += 1
            else:
                profile_absent["disagreed"] += 1

    # Total for profile rates
    profile_present["total"] = total_feedback  # approximate
    profile_absent["total"] = total_feedback

    n = len(classified)

    # Customer hotspots
    customer_hotspots = []
    for cno, causes_map in sorted(customer_causes.items(), key=lambda x: sum(x[1].values()), reverse=True)[:15]:
        customer_hotspots.append({
            "customer_no": cno,
            "total_disagreements": sum(causes_map.values()),
            "top_causes": [{"cause": c, "count": cnt} for c, cnt in causes_map.most_common(3)],
        })

    # Model hotspots
    model_hotspots = []
    for mdl, causes_map in model_causes.items():
        model_hotspots.append({
            "model": mdl,
            "total_disagreements": sum(causes_map.values()),
            "top_causes": [{"cause": c, "count": cnt} for c, cnt in causes_map.most_common(3)],
        })

    return {
        "total_analyzed": n,
        "total_feedback": total_feedback,
        "disagreement_rate": round(n / max(total_feedback, 1) * 100, 1),
        "root_cause_distribution": {c: cause_counter.get(c, 0) for c in ALL_ROOT_CAUSES if cause_counter.get(c, 0) > 0},
        "root_cause_ranked": [{"cause": c, "count": cnt, "pct": round(cnt / max(n, 1) * 100, 1)} for c, cnt in cause_counter.most_common()],
        "customer_hotspots": customer_hotspots,
        "model_hotspots": model_hotspots,
        "disagreement_by_advisory_confidence": {
            band: {"total": v["total"], "disagreed": v["disagreed"],
                   "rate": round(v["disagreed"] / max(v["total"], 1) * 100, 1)}
            for band, v in sorted(confidence_bands.items())
        },
        "disagreed_field_to_cause": [{"mapping": m, "count": c} for m, c in field_to_cause_counter.most_common(15)],
        "filters_applied": {k: v for k, v in {
            "date_from": date_from, "date_to": date_to,
            "customer_no": customer_no, "reviewer": reviewer,
            "model": model, "readiness_status": readiness_status,
            "assessment": assessment, "root_cause": root_cause,
        }.items() if v},
    }


async def get_disagreement_examples(
    db,
    root_cause: Optional[str] = None,
    limit: int = 20,
) -> List[Dict[str, Any]]:
    """
    Return example disagreement records, optionally filtered by root cause.
    """
    match: Dict[str, Any] = {
        "reviewer_assessment": {"$in": ["incorrect", "partially_correct", "not_helpful"]},
    }
    records = await db.so_reviewer_feedback.find(
        match, {"_id": 0}
    ).sort("timestamp", -1).limit(200).to_list(200)

    results = []
    for rec in records:
        causes = _classify_root_causes(rec)
        if root_cause and root_cause not in causes:
            continue
        results.append({
            "document_id": rec.get("document_id"),
            "customer_no": rec.get("customer_no"),
            "customer_name": rec.get("customer_name"),
            "reviewer_assessment": rec.get("reviewer_assessment"),
            "final_human_decision": rec.get("final_human_decision"),
            "disagreed_fields": rec.get("disagreed_fields", []),
            "notes": rec.get("notes", ""),
            "root_causes": causes,
            "advisory_confidence": (rec.get("linked_review") or {}).get("confidence"),
            "advisory_status": (rec.get("linked_review") or {}).get("readiness_status"),
            "model_used": (rec.get("linked_review") or {}).get("model_used"),
            "timestamp": rec.get("timestamp"),
        })
        if len(results) >= limit:
            break

    return results


# =============================================================================
# Classification logic
# =============================================================================

def _classify_root_causes(rec: Dict[str, Any]) -> List[str]:
    """
    Classify a disagreement record into root-cause categories.
    A single record may map to multiple causes.
    """
    causes = set()
    fields = rec.get("disagreed_fields") or []
    review = rec.get("linked_review") or {}
    assessment = rec.get("reviewer_assessment", "")
    notes = (rec.get("notes") or "").lower()

    # Field-based classification
    for f in fields:
        mapped = FIELD_TO_ROOT_CAUSE.get(f, "other_unknown")
        causes.add(mapped)

    # Profile-based signals
    profile_id = review.get("profile_id")
    if not profile_id:
        causes.add("no_customer_profile")
    elif "customer_profile_assumption" in fields:
        causes.add("profile_too_sparse")

    # Confidence overestimation: model was confident but reviewer said incorrect
    confidence = review.get("confidence") or 0
    if assessment == "incorrect" and confidence >= 0.8:
        causes.add("confidence_overestimation")

    # New customer signal from notes
    if any(kw in notes for kw in ["new customer", "first time", "new account", "never seen"]):
        causes.add("new_customer_low_history")

    # Prompt/explanation issue signal
    if assessment == "not_helpful" and not fields:
        causes.add("prompt_wording_issue")

    if not causes:
        causes.add("other_unknown")

    return sorted(causes)


def _confidence_band(conf: float) -> str:
    if conf >= 0.9:
        return "90-100%"
    if conf >= 0.7:
        return "70-89%"
    if conf >= 0.5:
        return "50-69%"
    return "0-49%"
