"""Authenticated read-only AP decision replay endpoint."""

from __future__ import annotations

import os
from typing import Optional

from bson import ObjectId
from fastapi import APIRouter, Depends, Header, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase

from hub_platform.bootstrap import get_platform_database
from services.decision_replay_service import build_ap_decision_replay


router = APIRouter(prefix="/documents", tags=["Documents"])


def _verify_token(authorization: Optional[str]) -> str:
    if not authorization or not authorization.startswith("Bearer "):
        raise HTTPException(
            status_code=401,
            detail="Missing or invalid Authorization header",
        )
    token = authorization.split(" ", 1)[1]
    try:
        import jwt as pyjwt

        payload = pyjwt.decode(
            token,
            os.environ.get("JWT_SECRET", "gpi-hub-secret-key"),
            algorithms=["HS256"],
        )
        return payload.get("sub", "unknown")
    except Exception:
        raise HTTPException(status_code=401, detail="Invalid or expired token")


@router.get("/{document_id}/decision-replay")
async def replay_document_decisions(
    document_id: str,
    authorization: Optional[str] = Header(None),
    database: AsyncIOMotorDatabase = Depends(get_platform_database),
):
    """Replay local AP decisions without writes or external service calls."""
    _verify_token(authorization)

    document = await database.hub_documents.find_one(
        {"id": document_id},
        {"_id": 0},
    )
    if document is None:
        try:
            document = await database.hub_documents.find_one(
                {"_id": ObjectId(document_id)},
                {"_id": 0},
            )
        except Exception:
            document = None

    if document is None:
        raise HTTPException(status_code=404, detail="Document not found")

    return await build_ap_decision_replay(database, document)
