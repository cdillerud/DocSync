from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers.admin_eod import router


@pytest.fixture
def database() -> Mock:
    return Mock(name="platform_database")


@pytest.fixture
def app(database: Mock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_platform_database] = lambda: database
    return application


def test_run_eod_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    report = {
        "status": "completed",
        "steps": ["close_orders", "archive_documents"],
        "dry_run": True,
    }

    controller = Mock()
    controller.run_close_day = AsyncMock(return_value=report)

    with (
        patch(
            "routers.admin_eod._eod_enabled",
            return_value=True,
        ),
        patch(
            "workflows.batch.eod_controller.EodController",
            return_value=controller,
        ) as controller_class,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/admin/eod/run",
                json={
                    "steps": ["close_orders", "archive_documents"],
                    "dry_run": True,
                },
            )

    assert response.status_code == 200
    assert response.json() == report

    controller_class.assert_called_once_with(database)
    controller.run_close_day.assert_awaited_once_with(
        steps=["close_orders", "archive_documents"],
        dry_run=True,
    )


def test_run_eod_force_allows_disabled_feature(
    app: FastAPI,
    database: Mock,
) -> None:
    controller = Mock()
    controller.run_close_day = AsyncMock(
        return_value={"status": "forced-preview"}
    )

    with (
        patch(
            "routers.admin_eod._eod_enabled",
            return_value=False,
        ),
        patch(
            "workflows.batch.eod_controller.EodController",
            return_value=controller,
        ) as controller_class,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/admin/eod/run",
                json={
                    "force": True,
                    "dry_run": True,
                },
            )

    assert response.status_code == 200
    assert response.json() == {"status": "forced-preview"}
    controller_class.assert_called_once_with(database)
    controller.run_close_day.assert_awaited_once_with(
        steps=None,
        dry_run=True,
    )


def test_run_eod_rejects_disabled_feature_without_force(
    app: FastAPI,
) -> None:
    with patch(
        "routers.admin_eod._eod_enabled",
        return_value=False,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/admin/eod/run",
                json={},
            )

    assert response.status_code == 501
    assert response.json() == {
        "detail": (
            "EOD_ENABLED=false; set EOD_ENABLED=true "
            "(or force=true) to run."
        )
    }


def test_run_eod_converts_value_error_to_400(
    app: FastAPI,
    database: Mock,
) -> None:
    controller = Mock()
    controller.run_close_day = AsyncMock(
        side_effect=ValueError("Unknown EOD step")
    )

    with (
        patch(
            "routers.admin_eod._eod_enabled",
            return_value=True,
        ),
        patch(
            "workflows.batch.eod_controller.EodController",
            return_value=controller,
        ) as controller_class,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/admin/eod/run",
                json={"steps": ["invalid-step"]},
            )

    assert response.status_code == 400
    assert response.json() == {"detail": "Unknown EOD step"}
    controller_class.assert_called_once_with(database)


def test_last_run_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    result = {
        "step": "archive_documents",
        "status": "completed",
    }

    with (
        patch(
            "routers.admin_eod._eod_enabled",
            return_value=True,
        ),
        patch(
            "workflows.batch.eod_controller.get_last_run",
            new=AsyncMock(return_value=result),
        ) as get_last_run,
    ):
        with TestClient(app) as client:
            response = client.get(
                "/admin/eod/last-run",
                params={"step": "archive_documents"},
            )

    assert response.status_code == 200
    assert response.json() == result
    get_last_run.assert_awaited_once_with(
        database,
        step="archive_documents",
    )


def test_last_run_rejects_disabled_feature(
    app: FastAPI,
) -> None:
    with patch(
        "routers.admin_eod._eod_enabled",
        return_value=False,
    ):
        with TestClient(app) as client:
            response = client.get("/admin/eod/last-run")

    assert response.status_code == 501
    assert response.json() == {
        "detail": (
            "EOD_ENABLED=false; set EOD_ENABLED=true "
            "to query run log."
        )
    }


def test_last_run_converts_value_error_to_400(
    app: FastAPI,
    database: Mock,
) -> None:
    with (
        patch(
            "routers.admin_eod._eod_enabled",
            return_value=True,
        ),
        patch(
            "workflows.batch.eod_controller.get_last_run",
            new=AsyncMock(side_effect=ValueError("Invalid step filter")),
        ) as get_last_run,
    ):
        with TestClient(app) as client:
            response = client.get(
                "/admin/eod/last-run",
                params={"step": "invalid-step"},
            )

    assert response.status_code == 400
    assert response.json() == {"detail": "Invalid step filter"}
    get_last_run.assert_awaited_once_with(
        database,
        step="invalid-step",
    )


def test_database_dependency_is_not_an_http_parameter(
    app: FastAPI,
) -> None:
    schema = app.openapi()

    run_operation = schema["paths"]["/admin/eod/run"]["post"]
    run_parameters = run_operation.get("parameters", [])

    last_run_operation = schema["paths"]["/admin/eod/last-run"]["get"]
    last_run_parameters = last_run_operation.get("parameters", [])

    assert all(
        parameter["name"] != "database"
        for parameter in run_parameters
    )
    assert all(
        parameter["name"] != "database"
        for parameter in last_run_parameters
    )
    assert any(
        parameter["name"] == "step"
        for parameter in last_run_parameters
    )
