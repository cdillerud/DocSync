from __future__ import annotations

import argparse
from pathlib import Path

from .bc_adapter import BCConfig, BusinessCentralClient, BusinessCentralError
from .bc_item_costs import fetch_bc_item_cost_contexts
from .bc_pricing_rules import fetch_bc_pricing_rules
from .supplier_margin_impact import (
    analyze_supplier_margin_impact,
    summarize_supplier_impacts,
    write_supplier_impact_csv,
)
from .supplier_price_compare import compare_supplier_prices_to_bc
from .supplier_price_ingest import load_supplier_notice


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def _money4(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.4f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Apply supplier-provided cost deltas to read-only posted Business Central sales/cost history "
            "to estimate customer margin exposure. No Business Central writes are performed."
        )
    )
    parser.add_argument("--input", required=True, help="Local CSV/XLSX/XLSM supplier notice")
    parser.add_argument("--supplier", default="", help="Default supplier name when the file omits it")
    parser.add_argument("--sheet", default="", help="Optional Excel worksheet name")
    parser.add_argument("--start-date", default="2024-01-01", help="Posted history start, YYYY-MM-DD")
    parser.add_argument("--end-date", default="", help="Optional posted history end, YYYY-MM-DD")
    parser.add_argument(
        "--history-alignment-tolerance-pct",
        type=float,
        default=5.0,
        help="Maximum supplier-current variance from recent posted cost median before review",
    )
    parser.add_argument(
        "--max-recent-cost-spread-pct",
        type=float,
        default=15.0,
        help="Maximum recent posted cost range as a percentage of median before the item is treated as heterogeneous",
    )
    parser.add_argument(
        "--recent-item-cost-count",
        type=int,
        default=10,
        help="Recent item/UOM posted cost lines used to validate the supplier current cost",
    )
    parser.add_argument(
        "--recent-customer-count",
        type=int,
        default=3,
        help="Recent customer/item/UOM lines used for sell and cost baselines",
    )
    parser.add_argument(
        "--trailing-days",
        type=int,
        default=365,
        help="Historical volume window used for estimated margin-dollar erosion",
    )
    parser.add_argument(
        "--include-review-scenarios",
        action="store_true",
        help=(
            "Also calculate customer-level what-if scenarios for REVIEW rows. These remain excluded "
            "from actionable headline totals."
        ),
    )
    parser.add_argument("--show-customers", type=int, default=25, help="Maximum customer impacts per item")
    parser.add_argument("--out", default="", help="Optional flattened supplier/customer impact CSV")
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
        comparisons = compare_supplier_prices_to_bc(staged, contexts)
        pricing_rules = fetch_bc_pricing_rules(client)
        transactions = client.fetch_transactions(
            start_date=args.start_date,
            end_date=args.end_date,
            item_nos=item_nos,
        )
    except (BusinessCentralError, ValueError) as exc:
        parser.error(str(exc))

    impacts = [
        analyze_supplier_margin_impact(
            comparison,
            transactions,
            pricing_rules=pricing_rules,
            recent_item_cost_count=args.recent_item_cost_count,
            recent_customer_count=args.recent_customer_count,
            history_alignment_tolerance_pct=args.history_alignment_tolerance_pct,
            max_recent_cost_spread_pct=args.max_recent_cost_spread_pct,
            trailing_days=args.trailing_days,
            include_review_scenarios=args.include_review_scenarios,
        )
        for comparison in comparisons
    ]
    summary = summarize_supplier_impacts(impacts)

    print("\n============================================================")
    print("GPI COMMERCIAL GUARDRAIL - SUPPLIER COST MARGIN IMPACT")
    print("============================================================")
    print(f"BC environment       : {config.environment}")
    print(f"Input file           : {Path(args.input).resolve()}")
    print(f"History window       : {args.start_date} through {args.end_date or 'latest'}")
    print(f"Supplier rows        : {summary['rows']}")
    print(f"IMPACT_READY         : {summary['impact_ready']}")
    print(f"REVIEW               : {summary['review']}")
    print(f"REJECT               : {summary['reject']}")
    print(f"Actionable customers : {summary['customers']}")
    print(f"Protected actionable : {summary['protected_customers']}")
    print(f"Actionable erosion   : {_money(summary['estimated_margin_erosion'])}")
    if summary["review_scenario_customers"]:
        print(f"Review scenarios     : {summary['review_scenario_customers']} customer(s)")
        print(f"Review-only erosion  : {_money(summary['review_scenario_margin_erosion'])}")
    print(f"Pricing rules read   : {len(pricing_rules)}")

    for index, row in enumerate(impacts, start=1):
        staged_row = row.comparison.staged
        item = staged_row.gpi_item_no or staged_row.supplier_item_no or "<missing item>"
        print("\n------------------------------------------------------------")
        print(f"{index}. [{row.status}] {item}")
        print(f"   Supplier        : {staged_row.supplier_name or 'n/a'}")
        if staged_row.supplier_item_no:
            print(f"   Supplier item   : {staged_row.supplier_item_no}")
        print(f"   BC match        : {row.comparison.bc_match}")
        print(f"   UOM             : {staged_row.uom or 'n/a'}")
        print(f"   Supplier current: {_money4(staged_row.current_cost)}/{staged_row.uom or 'UOM'}")
        print(f"   Supplier new    : {_money4(staged_row.new_cost)}/{staged_row.uom or 'UOM'}")
        print(f"   Supplier delta  : {_money4(row.cost_delta)} ({_pct(row.cost_delta_pct)})")
        if row.comparison.bc_unit_cost_in_uom is not None:
            print(
                f"   BC Item cost ctx: {_money4(row.comparison.bc_unit_cost_in_uom)}/"
                f"{row.comparison.bc_uom or staged_row.uom}"
            )
        print(f"   Posted hist lines: {row.historical_lines}")
        print(f"   Posted customers : {row.historical_customers}")
        print(
            f"   Recent posted cost: {_money4(row.recent_posted_cost_median)}/"
            f"{staged_row.uom or 'UOM'}"
        )
        if row.recent_posted_cost_min is not None and row.recent_posted_cost_max is not None:
            print(
                f"   Recent cost range : {_money4(row.recent_posted_cost_min)} to "
                f"{_money4(row.recent_posted_cost_max)}/{staged_row.uom or 'UOM'}"
            )
        if row.recent_posted_cost_spread_pct is not None:
            print(f"   Recent cost spread: {row.recent_posted_cost_spread_pct:.1f}% of median")
        if row.latest_posted_sale is not None:
            print(f"   Latest posted sale: {row.latest_posted_sale.date().isoformat()}")
        if row.latest_posted_cost is not None:
            print(f"   Latest posted cost: {_money4(row.latest_posted_cost)}/{staged_row.uom or 'UOM'}")
        if row.supplier_current_vs_posted_pct is not None:
            print(f"   Current vs posted: {_pct(row.supplier_current_vs_posted_pct)}")
        print(f"   Trailing quantity: {row.trailing_quantity:,.2f} {staged_row.uom or ''}".rstrip())
        print(f"   Trailing sales   : {_money(row.trailing_sales)}")
        label = "Est. erosion" if row.status == "IMPACT_READY" else "Review-only erosion"
        print(f"   {label:<17}: {_money(row.estimated_margin_erosion)}")
        if row.warnings:
            print(f"   Review notes     : {'; '.join(row.warnings)}")

        if row.customer_impacts and args.show_customers > 0:
            heading = "CUSTOMER MARGIN IMPACT" if row.status == "IMPACT_READY" else "REVIEW-ONLY CUSTOMER SCENARIOS"
            print(f"\n   {heading}")
            print(
                f"   {'Customer':<12} {'Lines':>5} {'Last':<10} {'Sell':>10} {'Cost':>10} "
                f"{'ProjCost':>10} {'GP Now':>8} {'GP New':>8} {'Drop':>7} "
                f"{'12M Qty':>10} {'Erosion':>12} {'Protection':<12}"
            )
            for customer in row.customer_impacts[: max(0, args.show_customers)]:
                protection = "PROTECTED" if customer.special_pricing_protected else ""
                print(
                    f"   {customer.customer_no:<12} {customer.history_lines:>5} "
                    f"{customer.last_sale.date().isoformat():<10} "
                    f"{customer.recent_sell_median:>10.2f} {customer.recent_cost_median:>10.2f} "
                    f"{customer.projected_cost:>10.2f} {customer.current_gp_pct:>7.1f}% "
                    f"{customer.projected_gp_pct:>7.1f}% {customer.gp_drop_points:>6.1f} "
                    f"{customer.trailing_quantity:>10.2f} {customer.estimated_margin_erosion:>12.2f} "
                    f"{protection:<12}"
                )
                if customer.special_pricing_protected and customer.pricing_approvers:
                    print(
                        "   " + " " * 12 + f"Special-pricing approver: {', '.join(customer.pricing_approvers)}"
                    )

    if args.out:
        write_supplier_impact_csv(impacts, args.out)
        print(f"\nImpact CSV written to: {Path(args.out).resolve()}")

    print("\nINTERPRETATION NOTE")
    print(
        "  Actionable erosion includes IMPACT_READY rows only. REVIEW rows are excluded from headline "
        "customer and erosion totals. Recent posted cost must be both aligned to the supplier-stated "
        "current cost and sufficiently stable across recent transactions before one supplier delta is "
        "applied across customers. Use --include-review-scenarios only for explicit what-if analysis."
    )

    print("\nSAFETY NOTE")
    print(
        "  This is a scenario analysis, not a pricing recommendation. Historical volume is not a forecast. "
        "BC Item Unit Cost remains comparison context. No Business Central record is created or changed."
    )

    return 1 if summary["review"] or summary["reject"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
