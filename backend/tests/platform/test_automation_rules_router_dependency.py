from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers.automation_rules import router


@pytest.fixture
def documents_collection() -> MagicMock:
    collection = MagicMock(name="hub_documents")
    collection.find_one = AsyncMock()
    return collection


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


def test_evaluate_document_uses_platform_database(
    app: FastAPI,
    database: MagicMock,
    documents_collection: MagicMock,
) -> None:
    document = {
        "id": "doc-123",
        "document_type": "invoice",
        "vendor_no": "V100",
    }
    evaluation = {
        "matched": True,
        "rule_id": "rule-1",
    }

    documents_collection.find_one.return_value = document

    service = MagicMock(name="automation_rules_service")
    service.evaluate = AsyncMock(return_value=evaluation)

    with patch(
        "routers.automation_rules.get_automation_rules_service",
        return_value=service,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/automation-rules/evaluate/doc-123"
            )

    assert response.status_code == 200
    assert response.json() == evaluation

    assert database.hub_documents is documents_collection
    documents_collection.find_one.assert_awaited_once_with(
        {"id": "doc-123"},
        {"_id": 0},
    )
    service.evaluate.assert_awaited_once_with(document)


def test_evaluate_document_returns_default_when_no_rule_matches(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    document = {
        "id": "doc-123",
        "document_type": "invoice",
    }
    documents_collection.find_one.return_value = document

    service = MagicMock(name="automation_rules_service")
    service.evaluate = AsyncMock(return_value=None)

    with patch(
        "routers.automation_rules.get_automation_rules_service",
        return_value=service,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/automation-rules/evaluate/doc-123"
            )

    assert response.status_code == 200
    assert response.json() == {
        "matched": False,
        "message": "No matching rule found",
    }
    service.evaluate.assert_awaited_once_with(document)


def test_evaluate_document_returns_404_when_document_missing(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    documents_collection.find_one.return_value = None

    with patch(
        "routers.automation_rules.get_automation_rules_service"
    ) as get_service:
        with TestClient(app) as client:
            response = client.post(
                "/automation-rules/evaluate/missing"
            )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Document not found",
    }
    documents_collection.find_one.assert_awaited_once_with(
        {"id": "missing"},
        {"_id": 0},
    )
    get_service.assert_not_called()


def test_evaluate_document_returns_503_when_service_unavailable(
    app: FastAPI,
    documents_collection: MagicMock,
) -> None:
    document = {
        "id": "doc-123",
        "document_type": "invoice",
    }
    documents_collection.find_one.return_value = document

    with patch(
        "routers.automation_rules.get_automation_rules_service",
        return_value=None,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/automation-rules/evaluate/doc-123"
            )

    assert response.status_code == 503
    assert response.json() == {
        "detail": "Rules engine not initialized",
    }


def test_database_dependency_is_not_an_http_parameter(
    app: FastAPI,
) -> None:
    operation = app.openapi()["paths"][
        "/automation-rules/evaluate/{doc_id}"
    ]["post"]
    parameters = operation.get("parameters", [])

    assert all(
        parameter["name"] != "database"
        for parameter in parameters
    )
