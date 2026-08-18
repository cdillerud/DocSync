import unittest
from datetime import datetime

from poc.commercial_guardrails.engine import Transaction
from poc.commercial_guardrails.proposal_guard import Proposal
from poc.commercial_guardrails.proposal_margin import analyze_proposal_margin


def tx(date, cost, sell=224.81, uom="M"):
    return Transaction(
        transaction_id=f"INV-{date}",
        order_no="",
        transaction_date=datetime.strptime(date, "%Y-%m-%d"),
        customer_no="TRIPLEH",
        customer_name="Triple H Food Processors, Inc.",
        item_no="20041936-P4305",
        item_description="12oz 38-400 Ring Neck PET",
        quantity=139.392,
        uom=uom,
        unit_cost=cost,
        unit_sell_price=sell,
    )


class ProposalMarginTests(unittest.TestCase):
    def setUp(self):
        self.history = [
            tx("2024-04-25", 160.579950),
            tx("2024-05-09", 161.640000),
            tx("2024-07-15", 160.800000),
            tx("2024-11-11", 157.970000),
            tx("2025-01-31", 158.840000),
            tx("2025-03-03", 158.459950),
            tx("2025-05-06", 161.039940),
        ]

    def test_tripleh_195_flags_low_gp(self):
        proposal = Proposal("TRIPLEH", "20041936-P4305", 195.00, 139.392, "M")
        profile, exceptions = analyze_proposal_margin(self.history, proposal)
        types = {e.exception_type for e in exceptions}

        self.assertIn("LOW_GP_ANOMALY", types)
        self.assertEqual(profile["margin_history_lines"], 7)
        self.assertAlmostEqual(profile["latest_historical_cost"], 161.039940, places=5)
        self.assertAlmostEqual(profile["estimated_proposal_gp_pct"], 17.42, places=1)
        self.assertGreater(profile["recent_median_gp_pct"], 28.0)

    def test_normal_tripleh_price_does_not_flag_low_gp(self):
        proposal = Proposal("TRIPLEH", "20041936-P4305", 224.81, 139.392, "M")
        _, exceptions = analyze_proposal_margin(self.history, proposal)
        self.assertNotIn("LOW_GP_ANOMALY", {e.exception_type for e in exceptions})

    def test_wrong_uom_does_not_use_m_cost_history(self):
        proposal = Proposal("TRIPLEH", "20041936-P4305", 195.00, 139392.0, "EA")
        profile, exceptions = analyze_proposal_margin(self.history, proposal)
        self.assertEqual(profile["margin_history_lines"], 0)
        self.assertEqual(exceptions, [])

    def test_insufficient_history_does_not_flag(self):
        proposal = Proposal("TRIPLEH", "20041936-P4305", 195.00, 139.392, "M")
        profile, exceptions = analyze_proposal_margin(self.history[:2], proposal)
        self.assertEqual(profile["margin_history_lines"], 2)
        self.assertEqual(exceptions, [])


if __name__ == "__main__":
    unittest.main()
