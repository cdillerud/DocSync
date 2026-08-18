import csv
import tempfile
import unittest
from datetime import date
from pathlib import Path

from poc.commercial_guardrails.supplier_price_ingest import (
    canonical_header,
    load_supplier_notice,
    map_headers,
    summarize_staging,
    write_staging_csv,
)


class SupplierPriceIngestTests(unittest.TestCase):
    def test_header_aliases_are_normalized(self):
        headers = [
            "Vendor", "Vendor Item No", "GPI Item No", "Current Price", "New Price",
            "Effective Date", "UOM", "Min Qty", "Freight Included",
        ]
        mapped = map_headers(headers)
        self.assertEqual(mapped[0], "supplier_name")
        self.assertEqual(mapped[1], "supplier_item_no")
        self.assertEqual(mapped[2], "gpi_item_no")
        self.assertEqual(mapped[3], "current_cost")
        self.assertEqual(mapped[4], "new_cost")
        self.assertEqual(canonical_header("Price Effective Date"), "effective_date")

    def test_csv_row_calculates_change_and_is_ready(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "notice.csv"
            path.write_text(
                "Vendor,Vendor Item No,GPI Item No,Current Price,New Price,Effective Date,UOM\n"
                "Synthetic Glass,RG12,20041936-P4305,$160.00,$169.60,2026-09-01,M\n",
                encoding="utf-8",
            )
            rows = load_supplier_notice(path)

        self.assertEqual(len(rows), 1)
        row = rows[0]
        self.assertEqual(row.status, "READY")
        self.assertAlmostEqual(row.cost_change, 9.60, places=2)
        self.assertAlmostEqual(row.cost_change_pct, 6.0, places=2)
        self.assertEqual(row.effective_date, date(2026, 9, 1))
        self.assertEqual(row.uom, "M")

    def test_missing_current_cost_requires_review_not_reject(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "notice.csv"
            path.write_text(
                "Vendor Item No,New Price,Effective Date,UOM\n"
                "ABC-1,1.25,09/15/2026,EA\n",
                encoding="utf-8",
            )
            rows = load_supplier_notice(path, default_supplier="Synthetic Supplier")

        row = rows[0]
        self.assertEqual(row.status, "REVIEW")
        self.assertIn("current cost not supplied; BC comparison required", row.warnings)
        self.assertEqual(row.supplier_name, "Synthetic Supplier")

    def test_missing_item_or_new_cost_is_rejected(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "notice.csv"
            path.write_text(
                "Vendor,Description,Current Price,New Price,Effective Date,UOM\n"
                "Synthetic,Unknown line,1.00,,2026-09-01,EA\n",
                encoding="utf-8",
            )
            rows = load_supplier_notice(path)

        row = rows[0]
        self.assertEqual(row.status, "REJECT")
        self.assertIn("missing supplier/GPI item identifier", row.warnings)
        self.assertIn("missing or invalid new cost", row.warnings)

    def test_unrecognized_effective_date_requires_review(self):
        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "notice.csv"
            path.write_text(
                "Vendor Item No,Current Price,New Price,Effective Date,UOM\n"
                "ABC-1,10,11,TBD,EA\n",
                encoding="utf-8",
            )
            rows = load_supplier_notice(path, default_supplier="Synthetic Supplier")

        self.assertEqual(rows[0].status, "REVIEW")
        self.assertIsNone(rows[0].effective_date)
        self.assertIn("effective date missing or unrecognized", rows[0].warnings)

    def test_staging_summary_and_csv_audit(self):
        with tempfile.TemporaryDirectory() as temp:
            source = Path(temp) / "notice.csv"
            out = Path(temp) / "staged.csv"
            source.write_text(
                "Vendor Item No,Current Price,New Price,Effective Date,UOM\n"
                "A,100,110,2026-09-01,EA\n"
                "B,100,95,2026-09-01,EA\n"
                "C,,120,2026-09-01,EA\n",
                encoding="utf-8",
            )
            rows = load_supplier_notice(source, default_supplier="Synthetic Supplier")
            summary = summarize_staging(rows)
            write_staging_csv(rows, out)
            with out.open(newline="", encoding="utf-8") as handle:
                staged = list(csv.DictReader(handle))

        self.assertEqual(summary["rows"], 3)
        self.assertEqual(summary["ready"], 2)
        self.assertEqual(summary["review"], 1)
        self.assertEqual(summary["reject"], 0)
        self.assertEqual(summary["increases"], 1)
        self.assertEqual(summary["decreases"], 1)
        self.assertAlmostEqual(summary["max_increase_pct"], 10.0)
        self.assertAlmostEqual(summary["max_decrease_pct"], -5.0)
        self.assertEqual(len(staged), 3)
        self.assertIn("cost_change_pct", staged[0])
        self.assertIn("source_row", staged[0])

    def test_xlsx_notice_is_supported(self):
        try:
            from openpyxl import Workbook
        except ImportError:
            self.skipTest("openpyxl not installed")

        with tempfile.TemporaryDirectory() as temp:
            path = Path(temp) / "notice.xlsx"
            workbook = Workbook()
            sheet = workbook.active
            sheet.title = "Price Update"
            sheet.append(["Vendor", "Vendor SKU", "New Cost", "Effective", "Unit of Measure"])
            sheet.append(["Synthetic Glass", "RG12", 1.25, date(2026, 9, 1), "EA"])
            workbook.save(path)
            workbook.close()
            rows = load_supplier_notice(path)

        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0].source_sheet, "Price Update")
        self.assertEqual(rows[0].supplier_item_no, "RG12")
        self.assertEqual(rows[0].new_cost, 1.25)
        self.assertEqual(rows[0].effective_date, date(2026, 9, 1))
        self.assertEqual(rows[0].status, "REVIEW")


if __name__ == "__main__":
    unittest.main()
