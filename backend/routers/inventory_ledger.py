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
    create_movement, list_movements, get_history, item_audit_summary,
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
# MANUAL MOVEMENT ENTRY (validated, restricted types)
# ═══════════════════════════════════════════════════════════════

MANUAL_ALLOWED_TYPES = {"opening_balance", "manual_adjustment", "transfer", "writeoff", "correction"}
MANUAL_BLOCKED_TYPES = {"order_commitment", "order_release", "receipt"}


class ManualMovementReq(BaseModel):
    customer_id: str
    movement_type: str
    item: str
    qty: float
    item_description: str = ""
    warehouse: str = "MAIN"
    ownership_type: str = "customer_owned"
    unit_of_measure: str = "units"
    reference: str = ""
    notes: str = ""
    idempotency_key: str = ""


@router.post("/movements")
async def api_manual_movement(body: ManualMovementReq):
    """Create a manual inventory ledger movement with strict validation.

    Only allows: opening_balance, manual_adjustment, transfer, writeoff, correction.
    Rejects order_commitment, order_release, receipt (use dedicated workflows).
    Rejects zero quantity (422). Writeoff must be negative.
    Duplicate opening_balance for same item/customer/warehouse/ownership is rejected.
    Lightweight idempotency via idempotency_key.
    """
    db = get_db()

    # Type validation
    if body.movement_type in MANUAL_BLOCKED_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Movement type '{body.movement_type}' is not allowed through manual entry. "
                   f"Use the dedicated workflow endpoint.",
        )
    if body.movement_type not in MANUAL_ALLOWED_TYPES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid movement type '{body.movement_type}'. "
                   f"Allowed: {', '.join(sorted(MANUAL_ALLOWED_TYPES))}",
        )

    # Zero qty
    if body.qty == 0:
        raise HTTPException(status_code=422, detail="Quantity must not be zero")

    # Writeoff must reduce inventory
    if body.movement_type == "writeoff" and body.qty > 0:
        raise HTTPException(
            status_code=422,
            detail="Writeoff must reduce inventory (use negative quantity)",
        )

    # Duplicate opening_balance check
    if body.movement_type == "opening_balance":
        from services.inventory_ledger_service import MOVEMENTS_COLL
        existing = await db[MOVEMENTS_COLL].find_one({
            "customer_id": body.customer_id,
            "item": body.item.strip(),
            "warehouse": body.warehouse.strip(),
            "ownership_type": body.ownership_type,
            "movement_type": "opening_balance",
        }, {"_id": 0, "id": 1})
        if existing:
            raise HTTPException(
                status_code=409,
                detail=f"Opening balance already exists for item '{body.item}' "
                       f"in warehouse '{body.warehouse}'. Use 'correction' or "
                       f"'manual_adjustment' to modify.",
            )

    # Idempotency guard
    if body.idempotency_key:
        from services.inventory_ledger_service import MOVEMENTS_COLL
        dup = await db[MOVEMENTS_COLL].find_one(
            {"idempotency_key": body.idempotency_key},
            {"_id": 0, "id": 1},
        )
        if dup:
            raise HTTPException(
                status_code=409, detail="Duplicate submission detected (idempotency key match)",
            )

    try:
        result = await create_movement(
            db, body.customer_id,
            item=body.item,
            item_description=body.item_description,
            warehouse=body.warehouse,
            ownership_type=body.ownership_type,
            movement_type=body.movement_type,
            quantity_delta=body.qty,
            unit_of_measure=body.unit_of_measure,
            source_type="manual_entry",
            reference_type="manual",
            reference_id=body.reference,
            notes=body.notes,
            created_by="gpi_hub",
        )
        # Store idempotency_key on the movement if provided
        if body.idempotency_key and result.get("success"):
            from services.inventory_ledger_service import MOVEMENTS_COLL
            await db[MOVEMENTS_COLL].update_one(
                {"id": result["movement"]["id"]},
                {"$set": {"idempotency_key": body.idempotency_key}},
            )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))




# ═══════════════════════════════════════════════════════════════
# HISTORY & AUDIT
# ═══════════════════════════════════════════════════════════════

@router.get("/history")
async def api_history(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query("", description="Filter by item"),
    reference: str = Query("", description="Filter by reference_id"),
    movement_type: str = Query("", description="Filter by movement_type"),
    limit: int = Query(100, ge=1, le=500),
    offset: int = Query(0, ge=0),
):
    """Return movement history with display_effect enrichment, reverse chronological."""
    db = get_db()
    return await get_history(
        db, customer_id, item=item, reference=reference,
        movement_type=movement_type, skip=offset, limit=limit,
    )


@router.get("/history/summary")
async def api_history_summary(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query(..., description="Item to summarize"),
):
    """Compact audit summary: per-type totals + current balance for a given item."""
    db = get_db()
    return await item_audit_summary(db, customer_id, item=item)



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


# ═══════════════════════════════════════════════════════════════
# ORDER RELEASE
# ═══════════════════════════════════════════════════════════════

class ReleaseLineReq(BaseModel):
    item: str
    qty: float


class ReleaseReq(BaseModel):
    sales_order_id: str
    lines: list[ReleaseLineReq]


@router.post("/release")
async def api_release_commitments(body: ReleaseReq):
    """Release committed inventory for a fulfilled or cancelled Sales Order.

    Validates that matching order_commitment exists and that release qty
    does not exceed the outstanding committed quantity.
    """
    db = get_db()
    try:
        from services.inventory_so_integration import release_order_commitments
        result = await release_order_commitments(
            db,
            sales_order_id=body.sales_order_id,
            lines=[{"item": ln.item, "qty": ln.qty} for ln in body.lines],
            created_by="gpi_hub",
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))



# ═══════════════════════════════════════════════════════════════
# SALES ORDER RECONCILIATION
# ═══════════════════════════════════════════════════════════════

class ReconcileLineReq(BaseModel):
    item: str
    qty: float


class ReconcileSOReq(BaseModel):
    sales_order_id: str
    lines: list[ReconcileLineReq] = []
    cancelled: bool = False


@router.post("/reconcile-sales-order")
async def api_reconcile_sales_order(body: ReconcileSOReq):
    """Reconcile inventory commitments for an edited or cancelled Sales Order.

    When cancelled=true, releases all remaining net commitments.
    When cancelled=false, adjusts per-line: creates delta commitments or releases.
    """
    db = get_db()
    try:
        from services.inventory_so_integration import reconcile_sales_order
        result = await reconcile_sales_order(
            db,
            sales_order_id=body.sales_order_id,
            lines=[{"item": ln.item, "qty": ln.qty} for ln in body.lines],
            cancelled=body.cancelled,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


# ═══════════════════════════════════════════════════════════════
# INCOMING SUPPLY FROM SHORTAGE (separate prefix)
# ═══════════════════════════════════════════════════════════════

incoming_supply_router = APIRouter(prefix="/incoming-supply", tags=["Incoming Supply"])


class ShortageLineReq(BaseModel):
    item: str
    qty_needed: float
    qty_available: float


class ShortageReq(BaseModel):
    sales_order_id: str
    lines: list[ShortageLineReq]


@incoming_supply_router.post("/from-shortage")
async def api_create_from_shortage(body: ShortageReq):
    """Create incoming supply records for SHORT items on a Sales Order.

    Returns 409 if a duplicate supply record already exists for the same
    item + order reference. Returns 422 if shortage <= 0.
    """
    db = get_db()
    try:
        from services.inventory_so_integration import create_shortage_supply
        result = await create_shortage_supply(
            db,
            sales_order_id=body.sales_order_id,
            lines=[{"item": ln.item, "qty_needed": ln.qty_needed, "qty_available": ln.qty_available} for ln in body.lines],
            created_by="gpi_hub",
        )
        # If ALL lines were duplicates and nothing was created, return 409
        if result["created"] == 0 and len(result["duplicates"]) > 0:
            raise HTTPException(
                status_code=409,
                detail={
                    "message": f"Duplicate incoming supply already exists for: {', '.join(result['duplicates'])}",
                    "duplicates": result["duplicates"],
                },
            )
        return result
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))



class StatusTransitionReq(BaseModel):
    status: str


@incoming_supply_router.post("/{supply_id}/status")
async def api_transition_status(supply_id: str, body: StatusTransitionReq):
    """Transition an incoming supply record's status.

    Valid: planned→ordered, planned→cancelled, ordered→received, ordered→cancelled.
    When received, creates a receipt ledger movement.
    Returns 409 if already received. Returns 422 for invalid transitions.
    """
    db = get_db()
    try:
        from services.inventory_so_integration import (
            transition_supply_status, DuplicateReceiptError,
        )
        result = await transition_supply_status(
            db, supply_id=supply_id, new_status=body.status,
        )
        return result
    except DuplicateReceiptError as e:
        raise HTTPException(status_code=409, detail=str(e))
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))
