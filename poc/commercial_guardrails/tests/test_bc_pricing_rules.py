import unittest
from datetime import date

from poc.commercial_guardrails.bc_pricing_rules import pricing_rules_from_bc_rows


class BCPricingRuleTests(unittest.TestCase):
    def test_blank_scope_becomes_wildcard(self):
        rules = pricing_rules_from_bc_rows(
            [
                {
                    "enabled": True,
                    "customerNo": "",
                    "itemNo": "",
                    "ruleType": "Special Pricing",
                    "lockedSellPrice": 0,
                    "effectiveFrom": "0001-01-01",
                    "effectiveTo": "0001-01-01",
                    "approver": "Megan",
                    "notes": "All-customer test",
                }
            ]
        )
        self.assertEqual(len(rules), 1)
        self.assertEqual(rules[0].customer_no, "*")
        self.assertEqual(rules[0].item_no, "*")
        self.assertEqual(rules[0].rule_type, "SPECIAL_PRICING")
        self.assertIsNone(rules[0].effective_from)
        self.assertIsNone(rules[0].effective_to)

    def test_fixed_price_and_dates_are_normalized(self):
        rules = pricing_rules_from_bc_rows(
            [
                {
                    "enabled": True,
                    "customerNo": "TRIPLEH",
                    "itemNo": "20041936-P4305",
                    "ruleType": "Fixed Price",
                    "lockedSellPrice": 224.81,
                    "effectiveFrom": "2026-01-01",
                    "effectiveTo": "2026-12-31",
                }
            ]
        )
        rule = rules[0]
        self.assertEqual(rule.rule_type, "FIXED_PRICE")
        self.assertAlmostEqual(rule.locked_sell_price, 224.81, places=2)
        self.assertEqual(rule.effective_from, date(2026, 1, 1))
        self.assertEqual(rule.effective_to, date(2026, 12, 31))

    def test_disabled_row_is_ignored(self):
        rules = pricing_rules_from_bc_rows(
            [
                {
                    "enabled": False,
                    "customerNo": "TRIPLEH",
                    "itemNo": "20041936-P4305",
                    "ruleType": "Special Pricing",
                }
            ]
        )
        self.assertEqual(rules, [])

    def test_numeric_enum_values_are_supported(self):
        special, fixed = pricing_rules_from_bc_rows(
            [
                {"enabled": True, "ruleType": 0},
                {"enabled": True, "ruleType": 1, "lockedSellPrice": 10},
            ]
        )
        self.assertEqual(special.rule_type, "SPECIAL_PRICING")
        self.assertEqual(fixed.rule_type, "FIXED_PRICE")


if __name__ == "__main__":
    unittest.main()
