from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers import email_polling as router_module
from routers.email_polling import router


def make_find_cursor(
    results: list[dict],
) -> MagicMock:
    cursor = MagicMock(name="find_cursor")
    sorted_cursor = MagicMock(name="sorted_cursor")
    limited_cursor = MagicMock(name="limited_cursor")

    cursor.sort.return_value = sorted_cursor
    sorted_cursor.limit.return_value = limited_cursor
    limited_cursor.to_list = AsyncMock(return_value=results)

    return cursor


@pytest.fixture
def mail_poll_runs() -> MagicMock:
    collection = MagicMock(name="mail_poll_runs")
    collection.find.return_value = make_find_cursor([])
    return collection


@pytest.fixture
def hub_settings() -> MagicMock:
    collection = MagicMock(name="hub_settings")
    collection.find_one = AsyncMock(return_value=None)
    return collection


@pytest.fixture
def mail_intake_log() -> MagicMock:
    collection = MagicMock(name="mail_intake_log")
    collection.find.return_value = make_find_cursor([])
    return collection


@pytest.fixture
def database(
    mail_poll_runs: MagicMock,
    hub_settings: MagicMock,
    mail_intake_log: MagicMock,
) -> MagicMock:
    db = MagicMock(name="platform_database")
    db.mail_poll_runs = mail_poll_runs
    db.hub_settings = hub_settings
    db.mail_intake_log = mail_intake_log
    return db


@pytest.fixture
def app(database: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[
        get_platform_database
    ] = lambda: database
    return application


def test_status_uses_injected_database_and_aggregates_runs(
    app: FastAPI,
    mail_poll_runs: MagicMock,
    hub_settings: MagicMock,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    runs = [
        {
            "started_at": "2026-07-25T10:00:00+00:00",
            "messages_detected": 10,
            "attachments_ingested": 6,
            "attachments_skipped_duplicate": 2,
            "attachments_skipped_inline": 1,
            "attachments_failed": 0,
        },
        {
            "started_at": "2026-07-25T09:00:00+00:00",
            "messages_scanned": 4,
            "attachments_processed": 3,
            "attachments_skipped_duplicate": 1,
            "attachments_failed": 1,
        },
    ]

    mail_poll_runs.find.return_value = make_find_cursor(runs)
    hub_settings.find_one.return_value = {
        "last_received_datetime": "2026-07-25T09:55:00+00:00"
    }

    monkeypatch.setattr(
        router_module,
        "EMAIL_POLLING_ENABLED",
        True,
    )
    monkeypatch.setattr(
        router_module,
        "EMAIL_POLLING_INTERVAL_MINUTES",
        5,
    )
    monkeypatch.setattr(
        router_module,
        "EMAIL_POLLING_USER",
        "ap@gamerpackaging.com",
    )
    monkeypatch.setattr(
        router_module,
        "EMAIL_POLLING_LOOKBACK_MINUTES",
        30,
    )
    monkeypatch.setattr(
        router_module,
        "EMAIL_POLLING_MAX_MESSAGES",
        100,
    )
    monkeypatch.setattr(
        router_module,
        "EMAIL_POLLING_MAX_ATTACHMENT_MB",
        25,
    )
    monkeypatch.setattr(
        router_module,
        "EMAIL_CLIENT_ID",
        "configured-client",
    )

    with TestClient(app) as client:
        response = client.get("/email-polling/status")

    assert response.status_code == 200

    body = response.json()

    assert body["config"] == {
        "enabled": True,
        "mode": "passive_tap",
        "interval_minutes": 5,
        "user": "ap@gamerpackaging.com",
        "lookback_minutes": 30,
        "max_messages_per_run": 100,
        "max_attachment_mb": 25,
        "email_app_configured": True,
    }
    assert body["last_24h"] == {
        "runs_count": 2,
        "messages_detected": 14,
        "attachments_ingested": 9,
        "attachments_skipped_duplicate": 3,
        "attachments_skipped_inline": 1,
        "attachments_failed": 1,
    }
    assert body["watermark"] == (
        "2026-07-25T09:55:00+00:00"
    )
    assert body["recent_runs"] == runs
    assert body["health"] == "degraded"
    assert body["permissions_required"] == (
        "Mail.Read (application, read-only)"
    )

    mail_poll_runs.find.assert_called_once()
    find_call = mail_poll_runs.find.call_args

    assert find_call.args[1] == {"_id": 0}
    assert find_call.args[0].keys() == {"started_at"}
    assert "$gte" in find_call.args[0]["started_at"]

    cursor = mail_poll_runs.find.return_value
    cursor.sort.assert_called_once_with("started_at", -1)
    cursor.sort.return_value.limit.assert_called_once_with(10)
    cursor.sort.return_value.limit.return_value.to_list.assert_awaited_once_with(
        10
    )

    hub_settings.find_one.assert_awaited_once_with(
        {"type": "email_poll_watermark"},
        {"_id": 0},
    )


def test_status_returns_healthy_without_failures(
    app: FastAPI,
    mail_poll_runs: MagicMock,
) -> None:
    mail_poll_runs.find.return_value = make_find_cursor(
        [
            {
                "messages_detected": 5,
                "attachments_ingested": 4,
                "attachments_failed": 0,
            }
        ]
    )

    with TestClient(app) as client:
        response = client.get("/email-polling/status")

    assert response.status_code == 200
    assert response.json()["health"] == "healthy"


def test_status_returns_unhealthy_when_failures_match_ingested(
    app: FastAPI,
    mail_poll_runs: MagicMock,
) -> None:
    mail_poll_runs.find.return_value = make_find_cursor(
        [
            {
                "messages_detected": 4,
                "attachments_ingested": 2,
                "attachments_failed": 2,
            }
        ]
    )

    with TestClient(app) as client:
        response = client.get("/email-polling/status")

    assert response.status_code == 200
    assert response.json()["health"] == "unhealthy"


def test_status_limits_recent_runs_to_five(
    app: FastAPI,
    mail_poll_runs: MagicMock,
) -> None:
    runs = [
        {
            "started_at": f"run-{index}",
            "attachments_failed": 0,
        }
        for index in range(8)
    ]
    mail_poll_runs.find.return_value = make_find_cursor(runs)

    with TestClient(app) as client:
        response = client.get("/email-polling/status")

    assert response.status_code == 200
    assert response.json()["last_24h"]["runs_count"] == 8
    assert response.json()["recent_runs"] == runs[:5]


def test_logs_uses_injected_database_with_status_filter(
    app: FastAPI,
    mail_intake_log: MagicMock,
) -> None:
    logs = [
        {
            "message_id": "mail-1",
            "status": "failed",
        },
        {
            "message_id": "mail-2",
            "status": "failed",
        },
    ]
    mail_intake_log.find.return_value = make_find_cursor(logs)

    with TestClient(app) as client:
        response = client.get(
            "/email-polling/logs",
            params={
                "days": 7,
                "status": "failed",
                "limit": 25,
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "logs": logs,
        "count": 2,
    }

    mail_intake_log.find.assert_called_once()
    find_call = mail_intake_log.find.call_args

    query = find_call.args[0]
    projection = find_call.args[1]

    assert query["status"] == "failed"
    assert query["processed_at"].keys() == {"$gte"}
    assert projection == {"_id": 0}

    cursor = mail_intake_log.find.return_value
    cursor.sort.assert_called_once_with("processed_at", -1)
    cursor.sort.return_value.limit.assert_called_once_with(25)
    cursor.sort.return_value.limit.return_value.to_list.assert_awaited_once_with(
        25
    )


def test_logs_uses_defaults_without_status_filter(
    app: FastAPI,
    mail_intake_log: MagicMock,
) -> None:
    with TestClient(app) as client:
        response = client.get("/email-polling/logs")

    assert response.status_code == 200
    assert response.json() == {
        "logs": [],
        "count": 0,
    }

    query = mail_intake_log.find.call_args.args[0]

    assert set(query) == {"processed_at"}

    cursor = mail_intake_log.find.return_value
    cursor.sort.return_value.limit.assert_called_once_with(100)
    cursor.sort.return_value.limit.return_value.to_list.assert_awaited_once_with(
        100
    )


def test_database_dependencies_are_not_exposed_in_openapi(
    app: FastAPI,
) -> None:
    paths = app.openapi()["paths"]

    operations = [
        paths["/email-polling/status"]["get"],
        paths["/email-polling/logs"]["get"],
    ]

    for operation in operations:
        parameter_names = {
            parameter["name"]
            for parameter in operation.get("parameters", [])
        }
        assert "database" not in parameter_names


def test_non_database_endpoints_do_not_gain_dependency(
    app: FastAPI,
) -> None:
    paths = app.openapi()["paths"]

    operations = [
        paths["/email-polling/trigger"]["post"],
        paths["/graph/webhook"]["post"],
        paths["/graph/webhook"]["get"],
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
    assert "db.mail_poll_runs" not in source
    assert "db.hub_settings" not in source
    assert "db.mail_intake_log" not in source

    assert source.count(
        "Depends(get_platform_database)"
    ) == 2
    assert source.count("database.mail_poll_runs") == 1
    assert source.count("database.hub_settings") == 1
    assert source.count("database.mail_intake_log") == 1
