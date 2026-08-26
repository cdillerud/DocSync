from __future__ import annotations

import os
import unittest
from unittest.mock import Mock, patch
from uuid import UUID

from ai_provider import (
    CommercialAIEvaluationError,
    evaluate_with_ai,
)
from commercial_agent_contract import CommercialEvaluationRequest


class AIProviderTests(unittest.TestCase):
    def setUp(self) -> None:
        self.original_endpoint = os.environ.get("GPI_AI_EVALUATION_ENDPOINT")
        self.original_bearer = os.environ.get("GPI_AI_EVALUATION_BEARER")
        os.environ["GPI_AI_EVALUATION_ENDPOINT"] = "https://example.invalid/evaluate"
        os.environ["GPI_AI_EVALUATION_BEARER"] = "test-token"

    def tearDown(self) -> None:
        if self.original_endpoint is None:
            os.environ.pop("GPI_AI_EVALUATION_ENDPOINT", None)
        else:
            os.environ["GPI_AI_EVALUATION_ENDPOINT"] = self.original_endpoint

        if self.original_bearer is None:
            os.environ.pop("GPI_AI_EVALUATION_BEARER", None)
        else:
            os.environ["GPI_AI_EVALUATION_BEARER"] = self.original_bearer

    def request(self) -> CommercialEvaluationRequest:
        return CommercialEvaluationRequest(
            agentType="lowMargin",
            correlationId=UUID(
                "00000000-0000-0000-0000-000000000010"
            ),
            sourceType="SalesDocument",
            sourceKey="SO10",
            authoritativeFacts={"currentMarginPct": 12.5},
            context={},
            evidence=[],
        )

    @patch("ai_provider.requests.post")
    def test_valid_result_is_accepted(self, post_mock) -> None:
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "contractVersion": "1.0",
            "agentType": "lowMargin",
            "correlationId": "00000000-0000-0000-0000-000000000010",
            "shouldSurface": True,
            "severity": 90,
            "riskScore": 92.5,
            "confidenceScore": 96.0,
            "summary": "Margin materially below historical pattern.",
            "finding": "Current margin is materially below the historical baseline.",
            "recommendedAction": "Review pricing before the next order.",
            "evidenceUsed": ["CurrentMarginPct"],
            "missingContext": [],
            "model": "test-model",
            "evaluationVersion": "0.46",
        }
        post_mock.return_value = response

        result = evaluate_with_ai(self.request())

        self.assertTrue(result.shouldSurface)
        self.assertEqual(result.riskScore, 92.5)
        headers = post_mock.call_args.kwargs["headers"]
        self.assertEqual(headers["Authorization"], "Bearer test-token")

    @patch("ai_provider.requests.post")
    def test_correlation_id_mismatch_is_rejected(self, post_mock) -> None:
        response = Mock()
        response.status_code = 200
        response.json.return_value = {
            "contractVersion": "1.0",
            "agentType": "lowMargin",
            "correlationId": "00000000-0000-0000-0000-000000000011",
            "shouldSurface": False,
            "severity": 0,
            "riskScore": 0,
            "confidenceScore": 80,
            "summary": "No material concern.",
            "finding": "No material concern found.",
            "recommendedAction": "",
            "evidenceUsed": [],
            "missingContext": [],
            "model": "test-model",
            "evaluationVersion": "0.46",
        }
        post_mock.return_value = response

        with self.assertRaises(CommercialAIEvaluationError):
            evaluate_with_ai(self.request())


if __name__ == "__main__":
    unittest.main()
