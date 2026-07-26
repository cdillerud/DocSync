"""
FastAPI dependencies shared by the active GPI Document Hub application.
"""

from fastapi import Request
from motor.motor_asyncio import AsyncIOMotorDatabase


def get_database(request: Request) -> AsyncIOMotorDatabase:
    """Return the MongoDB database attached to the FastAPI application."""
    database = getattr(request.app.state, "database", None)

    if database is None:
        raise RuntimeError("Application database has not been initialized")

    return database
