from __future__ import annotations

import argparse
from pathlib import Path

from .bc_adapter import BusinessCentralError
from .supplier_review_pipeline import DEFAULT_RUN_ROOT, create_manual_supplier_review_run


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.2f}"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Create an auditable local supplier-review run from one manually supplied CSV/XLSX/XLSM notice. "
            "The pipeline reads Business Central but performs no BC writes."
        )
    )
    parser.add_argument("--input", required=True, help="Local supplier notice CSV/XLSX/XLSM")
    parser.add_argument("--supplier", default="", help="Default supplier name when the notice omits it")
    parser.add_argument("--sheet", default="", help="Optional Excel worksheet name")
    parser.add_argument("--start-date", default="2024-01-01", help="Posted sales history start, YYYY-MM-DD")
    parser.add_argument("--end-date", default="", help="Optional posted sales history end, YYYY-MM-DD")
    parser.add_argument(
        "--run-root",
        default=str(DEFAULT_RUN_ROOT),
        help="Folder under which a unique auditable run directory is created",
    )
    args = parser.parse_args()

    source = Path(args.input)
    if not source.exists() or not source.is_file():
        parser.error(f"Supplier notice not found: {source}")

    try:
        artifacts = create_manual_supplier_review_run(
            source.name,
            source.read_bytes(),
            run_root=args.run_root,
            start_date=args.start_date,
            end_date=args.end_date,
            default_supplier=args.supplier,
            sheet_name=args.sheet,
        )
    except (BusinessCentralError, OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))

    summary = artifacts.review_run.summary

    print("\n============================================================")
    print("GPI COMMERCIAL GUARDRAIL - MANUAL SUPPLIER INTAKE")
    print("============================================================")
    print(f"BC environment       : {artifacts.review_run.environment}")
    print(f"Source notice        : {source.resolve()}")
    print(f"Run directory        : {artifacts.run_directory.resolve()}")
    print(f"Supplier rows        : {summary['supplier_rows']}")
    print(f"Approval items       : {summary['items']}")
    print(f"Protected items      : {summary['protected_items']}")
    print(f"Affected customers   : {summary['affected_customers']}")
    print(f"Protected customers  : {summary['protected_customers']}")
    print(f"Actionable erosion   : {_money(summary['estimated_margin_erosion'])}")
    print(f"Upstream REVIEW      : {summary['review_rows']}")
    print(f"Upstream REJECT      : {summary['reject_rows']}")
    print(f"Pricing rules read   : {summary['pricing_rules_read']}")

    print("\nRUN ARTIFACTS")
    print(f"  Source copy        : {artifacts.source_path.resolve()}")
    print(f"  Approval queue     : {artifacts.queue_path.resolve()}")
    print(f"  Margin detail      : {artifacts.detail_path.resolve()}")
    print(f"  Decision log       : {artifacts.decision_path.resolve()} (created when a decision is saved)")
    print(f"  Manifest           : {artifacts.manifest_path.resolve()}")

    print("\nNEXT STEP")
    print("  Point the Supplier Cost Review Cockpit at this run's approval_queue.csv and margin_impact.csv.")
    print("  The cockpit decision log should use this run's decisions.csv path.")

    print("\nSAFETY NOTE")
    print(
        "  This intake is manual and auditable. It does not monitor email and does not update Business Central. "
        "Human approval remains required."
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
