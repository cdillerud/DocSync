from __future__ import annotations

import csv
from dataclasses import dataclass
from datetime import datetime, timedelta
from pathlib import Path
from statistics import median
from typing import Sequence

from .engine import Transaction
from .proposal_guard import Proposal
from .proposal_special_pricing import ProposalPricingRule, matching_proposal_pricing_rules
from .supplier_price_compare import SupplierPriceComparison


@dataclass(frozen=True)
class CustomerMarginImpact:
    customer_no: str
    customer_name: str
    sales_rep: str
    history_lines: int
    last_sale: datetime
    recent_sell_median: float
    recent_cost_median: float
    projected_cost: float
    current_gp_pct: float
    projected_gp_pct: float
    gp_drop_points: float
    trailing_quantity: float
    trailing_sales: float
    estimated_margin_erosion: float
    special_pricing_protected: bool
    pricing_rule_types: tuple[str, ...]
    pricing_approvers: tuple[str, ...]

    def to_dict(self) -> dict:
        return {
            "customer_no": self.customer_no,
            "customer_name": self.customer_name,
            "sales_rep": self.sales_rep,
            "history_lines": self.history_lines,
            "last_sale": self.last_sale.date().isoformat(),
            "recent_sell_median": self.recent_sell_median,
            "recent_cost_median": self.recent_cost_median,
            "projected_cost": self.projected_cost,
            "current_gp_pct": self.current_gp_pct,
            "projected_gp_pct": self.projected_gp_pct,
            "gp_drop_points": self.gp_drop_points,
            "trailing_quantity": self.trailing_quantity,
            "trailing_sales": self.trailing_sales,
            "estimated_margin_erosion": self.estimated_margin_erosion,
            "special_pricing_protected": self.special_pricing_protected,
            "pricing_rule_types": ", ".join(self.pricing_rule_types),
            "pricing_approvers": ", ".join(self.pricing_approvers),
        }


@dataclass(frozen=True)
class SupplierMarginImpact:
    comparison: SupplierPriceComparison
    status: str
    cost_delta: float | None
    cost_delta_pct: float | None
    historical_lines: int
    historical_customers: int
    recent_posted_cost_median: float | None
    latest_posted_cost: float | None
    latest_posted_sale: datetime | None
    supplier_current_vs_posted_pct: float | None
    customer_impacts: tuple[CustomerMarginImpact, ...]
    warnings: tuple[str, ...]

    @property
    def trailing_quantity(self) -> float:
        return sum(row.trailing_quantity for row in self.customer_impacts)

    @property
    def trailing_sales(self) -> float:
        return sum(row.trailing_sales for row in self.customer_impacts)

    @property
    def estimated_margin_erosion(self) -> float:
        return sum(row.estimated_margin_erosion for row in self.customer_impacts)


def _same(left: str, right: str) -> bool:
    return left.strip().casefold() == right.strip().casefold()


def _pct_delta(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None or baseline == 0:
        return None
    return ((value - baseline) / abs(baseline)) * 100.0


def _gp_pct(sell: float, cost: float) -> float:
    if sell == 0:
        return 0.0
    return ((sell - cost) / sell) * 100.0


def _matching_history(
    transactions: Sequence[Transaction],
    item_no: str,
    uom: str,
) -> list[Transaction]:
    rows = [
        tx
        for tx in transactions
        if _same(tx.item_no, item_no)
        and _same(tx.uom, uom)
        and tx.quantity > 0
        and tx.unit_sell_price > 0
        and tx.unit_cost > 0
    ]
    rows.sort(key=lambda tx: (tx.transaction_date, tx.transaction_id))
    return rows


def _customer_impacts(
    history: Sequence[Transaction],
    *,
    item_no: str,
    uom: str,
    cost_delta: float,
    effective_date,
    pricing_rules: Sequence[ProposalPricingRule],
    recent_customer_count: int,
    trailing_days: int,
) -> list[CustomerMarginImpact]:
    if not history:
        return []

    latest_history_date = max(tx.transaction_date for tx in history)
    trailing_cutoff = latest_history_date - timedelta(days=max(1, trailing_days))

    grouped: dict[str, list[Transaction]] = {}
    for tx in history:
        grouped.setdefault(tx.customer_no, []).append(tx)

    impacts: list[CustomerMarginImpact] = []
    for customer_no, lines in grouped.items():
        ordered = sorted(lines, key=lambda tx: (tx.transaction_date, tx.transaction_id))
        recent = ordered[-max(1, int(recent_customer_count)) :]
        recent_sell = median([tx.unit_sell_price for tx in recent])
        recent_cost = median([tx.unit_cost for tx in recent])
        projected_cost = recent_cost + cost_delta
        current_gp = _gp_pct(recent_sell, recent_cost)
        projected_gp = _gp_pct(recent_sell, projected_cost)
        trailing = [tx for tx in ordered if tx.transaction_date >= trailing_cutoff]
        trailing_quantity = sum(tx.quantity for tx in trailing)
        trailing_sales = sum(tx.quantity * tx.unit_sell_price for tx in trailing)
        erosion = max(cost_delta, 0.0) * trailing_quantity

        proposal = Proposal(
            customer_no=customer_no,
            customer_name=ordered[-1].customer_name,
            item_no=item_no,
            unit_price=recent_sell,
            quantity=1.0,
            uom=uom,
        )
        matches = matching_proposal_pricing_rules(
            proposal,
            pricing_rules,
            as_of=effective_date,
        )

        sales_rep = next(
            (tx.sales_rep for tx in reversed(ordered) if tx.sales_rep),
            "",
        )
        impacts.append(
            CustomerMarginImpact(
                customer_no=customer_no,
                customer_name=ordered[-1].customer_name,
                sales_rep=sales_rep,
                history_lines=len(ordered),
                last_sale=ordered[-1].transaction_date,
                recent_sell_median=recent_sell,
                recent_cost_median=recent_cost,
                projected_cost=projected_cost,
                current_gp_pct=current_gp,
                projected_gp_pct=projected_gp,
                gp_drop_points=current_gp - projected_gp,
                trailing_quantity=trailing_quantity,
                trailing_sales=trailing_sales,
                estimated_margin_erosion=erosion,
                special_pricing_protected=bool(matches),
                pricing_rule_types=tuple(sorted({rule.rule_type for rule in matches})),
                pricing_approvers=tuple(sorted({rule.approver for rule in matches if rule.approver})),
            )
        )

    impacts.sort(
        key=lambda row: (
            -row.estimated_margin_erosion,
            row.projected_gp_pct,
            row.customer_no,
        )
    )
    return impacts


def analyze_supplier_margin_impact(
    comparison: SupplierPriceComparison,
    transactions: Sequence[Transaction],
    *,
    pricing_rules: Sequence[ProposalPricingRule] = (),
    recent_item_cost_count: int = 10,
    recent_customer_count: int = 3,
    history_alignment_tolerance_pct: float = 5.0,
    trailing_days: int = 365,
) -> SupplierMarginImpact:
    staged = comparison.staged
    warnings: list[str] = []

    if comparison.status == "REJECT" or staged.new_cost is None or staged.new_cost <= 0:
        return SupplierMarginImpact(
            comparison=comparison,
            status="REJECT",
            cost_delta=None,
            cost_delta_pct=None,
            historical_lines=0,
            historical_customers=0,
            recent_posted_cost_median=None,
            latest_posted_cost=None,
            latest_posted_sale=None,
            supplier_current_vs_posted_pct=None,
            customer_impacts=(),
            warnings=tuple(dict.fromkeys([*staged.warnings, *comparison.warnings])),
        )

    if not staged.gpi_item_no or comparison.bc_match != "EXACT_ITEM_UOM" or not staged.uom:
        warnings.extend(staged.warnings)
        warnings.append("exact BC item and supplier UOM match is required for margin impact analysis")
        return SupplierMarginImpact(
            comparison=comparison,
            status="REVIEW",
            cost_delta=None,
            cost_delta_pct=None,
            historical_lines=0,
            historical_customers=0,
            recent_posted_cost_median=None,
            latest_posted_cost=None,
            latest_posted_sale=None,
            supplier_current_vs_posted_pct=None,
            customer_impacts=(),
            warnings=tuple(dict.fromkeys(warnings)),
        )

    history = _matching_history(transactions, staged.gpi_item_no, staged.uom)
    recent_item = history[-max(1, int(recent_item_cost_count)) :]
    recent_posted_cost = median([tx.unit_cost for tx in recent_item]) if recent_item else None
    latest_posted_cost = history[-1].unit_cost if history else None
    latest_posted_sale = history[-1].transaction_date if history else None
    current_vs_posted = _pct_delta(staged.current_cost, recent_posted_cost)
    cost_delta = (
        staged.new_cost - staged.current_cost
        if staged.current_cost is not None and staged.new_cost is not None
        else None
    )
    cost_delta_pct = (
        ((staged.new_cost - staged.current_cost) / abs(staged.current_cost)) * 100.0
        if staged.current_cost not in {None, 0} and staged.new_cost is not None
        else None
    )

    status = "IMPACT_READY"

    if staged.current_cost is None or staged.current_cost <= 0:
        warnings.append("supplier current cost is required to calculate a supplier cost delta")
        status = "REVIEW"
    if staged.effective_date is None:
        warnings.append("effective date is required before margin impact can be treated as actionable")
        status = "REVIEW"
    if staged.currency and staged.currency.upper() != "USD":
        warnings.append("non-USD supplier pricing is not converted automatically")
        status = "REVIEW"
    if staged.tier_qty is not None and staged.tier_qty > 1:
        warnings.append("tier-specific supplier pricing requires quantity-tier validation before impact analysis")
        status = "REVIEW"
    if comparison.bc_blocked:
        warnings.append("BC item is blocked")
        status = "REVIEW"
    if not history:
        warnings.append("no positive posted sales/cost history exists for this exact item and UOM")
        status = "REVIEW"
    elif current_vs_posted is None:
        warnings.append("supplier current cost cannot be aligned to recent posted Unit Cost (LCY)")
        status = "REVIEW"
    elif abs(current_vs_posted) > history_alignment_tolerance_pct:
        warnings.append(
            "supplier current cost differs materially from the recent posted Unit Cost (LCY) median; "
            "verify supplier, freight, timing, tier, and historical cost basis before using the delta"
        )
        status = "REVIEW"

    if comparison.status == "REVIEW" and status == "IMPACT_READY":
        warnings.append(
            "BC Item Unit Cost context is not aligned, but the supplier current cost aligns to recent "
            "posted Unit Cost (LCY); this scenario applies only the supplier cost delta to posted history"
        )

    customer_impacts: list[CustomerMarginImpact] = []
    if cost_delta is not None and history:
        customer_impacts = _customer_impacts(
            history,
            item_no=staged.gpi_item_no,
            uom=staged.uom,
            cost_delta=cost_delta,
            effective_date=staged.effective_date,
            pricing_rules=pricing_rules,
            recent_customer_count=recent_customer_count,
            trailing_days=trailing_days,
        )

    return SupplierMarginImpact(
        comparison=comparison,
        status=status,
        cost_delta=cost_delta,
        cost_delta_pct=cost_delta_pct,
        historical_lines=len(history),
        historical_customers=len({tx.customer_no for tx in history if tx.customer_no}),
        recent_posted_cost_median=recent_posted_cost,
        latest_posted_cost=latest_posted_cost,
        latest_posted_sale=latest_posted_sale,
        supplier_current_vs_posted_pct=current_vs_posted,
        customer_impacts=tuple(customer_impacts),
        warnings=tuple(dict.fromkeys(warnings)),
    )


def summarize_supplier_impacts(rows: Sequence[SupplierMarginImpact]) -> dict:
    return {
        "rows": len(rows),
        "impact_ready": sum(row.status == "IMPACT_READY" for row in rows),
        "review": sum(row.status == "REVIEW" for row in rows),
        "reject": sum(row.status == "REJECT" for row in rows),
        "customers": sum(len(row.customer_impacts) for row in rows),
        "protected_customers": sum(
            impact.special_pricing_protected
            for row in rows
            for impact in row.customer_impacts
        ),
        "estimated_margin_erosion": sum(row.estimated_margin_erosion for row in rows),
    }


def write_supplier_impact_csv(rows: Sequence[SupplierMarginImpact], path: str | Path) -> None:
    output: list[dict] = []
    for row in rows:
        staged = row.comparison.staged
        base = {
            "impact_status": row.status,
            "supplier_name": staged.supplier_name,
            "supplier_item_no": staged.supplier_item_no,
            "gpi_item_no": staged.gpi_item_no,
            "uom": staged.uom,
            "effective_date": staged.effective_date.isoformat() if staged.effective_date else "",
            "supplier_current_cost": staged.current_cost,
            "supplier_new_cost": staged.new_cost,
            "supplier_cost_delta": row.cost_delta,
            "supplier_cost_delta_pct": row.cost_delta_pct,
            "bc_match": row.comparison.bc_match,
            "bc_item_unit_cost_in_uom": row.comparison.bc_unit_cost_in_uom,
            "historical_lines": row.historical_lines,
            "historical_customers": row.historical_customers,
            "recent_posted_cost_median": row.recent_posted_cost_median,
            "latest_posted_cost": row.latest_posted_cost,
            "latest_posted_sale": row.latest_posted_sale.date().isoformat() if row.latest_posted_sale else "",
            "supplier_current_vs_posted_pct": row.supplier_current_vs_posted_pct,
            "impact_warnings": "; ".join(row.warnings),
            "source_file": staged.source_file,
            "source_sheet": staged.source_sheet,
            "source_row": staged.source_row,
        }
        if row.customer_impacts:
            for customer in row.customer_impacts:
                output.append({**base, **customer.to_dict()})
        else:
            output.append(base)

    if not output:
        Path(path).write_text("", encoding="utf-8")
        return

    fieldnames: list[str] = []
    for record in output:
        for key in record:
            if key not in fieldnames:
                fieldnames.append(key)

    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(output)
