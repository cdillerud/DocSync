"""Learned authority for AI-primary AP routing.

The AI proposes the route. This module decides whether that exact proposal has
earned autonomy from relevant human evidence and historical AI-vs-human
performance. It never substitutes another route.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence

from services.ap_routing_autonomy_performance_service import summarize_pattern_performance
from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name
from services.ap_routing_relevant_learning_service import (
    LABEL_SOURCE_REVIEWER_CONFIRMATION,
    build_relevant_learning_examples,
    is_train_human_example,
)

REVIEW = "review"
GUARDED = "guarded"
EARNED_AUTO = "earned_auto"


def _vendor(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    return normalize_vendor_name(
        document.get("vendor_name")
        or document.get("vendor_canonical")
        or fields.get("vendor")
        or ""
    )


def _doc_type(document: Dict[str, Any]) -> str:
    fields = document.get("extracted_fields") or {}
    return str(
        document.get("document_type")
        or document.get("suggested_job_type")
        or fields.get("document_type")
        or ""
    ).strip().lower()


def _example_vendor(example: Dict[str, Any]) -> str:
    return normalize_vendor_name(example.get("vendor_name") or example.get("normalized_vendor") or "")


def _example_doc_type(example: Dict[str, Any]) -> str:
    return str(example.get("document_type") or example.get("suggested_job_type") or "").strip().lower()


def _weight(example: Dict[str, Any]) -> float:
    source = str(example.get("label_source") or "").lower()
    if source == "reviewer_correction":
        return 3.0
    if source == LABEL_SOURCE_REVIEWER_CONFIRMATION:
        return 1.5
    return 1.0


def evaluate_learned_autonomy(
    *,
    document: Dict[str, Any],
    ai_decision: Dict[str, Any],
    train_examples: Sequence[Dict[str, Any]],
    performance_outcomes: Iterable[Dict[str, Any]] = (),
    relevant_limit: int = 20,
    minimum_model_confidence: float = 0.80,
    minimum_support_count: int = 4,
    minimum_support_share: float = 0.80,
    minimum_performance_observations: int = 5,
    minimum_performance_lower_bound: float = 0.55,
) -> Dict[str, Any]:
    """Grant or abstain on the AI's exact route using learned human evidence."""
    proposed = normalize_route_path(
        ai_decision.get("proposed_route")
        or ai_decision.get("route_path")
        or ((ai_decision.get("prediction") or {}).get("proposed_route"))
    )
    confidence = float(
        ai_decision.get("confidence")
        or ((ai_decision.get("prediction") or {}).get("confidence"))
        or 0.0
    )
    reasons: List[str] = []

    if not proposed:
        return {
            "decision": "needs_review",
            "route_path": "",
            "ai_proposed_route": "",
            "autonomy_tier": REVIEW,
            "autonomy_score": 0.0,
            "reason": "AI produced no route",
            "reasons": ["AI produced no route"],
            "route_preserved": True,
        }

    relevant = build_relevant_learning_examples(document, train_examples, limit=relevant_limit)
    wanted_vendor = _vendor(document)
    wanted_type = _doc_type(document)

    # Authority is local to the current learned pattern. Cross-vendor examples
    # can inform the model prompt but cannot, by themselves, grant autonomy.
    local = [
        row
        for row in relevant
        if is_train_human_example(row)
        and wanted_vendor
        and _example_vendor(row) == wanted_vendor
        and (not wanted_type or not _example_doc_type(row) or _example_doc_type(row) == wanted_type)
    ]
    support = [row for row in local if normalize_route_path(row.get("route_path")) == proposed]
    contradictions = [row for row in local if normalize_route_path(row.get("route_path")) != proposed]

    support_weight = sum(_weight(row) for row in support)
    contradiction_weight = sum(_weight(row) for row in contradictions)
    total_weight = support_weight + contradiction_weight
    share = support_weight / total_weight if total_weight else 0.0
    correction_contradictions = sum(
        1 for row in contradictions if str(row.get("label_source") or "") == "reviewer_correction"
    )

    performance = summarize_pattern_performance(
        document=document,
        proposed_route=proposed,
        outcomes=performance_outcomes,
        minimum_observations=minimum_performance_observations,
    )

    if confidence < minimum_model_confidence:
        reasons.append(
            f"AI confidence {confidence:.1%} below learned-autonomy floor {minimum_model_confidence:.1%}"
        )
    if not wanted_vendor:
        reasons.append("vendor identity unresolved; no local learned authority")
    if len(support) < minimum_support_count:
        reasons.append(f"only {len(support)} local human supports; need {minimum_support_count}")
    if share < minimum_support_share:
        reasons.append(f"local human support share {share:.1%} below {minimum_support_share:.1%}")
    if correction_contradictions:
        reasons.append(f"{correction_contradictions} reviewer correction(s) contradict the AI route")
    if performance.get("suspended"):
        reasons.append("learned pattern suspended by historical human-resolved AI error")

    performance_earned = bool(
        performance.get("sufficient_observations")
        and not performance.get("suspended")
        and float(performance.get("wilson_lower_bound") or 0.0) >= minimum_performance_lower_bound
    )
    bootstrap_earned = bool(
        len(support) >= max(minimum_support_count, 5)
        and contradiction_weight == 0.0
        and correction_contradictions == 0
    )

    hard_reasons = bool(reasons)
    earned = not hard_reasons and (performance_earned or bootstrap_earned)

    if earned:
        tier = EARNED_AUTO
        decision = "auto_route"
        route_path = proposed
        reason = (
            "AI route earned autonomy from human-confirmed Gamer Accounting evidence"
            + (" and measured AI-vs-human performance" if performance_earned else "")
        )
    else:
        promising = (
            proposed
            and confidence >= minimum_model_confidence
            and len(support) >= 2
            and share >= 0.60
            and not correction_contradictions
            and not performance.get("suspended")
        )
        tier = GUARDED if promising else REVIEW
        decision = "needs_review"
        route_path = ""
        reason = "; ".join(reasons) if reasons else "learned pattern has not yet earned automatic authority"

    # Score is explanatory telemetry, never a route selector. It combines
    # evidence agreement, model confidence, and conservative performance.
    performance_component = float(performance.get("wilson_lower_bound") or 0.0)
    score = min(
        1.0,
        0.35 * confidence
        + 0.35 * share
        + 0.20 * min(1.0, len(support) / max(minimum_support_count, 1))
        + 0.10 * performance_component,
    )

    return {
        "decision": decision,
        "route_path": route_path,
        "ai_proposed_route": proposed,
        "autonomy_tier": tier,
        "autonomy_score": round(score, 4),
        "reason": reason,
        "reasons": reasons,
        "route_preserved": route_path in {"", proposed},
        "support_count": len(support),
        "support_weight": round(support_weight, 3),
        "contradiction_count": len(contradictions),
        "contradiction_weight": round(contradiction_weight, 3),
        "reviewer_correction_contradictions": correction_contradictions,
        "support_share": round(share, 4),
        "relevant_example_count": len(relevant),
        "relevant_example_ids": [
            str(row.get("fingerprint") or row.get("source_item_id") or row.get("document_id") or row.get("file_name") or "")
            for row in relevant[:relevant_limit]
        ],
        "performance": performance,
        "earned_by": (
            "measured_performance" if earned and performance_earned else
            "human_consensus_bootstrap" if earned and bootstrap_earned else
            "none"
        ),
        "policy": {
            "minimum_model_confidence": minimum_model_confidence,
            "minimum_support_count": minimum_support_count,
            "minimum_support_share": minimum_support_share,
            "minimum_performance_observations": minimum_performance_observations,
            "minimum_performance_lower_bound": minimum_performance_lower_bound,
        },
    }
