"""
Tests for line-item reconciliation and invoice-total sanity checks.

Covers the three defensive layers introduced to prevent freight-style
invoices (where qty * unit_price != line total) from posting incorrect
amounts to Business Central:

  1. reconcile_line_amounts — unit tests for the pure function
  2. build_smart_pi_lines — integration test that the PI builder
     applies reconciliation to every line
  3. detect_deviations — the invoice-total sanity check emits a
     `total_mismatch` critical deviation when planned lines don't
     sum to the invoice's extracted total
"""

from services.line_reconciliation import (
    reconcile_line_amounts,
    format_reconcile_suffix,
)
from services.vendor_invoice_profile_service import (
    build_smart_pi_lines,
    detect_deviations,
)


# ---------------------------------------------------------------------------
# 1. reconcile_line_amounts — pure function tests
# ---------------------------------------------------------------------------

class TestReconcileLineAmounts:
    def test_consistent_line_requires_no_reconciliation(self):
        """qty * unit_price == total -> no reconciliation, raw values preserved."""
        qty, unit_cost, info = reconcile_line_amounts(
            {"quantity": 10, "unit_price": 5.00, "total": 50.00}
        )
        assert qty == 10
        assert unit_cost == 5.00
        assert info is None

    def test_xpologi_regression_payload(self):
        """Regression test for doc 76410e9e XPO line 1 (the $715K bug).
        Raw: qty=2600, unit_price=277.68, total=7219.68.
        Expected: qty preserved at 2600, unit_cost derived = 2.7768."""
        qty, unit_cost, info = reconcile_line_amounts(
            {"quantity": 2600, "unit_price": 277.68, "total": 7219.68}
        )
        assert qty == 2600
        assert abs(unit_cost - (7219.68 / 2600)) < 1e-6
        assert info is not None
        assert info["strategy"] == "preserve_qty"
        assert info["raw_qty"] == 2600
        assert info["raw_unit_price"] == 277.68
        assert info["raw_total"] == 7219.68
        # Sanity: reconciled qty * unit_cost matches total
        assert abs(qty * unit_cost - 7219.68) < 0.01

    def test_zero_qty_collapses_to_unit(self):
        """qty missing or zero -> qty=1, unit_cost=total."""
        qty, unit_cost, info = reconcile_line_amounts(
            {"quantity": 0, "unit_price": 0, "total": 99.99}
        )
        assert qty == 1
        assert unit_cost == 99.99
        assert info is not None
        assert info["strategy"] == "collapse_to_unit"

    def test_missing_qty_defaults_to_one(self):
        """No quantity key at all, with valid unit_price and total that agree."""
        qty, unit_cost, info = reconcile_line_amounts(
            {"unit_price": 50.00, "total": 50.00}
        )
        assert qty == 1
        assert unit_cost == 50.00
        assert info is None

    def test_no_total_uses_qty_times_unit_price(self):
        """When `total` is absent, no reconciliation possible; trust qty * unit_price."""
        qty, unit_cost, info = reconcile_line_amounts(
            {"quantity": 3, "unit_price": 10.00}
        )
        assert qty == 3
        assert unit_cost == 10.00
        assert info is None

    def test_tolerance_absorbs_penny_rounding(self):
        """qty * unit_price within $0.01 of total -> treated as consistent."""
        # qty=3, unit_price=33.333 -> 99.999; total=100.00 (delta 0.001)
        qty, unit_cost, info = reconcile_line_amounts(
            {"quantity": 3, "unit_price": 33.333, "total": 100.00}
        )
        assert qty == 3
        assert unit_cost == 33.333
        assert info is None

    def test_accepts_camelcase_unit_cost_key(self):
        """Preflight uses `unitCost`; extractor uses `unit_price`. Both must work."""
        qty, unit_cost, info = reconcile_line_amounts(
            {"quantity": 2, "unitCost": 25.00, "total": 50.00}
        )
        assert qty == 2
        assert unit_cost == 25.00
        assert info is None

    def test_accepts_amount_key_for_total(self):
        """Some producers use `amount` instead of `total`."""
        qty, unit_cost, info = reconcile_line_amounts(
            {"quantity": 2600, "unit_price": 277.68, "amount": 7219.68}
        )
        assert qty == 2600
        assert abs(unit_cost - 7219.68 / 2600) < 1e-6
        assert info is not None

    def test_format_reconcile_suffix(self):
        info = {
            "raw_qty": 2600,
            "raw_unit_price": 277.68,
            "raw_total": 7219.68,
            "reason": "irrelevant",
            "strategy": "preserve_qty",
        }
        suffix = format_reconcile_suffix(info)
        assert "2600" in suffix
        assert "$7,219.68" in suffix
        assert "reconciled" in suffix.lower()


# ---------------------------------------------------------------------------
# 2. build_smart_pi_lines — reconciliation flows end-to-end into BC payload
# ---------------------------------------------------------------------------

class TestBuildSmartPiLinesReconciliation:
    @staticmethod
    def _empty_profile():
        """Minimal profile that forces the env_default fallback branch."""
        return {
            "vendor_no": "XPOLOGI",
            "default_line_type": "Account",
            "default_gl_account": "",
            "default_item_code": "",
            "description_pattern": "po_reference",
            "amount_stats": {"sample_count": 0},
            "line_patterns": {},
        }

    def test_xpologi_four_line_freight_invoice_reconciles(self):
        """End-to-end: the real doc 76410e9e line payload produces a BC
        payload whose lines sum to $649.97 (the invoice total), not $715K."""
        doc = {
            "extracted_fields": {
                "amount": 649.97,
                "invoice_number": "954-199691",
                "line_items": [
                    # The bug case — qty*unit_price = $722,008 but total = $7,219.68
                    {"description": "PLT METAL CLOSURES",
                     "quantity": 2600, "unit_price": 277.68, "total": 7219.68},
                    {"description": "XPO LOGISTICS DISCOUNT",
                     "quantity": 1, "unit_price": -6750.40, "total": -6750.40},
                    {"description": "FSC FUEL SURCHARGE",
                     "quantity": 1, "unit_price": 153.69, "total": 153.69},
                    {"description": "CCS CA COMPLIANCE",
                     "quantity": 1, "unit_price": 27.00, "total": 27.00},
                ],
            },
        }
        lines = build_smart_pi_lines(
            doc, self._empty_profile(), po_reference="10000316169984"
        )
        assert len(lines) == 4

        # Line 1 reconciled; others untouched
        assert lines[0].get("reconciled") is True
        assert "reconcile_info" in lines[0]
        assert lines[1].get("reconciled", False) is False
        assert lines[2].get("reconciled", False) is False
        assert lines[3].get("reconciled", False) is False

        # Extended totals must now sum to the invoice amount (within 1 cent).
        extended = sum(line["quantity"] * line["unitCost"] for line in lines)
        assert abs(extended - 649.97) < 0.01, (
            f"Reconciled lines should sum to $649.97, got ${extended:.2f}"
        )

        # Reconciled line 1 preserves qty=2600 (audit semantics).
        assert lines[0]["quantity"] == 2600
        assert abs(lines[0]["unitCost"] - 7219.68 / 2600) < 1e-6

        # Reconciled line description carries the audit suffix.
        assert "reconciled" in lines[0]["description"].lower()
        assert "2600" in lines[0]["description"]

    def test_clean_single_line_not_marked_reconciled(self):
        """A line that's already self-consistent should NOT be flagged."""
        doc = {
            "extracted_fields": {
                "amount": 500.00,
                "line_items": [
                    {"description": "Freight", "quantity": 1,
                     "unit_price": 500.00, "total": 500.00},
                ],
            },
        }
        lines = build_smart_pi_lines(doc, self._empty_profile())
        assert len(lines) == 1
        assert lines[0].get("reconciled", False) is False
        assert "reconcile_info" not in lines[0]
        # Description should NOT have the reconciled suffix
        assert "reconciled" not in lines[0]["description"].lower()


# ---------------------------------------------------------------------------
# 3. detect_deviations — invoice-total sanity check
# ---------------------------------------------------------------------------

class TestInvoiceTotalMismatchDetection:
    @staticmethod
    def _profile_with_history():
        return {
            "vendor_no": "XPOLOGI",
            "amount_stats": {
                "sample_count": 1108,
                "avg_amount": 541.96,
                "amount_stddev": 200.0,
            },
            "line_patterns": {"avg_line_count": 1},
        }

    def test_matching_totals_pass(self):
        """Planned lines sum == invoice total -> no total_mismatch deviation."""
        doc = {"extracted_fields": {"amount": 649.97}}
        planned_lines = [
            {"quantity": 2600, "unitCost": 7219.68 / 2600},  # $7,219.68
            {"quantity": 1, "unitCost": -6750.40},
            {"quantity": 1, "unitCost": 153.69},
            {"quantity": 1, "unitCost": 27.00},
        ]
        deviations = detect_deviations(
            doc, self._profile_with_history(), planned_lines
        )
        mismatches = [d for d in deviations if d["type"] == "total_mismatch"]
        assert mismatches == []

    def test_unreconciled_payload_emits_critical_mismatch(self):
        """The pre-fix bug case: $715K planned vs $649.97 invoice -> critical."""
        doc = {"extracted_fields": {"amount": 649.97}}
        planned_lines = [
            {"quantity": 2600, "unitCost": 277.68},  # naive: $722K
            {"quantity": 1, "unitCost": -6750.40},
            {"quantity": 1, "unitCost": 153.69},
            {"quantity": 1, "unitCost": 27.00},
        ]
        deviations = detect_deviations(
            doc, self._profile_with_history(), planned_lines
        )
        mismatches = [d for d in deviations if d["type"] == "total_mismatch"]
        assert len(mismatches) == 1
        dev = mismatches[0]
        assert dev["severity"] == "critical"
        assert dev["invoice_total"] == 649.97
        assert dev["planned_total"] > 700_000
        assert "Posting blocked" in dev["message"]

    def test_tolerance_allows_small_rounding_drift(self):
        """Planned vs invoice total within tolerance -> no critical deviation."""
        doc = {"extracted_fields": {"amount": 1000.00}}
        # Off by $0.50 (0.05%) - within tolerance
        planned_lines = [{"quantity": 1, "unitCost": 1000.50}]
        deviations = detect_deviations(
            doc, self._profile_with_history(), planned_lines
        )
        mismatches = [d for d in deviations if d["type"] == "total_mismatch"]
        assert mismatches == []

    def test_tolerance_rejects_material_drift(self):
        """Planned vs invoice off by >0.5% and >$1 -> critical."""
        doc = {"extracted_fields": {"amount": 1000.00}}
        # Off by $50 (5%) — well beyond tolerance
        planned_lines = [{"quantity": 1, "unitCost": 1050.00}]
        deviations = detect_deviations(
            doc, self._profile_with_history(), planned_lines
        )
        mismatches = [d for d in deviations if d["type"] == "total_mismatch"]
        assert len(mismatches) == 1
        assert mismatches[0]["severity"] == "critical"

    def test_no_invoice_total_skips_check(self):
        """When invoice total cannot be extracted, total_mismatch doesn't fire."""
        doc = {"extracted_fields": {}}
        planned_lines = [{"quantity": 1, "unitCost": 100.00}]
        deviations = detect_deviations(
            doc, self._profile_with_history(), planned_lines
        )
        mismatches = [d for d in deviations if d["type"] == "total_mismatch"]
        assert mismatches == []
