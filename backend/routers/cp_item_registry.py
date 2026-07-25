"""
CP-item registry router — Lane C Step 1.

Thin HTTP wrapper over workflows/inventory/ownership.py. All endpoints are
JWT-gated. Retirement additionally requires a specific actor email (signed §4b).
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from motor.motor_asyncio import AsyncIOMotorDatabase
from pydantic import BaseModel, Field

from hub_platform.bootstrap import get_platform_database
from services.auth_deps import get_current_user
from workflows.inventory import ownership

router = APIRouter(prefix="/cp-items", tags=["CP Item Registry"])


class RetireBody(BaseModel):
    actor_email: str = Field(..., description="Must match COW_RETIREMENT_ACTOR_EMAIL")


@router.get("")
async def list_cp_items(
    customer_no: str | None = Query(None),
    status: str | None = Query(None, description="active | retired"),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(get_current_user),
    database: AsyncIOMotorDatabase = Depends(get_platform_database),
):
    items = await ownership.list_all_cp_items(
        database, customer_no=customer_no, status=status, limit=limit
    )
    return {"total": len(items), "items": items}


@router.get("/{item_no}")
async def get_cp_item_endpoint(
    item_no: str,
    _user: dict = Depends(get_current_user),
    database: AsyncIOMotorDatabase = Depends(get_platform_database),
):
    row = await ownership.get_cp_item(database, item_no)
    if row is None:
        raise HTTPException(status_code=404, detail="CP item not found")
    return row


@router.post("")
async def upsert_cp_item_endpoint(
    payload: ownership.CpItemCreate,
    user: dict = Depends(get_current_user),
    database: AsyncIOMotorDatabase = Depends(get_platform_database),
):
    actor = user.get("email") or user.get("username") or "unknown"
    return await ownership.upsert_cp_item(database, payload, actor=actor)


@router.post("/{item_no}/retire")
async def retire_cp_item_endpoint(
    item_no: str,
    body: RetireBody,
    _user: dict = Depends(get_current_user),
    database: AsyncIOMotorDatabase = Depends(get_platform_database),
):
    # HTTP-layer guard raises 403 if actor mismatched
    ownership.require_retirement_actor(body.actor_email)
    try:
        return await ownership.retire_cp_item(
            database,
            item_no,
            actor=body.actor_email,
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        # Defensive — HTTP guard should have caught this already
        raise HTTPException(status_code=403, detail=str(e))
