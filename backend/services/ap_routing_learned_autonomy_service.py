"""Learned authority for AI-primary AP routing.

The AI proposes the route. This module decides whether that exact proposal has
earned autonomy from nearby human evidence and historical AI-vs-human
performance. It never substitutes another route.
"""

from __future__ import annotations

from typing import Any, Dict, Iterable, List, Sequence

from services.ap_routing_autonomy_performance_service import summarize_pattern_performance
from services.ap_routing_learned_neighborhood_service import summarize_authority_neighborhood
from services.ap_routing_learning_service import normalize_route_path

REVIEW = "review"
GUARDED = "guarded"
EARNED_AUTO = "earned_auto"


def evaluate_learned_autonomy(
    *,
    document: Dict[str, Any],
    ai_decision: Dict[str, Any],
    train_examples: Sequence[Dict[str, Any]],
    performance_outcomes: Iterable[Dict[str, Any]] = (),
    relevant_limit: int = 8,
    minimum_model_confidence: float = 0.90,
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
            "support_count": 0,
            "contradiction_count": 0,
            "support_share": 0.0,
            "earned_by": "none",
        }

    neighborhood = summarize_authority_neighborhood(
        document=document,
        proposed_route=proposed,
        train_examples=train_examples,
        limit=relevant_limit,
    )
    performance = summarize_pattern_performance(
        document=document,
        proposed_route=proposed,
        outcomes=performance_outcomes,
        minimum_observations=minimum_performance_observations,
    )

    hard_reasons: List[str] = []
    neighborhood_reasons: List[str] = []
    if confidence < minimum_model_confidence:
        hard_reasons.append(
            f"AI confidence {confidence:.1%} below learned-autonomy floor {minimum_model_confidence:.1%}"
        )
    if int(neighborhood.get("reviewer_correction_contradictions") or 0) > 0:
        hard_reasons.append(
            f"{int(neighborhood.get('reviewer_correction_contradictions') or 0)} reviewer correction(s) contradict the AI route"
        )
    if performance.get("suspended"):
        hard_reasons.append("learned pattern suspended by historical human-resolved AI error")

    if int(neighborhood.get("support_count") or 0) < int(neighborhood.get("minimum_support") or 0):
        neighborhood_reasons.append(
            f"only {int(neighborhood.get('support_count') or 0)} nearby human supports; need {int(neighborhood.get('minimum_support') or 0)}"
        )
    if float(neighborhood.get("support_share") or 0.0) < float(neighborhood.get("minimum_support_share") or 0.0):
        neighborhood_reasons.append(
            f"nearby human support share {float(neighborhood.get('support_share') or 0.0):.1%} below {float(neighborhood.get('minimum_support_share') or 0.0):.1%}"
        )
    if float(neighborhood.get("support_margin") or 0.0) < float(neighborhood.get("minimum_support_margin") or 0.0):
        neighborhood_reasons.append(
            f"nearest-support relevance margin {float(neighborhood.get('support_margin') or 0.0):.2f} below {float(neighborhood.get('minimum_support_margin') or 0.0):.2f}"
        )
    if neighborhood.get("scope") == "semantic_cross_vendor" and not neighborhood.get("semantic_anchor"):
        neighborhood_reasons.append("cross-vendor authority lacks a route-neutral semantic/reference anchor")

    performance_earned = bool(
        performance.get("sufficient_observations")
        and not performance.get("suspended")
        and int(performance.get("wrong") or 0) == 0
        and float(performance.get("wilson_lower_bound") or 0.0) >= minimum_performance_lower_bound
    )
    neighborhood_earned = bool(neighborhood.get("authority_ready"))
    earned = not hard_reasons and (performance_earned or neighborhood_earned)

    if earned:
        tier = EARNED_AUTO
        decision = "auto_route"
        route_path = proposed
        if performance_earned:
            earned_by = "measured_performance"
            reason = "AI route earned autonomy from measured human-resolved AI performance"
        else:
            earned_by = "human_consensus_bootstrap"
            reason = "AI route earned autonomy from a high-purity nearby human Accounting neighborhood"
    else:
        promising = bool(
            proposed
            and confidence >= minimum_model_confidence
            and int(neighborhood.get("support_count") or 0) >= 2
            and float(neighborhood.get("support_share") or 0.0) >= 0.60
            and int(neighborhood.get("reviewer_correction_contradictions") or 0) == 0
            and not performance.get("suspended")
        )
        tier = GUARDED if promising else REVIEW
        decision = "needs_review"
        route_path = ""
        earned_by = "none"
        reasons = hard_reasons + neighborhood_reasons
        reason = "; ".join(reasons) if reasons else "learned pattern has not yet earned automatic authority"

    # Explanatory only. It cannot select a route.
    performance_component = float(performance.get("wilson_lower_bound") or 0.0)
    score = min(
        1.0,
        0.35 * confidence
        + 0.35 * float(neighborhood.get("support_share") or 0.0)
        + 0.20 * min(1.0, int(neighborhood.get("support_count") or 0) / max(int(neighborhood.get("minimum_support") or 1), 1))
        + 0.10 * performance_component,
    )

    return {
        "decision": decision,
        "route_path": route_path,
        "ai_proposed_route": proposed,
        "autonomy_tier": tier,
        "autonomy_score": round(score, 4),
        "reason": reason,
        "reasons": hard_reasons + ([] if earned else neighborhood_reasons),
        "route_preserved": route_path in {"", proposed},
        "support_count": int(neighborhood.get("support_count") or 0),
        "support_weight": neighborhood.get("support_weight"),
        "contradiction_count": int(neighborhood.get("contradiction_count") or 0),
        "contradiction_weight": neighborhood.get("contradiction_weight"),
        "reviewer_correction_contradictions": int(neighborhood.get("reviewer_correction_contradictions") or 0),
        "support_share": float(neighborhood.get("support_share") or 0.0),
        "support_margin": float(neighborhood.get("support_margin") or 0.0),
        "neighborhood": neighborhood,
        "performance": performance,
        "earned_by": earned_by,
        "policy": {
            "minimum_model_confidence": minimum_model_confidence,
            "minimum_performance_observations": minimum_performance_observations,
            "minimum_performance_lower_bound": minimum_performance_lower_bound,
            "authority_neighborhood_limit": relevant_limit,
        },
    }
