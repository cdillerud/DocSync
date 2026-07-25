from __future__ import annotations

from dataclasses import dataclass
from functools import lru_cache

from hub_platform.bootstrap.settings import HubSettings, get_settings
from hub_platform.infrastructure.mongo import MongoManager


@dataclass(frozen=True, slots=True)
class PlatformContainer:
    """Shared application-level platform dependencies."""

    settings: HubSettings
    mongo: MongoManager


@lru_cache(maxsize=1)
def get_platform_container() -> PlatformContainer:
    """
    Return the process-wide platform dependency container.

    Importing database lazily prevents a circular import while preserving
    the canonical application MongoManager instance.
    """
    from database import mongo_manager

    return PlatformContainer(
        settings=get_settings(),
        mongo=mongo_manager,
    )


def clear_platform_container_cache() -> None:
    """Clear the cached container for isolated tests."""
    get_platform_container.cache_clear()
