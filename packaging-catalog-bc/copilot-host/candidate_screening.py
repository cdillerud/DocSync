from __future__ import annotations

from dataclasses import dataclass


@dataclass(frozen=True)
class ScreeningDecision:
    should_evaluate: bool
    reasons: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "shouldEvaluate": self.should_evaluate,
            "reasons": list(self.reasons),
        }


def screen_low_margin(
    *,
    current_margin_pct: float | None,
    historical_margin_pct: float | None,
    hard_floor_pct: float = 20.0,
    variance_threshold_points: float = 8.0,
) -> ScreeningDecision:
    reasons: list[str] = []

    if current_margin_pct is None:
        return ScreeningDecision(
            should_evaluate=True,
            reasons=("Current margin is unavailable; AI review requires context.",),
        )

    if current_margin_pct < hard_floor_pct:
        reasons.append(
            f"Current margin {current_margin_pct:.2f}% is below hard floor "
            f"{hard_floor_pct:.2f}%."
        )

    if historical_margin_pct is not None:
        variance = historical_margin_pct - current_margin_pct
        if variance >= variance_threshold_points:
            reasons.append(
                f"Current margin is {variance:.2f} points below the "
                "historical customer/item margin."
            )

    return ScreeningDecision(bool(reasons), tuple(reasons))


def screen_cost_change(
    *,
    previous_unit_cost: float,
    current_unit_cost: float,
    minimum_change_pct: float = 2.0,
    minimum_absolute_change: float = 0.01,
) -> ScreeningDecision:
    delta = current_unit_cost - previous_unit_cost
    reasons: list[str] = []

    if abs(delta) < minimum_absolute_change:
        return ScreeningDecision(False, ())

    if previous_unit_cost == 0:
        reasons.append("Prior unit cost is zero; percentage change is undefined.")
    else:
        change_pct = abs(delta / previous_unit_cost) * 100
        if change_pct >= minimum_change_pct:
            reasons.append(
                f"Unit cost changed {change_pct:.2f}%, meeting the "
                f"{minimum_change_pct:.2f}% evaluation threshold."
            )

    return ScreeningDecision(bool(reasons), tuple(reasons))


def screen_incorrect_item(
    *,
    candidate_purchased_before: bool,
    candidate_historical_line_count: int,
    top_similarity_score: float | None,
    similarity_threshold: float = 85.0,
) -> ScreeningDecision:
    reasons: list[str] = []

    if not candidate_purchased_before:
        reasons.append("Customer has no posted-sales history for the candidate item.")

    if candidate_historical_line_count <= 1:
        reasons.append("Candidate item has little or no customer purchase history.")

    if (
        top_similarity_score is not None
        and top_similarity_score >= similarity_threshold
    ):
        reasons.append(
            f"A Packaging Catalog alternative scores {top_similarity_score:.1f}% "
            "similarity, creating plausible wrong-SKU risk."
        )

    return ScreeningDecision(bool(reasons), tuple(reasons))
