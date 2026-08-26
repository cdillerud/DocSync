from __future__ import annotations

import unittest

from margin_context import calculate_line_margin


class MarginContextTests(unittest.TestCase):
    def test_calculates_margin_from_posted_line_values(self) -> None:
        result = calculate_line_margin(
            {
                "quantity": 100,
                "unitCostLCY": 0.75,
                "lineAmount": 100,
            }
        )

        self.assertEqual(result["deterministicCostAmount"], 75.0)
        self.assertEqual(result["deterministicGrossProfit"], 25.0)
        self.assertEqual(result["deterministicMarginPercent"], 25.0)

    def test_zero_sales_has_no_margin_percent(self) -> None:
        result = calculate_line_margin(
            {
                "quantity": 10,
                "unitCostLCY": 1,
                "lineAmount": 0,
            }
        )

        self.assertIsNone(result["deterministicMarginPercent"])

    def test_negative_margin_is_preserved(self) -> None:
        result = calculate_line_margin(
            {
                "quantity": 10,
                "unitCostLCY": 12,
                "lineAmount": 100,
            }
        )

        self.assertEqual(result["deterministicMarginPercent"], -20.0)


if __name__ == "__main__":
    unittest.main()
