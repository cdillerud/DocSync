from __future__ import annotations

from statistics import median
from typing import Dict, List, Sequence

from .engine import Transaction
from .proposal_guard import Proposal, ProposalException


DEFAULT_MARGIN_THRESHOLDS = {
    "minimum_margin_history": 3,
    "recent_margin_count": 3,
    "low_gp_drop_points": 5.0,
    "minimum_gp_floor_pct": 10.0,
}


def _price_to_restore_gp(unit_cost: float, target_gp_pct: float) -> float | None:
    if target_gp_pct >= 100.0:
        return None
    denominator = 1.0 - (target_gp_pct / 100.0)
    if denominator <= 0:
        return None
    return unit_cost / denominator


def _gp_pct(unit_sell: float, unit_cost: float) -> float | None:
    if unit_sell == 0:
        return None
    return ((unit_sell - unit_cost) / unit_sell) * 100.0


def build_margin_profile(
    history: Sequence[Transaction],
    proposal: Proposal,
    recent_margin_count: int = 3,
) -> dict:
    """Build a customer/item/UOM margin profile from the validated custom BC API.

    The GPI custom API's historical Unit Cost (LCY) has been validated for the POC
    as already being on the posted sales-UOM basis for the tested M transactions.
    The latest historical cost is still only a proposal-time proxy. It is not a
    substitute for the current quote/order cost when that becomes available.
    """
    exact = sorted(
        [
            tx
            for tx in history
            if tx.customer_no == proposal.customer_no
            and tx.item_no == proposal.item_no
            and (not proposal.uom or tx.uom == proposal.uom)
            and tx.unit_sell_price > 0
            and tx.unit_cost > 0
        ],
        key=lambda tx: (tx.transaction_date, tx.transaction_id),
    )

    recent = exact[-max(1, recent_margin_count):]
    all_gp = [tx.gp_pct for tx in exact]
    recent_gp = [tx.gp_pct for tx in recent]
    latest = exact[-1] if exact else None

    latest_cost = latest.unit_cost if latest else None
    estimated_proposal_gp = (
        _gp_pct(proposal.unit_price, latest_cost)
        if latest_cost is not None and proposal.unit_price != 0
        else None
    )

    return {
        "margin_history_lines": len(exact),
        "historical_uom": proposal.uom,
        "first_margin_sale": exact[0].transaction_date if exact else None,
        "last_margin_sale": latest.transaction_date if latest else None,
        "latest_historical_cost": latest_cost,
        "latest_historical_sell": latest.unit_sell_price if latest else None,
        "all_time_median_gp_pct": median(all_gp) if all_gp else None,
        "recent_margin_count": len(recent),
        "recent_median_gp_pct": median(recent_gp) if recent_gp else None,
        "recent_gp_pct": recent_gp,
        "estimated_proposal_gp_pct": estimated_proposal_gp,
        "cost_basis": "latest posted historical Unit Cost (LCY) on sales-UOM basis",
        "cost_is_proxy": True,
    }


def analyze_proposal_margin(
    history: Sequence[Transaction],
    proposal: Proposal,
    thresholds: Dict[str, float] | None = None,
) -> tuple[dict, List[ProposalException]]:
    cfg = dict(DEFAULT_MARGIN_THRESHOLDS)
    if thresholds:
        cfg.update(thresholds)

    profile = build_margin_profile(
        history,
        proposal,
        recent_margin_count=int(cfg["recent_margin_count"]),
    )
    exceptions: List[ProposalException] = []

    if profile["margin_history_lines"] < int(cfg["minimum_margin_history"]):
        return profile, exceptions

    estimated_gp = profile["estimated_proposal_gp_pct"]
    median_gp = profile["recent_median_gp_pct"]
    latest_cost = profile["latest_historical_cost"]
    if estimated_gp is None or median_gp is None or latest_cost is None:
        return profile, exceptions

    low_threshold = max(
        float(cfg["minimum_gp_floor_pct"]),
        median_gp - float(cfg["low_gp_drop_points"]),
    )
    if estimated_gp >= low_threshold:
        return profile, exceptions

    target_sell = _price_to_restore_gp(latest_cost, median_gp)
    exposure = (
        max(0.0, (target_sell - proposal.unit_price) * proposal.quantity)
        if target_sell is not None
        else 0.0
    )

    exceptions.append(
        ProposalException(
            exception_type="LOW_GP_ANOMALY",
            severity="HIGH",
            actual=(
                f"Estimated {estimated_gp:.1f}% GP at ${proposal.unit_price:.2f}/"
                f"{proposal.uom or 'UOM'} using latest historical cost ${latest_cost:.4f}"
            ),
            expected=(
                f"Recent customer/item median {median_gp:.1f}% GP from "
                f"{profile['recent_margin_count']} transaction(s)"
            ),
            estimated_exposure=exposure,
            recommended_action="REVIEW MARGIN / CURRENT COST BEFORE RELEASE",
            explanation=(
                f"Estimated proposal GP is {median_gp - estimated_gp:.1f} percentage points below "
                "this customer's recent GP history for the exact item and UOM. The estimate uses "
                "the latest posted historical Unit Cost (LCY) as a cost proxy, so confirm the "
                "current quote/order cost before making a pricing decision."
            ),
        )
    )
    return profile, exceptions
