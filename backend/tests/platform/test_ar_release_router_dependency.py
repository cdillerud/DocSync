from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers.ar_release import router


@pytest.fixture
def documents_collection() -> MagicMock:
    return MagicMock(name="hub_documents")


@pytest.fixture
def database(documents_collection: MagicMock) -> MagicMock:
    db = MagicMock(name="platform_database")
    db.hub_documents = documents_collection
    return db


@pytest.fixture
def app(database: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_platform_database] = lambda: database
    return application


def test_metrics_uses_platform_database(
    app: FastAPI,
    database: MagicMock,
) -> None:
    metrics = {
        "held": 4,
        "released": 12,
        "override": 2,
    }

    with patch(
        "routers.ar_release.get_ar_release_metrics",
        new=AsyncMock(return_value=metrics),
    ) as get_metrics:
        with TestClient(app) as client:
            response = client.get("/ar-release/metrics")

    assert response.status_code == 200
    assert response.json() == metrics
    get_metrics.assert_awaited_once_with(database)


def test_evaluate_uses_platform_database(
    app: FastAPI,
    database: MagicMock,
) -> None:
    result = {
        "document_id": "doc-123",
        "status": "held",
    }

    with patch(
        "routers.ar_release.evaluate_and_store",
        new=AsyncMock(return_value=result),
    ) as evaluate:
        with TestClient(app) as client:
            response = client.post(
                "/ar-release/evaluate/doc-123"
            )

    assert response.status_code == 200
    assert response.json() == result
    evaluate.assert_awaited_once_with("doc-123", database)


def test_evaluate_converts_service_error_to_404(
    app: FastAPI,
    database: MagicMock,
) -> None:
    with patch(
        "routers.ar_release.evaluate_and_store",
        new=AsyncMock(
            return_value={"error": "Document not found"}
        ),
    ) as evaluate:
        with TestClient(app) as client:
            response = client.post(
                "/ar-release/evaluate/missing"
            )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Document not found",
    }
    evaluate.assert_awaited_once_with("missing", database)


def test_override_uses_platform_database(
    app: FastAPI,
    database: MagicMock,
) -> None:
    result = {
        "document_id": "doc-123",
        "status": "override",
        "approved_by": "manager@example.com",
    }

    with patch(
        "routers.ar_release.override_gate",
        new=AsyncMock(return_value=result),
    ) as override:
        with TestClient(app) as client:
            response = client.post(
                "/ar-release/override/doc-123",
                json={
                    "approved_by": "manager@example.com",
                    "notes": "Approved manually",
                },
            )

    assert response.status_code == 200
    assert response.json() == result
    override.assert_awaited_once_with(
        "doc-123",
        database,
        "manager@example.com",
        "Approved manually",
    )


def test_override_converts_service_error_to_404(
    app: FastAPI,
    database: MagicMock,
) -> None:
    with patch(
        "routers.ar_release.override_gate",
        new=AsyncMock(
            return_value={"error": "Document not found"}
        ),
    ) as override:
        with TestClient(app) as client:
            response = client.post(
                "/ar-release/override/missing",
                json={
                    "approved_by": "manager@example.com",
                    "notes": "",
                },
            )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Document not found",
    }
    override.assert_awaited_once_with(
        "missing",
        database,
        "manager@example.com",
        "",
    )


def test_held_queue_uses_platform_database_and_status_filter(
    app: FastAPI,
    database: MagicMock,
    documents_collection: MagicMock,
) -> None:
    documents = [
        {
            "id": "doc-123",
            "file_name": "invoice.pdf",
            "ar_release_gate": {"status": "held"},
        }
    ]

    cursor = MagicMock(name="queue_cursor")
    sorted_cursor = MagicMock(name="sorted_cursor")
    limited_cursor = MagicMock(name="limited_cursor")
    limited_cursor.to_list = AsyncMock(return_value=documents)

    documents_collection.find.return_value = cursor
    cursor.sort.return_value = sorted_cursor
    sorted_cursor.limit.return_value = limited_cursor

    with TestClient(app) as client:
        response = client.get(
            "/ar-release/queue",
            params={
                "status": "held",
                "limit": 25,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "total": 1,
        "status_filter": "held",
        "documents": documents,
    }

    assert database.hub_documents is documents_collection

    find_filter, projection = documents_collection.find.call_args.args
    assert find_filter == {
        "ar_release_gate": {"$exists": True},
        "ar_release_gate.status": "held",
    }
    assert projection["_id"] == 0
    assert projection["id"] == 1
    assert projection["ar_release_gate"] == 1

    cursor.sort.assert_called_once_with("created_utc", -1)
    sorted_cursor.limit.assert_called_once_with(25)
    limited_cursor.to_list.assert_awaited_once_with(25)


def test_held_queue_all_status_omits_status_filter(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    cursor = MagicMock(name="queue_cursor")
    sorted_cursor = MagicMock(name="sorted_cursor")
    limited_cursor = MagicMock(name="limited_cursor")
    limited_cursor.to_list = AsyncMock(return_value=[])

    documents_collection.find.return_value = cursor
    cursor.sort.return_value = sorted_cursor
    sorted_cursor.limit.return_value = limited_cursor

    with TestClient(app) as client:
        response = client.get(
            "/ar-release/queue",
            params={"status": "all"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "total": 0,
        "status_filter": "all",
        "documents": [],
    }

    find_filter = documents_collection.find.call_args.args[0]
    assert find_filter == {
        "ar_release_gate": {"$exists": True},
    }


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/ar-release/metrics", "get"),
        ("/ar-release/evaluate/{document_id}", "post"),
        ("/ar-release/override/{document_id}", "post"),
        ("/ar-release/queue", "get"),
    ],
)
def test_database_dependency_is_not_an_http_parameter(
    app: FastAPI,
    path: str,
    method: str,
) -> None:
    operation = app.openapi()["paths"][path][method]
    parameters = operation.get("parameters", [])

    assert all(
        parameter["name"] != "database"
        for parameter in parameters
    )
