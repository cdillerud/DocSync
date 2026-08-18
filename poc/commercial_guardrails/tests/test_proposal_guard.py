import unittest
from datetime import datetime

from poc.commercial_guardrails.proposal_guard import HistoricalLine, Proposal, analyze_proposal


def line(date, customer, item, price, quantity=10.0, uom="M", description=""):
    return HistoricalLine(
        posting_date=datetime.strptime(date, "%Y-%m-%d"),
        invoice_no=f"INV-{date}",
        order_no="",
        customer_no=customer,
        customer_name=customer,
        item_no=item,
        description=description,
        uom=uom,
        quantity=quantity,
        unit_price=price,
        net_amount=price * quantity,
    )


class ProposalGuardTests(unittest.TestCase):
    def setUp(self):
        self.history = [
            line("2024-04-25", "TRIPLEH", "20041936-P4305", 224.81),
            line("2024-05-09", "TRIPLEH", "20041936-P4305", 224.81),
            line("2024-07-15", "TRIPLEH", "20041936-P4305", 224.81),
            line("2024-11-11", "TRIPLEH", "20041936-P4305", 224.81),
            line("2025-01-31", "TRIPLEH", "20041936-P4305", 224.81),
            line("2025-03-03", "TRIPLEH", "20041936-P4305", 224.81),
            line("2025-05-06", "TRIPLEH", "20041936-P4305", 224.81),
            line("2025-04-30", "GRUMPY", "8404730008", 308.10),
            line("2025-06-27", "GRUMPY", "8404730008", 325.60),
            line("2025-09-29", "GRUMPY", "8404730008", 325.08),
            line("2026-01-09", "GRUMPY", "8404730008", 325.08),
            line("2026-03-13", "GRUMPY", "8404730008", 325.08),
            line("2026-05-19", "GRUMPY", "8404730008", 338.42),
        ]

    def test_tripleh_195_is_below_customer_history(self):
        proposal = Proposal("TRIPLEH", "20041936-P4305", 195.00, 100.0, "M")
        profile, exceptions = analyze_proposal(self.history, proposal)
        types = {e.exception_type for e in exceptions}
        self.assertIn("SELL_BELOW_CUSTOMER_HISTORY", types)
        self.assertAlmostEqual(profile["recent_median_price"], 224.81, places=2)

    def test_same_price_can_be_normal_for_different_customer(self):
        history = self.history + [
            line("2024-05-03", "FELBROF", "20041936-P4305", 194.51),
            line("2024-06-21", "FELBROF", "20041936-P4305", 194.51),
            line("2024-11-06", "FELBROF", "20041936-P4305", 194.51),
            line("2025-03-17", "FELBROF", "20041936-P4305", 194.51),
        ]
        proposal = Proposal("FELBROF", "20041936-P4305", 195.00, 10.0, "M")
        _, exceptions = analyze_proposal(history, proposal)
        self.assertNotIn("SELL_BELOW_CUSTOMER_HISTORY", {e.exception_type for e in exceptions})

    def test_grumpy_hot_fill_item_is_similar_item_substitution(self):
        proposal = Proposal("GRUMPY", "20041936-P4305", 224.81, 5.0, "M")
        _, exceptions = analyze_proposal(self.history, proposal)
        records = [e for e in exceptions if e.exception_type == "SIMILAR_ITEM_SUBSTITUTION"]
        self.assertEqual(len(records), 1)
        self.assertIn("8404730008", records[0].expected)

    def test_grumpy_latest_price_is_not_an_outlier(self):
        proposal = Proposal("GRUMPY", "8404730008", 338.42, 5.0, "M")
        profile, exceptions = analyze_proposal(self.history, proposal)
        self.assertAlmostEqual(profile["recent_median_price"], 325.08, places=2)
        self.assertFalse(
            {"SELL_BELOW_CUSTOMER_HISTORY", "SELL_ABOVE_CUSTOMER_HISTORY"}
            .intersection({e.exception_type for e in exceptions})
        )

    def test_uom_change_is_flagged(self):
        proposal = Proposal("TRIPLEH", "20041936-P4305", 224.81, 1000.0, "EA")
        _, exceptions = analyze_proposal(self.history, proposal)
        self.assertIn("UOM_MISMATCH", {e.exception_type for e in exceptions})


if __name__ == "__main__":
    unittest.main()
