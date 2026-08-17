from __future__ import annotations

import argparse
import json
from pathlib import Path

from .bc_adapter import BCConfig, BusinessCentralClient, BusinessCentralError, write_transactions_csv
from .engine import analyze_transactions, load_guardrails, summarize, write_exceptions_csv


def main() -> int:
    parser = argparse.ArgumentParser(
        description="GPI Commercial Guardrail POC - read-only Business Central ingestion"
    )
    parser.add_argument("--source", choices=("custom", "analytics"), default="custom")
    parser.add_argument("--start-date", help="Posting date lower bound, YYYY-MM-DD")
    parser.add_argument("--end-date", help="Posting date upper bound, YYYY-MM-DD")
    parser.add_argument("--item", action="append", default=[], help="Exact BC item number; repeatable")
    parser.add_argument(
        "--customer", action="append", default=[], help="Exact BC customer number; repeatable"
    )
    parser.add_argument("--guardrails", help="Optional guardrail rules CSV")
    parser.add_argument(
        "--transactions-out",
        default="bc_guardrail_transactions.csv",
        help="Normalized BC transactions CSV",
    )
    parser.add_argument(
        "--exceptions-out",
        default="bc_guardrail_exceptions.csv",
        help="Guardrail exceptions CSV",
    )
    args = parser.parse_args()

    try:
        config = BCConfig.from_env(source=args.source)
        client = BusinessCentralClient(config)
        transactions = client.fetch_transactions(
            start_date=args.start_date or "",
            end_date=args.end_date or "",
            item_nos=args.item,
            customer_nos=args.customer,
        )
    except BusinessCentralError as exc:
        parser.error(str(exc))

    if not transactions:
        print("No qualifying Business Central transactions were returned.")
        return 2

    write_transactions_csv(transactions, args.transactions_out)
    rules = load_guardrails(args.guardrails)
    exceptions = analyze_transactions(transactions, rules)
    write_exceptions_csv(exceptions, args.exceptions_out)

    output = summarize(exceptions)
    output["transactions_analyzed"] = len(transactions)
    output["bc_environment"] = config.environment
    output["bc_source"] = config.source
    if config.source == "analytics":
        output["warning"] = (
            "Analytics API fallback uses quantityBase and does not expose sales UOM. "
            "Use the custom API query before treating margin math as authoritative."
        )

    print(json.dumps(output, indent=2))
    print(f"\nNormalized transactions: {Path(args.transactions_out).resolve()}")
    print(f"Exceptions: {Path(args.exceptions_out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
