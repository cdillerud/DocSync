from __future__ import annotations

import unittest
from uuid import UUID

from commercial_agent_contract import (
    CommercialEvaluationRequest,
    CommercialEvaluationResult,
    CommercialEvidence,
)
from commercial_persistence import persist_evaluation


CORRELATION = UUID("11111111-2222-3333-4444-555555555555")


class FakeClient:
    def __init__(self):
        self.calls = []

    def post_api_json(self, group, path, *, body=None, api_version="v1.0"):
        self.calls.append((group, path, body))
        if path == "commercialAgentExceptionWrites":
            return {"id": "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee", "entryNo": 42}
        if path == "commercialAgentEvidenceWrites":
            return {"id": "99999999-8888-7777-6666-555555555555", "entryNo": 1}
        raise AssertionError(path)


class PersistenceTests(unittest.TestCase):
    def _request(self):
        return CommercialEvaluationRequest(
            agentType="lowMargin",
            correlationId=CORRELATION,
            sourceType="SalesDocument",
            sourceKey="INV100",
            customerNo="C100",
            itemNo="I100",
            documentType="Sales",
            documentNo="INV100",
            authoritativeFacts={"currentMarginPct": 12.5},
            context={},
            evidence=[
                CommercialEvidence(
                    evidenceType="Margin",
                    sourceSystem="Business Central",
                    sourceRecordType="Sales Document",
                    metric="CurrentMarginPct",
                    currentValue="12.5",
                    comparisonValue="31.0",
                    variance=-18.5,
                    unit="Percent",
                    weight=100,
                    provenance="BC",
                )
            ],
        )

    def _result(self, should_surface=True):
        return CommercialEvaluationResult(
            agentType="lowMargin",
            correlationId=CORRELATION,
            shouldSurface=should_surface,
            severity=90,
            riskScore=95,
            confidenceScore=92,
            summary="Low margin exception",
            finding="Margin is materially below history.",
            recommendedAction="Review pricing.",
            model="test-model",
            evaluationVersion="1.0",
        )

    def test_surfaceable_result_writes_exception_and_evidence(self):
        client = FakeClient()
        result = persist_evaluation(
            self._request(),
            self._result(),
            client=client,
        )
        self.assertTrue(result["persisted"])
        self.assertEqual(42, result["exceptionEntryNo"])
        self.assertEqual(1, result["evidenceCount"])
        self.assertEqual(2, len(client.calls))
        self.assertEqual("commercialAgentWrite", client.calls[0][0])

    def test_non_surfaceable_result_does_not_write(self):
        client = FakeClient()
        result = persist_evaluation(
            self._request(),
            self._result(False),
            client=client,
        )
        self.assertFalse(result["persisted"])
        self.assertEqual([], client.calls)

    def test_correlation_mismatch_is_rejected(self):
        client = FakeClient()
        result = self._result()
        result.correlationId = UUID("aaaaaaaa-1111-2222-3333-bbbbbbbbbbbb")
        with self.assertRaises(ValueError):
            persist_evaluation(self._request(), result, client=client)
        self.assertEqual([], client.calls)


if __name__ == "__main__":
    unittest.main()
