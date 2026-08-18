from __future__ import annotations

import argparse
from pathlib import Path

from .bc_adapter import BCConfig, BusinessCentralClient, BusinessCentralError
from .bc_item_costs import fetch_bc_item_cost_contexts
from .supplier_price_compare import (
    compare_supplier_prices_to_bc,
    summarize_comparisons,
    write_comparison_csv,
)
from .supplier_price_ingest import load_supplier_notice


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.4f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize a local supplier price notice and compare exact GPI item/UOM rows against "
            "read-only Business Central Item Unit Cost and Item Unit of Measure context. No BC writes."
        )
    )
    parser.add_argument("--input", required=True, help="Local CSV/XLSX/XLSM supplier notice")
    parser.add_argument("--supplier", default="", help="Default supplier name when the file omits it")
    parser.add_argument("--sheet", default="", help="Optional Excel worksheet name")
    parser.add_argument("--out", default="", help="Optional comparison CSV output")
    parser.add_argument("--show", type=int, default=50, help="Maximum compared rows to display")
    parser.add_argument(
        "--current-cost-tolerance-pct",
        type=float,
        default=2.0,
        help="Supplier-stated current cost variance from BC Item Unit Cost that triggers review",
    )
    args = parser.parse_args()

    try:
        staged = load_supplier_notice(
            args.input,
            default_supplier=args.supplier,
            sheet_name=args.sheet,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))

    item_nos = sorted({row.gpi_item_no for row in staged if row.gpi_item_no})

    try:
        config = BCConfig.from_env(source="custom")
        client = BusinessCentralClient(config)
        contexts = fetch_bc_item_cost_contexts(client, item_nos=item_nos)
    except (BusinessCentralError, ValueError) as exc:
        parser.error(str(exc))

    compared = compare_supplier_prices_to_bc(
        staged,
        contexts,
        current_cost_tolerance_pct=args.current_cost_tolerance_pct,
    )
    summary = summarize_comparisons(compared)

    print("\n============================================================")
    print("GPI COMMERCIAL GUARDRAIL - SUPPLIER PRICE / BC COMPARISON")
    print("============================================================")
    print(f"BC environment     : {config.environment}")
    print(f"Input file         : {Path(args.input).resolve()}")
    print(f"Supplier rows      : {summary['rows']}")
    print(f"BC context rows    : {len(contexts)}")
    print(f"Exact item + UOM   : {summary['exact_item_uom']}")
    print(f"Item-only matches  : {summary['item_only']}")
    print(f"BC item not found  : {summary['not_found']}")
    print(f"READY_FOR_IMPACT   : {summary['ready_for_impact']}")
    print(f"REVIEW             : {summary['review']}")
    print(f"REJECT             : {summary['reject']}")

    if compared and args.show > 0:
        print("\nSUPPLIER PRICE COMPARISONS")
        for index, row in enumerate(compared[: args.show], start=1):
            staged_row = row.staged
            item = staged_row.gpi_item_no or staged_row.supplier_item_no or "<missing item>"
            effective = staged_row.effective_date.isoformat() if staged_row.effective_date else "n/a"
            print(f"\n{index}. [{row.status}] {item}")
            print(f"   BC match        : {row.bc_match}")
            print(f"   Supplier        : {staged_row.supplier_name or 'n/a'}")
            if staged_row.supplier_item_no:
                print(f"   Supplier item   : {staged_row.supplier_item_no}")
            if staged_row.gpi_item_no:
                print(f"   GPI item        : {staged_row.gpi_item_no}")
            if row.bc_description:
                print(f"   BC description  : {row.bc_description}")
            print(f"   Effective       : {effective}")
            print(f"   Supplier UOM    : {staged_row.uom or 'n/a'}")
            if row.bc_base_uom:
                print(f"   BC base UOM     : {row.bc_base_uom}")
            if row.bc_uom:
                print(f"   BC matched UOM  : {row.bc_uom}")
            if row.bc_qty_per_uom is not None:
                print(f"   Qty per BC UOM  : {row.bc_qty_per_uom:g} base unit(s)")
            if row.bc_base_unit_cost is not None:
                print(f"   BC base cost    : {_money(row.bc_base_unit_cost)}/{row.bc_base_uom or 'BASE'}")
            if row.bc_unit_cost_in_uom is not None:
                print(f"   BC cost in UOM  : {_money(row.bc_unit_cost_in_uom)}/{row.bc_uom or staged_row.uom}")
            print(f"   Supplier current: {_money(staged_row.current_cost)}/{staged_row.uom or 'UOM'}")
            print(f"   Supplier new    : {_money(staged_row.new_cost)}/{staged_row.uom or 'UOM'}")
            if row.supplier_current_vs_bc_pct is not None:
                print(f"   Current vs BC   : {_pct(row.supplier_current_vs_bc_pct)}")
            if row.new_cost_vs_bc_pct is not None:
                print(f"   New vs BC       : {_pct(row.new_cost_vs_bc_pct)}")
            if row.bc_vendor_no or row.bc_vendor_item_no:
                print(
                    f"   BC vendor ctx   : {row.bc_vendor_no or 'n/a'} / "
                    f"{row.bc_vendor_item_no or 'n/a'}"
                )
            if row.bc_blocked:
                print("   BC blocked      : YES")
            if row.warnings:
                print(f"   Review notes    : {'; '.join(row.warnings)}")
            print(
                f"   Source          : {staged_row.source_file}"
                + (f" / {staged_row.source_sheet}" if staged_row.source_sheet else "")
                + f" row {staged_row.source_row}"
            )

    if args.out:
        write_comparison_csv(compared, args.out)
        print(f"\nComparison CSV written to: {Path(args.out).resolve()}")

    print("\nSAFETY NOTE")
    print(
        "  BC Item Unit Cost is inventory/current-cost context, not an automatically authoritative "
        "vendor price. READY_FOR_IMPACT only means the supplier row has an exact BC item/UOM match "
        "and enough clean context to proceed to margin-impact analysis. This command does not update "
        "items, vendor prices, purchase prices, sales prices, or any other Business Central record."
    )

    return 1 if summary["review"] or summary["reject"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
