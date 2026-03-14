"""
Inventory Item Settings Router

CRUD for per-item reorder thresholds and safety buffers.

Endpoints:
  GET  /inventory-items/settings  — list item settings for a workspace
  POST /inventory-items/settings  — upsert item settings
"""

from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from deps import get_db

router = APIRouter(prefix="/inventory-items", tags=["Inventory Item Settings"])

COLL = "inv_item_settings"


class ItemSettingsReq(BaseModel):
    customer_id: str
    item: str
    reorder_threshold: float
    safety_buffer: float
    notes: str = ""


@router.get("/settings")
async def api_list_settings(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query("", description="Filter by item"),
):
    """List item reorder settings for a workspace."""
    db = get_db()
    query = {"customer_id": customer_id}
    if item:
        query["item"] = item
    docs = await db[COLL].find(query, {"_id": 0}).sort("item", 1).to_list(5000)
    return {"settings": docs, "total": len(docs)}


@router.post("/settings")
async def api_upsert_settings(body: ItemSettingsReq):
    """Upsert reorder settings for a specific item + workspace.

    Rejects negative reorder_threshold or safety_buffer (422).
    """
    if body.reorder_threshold < 0:
        raise HTTPException(status_code=422, detail="reorder_threshold must not be negative")
    if body.safety_buffer < 0:
        raise HTTPException(status_code=422, detail="safety_buffer must not be negative")
    if not body.item.strip():
        raise HTTPException(status_code=422, detail="item is required")

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    item_key = body.item.strip()

    existing = await db[COLL].find_one(
        {"customer_id": body.customer_id, "item": item_key}, {"_id": 0}
    )

    if existing:
        await db[COLL].update_one(
            {"customer_id": body.customer_id, "item": item_key},
            {"$set": {
                "reorder_threshold": body.reorder_threshold,
                "safety_buffer": body.safety_buffer,
                "notes": body.notes,
                "updated_at": now,
            }},
        )
    else:
        await db[COLL].insert_one({
            "customer_id": body.customer_id,
            "item": item_key,
            "reorder_threshold": body.reorder_threshold,
            "safety_buffer": body.safety_buffer,
            "notes": body.notes,
            "created_at": now,
            "updated_at": now,
        })

    doc = await db[COLL].find_one(
        {"customer_id": body.customer_id, "item": item_key}, {"_id": 0}
    )
    return doc
