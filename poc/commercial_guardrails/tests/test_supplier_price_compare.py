import unittest
from datetime import date

from poc.commercial_guardrails.bc_item_costs import BCItemCostContext
from poc.commercial_guardrails.supplier_price_compare import compare_supplier_prices_to_bc
from poc.commercial_guardrails.supplier_price_ingest import SupplierPriceChange


def staged(
    *,
    gpi_item_no="ITEM1",
    current_cost=100.0,
    new_cost=106.0,
    effective_date=date(2026, 9, 1),
    uom="M",
    status="READY",
    warnings=(),
    currency="USD",
    tier_qty=1.0,
):
    return SupplierPriceChange(
        supplier_name="Synthetic Supplier",
        supplier_item_no="SUP-1",
        gpi_item_no=gpi_item_no,
        description="Synthetic item",
        current_cost=current_cost,
        new_cost=new_cost,
        effective_date=effective_date,
        uom=uom,
        tier_qty=tier_qty,
        freight_included=True,
        currency=currency,
        source_file="sample.csv",
        source_sheet="",
        source_row=2,
        status=status,
        warnings=tuple(warnings),
    )


def context(*, item_no="ITEM1", uom="M", cost=0.1, factor=1000.0, blocked=False):
    return BCItemCostContext(
        item_no=item_no,
        description="BC item",
        base_uom="EA",
        base_unit_cost=cost,
        blocked=blocked,
        vendor_no="VEND1",
        vendor_item_no="SUP-1",
        uom=uom,
        qty_per_uom=factor,
    )


class SupplierPriceComparisonTests(unittest.TestCase):
    def test_exact_item_uom_and_aligned_cost_is_ready_for_impact(self):
        result = compare_supplier_prices_to_bc([staged()], [context()])[0]
        self.assertEqual(result.bc_match, "EXACT_ITEM_UOM")
        self.assertEqual(result.status, "READY_FOR_IMPACT")
        self.assertAlmostEqual(result.bc_unit_cost_in_uom, 100.0, places=4)
        self.assertAlmostEqual(result.new_cost_vs_bc_pct, 6.0, places=2)

    def test_missing_supplier_current_cost_is_resolved_by_exact_bc_context(self):
        row = staged(
            current_cost=None,
            status="REVIEW",
            warnings=("current cost not supplied; BC comparison required",),
        )
        result = compare_supplier_prices_to_bc([row], [context()])[0]
        self.assertEqual(result.status, "READY_FOR_IMPACT")
        self.assertNotIn("current cost not supplied; BC comparison required", result.warnings)
        self.assertTrue(any("BC Item Unit Cost" in warning for warning in result.warnings))

    def test_material_supplier_current_cost_difference_requires_review(self):
        result = compare_supplier_prices_to_bc(
            [staged(current_cost=80.0, new_cost=85.0)],
            [context()],
        )[0]
        self.assertEqual(result.status, "REVIEW")
        self.assertAlmostEqual(result.supplier_current_vs_bc_pct, -20.0, places=2)

    def test_missing_effective_date_remains_review(self):
        row = staged(
            effective_date=None,
            status="REVIEW",
            warnings=("effective date missing or unrecognized",),
        )
        result = compare_supplier_prices_to_bc([row], [context()])[0]
        self.assertEqual(result.status, "REVIEW")

    def test_uom_mismatch_is_not_guessed(self):
        result = compare_supplier_prices_to_bc(
            [staged(uom="CASE")],
            [context(uom="M")],
        )[0]
        self.assertEqual(result.status, "REVIEW")
        self.assertEqual(result.bc_match, "ITEM_ONLY")
        self.assertIsNone(result.bc_unit_cost_in_uom)

    def test_missing_gpi_item_does_not_fuzzy_map_supplier_item(self):
        result = compare_supplier_prices_to_bc(
            [staged(gpi_item_no="")],
            [context()],
        )[0]
        self.assertEqual(result.status, "REVIEW")
        self.assertEqual(result.bc_match, "NO_GPI_ITEM")

    def test_blocked_item_requires_review(self):
        result = compare_supplier_prices_to_bc(
            [staged()],
            [context(blocked=True)],
        )[0]
        self.assertEqual(result.status, "REVIEW")
        self.assertIn("BC item is blocked", result.warnings)

    def test_rejected_staging_row_stays_rejected(self):
        row = staged(
            gpi_item_no="",
            new_cost=None,
            status="REJECT",
            warnings=("missing supplier/GPI item identifier", "missing or invalid new cost"),
        )
        result = compare_supplier_prices_to_bc([row], [context()])[0]
        self.assertEqual(result.status, "REJECT")
        self.assertEqual(result.bc_match, "NOT_ATTEMPTED")


if __name__ == "__main__":
    unittest.main()
