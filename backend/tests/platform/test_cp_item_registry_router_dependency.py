from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers.cp_item_registry import router
from services.auth_deps import get_current_user


@pytest.fixture
def database() -> Mock:
    return Mock(name="platform_database")


@pytest.fixture
def app(database: Mock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_platform_database] = lambda: database
    application.dependency_overrides[get_current_user] = lambda: {
        "email": "owner@example.com",
        "username": "owner",
    }
    return application


def test_list_cp_items_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    items = [
        {"item_no": "CP-100", "status": "active"},
        {"item_no": "CP-101", "status": "active"},
    ]

    with patch(
        "routers.cp_item_registry.ownership.list_all_cp_items",
        new=AsyncMock(return_value=items),
    ) as list_items:
        with TestClient(app) as client:
            response = client.get(
                "/cp-items",
                params={
                    "customer_no": "C100",
                    "status": "active",
                    "limit": 25,
                },
            )

    assert response.status_code == 200
    assert response.json() == {
        "total": 2,
        "items": items,
    }
    list_items.assert_awaited_once_with(
        database,
        customer_no="C100",
        status="active",
        limit=25,
    )


def test_get_cp_item_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    item = {
        "item_no": "CP-100",
        "customer_no": "C100",
        "status": "active",
    }

    with patch(
        "routers.cp_item_registry.ownership.get_cp_item",
        new=AsyncMock(return_value=item),
    ) as get_item:
        with TestClient(app) as client:
            response = client.get("/cp-items/CP-100")

    assert response.status_code == 200
    assert response.json() == item
    get_item.assert_awaited_once_with(database, "CP-100")


def test_get_cp_item_returns_404_when_missing(
    app: FastAPI,
    database: Mock,
) -> None:
    with patch(
        "routers.cp_item_registry.ownership.get_cp_item",
        new=AsyncMock(return_value=None),
    ) as get_item:
        with TestClient(app) as client:
            response = client.get("/cp-items/missing")

    assert response.status_code == 404
    assert response.json() == {"detail": "CP item not found"}
    get_item.assert_awaited_once_with(database, "missing")


def test_upsert_cp_item_uses_platform_database_and_user_email(
    app: FastAPI,
    database: Mock,
) -> None:
    result = {
        "item_no": "CP-200",
        "customer_no": "C200",
        "status": "active",
    }

    payload = {
        "item_no": "CP-200",
        "customer_no": "C200",
        "base_item_no": "BASE-200",
        "canonical_location": "MAIN",
    }

    with patch(
        "routers.cp_item_registry.ownership.upsert_cp_item",
        new=AsyncMock(return_value=result),
    ) as upsert_item:
        with TestClient(app) as client:
            response = client.post(
                "/cp-items",
                json=payload,
            )

    assert response.status_code == 200
    assert response.json() == result

    args = upsert_item.await_args
    assert args.args[0] is database

    submitted_payload = args.args[1].model_dump(
        by_alias=True,
        exclude_unset=True,
    )
    assert submitted_payload == payload

    assert args.kwargs == {"actor": "owner@example.com"}


def test_retire_cp_item_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    result = {
        "item_no": "CP-300",
        "status": "retired",
    }

    with (
        patch(
            "routers.cp_item_registry.ownership.require_retirement_actor",
        ) as require_actor,
        patch(
            "routers.cp_item_registry.ownership.retire_cp_item",
            new=AsyncMock(return_value=result),
        ) as retire_item,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/cp-items/CP-300/retire",
                json={"actor_email": "retirement@example.com"},
            )

    assert response.status_code == 200
    assert response.json() == result
    require_actor.assert_called_once_with("retirement@example.com")
    retire_item.assert_awaited_once_with(
        database,
        "CP-300",
        actor="retirement@example.com",
    )


def test_retire_cp_item_converts_value_error_to_404(
    app: FastAPI,
    database: Mock,
) -> None:
    with (
        patch(
            "routers.cp_item_registry.ownership.require_retirement_actor",
        ),
        patch(
            "routers.cp_item_registry.ownership.retire_cp_item",
            new=AsyncMock(side_effect=ValueError("CP item not found")),
        ) as retire_item,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/cp-items/missing/retire",
                json={"actor_email": "retirement@example.com"},
            )

    assert response.status_code == 404
    assert response.json() == {"detail": "CP item not found"}
    retire_item.assert_awaited_once_with(
        database,
        "missing",
        actor="retirement@example.com",
    )


def test_retire_cp_item_converts_permission_error_to_403(
    app: FastAPI,
    database: Mock,
) -> None:
    with (
        patch(
            "routers.cp_item_registry.ownership.require_retirement_actor",
        ),
        patch(
            "routers.cp_item_registry.ownership.retire_cp_item",
            new=AsyncMock(
                side_effect=PermissionError("Retirement not permitted")
            ),
        ) as retire_item,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/cp-items/CP-300/retire",
                json={"actor_email": "retirement@example.com"},
            )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Retirement not permitted",
    }
    retire_item.assert_awaited_once_with(
        database,
        "CP-300",
        actor="retirement@example.com",
    )


def test_database_dependency_is_not_an_http_parameter(
    app: FastAPI,
) -> None:
    schema = app.openapi()

    operations = [
        schema["paths"]["/cp-items"]["get"],
        schema["paths"]["/cp-items"]["post"],
        schema["paths"]["/cp-items/{item_no}"]["get"],
        schema["paths"]["/cp-items/{item_no}/retire"]["post"],
    ]

    for operation in operations:
        parameters = operation.get("parameters", [])
        assert all(
            parameter["name"] != "database"
            for parameter in parameters
        )
