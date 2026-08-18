from __future__ import annotations

import argparse
from datetime import datetime

from .bc_adapter import BCConfig, BusinessCentralClient, BusinessCentralError
from .quote_history import summarize_quote_history


def _date_text(value: datetime | None) -> str:
    return value.date().isoformat() if value is not None else "n/a"


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def _print_summary(title: str, stats: dict, uom_label: str = "") -> None:
    suffix = f"/{uom_label}" if uom_label else ""
    print(f"\n{title}")
    print(f"  Lines             : {stats['lines']}")
    print(f"  Customers         : {stats['customers']}")
    if not stats["lines"]:
        return
    print(f"  First sale        : {_date_text(stats['first_sale'])}")
    print(f"  Last sale         : {_date_text(stats['last_sale'])}")
    print(f"  UOM(s)            : {', '.join(stats['uoms']) or 'n/a'}")
    print(f"  Median price      : {_money(stats['median_price'])}{suffix}")
    print(f"  Simple average    : {_money(stats['average_price'])}{suffix}")
    print(f"  Weighted average  : {_money(stats['weighted_average_price'])}{suffix}")
    print(f"  Range             : {_money(stats['min_price'])} to {_money(stats['max_price'])}{suffix}")
    print(f"  Quantity          : {stats['quantity']:,.4f}")
    print(f"  Sales amount      : ${stats['sales_amount']:,.2f}")
    print(
        "  Recent prices     : "
        + ", ".join(_money(price) for price in stats["recent_prices"])
    )


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read posted Business Central history for a quote/extra item and show customer-specific "
            "and all-customer pricing context. This probe does not recommend or write a price."
        )
    )
    parser.add_argument("--item", required=True, help="Exact BC item number, for example BALLARTWORK")
    parser.add_argument("--customer", default="", help="Optional exact BC customer number")
    parser.add_argument("--uom", default="", help="Optional exact UOM filter")
    parser.add_argument("--start-date", default="2024-01-01", help="History start, YYYY-MM-DD")
    parser.add_argument("--end-date", default="", help="History end, YYYY-MM-DD")
    parser.add_argument("--recent-count", type=int, default=10, help="Number of recent prices to display")
    parser.add_argument("--show-lines", type=int, default=25, help="Maximum individual history lines to display")
    parser.add_argument("--show-customers", type=int, default=20, help="Maximum customer summaries to display")
    args = parser.parse_args()

    try:
        config = BCConfig.from_env(source="custom")
        client = BusinessCentralClient(config)
        transactions = client.fetch_transactions(
            start_date=args.start_date,
            end_date=args.end_date,
            item_nos=[args.item],
        )
    except BusinessCentralError as exc:
        parser.error(str(exc))

    profile = summarize_quote_history(
        transactions,
        item_no=args.item,
        customer_no=args.customer,
        uom=args.uom,
        recent_count=args.recent_count,
    )

    all_stats = profile["all_history"]
    customer_stats = profile["customer_history"]
    uom_label = args.uom or (all_stats["uoms"][0] if len(all_stats["uoms"]) == 1 else "")

    print("\n============================================================")
    print("GPI COMMERCIAL GUARDRAIL - BC QUOTE / EXTRAS HISTORY PROBE")
    print("============================================================")
    print(f"BC environment     : {config.environment}")
    print(f"Item               : {args.item}")
    print(f"Customer filter    : {args.customer or 'ALL CUSTOMERS'}")
    print(f"UOM filter         : {args.uom or 'ALL UOMS'}")
    print(f"History window     : {args.start_date} through {args.end_date or 'latest'}")
    print(f"BC rows returned   : {len(transactions)}")
    print(f"Usable sale lines  : {all_stats['lines']}")

    _print_summary("ALL-CUSTOMER ITEM HISTORY", all_stats, uom_label)

    if args.customer:
        _print_summary(
            f"CUSTOMER-SPECIFIC HISTORY: {args.customer}",
            customer_stats,
            uom_label,
        )

    if profile["by_customer"]:
        print("\nBY CUSTOMER")
        print(
            f"  {'Customer':<12} {'Lines':>5} {'First':<10} {'Last':<10} "
            f"{'Median':>12} {'Average':>12} {'Min':>12} {'Max':>12}"
        )
        for row in profile["by_customer"][: max(0, args.show_customers)]:
            print(
                f"  {row['customer_no']:<12} {row['lines']:>5} "
                f"{_date_text(row['first_sale']):<10} {_date_text(row['last_sale']):<10} "
                f"{_money(row['median_price']):>12} {_money(row['average_price']):>12} "
                f"{_money(row['min_price']):>12} {_money(row['max_price']):>12}"
            )

    lines = profile["matching_lines"]
    if lines and args.show_lines > 0:
        print("\nPOSTED HISTORY LINES")
        for tx in lines[-args.show_lines :]:
            print(
                f"  {tx.transaction_date.date().isoformat()} "
                f"{tx.customer_no:<12} {tx.transaction_id:<18} "
                f"Qty {tx.quantity:g} {tx.uom:<5} Price ${tx.unit_sell_price:,.2f}"
            )

    print("\nINTERPRETATION NOTE")
    print(
        "  All-customer figures are historical context only. Do not treat a global average or median "
        "as an authoritative quote price because customer-specific, contract, strategic, or special "
        "pricing may apply. The next guardrail step should prefer customer-specific history when it "
        "is sufficiently populated and otherwise label broader benchmarks as lower-confidence context."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
