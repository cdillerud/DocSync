from __future__ import annotations

import argparse
from dataclasses import dataclass
from typing import Mapping, Sequence

from .bc_adapter import BCConfig, BusinessCentralClient, BusinessCentralError


@dataclass(frozen=True)
class CostProbeRow:
    posting_date: str
    invoice_no: str
    order_no: str
    customer_no: str
    item_no: str
    description: str
    uom: str
    quantity: float
    quantity_base: float
    base_units_per_sales_uom: float
    unit_cost_lcy_raw: float
    unit_price: float
    line_amount: float
    net_unit_sell: float
    base_scaled_cost_candidate: float
    gp_pct_raw_cost: float | None
    gp_pct_base_scaled_cost: float | None


def _float(value: object) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return 0.0


def _gp_pct(sell: float, cost: float) -> float | None:
    if sell == 0:
        return None
    return ((sell - cost) / sell) * 100.0


def normalize_cost_probe_rows(rows: Sequence[Mapping[str, object]]) -> list[CostProbeRow]:
    normalized: list[CostProbeRow] = []

    for row in rows:
        line_type = str(row.get("lineType") or "").strip().casefold()
        if line_type and line_type != "item":
            continue

        quantity = _float(row.get("quantity"))
        quantity_base = _float(row.get("quantityBase"))
        if quantity == 0:
            continue

        line_amount = _float(row.get("lineAmount"))
        raw_cost = _float(row.get("unitCostLCY"))
        net_unit_sell = line_amount / quantity
        factor = abs(quantity_base / quantity) if quantity_base else 1.0
        scaled_cost = raw_cost * factor

        normalized.append(
            CostProbeRow(
                posting_date=str(row.get("postingDate") or "").strip(),
                invoice_no=str(row.get("invoiceNo") or "").strip(),
                order_no=str(row.get("orderNo") or "").strip(),
                customer_no=str(row.get("customerNo") or "").strip(),
                item_no=str(row.get("itemNo") or "").strip(),
                description=str(row.get("description") or "").strip(),
                uom=str(row.get("unitOfMeasureCode") or "").strip(),
                quantity=quantity,
                quantity_base=quantity_base,
                base_units_per_sales_uom=factor,
                unit_cost_lcy_raw=raw_cost,
                unit_price=_float(row.get("unitPrice")),
                line_amount=line_amount,
                net_unit_sell=net_unit_sell,
                base_scaled_cost_candidate=scaled_cost,
                gp_pct_raw_cost=_gp_pct(net_unit_sell, raw_cost),
                gp_pct_base_scaled_cost=_gp_pct(net_unit_sell, scaled_cost),
            )
        )

    normalized.sort(key=lambda r: (r.posting_date, r.invoice_no))
    return normalized


def _fmt_gp(value: float | None) -> str:
    return "n/a" if value is None else f"{value:.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read the GPI custom historical-sales API and expose raw versus UOM-scaled "
            "cost math before enabling GP guardrails. No Business Central writes are performed."
        )
    )
    parser.add_argument("--customer", required=True, help="Exact BC customer number")
    parser.add_argument("--item", required=True, help="Exact BC item number")
    parser.add_argument("--start-date", default="2024-01-01", help="Posting date lower bound")
    parser.add_argument("--end-date", default="", help="Posting date upper bound")
    args = parser.parse_args()

    try:
        config = BCConfig.from_env(source="custom")
        client = BusinessCentralClient(config)
        raw_rows = client.fetch_custom_historical_sales_lines(
            start_date=args.start_date,
            end_date=args.end_date,
            item_nos=[args.item],
            customer_nos=[args.customer],
        )
    except BusinessCentralError as exc:
        parser.error(str(exc))

    rows = normalize_cost_probe_rows(raw_rows)
    if not rows:
        print("No matching item lines were returned by the custom API query.")
        return 2

    print("\n================================================================================")
    print("GPI COMMERCIAL GUARDRAIL - BC COST / UOM PROBE")
    print("================================================================================")
    print(f"BC environment : {config.environment}")
    print(f"Customer       : {args.customer}")
    print(f"Item           : {args.item}")
    print(f"Rows           : {len(rows)}")
    print("\nIMPORTANT: GP is not yet authoritative. This probe shows both possible cost bases")
    print("so we can verify how BC Unit Cost (LCY) behaves when the sales UOM is not the base UOM.\n")

    for row in rows:
        print(f"{row.posting_date} | Inv {row.invoice_no} | Order {row.order_no}")
        print(
            f"  Qty {row.quantity:g} {row.uom} | Qty Base {row.quantity_base:g} | "
            f"Base/Sales UOM {row.base_units_per_sales_uom:g}"
        )
        print(
            f"  Unit Price ${row.unit_price:,.4f} | Net Unit Sell ${row.net_unit_sell:,.4f} | "
            f"Line ${row.line_amount:,.2f}"
        )
        print(
            f"  Raw Unit Cost LCY ${row.unit_cost_lcy_raw:,.6f} | "
            f"GP if raw {_fmt_gp(row.gp_pct_raw_cost)}"
        )
        print(
            f"  Cost x UOM factor ${row.base_scaled_cost_candidate:,.4f} | "
            f"GP if scaled {_fmt_gp(row.gp_pct_base_scaled_cost)}"
        )

    factors = sorted({round(row.base_units_per_sales_uom, 6) for row in rows})
    print("--------------------------------------------------------------------------------")
    print(f"Observed base-units-per-sales-UOM factor(s): {', '.join(str(f) for f in factors)}")
    print("Do not enable GP alerts until the raw/scaled cost interpretation is validated against BC.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
