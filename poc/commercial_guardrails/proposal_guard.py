from __future__ import annotations

import csv
from dataclasses import asdict, dataclass
from datetime import datetime
from pathlib import Path
from statistics import median
from typing import Dict, List, Sequence


DEFAULT_PROPOSAL_THRESHOLDS = {
    "recent_price_count": 3,
    "sell_below_recent_pct": 7.5,
    "sell_above_recent_pct": 10.0,
}


@dataclass(frozen=True)
class HistoricalLine:
    posting_date: datetime
    invoice_no: str
    order_no: str
    customer_no: str
    customer_name: str
    item_no: str
    description: str
    uom: str
    quantity: float
    unit_price: float
    net_amount: float


@dataclass(frozen=True)
class Proposal:
    customer_no: str
    item_no: str
    unit_price: float
    quantity: float
    uom: str
    customer_name: str = ""
    description: str = ""


@dataclass
class ProposalException:
    exception_type: str
    severity: str
    actual: str
    expected: str
    estimated_exposure: float
    recommended_action: str
    explanation: str

    def to_dict(self) -> dict:
        data = asdict(self)
        data["estimated_exposure"] = round(self.estimated_exposure, 2)
        return data


def _value(row: dict, *names: str) -> str:
    for name in names:
        if name in row and row[name] is not None:
            return str(row[name]).strip()
    return ""


def _parse_float(value: str | float | int | None) -> float:
    text = str(value if value is not None else "").strip()
    if not text:
        return 0.0
    text = text.replace("$", "").replace(",", "").replace("%", "")
    return float(text)


def _parse_date(value: str) -> datetime:
    text = value.strip()
    for fmt in (
        "%Y-%m-%d",
        "%m/%d/%Y",
        "%Y-%m-%dT%H:%M:%S",
        "%Y-%m-%dT%H:%M:%SZ",
        "%m/%d/%Y %I:%M:%S %p",
    ):
        try:
            return datetime.strptime(text, fmt)
        except ValueError:
            pass
    raise ValueError(f"Unsupported posting date: {value!r}")


def load_family_history(path: str | Path) -> List[HistoricalLine]:
    """Load a family-scoped history exported from the BC standard API discovery scan.

    The loader accepts both the PowerShell-friendly column names used during the POC
    (PostingDate, InvoiceNo, CustomerNo, ItemNo, UnitPrice, ...) and snake_case names.
    """
    rows: List[HistoricalLine] = []
    with open(path, newline="", encoding="utf-8-sig") as handle:
        reader = csv.DictReader(handle)
        for row in reader:
            posting_date = _value(row, "PostingDate", "posting_date", "postingDate")
            customer_no = _value(row, "CustomerNo", "customer_no", "customerNumber")
            item_no = _value(row, "ItemNo", "item_no", "lineObjectNumber")
            if not posting_date or not customer_no or not item_no:
                continue

            rows.append(
                HistoricalLine(
                    posting_date=_parse_date(posting_date),
                    invoice_no=_value(row, "InvoiceNo", "invoice_no", "number"),
                    order_no=_value(row, "OrderNo", "order_no", "orderNumber"),
                    customer_no=customer_no,
                    customer_name=_value(row, "Customer", "CustomerName", "customer_name", "customerName"),
                    item_no=item_no,
                    description=_value(row, "Description", "description"),
                    uom=_value(row, "UOM", "uom", "unitOfMeasureCode"),
                    quantity=_parse_float(_value(row, "Quantity", "quantity")),
                    unit_price=_parse_float(_value(row, "UnitPrice", "unit_price", "unitPrice")),
                    net_amount=_parse_float(_value(row, "NetAmount", "net_amount", "amountExcludingTax")),
                )
            )
    return rows


def _related_item_summary(lines: Sequence[HistoricalLine]) -> str:
    grouped: Dict[str, List[HistoricalLine]] = {}
    for line in lines:
        grouped.setdefault(line.item_no, []).append(line)

    parts = []
    for item_no, item_lines in sorted(grouped.items(), key=lambda pair: (-len(pair[1]), pair[0]))[:5]:
        latest = max(item_lines, key=lambda line: line.posting_date)
        parts.append(f"{item_no} ({len(item_lines)} lines, latest {latest.posting_date.date().isoformat()})")
    return ", ".join(parts)


def build_profile(
    history: Sequence[HistoricalLine],
    proposal: Proposal,
    recent_price_count: int = 3,
) -> dict:
    customer_family = [h for h in history if h.customer_no == proposal.customer_no]
    customer_item = [h for h in customer_family if h.item_no == proposal.item_no]
    priced = sorted(
        [h for h in customer_item if h.unit_price > 0],
        key=lambda h: (h.posting_date, h.invoice_no),
    )
    recent = priced[-max(1, recent_price_count):]

    recent_median = median([h.unit_price for h in recent]) if recent else None
    all_prices = [h.unit_price for h in priced]
    uoms = sorted({h.uom for h in customer_item if h.uom})

    return {
        "customer_family_lines": len(customer_family),
        "customer_item_lines": len(customer_item),
        "family_items": sorted({h.item_no for h in customer_family}),
        "historical_uoms": uoms,
        "first_item_sale": min((h.posting_date for h in customer_item), default=None),
        "last_item_sale": max((h.posting_date for h in customer_item), default=None),
        "all_time_min_price": min(all_prices) if all_prices else None,
        "all_time_max_price": max(all_prices) if all_prices else None,
        "recent_price_count": len(recent),
        "recent_median_price": recent_median,
        "recent_prices": [h.unit_price for h in recent],
        "related_item_summary": _related_item_summary(customer_family),
    }


def analyze_proposal(
    history: Sequence[HistoricalLine],
    proposal: Proposal,
    thresholds: Dict[str, float] | None = None,
) -> tuple[dict, List[ProposalException]]:
    cfg = dict(DEFAULT_PROPOSAL_THRESHOLDS)
    if thresholds:
        cfg.update(thresholds)

    recent_count = int(cfg["recent_price_count"])
    profile = build_profile(history, proposal, recent_count)
    customer_family = [h for h in history if h.customer_no == proposal.customer_no]
    customer_item = [h for h in customer_family if h.item_no == proposal.item_no]
    exceptions: List[ProposalException] = []

    if not customer_item:
        if customer_family:
            related = _related_item_summary(customer_family)
            exceptions.append(
                ProposalException(
                    exception_type="SIMILAR_ITEM_SUBSTITUTION",
                    severity="HIGH",
                    actual=f"No observed history for {proposal.customer_no} / {proposal.item_no}",
                    expected=f"Related family history: {related}",
                    estimated_exposure=0.0,
                    recommended_action="VERIFY ITEM SPECIFICATION BEFORE PROCESSING",
                    explanation=(
                        f"Customer {proposal.customer_no} has {len(customer_family)} prior line(s) in this "
                        "related product family but none for the proposed item. Confirm the intended SKU, "
                        "fill requirements, finish, pack method, and UOM before proceeding."
                    ),
                )
            )
        else:
            exceptions.append(
                ProposalException(
                    exception_type="FIRST_FAMILY_PURCHASE",
                    severity="MEDIUM",
                    actual=f"No related-family history for customer {proposal.customer_no}",
                    expected="Confirm new customer/product-family combination",
                    estimated_exposure=0.0,
                    recommended_action="CONFIRM PRODUCT SPECIFICATION",
                    explanation=(
                        "The supplied family history contains no prior purchase for this customer, so there "
                        "is no customer-specific item baseline to validate against."
                    ),
                )
            )
        return profile, exceptions

    known_uoms = sorted({h.uom for h in customer_item if h.uom})
    if proposal.uom and known_uoms and proposal.uom not in known_uoms:
        exceptions.append(
            ProposalException(
                exception_type="UOM_MISMATCH",
                severity="HIGH",
                actual=f"Proposed UOM {proposal.uom}",
                expected=f"Historical UOM(s): {', '.join(known_uoms)}",
                estimated_exposure=0.0,
                recommended_action="VERIFY UOM BEFORE PROCESSING",
                explanation="The proposed UOM has not been observed for this customer/item history.",
            )
        )

    reference = profile["recent_median_price"]
    if reference and reference > 0:
        diff_pct = ((proposal.unit_price - reference) / reference) * 100.0
        reference_count = profile["recent_price_count"]
        reference_text = (
            f"Recent median ${reference:.2f}/{proposal.uom or 'UOM'} "
            f"from {reference_count} transaction(s)"
        )

        if diff_pct <= -float(cfg["sell_below_recent_pct"]):
            exposure = max(0.0, (reference - proposal.unit_price) * proposal.quantity)
            exceptions.append(
                ProposalException(
                    exception_type="SELL_BELOW_CUSTOMER_HISTORY",
                    severity="HIGH",
                    actual=f"${proposal.unit_price:.2f}/{proposal.uom or 'UOM'} ({diff_pct:.1f}% vs recent median)",
                    expected=reference_text,
                    estimated_exposure=exposure,
                    recommended_action="REVIEW QUOTED SELL PRICE",
                    explanation=(
                        "The proposed sell price is materially below this customer's recent price history "
                        "for the exact same item. This is customer/item specific, not a global item average."
                    ),
                )
            )
        elif diff_pct >= float(cfg["sell_above_recent_pct"]):
            exceptions.append(
                ProposalException(
                    exception_type="SELL_ABOVE_CUSTOMER_HISTORY",
                    severity="MEDIUM",
                    actual=f"${proposal.unit_price:.2f}/{proposal.uom or 'UOM'} (+{diff_pct:.1f}% vs recent median)",
                    expected=reference_text,
                    estimated_exposure=0.0,
                    recommended_action="VERIFY PRICE CHANGE / CUSTOMER EXPECTATION",
                    explanation=(
                        "The proposed sell price is materially above this customer's recent history for the "
                        "same item. Verify that the increase is intentional and supported."
                    ),
                )
            )

    return profile, exceptions
