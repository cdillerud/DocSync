from __future__ import annotations

from collections.abc import AsyncIterator
from typing import Any
from unittest.mock import AsyncMock, Mock, call, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers.feedback_health import router


class AsyncDocuments:
    def __init__(self, documents: list[dict[str, Any]]) -> None:
        self._documents = documents

    def __aiter__(self) -> AsyncIterator[dict[str, Any]]:
        return self._iterate()

    async def _iterate(self) -> AsyncIterator[dict[str, Any]]:
        for document in self._documents:
            yield document


@pytest.fixture
def database() -> Mock:
    return Mock(name="platform_database")


@pytest.fixture
def app(database: Mock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_platform_database] = lambda: database
    return application


def test_feedback_loop_health_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    stats = {
        "total_events": 12,
        "applied_events": 10,
        "unapplied_events": 2,
    }
    recent_events = [
        {
            "event_type": "vendor_correction",
            "vendor_id": "V100",
            "document_id": "doc-1",
            "source": "review",
            "created_at": "2026-07-24T12:00:00+00:00",
            "applied": True,
        }
    ]
    daily_documents = [
        {"_id": "2026-07-23", "count": 3},
        {"_id": "2026-07-24", "count": 5},
    ]
    vendor_documents = [
        {"_id": "V100", "count": 7},
        {"_id": "V200", "count": 4},
    ]

    recent_cursor = Mock(name="recent_cursor")
    recent_cursor.sort.return_value = recent_cursor
    recent_cursor.limit.return_value = recent_cursor
    recent_cursor.to_list = AsyncMock(return_value=recent_events)

    feedback_events = Mock(name="feedback_events")
    feedback_events.find.return_value = recent_cursor
    feedback_events.aggregate.side_effect = [
        AsyncDocuments(daily_documents),
        AsyncDocuments(vendor_documents),
    ]
    database.feedback_events = feedback_events

    with patch(
        "routers.feedback_health.get_feedback_stats",
        new=AsyncMock(return_value=stats),
    ) as get_stats:
        with TestClient(app) as client:
            response = client.get("/feedback-loop/health")

    assert response.status_code == 200
    assert response.json() == {
        **stats,
        "recent_events": recent_events,
        "daily_activity": [
            {"date": "2026-07-23", "count": 3},
            {"date": "2026-07-24", "count": 5},
        ],
        "top_corrected_vendors": [
            {"vendor_id": "V100", "event_count": 7},
            {"vendor_id": "V200", "event_count": 4},
        ],
    }

    get_stats.assert_awaited_once_with(database)

    feedback_events.find.assert_called_once()
    find_args = feedback_events.find.call_args
    assert find_args.args[0] == {}
    assert find_args.args[1]["_id"] == 0
    assert find_args.args[1]["event_type"] == 1
    assert find_args.args[1]["vendor_id"] == 1

    recent_cursor.sort.assert_called_once_with("created_at", -1)
    recent_cursor.limit.assert_called_once_with(20)
    recent_cursor.to_list.assert_awaited_once_with(20)

    assert feedback_events.aggregate.call_count == 2

    daily_pipeline = feedback_events.aggregate.call_args_list[0].args[0]
    assert daily_pipeline[0]["$match"]["created_at"]["$gte"]
    assert daily_pipeline[1] == {
        "$addFields": {
            "day": {
                "$substr": ["$created_at", 0, 10],
            }
        }
    }
    assert daily_pipeline[-1] == {"$sort": {"_id": 1}}

    vendor_pipeline = feedback_events.aggregate.call_args_list[1].args[0]
    assert vendor_pipeline == [
        {"$match": {"vendor_id": {"$ne": ""}}},
        {"$group": {"_id": "$vendor_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]


def test_replay_feedback_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    result = {
        "processed": 5,
        "applied": 4,
        "failed": 1,
    }

    with patch(
        "routers.feedback_health.replay_unapplied_events",
        new=AsyncMock(return_value=result),
    ) as replay_events:
        with TestClient(app) as client:
            response = client.post("/feedback-loop/replay")

    assert response.status_code == 200
    assert response.json() == result
    replay_events.assert_awaited_once_with(database)


def test_health_database_dependency_is_not_http_parameter(
    app: FastAPI,
) -> None:
    operation = app.openapi()["paths"]["/feedback-loop/health"]["get"]
    parameters = operation.get("parameters", [])

    assert all(
        parameter["name"] != "database"
        for parameter in parameters
    )


def test_replay_database_dependency_is_not_http_parameter(
    app: FastAPI,
) -> None:
    operation = app.openapi()["paths"]["/feedback-loop/replay"]["post"]
    parameters = operation.get("parameters", [])

    assert all(
        parameter["name"] != "database"
        for parameter in parameters
    )
