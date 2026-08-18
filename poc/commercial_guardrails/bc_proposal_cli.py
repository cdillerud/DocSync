from __future__ import annotations

import argparse
import json
from dataclasses import asdict
from pathlib import Path

from .bc_adapter import BCConfig, BusinessCentralClient, BusinessCentralError
from .bc_standard import fetch_standard_customer_family_history, write_family_history_csv
from .item_similarity import ItemCandidate, discover_related_items
from .proposal_guard import Proposal, analyze_proposal


def _json_safe_profile(profile: dict) -> dict:
    safe = dict(profile)
    for key in ("first_item_sale", "last_item_sale"):
        value = safe.get(key)
        if value is not None:
            safe[key] = value.date().isoformat()
    return safe


def _candidate_dict(candidate: ItemCandidate) -> dict:
    return {
        "item_no": candidate.item_no,
        "description": candidate.description,
        "score": candidate.score,
        "reasons": list(candidate.reasons),
        "blocked": candidate.blocked,
        "base_uom": candidate.base_uom,
    }


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Read a customer's posted Business Central sales history through the standard "
            "v2 API and evaluate a proposed line without writing to BC."
        )
    )
    parser.add_argument("--customer", required=True, help="Exact BC customer number")
    parser.add_argument("--item", required=True, help="Proposed BC item number")
    parser.add_argument(
        "--related-item",
        action="append",
        default=[],
        help="Additional related/family BC item number; repeatable",
    )
    parser.add_argument(
        "--no-auto-related",
        action="store_true",
        help="Disable automatic related-item discovery from the BC item master",
    )
    parser.add_argument(
        "--related-min-score",
        type=float,
        default=90.0,
        help="Minimum similarity score for automatically discovered related items",
    )
    parser.add_argument(
        "--max-related",
        type=int,
        default=12,
        help="Maximum automatically discovered related items",
    )
    parser.add_argument(
        "--include-blocked-related",
        action="store_true",
        help="Allow blocked BC items to be considered as related-item candidates",
    )
    parser.add_argument("--price", required=True, type=float, help="Proposed unit sell price")
    parser.add_argument("--quantity", required=True, type=float, help="Proposed quantity")
    parser.add_argument("--uom", required=True, help="Proposed unit of measure")
    parser.add_argument("--customer-name", default="", help="Optional customer name")
    parser.add_argument("--description", default="", help="Optional proposed item description override")
    parser.add_argument("--start-date", default="2024-01-01", help="History start, YYYY-MM-DD")
    parser.add_argument("--end-date", default="", help="History end, YYYY-MM-DD")
    parser.add_argument("--recent-count", type=int, default=3)
    parser.add_argument("--below-pct", type=float, default=7.5)
    parser.add_argument("--above-pct", type=float, default=10.0)
    parser.add_argument("--history-out", help="Optional local CSV audit of fetched history")
    parser.add_argument("--json-out", help="Optional local JSON proposal audit")
    args = parser.parse_args()

    discovered: list[ItemCandidate] = []
    proposed_master: dict = {}

    try:
        # Source is irrelevant here because this command calls only standard v2 GET APIs.
        config = BCConfig.from_env(source="custom")
        client = BusinessCentralClient(config)

        if not args.no_auto_related:
            proposed_master, discovered = discover_related_items(
                client,
                proposed_item_no=args.item,
                min_score=args.related_min_score,
                max_results=args.max_related,
                include_blocked=args.include_blocked_related,
            )

        family_items: list[str] = []
        for item in [args.item, *args.related_item, *(c.item_no for c in discovered)]:
            if item and item not in family_items:
                family_items.append(item)

        history = fetch_standard_customer_family_history(
            client,
            customer_no=args.customer,
            item_nos=family_items,
            start_date=args.start_date,
            end_date=args.end_date,
        )
    except BusinessCentralError as exc:
        parser.error(str(exc))

    if args.history_out:
        write_family_history_csv(history, args.history_out)

    proposal_description = args.description or str(proposed_master.get("displayName") or "").strip()
    proposal = Proposal(
        customer_no=args.customer,
        customer_name=args.customer_name,
        item_no=args.item,
        description=proposal_description,
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
    print("GPI COMMERCIAL GUARDRAIL - LIVE BC PROPOSAL CHECK")
    print("============================================================")
    print(f"BC environment     : {config.environment}")
    print(f"Customer           : {proposal.customer_no}")
    print(f"Proposed item      : {proposal.item_no}")
    if proposal.description:
        print(f"Item description   : {proposal.description}")
    print(f"Proposed price     : ${proposal.unit_price:.2f}/{proposal.uom}")
    print(f"Proposed quantity  : {proposal.quantity:g} {proposal.uom}")
    print(f"History window     : {args.start_date} through {args.end_date or 'latest'}")
    print(f"Auto related items : {'OFF' if args.no_auto_related else len(discovered)}")
    print(f"Family items       : {len(family_items)}")
    print(f"BC history fetched : {len(history)} matching line(s)")
    print(f"Result             : {status}")

    if discovered:
        print("\nAUTO-DISCOVERED RELATED ITEMS")
        for candidate in discovered:
            reason_text = ", ".join(candidate.reasons) or "description similarity"
            print(
                f"  {candidate.item_no:<18} score {candidate.score:>5.1f} | "
                f"{candidate.description} | {reason_text}"
            )

    print("------------------------------------------------------------")
    print(f"Family history     : {profile['customer_family_lines']} line(s)")
    print(f"Exact item history : {profile['customer_item_lines']} line(s)")

    if profile.get("last_item_sale") is not None:
        print(f"Last exact sale    : {profile['last_item_sale'].date().isoformat()}")
    if profile.get("recent_median_price") is not None:
        print(
            f"Recent median      : ${profile['recent_median_price']:.2f}/{proposal.uom} "
            f"({profile['recent_price_count']} transaction(s))"
        )
        print(f"Recent prices      : {', '.join(f'${p:.2f}' for p in profile['recent_prices'])}")
    if profile.get("historical_uoms"):
        print(f"Historical UOM(s)  : {', '.join(profile['historical_uoms'])}")

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
        print("\nNo proposal exceptions were detected against live BC history.")

    payload = {
        "status": status,
        "bc_environment": config.environment,
        "history_window": {
            "start_date": args.start_date,
            "end_date": args.end_date or None,
        },
        "proposed_item_master": proposed_master or None,
        "auto_related_enabled": not args.no_auto_related,
        "auto_related_items": [_candidate_dict(candidate) for candidate in discovered],
        "family_items": family_items,
        "history_lines": len(history),
        "proposal": asdict(proposal),
        "profile": _json_safe_profile(profile),
        "exceptions": [exc.to_dict() for exc in exceptions],
    }

    if args.json_out:
        path = Path(args.json_out)
        path.write_text(json.dumps(payload, indent=2), encoding="utf-8")
        print(f"\nAudit JSON written to: {path.resolve()}")
    if args.history_out:
        print(f"History CSV written to: {Path(args.history_out).resolve()}")

    return 2 if exceptions else 0


if __name__ == "__main__":
    raise SystemExit(main())
