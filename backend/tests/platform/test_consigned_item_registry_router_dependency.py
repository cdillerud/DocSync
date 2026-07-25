from __future__ import annotations

from unittest.mock import AsyncMock, Mock, patch

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers.consigned_item_registry import router
from services.auth_deps import get_current_user


@pytest.fixture
def database() -> Mock:
    return Mock(name="platform_database")


@pytest.fixture
def current_user() -> dict[str, str]:
    return {
        "email": "owner@example.com",
        "username": "owner",
    }


@pytest.fixture
def app(
    database: Mock,
    current_user: dict[str, str],
) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_platform_database] = lambda: database
    application.dependency_overrides[get_current_user] = lambda: current_user
    return application


def test_list_consigned_items_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    items = [
        {
            "item_no": "CONS-100",
            "vendor_no": "V100",
            "physical_location": "MAIN",
            "state": "consigned_in",
        }
    ]

    with patch(
        "routers.consigned_item_registry.ownership.list_consigned_items",
        new=AsyncMock(return_value=items),
    ) as list_items:
        with TestClient(app) as client:
            response = client.get(
                "/consigned-items",
                params={
                    "vendor_no": "V100",
                    "state": "consigned_in",
                    "limit": 50,
                },
            )

    assert response.status_code == 200
    assert response.json() == {
        "total": 1,
        "items": items,
    }
    list_items.assert_awaited_once_with(
        database,
        vendor_no="V100",
        state="consigned_in",
        limit=50,
    )


def test_get_consigned_item_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    item = {
        "item_no": "CONS-100",
        "vendor_no": "V100",
        "physical_location": "MAIN",
        "state": "consigned_in",
    }

    with patch(
        "routers.consigned_item_registry.ownership.get_consigned_item",
        new=AsyncMock(return_value=item),
    ) as get_item:
        with TestClient(app) as client:
            response = client.get("/consigned-items/CONS-100")

    assert response.status_code == 200
    assert response.json() == item
    get_item.assert_awaited_once_with(database, "CONS-100")


def test_get_consigned_item_returns_404_when_missing(
    app: FastAPI,
    database: Mock,
) -> None:
    with patch(
        "routers.consigned_item_registry.ownership.get_consigned_item",
        new=AsyncMock(return_value=None),
    ) as get_item:
        with TestClient(app) as client:
            response = client.get("/consigned-items/MISSING")

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Consigned item not found",
    }
    get_item.assert_awaited_once_with(database, "MISSING")


def test_upsert_consigned_item_uses_platform_database_and_user_email(
    app: FastAPI,
    database: Mock,
) -> None:
    payload = {
        "item_no": "CONS-200",
        "vendor_no": "V200",
        "physical_location": "MAIN",
        "notes": "Focused dependency test",
    }
    result = {
        **payload,
        "state": "consigned_in",
        "created_by": "owner@example.com",
    }

    with patch(
        "routers.consigned_item_registry.ownership.upsert_consigned_item",
        new=AsyncMock(return_value=result),
    ) as upsert_item:
        with TestClient(app) as client:
            response = client.post(
                "/consigned-items",
                json=payload,
            )

    assert response.status_code == 200
    assert response.json() == result

    args = upsert_item.await_args
    assert args.args[0] is database
    assert args.args[1].model_dump(
        by_alias=True,
        exclude_unset=True,
    ) == payload
    assert args.kwargs == {
        "actor": "owner@example.com",
    }


def test_transition_consigned_item_uses_platform_database(
    app: FastAPI,
    database: Mock,
) -> None:
    body = {
        "new_state": "consumed",
        "actor_email": "items@gamerpackaging.com",
        "evidence_id": "doc-123",
    }
    result = {
        "item_no": "CONS-100",
        "state": "consumed",
        "transition_evidence_id": "doc-123",
    }

    with (
        patch(
            "routers.consigned_item_registry."
            "ownership.require_consignment_actor"
        ) as require_actor,
        patch(
            "routers.consigned_item_registry."
            "ownership.transition_consigned_item",
            new=AsyncMock(return_value=result),
        ) as transition_item,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/consigned-items/CONS-100/transition",
                json=body,
            )

    assert response.status_code == 200
    assert response.json() == result

    require_actor.assert_called_once_with(
        "items@gamerpackaging.com"
    )
    transition_item.assert_awaited_once_with(
        database,
        item_no="CONS-100",
        new_state="consumed",
        actor="items@gamerpackaging.com",
        evidence_id="doc-123",
    )


def test_transition_converts_permission_error_to_403(
    app: FastAPI,
    database: Mock,
) -> None:
    body = {
        "new_state": "consumed",
        "actor_email": "items@gamerpackaging.com",
        "evidence_id": "doc-123",
    }

    with (
        patch(
            "routers.consigned_item_registry."
            "ownership.require_consignment_actor"
        ),
        patch(
            "routers.consigned_item_registry."
            "ownership.transition_consigned_item",
            new=AsyncMock(
                side_effect=PermissionError("Transition forbidden")
            ),
        ) as transition_item,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/consigned-items/CONS-100/transition",
                json=body,
            )

    assert response.status_code == 403
    assert response.json() == {
        "detail": "Transition forbidden",
    }
    assert transition_item.await_args.args[0] is database


def test_transition_converts_not_found_to_404(
    app: FastAPI,
    database: Mock,
) -> None:
    body = {
        "new_state": "returned",
        "actor_email": "items@gamerpackaging.com",
        "evidence_id": "doc-404",
    }

    with (
        patch(
            "routers.consigned_item_registry."
            "ownership.require_consignment_actor"
        ),
        patch(
            "routers.consigned_item_registry."
            "ownership.transition_consigned_item",
            new=AsyncMock(
                side_effect=ValueError(
                    "Consigned item CONS-404 not found"
                )
            ),
        ) as transition_item,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/consigned-items/CONS-404/transition",
                json=body,
            )

    assert response.status_code == 404
    assert response.json() == {
        "detail": "Consigned item CONS-404 not found",
    }
    assert transition_item.await_args.args[0] is database


def test_transition_converts_other_value_error_to_400(
    app: FastAPI,
    database: Mock,
) -> None:
    body = {
        "new_state": "returned",
        "actor_email": "items@gamerpackaging.com",
        "evidence_id": "doc-400",
    }

    with (
        patch(
            "routers.consigned_item_registry."
            "ownership.require_consignment_actor"
        ),
        patch(
            "routers.consigned_item_registry."
            "ownership.transition_consigned_item",
            new=AsyncMock(
                side_effect=ValueError("Illegal state transition")
            ),
        ) as transition_item,
    ):
        with TestClient(app) as client:
            response = client.post(
                "/consigned-items/CONS-100/transition",
                json=body,
            )

    assert response.status_code == 400
    assert response.json() == {
        "detail": "Illegal state transition",
    }
    assert transition_item.await_args.args[0] is database


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/consigned-items", "get"),
        ("/consigned-items/{item_no}", "get"),
        ("/consigned-items", "post"),
        ("/consigned-items/{item_no}/transition", "post"),
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
