from __future__ import annotations

from motor.motor_asyncio import AsyncIOMotorDatabase

from hub_platform.bootstrap.container import get_platform_container
from hub_platform.bootstrap.settings import HubSettings
from hub_platform.infrastructure.mongo import MongoManager


def get_platform_settings() -> HubSettings:
    """Return the process-wide platform settings instance."""
    return get_platform_container().settings


def get_platform_mongo() -> MongoManager:
    """Return the canonical application Mongo manager."""
    return get_platform_container().mongo


def get_platform_database() -> AsyncIOMotorDatabase:
    """Return the canonical application Mongo database."""
    return get_platform_mongo().database
