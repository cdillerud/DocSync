import unittest
from datetime import date, datetime

from poc.commercial_guardrails.supplier_approval_queue import (
    build_supplier_approval_queue,
    summarize_supplier_approval_queue,
)
from poc.commercial_guardrails.supplier_margin_impact import (
    CustomerMarginImpact,
    SupplierMarginImpact,
)
from poc.commercial_guardrails.supplier_price_compare import SupplierPriceComparison
from poc.commercial_guardrails.supplier_price_ingest import SupplierPriceChange


def staged(item="ITEM1", current=100.0, new=110.0):
    return SupplierPriceChange(
        supplier_name="Synthetic Supplier",
        supplier_item_no="SUP-1",
        gpi_item_no=item,
        description="Synthetic item",
        current_cost=current,
        new_cost=new,
        effective_date=date(2026, 9, 1),
        uom="M",
        tier_qty=1.0,
        freight_included=True,
        currency="USD",
        source_file="sample.csv",
        source_sheet="",
        source_row=2,
        status="READY",
        warnings=(),
    )


def customer(
    customer_no,
    *,
    erosion,
    projected_gp=20.0,
    gp_drop=4.0,
    protected=False,
    approvers=(),
):
    return CustomerMarginImpact(
        customer_no=customer_no,
        customer_name=customer_no,
        sales_rep="REP",
        history_lines=3,
        last_sale=datetime(2026, 6, 1),
        recent_sell_median=200.0,
        recent_cost_median=150.0,
        projected_cost=160.0,
        current_gp_pct=25.0,
        projected_gp_pct=projected_gp,
        gp_drop_points=gp_drop,
        trailing_quantity=erosion / 10.0,
        trailing_sales=10000.0,
        estimated_margin_erosion=erosion,
        special_pricing_protected=protected,
        pricing_rule_types=("SPECIAL_PRICING",) if protected else (),
        pricing_approvers=tuple(approvers),
    )


def impact(
    *,
    item="ITEM1",
    status="IMPACT_READY",
    customers=(),
    current=100.0,
    new=110.0,
):
    row = staged(item=item, current=current, new=new)
    comparison = SupplierPriceComparison(
        staged=row,
        status="READY_FOR_IMPACT",
        bc_match="EXACT_ITEM_UOM",
        bc_uom="M",
        bc_qty_per_uom=1000.0,
        bc_unit_cost_in_uom=100.0,
    )
    return SupplierMarginImpact(
        comparison=comparison,
        status=status,
        cost_delta=new - current,
        cost_delta_pct=((new - current) / current) * 100.0,
        historical_lines=5,
        historical_customers=len(customers),
        recent_posted_cost_median=current,
        recent_posted_cost_min=current,
        recent_posted_cost_max=current,
        recent_posted_cost_spread_pct=0.0,
        latest_posted_cost=current,
        latest_posted_sale=datetime(2026, 6, 1),
        supplier_current_vs_posted_pct=0.0,
        customer_impacts=tuple(customers),
        warnings=(),
    )


class SupplierApprovalQueueTests(unittest.TestCase):
    def test_only_impact_ready_rows_enter_queue(self):
        rows = build_supplier_approval_queue(
            [
                impact(item="READY", status="IMPACT_READY", customers=(customer("A", erosion=100.0),)),
                impact(item="REVIEW", status="REVIEW", customers=(customer("B", erosion=200.0),)),
                impact(item="REJECT", status="REJECT", customers=()),
            ]
        )
        self.assertEqual([row.gpi_item_no for row in rows], ["READY"])

    def test_unprotected_item_is_pending_approval(self):
        rows = build_supplier_approval_queue(
            [impact(customers=(customer("A", erosion=100.0), customer("B", erosion=50.0)))]
        )
        row = rows[0]
        self.assertEqual(row.queue_status, "PENDING_APPROVAL")
        self.assertEqual(row.affected_customers, 2)
        self.assertEqual(row.protected_customers, 0)
        self.assertAlmostEqual(row.estimated_margin_erosion, 150.0, places=2)
        self.assertEqual(row.top_customer_no, "A")

    def test_protected_customer_routes_item_to_protected_review(self):
        rows = build_supplier_approval_queue(
            [
                impact(
                    customers=(
                        customer("A", erosion=100.0, protected=True, approvers=("Commercial Lead",)),
                        customer("B", erosion=50.0),
                    )
                )
            ]
        )
        row = rows[0]
        self.assertEqual(row.queue_status, "PROTECTED_REVIEW")
        self.assertEqual(row.protected_customers, 1)
        self.assertEqual(row.pricing_approvers, ("Commercial Lead",))
        self.assertIn("SPECIAL PRICING", row.action)

    def test_summary_counts_only_queue_rows(self):
        queue = build_supplier_approval_queue(
            [
                impact(
                    item="P",
                    customers=(customer("A", erosion=100.0, protected=True, approvers=("Lead",)),),
                ),
                impact(item="N", customers=(customer("B", erosion=250.0),)),
                impact(item="R", status="REVIEW", customers=(customer("C", erosion=999.0),)),
            ]
        )
        summary = summarize_supplier_approval_queue(queue)
        self.assertEqual(summary["items"], 2)
        self.assertEqual(summary["protected_items"], 1)
        self.assertEqual(summary["affected_customers"], 2)
        self.assertAlmostEqual(summary["estimated_margin_erosion"], 350.0, places=2)


if __name__ == "__main__":
    unittest.main()
