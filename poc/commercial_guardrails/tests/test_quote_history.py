import unittest
from datetime import datetime

from poc.commercial_guardrails.engine import Transaction
from poc.commercial_guardrails.quote_history import summarize_quote_history


def tx(
    transaction_id: str,
    date_text: str,
    customer: str,
    price: float,
    quantity: float = 1.0,
    uom: str = "EA",
    item: str = "BALLARTWORK",
) -> Transaction:
    return Transaction(
        transaction_id=transaction_id,
        order_no=transaction_id,
        transaction_date=datetime.strptime(date_text, "%Y-%m-%d"),
        customer_no=customer,
        customer_name=customer,
        item_no=item,
        item_description="Ball artwork",
        quantity=quantity,
        uom=uom,
        unit_cost=0.0,
        unit_sell_price=price,
    )


class QuoteHistoryTests(unittest.TestCase):
    def test_all_customer_summary_keeps_customer_specific_prices_visible(self):
        profile = summarize_quote_history(
            [
                tx("INV1", "2025-01-10", "HUMMKOM", 1000.0),
                tx("INV2", "2026-02-15", "TALKING", 900.0),
            ],
            item_no="BALLARTWORK",
        )
        stats = profile["all_history"]
        self.assertEqual(stats["lines"], 2)
        self.assertEqual(stats["customers"], 2)
        self.assertAlmostEqual(stats["median_price"], 950.0, places=2)
        self.assertAlmostEqual(stats["average_price"], 950.0, places=2)
        self.assertEqual([row["customer_no"] for row in profile["by_customer"]], ["HUMMKOM", "TALKING"])

    def test_customer_specific_summary_does_not_borrow_other_customer_price(self):
        profile = summarize_quote_history(
            [
                tx("INV1", "2025-01-10", "HUMMKOM", 1000.0),
                tx("INV2", "2026-02-15", "TALKING", 900.0),
            ],
            item_no="BALLARTWORK",
            customer_no="TALKING",
        )
        stats = profile["customer_history"]
        self.assertEqual(stats["lines"], 1)
        self.assertAlmostEqual(stats["median_price"], 900.0, places=2)

    def test_uom_filter_prevents_mixed_unit_benchmark(self):
        profile = summarize_quote_history(
            [
                tx("INV1", "2025-01-10", "A", 1000.0, uom="EA"),
                tx("INV2", "2026-02-15", "B", 5.0, quantity=100.0, uom="M"),
            ],
            item_no="BALLARTWORK",
            uom="EA",
        )
        stats = profile["all_history"]
        self.assertEqual(stats["lines"], 1)
        self.assertEqual(stats["uoms"], ["EA"])
        self.assertAlmostEqual(stats["median_price"], 1000.0, places=2)

    def test_nonpositive_and_unrelated_lines_are_excluded(self):
        profile = summarize_quote_history(
            [
                tx("INV1", "2025-01-10", "A", 1000.0),
                tx("INV2", "2025-01-11", "A", 0.0),
                tx("INV3", "2025-01-12", "A", 100.0, quantity=0.0),
                tx("INV4", "2025-01-13", "A", 700.0, item="OTHER"),
            ],
            item_no="BALLARTWORK",
        )
        self.assertEqual(profile["all_history"]["lines"], 1)


if __name__ == "__main__":
    unittest.main()
