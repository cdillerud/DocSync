import tempfile
import unittest
from pathlib import Path

from poc.commercial_guardrails.supplier_cockpit_core import (
    decision_widget_scope,
    detail_rows_for_item,
    load_csv_records,
    merge_saved_decisions,
    record_key,
    records_to_csv,
    summarize_queue,
    update_decision,
    validate_decisions,
    validate_detail_consistency,
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

    def test_record_key_uses_item_supplier_item_and_effective_date(self):
        row = {
            "gpi_item_no": " ITEM1 ",
            "supplier_item_no": " SUP-1 ",
            "effective_date": "2026-09-01",
        }
        self.assertEqual(record_key(row), ("item1", "sup-1", "2026-09-01"))

    def test_decision_widget_scope_is_stable_within_same_run(self):
        key = ("item1", "sup-1", "2026-09-01")
        first = decision_widget_scope("runs/run-a/decisions.csv", key)
        second = decision_widget_scope("runs/run-a/decisions.csv", key)
        self.assertEqual(first, second)

    def test_decision_widget_scope_changes_between_runs(self):
        key = ("item1", "sup-1", "2026-09-01")
        first = decision_widget_scope("runs/run-a/decisions.csv", key)
        second = decision_widget_scope("runs/run-b/decisions.csv", key)
        self.assertNotEqual(first, second)

    def test_saved_decisions_overlay_fresh_queue_without_replacing_new_analysis(self):
        queue = [
            {
                "queue_status": "PENDING_APPROVAL",
                "gpi_item_no": "ITEM1",
                "supplier_item_no": "SUP-1",
                "effective_date": "2026-09-01",
                "estimated_margin_erosion": "150.00",
            }
        ]
        saved = [
            {
                "queue_status": "PENDING_APPROVAL",
                "gpi_item_no": "ITEM1",
                "supplier_item_no": "SUP-1",
                "effective_date": "2026-09-01",
                "estimated_margin_erosion": "100.00",
                "decision": "HOLD",
                "decision_by": "Chad",
                "decision_notes": "Check supplier scope",
            }
        ]
        merged = merge_saved_decisions(queue, saved)
        self.assertEqual(merged[0]["estimated_margin_erosion"], "150.00")
        self.assertEqual(merged[0]["decision"], "HOLD")
        self.assertEqual(merged[0]["decision_by"], "Chad")

    def test_update_decision_changes_only_selected_queue_item(self):
        rows = [
            {
                "gpi_item_no": "ITEM1",
                "supplier_item_no": "SUP-1",
                "effective_date": "2026-09-01",
                "decision": "",
            },
            {
                "gpi_item_no": "ITEM2",
                "supplier_item_no": "SUP-2",
                "effective_date": "2026-09-15",
                "decision": "",
            },
        ]
        updated = update_decision(
            rows,
            record_key(rows[0]),
            decision="approve",
            decision_by="Chad",
            decision_notes="Validated",
        )
        self.assertEqual(updated[0]["decision"], "APPROVE")
        self.assertEqual(updated[0]["decision_by"], "Chad")
        self.assertEqual(updated[1]["decision"], "")

    def test_detail_consistency_passes_for_same_snapshot(self):
        queue = {
            "gpi_item_no": "ITEM1",
            "affected_customers": "2",
            "protected_customers": "0",
            "estimated_margin_erosion": "150.00",
            "top_customer_no": "A",
        }
        detail = [
            {
                "customer_no": "A",
                "estimated_margin_erosion": "100.00",
                "special_pricing_protected": "False",
            },
            {
                "customer_no": "B",
                "estimated_margin_erosion": "50.00",
                "special_pricing_protected": "False",
            },
        ]
        self.assertEqual(validate_detail_consistency(queue, detail), [])

    def test_detail_consistency_detects_stale_protection_state(self):
        queue = {
            "gpi_item_no": "ITEM1",
            "affected_customers": "2",
            "protected_customers": "0",
            "estimated_margin_erosion": "150.00",
            "top_customer_no": "A",
        }
        detail = [
            {
                "customer_no": "A",
                "estimated_margin_erosion": "100.00",
                "special_pricing_protected": "True",
            },
            {
                "customer_no": "B",
                "estimated_margin_erosion": "50.00",
                "special_pricing_protected": "False",
            },
        ]
        errors = validate_detail_consistency(queue, detail)
        self.assertTrue(any("protected customer" in error for error in errors))

    def test_detail_consistency_detects_customer_and_erosion_mismatch(self):
        queue = {
            "gpi_item_no": "ITEM1",
            "affected_customers": "2",
            "protected_customers": "0",
            "estimated_margin_erosion": "150.00",
            "top_customer_no": "A",
        }
        detail = [
            {
                "customer_no": "A",
                "estimated_margin_erosion": "99.00",
                "special_pricing_protected": "False",
            }
        ]
        errors = validate_detail_consistency(queue, detail)
        self.assertTrue(any("customer detail has 1 row" in error for error in errors))
        self.assertTrue(any("does not match queue erosion" in error for error in errors))


if __name__ == "__main__":
    unittest.main()
