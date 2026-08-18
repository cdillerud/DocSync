from __future__ import annotations

from collections import Counter
from statistics import median
from typing import Dict, Sequence

from .engine import Transaction
from .proposal_guard import Proposal, ProposalException


DEFAULT_QUOTE_THRESHOLDS: Dict[str, float] = {
    "minimum_customer_history": 3,
    "recent_count": 5,
    "below_customer_pct": 7.5,
    "above_customer_pct": 15.0,
    "high_deviation_pct": 15.0,
    "dominant_price_high_confidence_share": 0.80,
}


def _same(left: str, right: str) -> bool:
    return left.strip().casefold() == right.strip().casefold()


def _pct_delta(actual: float, baseline: float) -> float:
    if baseline == 0:
        return 0.0
    return ((actual - baseline) / baseline) * 100.0


def _dominant_price(prices: Sequence[float]) -> tuple[float | None, float]:
    if not prices:
        return None, 0.0
    rounded = [round(float(price), 4) for price in prices]
    counts = Counter(rounded)
    price, count = counts.most_common(1)[0]
    return float(price), count / len(rounded)


def analyze_quote_extra(
    transactions: Sequence[Transaction],
    proposal: Proposal,
    thresholds: Dict[str, float] | None = None,
) -> tuple[dict, list[ProposalException]]:
    """Evaluate a proposed quote/extra price using posted item history.

    Customer-specific exact-item/UOM history is the only source that can trigger a
    price exception. All-customer history is retained as lower-confidence context and
    never becomes an authoritative recommendation by itself.
    """
    cfg = dict(DEFAULT_QUOTE_THRESHOLDS)
    if thresholds:
        cfg.update(thresholds)

    matching = [
        tx
        for tx in transactions
        if _same(tx.item_no, proposal.item_no)
        and tx.quantity > 0
        and tx.unit_sell_price > 0
        and (not proposal.uom or _same(tx.uom, proposal.uom))
    ]
    matching.sort(key=lambda tx: (tx.transaction_date, tx.transaction_id))

    customer_lines = [tx for tx in matching if _same(tx.customer_no, proposal.customer_no)]
    customer_prices = [tx.unit_sell_price for tx in customer_lines]
    all_prices = [tx.unit_sell_price for tx in matching]

    recent_count = max(1, int(cfg["recent_count"]))
    recent_lines = customer_lines[-recent_count:]
    recent_prices = [tx.unit_sell_price for tx in recent_lines]

    customer_median = median(customer_prices) if customer_prices else None
    recent_median = median(recent_prices) if recent_prices else None
    all_median = median(all_prices) if all_prices else None
    dominant_price, dominant_share = _dominant_price(customer_prices)

    if len(customer_lines) >= 5:
        confidence = "HIGH"
    elif len(customer_lines) >= int(cfg["minimum_customer_history"]):
        confidence = "MEDIUM"
    else:
        confidence = "LOW"

    profile = {
        "customer_history_lines": len(customer_lines),
        "all_history_lines": len(matching),
        "all_history_customers": len({tx.customer_no for tx in matching if tx.customer_no}),
        "confidence": confidence,
        "customer_median_price": customer_median,
        "recent_median_price": recent_median,
        "recent_price_count": len(recent_prices),
        "recent_prices": recent_prices,
        "dominant_customer_price": dominant_price,
        "dominant_customer_price_share": dominant_share,
        "customer_min_price": min(customer_prices) if customer_prices else None,
        "customer_max_price": max(customer_prices) if customer_prices else None,
        "all_median_price": all_median,
        "all_min_price": min(all_prices) if all_prices else None,
        "all_max_price": max(all_prices) if all_prices else None,
        "last_customer_sale": customer_lines[-1].transaction_date if customer_lines else None,
        "last_all_sale": matching[-1].transaction_date if matching else None,
        "benchmark_source": "CUSTOMER" if len(customer_lines) >= int(cfg["minimum_customer_history"]) else "BROAD_CONTEXT_ONLY",
    }

    exceptions: list[ProposalException] = []
    if len(customer_lines) < int(cfg["minimum_customer_history"]):
        return profile, exceptions

    baseline = recent_median if recent_median is not None else customer_median
    if baseline is None or baseline <= 0:
        return profile, exceptions

    delta_pct = _pct_delta(proposal.unit_price, baseline)
    high_confidence_pattern = dominant_share >= float(cfg["dominant_price_high_confidence_share"])
    high_deviation = abs(delta_pct) >= float(cfg["high_deviation_pct"])
    severity = "HIGH" if high_confidence_pattern or high_deviation else "MEDIUM"

    if delta_pct <= -float(cfg["below_customer_pct"]):
        variance = max(0.0, (baseline - proposal.unit_price) * proposal.quantity)
        exceptions.append(
            ProposalException(
                exception_type="QUOTE_BELOW_CUSTOMER_HISTORY",
                severity=severity,
                actual=f"${proposal.unit_price:.2f}/{proposal.uom} ({delta_pct:.1f}% vs recent median)",
                expected=(
                    f"Recent customer/item median ${baseline:.2f}/{proposal.uom} "
                    f"from {len(recent_prices)} transaction(s)"
                ),
                estimated_exposure=variance,
                recommended_action="REVIEW PROPOSED EXTRA PRICE AGAINST CUSTOMER HISTORY",
                explanation=(
                    "The proposed quote/extra price is materially below this customer's recent "
                    "posted price history for the exact item and UOM. This is a review signal, "
                    "not an automatic replacement-price recommendation."
                ),
            )
        )

    if delta_pct >= float(cfg["above_customer_pct"]):
        variance = max(0.0, (proposal.unit_price - baseline) * proposal.quantity)
        exceptions.append(
            ProposalException(
                exception_type="QUOTE_ABOVE_CUSTOMER_HISTORY",
                severity=severity,
                actual=f"${proposal.unit_price:.2f}/{proposal.uom} (+{delta_pct:.1f}% vs recent median)",
                expected=(
                    f"Recent customer/item median ${baseline:.2f}/{proposal.uom} "
                    f"from {len(recent_prices)} transaction(s)"
                ),
                estimated_exposure=variance,
                recommended_action="REVIEW PROPOSED EXTRA PRICE AGAINST CUSTOMER HISTORY",
                explanation=(
                    "The proposed quote/extra price is materially above this customer's recent "
                    "posted price history for the exact item and UOM. Confirm the scope and customer "
                    "expectation before quoting."
                ),
            )
        )

    return profile, exceptions
