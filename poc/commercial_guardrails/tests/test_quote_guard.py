import unittest
from datetime import datetime

from poc.commercial_guardrails.engine import Transaction
from poc.commercial_guardrails.proposal_guard import Proposal
from poc.commercial_guardrails.quote_guard import analyze_quote_extra


def tx(customer, price, day, uom="EA", item="BALLARTWORK"):
    return Transaction(
        transaction_id=f"INV-{customer}-{day}-{price}",
        order_no=f"SO-{customer}-{day}",
        transaction_date=datetime(2026, 1, day),
        customer_no=customer,
        customer_name=customer,
        item_no=item,
        item_description="Ball artwork",
        quantity=1.0,
        uom=uom,
        unit_cost=0.0,
        unit_sell_price=float(price),
    )


def proposal(customer, price, uom="EA"):
    return Proposal(
        customer_no=customer,
        item_no="BALLARTWORK",
        unit_price=float(price),
        quantity=1.0,
        uom=uom,
    )


class QuoteGuardTests(unittest.TestCase):
    def test_hummkom_style_900_is_below_recent_customer_history(self):
        history = [
            tx("HUMMKOM", 1000, 1),
            tx("HUMMKOM", 1000, 2),
            tx("HUMMKOM", 1000, 3),
            tx("HUMMKOM", 1900, 4),
            tx("HUMMKOM", 1900, 5),
        ]
        profile, exceptions = analyze_quote_extra(history, proposal("HUMMKOM", 900))
        self.assertEqual(profile["benchmark_source"], "CUSTOMER")
        self.assertIn("QUOTE_BELOW_CUSTOMER_HISTORY", {e.exception_type for e in exceptions})

    def test_talking_900_control_passes(self):
        history = [tx("TALKING", 900, day) for day in range(1, 8)]
        profile, exceptions = analyze_quote_extra(history, proposal("TALKING", 900))
        self.assertEqual(profile["confidence"], "HIGH")
        self.assertEqual(exceptions, [])

    def test_new_customer_uses_broad_context_without_exception(self):
        history = [
            tx("A", 1000, 1),
            tx("B", 950, 2),
            tx("C", 1000, 3),
            tx("D", 850, 4),
        ]
        profile, exceptions = analyze_quote_extra(history, proposal("NEWCUST", 600))
        self.assertEqual(profile["benchmark_source"], "BROAD_CONTEXT_ONLY")
        self.assertEqual(profile["confidence"], "LOW")
        self.assertEqual(exceptions, [])

    def test_stable_customer_small_but_material_drop_flags(self):
        history = [tx("SLATECR", 950, day) for day in range(1, 6)]
        _, exceptions = analyze_quote_extra(history, proposal("SLATECR", 875))
        exc = next(e for e in exceptions if e.exception_type == "QUOTE_BELOW_CUSTOMER_HISTORY")
        self.assertEqual(exc.severity, "HIGH")

    def test_price_above_customer_history_flags(self):
        history = [tx("TALKING", 900, day) for day in range(1, 6)]
        _, exceptions = analyze_quote_extra(history, proposal("TALKING", 1100))
        self.assertIn("QUOTE_ABOVE_CUSTOMER_HISTORY", {e.exception_type for e in exceptions})

    def test_wrong_uom_does_not_borrow_customer_history(self):
        history = [tx("TALKING", 900, day, uom="EA") for day in range(1, 6)]
        profile, exceptions = analyze_quote_extra(history, proposal("TALKING", 900, uom="M"))
        self.assertEqual(profile["customer_history_lines"], 0)
        self.assertEqual(profile["benchmark_source"], "BROAD_CONTEXT_ONLY")
        self.assertEqual(exceptions, [])


if __name__ == "__main__":
    unittest.main()
