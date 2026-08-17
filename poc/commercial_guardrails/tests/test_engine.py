import unittest
from pathlib import Path

from poc.commercial_guardrails.engine import analyze_transactions, load_guardrails, load_transactions


ROOT = Path(__file__).resolve().parents[1]


class CommercialGuardrailTests(unittest.TestCase):
    @classmethod
    def setUpClass(cls):
        cls.transactions = load_transactions(ROOT / "sample_transactions.csv")
        cls.rules = load_guardrails(ROOT / "sample_guardrails.csv")
        cls.exceptions = analyze_transactions(cls.transactions, cls.rules)

    def types_for_order(self, order_no):
        return {e.exception_type for e in self.exceptions if e.order_no == order_no}

    def records_for_order(self, order_no):
        return [e for e in self.exceptions if e.order_no == order_no]

    def test_cost_up_sell_flat_is_flagged(self):
        self.assertIn("COST_UP_SELL_FLAT", self.types_for_order("SO1077"))

    def test_low_gp_is_flagged(self):
        self.assertTrue(
            {"LOW_GP_ANOMALY", "MIN_GP_RULE"}.intersection(self.types_for_order("SO1077"))
        )

    def test_special_pricing_firewall_is_visible(self):
        records = self.records_for_order("SO2050")
        self.assertIn("SPECIAL_PRICING_PROTECTED", {r.exception_type for r in records})
        actionable = [r for r in records if r.exception_type != "SPECIAL_PRICING_PROTECTED"]
        self.assertTrue(actionable)
        self.assertTrue(all(r.special_pricing_protected for r in actionable))
        self.assertTrue(
            all(
                "REVIEW SPECIAL PRICING RULE" in r.recommended_action
                for r in actionable
                if r.exception_type not in {"UNUSUAL_ITEM"}
            )
        )

    def test_wrong_or_unusual_item_is_flagged(self):
        self.assertIn("UNUSUAL_ITEM", self.types_for_order("SO3050"))

    def test_fixed_price_matching_value_does_not_create_mismatch(self):
        self.assertNotIn("FIXED_PRICE_MISMATCH", self.types_for_order("SO2050"))


if __name__ == "__main__":
    unittest.main()
