import tempfile
import unittest
from pathlib import Path

from poc.commercial_guardrails.supplier_cockpit_core import (
    detail_rows_for_item,
    load_csv_records,
    records_to_csv,
    summarize_queue,
    validate_decisions,
    write_decision_csv,
)


class SupplierCockpitCoreTests(unittest.TestCase):
    def test_summary_uses_queue_rows_only(self):
        rows = [
            {
                "queue_status": "PENDING_APPROVAL",
                "affected_customers": "4",
                "protected_customers": "0",
                "estimated_margin_erosion": "3041.28",
            },
            {
                "queue_status": "PROTECTED_REVIEW",
                "affected_customers": "2",
                "protected_customers": "1",
                "estimated_margin_erosion": "100.00",
            },
        ]
        summary = summarize_queue(rows)
        self.assertEqual(summary["items"], 2)
        self.assertEqual(summary["protected_items"], 1)
        self.assertEqual(summary["affected_customers"], 6)
        self.assertEqual(summary["protected_customers"], 1)
        self.assertAlmostEqual(summary["estimated_margin_erosion"], 3141.28, places=2)

    def test_protected_review_cannot_be_approved(self):
        errors = validate_decisions(
            [
                {
                    "queue_status": "PROTECTED_REVIEW",
                    "gpi_item_no": "ITEM1",
                    "decision": "APPROVE",
                    "decision_by": "Chad",
                }
            ]
        )
        self.assertTrue(any("cannot be approved" in error for error in errors))

    def test_decision_requires_decision_by(self):
        errors = validate_decisions(
            [
                {
                    "queue_status": "PENDING_APPROVAL",
                    "gpi_item_no": "ITEM1",
                    "decision": "HOLD",
                    "decision_by": "",
                }
            ]
        )
        self.assertTrue(any("decision_by is required" in error for error in errors))

    def test_detail_rows_are_item_scoped_and_sorted_by_erosion(self):
        rows = [
            {"gpi_item_no": "ITEM1", "customer_no": "A", "estimated_margin_erosion": "10"},
            {"gpi_item_no": "ITEM1", "customer_no": "B", "estimated_margin_erosion": "50"},
            {"gpi_item_no": "ITEM2", "customer_no": "C", "estimated_margin_erosion": "999"},
        ]
        detail = detail_rows_for_item(rows, "ITEM1")
        self.assertEqual([row["customer_no"] for row in detail], ["B", "A"])

    def test_decision_csv_roundtrip(self):
        rows = [
            {
                "queue_status": "PENDING_APPROVAL",
                "gpi_item_no": "ITEM1",
                "estimated_margin_erosion": "100.00",
                "decision": "APPROVE",
                "decision_by": "Chad",
                "decision_notes": "Reviewed synthetic POC item",
            }
        ]
        text = records_to_csv(rows)
        self.assertIn("decision_by", text)
        with tempfile.TemporaryDirectory() as folder:
            path = Path(folder) / "decisions.csv"
            write_decision_csv(rows, path)
            loaded = load_csv_records(path)
        self.assertEqual(loaded[0]["decision"], "APPROVE")
        self.assertEqual(loaded[0]["decision_by"], "Chad")


if __name__ == "__main__":
    unittest.main()
