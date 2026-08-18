from __future__ import annotations

import csv
from dataclasses import dataclass
from pathlib import Path
from typing import Sequence

from .bc_item_costs import BCItemCostContext
from .supplier_price_ingest import SupplierPriceChange


@dataclass(frozen=True)
class SupplierPriceComparison:
    staged: SupplierPriceChange
    status: str
    bc_match: str
    bc_description: str = ""
    bc_base_uom: str = ""
    bc_base_unit_cost: float | None = None
    bc_uom: str = ""
    bc_qty_per_uom: float | None = None
    bc_unit_cost_in_uom: float | None = None
    bc_blocked: bool = False
    bc_vendor_no: str = ""
    bc_vendor_item_no: str = ""
    supplier_current_vs_bc_pct: float | None = None
    new_cost_vs_bc_pct: float | None = None
    warnings: tuple[str, ...] = ()

    def to_dict(self) -> dict:
        row = self.staged.to_dict()
        row.update(
            {
                "comparison_status": self.status,
                "bc_match": self.bc_match,
                "bc_description": self.bc_description,
                "bc_base_uom": self.bc_base_uom,
                "bc_base_unit_cost": self.bc_base_unit_cost,
                "bc_uom": self.bc_uom,
                "bc_qty_per_uom": self.bc_qty_per_uom,
                "bc_unit_cost_in_uom": self.bc_unit_cost_in_uom,
                "bc_blocked": self.bc_blocked,
                "bc_vendor_no": self.bc_vendor_no,
                "bc_vendor_item_no": self.bc_vendor_item_no,
                "supplier_current_vs_bc_pct": self.supplier_current_vs_bc_pct,
                "new_cost_vs_bc_pct": self.new_cost_vs_bc_pct,
                "comparison_warnings": "; ".join(self.warnings),
            }
        )
        return row


def _pct_delta(value: float | None, baseline: float | None) -> float | None:
    if value is None or baseline is None or baseline == 0:
        return None
    return ((value - baseline) / abs(baseline)) * 100.0


def _same(left: str, right: str) -> bool:
    return left.strip().casefold() == right.strip().casefold()


def compare_supplier_prices_to_bc(
    staged_rows: Sequence[SupplierPriceChange],
    contexts: Sequence[BCItemCostContext],
    *,
    current_cost_tolerance_pct: float = 2.0,
) -> list[SupplierPriceComparison]:
    by_item: dict[str, list[BCItemCostContext]] = {}
    for context in contexts:
        by_item.setdefault(context.item_no.casefold(), []).append(context)

    output: list[SupplierPriceComparison] = []

    for staged in staged_rows:
        warnings: list[str] = []

        if staged.status == "REJECT":
            output.append(
                SupplierPriceComparison(
                    staged=staged,
                    status="REJECT",
                    bc_match="NOT_ATTEMPTED",
                    warnings=tuple(staged.warnings),
                )
            )
            continue

        if not staged.gpi_item_no:
            warnings.extend(staged.warnings)
            warnings.append(
                "authoritative GPI/BC item number not supplied; supplier-item mapping is not inferred"
            )
            output.append(
                SupplierPriceComparison(
                    staged=staged,
                    status="REVIEW",
                    bc_match="NO_GPI_ITEM",
                    warnings=tuple(dict.fromkeys(warnings)),
                )
            )
            continue

        item_contexts = by_item.get(staged.gpi_item_no.casefold(), [])
        if not item_contexts:
            warnings.extend(staged.warnings)
            warnings.append("GPI item was not found in the Business Central item cost/UOM context API")
            output.append(
                SupplierPriceComparison(
                    staged=staged,
                    status="REVIEW",
                    bc_match="ITEM_NOT_FOUND",
                    warnings=tuple(dict.fromkeys(warnings)),
                )
            )
            continue

        # Do not guess an alternate UOM when the supplier omitted one.
        if not staged.uom:
            context = item_contexts[0]
            warnings.extend(staged.warnings)
            warnings.append("supplier pricing UOM is missing; no BC UOM conversion was assumed")
            output.append(
                SupplierPriceComparison(
                    staged=staged,
                    status="REVIEW",
                    bc_match="ITEM_ONLY",
                    bc_description=context.description,
                    bc_base_uom=context.base_uom,
                    bc_base_unit_cost=context.base_unit_cost,
                    bc_blocked=context.blocked,
                    bc_vendor_no=context.vendor_no,
                    bc_vendor_item_no=context.vendor_item_no,
                    warnings=tuple(dict.fromkeys(warnings)),
                )
            )
            continue

        uom_context = next(
            (context for context in item_contexts if _same(context.uom, staged.uom)),
            None,
        )
        if uom_context is None:
            context = item_contexts[0]
            available = sorted({c.uom for c in item_contexts if c.uom})
            warnings.extend(staged.warnings)
            warnings.append(
                f"supplier UOM {staged.uom!r} is not configured for this BC item"
                + (f"; available UOMs: {', '.join(available)}" if available else "")
            )
            output.append(
                SupplierPriceComparison(
                    staged=staged,
                    status="REVIEW",
                    bc_match="ITEM_ONLY",
                    bc_description=context.description,
                    bc_base_uom=context.base_uom,
                    bc_base_unit_cost=context.base_unit_cost,
                    bc_blocked=context.blocked,
                    bc_vendor_no=context.vendor_no,
                    bc_vendor_item_no=context.vendor_item_no,
                    warnings=tuple(dict.fromkeys(warnings)),
                )
            )
            continue

        bc_cost = uom_context.unit_cost_in_uom
        supplier_current_delta = _pct_delta(staged.current_cost, bc_cost)
        new_cost_delta = _pct_delta(staged.new_cost, bc_cost)

        status = "READY_FOR_IMPACT"

        # Carry forward unresolved staging issues, but the missing-current-cost warning is resolved
        # when an exact BC item/UOM cost context is available.
        for warning in staged.warnings:
            if warning == "current cost not supplied; BC comparison required" and bc_cost is not None:
                continue
            warnings.append(warning)

        if staged.effective_date is None:
            status = "REVIEW"
        if not staged.supplier_name:
            status = "REVIEW"
        if staged.new_cost is None or staged.new_cost <= 0:
            status = "REJECT"
        if staged.currency and staged.currency.upper() != "USD":
            warnings.append(
                f"currency {staged.currency} is not automatically converted to BC local currency"
            )
            status = "REVIEW"
        if staged.tier_qty is not None and staged.tier_qty > 1:
            warnings.append(
                "tier quantity is greater than 1; BC Item Unit Cost is not a tier-specific vendor price"
            )
            status = "REVIEW"
        if uom_context.blocked:
            warnings.append("BC item is blocked")
            status = "REVIEW"
        if uom_context.qty_per_uom <= 0 or bc_cost is None:
            warnings.append("BC UOM conversion or current Item Unit Cost is not usable")
            status = "REVIEW"
        elif bc_cost == 0:
            warnings.append("BC Item Unit Cost is zero; supplier current-cost alignment cannot be validated")
            status = "REVIEW"

        if staged.current_cost is None and bc_cost is not None:
            warnings.append("supplier current cost not supplied; BC Item Unit Cost is used only as comparison context")
        elif supplier_current_delta is not None and abs(supplier_current_delta) > current_cost_tolerance_pct:
            warnings.append(
                "supplier-stated current cost differs materially from BC Item Unit Cost in the same UOM; "
                "verify freight, timing, vendor tier, and cost basis before impact analysis"
            )
            status = "REVIEW"

        output.append(
            SupplierPriceComparison(
                staged=staged,
                status=status,
                bc_match="EXACT_ITEM_UOM",
                bc_description=uom_context.description,
                bc_base_uom=uom_context.base_uom,
                bc_base_unit_cost=uom_context.base_unit_cost,
                bc_uom=uom_context.uom,
                bc_qty_per_uom=uom_context.qty_per_uom,
                bc_unit_cost_in_uom=bc_cost,
                bc_blocked=uom_context.blocked,
                bc_vendor_no=uom_context.vendor_no,
                bc_vendor_item_no=uom_context.vendor_item_no,
                supplier_current_vs_bc_pct=supplier_current_delta,
                new_cost_vs_bc_pct=new_cost_delta,
                warnings=tuple(dict.fromkeys(warnings)),
            )
        )

    return output


def summarize_comparisons(rows: Sequence[SupplierPriceComparison]) -> dict:
    return {
        "rows": len(rows),
        "ready_for_impact": sum(row.status == "READY_FOR_IMPACT" for row in rows),
        "review": sum(row.status == "REVIEW" for row in rows),
        "reject": sum(row.status == "REJECT" for row in rows),
        "exact_item_uom": sum(row.bc_match == "EXACT_ITEM_UOM" for row in rows),
        "item_only": sum(row.bc_match == "ITEM_ONLY" for row in rows),
        "not_found": sum(row.bc_match == "ITEM_NOT_FOUND" for row in rows),
    }


def write_comparison_csv(rows: Sequence[SupplierPriceComparison], path: str | Path) -> None:
    data = [row.to_dict() for row in rows]
    if not data:
        Path(path).write_text("", encoding="utf-8")
        return
    fieldnames = list(data[0].keys())
    with Path(path).open("w", newline="", encoding="utf-8") as handle:
        writer = csv.DictWriter(handle, fieldnames=fieldnames)
        writer.writeheader()
        writer.writerows(data)
