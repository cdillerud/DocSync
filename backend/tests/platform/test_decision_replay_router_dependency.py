from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from bson import ObjectId
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers.decision_replay import router


@pytest.fixture
def database() -> Mock:
    database = Mock(name="platform_database")
    database.hub_documents = Mock(name="hub_documents")
    database.hub_documents.find_one = AsyncMock()
    return database


@pytest.fixture
def app(database: Mock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_platform_database] = lambda: database
    return application


def test_decision_replay_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    document = {
        "id": "doc-123",
        "document_type": "invoice",
    }
    replay = {
        "document_id": "doc-123",
        "decisions": [],
    }

    database.hub_documents.find_one.return_value = document

    with (
        patch(
            "routers.decision_replay._verify_token",
            return_value="user@example.com",
        ) as verify_token,
        patch(
            "routers.decision_replay.build_ap_decision_replay",
            new=AsyncMock(return_value=replay),
        ) as build_replay,
    ):
        with TestClient(app) as client:
            response = client.get(
                "/documents/doc-123/decision-replay",
                headers={"Authorization": "Bearer valid-token"},
            )

    assert response.status_code == 200
    assert response.json() == replay

    verify_token.assert_called_once_with("Bearer valid-token")
    database.hub_documents.find_one.assert_awaited_once_with(
        {"id": "doc-123"},
        {"_id": 0},
    )
    build_replay.assert_awaited_once_with(database, document)


def test_decision_replay_falls_back_to_object_id(
    app: FastAPI,
    database: Mock,
) -> None:
    document_id = "507f1f77bcf86cd799439011"
    document = {
        "id": "legacy-document",
        "document_type": "invoice",
    }

    database.hub_documents.find_one.side_effect = [
        None,
        document,
    ]

    with (
        patch(
            "routers.decision_replay._verify_token",
            return_value="user@example.com",
        ),
        patch(
            "routers.decision_replay.build_ap_decision_replay",
            new=AsyncMock(return_value={"found": True}),
        ) as build_replay,
    ):
        with TestClient(app) as client:
            response = client.get(
                f"/documents/{document_id}/decision-replay",
                headers={"Authorization": "Bearer valid-token"},
            )

    assert response.status_code == 200
    assert response.json() == {"found": True}

    assert database.hub_documents.find_one.await_args_list[0].args == (
        {"id": document_id},
        {"_id": 0},
    )
    assert database.hub_documents.find_one.await_args_list[1].args == (
        {"_id": ObjectId(document_id)},
        {"_id": 0},
    )
    build_replay.assert_awaited_once_with(database, document)


def test_decision_replay_returns_404_when_document_is_missing(
    app: FastAPI,
    database: Mock,
) -> None:
    database.hub_documents.find_one.return_value = None

    with (
        patch(
            "routers.decision_replay._verify_token",
            return_value="user@example.com",
        ),
        patch(
            "routers.decision_replay.build_ap_decision_replay",
            new=AsyncMock(),
        ) as build_replay,
    ):
        with TestClient(app) as client:
            response = client.get(
                "/documents/not-an-object-id/decision-replay",
                headers={"Authorization": "Bearer valid-token"},
            )

    assert response.status_code == 404
    assert response.json() == {"detail": "Document not found"}

    database.hub_documents.find_one.assert_awaited_once_with(
        {"id": "not-an-object-id"},
        {"_id": 0},
    )
    build_replay.assert_not_awaited()


def test_authentication_failure_prevents_database_access(
    app: FastAPI,
    database: Mock,
) -> None:
    with TestClient(app) as client:
        response = client.get(
            "/documents/doc-123/decision-replay",
        )

    assert response.status_code == 401
    assert response.json() == {
        "detail": "Missing or invalid Authorization header",
    }
    database.hub_documents.find_one.assert_not_awaited()


def test_database_dependency_is_not_an_http_parameter(
    app: FastAPI,
) -> None:
    operation = app.openapi()["paths"][
        "/documents/{document_id}/decision-replay"
    ]["get"]

    parameters = operation.get("parameters", [])

    assert all(item["name"] != "database" for item in parameters)
    assert any(item["name"] == "document_id" for item in parameters)
    assert any(item["name"] == "authorization" for item in parameters)
