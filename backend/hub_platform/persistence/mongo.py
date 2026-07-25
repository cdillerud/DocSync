from __future__ import annotations

from dataclasses import dataclass

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorDatabase,
)

from hub_platform.config.settings import HubSettings


class MongoConnectionError(RuntimeError):
    """Raised when the Hub cannot establish a MongoDB connection."""


@dataclass(frozen=True, slots=True)
class MongoResources:
    client: AsyncIOMotorClient
    database: AsyncIOMotorDatabase


class MongoManager:
    """Owns the MongoDB client and database lifecycle."""

    def __init__(self, settings: HubSettings) -> None:
        self._settings = settings
        self._resources: MongoResources | None = None

    @property
    def is_connected(self) -> bool:
        return self._resources is not None

    @property
    def client(self) -> AsyncIOMotorClient:
        if self._resources is None:
            raise MongoConnectionError("MongoDB has not been connected")

        return self._resources.client

    @property
    def database(self) -> AsyncIOMotorDatabase:
        if self._resources is None:
            raise MongoConnectionError("MongoDB has not been connected")

        return self._resources.database

    async def connect(self) -> MongoResources:
        if self._resources is not None:
            return self._resources

        client = AsyncIOMotorClient(
            self._settings.mongo_url,
            serverSelectionTimeoutMS=5000,
            connectTimeoutMS=5000,
        )

        try:
            await client.admin.command("ping")
        except Exception as exc:
            client.close()
            raise MongoConnectionError(
                f"Unable to connect to MongoDB database "
                f"{self._settings.db_name!r}"
            ) from exc

        resources = MongoResources(
            client=client,
            database=client[self._settings.db_name],
        )

        self._resources = resources
        return resources

    async def ping(self) -> bool:
        if self._resources is None:
            return False

        try:
            await self._resources.client.admin.command("ping")
        except Exception:
            return False

        return True

    async def disconnect(self) -> None:
        if self._resources is None:
            return

        self._resources.client.close()
        self._resources = None
