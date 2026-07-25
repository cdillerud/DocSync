from __future__ import annotations

from dataclasses import dataclass

from motor.motor_asyncio import (
    AsyncIOMotorClient,
    AsyncIOMotorDatabase,
)

from hub_platform.bootstrap.settings import HubSettings


class MongoConnectionError(RuntimeError):
    """Raised when the Hub cannot establish or manage a MongoDB connection."""


@dataclass(frozen=True, slots=True)
class MongoResources:
    client: AsyncIOMotorClient
    database: AsyncIOMotorDatabase


class MongoManager:
    """Manages MongoDB resources created by or adopted by the Hub platform."""

    def __init__(self, settings: HubSettings) -> None:
        self._settings = settings
        self._resources: MongoResources | None = None
        self._owns_client = False

    @property
    def is_connected(self) -> bool:
        return self._resources is not None

    @property
    def owns_client(self) -> bool:
        """Whether this manager created and owns the active Mongo client."""
        return self._owns_client

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

    def adopt(
        self,
        client: AsyncIOMotorClient,
        database: AsyncIOMotorDatabase,
    ) -> MongoResources:
        """
        Register Mongo resources created outside this manager.

        Adopted clients remain owned by their original lifecycle. Calling
        disconnect() clears this manager's references but does not close an
        adopted client.
        """
        if self._resources is not None:
            if (
                self._resources.client is client
                and self._resources.database is database
            ):
                return self._resources

            raise MongoConnectionError(
                "MongoDB resources have already been registered"
            )

        resources = MongoResources(
            client=client,
            database=database,
        )

        self._resources = resources
        self._owns_client = False
        return resources

    async def connect(self) -> MongoResources:
        """
        Create and verify a Mongo client owned by this manager.

        If resources are already connected or adopted, the existing resources
        are returned without creating another connection pool.
        """
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
        self._owns_client = True
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
        """
        Release the active resources.

        Clients created by this manager are closed. Adopted clients are left
        open because their original owner remains responsible for shutdown.
        """
        if self._resources is None:
            return

        if self._owns_client:
            self._resources.client.close()

        self._resources = None
        self._owns_client = False
