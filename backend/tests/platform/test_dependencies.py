from __future__ import annotations

from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient
from motor.motor_asyncio import AsyncIOMotorDatabase

import database
from hub_platform.bootstrap.container import (
    clear_platform_container_cache,
    get_platform_container,
)
from hub_platform.bootstrap.dependencies import (
    get_platform_database,
    get_platform_mongo,
    get_platform_settings,
)


def setup_function() -> None:
    clear_platform_container_cache()


def teardown_function() -> None:
    clear_platform_container_cache()


def test_settings_provider_returns_container_settings() -> None:
    assert get_platform_settings() is get_platform_container().settings


def test_mongo_provider_returns_canonical_manager() -> None:
    assert get_platform_mongo() is database.mongo_manager
    assert get_platform_mongo() is get_platform_container().mongo


def test_database_provider_returns_canonical_database() -> None:
    assert get_platform_database() is database.db
    assert get_platform_database() is database.mongo_manager.database


def test_database_provider_returns_motor_database() -> None:
    assert isinstance(get_platform_database(), AsyncIOMotorDatabase)


def test_providers_work_with_fastapi_depends() -> None:
    app = FastAPI()

    @app.get("/platform-dependency-smoke-test")
    async def dependency_smoke_test(
        settings=Depends(get_platform_settings),
        mongo=Depends(get_platform_mongo),
        db=Depends(get_platform_database),
    ) -> dict[str, bool]:
        return {
            "settings_match": settings is get_platform_container().settings,
            "mongo_match": mongo is database.mongo_manager,
            "database_match": db is database.db,
        }

    response = TestClient(app).get("/platform-dependency-smoke-test")

    assert response.status_code == 200
    assert response.json() == {
        "settings_match": True,
        "mongo_match": True,
        "database_match": True,
    }
