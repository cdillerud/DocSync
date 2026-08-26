from __future__ import annotations

from commercial_agent_contract import CommercialEvaluationRequest
from candidate_screening import (
    ScreeningDecision,
    screen_cost_change,
    screen_incorrect_item,
    screen_low_margin,
)


def screen_request(request: CommercialEvaluationRequest) -> ScreeningDecision:
    facts = request.authoritativeFacts
    context = request.context

    if request.agentType == "lowMargin":
        current = facts.get("currentMarginPct")
        historical = context.get("historical", {}).get("weightedMarginPct")
        return screen_low_margin(
            current_margin_pct=None if current is None else float(current),
            historical_margin_pct=(
                None if historical is None else float(historical)
            ),
        )

    if request.agentType == "costChange":
        return screen_cost_change(
            previous_unit_cost=float(facts.get("previousUnitCost") or 0),
            current_unit_cost=float(facts.get("currentUnitCost") or 0),
        )

    if request.agentType == "incorrectItem":
        similar = context.get("similarItems", {})
        candidates = similar.get("candidates", []) if isinstance(similar, dict) else []
        top_score = None
        if candidates:
            first = candidates[0]
            if isinstance(first, dict):
                raw = first.get("similarityScore")
                if raw is not None:
                    top_score = float(raw)

        return screen_incorrect_item(
            candidate_purchased_before=bool(
                facts.get("candidatePurchasedBefore")
            ),
            candidate_historical_line_count=int(
                facts.get("candidateHistoricalLineCount") or 0
            ),
            top_similarity_score=top_score,
        )

    raise ValueError(f"Unsupported agent type: {request.agentType}")
