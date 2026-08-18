from __future__ import annotations

import argparse

from .bc_adapter import BCConfig, BusinessCentralClient, BusinessCentralError
from .bc_pricing_rules import fetch_bc_pricing_rules
from .proposal_guard import Proposal
from .proposal_special_pricing import matching_proposal_pricing_rules, parse_proposal_date


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Read GPI pricing guardrail rules from Business Central without writing to BC."
    )
    parser.add_argument("--customer", required=True, help="Customer number to test")
    parser.add_argument("--item", required=True, help="Item number to test")
    parser.add_argument("--proposal-date", default="", help="YYYY-MM-DD; defaults to today")
    args = parser.parse_args()

    try:
        config = BCConfig.from_env(source="custom")
        client = BusinessCentralClient(config)
        rules = fetch_bc_pricing_rules(client)
    except (BusinessCentralError, ValueError) as exc:
        parser.error(str(exc))

    proposal_date = parse_proposal_date(args.proposal_date or None)
    proposal = Proposal(
        customer_no=args.customer,
        item_no=args.item,
        unit_price=0,
        quantity=0,
        uom="",
    )
    matched = matching_proposal_pricing_rules(proposal, rules, proposal_date)

    print("\n============================================================")
    print("GPI COMMERCIAL GUARDRAIL - BC PRICING RULE PROBE")
    print("============================================================")
    print(f"BC environment     : {config.environment}")
    print(f"Rules returned     : {len(rules)}")
    print(f"Customer           : {args.customer}")
    print(f"Item               : {args.item}")
    print(f"Proposal date      : {proposal_date.isoformat()}")
    print(f"Active matches     : {len(matched)}")

    if not matched:
        print("\nNo active pricing guardrail matched this customer/item/date.")
        return 0

    print("\nMATCHED RULES")
    for index, rule in enumerate(matched, start=1):
        scope_customer = rule.customer_no if rule.customer_no != "*" else "ALL CUSTOMERS"
        scope_item = rule.item_no if rule.item_no != "*" else "ALL ITEMS"
        print(f"\n{index}. {rule.rule_type}")
        print(f"   Customer  : {scope_customer}")
        print(f"   Item      : {scope_item}")
        if rule.locked_sell_price is not None:
            print(f"   Fixed     : ${rule.locked_sell_price:,.4f}")
        print(f"   Effective : {rule.effective_from or 'open'} through {rule.effective_to or 'open'}")
        if rule.approver:
            print(f"   Approver  : {rule.approver}")
        if rule.notes:
            print(f"   Notes     : {rule.notes}")

    return 0


if __name__ == "__main__":
    raise SystemExit(main())
