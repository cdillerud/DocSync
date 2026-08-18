import unittest
from datetime import date

from poc.commercial_guardrails.proposal_guard import Proposal, ProposalException
from poc.commercial_guardrails.proposal_special_pricing import (
    ProposalPricingRule,
    apply_special_pricing_firewall,
    matching_proposal_pricing_rules,
)


def proposal(price=195.0):
    return Proposal(
        customer_no="BRAGG",
        item_no="RING12",
        unit_price=price,
        quantity=10,
        uom="M",
    )


def price_exception(kind="SELL_BELOW_CUSTOMER_HISTORY"):
    return ProposalException(
        exception_type=kind,
        severity="HIGH",
        actual="bad",
        expected="baseline",
        estimated_exposure=100.0,
        recommended_action="REVIEW QUOTED SELL PRICE",
        explanation="Historical anomaly.",
    )


class ProposalSpecialPricingTests(unittest.TestCase):
    def test_active_special_pricing_rewrites_pricing_action(self):
        rules = [
            ProposalPricingRule(
                customer_no="BRAGG",
                item_no="RING12",
                rule_type="SPECIAL_PRICING",
                effective_from=date(2026, 1, 1),
                effective_to=date(2026, 12, 31),
                approver="Commercial Lead",
                notes="Synthetic test rule",
            )
        ]

        context, exceptions = apply_special_pricing_firewall(
            proposal(),
            [price_exception(), price_exception("LOW_GP_ANOMALY")],
            rules,
            as_of="2026-08-17",
        )

        self.assertTrue(context["protected"])
        self.assertEqual(exceptions[0].exception_type, "SPECIAL_PRICING_PROTECTED")
        actionable = [e for e in exceptions if e.exception_type != "SPECIAL_PRICING_PROTECTED"]
        self.assertTrue(all("REVIEW SPECIAL PRICING RULE" in e.recommended_action for e in actionable))

    def test_quote_exception_is_rewritten_by_special_pricing(self):
        rules = [ProposalPricingRule("BRAGG", "RING12", "SPECIAL_PRICING", approver="Commercial Lead")]
        quote_exc = price_exception("QUOTE_BELOW_CUSTOMER_HISTORY")
        quote_exc.recommended_action = "REVIEW PROPOSED EXTRA PRICE AGAINST CUSTOMER HISTORY"

        _, exceptions = apply_special_pricing_firewall(
            proposal(),
            [quote_exc],
            rules,
            as_of="2026-08-17",
        )
        rewritten = next(e for e in exceptions if e.exception_type == "QUOTE_BELOW_CUSTOMER_HISTORY")
        self.assertEqual(rewritten.recommended_action, "REVIEW SPECIAL PRICING RULE WITH Commercial Lead")

    def test_item_substitution_action_is_not_rewritten(self):
        rules = [ProposalPricingRule("BRAGG", "RING12", "SPECIAL_PRICING", approver="Commercial Lead")]
        item_exc = price_exception("SIMILAR_ITEM_SUBSTITUTION")
        item_exc.recommended_action = "VERIFY ITEM SPECIFICATION BEFORE PROCESSING"

        _, exceptions = apply_special_pricing_firewall(proposal(), [item_exc], rules, as_of="2026-08-17")
        substitution = next(e for e in exceptions if e.exception_type == "SIMILAR_ITEM_SUBSTITUTION")
        self.assertEqual(substitution.recommended_action, "VERIFY ITEM SPECIFICATION BEFORE PROCESSING")

    def test_expired_rule_does_not_match(self):
        rules = [
            ProposalPricingRule(
                customer_no="BRAGG",
                item_no="RING12",
                rule_type="SPECIAL_PRICING",
                effective_to=date(2025, 12, 31),
            )
        ]
        matches = matching_proposal_pricing_rules(proposal(), rules, as_of="2026-08-17")
        self.assertEqual(matches, [])

    def test_fixed_price_mismatch_is_critical(self):
        rules = [
            ProposalPricingRule(
                customer_no="BRAGG",
                item_no="RING12",
                rule_type="FIXED_PRICE",
                locked_sell_price=224.81,
                approver="Commercial Lead",
            )
        ]
        _, exceptions = apply_special_pricing_firewall(proposal(195.0), [], rules, as_of="2026-08-17")
        mismatch = next(e for e in exceptions if e.exception_type == "FIXED_PRICE_MISMATCH")
        self.assertEqual(mismatch.severity, "CRITICAL")
        self.assertAlmostEqual(mismatch.estimated_exposure, 298.10, places=2)

    def test_more_specific_fixed_price_overrides_wildcard(self):
        rules = [
            ProposalPricingRule("BRAGG", "*", "FIXED_PRICE", locked_sell_price=200.0),
            ProposalPricingRule("BRAGG", "RING12", "FIXED_PRICE", locked_sell_price=224.81),
        ]
        _, exceptions = apply_special_pricing_firewall(proposal(224.81), [], rules, as_of="2026-08-17")
        self.assertNotIn("CONFLICTING_FIXED_PRICE_RULES", {e.exception_type for e in exceptions})
        self.assertNotIn("FIXED_PRICE_MISMATCH", {e.exception_type for e in exceptions})


if __name__ == "__main__":
    unittest.main()
