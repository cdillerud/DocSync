from __future__ import annotations

import argparse
from pathlib import Path

from .supplier_price_ingest import load_supplier_notice, summarize_staging, write_staging_csv


def _money(value: float | None) -> str:
    return "n/a" if value is None else f"${value:,.4f}"


def _pct(value: float | None) -> str:
    return "n/a" if value is None else f"{value:+.1f}%"


def main() -> int:
    parser = argparse.ArgumentParser(
        description=(
            "Normalize a local supplier price notice into an auditable staging CSV. "
            "This command does not read email and does not write to Business Central."
        )
    )
    parser.add_argument("--input", required=True, help="Local CSV/XLSX/XLSM supplier notice")
    parser.add_argument("--supplier", default="", help="Default supplier name when the file omits it")
    parser.add_argument("--sheet", default="", help="Optional Excel worksheet name")
    parser.add_argument("--out", default="", help="Optional normalized staging CSV output")
    parser.add_argument("--show", type=int, default=50, help="Maximum staged rows to display")
    args = parser.parse_args()

    try:
        rows = load_supplier_notice(
            args.input,
            default_supplier=args.supplier,
            sheet_name=args.sheet,
        )
    except (OSError, RuntimeError, ValueError) as exc:
        parser.error(str(exc))

    summary = summarize_staging(rows)

    print("\n============================================================")
    print("GPI COMMERCIAL GUARDRAIL - SUPPLIER PRICE STAGING")
    print("============================================================")
    print(f"Input file         : {Path(args.input).resolve()}")
    print(f"Default supplier   : {args.supplier or 'NOT SUPPLIED'}")
    print(f"Rows staged        : {summary['rows']}")
    print(f"READY              : {summary['ready']}")
    print(f"REVIEW             : {summary['review']}")
    print(f"REJECT             : {summary['reject']}")
    print(f"Cost increases     : {summary['increases']}")
    print(f"Cost decreases     : {summary['decreases']}")
    if summary["max_increase_pct"] is not None:
        print(f"Largest increase   : {summary['max_increase_pct']:+.1f}%")
    if summary["max_decrease_pct"] is not None:
        print(f"Largest decrease   : {summary['max_decrease_pct']:+.1f}%")

    if rows and args.show > 0:
        print("\nSTAGED PRICE CHANGES")
        for index, row in enumerate(rows[: args.show], start=1):
            item = row.gpi_item_no or row.supplier_item_no or "<missing item>"
            effective = row.effective_date.isoformat() if row.effective_date else "n/a"
            print(f"\n{index}. [{row.status}] {item}")
            print(f"   Supplier       : {row.supplier_name or 'n/a'}")
            if row.supplier_item_no:
                print(f"   Supplier item  : {row.supplier_item_no}")
            if row.gpi_item_no:
                print(f"   GPI item       : {row.gpi_item_no}")
            if row.description:
                print(f"   Description    : {row.description}")
            print(f"   Current cost   : {_money(row.current_cost)}")
            print(f"   New cost       : {_money(row.new_cost)}")
            print(f"   Change         : {_money(row.cost_change)} ({_pct(row.cost_change_pct)})")
            print(f"   Effective      : {effective}")
            print(f"   UOM            : {row.uom or 'n/a'}")
            if row.tier_qty is not None:
                print(f"   Tier qty       : {row.tier_qty:g}")
            if row.freight_included is not None:
                print(f"   Freight incl.  : {'YES' if row.freight_included else 'NO'}")
            if row.warnings:
                print(f"   Review notes   : {'; '.join(row.warnings)}")
            print(
                f"   Source         : {row.source_file}"
                + (f" / {row.source_sheet}" if row.source_sheet else "")
                + f" row {row.source_row}"
            )

    if args.out:
        write_staging_csv(rows, args.out)
        print(f"\nNormalized staging CSV written to: {Path(args.out).resolve()}")

    print("\nSAFETY NOTE")
    print(
        "  This stage only normalizes supplier-provided data. READY does not mean approved for BC. "
        "The next stage must match the supplier item to an authoritative GPI/BC item, compare the "
        "notice against current BC cost/UOM, calculate customer margin exposure, and require human "
        "approval before any Business Central update is considered."
    )

    return 1 if summary["reject"] else 0


if __name__ == "__main__":
    raise SystemExit(main())
