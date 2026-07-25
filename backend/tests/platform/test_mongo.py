from unittest.mock import AsyncMock, MagicMock, patch

import pytest

from hub_platform.config.settings import HubSettings
from hub_platform.persistence.mongo import (
    MongoConnectionError,
    MongoManager,
)


def make_settings() -> HubSettings:
    return HubSettings.from_environment(
        {
            "MONGO_URL": "mongodb://mongo.example:27017",
            "DB_NAME": "gpi_hub_test",
        }
    )


def test_database_raises_before_connect() -> None:
    manager = MongoManager(make_settings())

    with pytest.raises(MongoConnectionError, match="not been connected"):
        _ = manager.database


@pytest.mark.asyncio
async def test_connect_creates_resources() -> None:
    client = MagicMock()
    client.admin.command = AsyncMock(return_value={"ok": 1})
    database = MagicMock()

    client.__getitem__.return_value = database

    with patch(
        "hub_platform.persistence.mongo.AsyncIOMotorClient",
        return_value=client,
    ):
        manager = MongoManager(make_settings())
        resources = await manager.connect()

    assert manager.is_connected is True
    assert resources.client is client
    assert resources.database is database
    client.admin.command.assert_awaited_once_with("ping")


@pytest.mark.asyncio
async def test_connect_is_idempotent() -> None:
    client = MagicMock()
    client.admin.command = AsyncMock(return_value={"ok": 1})
    client.__getitem__.return_value = MagicMock()

    with patch(
        "hub_platform.persistence.mongo.AsyncIOMotorClient",
        return_value=client,
    ) as client_factory:
        manager = MongoManager(make_settings())

        first = await manager.connect()
        second = await manager.connect()

    assert first is second
    client_factory.assert_called_once()


@pytest.mark.asyncio
async def test_connect_closes_client_on_failure() -> None:
    client = MagicMock()
    client.admin.command = AsyncMock(
        side_effect=RuntimeError("connection failed")
    )

    with patch(
        "hub_platform.persistence.mongo.AsyncIOMotorClient",
        return_value=client,
    ):
        manager = MongoManager(make_settings())

        with pytest.raises(MongoConnectionError, match="Unable to connect"):
            await manager.connect()

    client.close.assert_called_once()
    assert manager.is_connected is False


@pytest.mark.asyncio
async def test_disconnect_closes_client() -> None:
    client = MagicMock()
    client.admin.command = AsyncMock(return_value={"ok": 1})
    client.__getitem__.return_value = MagicMock()

    with patch(
        "hub_platform.persistence.mongo.AsyncIOMotorClient",
        return_value=client,
    ):
        manager = MongoManager(make_settings())
        await manager.connect()
        await manager.disconnect()

    client.close.assert_called_once()
    assert manager.is_connected is False


@pytest.mark.asyncio
async def test_ping_returns_false_when_disconnected() -> None:
    manager = MongoManager(make_settings())

    assert await manager.ping() is False
