from __future__ import annotations

import os
import unittest
from unittest.mock import MagicMock, patch

import commercial_queue_worker as worker


class CommercialQueueWorkerTests(unittest.TestCase):
    def test_get_next_pending_queue_returns_none_when_empty(self) -> None:
        client = MagicMock()
        client.get_api_json.return_value = {"value": []}

        result = worker.get_next_pending_queue(client=client)

        self.assertIsNone(result)
        client.get_api_json.assert_called_once()

    @patch("commercial_queue_worker.build_cost_change_request")
    def test_cost_change_queue_uses_explicit_previous_and_current_values(
        self,
        build_mock,
    ) -> None:
        sentinel = object()
        build_mock.return_value = sentinel
        queue = {
            "agentType": "Cost Change",
            "itemNo": "I200",
            "sourceKey": "P200",
            "sourceSystemId": None,
            "correlationId": None,
            "previousValue": 10.25,
            "currentValue": 11.50,
        }

        result = worker.build_request_from_queue(
            queue,
            client=MagicMock(),
        )

        self.assertIs(result, sentinel)
        build_mock.assert_called_once_with(
            item_no="I200",
            previous_unit_cost=10.25,
            current_unit_cost=11.50,
            source_key="P200",
            source_system_id=None,
            correlation_id=None,
        )

    @patch("commercial_queue_worker.persist_evaluation")
    @patch("commercial_queue_worker.evaluate_with_ai")
    @patch("commercial_queue_worker._persistence_enabled", return_value=False)
    @patch("commercial_queue_worker.ai_provider_configured", return_value=False)
    @patch("commercial_queue_worker.build_request_from_queue")
    @patch("commercial_queue_worker.get_next_pending_queue")
    def test_screened_out_queue_completes_without_ai_or_persistence(
        self,
        get_next_mock,
        build_mock,
        _configured,
        _persistence,
        evaluate_mock,
        persist_mock,
    ) -> None:
        queue = {
            "id": "00000000-0000-0000-0000-000000000001",
            "@odata.etag": 'W/"1"',
            "entryNo": 10,
            "attemptCount": 0,
        }
        get_next_mock.return_value = queue

        request = MagicMock()
        request.context = {
            "screening": {
                "shouldEvaluate": False,
                "reasons": [],
            }
        }
        build_mock.return_value = request

        client = MagicMock()
        client.patch_api_json.side_effect = [
            {
                "@odata.etag": 'W/"2"',
                "status": "Processing",
            },
            {
                "@odata.etag": 'W/"3"',
                "status": "Completed",
            },
        ]

        result = worker.execute_next_queue(client=client)

        self.assertEqual(result["status"], "completed_no_candidate")
        self.assertEqual(result["queueEntryNo"], 10)
        self.assertEqual(client.patch_api_json.call_count, 2)
        evaluate_mock.assert_not_called()
        persist_mock.assert_not_called()

    @patch("commercial_queue_worker._persistence_enabled", return_value=True)
    @patch("commercial_queue_worker.ai_provider_configured", return_value=False)
    @patch("commercial_queue_worker.build_request_from_queue")
    @patch("commercial_queue_worker.get_next_pending_queue")
    def test_candidate_execute_refuses_without_ai_provider(
        self,
        get_next_mock,
        build_mock,
        _configured,
        _persistence,
    ) -> None:
        get_next_mock.return_value = {"entryNo": 11}
        request = MagicMock()
        request.context = {
            "screening": {
                "shouldEvaluate": True,
                "reasons": ["candidate"],
            }
        }
        build_mock.return_value = request

        with self.assertRaises(worker.QueueWorkerError):
            worker.execute_next_queue(client=MagicMock())

    @patch("commercial_queue_worker._persistence_enabled", return_value=False)
    @patch("commercial_queue_worker.ai_provider_configured", return_value=True)
    @patch("commercial_queue_worker.build_request_from_queue")
    @patch("commercial_queue_worker.get_next_pending_queue")
    def test_candidate_execute_refuses_without_persistence_gate(
        self,
        get_next_mock,
        build_mock,
        _configured,
        _persistence,
    ) -> None:
        get_next_mock.return_value = {"entryNo": 12}
        request = MagicMock()
        request.context = {
            "screening": {
                "shouldEvaluate": True,
                "reasons": ["candidate"],
            }
        }
        build_mock.return_value = request

        with self.assertRaises(worker.QueueWorkerError):
            worker.execute_next_queue(client=MagicMock())


if __name__ == "__main__":
    unittest.main()
