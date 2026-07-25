from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers import automation_intelligence as router_module
from routers.automation_intelligence import router
from services import automation_intelligence_service as service_module


@pytest.fixture
def collection():
    value = MagicMock()
    value.find_one = AsyncMock()
    value.update_one = AsyncMock()
    return value


@pytest.fixture
def app(collection):
    database = MagicMock()
    database.hub_documents = collection

    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[
        get_platform_database
    ] = lambda: database
    return application


def test_decision_explanation_returns_stored(app, collection):
    stored = {"decision": "manual_review"}
    collection.find_one.return_value = {
        "id": "doc-1",
        "decision_explanation": stored,
    }

    with TestClient(app) as client:
        response = client.get(
            "/documents/doc-1/decision-explanation"
        )

    assert response.status_code == 200
    assert response.json() == stored
    collection.update_one.assert_not_awaited()


def test_decision_explanation_computes_and_saves(
    app,
    collection,
    monkeypatch,
):
    document = {"id": "doc-2"}
    result = {"decision": "approved"}

    collection.find_one.return_value = document

    builder = MagicMock(return_value=result)
    monkeypatch.setattr(
        service_module,
        "build_decision_explanation",
        builder,
    )

    with TestClient(app) as client:
        response = client.get(
            "/documents/doc-2/decision-explanation"
        )

    assert response.status_code == 200
    assert response.json() == result
    builder.assert_called_once_with(document)
    collection.update_one.assert_awaited_once_with(
        {"id": "doc-2"},
        {"$set": {"decision_explanation": result}},
    )


def test_automation_confidence_computes_and_saves(
    app,
    collection,
    monkeypatch,
):
    document = {"id": "doc-3"}
    result = {"score": 0.91}

    collection.find_one.return_value = document

    calculator = MagicMock(return_value=result)
    monkeypatch.setattr(
        service_module,
        "compute_automation_confidence",
        calculator,
    )

    with TestClient(app) as client:
        response = client.get(
            "/documents/doc-3/automation-confidence"
        )

    assert response.status_code == 200
    assert response.json() == result
    calculator.assert_called_once_with(document)
    collection.update_one.assert_awaited_once_with(
        {"id": "doc-3"},
        {"$set": {"automation_confidence": result}},
    )


def test_review_assist_returns_suggestions(
    app,
    collection,
    monkeypatch,
):
    document = {"id": "doc-4"}
    suggestions = [{"action": "set_field"}]

    collection.find_one.return_value = document

    generator = MagicMock(return_value=suggestions)
    monkeypatch.setattr(
        service_module,
        "generate_review_suggestions",
        generator,
    )

    with TestClient(app) as client:
        response = client.post(
            "/documents/doc-4/review-assist"
        )

    assert response.status_code == 200
    assert response.json() == {
        "doc_id": "doc-4",
        "suggested_actions": suggestions,
    }
    generator.assert_called_once_with(document)


@pytest.mark.parametrize(
    ("method", "url"),
    [
        ("get", "/documents/missing/decision-explanation"),
        ("get", "/documents/missing/automation-confidence"),
        ("post", "/documents/missing/review-assist"),
    ],
)
def test_document_endpoints_return_404(
    app,
    collection,
    method,
    url,
):
    collection.find_one.return_value = None

    with TestClient(app) as client:
        response = getattr(client, method)(url)

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Document not found"
    }


def test_database_dependency_not_exposed_in_openapi(app):
    paths = app.openapi()["paths"]

    operations = [
        paths[
            "/documents/{doc_id}/decision-explanation"
        ]["get"],
        paths[
            "/documents/{doc_id}/automation-confidence"
        ]["get"],
        paths[
            "/documents/{doc_id}/review-assist"
        ]["post"],
    ]

    for operation in operations:
        parameter_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
        }
        assert "database" not in parameter_names


def test_router_has_no_legacy_database_access():
    with open(
        router_module.__file__,
        encoding="utf-8",
    ) as router_file:
        source = router_file.read()

    assert "get_db" not in source
    assert "from deps import" not in source
    assert "db.hub_documents" not in source
    assert source.count(
        "Depends(get_platform_database)"
    ) == 3
