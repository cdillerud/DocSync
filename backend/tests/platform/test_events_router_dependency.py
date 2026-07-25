from __future__ import annotations

from unittest.mock import Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers.events import router


class FakeCursor:
    def __init__(self, rows):
        self.rows = rows
        self.sort_args = None
        self.limit_value = None

    def sort(self, *args):
        self.sort_args = args
        return self

    def limit(self, value):
        self.limit_value = value
        return self

    async def to_list(self, length):
        return self.rows[:length]


class FakeAggregateCursor:
    def __init__(self, rows):
        self.rows = rows

    async def to_list(self, length):
        return self.rows[:length]


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    return application


def test_recent_events_uses_platform_database_dependency(app: FastAPI) -> None:
    rows = [
        {
            "event_type": "document.created",
            "status": "completed",
            "timestamp": "2026-07-24T12:00:00+00:00",
        }
    ]

    cursor = FakeCursor(rows)
    workflow_events = Mock()
    workflow_events.find.return_value = cursor

    database = Mock()
    database.workflow_events = workflow_events

    app.dependency_overrides[get_platform_database] = lambda: database

    with TestClient(app) as client:
        response = client.get(
            "/events/recent",
            params={
                "limit": 10,
                "event_type": "document.created",
                "status": "completed",
            },
        )

    assert response.status_code == 200
    assert response.json() == {"events": rows, "count": 1}
    workflow_events.find.assert_called_once_with(
        {
            "event_type": "document.created",
            "status": "completed",
        },
        {"_id": 0},
    )
    assert cursor.sort_args == ("timestamp", -1)
    assert cursor.limit_value == 10


def test_event_stats_uses_platform_database_dependency(app: FastAPI) -> None:
    aggregate_rows = [
        {
            "_id": "document.created",
            "count": 5,
            "completed": 4,
            "failed": 1,
            "warning": 0,
        },
        {
            "_id": "document.updated",
            "count": 3,
            "completed": 2,
            "failed": 0,
            "warning": 1,
        },
    ]

    workflow_events = Mock()
    workflow_events.aggregate.return_value = FakeAggregateCursor(
        aggregate_rows
    )

    database = Mock()
    database.workflow_events = workflow_events

    app.dependency_overrides[get_platform_database] = lambda: database

    with TestClient(app) as client:
        response = client.get("/events/stats", params={"since_hours": 48})

    assert response.status_code == 200

    body = response.json()
    assert body["since_hours"] == 48
    assert body["total_events"] == 8
    assert body["total_completed"] == 6
    assert body["total_failed"] == 1
    assert body["by_type"] == aggregate_rows

    workflow_events.aggregate.assert_called_once()
    pipeline = workflow_events.aggregate.call_args.args[0]

    assert pipeline[0]["$match"]["timestamp"]["$gte"]
    assert pipeline[-1] == {"$sort": {"count": -1}}


def test_event_types_does_not_require_database(app: FastAPI) -> None:
    with TestClient(app) as client:
        response = client.get("/events/types")

    assert response.status_code == 200
    assert "event_types" in response.json()


def test_database_dependency_is_not_an_http_parameter(
    app: FastAPI,
) -> None:
    schema = app.openapi()

    recent_parameters = schema["paths"]["/events/recent"]["get"].get(
        "parameters",
        [],
    )
    stats_parameters = schema["paths"]["/events/stats"]["get"].get(
        "parameters",
        [],
    )

    assert all(item["name"] != "database" for item in recent_parameters)
    assert all(item["name"] != "database" for item in stats_parameters)
