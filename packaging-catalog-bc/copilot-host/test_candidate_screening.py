from __future__ import annotations

import unittest

from candidate_screening import (
    screen_cost_change,
    screen_incorrect_item,
    screen_low_margin,
)


class CandidateScreeningTests(unittest.TestCase):
    def test_low_margin_surfaces_hard_floor(self) -> None:
        result = screen_low_margin(
            current_margin_pct=17.5,
            historical_margin_pct=30.0,
        )
        self.assertTrue(result.should_evaluate)
        self.assertGreaterEqual(len(result.reasons), 1)

    def test_low_margin_ignores_normal_case(self) -> None:
        result = screen_low_margin(
            current_margin_pct=31.0,
            historical_margin_pct=32.0,
        )
        self.assertFalse(result.should_evaluate)

    def test_cost_change_surfaces_material_change(self) -> None:
        result = screen_cost_change(
            previous_unit_cost=1.00,
            current_unit_cost=1.08,
        )
        self.assertTrue(result.should_evaluate)

    def test_cost_change_ignores_noise(self) -> None:
        result = screen_cost_change(
            previous_unit_cost=1.00,
            current_unit_cost=1.005,
        )
        self.assertFalse(result.should_evaluate)

    def test_incorrect_item_surfaces_new_similar_item(self) -> None:
        result = screen_incorrect_item(
            candidate_purchased_before=False,
            candidate_historical_line_count=0,
            top_similarity_score=96,
        )
        self.assertTrue(result.should_evaluate)
        self.assertGreaterEqual(len(result.reasons), 2)


if __name__ == "__main__":
    unittest.main()
