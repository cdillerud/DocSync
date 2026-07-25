from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers.workflow_observer import router


@pytest.fixture
def database() -> Mock:
    return Mock(name="platform_database")


@pytest.fixture
def app(database: Mock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_platform_database] = lambda: database
    return application


def test_observer_summary_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    result = {
        "days": 14,
        "total": 8,
    }

    with patch(
        "routers.workflow_observer.get_observer_summary",
        new=AsyncMock(return_value=result),
    ) as service:
        with TestClient(app) as client:
            response = client.get(
                "/admin/workflow-observer/summary",
                params={"days": 14},
            )

    assert response.status_code == 200
    assert response.json() == result
    service.assert_awaited_once_with(database, days=14)


def test_observer_recent_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    rows = [
        {"caller_func": "process_document", "doc_type": "invoice"},
        {"caller_func": "process_document", "doc_type": "purchase_order"},
    ]

    with patch(
        "routers.workflow_observer.list_recent_observations",
        new=AsyncMock(return_value=rows),
    ) as service:
        with TestClient(app) as client:
            response = client.get(
                "/admin/workflow-observer/recent",
                params={
                    "limit": 25,
                    "caller_func": "process_document",
                },
            )

    assert response.status_code == 200
    assert response.json() == {
        "total": 2,
        "observations": rows,
    }
    service.assert_awaited_once_with(
        database,
        limit=25,
        caller_func="process_document",
    )


def test_phase_b_readiness_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    report = {
        "verdict": "ready",
        "markdown": "# Phase B\nReady",
    }

    with patch(
        "routers.workflow_observer.build_phase_b_readiness_report",
        new=AsyncMock(return_value=report),
    ) as service:
        with TestClient(app) as client:
            response = client.get(
                "/admin/workflow-observer/phase-b-readiness",
                params={
                    "days": 30,
                    "min_coverage": 10,
                    "format": "json",
                },
            )

    assert response.status_code == 200
    assert response.json() == report
    service.assert_awaited_once_with(
        database,
        days=30,
        min_coverage=10,
    )


def test_phase_b_readiness_markdown_response(
    app: FastAPI,
) -> None:
    report = {
        "verdict": "ready",
        "markdown": "# Phase B\nReady",
    }

    with patch(
        "routers.workflow_observer.build_phase_b_readiness_report",
        new=AsyncMock(return_value=report),
    ):
        with TestClient(app) as client:
            response = client.get(
                "/admin/workflow-observer/phase-b-readiness",
                params={"format": "markdown"},
            )

    assert response.status_code == 200
    assert response.text == "# Phase B\nReady"
    assert response.headers["content-type"].startswith("text/markdown")


def test_database_dependency_is_not_an_http_parameter(
    app: FastAPI,
) -> None:
    schema = app.openapi()

    paths = [
        (
            "/admin/workflow-observer/summary",
            "get",
        ),
        (
            "/admin/workflow-observer/recent",
            "get",
        ),
        (
            "/admin/workflow-observer/phase-b-readiness",
            "get",
        ),
    ]

    for path, method in paths:
        parameters = schema["paths"][path][method].get("parameters", [])
        assert all(item["name"] != "database" for item in parameters)
