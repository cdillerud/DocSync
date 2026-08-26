from __future__ import annotations

import unittest
from unittest.mock import patch
from uuid import UUID

from commercial_agent_service import (
    build_cost_change_request,
    build_incorrect_item_request,
    build_low_margin_request,
)


class CommercialAgentServiceTests(unittest.TestCase):
    @patch("commercial_agent_service.build_margin_context")
    def test_low_margin_request_preserves_authoritative_margin_context(
        self,
        build_margin_context_mock,
    ) -> None:
        build_margin_context_mock.return_value = {
            "current": {"marginPct": 18.0},
            "historical": {"weightedMarginPct": 31.5},
        }

        result = build_low_margin_request(
            customer_no="C100",
            item_no="I100",
            document_no="SO100",
            unit_price=100,
            unit_cost=82,
            quantity=10,
            line_amount=1000,
            correlation_id=UUID(
                "00000000-0000-0000-0000-000000000001"
            ),
        )

        self.assertEqual(result.agentType, "lowMargin")
        self.assertEqual(result.authoritativeFacts["currentMarginPct"], 18.0)
        self.assertEqual(result.evidence[0].variance, -13.5)
        self.assertEqual(result.customerNo, "C100")
        self.assertEqual(result.documentNo, "SO100")

    @patch("commercial_agent_service.cost_change_context")
    def test_cost_change_request_calculates_percentage(
        self,
        cost_change_context_mock,
    ) -> None:
        cost_change_context_mock.return_value = {
            "customerCount": 4,
            "customerExposure": [],
        }

        result = build_cost_change_request(
            item_no="I200",
            previous_unit_cost=10,
            current_unit_cost=12.5,
            correlation_id=UUID(
                "00000000-0000-0000-0000-000000000002"
            ),
        )

        self.assertEqual(result.agentType, "costChange")
        self.assertEqual(result.authoritativeFacts["costDelta"], 2.5)
        self.assertEqual(result.authoritativeFacts["costChangePct"], 25.0)

    @patch("commercial_agent_service.similar_items")
    @patch("commercial_agent_service.incorrect_item_context")
    def test_incorrect_item_request_combines_history_and_similarity(
        self,
        incorrect_item_context_mock,
        similar_items_mock,
    ) -> None:
        incorrect_item_context_mock.return_value = {
            "candidatePurchasedBefore": False,
            "candidateHistoricalLineCount": 0,
        }
        similar_items_mock.return_value = {
            "referenceItemNo": "I300",
            "candidates": [{"itemNo": "I301", "score": 96}],
        }

        result = build_incorrect_item_request(
            customer_no="C300",
            item_no="I300",
            document_no="SO300",
            correlation_id=UUID(
                "00000000-0000-0000-0000-000000000003"
            ),
        )

        self.assertEqual(result.agentType, "incorrectItem")
        self.assertFalse(
            result.authoritativeFacts["candidatePurchasedBefore"]
        )
        self.assertEqual(
            result.context["similarItems"]["candidates"][0]["score"],
            96,
        )
        self.assertEqual(len(result.evidence), 2)


if __name__ == "__main__":
    unittest.main()
