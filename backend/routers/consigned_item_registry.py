"""
Consigned-item registry router — Lane C Step 2.

Thin HTTP wrapper over workflows/inventory/ownership.py consignment primitives.
All endpoints JWT-gated. State transitions additionally require actor email.
"""
from __future__ import annotations

from fastapi import APIRouter, Depends, HTTPException, Query
from pydantic import BaseModel, Field

from deps import get_db
from services.auth_deps import get_current_user
from workflows.inventory import ownership

router = APIRouter(prefix="/consigned-items", tags=["Consigned Item Registry"])


class TransitionBody(BaseModel):
    new_state: str = Field(..., description="consumed | returned")
    actor_email: str = Field(..., description="Must match CONSIGNMENT_STATE_ACTOR_EMAIL")
    evidence_id: str = Field(..., description="Document id that triggered the transition")


@router.get("")
async def list_items(
    vendor_no: str | None = Query(None),
    state: str | None = Query(None, description="consigned_in | consumed | returned"),
    limit: int = Query(200, ge=1, le=1000),
    _user: dict = Depends(get_current_user),
):
    db = get_db()
    items = await ownership.list_consigned_items(
        db, vendor_no=vendor_no, state=state, limit=limit
    )
    return {"total": len(items), "items": items}


@router.get("/{item_no}")
async def get_item(
    item_no: str,
    _user: dict = Depends(get_current_user),
):
    db = get_db()
    row = await ownership.get_consigned_item(db, item_no)
    if row is None:
        raise HTTPException(status_code=404, detail="Consigned item not found")
    return row


@router.post("")
async def upsert_item(
    payload: ownership.ConsignedItemCreate,
    user: dict = Depends(get_current_user),
):
    db = get_db()
    actor = user.get("email") or user.get("username") or "unknown"
    return await ownership.upsert_consigned_item(db, payload, actor=actor)


@router.post("/{item_no}/transition")
async def transition_item(
    item_no: str,
    body: TransitionBody,
    _user: dict = Depends(get_current_user),
):
    ownership.require_consignment_actor(body.actor_email)
    db = get_db()
    try:
        return await ownership.transition_consigned_item(
            db,
            item_no=item_no,
            new_state=body.new_state,
            actor=body.actor_email,
            evidence_id=body.evidence_id,
        )
    except PermissionError as e:
        raise HTTPException(status_code=403, detail=str(e))
    except ValueError as e:
        detail = str(e)
        # "not found" → 404; all other ValueErrors → 400
        if detail.lower().endswith("not found"):
            raise HTTPException(status_code=404, detail=detail)
        raise HTTPException(status_code=400, detail=detail)
