from __future__ import annotations

from collections import defaultdict
from datetime import datetime
from statistics import mean, median
from typing import Sequence

from .engine import Transaction


def _same(value: str, expected: str) -> bool:
    return value.strip().casefold() == expected.strip().casefold()


def _summary(lines: Sequence[Transaction], recent_count: int = 10) -> dict:
    ordered = sorted(lines, key=lambda tx: (tx.transaction_date, tx.transaction_id))
    if not ordered:
        return {
            "lines": 0,
            "customers": 0,
            "first_sale": None,
            "last_sale": None,
            "uoms": [],
            "median_price": None,
            "average_price": None,
            "weighted_average_price": None,
            "min_price": None,
            "max_price": None,
            "recent_prices": [],
            "recent_lines": [],
            "quantity": 0.0,
            "sales_amount": 0.0,
        }

    prices = [tx.unit_sell_price for tx in ordered]
    total_quantity = sum(tx.quantity for tx in ordered)
    sales_amount = sum(tx.quantity * tx.unit_sell_price for tx in ordered)
    weighted_average = sales_amount / total_quantity if total_quantity else None
    recent = ordered[-max(1, int(recent_count)) :]

    return {
        "lines": len(ordered),
        "customers": len({tx.customer_no for tx in ordered if tx.customer_no}),
        "first_sale": ordered[0].transaction_date,
        "last_sale": ordered[-1].transaction_date,
        "uoms": sorted({tx.uom for tx in ordered if tx.uom}),
        "median_price": median(prices),
        "average_price": mean(prices),
        "weighted_average_price": weighted_average,
        "min_price": min(prices),
        "max_price": max(prices),
        "recent_prices": [tx.unit_sell_price for tx in recent],
        "recent_lines": list(recent),
        "quantity": total_quantity,
        "sales_amount": sales_amount,
    }


def summarize_quote_history(
    transactions: Sequence[Transaction],
    item_no: str,
    customer_no: str = "",
    uom: str = "",
    recent_count: int = 10,
) -> dict:
    """Summarize posted history for a quote/extra item without recommending a price.

    The all-customer benchmark is context only because Gamer may have customer-specific,
    contract, or strategic pricing. Customer-specific history is broken out separately.
    """
    matching = [
        tx
        for tx in transactions
        if _same(tx.item_no, item_no)
        and tx.quantity > 0
        and tx.unit_sell_price > 0
        and (not uom or _same(tx.uom, uom))
    ]
    matching.sort(key=lambda tx: (tx.transaction_date, tx.transaction_id))

    customer_lines = (
        [tx for tx in matching if _same(tx.customer_no, customer_no)]
        if customer_no
        else []
    )

    grouped: dict[str, list[Transaction]] = defaultdict(list)
    for tx in matching:
        grouped[tx.customer_no].append(tx)

    by_customer = []
    for number, lines in grouped.items():
        stats = _summary(lines, recent_count=recent_count)
        names = [tx.customer_name for tx in lines if tx.customer_name]
        by_customer.append(
            {
                "customer_no": number,
                "customer_name": names[-1] if names else number,
                **stats,
            }
        )

    by_customer.sort(
        key=lambda row: (
            -int(row["lines"]),
            -(row["last_sale"].toordinal() if isinstance(row["last_sale"], datetime) else 0),
            str(row["customer_no"]),
        )
    )

    return {
        "item_no": item_no,
        "customer_no": customer_no,
        "uom_filter": uom,
        "all_history": _summary(matching, recent_count=recent_count),
        "customer_history": _summary(customer_lines, recent_count=recent_count),
        "by_customer": by_customer,
        "matching_lines": matching,
    }
