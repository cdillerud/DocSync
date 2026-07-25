from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers import vendor_intelligence
from routers.vendor_intelligence import router


@pytest.fixture
def profiles_collection() -> MagicMock:
    collection = MagicMock(name="vendor_invoice_profiles")
    collection.update_one = AsyncMock()
    return collection


@pytest.fixture
def database(profiles_collection: MagicMock) -> MagicMock:
    db = MagicMock(name="platform_database")
    db.vendor_invoice_profiles = profiles_collection
    return db


@pytest.fixture
def app(database: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_platform_database] = lambda: database
    return application


def configure_profile_find(
    profiles_collection: MagicMock,
    vendors: list[dict],
) -> MagicMock:
    cursor = MagicMock(name="vendor_profile_cursor")
    cursor.to_list = AsyncMock(return_value=vendors)
    profiles_collection.find.return_value = cursor
    return cursor


def test_enable_vendor_bypass_uses_injected_database(
    app: FastAPI,
    database: MagicMock,
    profiles_collection: MagicMock,
) -> None:
    update_result = MagicMock()
    update_result.matched_count = 1
    profiles_collection.update_one.return_value = update_result

    with TestClient(app) as client:
        response = client.patch(
            "/vendor-intelligence/profiles/V-100/bypass",
            params={
                "enabled": "true",
                "reason": "Poor extraction quality",
            },
        )

    assert response.status_code == 200
    payload = response.json()

    assert payload["vendor_no"] == "V-100"
    assert payload["auto_process_bypass"] is True
    assert payload["reason"] == "Poor extraction quality"
    assert isinstance(payload["updated_at"], str)

    assert database.vendor_invoice_profiles is profiles_collection

    profiles_collection.update_one.assert_awaited_once()
    update_filter, update_document = (
        profiles_collection.update_one.await_args.args[:2]
    )
    update_options = profiles_collection.update_one.await_args.kwargs

    assert update_filter == {"vendor_no": "V-100"}
    assert update_document["$set"] == {
        "auto_process_bypass": True,
        "bypass_reason": "Poor extraction quality",
        "bypass_updated_at": payload["updated_at"],
    }
    assert update_options == {"upsert": False}


def test_enable_vendor_bypass_uses_default_reason(
    app: FastAPI,
    profiles_collection: MagicMock,
) -> None:
    update_result = MagicMock()
    update_result.matched_count = 1
    profiles_collection.update_one.return_value = update_result

    with TestClient(app) as client:
        response = client.patch(
            "/vendor-intelligence/profiles/V-200/bypass"
        )

    assert response.status_code == 200
    payload = response.json()

    assert payload["auto_process_bypass"] is True
    assert payload["reason"] == ""

    update_document = (
        profiles_collection.update_one.await_args.args[1]
    )
    assert (
        update_document["$set"]["bypass_reason"]
        == "Vendor flagged for manual review"
    )


def test_disable_vendor_bypass_clears_default_reason(
    app: FastAPI,
    profiles_collection: MagicMock,
) -> None:
    update_result = MagicMock()
    update_result.matched_count = 1
    profiles_collection.update_one.return_value = update_result

    with TestClient(app) as client:
        response = client.patch(
            "/vendor-intelligence/profiles/V-300/bypass",
            params={"enabled": "false"},
        )

    assert response.status_code == 200
    payload = response.json()

    assert payload["auto_process_bypass"] is False
    assert payload["reason"] == ""

    update_document = (
        profiles_collection.update_one.await_args.args[1]
    )
    assert update_document["$set"]["auto_process_bypass"] is False
    assert update_document["$set"]["bypass_reason"] == ""


def test_vendor_bypass_returns_404_when_profile_not_found(
    app: FastAPI,
    profiles_collection: MagicMock,
) -> None:
    update_result = MagicMock()
    update_result.matched_count = 0
    profiles_collection.update_one.return_value = update_result

    with TestClient(app) as client:
        response = client.patch(
            "/vendor-intelligence/profiles/MISSING/bypass"
        )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Vendor profile not found: MISSING"
    }


def test_bypassed_vendors_uses_injected_database(
    app: FastAPI,
    database: MagicMock,
    profiles_collection: MagicMock,
) -> None:
    vendors = [
        {
            "vendor_no": "V-100",
            "vendor_name": "Vendor One",
            "bypass_reason": "Poor extraction quality",
            "invoice_count": 42,
        },
        {
            "vendor_no": "V-200",
            "vendor_name": "Vendor Two",
            "bypass_reason": "Manual review required",
            "invoice_count": 12,
        },
    ]
    cursor = configure_profile_find(profiles_collection, vendors)

    with TestClient(app) as client:
        response = client.get(
            "/vendor-intelligence/bypassed-vendors"
        )

    assert response.status_code == 200
    assert response.json() == {
        "bypassed_vendors": vendors,
        "count": 2,
    }

    assert database.vendor_invoice_profiles is profiles_collection

    find_filter, projection = profiles_collection.find.call_args.args
    assert find_filter == {"auto_process_bypass": True}
    assert projection == {
        "_id": 0,
        "vendor_no": 1,
        "vendor_name": 1,
        "bypass_reason": 1,
        "bypass_updated_at": 1,
        "invoice_count": 1,
    }
    cursor.to_list.assert_awaited_once_with(100)


def test_bypassed_vendors_handles_empty_result(
    app: FastAPI,
    profiles_collection: MagicMock,
) -> None:
    configure_profile_find(profiles_collection, [])

    with TestClient(app) as client:
        response = client.get(
            "/vendor-intelligence/bypassed-vendors"
        )

    assert response.status_code == 200
    assert response.json() == {
        "bypassed_vendors": [],
        "count": 0,
    }


@pytest.mark.parametrize(
    ("path", "method"),
    [
        (
            "/vendor-intelligence/profiles/{vendor_no}/bypass",
            "patch",
        ),
        (
            "/vendor-intelligence/bypassed-vendors",
            "get",
        ),
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


def test_router_source_has_no_legacy_database_dependency() -> None:
    source_path = vendor_intelligence.__file__

    assert source_path is not None

    with open(source_path, encoding="utf-8") as router_file:
        source = router_file.read()

    assert "get_db" not in source
    assert "from deps import" not in source
