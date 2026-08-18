from __future__ import annotations

import argparse

from .bc_adapter import BCConfig, BusinessCentralClient, BusinessCentralError
from .bc_pricing_rules import fetch_bc_pricing_rules
from .proposal_guard import Proposal
from .proposal_special_pricing import apply_special_pricing_firewall, parse_proposal_date
from .quote_guard import analyze_quote_extra


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Evaluate a proposed quote/extra price against posted Business Central history. "
            "Customer-specific exact-item/UOM history has priority; broader history is context only."
        )
    )
    parser.add_argument("--customer", required=True, help="Exact BC customer number")
    parser.add_argument("--item", required=True, help="Exact BC quote/extra item number")
    parser.add_argument("--price", required=True, type=float, help="Proposed unit sell price")
    parser.add_argument("--quantity", type=float, default=1.0, help="Proposed quantity")
    parser.add_argument("--uom", default="EA", help="Proposed unit of measure")
    parser.add_argument("--customer-name", default="", help="Optional customer name")
    parser.add_argument("--description", default="", help="Optional item description")
    parser.add_argument("--start-date", default="2024-01-01", help="History start, YYYY-MM-DD")
    parser.add_argument("--end-date", default="", help="History end, YYYY-MM-DD")
    parser.add_argument("--proposal-date", default="", help="Proposal date, YYYY-MM-DD; defaults to today")
    parser.add_argument("--recent-count", type=int, default=5)
    parser.add_argument("--below-pct", type=float, default=7.5)
    parser.add_argument("--above-pct", type=float, default=15.0)
    parser.add_argument(
        "--no-special-pricing",
        action="store_true",
        help="Explicitly disable the BC special-pricing firewall for troubleshooting only",
    )
    args = parser.parse_args()

    try:
        config = BCConfig.from_env(source="custom")
        client = BusinessCentralClient(config)
        transactions = client.fetch_transactions(
            start_date=args.start_date,
            end_date=args.end_date,
            item_nos=[args.item],
        )

        pricing_rules = []
        if not args.no_special_pricing:
            try:
                pricing_rules = fetch_bc_pricing_rules(client)
            except (BusinessCentralError, ValueError) as exc:
                parser.error(
                    "Special-pricing firewall could not read Business Central pricing rules. "
                    "Refusing to continue without the authoritative protection layer. "
                    f"Detail: {exc}"
                )
    except BusinessCentralError as exc:
        parser.error(str(exc))

    proposal = Proposal(
        customer_no=args.customer,
        customer_name=args.customer_name,
        item_no=args.item,
        description=args.description,
        unit_price=args.price,
        quantity=args.quantity,
        uom=args.uom,
    )

    profile, exceptions = analyze_quote_extra(
        transactions,
        proposal,
        thresholds={
            "recent_count": args.recent_count,
            "below_customer_pct": args.below_pct,
            "above_customer_pct": args.above_pct,
        },
    )

    proposal_date = parse_proposal_date(args.proposal_date or None)
    firewall = {
        "protected": False,
        "matched_rule_count": 0,
        "rule_types": [],
        "approvers": [],
        "notes": [],
        "as_of": proposal_date.isoformat(),
    }
    if not args.no_special_pricing:
        firewall, exceptions = apply_special_pricing_firewall(
            proposal,
            exceptions,
            pricing_rules,
            as_of=proposal_date,
        )

    status = "REVIEW REQUIRED" if exceptions else "PASS"

    print("\n============================================================")
    print("GPI COMMERCIAL GUARDRAIL - LIVE BC QUOTE / EXTRAS CHECK")
    print("============================================================")
    print(f"BC environment     : {config.environment}")
    print(f"Customer           : {proposal.customer_no}")
    print(f"Item               : {proposal.item_no}")
    print(f"Proposed price     : ${proposal.unit_price:,.2f}/{proposal.uom}")
    print(f"Proposed quantity  : {proposal.quantity:g} {proposal.uom}")
    print(f"History window     : {args.start_date} through {args.end_date or 'latest'}")
    print(f"BC item rows       : {len(transactions)}")
    print(f"Customer history   : {profile['customer_history_lines']} exact item/UOM line(s)")
    print(f"Benchmark source   : {profile['benchmark_source']}")
    print(f"Confidence         : {profile['confidence']}")
    if args.no_special_pricing:
        print("Special pricing    : OFF BY EXPLICIT OVERRIDE")
    else:
        protected = firewall.get("protected", False)
        count = firewall.get("matched_rule_count", 0)
        print(f"Special pricing    : {'PROTECTED (' + str(count) + ' rule(s))' if protected else 'NO ACTIVE MATCH'}")
    print(f"Result             : {status}")

    print("\nCUSTOMER-SPECIFIC HISTORY")
    print(f"  Lines             : {profile['customer_history_lines']}")
    if profile["customer_history_lines"]:
        print(f"  Last sale         : {profile['last_customer_sale'].date().isoformat()}")
        print(f"  Customer median   : {_money(profile['customer_median_price'])}/{proposal.uom}")
        print(f"  Recent median     : {_money(profile['recent_median_price'])}/{proposal.uom}")
        print(
            "  Recent prices     : "
            + ", ".join(_money(value) for value in profile["recent_prices"])
        )
        print(f"  Customer range    : {_money(profile['customer_min_price'])} to {_money(profile['customer_max_price'])}/{proposal.uom}")
        if profile["dominant_customer_price"] is not None:
            print(
                f"  Dominant price    : {_money(profile['dominant_customer_price'])}/{proposal.uom} "
                f"({profile['dominant_customer_price_share'] * 100:.1f}% of history)"
            )
    else:
        print("  No posted history for this customer / item / UOM combination.")

    print("\nBROADER ITEM CONTEXT")
    print(f"  Lines             : {profile['all_history_lines']}")
    print(f"  Customers         : {profile['all_history_customers']}")
    if profile["all_history_lines"]:
        print(f"  All-cust median   : {_money(profile['all_median_price'])}/{proposal.uom}")
        print(f"  All-cust range    : {_money(profile['all_min_price'])} to {_money(profile['all_max_price'])}/{proposal.uom}")
    print("  Use               : CONTEXT ONLY, never an authoritative replacement price")

    if not args.no_special_pricing and firewall.get("protected"):
        print("\nSPECIAL PRICING FIREWALL")
        print(f"  Proposal date      : {firewall['as_of']}")
        print(f"  Active matches     : {firewall['matched_rule_count']}")
        if firewall.get("rule_types"):
            print(f"  Rule type(s)       : {', '.join(firewall['rule_types'])}")
        if firewall.get("approvers"):
            print(f"  Approver(s)        : {', '.join(firewall['approvers'])}")
        for note in firewall.get("notes", []):
            print(f"  Rule note          : {note}")

    if exceptions:
        print("\nEXCEPTIONS")
        for index, exc in enumerate(exceptions, start=1):
            print(f"\n{index}. [{exc.severity}] {exc.exception_type}")
            print(f"   Actual   : {exc.actual}")
            print(f"   Expected : {exc.expected}")
            if exc.estimated_exposure > 0:
                print(f"   Variance : ${exc.estimated_exposure:,.2f}")
            print(f"   Action   : {exc.recommended_action}")
            print(f"   Why      : {exc.explanation}")
    else:
        print("\nNo customer-specific quote/extra exception was detected.")

    if profile["benchmark_source"] == "BROAD_CONTEXT_ONLY":
        print("\nLOW-CONFIDENCE NOTE")
        print(
            "  There is not enough customer-specific history to judge this proposal. Broader item "
            "history is displayed only as context and does not cause an automatic price exception."
        )

    return 2 if exceptions else 0


if __name__ == "__main__":
    raise SystemExit(main())
