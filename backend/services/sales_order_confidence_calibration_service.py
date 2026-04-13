"""
GPI Document Hub — Sales Order Confidence Calibration Service

Adjusts raw model confidence to better reflect actual reviewer agreement
and real-world uncertainty. Preserves original values for audit.

CALIBRATION ONLY: Never changes routing or posting decisions.
"""

import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Penalty weights — each reduces confidence by this fraction of the gap to 0.5
PENALTY_NO_PROFILE = 0.20
PENALTY_WEAK_PROFILE = 0.10
PENALTY_PER_WARNING = 0.05
PENALTY_PER_UNUSUAL = 0.07
PENALTY_PER_BLOCKER = 0.15
PENALTY_NEW_CUSTOMER = 0.15
PENALTY_OVERCONFIDENCE_HISTORY = 0.12


@dataclass
class CalibrationResult:
    raw_confidence: float
    calibrated_confidence: float
    confidence_band: str
    calibration_reasons: List[str]
    penalties_applied: Dict[str, float]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def calibrate_confidence(
    review: Dict[str, Any],
    customer_profile: Optional[Dict[str, Any]] = None,
    historical_agreement_rate: Optional[float] = None,
) -> CalibrationResult:
    """
    Apply heuristic calibration to a readiness review's confidence.

    Args:
        review: The so_readiness_review dict from the document
        customer_profile: From customer_posting_profiles (may be None)
        historical_agreement_rate: Agreement rate for this model/customer
            from feedback analytics (0-1, or None if unknown)

    Returns:
        CalibrationResult with raw + calibrated confidence and reasons.
    """
    raw = float(review.get("confidence") or review.get("reviewer_confidence") or 0.5)
    penalties: Dict[str, float] = {}
    reasons: List[str] = []
    cal = raw

    # 1. No customer profile
    if not customer_profile:
        p = PENALTY_NO_PROFILE
        cal -= p
        penalties["no_profile"] = p
        reasons.append(f"No customer profile (-{p:.0%})")
    else:
        # Weak profile
        prof_conf = customer_profile.get("template_confidence", "low")
        analyzed = customer_profile.get("invoices_analyzed", 0)
        if prof_conf == "low" or analyzed < 5:
            p = PENALTY_WEAK_PROFILE
            cal -= p
            penalties["weak_profile"] = p
            reasons.append(f"Weak profile ({prof_conf}, {analyzed} orders) (-{p:.0%})")

    # 2. Warnings count
    warnings = review.get("warnings") or []
    if len(warnings) > 0:
        p = min(PENALTY_PER_WARNING * len(warnings), 0.20)
        cal -= p
        penalties["warnings"] = round(p, 4)
        reasons.append(f"{len(warnings)} warning(s) (-{p:.0%})")

    # 3. Unusual patterns
    unusual = review.get("unusual_patterns") or []
    if len(unusual) > 0:
        p = min(PENALTY_PER_UNUSUAL * len(unusual), 0.25)
        cal -= p
        penalties["unusual_patterns"] = round(p, 4)
        reasons.append(f"{len(unusual)} unusual pattern(s) (-{p:.0%})")

    # 4. Blocking issues
    blockers = review.get("blocking_issues") or []
    if len(blockers) > 0:
        p = min(PENALTY_PER_BLOCKER * len(blockers), 0.40)
        cal -= p
        penalties["blocking_issues"] = round(p, 4)
        reasons.append(f"{len(blockers)} blocking issue(s) (-{p:.0%})")

    # 5. New customer / low history — profile exists but very new
    if customer_profile:
        analyzed = customer_profile.get("invoices_analyzed", 0)
        cont_learning = customer_profile.get("continuous_learning_count", 0)
        if analyzed <= 1 and cont_learning <= 1:
            p = PENALTY_NEW_CUSTOMER
            cal -= p
            penalties["new_customer"] = p
            reasons.append(f"New customer (1 order learned) (-{p:.0%})")

    # 6. Historical overconfidence — if we know agreement rate is low
    if historical_agreement_rate is not None and historical_agreement_rate < 0.5:
        p = PENALTY_OVERCONFIDENCE_HISTORY
        cal -= p
        penalties["overconfidence_history"] = p
        reasons.append(f"Historical agreement rate {historical_agreement_rate:.0%} (-{p:.0%})")

    # 7. Clamp
    cal = max(0.0, min(1.0, cal))
    cal = round(cal, 4)

    band = _confidence_band(cal)

    if not reasons:
        reasons.append("No adjustments needed")

    logger.info(
        "[SO-Calibration] raw=%.2f calibrated=%.2f band=%s penalties=%s",
        raw, cal, band, penalties,
    )

    return CalibrationResult(
        raw_confidence=raw,
        calibrated_confidence=cal,
        confidence_band=band,
        calibration_reasons=reasons,
        penalties_applied=penalties,
    )


async def calibrate_document_review(
    db,
    document_id: str,
) -> CalibrationResult:
    """
    Load a document's review + profile and run calibration.
    Stores calibration result on the document.
    """
    doc = await db.hub_documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        return CalibrationResult(
            raw_confidence=0, calibrated_confidence=0,
            confidence_band="0-49%", calibration_reasons=[],
            penalties_applied={}, error="Document not found",
        )

    review = doc.get("so_readiness_review") or {}
    if not review:
        return CalibrationResult(
            raw_confidence=0, calibrated_confidence=0,
            confidence_band="0-49%", calibration_reasons=[],
            penalties_applied={}, error="No readiness review on document",
        )

    customer_no = doc.get("matched_customer_no") or doc.get("customer_no") or ""
    profile = None
    if customer_no:
        profile = await db.customer_posting_profiles.find_one(
            {"customer_no": customer_no, "status": "analyzed"}, {"_id": 0}
        )

    # Check historical agreement for this customer+model
    hist_rate = await _get_historical_agreement_rate(db, customer_no, review.get("model_used"))

    result = calibrate_confidence(review, profile, hist_rate)

    # Store on document
    await db.hub_documents.update_one(
        {"id": document_id},
        {"$set": {"so_confidence_calibration": result.to_dict()}}
    )

    return result


async def batch_calibrate(db, limit: int = 200) -> Dict[str, Any]:
    """
    Run calibration on recent documents with readiness reviews.
    Returns summary stats.
    """
    cursor = db.hub_documents.find(
        {"so_readiness_review": {"$exists": True, "$ne": None}},
        {"_id": 0, "id": 1}
    ).sort("created_utc", -1).limit(limit)

    total = 0
    calibrated = 0
    raw_sum = 0.0
    cal_sum = 0.0
    band_dist = {}

    async for doc_stub in cursor:
        total += 1
        result = await calibrate_document_review(db, doc_stub["id"])
        if not result.error:
            calibrated += 1
            raw_sum += result.raw_confidence
            cal_sum += result.calibrated_confidence
            band_dist[result.confidence_band] = band_dist.get(result.confidence_band, 0) + 1

    return {
        "total_processed": total,
        "calibrated": calibrated,
        "avg_raw_confidence": round(raw_sum / max(calibrated, 1), 4),
        "avg_calibrated_confidence": round(cal_sum / max(calibrated, 1), 4),
        "calibrated_band_distribution": band_dist,
    }


async def get_calibration_comparison(db, limit: int = 100) -> Dict[str, Any]:
    """
    Compare raw vs calibrated confidence and agreement rates by band.
    """
    # Get docs with calibration
    docs = await db.hub_documents.find(
        {"so_confidence_calibration": {"$exists": True}},
        {"_id": 0, "id": 1, "so_confidence_calibration": 1, "so_readiness_review": 1}
    ).limit(limit).to_list(limit)

    # Get feedback for these docs
    doc_ids = [d["id"] for d in docs]
    feedback_map = {}
    if doc_ids:
        fb_cursor = db.so_reviewer_feedback.find(
            {"document_id": {"$in": doc_ids}},
            {"_id": 0, "document_id": 1, "reviewer_assessment": 1}
        )
        async for fb in fb_cursor:
            feedback_map[fb["document_id"]] = fb["reviewer_assessment"]

    raw_bands = {}
    cal_bands = {}

    for doc in docs:
        cal = doc.get("so_confidence_calibration") or {}
        raw_conf = cal.get("raw_confidence", 0)
        cal_conf = cal.get("calibrated_confidence", 0)

        raw_band = _confidence_band(raw_conf)
        cal_band = _confidence_band(cal_conf)

        assessment = feedback_map.get(doc["id"])
        agreed = 1 if assessment == "correct" else 0
        has_fb = 1 if assessment else 0

        for band_name, band_key, conf_val in [
            (raw_band, "raw", raw_conf),
            (cal_band, "calibrated", cal_conf),
        ]:
            target = raw_bands if band_key == "raw" else cal_bands
            if band_name not in target:
                target[band_name] = {"total": 0, "with_feedback": 0, "agreed": 0}
            target[band_name]["total"] += 1
            target[band_name]["with_feedback"] += has_fb
            target[band_name]["agreed"] += agreed

    def _format(bands):
        return {
            b: {
                "total": v["total"],
                "with_feedback": v["with_feedback"],
                "agreement_rate": round(v["agreed"] / max(v["with_feedback"], 1) * 100, 1),
            }
            for b, v in sorted(bands.items())
        }

    return {
        "total_documents": len(docs),
        "with_feedback": len(feedback_map),
        "raw_confidence_bands": _format(raw_bands),
        "calibrated_confidence_bands": _format(cal_bands),
    }


# =============================================================================
# Helpers
# =============================================================================

def _confidence_band(conf: float) -> str:
    if conf >= 0.9:
        return "90-100%"
    if conf >= 0.7:
        return "70-89%"
    if conf >= 0.5:
        return "50-69%"
    return "0-49%"


async def _get_historical_agreement_rate(
    db, customer_no: str, model_used: Optional[str]
) -> Optional[float]:
    """Check feedback history for this customer+model pair."""
    if not customer_no:
        return None

    match: Dict[str, Any] = {"customer_no": customer_no}
    if model_used:
        match["linked_review.model_used"] = model_used

    total = await db.so_reviewer_feedback.count_documents(match)
    if total < 3:
        return None  # Not enough data

    correct = await db.so_reviewer_feedback.count_documents(
        {**match, "reviewer_assessment": "correct"}
    )
    return round(correct / total, 4)
