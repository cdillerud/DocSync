"""
GPI Document Hub — Sales Order Decision Explainer

Produces a plain-English explanation of why the advisory reviewer marked
a sales order as ready, needs_review, suspicious, or incomplete.

Prefers explaining an existing `so_readiness_review` on the document rather
than re-running the reviewer.  Falls back to a lightweight deterministic
summary when no review exists.

EXPLANATION ONLY: Never alters posting decisions or routing.
"""

import logging
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Evidence-strength qualifiers
_TONE = {
    "none":   "",
    "low":    "minor: ",
    "medium": "worth verifying: ",
    "high":   "",  # high severity speaks for itself
}


@dataclass
class SOExplanation:
    headline: str
    plain_english_summary: str
    why_it_was_flagged: List[str]
    what_looks_normal: List[str]
    what_needs_attention: List[str]
    recommended_next_steps: List[str]
    reviewer_confidence: float
    readiness_status: str
    review_reused: bool
    latency_ms: int
    explanation_tone: str = "neutral"
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def explain_sales_order_decision(
    doc: Dict[str, Any],
    db=None,
) -> SOExplanation:
    t0 = time.monotonic()
    doc_id = doc.get("id", "unknown")

    review = doc.get("so_readiness_review")

    if review and not review.get("error"):
        calibration = doc.get("so_confidence_calibration") or {}
        explanation = _explain_from_review(review, doc, calibration)
        latency = round((time.monotonic() - t0) * 1000)
        explanation.review_reused = True
        explanation.latency_ms = latency

        logger.info(
            "[SO-Explainer] doc=%s reused=True status=%s conf=%.2f cal=%.2f tone=%s latency=%dms",
            doc_id[:8], explanation.readiness_status, explanation.reviewer_confidence,
            calibration.get("calibrated_confidence", 0), explanation.explanation_tone, latency,
        )
        return explanation

    explanation = _explain_from_document_state(doc)
    latency = round((time.monotonic() - t0) * 1000)
    explanation.review_reused = False
    explanation.latency_ms = latency

    logger.info(
        "[SO-Explainer] doc=%s reused=False status=%s tone=%s latency=%dms",
        doc_id[:8], explanation.readiness_status, explanation.explanation_tone, latency,
    )
    return explanation


# =============================================================================
# Explain from existing readiness review
# =============================================================================

def _explain_from_review(
    review: Dict[str, Any],
    doc: Dict[str, Any],
    calibration: Dict[str, Any],
) -> SOExplanation:
    status = review.get("readiness_status", "needs_review")
    raw_conf = float(review.get("confidence", 0))
    cal_conf = float(calibration.get("calibrated_confidence", 0)) if calibration else 0
    display_conf = cal_conf if cal_conf > 0 else raw_conf
    summary_from_model = review.get("summary", "")
    profile_state = review.get("profile_state", "unknown")

    ship_to = review.get("ship_to_analysis") or {}
    item_uom = review.get("item_uom_analysis") or {}

    # ── Determine explanation tone ──
    tone = _determine_tone(status, profile_state, ship_to, item_uom, display_conf)

    # ── Headline ──
    headline = _build_headline(status, profile_state, tone)

    # ── Why it was flagged ──
    why_flagged = []
    # Blocking issues are always stated directly (these are real problems)
    for issue in review.get("blocking_issues", []):
        why_flagged.append(issue)

    # Unusual patterns — qualify with evidence strength
    ship_severity = ship_to.get("severity", "none")
    item_severity = item_uom.get("overall_severity", "none")

    for pattern in review.get("unusual_patterns", []):
        p_lower = pattern.lower()
        # Determine which pre-analysis this pattern relates to
        if any(kw in p_lower for kw in ("ship", "destination", "address", "location")):
            if ship_severity in ("none", "low"):
                why_flagged.append(f"minor: {pattern} (limited comparison basis)" if profile_state in ("none", "weak") else f"minor: {pattern}")
            else:
                why_flagged.append(pattern)
        elif any(kw in p_lower for kw in ("item", "product", "uom", "unit")):
            if item_severity in ("none", "low"):
                why_flagged.append(f"minor: {pattern}" if profile_state not in ("none",) else f"note: {pattern} — no history to compare against")
            else:
                why_flagged.append(pattern)
        else:
            qualifier = _TONE.get(("low" if profile_state in ("none", "weak") else "medium"), "")
            why_flagged.append(f"{qualifier}{pattern}" if qualifier else pattern)

    # If nothing flagged but status isn't ready, pull from warnings
    if not why_flagged and status != "ready":
        for w in review.get("warnings", []):
            why_flagged.append(w)

    # ── What looks normal ──
    what_normal = []
    matches = review.get("profile_matches", [])
    if matches:
        if profile_state in ("none", "weak"):
            what_normal.append(f"{len(matches)} field(s) checked (limited comparison basis)")
        elif profile_state == "medium":
            for m in matches[:5]:
                what_normal.append(f"{m} — consistent with moderate order history")
        else:
            for m in matches[:5]:
                what_normal.append(f"{m} — matches established customer pattern")

    # Add structured analysis positives
    if ship_to.get("match_type") in ("exact", "normalized_match"):
        what_normal.append("Ship-to matches a known customer location")
    elif ship_to.get("match_type") == "known_alternate":
        what_normal.append("Ship-to is a recognized alternate location")
    if item_uom.get("lines_exact", 0) > 0:
        total = item_uom.get("total_lines", 0)
        exact = item_uom.get("lines_exact", 0)
        if exact == total:
            what_normal.append(f"All {total} line item(s) use known items and expected UOMs")
        else:
            what_normal.append(f"{exact}/{total} line item(s) match customer history")

    # ── What needs attention ──
    what_attention = []

    # Profile context (always first for low-history)
    if profile_state == "none":
        what_attention.append("No customer order history — comparisons against history are not available")
    elif profile_state == "weak":
        what_attention.append("Customer profile is based on very few orders — deviations may be normal")

    # Ship-to attention
    if ship_severity == "medium":
        what_attention.append(f"Destination differs from common locations — {ship_to.get('context_notes', 'worth verifying')}")
    elif ship_severity == "high":
        what_attention.append(f"Unusual destination — {ship_to.get('context_notes', 'verify with customer')}")

    # Item/UOM attention
    if item_severity == "medium":
        what_attention.append(f"Some line items not in history — {item_uom.get('context_notes', 'worth verifying')}")
    elif item_severity == "high":
        what_attention.append(f"Line items significantly differ from history — {item_uom.get('context_notes', 'review carefully')}")

    # Remaining warnings not already covered
    covered_lower = {f.lower() for f in why_flagged + what_attention}
    for w in review.get("warnings", []):
        if w.lower() not in covered_lower and w not in why_flagged:
            what_attention.append(w)

    # ── Recommended next steps ──
    steps = _build_steps(status, profile_state, tone, display_conf, review.get("recommended_next_step", ""))

    # ── Summary ──
    summary = _build_summary(status, profile_state, tone, display_conf, summary_from_model,
                             len(why_flagged), len(what_normal), ship_severity, item_severity)

    return SOExplanation(
        headline=headline,
        plain_english_summary=summary,
        why_it_was_flagged=why_flagged,
        what_looks_normal=what_normal,
        what_needs_attention=what_attention,
        recommended_next_steps=steps,
        reviewer_confidence=display_conf,
        readiness_status=status,
        review_reused=True,
        latency_ms=0,
        explanation_tone=tone,
    )


# =============================================================================
# Explain from document state (no review available)
# =============================================================================

def _explain_from_document_state(doc: Dict[str, Any]) -> SOExplanation:
    status_raw = doc.get("status") or doc.get("workflow_status") or ""
    val = doc.get("validation_results") or {}

    why_flagged = []
    what_normal = []
    what_attention = []
    steps = []

    if status_raw in ("Validated", "ReadyForPost", "ready_for_post"):
        readiness = "ready"
        headline = "This sales order passed validation checks"
        summary = "All deterministic validation checks passed. Ready for BC creation."
        what_normal.append("All validation checks passed")
        steps.append("Review and approve for BC Sales Order creation")
        tone = "confident"
    elif status_raw in ("NeedsReview", "needs_review", "data_correction_pending"):
        readiness = "needs_review"
        headline = "This sales order needs a quick review"
        for check in val.get("checks", []):
            if not check.get("passed"):
                why_flagged.append(f"{check.get('check_name', 'unknown')}: {check.get('details', 'failed')}")
        if not why_flagged:
            why_flagged.append(f"Document is in {status_raw} status")
        summary = f"This order has {len(why_flagged)} issue(s) that need attention before posting."
        steps.append("Address the flagged issues and re-validate")
        tone = "cautious"
    elif status_raw in ("Completed", "exported", "LinkedToBC"):
        readiness = "ready"
        headline = "This sales order has been processed"
        summary = "This order has already been posted or linked to a BC record."
        what_normal.append("Order is complete")
        tone = "confident"
    else:
        readiness = "needs_review"
        headline = "Advisory review not yet available"
        summary = f"This order is in '{status_raw}' status. No AI advisory review has been performed yet."
        steps.append("The advisory reviewer will run automatically, or you can review manually")
        tone = "neutral"

    # Check extracted fields
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    customer = nf.get("customer") or ef.get("customer") or doc.get("customer_extracted")
    order_no = nf.get("order_number") or ef.get("order_number") or nf.get("invoice_number_clean")

    if customer:
        what_normal.append(f"Customer identified: {customer}")
    else:
        what_attention.append("Customer name not extracted")
    if order_no:
        what_normal.append(f"Order number: {order_no}")
    else:
        what_attention.append("Order/invoice number not extracted")

    return SOExplanation(
        headline=headline,
        plain_english_summary=summary,
        why_it_was_flagged=why_flagged,
        what_looks_normal=what_normal,
        what_needs_attention=what_attention,
        recommended_next_steps=steps,
        reviewer_confidence=0.0,
        readiness_status=readiness,
        review_reused=False,
        latency_ms=0,
        explanation_tone=tone,
    )


# =============================================================================
# Helpers
# =============================================================================

def _determine_tone(
    status: str, profile_state: str,
    ship_to: Dict, item_uom: Dict, confidence: float,
) -> str:
    """Classify the overall explanation tone."""
    if status == "incomplete":
        return "direct"  # missing data — be clear
    if status == "ready" and confidence >= 0.7:
        return "confident"
    if profile_state in ("none", "weak"):
        return "cautious"  # limited evidence — be measured
    ship_sev = ship_to.get("severity", "none")
    item_sev = item_uom.get("overall_severity", "none")
    if ship_sev == "high" or item_sev == "high":
        return "concerned"  # strong evidence of anomaly
    if ship_sev == "medium" or item_sev == "medium":
        return "attentive"  # moderate deviation
    if status == "suspicious":
        return "attentive"
    return "neutral"


def _build_headline(status: str, profile_state: str, tone: str) -> str:
    if tone == "direct":
        return "This sales order is missing required information"
    if tone == "confident":
        return "This sales order looks ready to post"
    if tone == "cautious":
        if status == "suspicious":
            return "Flagged for review — limited customer history available"
        return "Limited customer history — manual review recommended"
    if tone == "concerned":
        return "This sales order has patterns worth investigating"
    if tone == "attentive":
        return "This sales order has a few items to check"
    # neutral
    if status == "ready":
        return "This sales order looks ready to post"
    return "This sales order needs a quick review"


def _build_summary(
    status: str, profile_state: str, tone: str,
    confidence: float, model_summary: str,
    flag_count: int, normal_count: int,
    ship_sev: str, item_sev: str,
) -> str:
    if model_summary and tone not in ("cautious",):
        return model_summary

    if tone == "direct":
        return f"Critical fields are missing. {flag_count} issue(s) must be resolved before this order can proceed."

    if tone == "confident":
        return f"The advisory system is {confidence:.0%} confident this order matches the customer's typical pattern. {normal_count} field(s) confirmed."

    if tone == "cautious":
        base = "This customer has limited order history, so the system cannot fully assess whether this order is typical."
        if flag_count:
            base += f" {flag_count} item(s) were noted but may be normal for this customer."
        return base

    if tone == "concerned":
        parts = []
        if ship_sev in ("medium", "high"):
            parts.append("destination")
        if item_sev in ("medium", "high"):
            parts.append("line items")
        areas = " and ".join(parts) if parts else "some fields"
        return f"The {areas} differ from this customer's established pattern. Confidence: {confidence:.0%}."

    if tone == "attentive":
        return model_summary if model_summary else f"A few items differ from recent history ({confidence:.0%} confidence). Quick verification recommended."

    # neutral
    return model_summary if model_summary else f"Advisory review completed with {confidence:.0%} confidence."


def _build_steps(
    status: str, profile_state: str, tone: str,
    confidence: float, model_step: str,
) -> List[str]:
    steps = []
    if model_step:
        steps.append(model_step)

    if tone == "direct":
        if not steps:
            steps.append("Provide the missing information before proceeding")
        return steps

    if tone == "confident":
        if not steps:
            steps.append("Review and approve — this order aligns with the customer's history")
        return steps

    if tone == "cautious":
        if not steps:
            steps.append("Review this order manually — there is not enough history for automated confidence")
        steps.append("The customer's profile will improve as more orders are processed")
        return steps

    if tone == "concerned":
        steps.append("Compare against the customer's recent orders before approving")
        return steps

    if tone == "attentive":
        if not steps:
            steps.append("Check the flagged items — they may be valid but are worth a quick look")
        return steps

    # neutral
    if not steps:
        steps.append("Review the order details and approve if everything looks correct")
    return steps
