from __future__ import annotations

from typing import cast
from unittest.mock import MagicMock

import pytest

from hub_platform.bootstrap.settings import HubSettings
from hub_platform.infrastructure.mongo import (
    MongoConnectionError,
    MongoManager,
)


def make_manager() -> MongoManager:
    settings = cast(HubSettings, object())
    return MongoManager(settings)


def test_adopt_registers_existing_resources() -> None:
    manager = make_manager()
    client = MagicMock()
    database = MagicMock()

    resources = manager.adopt(client, database)

    assert manager.is_connected is True
    assert manager.owns_client is False
    assert resources.client is client
    assert resources.database is database
    assert manager.client is client
    assert manager.database is database


def test_adopt_is_idempotent_for_same_resources() -> None:
    manager = make_manager()
    client = MagicMock()
    database = MagicMock()

    first = manager.adopt(client, database)
    second = manager.adopt(client, database)

    assert second is first


def test_adopt_rejects_different_resources() -> None:
    manager = make_manager()

    manager.adopt(MagicMock(), MagicMock())

    with pytest.raises(
        MongoConnectionError,
        match="already been registered",
    ):
        manager.adopt(MagicMock(), MagicMock())


@pytest.mark.asyncio
async def test_disconnect_does_not_close_adopted_client() -> None:
    manager = make_manager()
    client = MagicMock()
    database = MagicMock()

    manager.adopt(client, database)
    await manager.disconnect()

    client.close.assert_not_called()
    assert manager.is_connected is False
    assert manager.owns_client is False
