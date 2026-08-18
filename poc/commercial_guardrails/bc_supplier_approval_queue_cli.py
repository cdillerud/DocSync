from __future__ import annotations

import argparse
from pathlib import Path
from typing import Sequence

from .bc_adapter import BCConfig, BusinessCentralClient, BusinessCentralError
from .bc_item_costs import fetch_bc_item_cost_contexts
from .bc_pricing_rules import fetch_bc_pricing_rules
from .proposal_special_pricing import ProposalPricingRule
from .supplier_approval_queue import (
    build_supplier_approval_queue,
    summarize_supplier_approval_queue,
    write_supplier_approval_queue_csv,
)
from .supplier_margin_impact import analyze_supplier_margin_impact, write_supplier_impact_csv
from .supplier_price_compare import SupplierPriceComparison, compare_supplier_prices_to_bc
from .supplier_price_ingest import load_supplier_notice


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def _money4(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.4f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def _resolve_detail_out(queue_out: str, detail_out: str) -> str:
    """Return a cockpit detail sidecar path for the same analysis snapshot as the queue."""
    explicit = str(detail_out or "").strip()
    if explicit:
        return explicit
    queue_text = str(queue_out or "").strip()
    if not queue_text:
        return ""
    queue_path = Path(queue_text)
    if queue_path.name.casefold() == "live_supplier_approval_queue.csv":
        return str(queue_path.with_name("live_supplier_margin_impact.csv"))
    return str(queue_path.with_name(f"{queue_path.stem}_detail.csv"))


def _build_impacts(
    comparisons: Sequence[SupplierPriceComparison],
    transactions,
    pricing_rules: Sequence[ProposalPricingRule],
    *,
    recent_item_cost_count: int,
    recent_customer_count: int,
    history_alignment_tolerance_pct: float,
    max_recent_cost_spread_pct: float,
    trailing_days: int,
):
    """Apply the approval-queue analysis settings using the margin engine's public parameter names."""
    return [
        analyze_supplier_margin_impact(
            comparison,
            transactions,
            pricing_rules=pricing_rules,
            recent_item_cost_count=recent_item_cost_count,
            recent_customer_count=recent_customer_count,
            history_alignment_tolerance_pct=history_alignment_tolerance_pct,
            max_recent_cost_spread_pct=max_recent_cost_spread_pct,
            trailing_days=trailing_days,
        )
        for comparison in comparisons
    ]


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Build a human supplier-cost approval queue from local supplier notice rows that have "
            "already passed exact BC item/UOM, posted-cost alignment, and cost-stability checks. "
            "No Business Central writes are performed."
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
        "--recent-cost-spread-tolerance-pct",
        dest="max_recent_cost_spread_pct",
        type=float,
        default=15.0,
        help="Maximum recent posted cost spread as percent of median before review",
    )
    parser.add_argument(
        "--recent-item-cost-count",
        type=int,
        default=10,
        help="Recent item/UOM posted cost lines used to validate supplier current cost",
    )
    parser.add_argument(
        "--recent-customer-count",
        type=int,
        default=3,
        help="Recent customer/item/UOM lines used for customer sell/cost baselines",
    )
    parser.add_argument(
        "--trailing-days",
        type=int,
        default=365,
        help="Historical volume window used for margin-dollar erosion context",
    )
    parser.add_argument("--out", default="", help="Optional approval queue CSV")
    parser.add_argument(
        "--detail-out",
        default="",
        help=(
            "Optional margin-impact detail CSV. When --out is supplied and this is omitted, a sidecar "
            "detail path is derived automatically so the cockpit queue and customer detail stay in sync."
        ),
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
        comparisons = compare_supplier_prices_to_bc(staged, contexts)
        pricing_rules = fetch_bc_pricing_rules(client)
        transactions = client.fetch_transactions(
            start_date=args.start_date,
            end_date=args.end_date,
            item_nos=item_nos,
        )
    except (BusinessCentralError, ValueError) as exc:
        parser.error(str(exc))

    impacts = _build_impacts(
        comparisons,
        transactions,
        pricing_rules,
        recent_item_cost_count=args.recent_item_cost_count,
        recent_customer_count=args.recent_customer_count,
        history_alignment_tolerance_pct=args.history_alignment_tolerance_pct,
        max_recent_cost_spread_pct=args.max_recent_cost_spread_pct,
        trailing_days=args.trailing_days,
    )

    queue = build_supplier_approval_queue(impacts)
    summary = summarize_supplier_approval_queue(queue)
    review_count = sum(row.status == "REVIEW" for row in impacts)
    reject_count = sum(row.status == "REJECT" for row in impacts)

    print("\n============================================================")
    print("GPI COMMERCIAL GUARDRAIL - SUPPLIER APPROVAL QUEUE")
    print("============================================================")
    print(f"BC environment       : {config.environment}")
    print(f"Input file           : {Path(args.input).resolve()}")
    print(f"History window       : {args.start_date} through {args.end_date or 'latest'}")
    print(f"Approval items       : {summary['items']}")
    print(f"Protected items      : {summary['protected_items']}")
    print(f"Affected customers   : {summary['affected_customers']}")
    print(f"Protected customers  : {summary['protected_customers']}")
    print(f"Actionable erosion   : {_money(summary['estimated_margin_erosion'])}")
    print(f"Upstream REVIEW      : {review_count}")
    print(f"Upstream REJECT      : {reject_count}")
    print(f"Pricing rules read   : {len(pricing_rules)}")

    if queue:
        print("\nPENDING HUMAN APPROVAL")
        for index, row in enumerate(queue, start=1):
            print(f"\n{index}. [{row.queue_status}] {row.gpi_item_no}")
            print(f"   Supplier        : {row.supplier_name or 'n/a'}")
            if row.supplier_item_no:
                print(f"   Supplier item   : {row.supplier_item_no}")
            print(f"   Effective       : {row.effective_date or 'n/a'}")
            print(f"   UOM             : {row.uom or 'n/a'}")
            print(f"   Current cost    : {_money4(row.supplier_current_cost)}/{row.uom or 'UOM'}")
            print(f"   Proposed cost   : {_money4(row.supplier_new_cost)}/{row.uom or 'UOM'}")
            print(f"   Cost change     : {_money4(row.supplier_cost_delta)} ({_pct(row.supplier_cost_delta_pct)})")
            print(f"   Customers       : {row.affected_customers}")
            print(f"   Protected       : {row.protected_customers}")
            print(f"   Trailing qty    : {row.trailing_quantity:,.2f} {row.uom}")
            print(f"   Trailing sales  : {_money(row.trailing_sales)}")
            print(f"   Est. erosion    : {_money(row.estimated_margin_erosion)}")
            print(f"   Worst GP drop   : {row.max_gp_drop_points:.1f} point(s)")
            print(f"   Lowest proj. GP : {row.min_projected_gp_pct:.1f}%")
            if row.top_customer_no:
                print(f"   Top exposure    : {row.top_customer_no} / {_money(row.top_customer_erosion)}")
            if row.pricing_approvers:
                print(f"   Pricing approver: {', '.join(row.pricing_approvers)}")
            print(f"   Action          : {row.action}")
            print(f"   Source          : {row.source_file} row {row.source_row}")

    if args.out:
        write_supplier_approval_queue_csv(queue, args.out)
        print(f"\nApproval queue CSV written to: {Path(args.out).resolve()}")
        print("  decision, decision_by, and decision_notes are intentionally blank for human completion.")

    detail_out = _resolve_detail_out(args.out, args.detail_out)
    if detail_out:
        write_supplier_impact_csv(impacts, detail_out)
        print(f"Margin detail CSV written to: {Path(detail_out).resolve()}")
        print("  Queue and customer detail were written from the same analysis snapshot.")

    print("\nQUEUE RULE")
    print(
        "  Only IMPACT_READY supplier rows enter this queue. REVIEW and REJECT rows stay upstream until "
        "their cost basis, UOM, effective date, supplier scope, or other validation issue is resolved."
    )

    print("\nSAFETY NOTE")
    print(
        "  PENDING_APPROVAL does not mean approved. PROTECTED_REVIEW means at least one affected "
        "customer/item has an active Business Central special-pricing or fixed-price rule. This command "
        "does not update any Business Central record."
    )

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
