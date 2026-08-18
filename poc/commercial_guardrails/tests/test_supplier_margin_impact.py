import unittest
from datetime import date, datetime

from poc.commercial_guardrails.engine import Transaction
from poc.commercial_guardrails.proposal_special_pricing import ProposalPricingRule
from poc.commercial_guardrails.supplier_margin_impact import analyze_supplier_margin_impact
from poc.commercial_guardrails.supplier_price_compare import SupplierPriceComparison
from poc.commercial_guardrails.supplier_price_ingest import SupplierPriceChange


def staged(
    *,
    current=160.0,
    new=169.6,
    effective=date(2026, 9, 1),
    item="20041936-P4305",
    uom="M",
    tier=1.0,
):
    warnings = () if current is not None else ("current cost not supplied; BC comparison required",)
    return SupplierPriceChange(
        supplier_name="Synthetic Supplier",
        supplier_item_no="RG12-HF",
        gpi_item_no=item,
        description="12oz ring neck",
        current_cost=current,
        new_cost=new,
        effective_date=effective,
        uom=uom,
        tier_qty=tier,
        freight_included=True,
        currency="USD",
        source_file="sample.csv",
        source_sheet="",
        source_row=2,
        status="READY" if current is not None and effective is not None else "REVIEW",
        warnings=warnings,
    )


def comparison(row=None, *, status="REVIEW", match="EXACT_ITEM_UOM", bc_cost=200.98):
    row = row or staged()
    return SupplierPriceComparison(
        staged=row,
        status=status,
        bc_match=match,
        bc_description="12oz bottle",
        bc_base_uom="EA",
        bc_base_unit_cost=0.20098,
        bc_uom=row.uom,
        bc_qty_per_uom=1000.0,
        bc_unit_cost_in_uom=bc_cost,
        bc_vendor_no="AMCOR",
        bc_vendor_item_no="P4305",
        warnings=("supplier-stated current cost differs materially from BC Item Unit Cost",),
    )


def tx(
    ident,
    when,
    customer,
    *,
    cost=160.0,
    sell=224.81,
    qty=10.0,
    item="20041936-P4305",
    uom="M",
):
    return Transaction(
        transaction_id=ident,
        order_no=ident,
        transaction_date=datetime.strptime(when, "%Y-%m-%d"),
        customer_no=customer,
        customer_name=customer,
        item_no=item,
        item_description="12oz ring neck",
        quantity=qty,
        uom=uom,
        unit_cost=cost,
        unit_sell_price=sell,
        sales_rep="REP1",
        special_pricing=False,
    )


class SupplierMarginImpactTests(unittest.TestCase):
    def test_posted_cost_alignment_can_make_impact_ready_when_item_master_cost_differs(self):
        rows = [
            tx("1", "2026-01-01", "TRIPLEH", cost=159.0),
            tx("2", "2026-02-01", "TRIPLEH", cost=160.0),
            tx("3", "2026-03-01", "TRIPLEH", cost=161.0),
        ]
        impact = analyze_supplier_margin_impact(comparison(), rows)
        self.assertEqual(impact.status, "IMPACT_READY")
        self.assertAlmostEqual(impact.recent_posted_cost_median, 160.0, places=2)
        self.assertAlmostEqual(impact.cost_delta, 9.6, places=2)
        self.assertTrue(any("BC Item Unit Cost context is not aligned" in note for note in impact.warnings))

    def test_supplier_current_cost_misalignment_requires_review(self):
        row = staged(current=200.0, new=212.0)
        rows = [tx("1", "2026-01-01", "TRIPLEH", cost=160.0)]
        impact = analyze_supplier_margin_impact(comparison(row), rows)
        self.assertEqual(impact.status, "REVIEW")
        self.assertGreater(abs(impact.supplier_current_vs_posted_pct), 5.0)

    def test_missing_supplier_current_cost_requires_review(self):
        row = staged(current=None, new=178.5)
        impact = analyze_supplier_margin_impact(comparison(row, bc_cost=0.0), [tx("1", "2026-01-01", "A")])
        self.assertEqual(impact.status, "REVIEW")
        self.assertIsNone(impact.cost_delta)

    def test_no_exact_item_uom_history_requires_review(self):
        impact = analyze_supplier_margin_impact(
            comparison(),
            [tx("1", "2026-01-01", "A", item="OTHER")],
        )
        self.assertEqual(impact.status, "REVIEW")
        self.assertEqual(impact.historical_lines, 0)

    def test_customer_gp_and_margin_erosion_are_calculated_from_supplier_delta(self):
        rows = [
            tx("1", "2026-01-01", "TRIPLEH", cost=160.0, sell=224.81, qty=10.0),
            tx("2", "2026-02-01", "TRIPLEH", cost=160.0, sell=224.81, qty=20.0),
            tx("3", "2026-03-01", "TRIPLEH", cost=160.0, sell=224.81, qty=30.0),
        ]
        impact = analyze_supplier_margin_impact(comparison(), rows)
        customer = impact.customer_impacts[0]
        self.assertAlmostEqual(customer.projected_cost, 169.6, places=2)
        self.assertAlmostEqual(customer.gp_drop_points, (9.6 / 224.81) * 100.0, places=2)
        self.assertAlmostEqual(customer.trailing_quantity, 60.0, places=2)
        self.assertAlmostEqual(customer.estimated_margin_erosion, 576.0, places=2)

    def test_trailing_window_excludes_old_volume(self):
        rows = [
            tx("old", "2024-01-01", "TRIPLEH", qty=1000.0),
            tx("new1", "2026-01-01", "TRIPLEH", qty=10.0),
            tx("new2", "2026-06-01", "TRIPLEH", qty=20.0),
        ]
        impact = analyze_supplier_margin_impact(comparison(), rows, trailing_days=365)
        customer = impact.customer_impacts[0]
        self.assertAlmostEqual(customer.trailing_quantity, 30.0, places=2)
        self.assertAlmostEqual(customer.estimated_margin_erosion, 288.0, places=2)

    def test_special_pricing_is_marked_on_customer_impact(self):
        rules = [
            ProposalPricingRule(
                customer_no="TRIPLEH",
                item_no="20041936-P4305",
                rule_type="SPECIAL_PRICING",
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 12, 31),
                approver="Commercial Lead",
            )
        ]
        impact = analyze_supplier_margin_impact(
            comparison(),
            [tx("1", "2026-03-01", "TRIPLEH")],
            pricing_rules=rules,
        )
        customer = impact.customer_impacts[0]
        self.assertTrue(customer.special_pricing_protected)
        self.assertEqual(customer.pricing_approvers, ("Commercial Lead",))

    def test_customers_are_sorted_by_estimated_margin_erosion(self):
        rows = [
            tx("a1", "2026-03-01", "SMALL", qty=5.0),
            tx("b1", "2026-03-01", "LARGE", qty=50.0),
        ]
        impact = analyze_supplier_margin_impact(comparison(), rows)
        self.assertEqual([row.customer_no for row in impact.customer_impacts], ["LARGE", "SMALL"])


if __name__ == "__main__":
    unittest.main()
