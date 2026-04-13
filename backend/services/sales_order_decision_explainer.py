"""
GPI Document Hub — Sales Order Decision Explainer

Produces a plain-English explanation of why the advisory reviewer marked
a sales order as ready, needs_review, suspicious, or incomplete.

Prefers explaining an existing `so_readiness_review` on the document rather
than re-running the reviewer.  Falls back to a lightweight LLM summary only
when no review exists and no deterministic signal is available.

EXPLANATION ONLY: Never alters posting decisions or routing.
"""

import logging
import time
from dataclasses import dataclass, asdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_HEADLINES = {
    "ready":        "This sales order looks ready to post",
    "needs_review": "This sales order needs a quick review",
    "suspicious":   "This sales order has unusual patterns",
    "incomplete":   "This sales order is missing information",
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
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        return asdict(self)


async def explain_sales_order_decision(
    doc: Dict[str, Any],
    db=None,
) -> SOExplanation:
    """
    Build a user-facing explanation for a sales order document.

    Args:
        doc: Full hub_documents dict (already fetched by caller)
        db: Motor database (for loading customer profile if needed)

    Returns:
        SOExplanation — structured, human-readable breakdown.
    """
    t0 = time.monotonic()
    doc_id = doc.get("id", "unknown")

    review = doc.get("so_readiness_review")

    if review and not review.get("error"):
        explanation = _explain_from_review(review, doc, db)
        latency = round((time.monotonic() - t0) * 1000)
        explanation.review_reused = True
        explanation.latency_ms = latency

        logger.info(
            "[SO-Explainer] doc=%s reused=True status=%s confidence=%.2f latency=%dms",
            doc_id[:8], explanation.readiness_status, explanation.reviewer_confidence, latency,
        )
        return explanation

    # No valid review — build explanation from deterministic signals
    explanation = _explain_from_document_state(doc)
    latency = round((time.monotonic() - t0) * 1000)
    explanation.review_reused = False
    explanation.latency_ms = latency

    logger.info(
        "[SO-Explainer] doc=%s reused=False status=%s confidence=%.2f latency=%dms",
        doc_id[:8], explanation.readiness_status, explanation.reviewer_confidence, latency,
    )
    return explanation


# =============================================================================
# Explain from existing readiness review
# =============================================================================

def _explain_from_review(
    review: Dict[str, Any],
    doc: Dict[str, Any],
    db=None,
) -> SOExplanation:
    status = review.get("readiness_status", "needs_review")
    confidence = float(review.get("confidence", 0))
    summary = review.get("summary", "")
    profile_state = review.get("profile_state", "unknown")

    # Adjust headline for low-history cases
    if profile_state in ("none", "weak") and status == "needs_review":
        headline = "Limited customer history — manual review recommended"
    elif profile_state in ("none", "weak") and status == "suspicious":
        headline = "Flagged for review — note: limited customer history available"
    else:
        headline = _HEADLINES.get(status, "Sales order status unclear")

    # Why it was flagged
    why_flagged = []
    for issue in review.get("blocking_issues", []):
        why_flagged.append(issue)
    for pattern in review.get("unusual_patterns", []):
        why_flagged.append(pattern)
    if not why_flagged and status != "ready":
        for w in review.get("warnings", []):
            why_flagged.append(w)

    # What looks normal
    what_normal = []
    for match in review.get("profile_matches", []):
        if profile_state in ("none", "weak"):
            what_normal.append(f"{match} (limited comparison basis)")
        else:
            what_normal.append(f"{match} matches customer history")

    # What needs attention
    what_attention = []
    for w in review.get("warnings", []):
        if w not in why_flagged:
            what_attention.append(w)
    for issue in review.get("blocking_issues", []):
        if issue not in why_flagged:
            what_attention.append(issue)

    # Add profile-state context
    if profile_state == "none":
        what_attention.insert(0, "No customer history available — all comparisons are limited")
    elif profile_state == "weak":
        what_attention.insert(0, "Customer profile based on very few orders — patterns may not be reliable")

    # Recommended next steps
    steps = []
    rec = review.get("recommended_next_step", "")
    if rec:
        steps.append(rec)

    if profile_state in ("none", "weak"):
        if not steps:
            steps.append("Review this order manually — insufficient history for automated confidence")
        steps.append("This customer's profile will improve as more orders are processed")
    elif status == "ready" and confidence >= 0.8:
        if not steps:
            steps.append("Review and approve — this order matches the customer's typical pattern")
    elif status == "suspicious":
        steps.append("Compare against the customer's recent orders before approving")
        steps.append("Verify the ship-to address and line items with the customer")
    elif status == "incomplete":
        steps.append("Request missing information before proceeding")
    elif status == "needs_review":
        if not steps:
            steps.append("Check the flagged items and approve if they look correct")

    # Enrich summary if sparse
    if not summary:
        summary = _build_fallback_summary(status, confidence, why_flagged, what_normal)

    return SOExplanation(
        headline=headline,
        plain_english_summary=summary,
        why_it_was_flagged=why_flagged,
        what_looks_normal=what_normal,
        what_needs_attention=what_attention,
        recommended_next_steps=steps,
        reviewer_confidence=confidence,
        readiness_status=status,
        review_reused=True,
        latency_ms=0,
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

    # Derive status from document state
    if status_raw in ("Validated", "ReadyForPost", "ready_for_post"):
        readiness = "ready"
        headline = _HEADLINES["ready"]
        summary = "This sales order passed all validation checks and is ready for BC creation."
        what_normal.append("All deterministic validations passed")
        steps.append("Review and approve for BC Sales Order creation")
    elif status_raw in ("NeedsReview", "needs_review", "data_correction_pending"):
        readiness = "needs_review"
        headline = _HEADLINES["needs_review"]

        # Extract check failures
        for check in val.get("checks", []):
            if not check.get("passed"):
                why_flagged.append(f"{check.get('check_name', 'unknown')}: {check.get('details', 'failed')}")

        if not why_flagged:
            why_flagged.append(f"Document is in {status_raw} status")

        summary = f"This sales order requires review — {len(why_flagged)} issue(s) detected."
        steps.append("Address the flagged issues and re-validate")
    elif status_raw in ("Completed", "exported", "LinkedToBC"):
        readiness = "ready"
        headline = "This sales order has been processed"
        summary = "This order has already been posted or linked to a BC record."
        what_normal.append("Order is complete")
    else:
        readiness = "needs_review"
        headline = _HEADLINES["needs_review"]
        summary = f"This sales order is in '{status_raw}' status. No readiness review has been performed yet."
        steps.append("Run the readiness reviewer or manually review this document")

    # Check for missing fields
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
    )


def _build_fallback_summary(
    status: str, confidence: float,
    why_flagged: List[str], what_normal: List[str],
) -> str:
    if status == "ready":
        return f"The AI reviewer is {confidence:.0%} confident this order is ready to post."
    parts = []
    if why_flagged:
        parts.append(f"{len(why_flagged)} issue(s) were identified")
    if what_normal:
        parts.append(f"{len(what_normal)} field(s) match customer history")
    detail = "; ".join(parts) if parts else "further review recommended"
    return f"The AI reviewer flagged this order as '{status}' ({confidence:.0%} confidence): {detail}."
