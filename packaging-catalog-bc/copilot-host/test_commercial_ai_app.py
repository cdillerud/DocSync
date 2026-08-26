from __future__ import annotations

import json
import os
import unittest
from unittest.mock import MagicMock
from uuid import UUID

from commercial_agent_contract import CommercialEvaluationRequest
import commercial_ai_app as ai_app


class CommercialAIAppTests(unittest.TestCase):
    def setUp(self) -> None:
        self.previous_key = os.environ.get("OPENAI_API_KEY")
        self.previous_model = os.environ.get("GPI_COMMERCIAL_AI_MODEL")
        os.environ["OPENAI_API_KEY"] = "test-key"
        os.environ["GPI_COMMERCIAL_AI_MODEL"] = "test-model"

    def tearDown(self) -> None:
        if self.previous_key is None:
            os.environ.pop("OPENAI_API_KEY", None)
        else:
            os.environ["OPENAI_API_KEY"] = self.previous_key

        if self.previous_model is None:
            os.environ.pop("GPI_COMMERCIAL_AI_MODEL", None)
        else:
            os.environ["GPI_COMMERCIAL_AI_MODEL"] = self.previous_model

    def _request(self) -> CommercialEvaluationRequest:
        return CommercialEvaluationRequest(
            agentType="incorrectItem",
            correlationId=UUID("00000000-0000-0000-0000-000000000123"),
            sourceType="SalesOrderLine",
            sourceKey="100729:F3U4926QRQQ030001X",
            customerNo="REVELTD",
            itemNo="F3U4926QRQQ030001X",
            documentType="SalesOrder",
            documentNo="100729",
            authoritativeFacts={
                "candidatePurchasedBefore": True,
                "candidateHistoricalLineCount": 1,
                "topSimilarityScore": None,
                "deterministicCandidate": True,
            },
            context={"screening": {"shouldEvaluate": True}},
            evidence=[],
        )

    def test_evaluate_request_preserves_identity_and_contract(self) -> None:
        result_payload = {
            "contractVersion": "1.0",
            "agentType": "incorrectItem",
            "correlationId": "00000000-0000-0000-0000-000000000123",
            "shouldSurface": True,
            "severity": 55,
            "riskScore": 61.5,
            "confidenceScore": 72.0,
            "summary": "Rare customer-item history warrants review.",
            "finding": "The item has only one prior posted-sales occurrence for this customer.",
            "recommendedAction": "Review the order line against the customer's expected bottle specification.",
            "evidenceUsed": ["CandidateHistoricalLines=1"],
            "missingContext": ["Packaging Catalog similarity attributes"],
            "model": "untrusted-model-name",
            "evaluationVersion": "9.9",
        }

        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {
            "output": [
                {
                    "content": [
                        {
                            "type": "output_text",
                            "text": json.dumps(result_payload),
                        }
                    ]
                }
            ]
        }

        post = MagicMock(return_value=response)
        result = ai_app.evaluate_request(self._request(), http_post=post)

        self.assertTrue(result.shouldSurface)
        self.assertEqual(result.agentType, "incorrectItem")
        self.assertEqual(
            str(result.correlationId),
            "00000000-0000-0000-0000-000000000123",
        )
        self.assertEqual(result.model, "test-model")
        self.assertEqual(result.evaluationVersion, "1.0")

        body = post.call_args.kwargs["json"]
        self.assertEqual(body["model"], "test-model")
        self.assertEqual(body["text"]["format"]["type"], "json_schema")
        self.assertTrue(body["text"]["format"]["strict"])

    def test_evaluate_request_rejects_changed_correlation_id(self) -> None:
        payload = {
            "contractVersion": "1.0",
            "agentType": "incorrectItem",
            "correlationId": "00000000-0000-0000-0000-000000000999",
            "shouldSurface": True,
            "severity": 50,
            "riskScore": 50,
            "confidenceScore": 50,
            "summary": "Review.",
            "finding": "Candidate merits review.",
            "recommendedAction": "Review manually.",
            "evidenceUsed": [],
            "missingContext": [],
            "model": "test-model",
            "evaluationVersion": "1.0",
        }
        response = MagicMock()
        response.status_code = 200
        response.json.return_value = {"output_text": json.dumps(payload)}

        with self.assertRaises(RuntimeError):
            ai_app.evaluate_request(
                self._request(),
                http_post=MagicMock(return_value=response),
            )

    def test_endpoint_bearer_guard(self) -> None:
        previous = os.environ.get("GPI_COMMERCIAL_AI_ENDPOINT_BEARER")
        os.environ["GPI_COMMERCIAL_AI_ENDPOINT_BEARER"] = "secret"
        try:
            with self.assertRaises(Exception):
                ai_app._require_endpoint_bearer("Bearer wrong")
            ai_app._require_endpoint_bearer("Bearer secret")
        finally:
            if previous is None:
                os.environ.pop("GPI_COMMERCIAL_AI_ENDPOINT_BEARER", None)
            else:
                os.environ["GPI_COMMERCIAL_AI_ENDPOINT_BEARER"] = previous


if __name__ == "__main__":
    unittest.main()
