"""
GPI Document Hub — AP Invoice Decision Explainer

Reuses the generic explainer pattern with AP/vendor-specific
headlines, tone, and field semantics.

EXPLANATION ONLY: Never alters posting decisions.
"""

import logging
import time
from dataclasses import dataclass, asdict
from typing import Any, Dict, List, Optional

from services.ap_invoice_advisory_reviewer import classify_vendor_profile_state

logger = logging.getLogger(__name__)


@dataclass
class APExplanation:
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


async def explain_ap_invoice_decision(doc: Dict, db=None) -> APExplanation:
    t0 = time.monotonic()
    review = doc.get("ap_advisory_review")

    if review and not review.get("error"):
        result = _explain_from_review(review, doc)
        result.review_reused = True
        result.latency_ms = round((time.monotonic() - t0) * 1000)
        return result

    result = _explain_from_state(doc)
    result.review_reused = False
    result.latency_ms = round((time.monotonic() - t0) * 1000)
    return result


def _explain_from_review(review: Dict, doc: Dict) -> APExplanation:
    status = review.get("readiness_status", "needs_review")
    conf = float(review.get("confidence", 0))
    summary = review.get("summary", "")
    profile_state = review.get("profile_state", "unknown")

    # Tone
    if status == "incomplete":
        tone = "direct"
    elif status == "ready" and conf >= 0.7:
        tone = "confident"
    elif profile_state in ("none", "weak"):
        tone = "cautious"
    elif status == "suspicious":
        tone = "concerned"
    else:
        tone = "neutral"

    # Headline
    headlines = {
        "direct": "This invoice is missing required information",
        "confident": "This invoice looks ready for posting",
        "cautious": "Limited vendor history — manual review recommended",
        "concerned": "This invoice has patterns worth investigating",
        "neutral": "This invoice needs a quick review",
    }
    headline = headlines.get(tone, headlines["neutral"])

    # Flagged
    why_flagged = list(review.get("blocking_issues", []))
    for p in review.get("unusual_patterns", []):
        if profile_state in ("none", "weak"):
            why_flagged.append(f"minor: {p}")
        else:
            why_flagged.append(p)
    if not why_flagged and status != "ready":
        why_flagged.extend(review.get("warnings", []))

    # Normal
    what_normal = []
    for m in review.get("profile_matches", []):
        if profile_state in ("none", "weak"):
            what_normal.append(f"{m} (limited comparison basis)")
        else:
            what_normal.append(f"{m} — matches vendor history")

    # Attention
    what_attention = []
    if profile_state == "none":
        what_attention.append("No vendor history — comparisons unavailable")
    elif profile_state == "weak":
        what_attention.append("Vendor profile based on few invoices")
    covered = set(f.lower() for f in why_flagged)
    for w in review.get("warnings", []):
        if w.lower() not in covered:
            what_attention.append(w)

    # Steps
    steps = []
    rec = review.get("recommended_next_step", "")
    if rec:
        steps.append(rec)
    if tone == "cautious" and not steps:
        steps.append("Review manually — insufficient vendor history for confidence")
    elif tone == "confident" and not steps:
        steps.append("Review and approve — matches vendor pattern")

    if not summary:
        summary = f"Advisory review: {status} ({conf:.0%} confidence)."

    return APExplanation(
        headline=headline, plain_english_summary=summary,
        why_it_was_flagged=why_flagged, what_looks_normal=what_normal,
        what_needs_attention=what_attention, recommended_next_steps=steps,
        reviewer_confidence=conf, readiness_status=status,
        review_reused=True, latency_ms=0, explanation_tone=tone,
    )


def _explain_from_state(doc: Dict) -> APExplanation:
    status = doc.get("status") or doc.get("workflow_status") or ""
    if status in ("ready_for_post", "ReadyForPost", "Validated"):
        return APExplanation(
            headline="This invoice passed validation", plain_english_summary="All checks passed.",
            why_it_was_flagged=[], what_looks_normal=["Validation passed"],
            what_needs_attention=[], recommended_next_steps=["Review and approve"],
            reviewer_confidence=0, readiness_status="ready",
            review_reused=False, latency_ms=0, explanation_tone="confident",
        )
    return APExplanation(
        headline="Advisory review not yet available",
        plain_english_summary=f"Document is in '{status}' status. No AI advisory has run yet.",
        why_it_was_flagged=[], what_looks_normal=[], what_needs_attention=[],
        recommended_next_steps=["Advisory reviewer will run automatically"],
        reviewer_confidence=0, readiness_status="needs_review",
        review_reused=False, latency_ms=0, explanation_tone="neutral",
    )
