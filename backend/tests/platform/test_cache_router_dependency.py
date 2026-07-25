from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers import cache as cache_router_module
from routers.cache import router


@pytest.fixture
def reference_cache_collection() -> MagicMock:
    collection = MagicMock(name="bc_reference_cache")
    cursor = MagicMock(name="aggregate_cursor")
    cursor.to_list = AsyncMock(return_value=[])
    collection.aggregate.return_value = cursor
    return collection


@pytest.fixture
def diagnostics_collection() -> MagicMock:
    collection = MagicMock(name="matching_diagnostics")
    collection.count_documents = AsyncMock(return_value=0)
    return collection


@pytest.fixture
def database(
    reference_cache_collection: MagicMock,
    diagnostics_collection: MagicMock,
) -> MagicMock:
    db = MagicMock(name="platform_database")
    db.bc_reference_cache = reference_cache_collection
    db.matching_diagnostics = diagnostics_collection
    return db


@pytest.fixture
def app(database: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[
        get_platform_database
    ] = lambda: database
    return application


def test_cache_metrics_uses_injected_database(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    reference_cache_collection: MagicMock,
    diagnostics_collection: MagicMock,
) -> None:
    cache_service = MagicMock(name="cache_service")
    cache_service.get_status = AsyncMock(
        return_value={
            "status": "ready",
            "last_sync": "2026-07-25T12:00:00Z",
        }
    )
    monkeypatch.setattr(
        cache_router_module,
        "get_cache_service",
        lambda: cache_service,
    )

    records = [
        {"_id": "sales_order", "count": 120},
        {"_id": "purchase_order", "count": 80},
    ]
    reference_cache_collection.aggregate.return_value.to_list = (
        AsyncMock(return_value=records)
    )

    diagnostics_collection.count_documents.side_effect = [
        100,
        75,
        20,
    ]

    with TestClient(app) as client:
        response = client.get("/cache/metrics")

    assert response.status_code == 200
    assert response.json() == {
        "cache_status": {
            "status": "ready",
            "last_sync": "2026-07-25T12:00:00Z",
        },
        "records_by_entity_type": [
            {
                "entity_type": "sales_order",
                "count": 120,
            },
            {
                "entity_type": "purchase_order",
                "count": 80,
            },
        ],
        "total_records": 200,
        "resolution_metrics": {
            "total_resolutions": 100,
            "cache_hit_count": 75,
            "bc_fallback_count": 20,
            "cache_hit_rate": 0.75,
        },
    }

    expected_pipeline = [
        {
            "$group": {
                "_id": "$bc_entity_type",
                "count": {"$sum": 1},
            }
        },
        {"$sort": {"count": -1}},
    ]

    reference_cache_collection.aggregate.assert_called_once_with(
        expected_pipeline
    )
    reference_cache_collection.aggregate.return_value.to_list.assert_awaited_once_with(
        20
    )

    assert (
        diagnostics_collection.count_documents.await_args_list[0].args
        == ({},)
    )
    assert (
        diagnostics_collection.count_documents.await_args_list[1].args
        == ({"cache_results": {"$ne": []}},)
    )
    assert (
        diagnostics_collection.count_documents.await_args_list[2].args
        == ({"bc_fallback_results": {"$ne": []}},)
    )


def test_cache_metrics_handles_zero_resolutions(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    reference_cache_collection: MagicMock,
    diagnostics_collection: MagicMock,
) -> None:
    cache_service = MagicMock(name="cache_service")
    cache_service.get_status = AsyncMock(
        return_value={"status": "ready"}
    )
    monkeypatch.setattr(
        cache_router_module,
        "get_cache_service",
        lambda: cache_service,
    )

    reference_cache_collection.aggregate.return_value.to_list = (
        AsyncMock(return_value=[])
    )
    diagnostics_collection.count_documents.side_effect = [
        0,
        0,
        0,
    ]

    with TestClient(app) as client:
        response = client.get("/cache/metrics")

    assert response.status_code == 200
    assert response.json() == {
        "cache_status": {"status": "ready"},
        "records_by_entity_type": [],
        "total_records": 0,
        "resolution_metrics": {
            "total_resolutions": 0,
            "cache_hit_count": 0,
            "bc_fallback_count": 0,
            "cache_hit_rate": 0.0,
        },
    }


def test_cache_metrics_rounds_hit_rate(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    diagnostics_collection: MagicMock,
) -> None:
    cache_service = MagicMock(name="cache_service")
    cache_service.get_status = AsyncMock(
        return_value={"status": "ready"}
    )
    monkeypatch.setattr(
        cache_router_module,
        "get_cache_service",
        lambda: cache_service,
    )

    diagnostics_collection.count_documents.side_effect = [
        3,
        2,
        1,
    ]

    with TestClient(app) as client:
        response = client.get("/cache/metrics")

    assert response.status_code == 200
    assert (
        response.json()["resolution_metrics"]["cache_hit_rate"]
        == 0.667
    )


def test_cache_metrics_returns_503_without_cache_service(
    app: FastAPI,
    monkeypatch: pytest.MonkeyPatch,
    reference_cache_collection: MagicMock,
    diagnostics_collection: MagicMock,
) -> None:
    monkeypatch.setattr(
        cache_router_module,
        "get_cache_service",
        lambda: None,
    )

    with TestClient(app) as client:
        response = client.get("/cache/metrics")

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Cache service not initialized"
    }

    reference_cache_collection.aggregate.assert_not_called()
    diagnostics_collection.count_documents.assert_not_awaited()


def test_database_dependency_is_not_an_http_parameter(
    app: FastAPI,
) -> None:
    operation = app.openapi()["paths"]["/cache/metrics"]["get"]
    parameters = operation.get("parameters", [])

    assert all(
        parameter["name"] != "database"
        for parameter in parameters
    )


def test_router_source_has_no_legacy_database_dependency() -> None:
    source_path = cache_router_module.__file__

    assert source_path is not None

    with open(source_path, encoding="utf-8") as router_file:
        source = router_file.read()

    assert "get_db" not in source
    assert "from deps import" not in source
    assert "db.bc_reference_cache" not in source
    assert "db.matching_diagnostics" not in source
    assert source.count(
        "Depends(get_platform_database)"
    ) == 1
