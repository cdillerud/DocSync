from __future__ import annotations

import argparse
import json
from pathlib import Path

from .engine import analyze_transactions, load_guardrails, load_transactions, summarize, write_exceptions_csv


def main() -> int:
    parser = argparse.ArgumentParser(description="GPI Commercial Guardrail POC")
    parser.add_argument("--transactions", required=True, help="Transactions CSV")
    parser.add_argument("--guardrails", help="Optional guardrail rules CSV")
    parser.add_argument("--out", default="commercial_guardrail_exceptions.csv", help="Exceptions CSV output")
    args = parser.parse_args()

    transactions = load_transactions(args.transactions)
    rules = load_guardrails(args.guardrails)
    exceptions = analyze_transactions(transactions, rules)
    write_exceptions_csv(exceptions, args.out)

    print(json.dumps(summarize(exceptions), indent=2))
    print(f"\nExceptions written to: {Path(args.out).resolve()}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
