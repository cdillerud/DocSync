"""
GPI Document Hub — Post-Tuning Calibration & Impact Review Service

Measures how recent tuning changes affected reviewer agreement,
disagreement root causes, confidence calibration quality, and
overall advisory usefulness. Produces recommendations for next
calibration adjustments.

ANALYSIS ONLY: Never changes workflow, calibration weights, or prompts.
"""

import logging
from collections import Counter, defaultdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Tuning milestones — used to partition pre/post comparisons
TUNING_MILESTONES = [
    ("2026-04-13T00:00:00Z", "ship_to_tuning"),
    ("2026-04-13T01:00:00Z", "item_uom_tuning"),
    ("2026-04-13T01:20:00Z", "wording_refinement"),
]


async def run_post_tuning_review(
    db,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    customer_no: Optional[str] = None,
    reviewer: Optional[str] = None,
    model: Optional[str] = None,
    profile_state: Optional[str] = None,
    readiness_status: Optional[str] = None,
    assessment: Optional[str] = None,
) -> Dict[str, Any]:
    """Run comprehensive post-tuning impact analysis."""

    match = _build_match(date_from, date_to, customer_no, reviewer,
                         model, readiness_status, assessment)

    all_feedback = await db.so_reviewer_feedback.find(match, {"_id": 0}).to_list(5000)
    if not all_feedback:
        return {"total_feedback": 0, "message": "No feedback records found matching filters"}

    # Load related documents for enrichment
    doc_ids = list({f.get("document_id") for f in all_feedback if f.get("document_id")})
    docs_map = {}
    if doc_ids:
        cursor = db.hub_documents.find(
            {"id": {"$in": doc_ids}},
            {"_id": 0, "id": 1, "so_readiness_review": 1, "so_confidence_calibration": 1}
        )
        async for d in cursor:
            docs_map[d["id"]] = d

    # Filter by profile_state if requested
    if profile_state:
        filtered = []
        for fb in all_feedback:
            doc = docs_map.get(fb.get("document_id"), {})
            review = doc.get("so_readiness_review") or {}
            if review.get("profile_state") == profile_state:
                filtered.append(fb)
        all_feedback = filtered

    total = len(all_feedback)
    if total == 0:
        return {"total_feedback": 0, "message": "No feedback after profile_state filter"}

    # ── Core agreement metrics ──
    assess_counter = Counter()
    for fb in all_feedback:
        assess_counter[fb.get("reviewer_assessment", "unknown")] += 1

    correct = assess_counter.get("correct", 0)
    partial = assess_counter.get("partially_correct", 0)
    incorrect = assess_counter.get("incorrect", 0)
    helpful = assess_counter.get("helpful_but_not_decisive", 0)
    not_helpful = assess_counter.get("not_helpful", 0)

    # ── Disagreement root causes ──
    from services.sales_order_disagreement_diagnostics_service import _classify_root_causes
    cause_counter = Counter()
    for fb in all_feedback:
        if fb.get("reviewer_assessment") in ("incorrect", "partially_correct", "not_helpful"):
            for c in _classify_root_causes(fb):
                cause_counter[c] += 1

    # ── Confidence band analysis ──
    raw_bands = defaultdict(lambda: {"total": 0, "correct": 0, "incorrect": 0})
    cal_bands = defaultdict(lambda: {"total": 0, "correct": 0, "incorrect": 0})
    profile_state_outcomes = defaultdict(lambda: {"total": 0, "correct": 0, "incorrect": 0})

    # Ship-to and item/UOM specific disagreement
    ship_to_disagree = 0
    item_uom_disagree = 0
    tone_dist = Counter()

    for fb in all_feedback:
        doc = docs_map.get(fb.get("document_id"), {})
        review = doc.get("so_readiness_review") or {}
        cal = doc.get("so_confidence_calibration") or {}
        is_correct = fb.get("reviewer_assessment") == "correct"
        is_incorrect = fb.get("reviewer_assessment") in ("incorrect", "not_helpful")

        # Raw confidence bands
        raw_conf = (fb.get("linked_review") or {}).get("confidence") or 0
        rb = _conf_band(raw_conf)
        raw_bands[rb]["total"] += 1
        if is_correct:
            raw_bands[rb]["correct"] += 1
        if is_incorrect:
            raw_bands[rb]["incorrect"] += 1

        # Calibrated confidence bands
        cal_conf = cal.get("calibrated_confidence") or 0
        if cal_conf > 0:
            cb = _conf_band(cal_conf)
            cal_bands[cb]["total"] += 1
            if is_correct:
                cal_bands[cb]["correct"] += 1
            if is_incorrect:
                cal_bands[cb]["incorrect"] += 1

        # Profile state outcomes
        ps = review.get("profile_state", "unknown")
        profile_state_outcomes[ps]["total"] += 1
        if is_correct:
            profile_state_outcomes[ps]["correct"] += 1
        if is_incorrect:
            profile_state_outcomes[ps]["incorrect"] += 1

        # Ship-to / item/UOM disagreement tracking
        fields = fb.get("disagreed_fields") or []
        if "ship_to" in fields:
            ship_to_disagree += 1
        if "item_match" in fields or "uom" in fields:
            item_uom_disagree += 1

        # Tone distribution
        tone = review.get("explanation_tone") if review else None
        if tone:
            tone_dist[tone] += 1

    # ── Calibration weight assessment ──
    cal_assessment = _assess_calibration_weights(raw_bands, cal_bands, total)

    # ── Build tuning impact signals ──
    disagreement_total = incorrect + partial + not_helpful
    tuning_signals = []
    if total > 0:
        if ship_to_disagree == 0 and disagreement_total > 0:
            tuning_signals.append({"area": "ship_to_tuning", "signal": "positive", "note": "Zero ship-to disagreements post-tuning"})
        elif ship_to_disagree > 0:
            rate = round(ship_to_disagree / disagreement_total * 100, 1) if disagreement_total else 0
            tuning_signals.append({"area": "ship_to_tuning", "signal": "needs_monitoring", "note": f"{ship_to_disagree} ship-to disagreements ({rate}% of total)"})

        if item_uom_disagree == 0 and disagreement_total > 0:
            tuning_signals.append({"area": "item_uom_tuning", "signal": "positive", "note": "Zero item/UOM disagreements post-tuning"})
        elif item_uom_disagree > 0:
            rate = round(item_uom_disagree / disagreement_total * 100, 1) if disagreement_total else 0
            tuning_signals.append({"area": "item_uom_tuning", "signal": "needs_monitoring", "note": f"{item_uom_disagree} item/UOM disagreements ({rate}% of total)"})

        none_outcomes = profile_state_outcomes.get("none", {})
        if none_outcomes.get("total", 0) > 0:
            none_correct_pct = round(none_outcomes.get("correct", 0) / none_outcomes["total"] * 100, 1)
            tuning_signals.append({"area": "no_profile_handling", "signal": "positive" if none_correct_pct >= 50 else "needs_monitoring",
                                   "note": f"{none_correct_pct}% agreement on no-profile cases ({none_outcomes['total']} total)"})

        if helpful + not_helpful > 0:
            help_rate = round(helpful / (helpful + not_helpful) * 100, 1)
            tuning_signals.append({"area": "wording_refinement", "signal": "positive" if help_rate >= 60 else "needs_monitoring",
                                   "note": f"Helpful rate: {help_rate}% ({helpful}/{helpful + not_helpful})"})

    def pct(n):
        return round(n / max(total, 1) * 100, 1)

    def band_dict(bands):
        return {
            b: {"total": v["total"],
                "agreement_pct": round(v["correct"] / max(v["total"], 1) * 100, 1),
                "incorrect_pct": round(v["incorrect"] / max(v["total"], 1) * 100, 1)}
            for b, v in sorted(bands.items())
        }

    return {
        "total_feedback": total,
        "agreement_rates": {
            "correct": pct(correct),
            "partially_correct": pct(partial),
            "incorrect": pct(incorrect),
            "helpful": pct(helpful),
            "not_helpful": pct(not_helpful),
        },
        "disagreement_root_causes": [
            {"cause": c, "count": cnt, "pct": round(cnt / max(disagreement_total, 1) * 100, 1)}
            for c, cnt in cause_counter.most_common()
        ],
        "raw_confidence_bands": band_dict(raw_bands),
        "calibrated_confidence_bands": band_dict(cal_bands),
        "profile_state_outcomes": {
            ps: {"total": v["total"],
                 "agreement_pct": round(v["correct"] / max(v["total"], 1) * 100, 1),
                 "incorrect_pct": round(v["incorrect"] / max(v["total"], 1) * 100, 1)}
            for ps, v in profile_state_outcomes.items()
        },
        "ship_to_disagreement_count": ship_to_disagree,
        "item_uom_disagreement_count": item_uom_disagree,
        "explanation_tone_distribution": dict(tone_dist),
        "calibration_assessment": cal_assessment,
        "tuning_impact_signals": tuning_signals,
        "filters_applied": {k: v for k, v in {
            "date_from": date_from, "date_to": date_to,
            "customer_no": customer_no, "reviewer": reviewer,
            "model": model, "profile_state": profile_state,
            "readiness_status": readiness_status, "assessment": assessment,
        }.items() if v},
    }


async def get_post_tuning_details(
    db, limit: int = 100, skip: int = 0,
    date_from: Optional[str] = None, date_to: Optional[str] = None,
) -> Dict[str, Any]:
    """Return individual feedback records enriched with review + calibration data."""
    match = _build_match(date_from, date_to)
    total = await db.so_reviewer_feedback.count_documents(match)
    records = await db.so_reviewer_feedback.find(
        match, {"_id": 0}
    ).sort("timestamp", -1).skip(skip).limit(limit).to_list(limit)

    enriched = []
    for fb in records:
        doc_id = fb.get("document_id")
        doc = None
        if doc_id:
            doc = await db.hub_documents.find_one(
                {"id": doc_id},
                {"_id": 0, "so_readiness_review.profile_state": 1,
                 "so_readiness_review.ship_to_analysis.severity": 1,
                 "so_readiness_review.item_uom_analysis.overall_severity": 1,
                 "so_confidence_calibration.calibrated_confidence": 1,
                 "so_confidence_calibration.calibration_reasons": 1}
            )
        review = (doc or {}).get("so_readiness_review") or {}
        cal = (doc or {}).get("so_confidence_calibration") or {}

        enriched.append({
            **fb,
            "profile_state": review.get("profile_state"),
            "ship_to_severity": (review.get("ship_to_analysis") or {}).get("severity"),
            "item_uom_severity": (review.get("item_uom_analysis") or {}).get("overall_severity"),
            "calibrated_confidence": cal.get("calibrated_confidence"),
            "calibration_reasons": cal.get("calibration_reasons"),
        })

    return {"total": total, "showing": len(enriched), "skip": skip, "records": enriched}


# =============================================================================
# Helpers
# =============================================================================

def _conf_band(conf: float) -> str:
    if conf >= 0.9:
        return "90-100%"
    if conf >= 0.7:
        return "70-89%"
    if conf >= 0.5:
        return "50-69%"
    return "0-49%"


def _build_match(
    date_from=None, date_to=None, customer_no=None, reviewer=None,
    model=None, readiness_status=None, assessment=None,
) -> Dict[str, Any]:
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
    if assessment:
        match["reviewer_assessment"] = assessment
    return match


def _assess_calibration_weights(
    raw_bands: Dict, cal_bands: Dict, total: int,
) -> Dict[str, Any]:
    """Assess whether calibration penalties are too strong, too weak, or reasonable."""
    if total < 5:
        return {"verdict": "insufficient_data", "note": "Need more feedback to assess calibration quality"}

    # Compare agreement rates: raw vs calibrated
    # Ideal: calibrated bands should have agreement rates that increase with confidence
    raw_sorted = sorted(raw_bands.items())
    cal_sorted = sorted(cal_bands.items())

    raw_monotonic = _check_monotonicity([v["correct"] / max(v["total"], 1) for _, v in raw_sorted])
    cal_monotonic = _check_monotonicity([v["correct"] / max(v["total"], 1) for _, v in cal_sorted])

    # Check if high-confidence calibrated band has good agreement
    high_band = cal_bands.get("90-100%", {})
    high_agreement = round(high_band.get("correct", 0) / max(high_band.get("total", 0), 1) * 100, 1) if high_band.get("total", 0) else None

    low_band = cal_bands.get("0-49%", {})
    low_agreement = round(low_band.get("correct", 0) / max(low_band.get("total", 0), 1) * 100, 1) if low_band.get("total", 0) else None

    recommendations = []

    if cal_monotonic:
        verdict = "well_calibrated"
        note = "Calibrated confidence bands show increasing agreement with increasing confidence — penalties appear well-tuned"
    elif raw_monotonic and not cal_monotonic:
        verdict = "penalties_too_aggressive"
        note = "Raw confidence was better ordered than calibrated — penalties may be overcorrecting"
        recommendations.append("Consider reducing penalty weights by 20-30%")
    else:
        verdict = "needs_more_data"
        note = "Neither raw nor calibrated confidence shows clear monotonic agreement — more feedback needed"

    if high_agreement is not None and high_agreement < 70:
        recommendations.append(f"High-confidence band (90-100%) has only {high_agreement}% agreement — penalize less in this range")

    if low_agreement is not None and low_agreement > 60:
        recommendations.append(f"Low-confidence band (0-49%) has {low_agreement}% agreement — current penalties may be too strong")

    return {
        "verdict": verdict,
        "note": note,
        "raw_monotonic": raw_monotonic,
        "calibrated_monotonic": cal_monotonic,
        "high_band_agreement": high_agreement,
        "low_band_agreement": low_agreement,
        "recommendations": recommendations,
    }


def _check_monotonicity(values: List[float]) -> bool:
    """Check if values are roughly monotonically increasing."""
    if len(values) < 2:
        return True
    increasing = 0
    for i in range(1, len(values)):
        if values[i] >= values[i - 1] - 0.05:  # allow 5% tolerance
            increasing += 1
    return increasing >= len(values) - 2  # allow one violation
