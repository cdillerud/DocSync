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


