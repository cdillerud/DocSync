from __future__ import annotations

import database

from hub_platform.bootstrap.container import (
    clear_platform_container_cache,
    get_platform_container,
)
from hub_platform.bootstrap.settings import get_settings


def setup_function() -> None:
    clear_platform_container_cache()


def teardown_function() -> None:
    clear_platform_container_cache()


def test_container_exposes_canonical_dependencies() -> None:
    container = get_platform_container()

    assert container.settings is get_settings()
    assert container.mongo is database.mongo_manager
    assert container.mongo.client is database.client
    assert container.mongo.database is database.db


def test_container_is_process_singleton() -> None:
    first = get_platform_container()
    second = get_platform_container()

    assert second is first


def test_clearing_cache_recreates_container_not_dependencies() -> None:
    first = get_platform_container()

    clear_platform_container_cache()

    second = get_platform_container()

    assert second is not first
    assert second.settings is first.settings
    assert second.mongo is first.mongo
