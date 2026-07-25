from __future__ import annotations

from unittest.mock import AsyncMock, MagicMock, Mock

import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient

from hub_platform.bootstrap import get_platform_database
from routers.inventory_items import COLL, router


@pytest.fixture
def collection() -> MagicMock:
    return MagicMock(name="inventory_item_settings_collection")


@pytest.fixture
def database(collection: MagicMock) -> MagicMock:
    db = MagicMock(name="platform_database")
    db.__getitem__.return_value = collection
    return db


@pytest.fixture
def app(database: MagicMock) -> FastAPI:
    application = FastAPI()
    application.include_router(router)
    application.dependency_overrides[get_platform_database] = lambda: database
    return application


def test_list_settings_uses_platform_database(
    app: FastAPI,
    database: MagicMock,
    collection: MagicMock,
) -> None:
    documents = [
        {
            "customer_id": "workspace-1",
            "item": "ITEM-100",
            "reorder_threshold": 10.0,
            "safety_buffer": 3.0,
            "notes": "",
        }
    ]

    cursor = MagicMock(name="cursor")
    sorted_cursor = MagicMock(name="sorted_cursor")
    sorted_cursor.to_list = AsyncMock(return_value=documents)

    cursor.sort.return_value = sorted_cursor
    collection.find.return_value = cursor

    with TestClient(app) as client:
        response = client.get(
            "/inventory-items/settings",
            params={
                "customer_id": "workspace-1",
                "item": "ITEM-100",
            },
        )

    assert response.status_code == 200
    assert response.json() == {
        "settings": documents,
        "total": 1,
    }

    database.__getitem__.assert_called_with(COLL)
    collection.find.assert_called_once_with(
        {
            "customer_id": "workspace-1",
            "item": "ITEM-100",
        },
        {"_id": 0},
    )
    cursor.sort.assert_called_once_with("item", 1)
    sorted_cursor.to_list.assert_awaited_once_with(5000)


def test_list_settings_omits_empty_item_filter(
    app: FastAPI,
    collection: MagicMock,
) -> None:
    cursor = MagicMock(name="cursor")
    sorted_cursor = MagicMock(name="sorted_cursor")
    sorted_cursor.to_list = AsyncMock(return_value=[])

    cursor.sort.return_value = sorted_cursor
    collection.find.return_value = cursor

    with TestClient(app) as client:
        response = client.get(
            "/inventory-items/settings",
            params={"customer_id": "workspace-1"},
        )

    assert response.status_code == 200
    assert response.json() == {
        "settings": [],
        "total": 0,
    }
    collection.find.assert_called_once_with(
        {"customer_id": "workspace-1"},
        {"_id": 0},
    )


def test_upsert_existing_settings_uses_platform_database(
    app: FastAPI,
    database: MagicMock,
    collection: MagicMock,
) -> None:
    existing = {
        "customer_id": "workspace-1",
        "item": "ITEM-100",
        "reorder_threshold": 5.0,
        "safety_buffer": 1.0,
    }
    updated = {
        "customer_id": "workspace-1",
        "item": "ITEM-100",
        "reorder_threshold": 12.0,
        "safety_buffer": 4.0,
        "notes": "Updated",
        "updated_at": "2026-07-24T12:00:00+00:00",
    }

    collection.find_one = AsyncMock(
        side_effect=[
            existing,
            updated,
        ]
    )
    collection.update_one = AsyncMock()
    collection.insert_one = AsyncMock()

    with TestClient(app) as client:
        response = client.post(
            "/inventory-items/settings",
            json={
                "customer_id": "workspace-1",
                "item": "  ITEM-100  ",
                "reorder_threshold": 12,
                "safety_buffer": 4,
                "notes": "Updated",
            },
        )

    assert response.status_code == 200
    assert response.json() == updated

    database.__getitem__.assert_called_with(COLL)

    assert collection.find_one.await_count == 2
    assert collection.find_one.await_args_list[0].args == (
        {
            "customer_id": "workspace-1",
            "item": "ITEM-100",
        },
        {"_id": 0},
    )

    collection.update_one.assert_awaited_once()
    update_filter, update_document = collection.update_one.await_args.args

    assert update_filter == {
        "customer_id": "workspace-1",
        "item": "ITEM-100",
    }
    assert update_document["$set"]["reorder_threshold"] == 12.0
    assert update_document["$set"]["safety_buffer"] == 4.0
    assert update_document["$set"]["notes"] == "Updated"
    assert "updated_at" in update_document["$set"]

    collection.insert_one.assert_not_awaited()


def test_upsert_new_settings_uses_platform_database(
    app: FastAPI,
    collection: MagicMock,
) -> None:
    created = {
        "customer_id": "workspace-2",
        "item": "ITEM-200",
        "reorder_threshold": 20.0,
        "safety_buffer": 5.0,
        "notes": "New item",
        "created_at": "2026-07-24T12:00:00+00:00",
        "updated_at": "2026-07-24T12:00:00+00:00",
    }

    collection.find_one = AsyncMock(
        side_effect=[
            None,
            created,
        ]
    )
    collection.update_one = AsyncMock()
    collection.insert_one = AsyncMock()

    with TestClient(app) as client:
        response = client.post(
            "/inventory-items/settings",
            json={
                "customer_id": "workspace-2",
                "item": "ITEM-200",
                "reorder_threshold": 20,
                "safety_buffer": 5,
                "notes": "New item",
            },
        )

    assert response.status_code == 200
    assert response.json() == created

    collection.update_one.assert_not_awaited()
    collection.insert_one.assert_awaited_once()

    inserted = collection.insert_one.await_args.args[0]
    assert inserted["customer_id"] == "workspace-2"
    assert inserted["item"] == "ITEM-200"
    assert inserted["reorder_threshold"] == 20.0
    assert inserted["safety_buffer"] == 5.0
    assert inserted["notes"] == "New item"
    assert "created_at" in inserted
    assert "updated_at" in inserted


@pytest.mark.parametrize(
    ("payload", "detail"),
    [
        (
            {
                "customer_id": "workspace-1",
                "item": "ITEM-100",
                "reorder_threshold": -1,
                "safety_buffer": 2,
                "notes": "",
            },
            "reorder_threshold must not be negative",
        ),
        (
            {
                "customer_id": "workspace-1",
                "item": "ITEM-100",
                "reorder_threshold": 1,
                "safety_buffer": -2,
                "notes": "",
            },
            "safety_buffer must not be negative",
        ),
        (
            {
                "customer_id": "workspace-1",
                "item": "   ",
                "reorder_threshold": 1,
                "safety_buffer": 2,
                "notes": "",
            },
            "item is required",
        ),
    ],
)
def test_upsert_validation_does_not_access_database(
    app: FastAPI,
    collection: MagicMock,
    payload: dict[str, object],
    detail: str,
) -> None:
    with TestClient(app) as client:
        response = client.post(
            "/inventory-items/settings",
            json=payload,
        )

    assert response.status_code == 422
    assert response.json() == {"detail": detail}
    collection.find_one.assert_not_called()
    collection.update_one.assert_not_called()
    collection.insert_one.assert_not_called()


@pytest.mark.parametrize(
    ("path", "method"),
    [
        ("/inventory-items/settings", "get"),
        ("/inventory-items/settings", "post"),
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
