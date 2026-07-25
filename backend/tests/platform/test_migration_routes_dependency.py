from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers import migration_routes as router_module
from routers.migration_routes import router


@pytest.fixture
def documents_collection() -> MagicMock:
    collection = MagicMock(name="hub_documents")

    find_cursor = MagicMock(name="find_cursor")
    limited_cursor = MagicMock(name="limited_cursor")
    limited_cursor.to_list = AsyncMock(return_value=[])

    find_cursor.limit.return_value = limited_cursor
    collection.find.return_value = find_cursor

    aggregate_cursor = MagicMock(name="aggregate_cursor")
    aggregate_cursor.to_list = AsyncMock(return_value=[])
    collection.aggregate.return_value = aggregate_cursor

    return collection


@pytest.fixture
def database(
    documents_collection: MagicMock,
) -> MagicMock:
    db = MagicMock(name="platform_database")
    db.hub_documents = documents_collection
    return db


@pytest.fixture
def app(database: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[
        get_platform_database
    ] = lambda: database
    return application


def test_run_migration_does_not_require_database(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/migration/run",
            json={
                "source_file": "/tmp/export.json",
                "mode": "preview",
                "batch_size": 50,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "status": "accepted",
        "message": "Migration job queued",
        "mode": "preview",
        "source_file": "/tmp/export.json",
    }

    documents_collection.find.assert_not_called()
    documents_collection.aggregate.assert_not_called()


def test_preview_uses_injected_database(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    documents = [
        {
            "id": "doc-1",
            "doc_type": "AP_INVOICE",
            "legacy_system": "SQUARE9",
        },
        {
            "id": "doc-2",
            "doc_type": "AP_INVOICE",
            "legacy_system": "SQUARE9",
        },
    ]

    documents_collection.find.return_value.limit.return_value.to_list = (
        AsyncMock(return_value=documents)
    )

    with TestClient(app) as client:
        response = client.get(
            "/migration/preview",
            params={
                "source_filter": "SQUARE9",
                "doc_type_filter": "AP_INVOICE",
                "limit": 25,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "preview": documents,
        "count": 2,
        "filters": {
            "doc_type": "AP_INVOICE",
            "source": "SQUARE9",
        },
    }

    documents_collection.find.assert_called_once_with(
        {
            "is_migrated": True,
            "doc_type": "AP_INVOICE",
            "legacy_system": "SQUARE9",
        },
        {"_id": 0},
    )
    documents_collection.find.return_value.limit.assert_called_once_with(
        25
    )
    documents_collection.find.return_value.limit.return_value.to_list.assert_awaited_once_with(
        25
    )


def test_preview_uses_default_filters(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    with TestClient(app) as client:
        response = client.get("/migration/preview")

    assert response.status_code == 200
    assert response.json() == {
        "preview": [],
        "count": 0,
        "filters": {
            "doc_type": None,
            "source": None,
        },
    }

    documents_collection.find.assert_called_once_with(
        {"is_migrated": True},
        {"_id": 0},
    )
    documents_collection.find.return_value.limit.assert_called_once_with(
        10
    )


def test_preview_rejects_limit_over_100(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/migration/preview",
            params={"limit": 101},
        )

    assert response.status_code == 422
    documents_collection.find.assert_not_called()


def test_stats_uses_injected_database(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    results = [
        {
            "_id": {
                "legacy_system": "SQUARE9",
                "doc_type": "AP_INVOICE",
                "workflow_status": "completed",
            },
            "count": 10,
        },
        {
            "_id": {
                "legacy_system": "SQUARE9",
                "doc_type": "PURCHASE_ORDER",
                "workflow_status": "completed",
            },
            "count": 4,
        },
        {
            "_id": {
                "legacy_system": "ZETADOCS",
                "doc_type": "AP_INVOICE",
                "workflow_status": "review",
            },
            "count": 3,
        },
    ]

    documents_collection.aggregate.return_value.to_list = (
        AsyncMock(return_value=results)
    )

    with TestClient(app) as client:
        response = client.get("/migration/stats")

    assert response.status_code == 200
    assert response.json() == {
        "total_migrated": 17,
        "by_legacy_system": {
            "SQUARE9": 14,
            "ZETADOCS": 3,
        },
        "by_doc_type": {
            "AP_INVOICE": 13,
            "PURCHASE_ORDER": 4,
        },
        "by_workflow_status": {
            "completed": 14,
            "review": 3,
        },
    }

    expected_pipeline = [
        {"$match": {"is_migrated": True}},
        {
            "$group": {
                "_id": {
                    "legacy_system": "$legacy_system",
                    "doc_type": "$doc_type",
                    "workflow_status": "$workflow_status",
                },
                "count": {"$sum": 1},
            }
        },
        {
            "$sort": {
                "_id.legacy_system": 1,
                "_id.doc_type": 1,
            }
        },
    ]

    documents_collection.aggregate.assert_called_once_with(
        expected_pipeline
    )
    documents_collection.aggregate.return_value.to_list.assert_awaited_once_with(
        500
    )


def test_stats_applies_fallback_group_names(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    documents_collection.aggregate.return_value.to_list = (
        AsyncMock(
            return_value=[
                {
                    "_id": {},
                    "count": 2,
                }
            ]
        )
    )

    with TestClient(app) as client:
        response = client.get("/migration/stats")

    assert response.status_code == 200
    assert response.json() == {
        "total_migrated": 2,
        "by_legacy_system": {"UNKNOWN": 2},
        "by_doc_type": {"OTHER": 2},
        "by_workflow_status": {"unknown": 2},
    }


def test_database_dependencies_not_exposed_in_openapi(
    app: FastAPI,
) -> None:
    paths = app.openapi()["paths"]

    operations = [
        paths["/migration/preview"]["get"],
        paths["/migration/stats"]["get"],
    ]

    for operation in operations:
        parameter_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
        }
        assert "database" not in parameter_names


def test_router_source_has_no_legacy_database_dependency() -> None:
    source_path = router_module.__file__

    assert source_path is not None

    with open(source_path, encoding="utf-8") as router_file:
        source = router_file.read()

    assert "get_db" not in source
    assert "from deps import" not in source
    assert "db.hub_documents" not in source
    assert source.count(
        "Depends(get_platform_database)"
    ) == 2
