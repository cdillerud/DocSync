"""
GPI Document Hub — AP Invoice Confidence Calibration

Heuristic calibration for AP vendor advisory. Preserves raw
confidence, adds calibrated values.

CALIBRATION ONLY: Never changes routing or posting.
"""

import logging
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

P_NO_PROFILE = 0.20
P_WEAK_PROFILE = 0.10
P_PER_WARNING = 0.05
P_PER_UNUSUAL = 0.07
P_PER_BLOCKER = 0.15
P_OVERCONF_HISTORY = 0.12


@dataclass
class APCalibrationResult:
    raw_confidence: float
    calibrated_confidence: float
    confidence_band: str
    calibration_reasons: List[str]
    penalties_applied: Dict[str, float]
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


def calibrate_ap_confidence(
    review: Dict[str, Any],
    vendor_profile: Optional[Dict[str, Any]] = None,
    historical_agreement: Optional[float] = None,
) -> APCalibrationResult:
    raw = float(review.get("confidence", 0.5))
    penalties: Dict[str, float] = {}
    reasons: List[str] = []
    cal = raw

    profile_state = review.get("profile_state", "unknown")

    if not vendor_profile or profile_state == "none":
        p = P_NO_PROFILE
        cal -= p
        penalties["no_profile"] = p
        reasons.append(f"No vendor profile (-{p:.0%})")
    elif profile_state == "weak":
        p = P_WEAK_PROFILE
        cal -= p
        penalties["weak_profile"] = p
        analyzed = vendor_profile.get("bc_invoice_count", 0)
        reasons.append(f"Weak vendor profile ({analyzed} invoices) (-{p:.0%})")

    warnings = review.get("warnings") or []
    if warnings:
        p = min(P_PER_WARNING * len(warnings), 0.20)
        cal -= p
        penalties["warnings"] = round(p, 4)
        reasons.append(f"{len(warnings)} warning(s) (-{p:.0%})")

    unusual = review.get("unusual_patterns") or []
    if unusual:
        p = min(P_PER_UNUSUAL * len(unusual), 0.25)
        cal -= p
        penalties["unusual"] = round(p, 4)
        reasons.append(f"{len(unusual)} unusual pattern(s) (-{p:.0%})")

    blockers = review.get("blocking_issues") or []
    if blockers:
        p = min(P_PER_BLOCKER * len(blockers), 0.40)
        cal -= p
        penalties["blockers"] = round(p, 4)
        reasons.append(f"{len(blockers)} blocking issue(s) (-{p:.0%})")

    if historical_agreement is not None and historical_agreement < 0.5:
        p = P_OVERCONF_HISTORY
        cal -= p
        penalties["overconf_history"] = p
        reasons.append(f"Historical agreement {historical_agreement:.0%} (-{p:.0%})")

    cal = max(0.0, min(1.0, round(cal, 4)))
    band = _band(cal)

    if not reasons:
        reasons.append("No adjustments needed")

    return APCalibrationResult(
        raw_confidence=raw, calibrated_confidence=cal,
        confidence_band=band, calibration_reasons=reasons,
        penalties_applied=penalties,
    )


async def calibrate_ap_document(db, document_id: str) -> APCalibrationResult:
    doc = await db.hub_documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        return APCalibrationResult(0, 0, "0-49%", [], {}, error="Document not found")

    review = doc.get("ap_advisory_review") or {}
    if not review:
        return APCalibrationResult(0, 0, "0-49%", [], {}, error="No AP advisory review")

    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_canonical") or ""
    profile = None
    if vendor_no:
        profile = await db.vendor_invoice_profiles.find_one({"vendor_no": vendor_no}, {"_id": 0})

    result = calibrate_ap_confidence(review, profile)

    await db.hub_documents.update_one(
        {"id": document_id},
        {"$set": {"ap_confidence_calibration": result.to_dict()}}
    )
    return result


def _band(c: float) -> str:
    if c >= 0.9:
        return "90-100%"
    if c >= 0.7:
        return "70-89%"
    if c >= 0.5:
        return "50-69%"
    return "0-49%"
