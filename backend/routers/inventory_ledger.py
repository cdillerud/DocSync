"""
Customer Inventory Ledger Router

REST API for the customer-specific inventory ledger module.
All endpoints under /inventory-ledger/.
"""

import logging
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field
from typing import Optional
from deps import get_db
from services.inventory_ledger_service import (
    list_customers, get_customer, create_customer, update_customer,
    create_movement, list_movements,
    derive_balances, customer_summary,
    create_incoming, update_incoming, list_incoming,
    distinct_items, distinct_warehouses,
    seed_opening_balances, ensure_indexes,
    MOVEMENT_TYPES, SOURCE_TYPES, OWNERSHIP_TYPES,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/inventory-ledger", tags=["Inventory Ledger"])


# ═══════════════════════════════════════════════════════════════
# MODELS
# ═══════════════════════════════════════════════════════════════

class CreateCustomerReq(BaseModel):
    name: str
    code: str
    negative_balance_policy: str = Field("warn_only", description="warn_only or block_commitment")


class UpdateCustomerReq(BaseModel):
    name: Optional[str] = None
    code: Optional[str] = None
    negative_balance_policy: Optional[str] = None
    active: Optional[bool] = None


class CreateMovementReq(BaseModel):
    item: str
    item_description: str = ""
    warehouse: str = "MAIN"
    ownership_type: str = "customer_owned"
    movement_type: str
    quantity_delta: float
    unit_of_measure: str = "units"
    source_type: str = "manual_entry"
    reference_type: str = ""
    reference_id: str = ""
    notes: str = ""


class CreateIncomingReq(BaseModel):
    item: str
    item_description: str = ""
    warehouse: str = "MAIN"
    ownership_type: str = "customer_owned"
    incoming_qty: float
    unit_of_measure: str = "units"
    eta: str = ""
    source_reference: str = ""
    notes: str = ""


class UpdateIncomingReq(BaseModel):
    incoming_qty: Optional[float] = None
    eta: Optional[str] = None
    source_reference: Optional[str] = None
    status: Optional[str] = None
    notes: Optional[str] = None
    warehouse: Optional[str] = None


class SeedRow(BaseModel):
    item: str
    item_description: str = ""
    warehouse: str = "MAIN"
    ownership_type: str = "customer_owned"
    quantity: float
    unit_of_measure: str = "units"
    notes: str = ""


class SeedReq(BaseModel):
    rows: list[SeedRow]


# ═══════════════════════════════════════════════════════════════
# CUSTOMER WORKSPACES
# ═══════════════════════════════════════════════════════════════

@router.get("/customers")
async def api_list_customers(active_only: bool = True):
    db = get_db()
    return await list_customers(db, active_only)


@router.post("/customers")
async def api_create_customer(body: CreateCustomerReq):
    db = get_db()
    try:
        return await create_customer(db, body.name, body.code, body.negative_balance_policy)
    except Exception as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/customers/{customer_id}")
async def api_get_customer(customer_id: str):
    db = get_db()
    c = await get_customer(db, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer workspace not found")
    return c


@router.put("/customers/{customer_id}")
async def api_update_customer(customer_id: str, body: UpdateCustomerReq):
    db = get_db()
    c = await get_customer(db, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer workspace not found")
    return await update_customer(db, customer_id, body.dict(exclude_none=True))


# ═══════════════════════════════════════════════════════════════
# BALANCES
# ═══════════════════════════════════════════════════════════════

@router.get("/customers/{customer_id}/balances")
async def api_get_balances(
    customer_id: str,
    item: str = Query("", description="Filter by item"),
    warehouse: str = Query("", description="Filter by warehouse"),
):
    db = get_db()
    c = await get_customer(db, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer workspace not found")
    balances = await derive_balances(db, customer_id, item=item or None, warehouse=warehouse or None)
    return {"customer_id": customer_id, "balances": balances, "count": len(balances)}


@router.get("/customers/{customer_id}/summary")
async def api_get_summary(customer_id: str):
    db = get_db()
    c = await get_customer(db, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer workspace not found")
    s = await customer_summary(db, customer_id)
    return {"customer_id": customer_id, "customer_name": c["name"], **s}


# ═══════════════════════════════════════════════════════════════
# MOVEMENTS (immutable)
# ═══════════════════════════════════════════════════════════════

@router.get("/customers/{customer_id}/movements")
async def api_list_movements(
    customer_id: str,
    item: str = "", warehouse: str = "",
    movement_type: str = "", source_type: str = "",
    skip: int = Query(0, ge=0), limit: int = Query(100, ge=1, le=500),
):
    db = get_db()
    return await list_movements(db, customer_id, item, warehouse, movement_type, source_type, skip, limit)


@router.post("/customers/{customer_id}/movements")
async def api_create_movement(customer_id: str, body: CreateMovementReq):
    db = get_db()
    try:
        result = await create_movement(
            db, customer_id,
            item=body.item,
            item_description=body.item_description,
            warehouse=body.warehouse,
            ownership_type=body.ownership_type,
            movement_type=body.movement_type,
            quantity_delta=body.quantity_delta,
            unit_of_measure=body.unit_of_measure,
            source_type=body.source_type,
            reference_type=body.reference_type,
            reference_id=body.reference_id,
            notes=body.notes,
            created_by="gpi_hub",
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# INCOMING SUPPLY
# ═══════════════════════════════════════════════════════════════

@router.get("/customers/{customer_id}/incoming")
async def api_list_incoming(customer_id: str, status: str = "", item: str = ""):
    db = get_db()
    return await list_incoming(db, customer_id, status, item)


@router.post("/customers/{customer_id}/incoming")
async def api_create_incoming(customer_id: str, body: CreateIncomingReq):
    db = get_db()
    c = await get_customer(db, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer workspace not found")
    return await create_incoming(
        db, customer_id,
        item=body.item, item_description=body.item_description,
        warehouse=body.warehouse, ownership_type=body.ownership_type,
        incoming_qty=body.incoming_qty, unit_of_measure=body.unit_of_measure,
        eta=body.eta, source_reference=body.source_reference,
        notes=body.notes, created_by="gpi_hub",
    )


@router.put("/customers/{customer_id}/incoming/{supply_id}")
async def api_update_incoming(customer_id: str, supply_id: str, body: UpdateIncomingReq):
    db = get_db()
    result = await update_incoming(db, supply_id, body.dict(exclude_none=True))
    if not result:
        raise HTTPException(status_code=404, detail="Incoming supply record not found")
    return result


# ═══════════════════════════════════════════════════════════════
# SEED / IMPORT
# ═══════════════════════════════════════════════════════════════

@router.post("/customers/{customer_id}/seed")
async def api_seed_opening_balances(customer_id: str, body: SeedReq):
    db = get_db()
    c = await get_customer(db, customer_id)
    if not c:
        raise HTTPException(status_code=404, detail="Customer workspace not found")
    rows = [r.dict() for r in body.rows]
    return await seed_opening_balances(db, customer_id, rows, created_by="gpi_hub_import")


# ═══════════════════════════════════════════════════════════════
# LOOKUPS
# ═══════════════════════════════════════════════════════════════

@router.get("/customers/{customer_id}/items")
async def api_distinct_items(customer_id: str):
    db = get_db()
    return await distinct_items(db, customer_id)


@router.get("/customers/{customer_id}/warehouses")
async def api_distinct_warehouses(customer_id: str):
    db = get_db()
    return await distinct_warehouses(db, customer_id)


@router.get("/meta")
async def api_meta():
    """Return valid enums for the UI."""
    return {
        "movement_types": sorted(MOVEMENT_TYPES),
        "source_types": sorted(SOURCE_TYPES),
        "ownership_types": sorted(OWNERSHIP_TYPES),
    }
