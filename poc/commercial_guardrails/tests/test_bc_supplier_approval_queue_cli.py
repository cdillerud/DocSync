import unittest
from unittest.mock import patch

from poc.commercial_guardrails.bc_supplier_approval_queue_cli import _build_impacts


class SupplierApprovalQueueCliTests(unittest.TestCase):
    def test_margin_engine_receives_current_cost_spread_parameter_name(self):
        with patch(
            "poc.commercial_guardrails.bc_supplier_approval_queue_cli.analyze_supplier_margin_impact",
            return_value="IMPACT",
        ) as mocked:
            result = _build_impacts(
                ["COMPARISON"],
                ["TRANSACTION"],
                ["RULE"],
                recent_item_cost_count=10,
                recent_customer_count=3,
                history_alignment_tolerance_pct=5.0,
                max_recent_cost_spread_pct=15.0,
                trailing_days=365,
            )

        self.assertEqual(result, ["IMPACT"])
        kwargs = mocked.call_args.kwargs
        self.assertEqual(kwargs["max_recent_cost_spread_pct"], 15.0)
        self.assertNotIn("recent_cost_spread_tolerance_pct", kwargs)
        self.assertEqual(kwargs["history_alignment_tolerance_pct"], 5.0)
        self.assertEqual(kwargs["trailing_days"], 365)


if __name__ == "__main__":
    unittest.main()
