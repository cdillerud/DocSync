from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .proposal_guard import Proposal, analyze_proposal, load_family_history


def _json_safe_profile(profile: dict) -> dict:
    safe = dict(profile)
    for key in ("first_item_sale", "last_item_sale"):
        value = safe.get(key)
        if value is not None:
            safe[key] = value.date().isoformat()
    return safe


def main() -> int:
    parser = argparse.ArgumentParser(
        description="Evaluate a proposed commercial line against real customer/item family history"
    )
    parser.add_argument("--history", required=True, help="Family-scoped historical line CSV")
    parser.add_argument("--customer", required=True, help="Customer number")
    parser.add_argument("--item", required=True, help="Proposed item number")
    parser.add_argument("--price", required=True, type=float, help="Proposed unit sell price")
    parser.add_argument("--quantity", required=True, type=float, help="Proposed quantity")
    parser.add_argument("--uom", required=True, help="Proposed unit of measure")
    parser.add_argument("--customer-name", default="", help="Optional customer name")
    parser.add_argument("--description", default="", help="Optional item description")
    parser.add_argument("--recent-count", type=int, default=3, help="Recent transactions used for price baseline")
    parser.add_argument("--below-pct", type=float, default=7.5, help="Percent below recent median that triggers review")
    parser.add_argument("--above-pct", type=float, default=10.0, help="Percent above recent median that triggers review")
    parser.add_argument("--json-out", help="Optional JSON audit output")
    args = parser.parse_args()

    history = load_family_history(args.history)
    proposal = Proposal(
        customer_no=args.customer,
        customer_name=args.customer_name,
        item_no=args.item,
        description=args.description,
        unit_price=args.price,
        quantity=args.quantity,
        uom=args.uom,
    )

    profile, exceptions = analyze_proposal(
        history,
        proposal,
        thresholds={
            "recent_price_count": args.recent_count,
            "sell_below_recent_pct": args.below_pct,
            "sell_above_recent_pct": args.above_pct,
        },
    )

    status = "REVIEW REQUIRED" if exceptions else "PASS"
    print("\n============================================================")
    print("GPI COMMERCIAL GUARDRAIL - PROPOSAL CHECK")
    print("============================================================")
    print(f"Customer          : {proposal.customer_no}")
    print(f"Item              : {proposal.item_no}")
    print(f"Proposed price    : ${proposal.unit_price:.2f}/{proposal.uom}")
    print(f"Proposed quantity : {proposal.quantity:g} {proposal.uom}")
    print(f"Result            : {status}")
    print("------------------------------------------------------------")
    print(f"Family history    : {profile['customer_family_lines']} line(s)")
    print(f"Exact item history: {profile['customer_item_lines']} line(s)")

    if profile.get("last_item_sale") is not None:
        print(f"Last exact sale   : {profile['last_item_sale'].date().isoformat()}")
    if profile.get("recent_median_price") is not None:
        print(
            f"Recent median     : ${profile['recent_median_price']:.2f}/{proposal.uom} "
            f"({profile['recent_price_count']} transaction(s))"
        )
        print(f"Recent prices     : {', '.join(f'${p:.2f}' for p in profile['recent_prices'])}")
    if profile.get("historical_uoms"):
        print(f"Historical UOM(s) : {', '.join(profile['historical_uoms'])}")

    if exceptions:
        print("\nEXCEPTIONS")
        for index, exc in enumerate(exceptions, start=1):
            print(f"\n{index}. [{exc.severity}] {exc.exception_type}")
            print(f"   Actual   : {exc.actual}")
            print(f"   Expected : {exc.expected}")
            if exc.estimated_exposure > 0:
                print(f"   Exposure : ${exc.estimated_exposure:,.2f}")
            print(f"   Action   : {exc.recommended_action}")
            print(f"   Why      : {exc.explanation}")
    else:
        print("\nNo proposal exceptions were detected against the supplied history.")

    payload = {
        "status": status,
        "proposal": asdict(proposal),
        "profile": _json_safe_profile(profile),
        "exceptions": [exc.to_dict() for exc in exceptions],
    }

    if args.json_out:
        path = Path(args.json_out)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nAudit JSON written to: {path.resolve()}")

    return 2 if exceptions else 0


if __name__ == "__main__":
    raise SystemExit(main())
