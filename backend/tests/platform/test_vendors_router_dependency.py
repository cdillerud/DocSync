from __future__ import annotations

from unittest.mock import AsyncMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers.vendors import router


class FakeAggregateCursor:
    def __init__(self, rows):
        self.rows = rows
        self.requested_length = None

    async def to_list(self, length):
        self.requested_length = length
        return self.rows[:length]


@pytest.fixture
def app() -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    return application


def test_vendor_match_stats_uses_platform_database_dependency(
    app: FastAPI,
) -> None:
    aggregate_cursor = FakeAggregateCursor(
        [
            {"_id": "spiro", "count": 7},
            {"_id": "cache", "count": 3},
            {"_id": None, "count": 1},
        ]
    )

    spiro_companies = Mock()
    spiro_companies.count_documents = AsyncMock(return_value=25)

    vendor_matches = Mock()
    vendor_matches.count_documents = AsyncMock(return_value=10)
    vendor_matches.aggregate.return_value = aggregate_cursor

    hub_documents = Mock()
    hub_documents.count_documents = AsyncMock(return_value=18)

    database = Mock()
    database.spiro_companies = spiro_companies
    database.vendor_matches = vendor_matches
    database.hub_documents = hub_documents

    app.dependency_overrides[get_platform_database] = lambda: database

    with TestClient(app) as client:
        response = client.get("/vendors/match-stats")

    assert response.status_code == 200
    assert response.json() == {
        "sources": {
            "spiro_companies": 25,
            "cached_matches": 10,
            "documents_with_vendors": 18,
        },
        "matches_by_source": {
            "spiro": 7,
            "cache": 3,
        },
    }

    spiro_companies.count_documents.assert_awaited_once_with({})
    vendor_matches.count_documents.assert_awaited_once_with({})
    hub_documents.count_documents.assert_awaited_once_with(
        {
            "vendor_canonical": {
                "$exists": True,
                "$ne": None,
            }
        }
    )

    vendor_matches.aggregate.assert_called_once_with(
        [
            {"$match": {"source": {"$exists": True}}},
            {
                "$group": {
                    "_id": "$source",
                    "count": {"$sum": 1},
                }
            },
        ]
    )

    assert aggregate_cursor.requested_length == 20


def test_database_dependency_is_not_an_http_parameter(
    app: FastAPI,
) -> None:
    schema = app.openapi()

    parameters = schema["paths"]["/vendors/match-stats"]["get"].get(
        "parameters",
        [],
    )

    assert all(item["name"] != "database" for item in parameters)


def test_vendor_match_route_does_not_require_database(
    app: FastAPI,
) -> None:
    schema = app.openapi()

    operation = schema["paths"]["/vendors/match"]["post"]
    parameters = operation.get("parameters", [])

    assert all(item["name"] != "database" for item in parameters)
