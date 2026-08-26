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

    @patch("commercial_queue_worker.ai_provider_configured", return_value=False)
    def test_execute_refuses_without_ai_provider(self, _configured) -> None:
        with self.assertRaises(worker.QueueWorkerError):
            worker.execute_next_queue(client=MagicMock())

    @patch("commercial_queue_worker.ai_provider_configured", return_value=True)
    def test_execute_refuses_without_persistence_gate(self, _configured) -> None:
        previous = os.environ.pop("GPI_ENABLE_COMMERCIAL_PERSISTENCE", None)
        try:
            with self.assertRaises(worker.QueueWorkerError):
                worker.execute_next_queue(client=MagicMock())
        finally:
            if previous is not None:
                os.environ["GPI_ENABLE_COMMERCIAL_PERSISTENCE"] = previous


if __name__ == "__main__":
    unittest.main()
