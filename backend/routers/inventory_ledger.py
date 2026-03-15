"""
Customer Inventory Ledger Router

REST API for the customer-specific inventory ledger module.
All endpoints under /inventory-ledger/.
"""

import logging
import hashlib
import csv
import io
from datetime import datetime, timezone, timedelta
from fastapi import APIRouter, HTTPException, Query, UploadFile, File, Form
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
    MOVEMENT_TYPES, SOURCE_TYPES, OWNERSHIP_TYPES, MOVEMENTS_COLL,
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
# DASHBOARD SUMMARY
# ═══════════════════════════════════════════════════════════════

@router.get("/dashboard-summary")
async def api_dashboard_summary(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query("", description="Filter by item"),
):
    """Compute inventory health metrics from derive_balances.

    Uses the same status logic (is_short / is_low) as the balance table and CSV export.
    total_reorder_recommendations mirrors the count from /reorder-recommendations.
    Returns zeros for all fields when no inventory exists.
    """
    db = get_db()
    balances = await derive_balances(db, customer_id, item=item or None)

    total_items = len(set(b["item"] for b in balances))
    items_ok = 0
    items_low = 0
    items_short = 0
    total_on_hand = 0.0
    total_incoming = 0.0
    total_committed = 0.0
    total_available = 0.0

    for b in balances:
        total_on_hand += b.get("on_hand", 0)
        total_incoming += b.get("incoming", 0)
        total_committed += b.get("committed", 0)
        total_available += b.get("available", 0)
        if b.get("is_short"):
            items_short += 1
        elif b.get("is_low"):
            items_low += 1
        else:
            items_ok += 1

    # Reorder recommendation count — same logic as api_reorder_recommendations
    settings_docs = await db["inv_item_settings"].find(
        {"customer_id": customer_id}, {"_id": 0}
    ).to_list(5000)
    settings_map = {s["item"]: s for s in settings_docs}

    reorder_count = 0
    for b in balances:
        avail = b.get("available", 0)
        is_short = b.get("is_short", False)
        s = settings_map.get(b["item"])
        threshold = s["reorder_threshold"] if s else DEFAULT_REORDER_THRESHOLD
        if avail > threshold and not is_short:
            continue
        reorder_count += 1

    return {
        "total_items": total_items,
        "items_ok": items_ok,
        "items_low": items_low,
        "items_short": items_short,
        "total_on_hand": round(total_on_hand, 2),
        "total_incoming": round(total_incoming, 2),
        "total_committed": round(total_committed, 2),
        "total_available": round(total_available, 2),
        "total_reorder_recommendations": reorder_count,
    }


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
# CSV IMPORT
# ═══════════════════════════════════════════════════════════════

IMPORT_ALLOWED_MODES = {"opening_balance", "manual_adjustment"}
IMPORT_HASHES_COLL = "inv_import_hashes"


@router.post("/import")
async def api_import_csv(
    file: UploadFile = File(...),
    customer_id: str = Form(...),
    import_mode: str = Form(...),
):
    """Import inventory movements from CSV.

    Each row becomes an immutable ledger movement using the selected import_mode.
    Only opening_balance and manual_adjustment are allowed.
    Duplicate import protection via SHA-256 file hash (409 on duplicate).
    For opening_balance: rejects rows where an opening balance already exists
    for the same item/customer/warehouse/ownership.
    """
    db = get_db()

    # Validate import mode
    if import_mode not in IMPORT_ALLOWED_MODES:
        raise HTTPException(
            status_code=422,
            detail=f"Invalid import_mode '{import_mode}'. Allowed: {', '.join(sorted(IMPORT_ALLOWED_MODES))}",
        )

    # Validate customer exists
    cust = await get_customer(db, customer_id)
    if not cust:
        raise HTTPException(status_code=404, detail="Customer workspace not found")

    # Read file content
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Empty file")

    # Duplicate import protection via file hash
    file_hash = hashlib.sha256(raw + customer_id.encode() + import_mode.encode()).hexdigest()
    existing_hash = await db[IMPORT_HASHES_COLL].find_one({"hash": file_hash})
    if existing_hash:
        raise HTTPException(
            status_code=409,
            detail="Duplicate import detected. This file has already been imported.",
        )

    # Parse CSV
    try:
        text = raw.decode("utf-8-sig")
    except UnicodeDecodeError:
        text = raw.decode("latin-1")

    reader = csv.DictReader(io.StringIO(text))
    if not reader.fieldnames:
        raise HTTPException(status_code=422, detail="CSV has no columns")

    # Normalize column names
    cols = [c.strip().lower().replace(" ", "_") for c in reader.fieldnames]
    if "item" not in cols:
        raise HTTPException(status_code=422, detail="CSV missing required column: 'item'")
    if "qty" not in cols:
        raise HTTPException(status_code=422, detail="CSV missing required column: 'qty'")

    rows_processed = 0
    rows_imported = 0
    rows_failed = 0
    errors = []
    import_batch_id = f"CSV-{datetime.now(timezone.utc).strftime('%Y%m%d-%H%M%S')}-{file_hash[:8]}"

    for raw_row in reader:
        rows_processed += 1
        row_num = rows_processed + 1  # +1 for header

        # Normalize keys
        row = {k.strip().lower().replace(" ", "_"): v.strip() for k, v in raw_row.items() if v}

        item = row.get("item", "").strip()
        if not item:
            rows_failed += 1
            errors.append({"row": row_num, "error": "Missing required field: item"})
            continue

        qty_str = row.get("qty", "").strip()
        try:
            qty = float(qty_str)
        except (ValueError, TypeError):
            rows_failed += 1
            errors.append({"row": row_num, "item": item, "error": f"Invalid qty: '{qty_str}'"})
            continue

        if qty == 0:
            rows_failed += 1
            errors.append({"row": row_num, "item": item, "error": "qty must not be zero"})
            continue

        warehouse = row.get("warehouse", "MAIN").strip() or "MAIN"
        ownership_type = row.get("ownership_type", "customer_owned").strip() or "customer_owned"
        unit_of_measure = row.get("uom", row.get("unit_of_measure", "units")).strip() or "units"
        item_description = row.get("item_description", row.get("description", "")).strip()
        reference = row.get("reference", "").strip()
        notes = row.get("notes", "").strip()

        # Duplicate opening_balance check
        if import_mode == "opening_balance":
            existing = await db[MOVEMENTS_COLL].find_one({
                "customer_id": customer_id,
                "item": item,
                "warehouse": warehouse,
                "ownership_type": ownership_type,
                "movement_type": "opening_balance",
            }, {"_id": 0, "id": 1})
            if existing:
                rows_failed += 1
                errors.append({
                    "row": row_num, "item": item,
                    "error": f"Opening balance already exists for '{item}' in warehouse '{warehouse}'",
                })
                continue

        try:
            await create_movement(
                db, customer_id,
                item=item,
                item_description=item_description,
                warehouse=warehouse,
                ownership_type=ownership_type,
                movement_type=import_mode,
                quantity_delta=qty,
                unit_of_measure=unit_of_measure,
                source_type="spreadsheet_import",
                reference_type="csv_import",
                reference_id=reference or import_batch_id,
                notes=notes or f"CSV import ({import_mode})",
                created_by="gpi_hub_import",
                skip_balance_check=True,
            )
            rows_imported += 1
        except Exception as e:
            rows_failed += 1
            errors.append({"row": row_num, "item": item, "error": str(e)})

    # Store file hash only if at least one row was imported
    if rows_imported > 0:
        await db[IMPORT_HASHES_COLL].insert_one({
            "hash": file_hash,
            "customer_id": customer_id,
            "import_mode": import_mode,
            "filename": file.filename or "unknown",
            "rows_imported": rows_imported,
            "import_batch_id": import_batch_id,
            "created_at": datetime.now(timezone.utc).isoformat(),
        })

    return {
        "success": rows_imported > 0,
        "import_batch_id": import_batch_id,
        "rows_processed": rows_processed,
        "rows_imported": rows_imported,
        "rows_failed": rows_failed,
        "errors": errors[:50],  # Cap errors to avoid huge responses
    }


# ═══════════════════════════════════════════════════════════════
# BALANCE EXPORT (CSV)
# ═══════════════════════════════════════════════════════════════

@router.get("/export")
async def api_export_balances(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query("", description="Filter by item"),
    warehouse: str = Query("", description="Filter by warehouse"),
):
    """Export current inventory balances as CSV download.

    Uses the same derive_balances pipeline as the UI — identical values and status logic.
    Returns valid CSV with headers even when no rows match.
    """
    from fastapi.responses import StreamingResponse
    import csv
    import io

    db = get_db()
    cust = await get_customer(db, customer_id)
    cust_name = cust["name"] if cust else customer_id

    balances = await derive_balances(
        db, customer_id,
        item=item or None,
        warehouse=warehouse or None,
    )

    headers = [
        "item", "item_description", "warehouse", "ownership_type",
        "on_hand", "incoming", "committed", "available",
        "unit_of_measure", "status",
    ]

    buf = io.StringIO()
    writer = csv.DictWriter(buf, fieldnames=headers, extrasaction="ignore")
    writer.writeheader()
    for b in balances:
        row = {k: b.get(k, "") for k in headers}
        if b.get("is_short"):
            row["status"] = "SHORT"
        elif b.get("is_low"):
            row["status"] = "LOW"
        else:
            row["status"] = "OK"
        writer.writerow(row)

    buf.seek(0)
    safe_name = cust_name.replace(" ", "_").replace("/", "_")[:40]
    filename = f"inventory_{safe_name}.csv"

    return StreamingResponse(
        iter([buf.getvalue()]),
        media_type="text/csv",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ═══════════════════════════════════════════════════════════════
# DEMAND SIGNALS
# ═══════════════════════════════════════════════════════════════


@router.get("/demand-signals")
async def api_demand_signals(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query("", description="Filter by item"),
    limit: int = Query(500, ge=1, le=5000),
):
    """Return forward demand pressure per item from Sales Order commitments.

    Uses derive_balances for current inventory state.
    total_open_order_qty = committed balance (outstanding SO commitments).
    demand_gap = total_open_order_qty - available.
    Rows included only when total_open_order_qty > 0.
    Sorted by demand_gap descending (highest risk first).
    """
    db = get_db()
    balances = await derive_balances(db, customer_id, item=item or None)

    rows = []
    for b in balances:
        committed = b.get("committed", 0)
        if committed <= 0:
            continue
        avail = b.get("available", 0)
        demand_gap = round(committed - avail, 4)
        rows.append({
            "item": b["item"],
            "item_description": b.get("item_description", ""),
            "warehouse": b.get("warehouse", ""),
            "ownership_type": b.get("ownership_type", ""),
            "total_open_order_qty": committed,
            "total_committed_qty": committed,
            "on_hand": b.get("on_hand", 0),
            "incoming": b.get("incoming", 0),
            "available": avail,
            "demand_gap": demand_gap,
            "unit_of_measure": b.get("unit_of_measure", ""),
            "status": "SHORT" if b.get("is_short") else ("LOW" if b.get("is_low") else "OK"),
        })

    rows.sort(key=lambda r: r["demand_gap"], reverse=True)
    return {
        "total": min(len(rows), limit),
        "demand_signals": rows[:limit],
    }


# ═══════════════════════════════════════════════════════════════
# SUPPLY COVERAGE
# ═══════════════════════════════════════════════════════════════


@router.get("/supply-coverage")
async def api_supply_coverage(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query("", description="Filter by item"),
    limit: int = Query(500, ge=1, le=5000),
):
    """Return supply coverage projection per item.

    coverage = on_hand + incoming - committed
    coverage_status = 'covered' if coverage >= 0 else 'at_risk'
    Only items with committed > 0 included.
    Sorted by coverage ascending (largest shortages first).
    """
    db = get_db()
    balances = await derive_balances(db, customer_id, item=item or None)

    rows = []
    for b in balances:
        committed = b.get("committed", 0)
        if committed <= 0:
            continue
        on_hand = b.get("on_hand", 0)
        incoming = b.get("incoming", 0)
        avail = b.get("available", 0)
        coverage = round(on_hand + incoming - committed, 4)
        rows.append({
            "item": b["item"],
            "item_description": b.get("item_description", ""),
            "warehouse": b.get("warehouse", ""),
            "ownership_type": b.get("ownership_type", ""),
            "on_hand": on_hand,
            "incoming": incoming,
            "committed": committed,
            "available": avail,
            "coverage": coverage,
            "coverage_status": "covered" if coverage >= 0 else "at_risk",
            "unit_of_measure": b.get("unit_of_measure", ""),
            "status": "SHORT" if b.get("is_short") else ("LOW" if b.get("is_low") else "OK"),
        })

    rows.sort(key=lambda r: r["coverage"])
    return {
        "total": min(len(rows), limit),
        "coverage": rows[:limit],
    }


# ═══════════════════════════════════════════════════════════════
# ACTION CENTER
# ═══════════════════════════════════════════════════════════════

ACTION_TYPES = {"shortage", "reorder", "demand_gap", "coverage_risk", "no_incoming"}

# Priority weights: higher = more urgent
_PRIORITY_WEIGHTS = {
    "shortage": 50,
    "coverage_risk": 30,
    "demand_gap": 20,
    "reorder": 10,
    "no_incoming": 5,
}


def _compute_action_item(b, reorder_info, committed):
    """Classify a single balance row into action types and compute priority."""
    is_short = b.get("is_short", False)
    is_low = b.get("is_low", False)
    incoming = b.get("incoming", 0)
    on_hand = b.get("on_hand", 0)
    avail = b.get("available", 0)

    action_types = []
    if is_short:
        action_types.append("shortage")
    if reorder_info:
        action_types.append("reorder")
    if committed > 0:
        demand_gap = round(committed - avail, 4)
        if demand_gap > 0:
            action_types.append("demand_gap")
        coverage = round(on_hand + incoming - committed, 4)
        if coverage < 0:
            action_types.append("coverage_risk")
    else:
        demand_gap = 0
        coverage = None
    if (is_short or is_low) and incoming == 0:
        action_types.append("no_incoming")

    if not action_types:
        return None

    priority_score = sum(_PRIORITY_WEIGHTS.get(a, 0) for a in action_types)
    status = "SHORT" if is_short else ("LOW" if is_low else "OK")

    row = {
        "item": b["item"],
        "item_description": b.get("item_description", ""),
        "warehouse": b.get("warehouse", ""),
        "ownership_type": b.get("ownership_type", ""),
        "on_hand": on_hand,
        "incoming": incoming,
        "committed": committed,
        "available": avail,
        "status": status,
        "action_types": action_types,
        "priority_score": priority_score,
        "unit_of_measure": b.get("unit_of_measure", ""),
    }

    if reorder_info:
        row["recommended_qty"] = reorder_info["recommended_qty"]
    if committed > 0:
        row["demand_gap"] = demand_gap
        row["coverage"] = coverage
        row["coverage_status"] = "covered" if coverage >= 0 else "at_risk"

    return row


@router.get("/action-center")
async def api_action_center(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query("", description="Filter by item"),
    action_type: str = Query("", description="Filter by action type"),
    limit: int = Query(500, ge=1, le=5000),
):
    """Unified prioritized action queue consolidating exceptions, reorder,
    demand, and supply coverage.

    Uses only existing pipelines. Returns merged rows with action_types and
    priority_score. Sorted by priority_score desc, then available asc.
    """
    db = get_db()
    balances = await derive_balances(db, customer_id, item=item or None)

    # Build reorder map (same logic as reorder-recommendations)
    settings_docs = await db["inv_item_settings"].find(
        {"customer_id": customer_id}, {"_id": 0}
    ).to_list(5000)
    settings_map = {s["item"]: s for s in settings_docs}

    reorder_map = {}
    for b in balances:
        avail = b.get("available", 0)
        is_short = b.get("is_short", False)
        s = settings_map.get(b["item"])
        threshold = s["reorder_threshold"] if s else DEFAULT_REORDER_THRESHOLD
        buffer = s["safety_buffer"] if s else DEFAULT_SAFETY_BUFFER
        if avail > threshold and not is_short:
            continue
        rec_qty = round(max(0, threshold - avail) + buffer, 4)
        key = f'{b["item"]}|{b.get("warehouse", "")}|{b.get("ownership_type", "")}'
        reorder_map[key] = {"recommended_qty": rec_qty, "reorder_threshold": threshold, "safety_buffer": buffer}

    # Classify all items
    all_rows = []
    counts = {a: 0 for a in ACTION_TYPES}

    filter_types = set()
    if action_type:
        for t in action_type.split(","):
            t = t.strip().lower()
            if t in ACTION_TYPES:
                filter_types.add(t)

    for b in balances:
        key = f'{b["item"]}|{b.get("warehouse", "")}|{b.get("ownership_type", "")}'
        committed = b.get("committed", 0)
        reorder_info = reorder_map.get(key)

        row = _compute_action_item(b, reorder_info, committed)
        if not row:
            continue

        # Count all (before filter)
        for a in row["action_types"]:
            counts[a] += 1

        # Apply filter
        if filter_types and not filter_types.intersection(row["action_types"]):
            continue

        all_rows.append(row)

    # Sort: priority_score desc, then available asc
    all_rows.sort(key=lambda r: (-r["priority_score"], r["available"]))

    return {
        "total": min(len(all_rows), limit),
        "action_summary": {
            "shortage_count": counts["shortage"],
            "coverage_risk_count": counts["coverage_risk"],
            "demand_gap_count": counts["demand_gap"],
            "reorder_count": counts["reorder"],
            "no_incoming_count": counts["no_incoming"],
            "total_action_items": len(all_rows),
        },
        "actions": all_rows[:limit],
    }


# ═══════════════════════════════════════════════════════════════
# PO DRAFT GENERATION
# ═══════════════════════════════════════════════════════════════

PO_DRAFTS_COLL = "po_drafts"
PO_SUBMISSION_LOGS_COLL = "po_submission_logs"
PO_DUPLICATE_WINDOW_MINUTES = 5


class PODraftLineIn(BaseModel):
    item: str = Field(..., min_length=1)
    recommended_qty: float = Field(..., gt=0)
    source: str = Field(default="action_center")


class PODraftIn(BaseModel):
    customer_id: str = Field(..., min_length=1)
    items: list[PODraftLineIn] = Field(..., min_length=1)


@router.post("/generate-po-draft")
async def api_generate_po_draft(body: PODraftIn):
    """Generate a PO draft payload for vendor fulfillment.

    Does NOT create ledger movements or ERP records.
    Stores the draft in po_drafts collection.
    Duplicate guard: rejects if the same item+customer had a draft
    within the last PO_DUPLICATE_WINDOW_MINUTES.
    """
    db = get_db()

    # Validate customer
    cust = await get_customer(db, body.customer_id)
    if not cust:
        raise HTTPException(status_code=404, detail="Customer workspace not found")

    # Validate items exist in inventory
    balances = await derive_balances(db, body.customer_id)
    known_items = {b["item"] for b in balances}

    lines = []
    now = datetime.now(timezone.utc)
    cutoff = now - __import__("datetime").timedelta(minutes=PO_DUPLICATE_WINDOW_MINUTES)

    for line in body.items:
        item = line.item.strip()
        if item not in known_items:
            raise HTTPException(
                status_code=422,
                detail=f"Item '{item}' not found in customer inventory",
            )

        # Duplicate guard
        recent = await db[PO_DRAFTS_COLL].find_one({
            "customer_id": body.customer_id,
            "lines.item": item,
            "status": "draft",
            "created_at": {"$gte": cutoff.isoformat()},
        }, {"_id": 0, "po_draft_id": 1})
        if recent:
            raise HTTPException(
                status_code=409,
                detail=f"Duplicate draft: item '{item}' already has a recent draft ({recent['po_draft_id']}). Wait {PO_DUPLICATE_WINDOW_MINUTES} minutes or archive the existing draft.",
            )

        lines.append({
            "item": item,
            "qty": line.recommended_qty,
            "source": line.source,
        })

    # Generate draft
    import uuid
    draft_id = f"PO-DRAFT-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    draft = {
        "po_draft_id": draft_id,
        "created_at": now.isoformat(),
        "customer_id": body.customer_id,
        "customer_name": cust.get("name", ""),
        "lines": lines,
        "source": "action_center",
        "status": "draft",
        "po_type": "warehouse_supply",
        "total_qty": sum(ln["qty"] for ln in lines),
        "total_lines": len(lines),
    }

    # Insert draft (let MongoDB generate _id)
    await db[PO_DRAFTS_COLL].insert_one(draft.copy())
    # _id not in original draft dict, so no removal needed

    return draft


@router.get("/po-drafts")
async def api_list_po_drafts(
    customer_id: str = Query(..., description="Customer workspace ID"),
    status: str = Query("", description="Filter by status (draft|sent|archived)"),
    limit: int = Query(50, ge=1, le=500),
):
    """List PO drafts for a customer."""
    db = get_db()
    query = {"customer_id": customer_id}
    if status:
        query["status"] = status
    docs = await db[PO_DRAFTS_COLL].find(
        query, {"_id": 0}
    ).sort("created_at", -1).to_list(limit)

    # Enrich with latest submission status
    draft_ids = [d["po_draft_id"] for d in docs]
    if draft_ids:
        pipeline = [
            {"$match": {"po_draft_id": {"$in": draft_ids}}},
            {"$sort": {"submitted_at": -1}},
            {"$group": {"_id": "$po_draft_id", "latest_status": {"$first": "$status"}, "latest_at": {"$first": "$submitted_at"}}},
        ]
        agg = await db[PO_SUBMISSION_LOGS_COLL].aggregate(pipeline).to_list(500)
        status_map = {a["_id"]: {"latest_submission_status": a["latest_status"], "latest_submission_at": a["latest_at"]} for a in agg}
        for d in docs:
            sub = status_map.get(d["po_draft_id"])
            if sub:
                d["latest_submission_status"] = sub["latest_submission_status"]
                d["latest_submission_at"] = sub["latest_submission_at"]

    return {"total": len(docs), "drafts": docs}


@router.patch("/po-drafts/{draft_id}/status")
async def api_update_po_draft_status(
    draft_id: str,
    status: str = Query(..., description="New status"),
):
    """Update PO draft status (draft -> sent -> archived)."""
    if status not in ("draft", "sent", "archived"):
        raise HTTPException(status_code=422, detail="Invalid status. Use: draft, sent, archived")
    db = get_db()
    result = await db[PO_DRAFTS_COLL].update_one(
        {"po_draft_id": draft_id},
        {"$set": {"status": status, "updated_at": datetime.now(timezone.utc).isoformat()}},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="PO draft not found")
    return {"po_draft_id": draft_id, "status": status}


@router.get("/po-drafts/{draft_id}")
async def api_get_po_draft(draft_id: str):
    """Return the full stored PO draft with linked supply summary."""
    db = get_db()
    doc = await db[PO_DRAFTS_COLL].find_one(
        {"po_draft_id": draft_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="PO draft not found")

    # Enrich with linked supply summary
    pipeline = [
        {"$match": {"source_reference": draft_id}},
        {"$group": {
            "_id": "$status",
            "count": {"$sum": 1},
            "has_bc_po": {"$sum": {"$cond": [{"$gt": ["$bc_po_number", None]}, 1, 0]}},
        }},
    ]
    agg = await db["inv_incoming_supply"].aggregate(pipeline).to_list(20)
    total_linked = sum(a["count"] for a in agg)
    if total_linked > 0:
        doc["linked_supply_count"] = total_linked
        doc["linked_supply_status_counts"] = {a["_id"]: a["count"] for a in agg}
        doc["linked_supply_has_bc_po_number"] = any(a["has_bc_po"] > 0 for a in agg)

    # Receipt summary from aggregation
    qty_pipeline = [
        {"$match": {"source_reference": draft_id}},
        {"$group": {
            "_id": None,
            "total_qty": {"$sum": "$incoming_qty"},
            "received_qty": {"$sum": {"$cond": [{"$eq": ["$status", "received"]}, "$incoming_qty", 0]}},
            "received_count": {"$sum": {"$cond": [{"$eq": ["$status", "received"]}, 1, 0]}},
            "ordered_count": {"$sum": {"$cond": [{"$eq": ["$status", "ordered"]}, 1, 0]}},
        }},
    ]
    qty_agg = await db["inv_incoming_supply"].aggregate(qty_pipeline).to_list(1)
    if qty_agg:
        qa = qty_agg[0]
        doc["linked_supply_received_count"] = qa["received_count"]
        doc["linked_supply_ordered_count"] = qa["ordered_count"]
        doc["linked_supply_total_qty"] = qa["total_qty"]
        doc["linked_supply_received_qty"] = qa["received_qty"]

    # Document linkage + process checklist enrichment
    doc_count, docs_by_type, _ = await _get_document_links_summary(db, "po_draft", draft_id)
    po_approval = await _get_latest_approval(db, "po_draft", draft_id)
    checklist_items, checklist_complete = _derive_po_draft_checklist(doc, doc_count, docs_by_type, approval=po_approval)
    doc["linked_document_count"] = doc_count
    doc["linked_documents_by_type"] = docs_by_type
    doc["process_checklist"] = checklist_items
    doc["checklist_complete"] = checklist_complete

    # Approval enrichment
    appr_summary = await _get_approval_enrichment(db, "po_draft", draft_id)
    doc.update(appr_summary)

    # Escalation enrichment
    esc_enrich = await _get_escalation_enrichment(db, "po_draft", draft_id)
    doc.update(esc_enrich)

    # Assignment enrichment
    asgn_enrich = await _get_assignment_enrichment(db, "po_draft", draft_id)
    doc.update(asgn_enrich)

    # Activity enrichment
    act_enrich = await _get_activity_enrichment(db, "po_draft", draft_id)
    doc.update(act_enrich)

    return doc


@router.get("/po-drafts/{draft_id}/export")
async def api_export_po_draft(draft_id: str):
    """Download PO draft as a JSON file. Uses stored data exactly as saved."""
    from fastapi.responses import Response
    import json as json_mod

    db = get_db()
    doc = await db[PO_DRAFTS_COLL].find_one(
        {"po_draft_id": draft_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="PO draft not found")

    filename = f"{draft_id}.json"
    return Response(
        content=json_mod.dumps(doc, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


class PODraftVendorIn(BaseModel):
    vendor_id: str = Field(..., min_length=1)
    vendor_name: str = Field(..., min_length=1)


class BCResponseIn(BaseModel):
    bc_response_status: str = Field(..., description="created|rejected|pending")
    bc_po_number: str = Field(default="", description="BC Purchase Order number")
    bc_document_id: str = Field(default="", description="BC document ID")
    bc_response_notes: str = Field(default="", description="Notes about the response")


@router.patch("/po-drafts/{draft_id}/vendor")
async def api_update_po_draft_vendor(draft_id: str, body: PODraftVendorIn):
    """Assign or update vendor on a PO draft."""
    db = get_db()
    result = await db[PO_DRAFTS_COLL].update_one(
        {"po_draft_id": draft_id},
        {"$set": {
            "vendor_id": body.vendor_id.strip(),
            "vendor_name": body.vendor_name.strip(),
            "updated_at": datetime.now(timezone.utc).isoformat(),
        }},
    )
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="PO draft not found")
    return {"po_draft_id": draft_id, "vendor_id": body.vendor_id.strip(), "vendor_name": body.vendor_name.strip()}


BC_RESPONSE_STATUSES = ("created", "rejected", "pending")
BC_RESPONSE_TO_LOG_STATUS = {"created": "acknowledged", "rejected": "failed", "pending": "submitted"}


@router.patch("/po-drafts/{draft_id}/bc-response")
async def api_update_bc_response(draft_id: str, body: BCResponseIn):
    """Record the downstream BC processing result for a PO draft.

    Does NOT create or modify BC records. Purely informational.
    Auto-creates a submission log entry mapped from the response status.
    """
    import uuid as _uuid

    if body.bc_response_status not in BC_RESPONSE_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid bc_response_status. Use: {', '.join(BC_RESPONSE_STATUSES)}")

    if body.bc_response_status == "rejected" and not body.bc_response_notes.strip():
        raise HTTPException(status_code=422, detail="bc_response_notes is required when status is 'rejected'")

    db = get_db()
    doc = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": draft_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="PO draft not found")

    now = datetime.now(timezone.utc).isoformat()
    update_fields = {
        "bc_response_status": body.bc_response_status,
        "bc_response_at": now,
        "bc_response_notes": body.bc_response_notes.strip(),
        "updated_at": now,
    }
    if body.bc_po_number.strip():
        update_fields["bc_po_number"] = body.bc_po_number.strip()
    if body.bc_document_id.strip():
        update_fields["bc_document_id"] = body.bc_document_id.strip()

    await db[PO_DRAFTS_COLL].update_one(
        {"po_draft_id": draft_id},
        {"$set": update_fields},
    )

    # Auto-create submission log entry
    vendor_id = (doc.get("vendor_id") or "").strip()
    vendor_name = (doc.get("vendor_name") or "").strip()
    log_status = BC_RESPONSE_TO_LOG_STATUS.get(body.bc_response_status, "submitted")
    notes_parts = [f"BC response: {body.bc_response_status}"]
    if body.bc_po_number.strip():
        notes_parts.append(f"PO#: {body.bc_po_number.strip()}")
    if body.bc_response_notes.strip():
        notes_parts.append(body.bc_response_notes.strip())

    # Build BC payload snapshot from current draft state
    created_at = doc.get("created_at", "")
    document_date = created_at[:10] if len(created_at) >= 10 else now[:10]
    bc_lines = []
    for line in doc.get("lines", []):
        item = (line.get("item") or "").strip()
        qty = line.get("qty", 0)
        if item and qty > 0:
            bc_lines.append({"itemNumber": item, "quantity": qty, "sourceReference": line.get("source", "")})

    payload_snapshot = {
        "poDraftId": doc["po_draft_id"],
        "vendor": {"vendorId": vendor_id, "vendorName": vendor_name},
        "documentDate": document_date,
        "source": "GPI_Hub_PO_Draft",
        "lines": bc_lines,
    }

    log_entry = {
        "submission_id": f"SUB-{_uuid.uuid4().hex[:8].upper()}",
        "po_draft_id": draft_id,
        "submitted_at": now,
        "submitted_by": None,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "status": log_status,
        "notes": " | ".join(notes_parts),
        "bc_payload_snapshot": payload_snapshot,
    }
    await db[PO_SUBMISSION_LOGS_COLL].insert_one(log_entry.copy())

    # --- BC PO linkage to incoming supply (warehouse_supply only) ---
    if body.bc_response_status == "created" and doc.get("po_type") != "drop_ship":
        link_update = {"bc_po_number": body.bc_po_number.strip(), "bc_document_id": body.bc_document_id.strip(), "updated_at": now}
        # Advance planned → ordered; leave ordered/received/cancelled unchanged
        await db["inv_incoming_supply"].update_many(
            {"source_reference": draft_id, "status": "planned"},
            {"$set": {**link_update, "status": "ordered"}},
        )
        # For already ordered records, just set BC fields (idempotent)
        await db["inv_incoming_supply"].update_many(
            {"source_reference": draft_id, "status": "ordered"},
            {"$set": {"bc_po_number": body.bc_po_number.strip(), "bc_document_id": body.bc_document_id.strip(), "updated_at": now}},
        )

    # Return the updated draft
    updated = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": draft_id}, {"_id": 0})
    # System activity for BC response
    await _create_activity(db, "po_draft", draft_id, "bc_response",
                           f"BC response: {body.bc_response_status}", body.bc_response_notes.strip(), "system",
                           {"bc_po_number": body.bc_po_number.strip()})
    return updated


@router.get("/po-drafts/{draft_id}/bc-export")
async def api_bc_export_po_draft(draft_id: str):
    """Generate a Business Central compatible purchase order payload.

    Does NOT send data to BC or create any records. Returns a structured
    JSON payload shaped for BC PO creation. Validates vendor info, lines,
    and draft status before generating. Auto-creates a submission log entry.
    """
    from fastapi.responses import Response
    import json as json_mod

    db = get_db()
    doc = await db[PO_DRAFTS_COLL].find_one(
        {"po_draft_id": draft_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="PO draft not found")

    # --- Validation ---
    if doc.get("status") == "archived":
        raise HTTPException(status_code=422, detail="Cannot export an archived draft for BC")

    lines = doc.get("lines", [])
    if not lines:
        raise HTTPException(status_code=422, detail="PO draft has no lines to export")

    vendor_id = (doc.get("vendor_id") or "").strip()
    vendor_name = (doc.get("vendor_name") or "").strip()
    if not vendor_id or not vendor_name:
        raise HTTPException(
            status_code=422,
            detail="Vendor information is required for BC export. Assign a vendor to this draft first.",
        )

    # --- Build BC payload ---
    created_at = doc.get("created_at", "")
    document_date = created_at[:10] if len(created_at) >= 10 else datetime.now(timezone.utc).strftime("%Y-%m-%d")

    bc_lines = []
    for line in lines:
        item = (line.get("item") or "").strip()
        qty = line.get("qty", 0)
        if item and qty > 0:
            bc_lines.append({
                "itemNumber": item,
                "quantity": qty,
                "sourceReference": line.get("source", ""),
            })

    payload = {
        "poDraftId": doc["po_draft_id"],
        "vendor": {
            "vendorId": vendor_id,
            "vendorName": vendor_name,
        },
        "documentDate": document_date,
        "source": "GPI_Hub_PO_Draft",
        "lines": bc_lines,
    }

    # --- Auto-create submission log entry ---
    import uuid as _uuid
    now = datetime.now(timezone.utc).isoformat()
    log_entry = {
        "submission_id": f"SUB-{_uuid.uuid4().hex[:8].upper()}",
        "po_draft_id": draft_id,
        "submitted_at": now,
        "submitted_by": None,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "status": "exported",
        "notes": "Auto-logged on BC payload export",
        "bc_payload_snapshot": payload,
    }
    await db[PO_SUBMISSION_LOGS_COLL].insert_one(log_entry.copy())

    # System activity for BC export
    await _create_activity(db, "po_draft", draft_id, "bc_export",
                           f"BC export payload generated", "", "system")

    filename = f"BC-PO-{draft_id}.json"
    return Response(
        content=json_mod.dumps(payload, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ═══════════════════════════════════════════════════════════════
# PO SUBMISSION LOG
# ═══════════════════════════════════════════════════════════════

SUBMISSION_STATUSES = ("exported", "submitted", "acknowledged", "failed")


class SubmissionLogIn(BaseModel):
    status: str = Field(..., description="exported|submitted|acknowledged|failed")
    notes: str = Field(default="", description="Optional notes")


@router.post("/po-drafts/{draft_id}/submission-log")
async def api_create_submission_log(draft_id: str, body: SubmissionLogIn):
    """Create a submission log entry for a PO draft.

    Captures the current vendor info and a snapshot of the BC export payload.
    Does NOT create BC records or modify ledger data.
    """
    import uuid as _uuid
    import json as json_mod

    if body.status not in SUBMISSION_STATUSES:
        raise HTTPException(status_code=422, detail=f"Invalid status. Use: {', '.join(SUBMISSION_STATUSES)}")

    db = get_db()
    doc = await db[PO_DRAFTS_COLL].find_one(
        {"po_draft_id": draft_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="PO draft not found")

    # Validate draft is exportable (same rules as bc-export)
    if doc.get("status") == "archived":
        raise HTTPException(status_code=422, detail="Cannot log submission for an archived draft")

    lines = doc.get("lines", [])
    if not lines:
        raise HTTPException(status_code=422, detail="PO draft has no lines")

    vendor_id = (doc.get("vendor_id") or "").strip()
    vendor_name = (doc.get("vendor_name") or "").strip()
    if not vendor_id or not vendor_name:
        raise HTTPException(
            status_code=422,
            detail="Vendor information is required. Assign a vendor first.",
        )

    # Build BC payload snapshot
    created_at = doc.get("created_at", "")
    document_date = created_at[:10] if len(created_at) >= 10 else datetime.now(timezone.utc).strftime("%Y-%m-%d")
    bc_lines = []
    for line in lines:
        item = (line.get("item") or "").strip()
        qty = line.get("qty", 0)
        if item and qty > 0:
            bc_lines.append({"itemNumber": item, "quantity": qty, "sourceReference": line.get("source", "")})

    payload_snapshot = {
        "poDraftId": doc["po_draft_id"],
        "vendor": {"vendorId": vendor_id, "vendorName": vendor_name},
        "documentDate": document_date,
        "source": "GPI_Hub_PO_Draft",
        "lines": bc_lines,
    }

    now = datetime.now(timezone.utc).isoformat()
    log_entry = {
        "submission_id": f"SUB-{_uuid.uuid4().hex[:8].upper()}",
        "po_draft_id": draft_id,
        "submitted_at": now,
        "submitted_by": None,
        "vendor_id": vendor_id,
        "vendor_name": vendor_name,
        "status": body.status,
        "notes": body.notes.strip(),
        "bc_payload_snapshot": payload_snapshot,
    }
    await db[PO_SUBMISSION_LOGS_COLL].insert_one(log_entry.copy())

    # Return without _id
    log_entry.pop("_id", None)
    return log_entry


@router.get("/po-drafts/{draft_id}/submission-log")
async def api_list_submission_logs(draft_id: str):
    """List all submission log entries for a PO draft, reverse chronological."""
    db = get_db()

    # Verify draft exists
    doc = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": draft_id}, {"_id": 0, "po_draft_id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="PO draft not found")

    cursor = db[PO_SUBMISSION_LOGS_COLL].find(
        {"po_draft_id": draft_id}, {"_id": 0}
    ).sort("submitted_at", -1)
    entries = await cursor.to_list(length=200)
    return {"po_draft_id": draft_id, "total": len(entries), "entries": entries}


@router.get("/po-drafts/{draft_id}/incoming-supply")
async def api_linked_incoming_supply(draft_id: str):
    """Return all incoming supply records linked to a PO draft."""
    db = get_db()
    doc = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": draft_id}, {"_id": 0, "po_draft_id": 1})
    if not doc:
        raise HTTPException(status_code=404, detail="PO draft not found")

    cursor = db["inv_incoming_supply"].find(
        {"source_reference": draft_id},
        {"_id": 0},
    ).sort("item", 1)
    records = await cursor.to_list(length=500)

    # Compute receipt summary
    received_count = sum(1 for r in records if r.get("status") == "received")
    ordered_count = sum(1 for r in records if r.get("status") == "ordered")
    total_qty = sum(r.get("incoming_qty", 0) for r in records)
    received_qty = sum(r.get("incoming_qty", 0) for r in records if r.get("status") == "received")

    return {
        "po_draft_id": draft_id,
        "total": len(records),
        "records": records,
        "receipt_summary": {
            "received_count": received_count,
            "ordered_count": ordered_count,
            "total_qty": total_qty,
            "received_qty": received_qty,
        },
    }


class BCReceiptLineIn(BaseModel):
    item: str = Field(..., min_length=1)
    qty_received: float = Field(..., gt=0)


class BCReceiptIn(BaseModel):
    received_lines: list[BCReceiptLineIn] = Field(..., min_items=1)
    receipt_notes: str = Field(default="", description="Notes about the receipt")


@router.post("/po-drafts/{draft_id}/bc-receipt")
async def api_bc_receipt_capture(draft_id: str, body: BCReceiptIn):
    """Record that a BC PO has been received, advancing linked incoming supply
    from ordered → received through the existing transition pipeline.

    Uses transition_supply_status which auto-creates receipt ledger movements.
    Does NOT call BC APIs or change balance formulas.
    """
    from services.inventory_so_integration import (
        transition_supply_status, DuplicateReceiptError,
    )

    db = get_db()
    doc = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": draft_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="PO draft not found")

    # Must have BC response status = created
    if doc.get("bc_response_status") != "created":
        raise HTTPException(
            status_code=422,
            detail=f"BC response status must be 'created' to capture receipt. Current: '{doc.get('bc_response_status', 'none')}'",
        )

    # Get linked supply records
    linked = await db["inv_incoming_supply"].find(
        {"source_reference": draft_id}, {"_id": 0}
    ).to_list(500)
    if not linked:
        raise HTTPException(status_code=422, detail="No linked incoming supply records found for this draft")

    now = datetime.now(timezone.utc).isoformat()
    results = []
    errors = []

    for line in body.received_lines:
        item = line.item.strip()
        qty = line.qty_received

        # Find matching linked supply for this item
        matching = [s for s in linked if s["item"] == item]
        if not matching:
            errors.append({"item": item, "error": "No linked incoming supply found for this item"})
            continue

        for supply_rec in matching:
            supply_id = supply_rec["id"]
            current_status = supply_rec["status"]
            ordered_qty = supply_rec.get("incoming_qty", 0)

            # Skip if already received or cancelled
            if current_status in ("received", "cancelled"):
                results.append({"item": item, "supply_id": supply_id, "status": "skipped", "reason": f"Already {current_status}"})
                continue

            # Must be ordered to receive
            if current_status != "ordered":
                errors.append({"item": item, "supply_id": supply_id, "error": f"Cannot receive: current status is '{current_status}', must be 'ordered'"})
                continue

            # Over-receipt check
            if qty > ordered_qty:
                errors.append({"item": item, "supply_id": supply_id, "error": f"Over-receipt: received {qty} > ordered {ordered_qty}"})
                continue

            # Partial receipt check — reject cleanly
            if qty < ordered_qty:
                errors.append({"item": item, "supply_id": supply_id, "error": f"Partial receipt not supported: received {qty} < ordered {ordered_qty}. Record full qty ({ordered_qty}) or adjust the incoming supply first."})
                continue

            # Full receipt — use existing transition pipeline
            try:
                result = await transition_supply_status(
                    db, supply_id=supply_id, new_status="received",
                    created_by="bc_receipt_capture",
                )
                # Add receipt trace fields
                await db["inv_incoming_supply"].update_one(
                    {"id": supply_id},
                    {"$set": {"bc_receipt_at": now, "bc_receipt_notes": body.receipt_notes.strip()}},
                )
                results.append({
                    "item": item,
                    "supply_id": supply_id,
                    "status": "received",
                    "qty": ordered_qty,
                    "receipt_movement_id": result.get("receipt_movement_id"),
                })
            except DuplicateReceiptError:
                results.append({"item": item, "supply_id": supply_id, "status": "skipped", "reason": "Already received"})
            except ValueError as e:
                errors.append({"item": item, "supply_id": supply_id, "error": str(e)})

    if errors and not results:
        raise HTTPException(status_code=422, detail={"message": "Receipt capture failed", "errors": errors})

    return {
        "po_draft_id": draft_id,
        "receipt_notes": body.receipt_notes.strip(),
        "results": results,
        "errors": errors,
        "total_received": sum(1 for r in results if r.get("status") == "received"),
        "total_skipped": sum(1 for r in results if r.get("status") == "skipped"),
        "total_errors": len(errors),
    }


@router.post("/po-drafts/{draft_id}/create-incoming-supply")
async def api_po_draft_create_incoming_supply(draft_id: str):
    """Convert PO draft lines into planned incoming supply records.

    Does NOT create ledger movements or ERP records. Creates incoming supply
    via the existing create_incoming pipeline so derive_balances picks up
    the planned quantities automatically.
    Duplicate protection: if the draft has already been converted, returns 409.
    """
    db = get_db()
    doc = await db[PO_DRAFTS_COLL].find_one(
        {"po_draft_id": draft_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="PO draft not found")

    if doc.get("status") == "archived":
        raise HTTPException(status_code=422, detail="Cannot convert an archived draft")

    if doc.get("po_type") == "drop_ship":
        raise HTTPException(status_code=422, detail="Drop-ship PO drafts do not create incoming supply. They are operational purchasing records only.")

    # Duplicate protection: check if already converted
    if doc.get("incoming_supply_created"):
        raise HTTPException(
            status_code=409,
            detail="This PO draft has already been converted to incoming supply",
        )

    lines = doc.get("lines", [])
    if not lines:
        raise HTTPException(status_code=422, detail="PO draft has no lines")

    customer_id = doc["customer_id"]
    rows_processed = 0
    rows_created = 0
    rows_skipped = 0
    created_ids = []
    messages = []

    for line in lines:
        rows_processed += 1
        item = line.get("item", "").strip()
        qty = line.get("qty", 0)

        if not item or qty <= 0:
            rows_skipped += 1
            messages.append({"item": item or "?", "status": "skipped", "reason": "Invalid item or qty"})
            continue

        # Check for existing incoming supply from this draft for this item
        existing = await db["inv_incoming_supply"].find_one(
            {"customer_id": customer_id, "item": item, "source_reference": draft_id},
            {"_id": 0, "id": 1},
        )
        if existing:
            rows_skipped += 1
            messages.append({"item": item, "status": "skipped", "reason": "Already converted", "supply_id": existing["id"]})
            continue

        supply = await create_incoming(
            db, customer_id,
            item=item,
            item_description="",
            warehouse="MAIN",
            ownership_type="customer_owned",
            incoming_qty=qty,
            unit_of_measure="units",
            eta="",
            source_reference=draft_id,
            notes=f"From PO draft {draft_id}",
            created_by="po_draft_conversion",
            status="planned",
        )
        # Store po_draft_id on the created supply record
        await db["inv_incoming_supply"].update_one(
            {"id": supply["id"]},
            {"$set": {"po_draft_id": draft_id}},
        )
        rows_created += 1
        created_ids.append(supply["id"])
        messages.append({"item": item, "status": "created", "supply_id": supply["id"], "qty": qty})

    # Mark draft as converted
    if rows_created > 0:
        now = datetime.now(timezone.utc).isoformat()
        await db[PO_DRAFTS_COLL].update_one(
            {"po_draft_id": draft_id},
            {"$set": {
                "incoming_supply_created": True,
                "incoming_supply_created_at": now,
                "incoming_supply_ids": created_ids,
            }},
        )
        # System activity
        await _create_activity(db, "po_draft", draft_id, "system",
                               f"Converted to incoming supply ({rows_created} lines)", "", "system")

    return {
        "po_draft_id": draft_id,
        "rows_processed": rows_processed,
        "rows_created": rows_created,
        "rows_skipped": rows_skipped,
        "created_supply_ids": created_ids,
        "messages": messages,
    }


# ═══════════════════════════════════════════════════════════════
# ITEM DETAIL
# ═══════════════════════════════════════════════════════════════


@router.get("/item-detail")
async def api_item_detail(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query(..., min_length=1, description="Item identifier"),
):
    """Return a complete operational picture for a single item.

    Reuses derive_balances, item settings, reorder logic, exception
    classification, and movement history pipelines.
    """
    db = get_db()
    balances = await derive_balances(db, customer_id, item=item)
    if not balances:
        raise HTTPException(status_code=404, detail=f"Item '{item}' not found in this workspace")

    # Aggregate across all warehouses/ownership for the item
    b = balances[0]
    is_short = b.get("is_short", False)
    is_low = b.get("is_low", False)
    status = "SHORT" if is_short else ("LOW" if is_low else "OK")

    balance = {
        "on_hand": b.get("on_hand", 0),
        "incoming": b.get("incoming", 0),
        "committed": b.get("committed", 0),
        "available": b.get("available", 0),
        "status": status,
        "warehouse": b.get("warehouse", ""),
        "ownership_type": b.get("ownership_type", ""),
        "unit_of_measure": b.get("unit_of_measure", ""),
        "item_description": b.get("item_description", ""),
    }

    # Item settings
    settings_doc = await db["inv_item_settings"].find_one(
        {"customer_id": customer_id, "item": item}, {"_id": 0}
    )
    settings = None
    if settings_doc:
        settings = {
            "reorder_threshold": settings_doc.get("reorder_threshold", 0),
            "safety_buffer": settings_doc.get("safety_buffer", 0),
            "notes": settings_doc.get("notes", ""),
        }

    # Reorder recommendation
    threshold = settings["reorder_threshold"] if settings else DEFAULT_REORDER_THRESHOLD
    buffer = settings["safety_buffer"] if settings else DEFAULT_SAFETY_BUFFER
    avail = balance["available"]
    is_reorder = avail <= threshold or is_short
    rec_qty = round(max(0, threshold - avail) + buffer, 4) if is_reorder else 0

    reorder = {
        "is_reorder_recommended": is_reorder,
        "recommended_qty": rec_qty,
        "reorder_threshold": threshold,
        "safety_buffer": buffer,
    }

    # Exception flags
    incoming = balance["incoming"]
    exceptions = {
        "short": is_short,
        "low": is_low,
        "reorder": is_reorder,
        "no_incoming": (is_short or is_low) and incoming == 0,
    }

    # Recent movement history (latest 10)
    history_data = await get_history(db, customer_id, item=item, limit=10)

    # Movement type summary
    type_summary = await item_audit_summary(db, customer_id, item)

    # Demand signal (only when committed > 0)
    committed = balance["committed"]
    demand = None
    supply_coverage = None
    if committed > 0:
        demand = {
            "total_open_order_qty": committed,
            "demand_gap": round(committed - balance["available"], 4),
        }
        cov = round(balance["on_hand"] + balance["incoming"] - committed, 4)
        supply_coverage = {
            "coverage": cov,
            "coverage_status": "covered" if cov >= 0 else "at_risk",
        }

    # Action center summary (reuse _compute_action_item)
    reorder_info_for_action = {"recommended_qty": rec_qty} if is_reorder else None
    action_item = _compute_action_item(b, reorder_info_for_action, committed)
    action_summary = None
    if action_item:
        action_summary = {
            "action_types": action_item["action_types"],
            "priority_score": action_item["priority_score"],
        }

    # Last PO draft for this item
    last_po_draft = await db[PO_DRAFTS_COLL].find_one(
        {"customer_id": customer_id, "lines.item": item},
        {"_id": 0, "po_draft_id": 1, "created_at": 1, "status": 1, "bc_po_number": 1, "bc_response_status": 1},
        sort=[("created_at", -1)],
    )

    return {
        "item": item,
        "customer_id": customer_id,
        "balance": balance,
        "settings": settings,
        "reorder": reorder,
        "exceptions": exceptions,
        "demand": demand,
        "supply_coverage": supply_coverage,
        "action_summary": action_summary,
        "last_po_draft": last_po_draft,
        "history_preview": history_data.get("movements", []),
        "history_total": history_data.get("total", 0),
        "type_summary": type_summary.get("movement_type_totals", {}),
    }


# ═══════════════════════════════════════════════════════════════
# INVENTORY SNAPSHOT
# ═══════════════════════════════════════════════════════════════

EXCEPTION_TYPES = {"short", "low", "reorder", "no_incoming"}


@router.get("/exceptions")
async def api_exceptions(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query("", description="Filter by item"),
    exception_type: str = Query("", description="Filter by exception type (short|low|reorder|no_incoming)"),
    limit: int = Query(500, ge=1, le=5000),
):
    """Return inventory items that need attention.

    Uses existing derive_balances and reorder recommendation logic.
    """
    db = get_db()
    balances = await derive_balances(db, customer_id, item=item or None)

    # Build reorder set (same logic as reorder-recommendations)
    settings_docs = await db["inv_item_settings"].find(
        {"customer_id": customer_id}, {"_id": 0}
    ).to_list(5000)
    settings_map = {s["item"]: s for s in settings_docs}

    reorder_map = {}
    for b in balances:
        avail = b.get("available", 0)
        is_short = b.get("is_short", False)
        s = settings_map.get(b["item"])
        threshold = s["reorder_threshold"] if s else DEFAULT_REORDER_THRESHOLD
        buffer = s["safety_buffer"] if s else DEFAULT_SAFETY_BUFFER
        if avail > threshold and not is_short:
            continue
        rec_qty = round(max(0, threshold - avail) + buffer, 4)
        reorder_map[f'{b["item"]}|{b.get("warehouse", "")}|{b.get("ownership_type", "")}'] = {
            "recommended_qty": rec_qty,
            "reorder_threshold": threshold,
            "safety_buffer": buffer,
        }

    # Classify exceptions
    rows = []
    short_count = low_count = reorder_count = no_incoming_count = 0

    filter_types = set()
    if exception_type:
        for t in exception_type.split(","):
            t = t.strip().lower()
            if t in EXCEPTION_TYPES:
                filter_types.add(t)

    for b in balances:
        exc_types = []
        key = f'{b["item"]}|{b.get("warehouse", "")}|{b.get("ownership_type", "")}'
        is_short = b.get("is_short", False)
        is_low = b.get("is_low", False)
        incoming = b.get("incoming", 0)

        if is_short:
            exc_types.append("short")
        if is_low:
            exc_types.append("low")
        if key in reorder_map:
            exc_types.append("reorder")
        if (is_short or is_low) and incoming == 0:
            exc_types.append("no_incoming")

        if not exc_types:
            continue

        # Count all exceptions (before filter)
        if "short" in exc_types:
            short_count += 1
        if "low" in exc_types:
            low_count += 1
        if "reorder" in exc_types:
            reorder_count += 1
        if "no_incoming" in exc_types:
            no_incoming_count += 1

        # Apply exception_type filter
        if filter_types and not filter_types.intersection(exc_types):
            continue

        status = "SHORT" if is_short else ("LOW" if is_low else "OK")
        row = {
            "item": b["item"],
            "item_description": b.get("item_description", ""),
            "warehouse": b.get("warehouse", ""),
            "ownership_type": b.get("ownership_type", ""),
            "on_hand": b.get("on_hand", 0),
            "incoming": incoming,
            "committed": b.get("committed", 0),
            "available": b.get("available", 0),
            "unit_of_measure": b.get("unit_of_measure", ""),
            "status": status,
            "exception_types": exc_types,
        }
        if key in reorder_map:
            row["recommended_qty"] = reorder_map[key]["recommended_qty"]
            row["reorder_threshold"] = reorder_map[key]["reorder_threshold"]
            row["safety_buffer"] = reorder_map[key]["safety_buffer"]

        rows.append(row)

    # Sort most critical first (available ascending)
    rows.sort(key=lambda r: r["available"])

    return {
        "total": len(rows[:limit]),
        "exception_summary": {
            "short_count": short_count,
            "low_count": low_count,
            "reorder_count": reorder_count,
            "no_incoming_count": no_incoming_count,
        },
        "exceptions": rows[:limit],
    }


async def _build_snapshot(db, customer_id: str, item: str = "", include_reorders: bool = True):
    """Build a read-only snapshot of current inventory state.

    Reuses derive_balances, dashboard summary logic, and reorder recommendations.
    """
    balances = await derive_balances(db, customer_id, item=item or None)

    # Summary metrics (same logic as dashboard-summary)
    total_items = len(set(b["item"] for b in balances))
    items_ok = items_low = items_short = 0
    total_on_hand = total_incoming = total_committed = total_available = 0.0

    for b in balances:
        total_on_hand += b.get("on_hand", 0)
        total_incoming += b.get("incoming", 0)
        total_committed += b.get("committed", 0)
        total_available += b.get("available", 0)
        if b.get("is_short"):
            items_short += 1
        elif b.get("is_low"):
            items_low += 1
        else:
            items_ok += 1

    # Item settings for reorder logic
    settings_docs = await db["inv_item_settings"].find(
        {"customer_id": customer_id}, {"_id": 0}
    ).to_list(5000)
    settings_map = {s["item"]: s for s in settings_docs}

    # Reorder count + optional reorder rows
    reorder_count = 0
    reorder_rows = []
    for b in balances:
        avail = b.get("available", 0)
        is_short = b.get("is_short", False)
        s = settings_map.get(b["item"])
        threshold = s["reorder_threshold"] if s else DEFAULT_REORDER_THRESHOLD
        buffer = s["safety_buffer"] if s else DEFAULT_SAFETY_BUFFER
        if avail > threshold and not is_short:
            continue
        reorder_count += 1
        if include_reorders:
            rec_qty = round(max(0, threshold - avail) + buffer, 4)
            reorder_rows.append({
                "item": b["item"],
                "warehouse": b.get("warehouse", "MAIN"),
                "available": avail,
                "status": "SHORT" if is_short else ("LOW" if b.get("is_low") else "OK"),
                "recommended_qty": rec_qty,
                "reorder_threshold": threshold,
                "safety_buffer": buffer,
            })

    # Clean balance rows for snapshot (strip internal flags)
    balance_rows = []
    for b in balances:
        status = "SHORT" if b.get("is_short") else ("LOW" if b.get("is_low") else "OK")
        balance_rows.append({
            "item": b["item"],
            "item_description": b.get("item_description", ""),
            "warehouse": b.get("warehouse", ""),
            "ownership_type": b.get("ownership_type", ""),
            "on_hand": b.get("on_hand", 0),
            "incoming": b.get("incoming", 0),
            "committed": b.get("committed", 0),
            "available": b.get("available", 0),
            "unit_of_measure": b.get("unit_of_measure", ""),
            "status": status,
        })

    snapshot = {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "context": {
            "customer_id": customer_id,
            "item_filter": item or None,
            "include_reorders": include_reorders,
        },
        "summary": {
            "total_items": total_items,
            "items_ok": items_ok,
            "items_low": items_low,
            "items_short": items_short,
            "total_on_hand": round(total_on_hand, 2),
            "total_incoming": round(total_incoming, 2),
            "total_committed": round(total_committed, 2),
            "total_available": round(total_available, 2),
            "total_reorder_recommendations": reorder_count,
        },
        "balances": balance_rows,
    }
    if include_reorders:
        snapshot["reorders"] = reorder_rows

    return snapshot


@router.get("/snapshot")
async def api_snapshot(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query("", description="Filter by item"),
    include_reorders: bool = Query(True, description="Include reorder recommendations"),
):
    """Generate a read-only inventory snapshot for the current workspace."""
    db = get_db()
    return await _build_snapshot(db, customer_id, item, include_reorders)


@router.get("/snapshot/export")
async def api_snapshot_export(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query("", description="Filter by item"),
    include_reorders: bool = Query(True, description="Include reorder recommendations"),
):
    """Download inventory snapshot as a JSON file."""
    from fastapi.responses import Response
    import json as json_mod

    db = get_db()
    cust = await get_customer(db, customer_id)
    cust_name = cust["name"] if cust else customer_id

    snapshot = await _build_snapshot(db, customer_id, item, include_reorders)

    safe_name = cust_name.replace(" ", "_").replace("/", "_")[:40]
    ts = datetime.now(timezone.utc).strftime("%Y%m%d_%H%M%S")
    filename = f"snapshot_{safe_name}_{ts}.json"

    return Response(
        content=json_mod.dumps(snapshot, indent=2),
        media_type="application/json",
        headers={"Content-Disposition": f'attachment; filename="{filename}"'},
    )


# ═══════════════════════════════════════════════════════════════
# REORDER RECOMMENDATIONS
# ═══════════════════════════════════════════════════════════════

DEFAULT_SAFETY_BUFFER = 10
DEFAULT_REORDER_THRESHOLD = 0


@router.get("/reorder-recommendations")
async def api_reorder_recommendations(
    customer_id: str = Query(..., description="Customer workspace ID"),
    item: str = Query("", description="Filter by item"),
    limit: int = Query(100, ge=1, le=500),
):
    """Generate reorder recommendations based on current derived balances.

    Uses per-item settings (reorder_threshold, safety_buffer) when configured.
    Falls back to defaults (threshold=0, buffer=10) when no settings exist.
    recommended_qty = max(0, reorder_threshold - available) + safety_buffer.
    """
    db = get_db()
    balances = await derive_balances(db, customer_id, item=item or None)

    # Load item settings for this workspace
    settings_docs = await db["inv_item_settings"].find(
        {"customer_id": customer_id}, {"_id": 0}
    ).to_list(5000)
    settings_map = {s["item"]: s for s in settings_docs}

    recs = []
    for b in balances:
        avail = b.get("available", 0)
        item_name = b["item"]
        is_short = b.get("is_short", False)

        s = settings_map.get(item_name)
        threshold = s["reorder_threshold"] if s else DEFAULT_REORDER_THRESHOLD
        buffer = s["safety_buffer"] if s else DEFAULT_SAFETY_BUFFER

        if avail > threshold and not is_short:
            continue

        rec_qty = round(max(0, threshold - avail) + buffer, 4)

        status = "SHORT" if is_short else ("LOW" if b.get("is_low") else "OK")
        recs.append({
            "item": item_name,
            "item_description": b.get("item_description", ""),
            "warehouse": b.get("warehouse", "MAIN"),
            "ownership_type": b.get("ownership_type", ""),
            "on_hand": b.get("on_hand", 0),
            "incoming": b.get("incoming", 0),
            "committed": b.get("committed", 0),
            "available": avail,
            "unit_of_measure": b.get("unit_of_measure", "units"),
            "status": status,
            "recommended_qty": rec_qty,
            "reorder_threshold": threshold,
            "safety_buffer": buffer,
            "has_settings": s is not None,
        })

    recs.sort(key=lambda r: r["available"])
    return {"recommendations": recs[:limit], "total": len(recs)}







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
    Drop-ship orders are rejected — they have no inventory commitments.
    """
    db = get_db()
    order_type = await _get_order_type(db, body.sales_order_id)
    if order_type == "drop_ship":
        raise HTTPException(
            status_code=422,
            detail="Drop-ship orders have no inventory commitments to reconcile.",
        )
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


# ═══════════════════════════════════════════════════════════════
# SO ORDER TYPE
# ═══════════════════════════════════════════════════════════════

VALID_ORDER_TYPES = ("warehouse", "drop_ship")


async def _get_order_type(db, sales_order_id: str) -> str:
    """Return the order type for a sales order. Default: warehouse."""
    doc = await db[SO_ORDER_TYPES_COLL].find_one(
        {"sales_order_id": sales_order_id}, {"_id": 0, "order_type": 1}
    )
    return doc["order_type"] if doc else "warehouse"


class OrderTypeIn(BaseModel):
    order_type: str = Field(..., description="warehouse or drop_ship")


@router.patch("/sales-orders/{sales_order_id}/order-type")
async def api_set_order_type(sales_order_id: str, body: OrderTypeIn):
    """Set or update the order type for a Sales Order."""
    if body.order_type not in VALID_ORDER_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid order_type. Use: {', '.join(VALID_ORDER_TYPES)}")

    db = get_db()

    # Verify SO exists via any movement
    sample = await db[MOVEMENTS_COLL].find_one(
        {"reference_id": sales_order_id, "movement_type": {"$in": ["order_commitment", "order_release"]}},
        {"_id": 0, "customer_id": 1},
    )

    # If switching TO drop_ship, check no remaining commitment
    if body.order_type == "drop_ship" and sample:
        pipeline = [
            {"$match": {"reference_id": sales_order_id, "movement_type": {"$in": ["order_commitment", "order_release"]}}},
            {"$group": {"_id": "$movement_type", "total": {"$sum": "$quantity_delta"}}},
        ]
        agg = await db[MOVEMENTS_COLL].aggregate(pipeline).to_list(5)
        committed = sum(abs(a["total"]) for a in agg if a["_id"] == "order_commitment")
        released = sum(abs(a["total"]) for a in agg if a["_id"] == "order_release")
        remaining = round(committed - released, 4)
        if remaining > 0:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot change to drop_ship: {remaining} qty still committed in warehouse. Release all commitments first.",
            )

    now = datetime.now(timezone.utc).isoformat()
    await db[SO_ORDER_TYPES_COLL].update_one(
        {"sales_order_id": sales_order_id},
        {"$set": {"sales_order_id": sales_order_id, "order_type": body.order_type, "set_at": now}},
        upsert=True,
    )

    return {"sales_order_id": sales_order_id, "order_type": body.order_type, "set_at": now}


@router.get("/sales-orders/{sales_order_id}/order-type")
async def api_get_order_type(sales_order_id: str):
    """Return the order type for a sales order."""
    db = get_db()
    order_type = await _get_order_type(db, sales_order_id)
    return {"sales_order_id": sales_order_id, "order_type": order_type}


# ═══════════════════════════════════════════════════════════════
# DROP-SHIP PO DRAFT GENERATION
# ═══════════════════════════════════════════════════════════════

DS_VENDOR_SHIPMENT_LOGS_COLL = "ds_vendor_shipment_logs"


class DSPODraftLineIn(BaseModel):
    item: str = Field(..., min_length=1)
    qty: float = Field(..., gt=0)
    description: str = Field(default="")


class DSPODraftIn(BaseModel):
    lines: list[DSPODraftLineIn] = Field(..., min_length=1)
    vendor_id: str = Field(default="")
    vendor_name: str = Field(default="")
    notes: str = Field(default="")


@router.post("/sales-orders/{sales_order_id}/generate-drop-ship-po-draft")
async def api_generate_drop_ship_po_draft(sales_order_id: str, body: DSPODraftIn):
    """Generate a PO draft linked to a Drop-Ship Sales Order.

    Validates SO exists and is drop_ship type.
    Creates a PO draft with po_type=drop_ship and sales_order_id link.
    Does NOT create incoming supply.
    """
    import uuid

    db = get_db()
    order_type = await _get_order_type(db, sales_order_id)
    if order_type != "drop_ship":
        raise HTTPException(
            status_code=422,
            detail=f"Sales order '{sales_order_id}' is type '{order_type}'. Only drop_ship orders can generate drop-ship PO drafts.",
        )

    now = datetime.now(timezone.utc)
    draft_id = f"PO-DS-{now.strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    lines = []
    for ln in body.lines:
        lines.append({
            "item": ln.item.strip(),
            "qty": ln.qty,
            "description": ln.description.strip(),
            "source": "drop_ship_so",
        })

    draft = {
        "po_draft_id": draft_id,
        "created_at": now.isoformat(),
        "sales_order_id": sales_order_id,
        "po_type": "drop_ship",
        "customer_id": "",
        "customer_name": "",
        "vendor_id": body.vendor_id.strip(),
        "vendor_name": body.vendor_name.strip(),
        "lines": lines,
        "source": "drop_ship_so",
        "status": "draft",
        "total_qty": sum(ln.qty for ln in body.lines),
        "total_lines": len(lines),
        "notes": body.notes.strip(),
    }

    await db[PO_DRAFTS_COLL].insert_one(draft.copy())
    draft.pop("_id", None)

    return draft


@router.get("/sales-orders/{sales_order_id}/drop-ship-po-drafts")
async def api_list_drop_ship_po_drafts(sales_order_id: str):
    """List PO drafts linked to a Drop-Ship Sales Order."""
    db = get_db()
    cursor = db[PO_DRAFTS_COLL].find(
        {"sales_order_id": sales_order_id, "po_type": "drop_ship"}, {"_id": 0}
    ).sort("created_at", -1)
    docs = await cursor.to_list(length=100)
    return {"sales_order_id": sales_order_id, "total": len(docs), "drafts": docs}


# ═══════════════════════════════════════════════════════════════
# DROP-SHIP VENDOR SHIPMENT CAPTURE
# ═══════════════════════════════════════════════════════════════


class DSVendorShipmentLineIn(BaseModel):
    item: str = Field(..., min_length=1)
    qty_shipped: float = Field(..., gt=0)


class DSVendorShipmentIn(BaseModel):
    shipped_lines: list[DSVendorShipmentLineIn] = Field(..., min_length=1)
    po_draft_id: str = Field(default="", description="Linked drop-ship PO draft ID")
    vendor_shipment_number: str = Field(default="", description="Vendor shipment document number")
    vendor_document_id: str = Field(default="", description="Vendor document ID")
    shipment_notes: str = Field(default="", description="Notes about the vendor shipment")


@router.post("/sales-orders/{sales_order_id}/drop-ship-vendor-shipment")
async def api_drop_ship_vendor_shipment(sales_order_id: str, body: DSVendorShipmentIn):
    """Record a vendor shipment for a Drop-Ship Sales Order.

    Traceability only. Does NOT release inventory, create ledger movements,
    or affect warehouse balances.
    """
    import uuid as _uuid

    db = get_db()
    order_type = await _get_order_type(db, sales_order_id)
    if order_type != "drop_ship":
        raise HTTPException(
            status_code=422,
            detail=f"Sales order '{sales_order_id}' is type '{order_type}'. Vendor shipment capture is only for drop_ship orders.",
        )

    # Validate linked PO draft if supplied
    if body.po_draft_id.strip():
        draft = await db[PO_DRAFTS_COLL].find_one(
            {"po_draft_id": body.po_draft_id.strip()}, {"_id": 0, "po_type": 1, "sales_order_id": 1}
        )
        if not draft:
            raise HTTPException(status_code=404, detail=f"PO draft '{body.po_draft_id}' not found")
        if draft.get("po_type") != "drop_ship":
            raise HTTPException(status_code=422, detail="Linked PO draft is not a drop-ship draft")
        if draft.get("sales_order_id") != sales_order_id:
            raise HTTPException(status_code=422, detail="PO draft is not linked to this sales order")

    now = datetime.now(timezone.utc).isoformat()
    results = []
    for line in body.shipped_lines:
        results.append({
            "item": line.item.strip(),
            "qty_shipped": line.qty_shipped,
            "status": "recorded",
            "note": "Vendor shipped directly to customer (drop-ship)",
        })

    log_entry = {
        "vendor_shipment_id": f"VSH-{_uuid.uuid4().hex[:8].upper()}",
        "sales_order_id": sales_order_id,
        "po_draft_id": body.po_draft_id.strip(),
        "vendor_shipment_number": body.vendor_shipment_number.strip(),
        "vendor_document_id": body.vendor_document_id.strip(),
        "shipped_at": now,
        "shipment_notes": body.shipment_notes.strip(),
        "shipped_lines": [{"item": l.item.strip(), "qty_shipped": l.qty_shipped} for l in body.shipped_lines],
        "results": results,
    }
    await db[DS_VENDOR_SHIPMENT_LOGS_COLL].insert_one(log_entry.copy())
    log_entry.pop("_id", None)

    # System activity
    await _create_activity(db, "sales_order", sales_order_id, "shipment",
                           f"Vendor shipment recorded: {body.vendor_shipment_number.strip()}", "", "system",
                           {"po_draft_id": body.po_draft_id.strip()})

    return {
        "vendor_shipment_number": body.vendor_shipment_number.strip(),
        "total_recorded": len(results),
        "results": results,
    }


@router.get("/sales-orders/{sales_order_id}/drop-ship-vendor-shipment-log")
async def api_list_ds_vendor_shipment_logs(sales_order_id: str):
    """List drop-ship vendor shipment log entries for a sales order."""
    db = get_db()
    cursor = db[DS_VENDOR_SHIPMENT_LOGS_COLL].find(
        {"sales_order_id": sales_order_id}, {"_id": 0}
    ).sort("shipped_at", -1)
    entries = await cursor.to_list(length=200)
    return {"sales_order_id": sales_order_id, "total": len(entries), "entries": entries}


# ═══════════════════════════════════════════════════════════════
# BC SHIPMENT CAPTURE
# ═══════════════════════════════════════════════════════════════

BC_SHIPMENT_LOGS_COLL = "bc_shipment_logs"
BC_INVOICE_LOGS_COLL = "bc_invoice_logs"
SO_ORDER_TYPES_COLL = "so_order_types"


class ShipmentLineIn(BaseModel):
    item: str = Field(..., min_length=1)
    qty_shipped: float = Field(..., gt=0)


class BCShipmentIn(BaseModel):
    shipped_lines: list[ShipmentLineIn] = Field(..., min_items=1)
    bc_shipment_number: str = Field(default="", description="BC shipment document number")
    bc_document_id: str = Field(default="", description="BC document ID")
    shipment_notes: str = Field(default="", description="Notes about the shipment")


@router.post("/sales-orders/{sales_order_id}/bc-shipment")
async def api_bc_shipment_capture(sales_order_id: str, body: BCShipmentIn):
    """Record that a BC Sales Order has been shipped.

    For warehouse orders: uses release_order_commitments to clear inventory.
    For drop_ship orders: records shipment without inventory effects.
    """
    import uuid as _uuid

    db = get_db()
    order_type = await _get_order_type(db, sales_order_id)
    now = datetime.now(timezone.utc).isoformat()
    results = []
    errors = []
    workspace_id = ""

    if order_type == "drop_ship":
        # Drop-ship: record shipment without inventory release
        for line in body.shipped_lines:
            results.append({"item": line.item.strip(), "status": "recorded", "qty_shipped": line.qty_shipped, "note": "Drop-ship: no warehouse release"})
    else:
        # Warehouse: use existing release pipeline
        from services.inventory_so_integration import release_order_commitments

        commit_pipeline = [
            {"$match": {"movement_type": {"$in": ["order_commitment", "order_release"]}, "reference_id": sales_order_id}},
            {"$group": {"_id": {"item": "$item", "mt": "$movement_type"}, "total": {"$sum": "$quantity_delta"}, "cust": {"$first": "$customer_id"}}},
        ]
        raw = await db[MOVEMENTS_COLL].aggregate(commit_pipeline).to_list(500)
        if not raw:
            raise HTTPException(status_code=404, detail=f"No order commitments found for warehouse sales order '{sales_order_id}'")

        commitments = {}
        releases = {}
        for r in raw:
            it, mt = r["_id"]["item"], r["_id"]["mt"]
            if not workspace_id:
                workspace_id = r["cust"]
            if mt == "order_commitment":
                commitments[it] = commitments.get(it, 0) + abs(r["total"])
            else:
                releases[it] = releases.get(it, 0) + abs(r["total"])

        net_committed = {}
        for it in set(list(commitments.keys()) + list(releases.keys())):
            net = round(commitments.get(it, 0) - releases.get(it, 0), 4)
            if net > 0:
                net_committed[it] = net

        release_lines = []
        for line in body.shipped_lines:
            item, qty = line.item.strip(), line.qty_shipped
            outstanding = net_committed.get(item, 0)
            if outstanding <= 0:
                results.append({"item": item, "status": "skipped", "reason": "No outstanding commitment (already fully released)"})
                continue
            if qty > outstanding:
                errors.append({"item": item, "error": f"Over-shipment: shipped {qty} > outstanding committed {outstanding}"})
                continue
            release_lines.append({"item": item, "qty": qty})

        if errors and not release_lines:
            raise HTTPException(status_code=422, detail={"message": "Shipment capture failed", "errors": errors})

        if release_lines:
            try:
                release_result = await release_order_commitments(db, sales_order_id=sales_order_id, lines=release_lines, created_by="bc_shipment_capture")
                for i, rl in enumerate(release_lines):
                    results.append({"item": rl["item"], "status": "released", "qty_shipped": rl["qty"],
                        "movement_id": release_result["movement_ids"][i] if i < len(release_result.get("movement_ids", [])) else None})
            except ValueError as e:
                raise HTTPException(status_code=422, detail=str(e))

    # Create shipment log entry
    log_entry = {
        "shipment_id": f"SHP-{_uuid.uuid4().hex[:8].upper()}",
        "sales_order_id": sales_order_id, "customer_id": workspace_id, "order_type": order_type,
        "bc_shipment_number": body.bc_shipment_number.strip(), "bc_document_id": body.bc_document_id.strip(),
        "shipped_at": now, "shipment_notes": body.shipment_notes.strip(),
        "shipped_lines": [{"item": l.item.strip(), "qty_shipped": l.qty_shipped} for l in body.shipped_lines],
        "results": results, "errors": errors,
    }
    await db[BC_SHIPMENT_LOGS_COLL].insert_one(log_entry.copy())
    log_entry.pop("_id", None)

    # System activity
    await _create_activity(db, "sales_order", sales_order_id, "shipment",
                           f"Shipment recorded: {body.bc_shipment_number.strip()}", "", "system",
                           {"order_type": order_type})

    return {
        "sales_order_id": sales_order_id, "order_type": order_type, "shipment_id": log_entry["shipment_id"],
        "bc_shipment_number": body.bc_shipment_number.strip(),
        "total_released": sum(1 for r in results if r.get("status") == "released"),
        "total_recorded": sum(1 for r in results if r.get("status") == "recorded"),
        "total_skipped": sum(1 for r in results if r.get("status") == "skipped"),
        "total_errors": len(errors), "results": results, "errors": errors,
    }


@router.get("/sales-orders/{sales_order_id}/shipment-log")
async def api_list_shipment_logs(sales_order_id: str):
    """List all shipment log entries for a sales order, reverse chronological."""
    db = get_db()
    cursor = db[BC_SHIPMENT_LOGS_COLL].find(
        {"sales_order_id": sales_order_id}, {"_id": 0}
    ).sort("shipped_at", -1)
    entries = await cursor.to_list(length=200)
    return {"sales_order_id": sales_order_id, "total": len(entries), "entries": entries}


# ═══════════════════════════════════════════════════════════════
# BC INVOICE CAPTURE
# ═══════════════════════════════════════════════════════════════

class BCInvoiceIn(BaseModel):
    bc_invoice_number: str = Field(..., min_length=1, description="BC invoice number")
    bc_document_id: str = Field(default="", description="BC document ID")
    invoice_date: str = Field(default="", description="Invoice date YYYY-MM-DD")
    invoice_notes: str = Field(default="", description="Notes")


@router.post("/sales-orders/{sales_order_id}/bc-invoice")
async def api_bc_invoice_capture(sales_order_id: str, body: BCInvoiceIn):
    """Record that a shipped Sales Order has been invoiced in BC.

    Informational only. Does NOT create ledger movements,
    accounting entries, or call BC APIs.
    For drop_ship orders: only requires shipment log (no commitment checks).
    """
    import uuid as _uuid

    db = get_db()
    order_type = await _get_order_type(db, sales_order_id)
    customer_id = ""

    if order_type == "drop_ship":
        # Drop-ship: verify shipment exists (BC shipment or vendor shipment), no commitment checks
        bc_ship_count = await db[BC_SHIPMENT_LOGS_COLL].count_documents({"sales_order_id": sales_order_id})
        ds_ship_count = await db[DS_VENDOR_SHIPMENT_LOGS_COLL].count_documents({"sales_order_id": sales_order_id})
        if bc_ship_count == 0 and ds_ship_count == 0:
            raise HTTPException(status_code=422, detail="No shipment activity recorded. Record a BC shipment or vendor shipment before invoicing.")
        # Try to find customer_id from shipment logs
        ship_log = await db[BC_SHIPMENT_LOGS_COLL].find_one(
            {"sales_order_id": sales_order_id}, {"_id": 0, "customer_id": 1}
        )
        customer_id = ship_log.get("customer_id", "") if ship_log else ""
    else:
        # Warehouse: verify SO exists via commitments
        sample = await db[MOVEMENTS_COLL].find_one(
            {"movement_type": "order_commitment", "reference_id": sales_order_id},
            {"_id": 0, "customer_id": 1},
        )
        if not sample:
            raise HTTPException(status_code=404, detail=f"No order commitments found for '{sales_order_id}'")
        customer_id = sample["customer_id"]

        # Check remaining committed qty — must be fully released to invoice
        pipeline = [
            {"$match": {"reference_id": sales_order_id, "movement_type": {"$in": ["order_commitment", "order_release"]}}},
            {"$group": {"_id": "$movement_type", "total": {"$sum": "$quantity_delta"}}},
        ]
        agg = await db[MOVEMENTS_COLL].aggregate(pipeline).to_list(5)
        committed = 0
        released = 0
        for a in agg:
            if a["_id"] == "order_commitment":
                committed = abs(a["total"])
            elif a["_id"] == "order_release":
                released = abs(a["total"])
        remaining = round(committed - released, 4)

        if remaining > 0:
            raise HTTPException(
                status_code=422,
                detail=f"Cannot invoice: {remaining} qty still committed. Ship all committed quantity first.",
            )

        # Verify shipment activity exists
        shipment_count = await db[BC_SHIPMENT_LOGS_COLL].count_documents({"sales_order_id": sales_order_id})
        if shipment_count == 0:
            raise HTTPException(status_code=422, detail="No shipment activity recorded. Record shipment before invoicing.")

    now = datetime.now(timezone.utc).isoformat()
    log_entry = {
        "invoice_log_id": f"INV-{_uuid.uuid4().hex[:8].upper()}",
        "sales_order_id": sales_order_id,
        "customer_id": customer_id,
        "order_type": order_type,
        "bc_invoice_number": body.bc_invoice_number.strip(),
        "bc_document_id": body.bc_document_id.strip(),
        "invoice_date": body.invoice_date.strip() or now[:10],
        "invoice_notes": body.invoice_notes.strip(),
        "captured_at": now,
    }
    await db[BC_INVOICE_LOGS_COLL].insert_one(log_entry.copy())
    log_entry.pop("_id", None)

    # System activity
    await _create_activity(db, "sales_order", sales_order_id, "invoice",
                           f"Invoice recorded: {body.bc_invoice_number.strip()}", "", "system")

    return log_entry


@router.get("/sales-orders/{sales_order_id}/invoice-log")
async def api_list_invoice_logs(sales_order_id: str):
    """List all invoice log entries for a sales order, reverse chronological."""
    db = get_db()
    cursor = db[BC_INVOICE_LOGS_COLL].find(
        {"sales_order_id": sales_order_id}, {"_id": 0}
    ).sort("captured_at", -1)
    entries = await cursor.to_list(length=200)
    return {"sales_order_id": sales_order_id, "total": len(entries), "entries": entries}


@router.get("/sales-orders/{sales_order_id}/summary")
async def api_sales_order_summary(sales_order_id: str):
    """Return a summary of commitment/release status for a sales order.

    For drop_ship orders, returns shipment/invoice logs only (no commitment data).
    """
    from services.inventory_so_integration import _get_net_committed

    db = get_db()
    order_type = await _get_order_type(db, sales_order_id)

    if order_type == "drop_ship":
        # Drop-ship: no commitment data, enriched with PO draft + vendor shipment info
        latest_shipment = await db[BC_SHIPMENT_LOGS_COLL].find_one(
            {"sales_order_id": sales_order_id}, {"_id": 0},
            sort=[("shipped_at", -1)],
        )
        latest_invoice = await db[BC_INVOICE_LOGS_COLL].find_one(
            {"sales_order_id": sales_order_id}, {"_id": 0},
            sort=[("captured_at", -1)],
        )
        bc_shipment_count = await db[BC_SHIPMENT_LOGS_COLL].count_documents({"sales_order_id": sales_order_id})
        invoice_count = await db[BC_INVOICE_LOGS_COLL].count_documents({"sales_order_id": sales_order_id})

        # Drop-ship PO draft info
        ds_drafts = await db[PO_DRAFTS_COLL].find(
            {"sales_order_id": sales_order_id, "po_type": "drop_ship"}, {"_id": 0}
        ).sort("created_at", -1).to_list(100)
        latest_ds_draft = ds_drafts[0] if ds_drafts else None

        # Drop-ship vendor shipment info
        latest_vendor_shipment = await db[DS_VENDOR_SHIPMENT_LOGS_COLL].find_one(
            {"sales_order_id": sales_order_id}, {"_id": 0},
            sort=[("shipped_at", -1)],
        )
        ds_vendor_shipment_count = await db[DS_VENDOR_SHIPMENT_LOGS_COLL].count_documents({"sales_order_id": sales_order_id})

        has_shipment = bc_shipment_count > 0 or ds_vendor_shipment_count > 0
        has_invoice = invoice_count > 0
        if has_invoice and has_shipment:
            operational_status = "complete"
        elif has_shipment:
            operational_status = "shipped"
        elif latest_ds_draft:
            operational_status = "po_drafted"
        else:
            operational_status = "pending"
        customer_id = (latest_shipment or {}).get("customer_id", "")
        ds_summary = {
            "sales_order_id": sales_order_id,
            "customer_id": customer_id,
            "order_type": order_type,
            "total_committed_qty": 0,
            "total_released_qty": 0,
            "total_remaining_committed_qty": 0,
            "latest_bc_shipment_number": latest_shipment.get("bc_shipment_number", "") if latest_shipment else "",
            "latest_bc_shipped_at": latest_shipment.get("shipped_at", "") if latest_shipment else "",
            "latest_bc_invoice_number": latest_invoice.get("bc_invoice_number", "") if latest_invoice else "",
            "latest_bc_invoice_at": latest_invoice.get("captured_at", "") if latest_invoice else "",
            "operational_status": operational_status,
            "is_fulfillment_complete": operational_status == "complete",
            "lines": [],
            # Drop-ship enrichment
            "linked_drop_ship_po_draft_count": len(ds_drafts),
            "linked_drop_ship_po_draft_id": latest_ds_draft["po_draft_id"] if latest_ds_draft else "",
            "latest_drop_ship_po_status": latest_ds_draft.get("bc_response_status", latest_ds_draft.get("status", "")) if latest_ds_draft else "",
            "latest_vendor_shipment_number": latest_vendor_shipment.get("vendor_shipment_number", "") if latest_vendor_shipment else "",
            "latest_vendor_shipped_at": latest_vendor_shipment.get("shipped_at", "") if latest_vendor_shipment else "",
        }
        # Enrich with document linkage + checklist
        doc_count, docs_by_type, _ = await _get_document_links_summary(db, "sales_order", sales_order_id)
        checklist_items, checklist_complete = await _derive_so_checklist(db, sales_order_id, order_type, doc_count, docs_by_type)
        ds_summary["linked_document_count"] = doc_count
        ds_summary["linked_documents_by_type"] = docs_by_type
        ds_summary["process_checklist"] = checklist_items
        ds_summary["checklist_complete"] = checklist_complete
        # Approval enrichment
        appr = await _get_approval_enrichment(db, "sales_order", sales_order_id)
        ds_summary.update(appr)
        # Escalation enrichment
        esc_enrich = await _get_escalation_enrichment(db, "sales_order", sales_order_id)
        ds_summary.update(esc_enrich)
        # Assignment enrichment
        asgn_enrich = await _get_assignment_enrichment(db, "sales_order", sales_order_id)
        ds_summary.update(asgn_enrich)
        # Activity enrichment
        act_enrich = await _get_activity_enrichment(db, "sales_order", sales_order_id)
        ds_summary.update(act_enrich)
        return ds_summary

    # Warehouse orders: existing behavior
    sample = await db[MOVEMENTS_COLL].find_one(
        {"movement_type": "order_commitment", "reference_id": sales_order_id},
        {"_id": 0, "customer_id": 1},
    )
    if not sample:
        raise HTTPException(status_code=404, detail=f"No order commitments found for '{sales_order_id}'")

    workspace_id = sample["customer_id"]

    # Get all commitment and release movements
    pipeline = [
        {"$match": {"reference_id": sales_order_id, "movement_type": {"$in": ["order_commitment", "order_release"]}}},
        {"$group": {
            "_id": {"item": "$item", "mt": "$movement_type"},
            "total": {"$sum": "$quantity_delta"},
            "warehouse": {"$first": "$warehouse"},
            "uom": {"$first": "$unit_of_measure"},
            "desc": {"$first": "$item_description"},
        }},
    ]
    raw = await db[MOVEMENTS_COLL].aggregate(pipeline).to_list(500)

    items = {}
    for r in raw:
        it = r["_id"]["item"]
        mt = r["_id"]["mt"]
        if it not in items:
            items[it] = {"item": it, "item_description": r["desc"], "warehouse": r["warehouse"], "unit_of_measure": r["uom"], "committed_qty": 0, "released_qty": 0}
        if mt == "order_commitment":
            items[it]["committed_qty"] = abs(r["total"])
        else:
            items[it]["released_qty"] = abs(r["total"])

    lines = []
    for it, v in items.items():
        v["remaining_committed_qty"] = round(v["committed_qty"] - v["released_qty"], 4)
        lines.append(v)
    lines.sort(key=lambda x: x["item"])

    total_committed = sum(l["committed_qty"] for l in lines)
    total_released = sum(l["released_qty"] for l in lines)
    total_remaining = sum(l["remaining_committed_qty"] for l in lines)

    # Latest shipment info
    latest_shipment = await db[BC_SHIPMENT_LOGS_COLL].find_one(
        {"sales_order_id": sales_order_id}, {"_id": 0},
        sort=[("shipped_at", -1)],
    )

    # Latest invoice info
    latest_invoice = await db[BC_INVOICE_LOGS_COLL].find_one(
        {"sales_order_id": sales_order_id}, {"_id": 0},
        sort=[("captured_at", -1)],
    )
    invoice_count = await db[BC_INVOICE_LOGS_COLL].count_documents({"sales_order_id": sales_order_id})
    shipment_count = await db[BC_SHIPMENT_LOGS_COLL].count_documents({"sales_order_id": sales_order_id})

    # Derive operational_status
    is_fully_released = total_remaining <= 0
    has_shipment = shipment_count > 0
    has_invoice = invoice_count > 0
    if has_invoice and is_fully_released:
        operational_status = "complete"
    elif has_shipment and is_fully_released:
        operational_status = "shipped"
    elif has_shipment:
        operational_status = "partially_shipped"
    elif total_released > 0:
        operational_status = "partially_released"
    else:
        operational_status = "committed"

    wh_summary = {
        "sales_order_id": sales_order_id,
        "customer_id": workspace_id,
        "order_type": "warehouse",
        "total_committed_qty": total_committed,
        "total_released_qty": total_released,
        "total_remaining_committed_qty": total_remaining,
        "latest_bc_shipment_number": latest_shipment.get("bc_shipment_number", "") if latest_shipment else "",
        "latest_bc_shipped_at": latest_shipment.get("shipped_at", "") if latest_shipment else "",
        "latest_bc_invoice_number": latest_invoice.get("bc_invoice_number", "") if latest_invoice else "",
        "latest_bc_invoice_at": latest_invoice.get("captured_at", "") if latest_invoice else "",
        "operational_status": operational_status,
        "is_fulfillment_complete": operational_status == "complete",
        "lines": lines,
    }
    # Enrich with document linkage + checklist
    doc_count, docs_by_type, _ = await _get_document_links_summary(db, "sales_order", sales_order_id)
    checklist_items, checklist_complete = await _derive_so_checklist(db, sales_order_id, "warehouse", doc_count, docs_by_type)
    wh_summary["linked_document_count"] = doc_count
    wh_summary["linked_documents_by_type"] = docs_by_type
    wh_summary["process_checklist"] = checklist_items
    wh_summary["checklist_complete"] = checklist_complete
    # Approval enrichment
    appr = await _get_approval_enrichment(db, "sales_order", sales_order_id)
    wh_summary.update(appr)
    # Escalation enrichment
    esc_enrich = await _get_escalation_enrichment(db, "sales_order", sales_order_id)
    wh_summary.update(esc_enrich)
    # Assignment enrichment
    asgn_enrich = await _get_assignment_enrichment(db, "sales_order", sales_order_id)
    wh_summary.update(asgn_enrich)
    # Activity enrichment
    act_enrich = await _get_activity_enrichment(db, "sales_order", sales_order_id)
    wh_summary.update(act_enrich)
    return wh_summary


# ═══════════════════════════════════════════════════════════════
# DOCUMENT LINKAGE & PROCESS CHECKLIST
# ═══════════════════════════════════════════════════════════════

DOCUMENT_LINKS_COLL = "document_links"
VALID_ENTITY_TYPES = ("sales_order", "po_draft")
VALID_DOCUMENT_TYPES = ("customer_po", "warehouse_agreement", "approval_backup", "vendor_po_support", "other")


class DocumentLinkIn(BaseModel):
    entity_type: str = Field(..., description="sales_order or po_draft")
    entity_id: str = Field(..., min_length=1)
    document_type: str = Field(..., description="customer_po, warehouse_agreement, approval_backup, vendor_po_support, other")
    document_name: str = Field(..., min_length=1)
    document_url: str = Field(default="")
    notes: str = Field(default="")


@router.post("/document-links")
async def api_create_document_link(body: DocumentLinkIn):
    """Create a document linkage record for a Sales Order or PO Draft."""
    import uuid as _uuid

    if body.entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid entity_type '{body.entity_type}'. Must be one of: {VALID_ENTITY_TYPES}")
    if body.document_type not in VALID_DOCUMENT_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid document_type '{body.document_type}'. Must be one of: {VALID_DOCUMENT_TYPES}")

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    doc = {
        "document_link_id": f"DOCL-{_uuid.uuid4().hex[:8].upper()}",
        "entity_type": body.entity_type,
        "entity_id": body.entity_id.strip(),
        "document_type": body.document_type,
        "document_name": body.document_name.strip(),
        "document_url": body.document_url.strip(),
        "uploaded_at": now,
        "uploaded_by": None,
        "notes": body.notes.strip(),
    }
    await db[DOCUMENT_LINKS_COLL].insert_one(doc.copy())
    doc.pop("_id", None)
    # System activity
    await _create_activity(db, body.entity_type, body.entity_id.strip(), "document",
                           f"Document linked: {body.document_name.strip()}", "", "system",
                           {"document_type": body.document_type})
    return doc


@router.get("/document-links")
async def api_list_document_links(entity_type: str, entity_id: str):
    """List document links for a given entity."""
    if entity_type not in VALID_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid entity_type '{entity_type}'.")
    db = get_db()
    cursor = db[DOCUMENT_LINKS_COLL].find(
        {"entity_type": entity_type, "entity_id": entity_id}, {"_id": 0}
    ).sort("uploaded_at", -1)
    docs = await cursor.to_list(length=200)
    return {"entity_type": entity_type, "entity_id": entity_id, "total": len(docs), "documents": docs}


@router.delete("/document-links/{document_link_id}")
async def api_delete_document_link(document_link_id: str):
    """Remove a document linkage record."""
    db = get_db()
    existing = await db[DOCUMENT_LINKS_COLL].find_one({"document_link_id": document_link_id}, {"_id": 0})
    result = await db[DOCUMENT_LINKS_COLL].delete_one({"document_link_id": document_link_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Document link '{document_link_id}' not found")
    if existing:
        await _create_activity(db, existing["entity_type"], existing["entity_id"], "document",
                               f"Document removed: {existing.get('document_name', document_link_id)}", "", "system")
    return {"deleted": document_link_id}


async def _get_document_links_summary(db, entity_type: str, entity_id: str):
    """Helper: return doc link count and by-type summary."""
    cursor = db[DOCUMENT_LINKS_COLL].find(
        {"entity_type": entity_type, "entity_id": entity_id}, {"_id": 0}
    ).sort("uploaded_at", -1)
    docs = await cursor.to_list(length=200)
    by_type = {}
    for d in docs:
        dt = d["document_type"]
        by_type[dt] = by_type.get(dt, 0) + 1
    return len(docs), by_type, docs


async def _derive_so_checklist(db, sales_order_id: str, order_type: str, doc_count: int, docs_by_type: dict):
    """Derive process checklist for a Sales Order."""
    items = []

    # Common: customer PO attached
    has_customer_po = docs_by_type.get("customer_po", 0) > 0
    items.append({"key": "customer_po_attached", "label": "Customer PO attached", "satisfied": has_customer_po})

    if order_type == "warehouse":
        # Warehouse: approval requested + granted + warehouse agreement
        approval = await _get_latest_approval(db, "sales_order", sales_order_id)
        items.append({"key": "approval_requested", "label": "Approval requested", "satisfied": approval is not None})
        items.append({"key": "approval_granted", "label": "Approval granted", "satisfied": approval is not None and approval.get("approval_status") == "approved"})
        has_agreement = docs_by_type.get("warehouse_agreement", 0) > 0
        items.append({"key": "warehouse_agreement", "label": "Warehouse agreement attached", "satisfied": has_agreement})
    else:
        # Drop-ship: DS PO draft created + approval granted
        ds_draft_count = await db[PO_DRAFTS_COLL].count_documents(
            {"sales_order_id": sales_order_id, "po_type": "drop_ship"}
        )
        items.append({"key": "ds_po_draft_created", "label": "Drop-Ship PO draft created", "satisfied": ds_draft_count > 0})
        approval = await _get_latest_approval(db, "sales_order", sales_order_id)
        items.append({"key": "approval_granted", "label": "Approval granted", "satisfied": approval is not None and approval.get("approval_status") == "approved"})

    all_satisfied = all(i["satisfied"] for i in items)
    return items, all_satisfied


def _derive_po_draft_checklist(draft: dict, doc_count: int, docs_by_type: dict, approval=None):
    """Derive process checklist for a PO Draft."""
    items = []

    # Vendor assigned
    has_vendor = bool(draft.get("vendor_name") or draft.get("vendor_id"))
    items.append({"key": "vendor_assigned", "label": "Vendor assigned", "satisfied": has_vendor})

    # Export-ready for BC (has lines and vendor)
    has_lines = len(draft.get("lines", [])) > 0
    export_ready = has_vendor and has_lines
    items.append({"key": "export_ready", "label": "Export-ready for BC", "satisfied": export_ready})

    # Approval granted
    items.append({"key": "approval_granted", "label": "Approval granted", "satisfied": approval is not None and approval.get("approval_status") == "approved"})

    all_satisfied = all(i["satisfied"] for i in items)
    return items, all_satisfied


@router.get("/document-links/checklist/sales-order/{sales_order_id}")
async def api_so_checklist(sales_order_id: str):
    """Return derived process checklist for a Sales Order."""
    db = get_db()
    order_type = await _get_order_type(db, sales_order_id)
    doc_count, docs_by_type, _ = await _get_document_links_summary(db, "sales_order", sales_order_id)
    items, all_satisfied = await _derive_so_checklist(db, sales_order_id, order_type, doc_count, docs_by_type)
    return {
        "sales_order_id": sales_order_id,
        "order_type": order_type,
        "linked_document_count": doc_count,
        "linked_documents_by_type": docs_by_type,
        "process_checklist": items,
        "checklist_complete": all_satisfied,
    }


@router.get("/document-links/checklist/po-draft/{po_draft_id}")
async def api_po_draft_checklist(po_draft_id: str):
    """Return derived process checklist for a PO Draft."""
    db = get_db()
    draft = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": po_draft_id}, {"_id": 0})
    if not draft:
        raise HTTPException(status_code=404, detail=f"PO Draft '{po_draft_id}' not found")
    doc_count, docs_by_type, _ = await _get_document_links_summary(db, "po_draft", po_draft_id)
    po_approval = await _get_latest_approval(db, "po_draft", po_draft_id)
    items, all_satisfied = _derive_po_draft_checklist(draft, doc_count, docs_by_type, approval=po_approval)
    return {
        "po_draft_id": po_draft_id,
        "linked_document_count": doc_count,
        "linked_documents_by_type": docs_by_type,
        "process_checklist": items,
        "checklist_complete": all_satisfied,
    }


# ═══════════════════════════════════════════════════════════════
# APPROVAL WORKFLOW TRACKING
# ═══════════════════════════════════════════════════════════════

APPROVAL_LOGS_COLL = "approval_logs"
VALID_APPROVAL_ENTITY_TYPES = ("sales_order", "po_draft")
VALID_APPROVAL_TYPES = ("sales_order", "purchase_order")
VALID_APPROVAL_STATUSES = ("pending", "approved", "rejected")


class ApprovalRequestIn(BaseModel):
    entity_type: str = Field(...)
    entity_id: str = Field(..., min_length=1)
    approval_type: str = Field(...)
    requested_by: str = Field(default="")
    notes: str = Field(default="")


class ApprovalDecisionIn(BaseModel):
    approval_status: str = Field(...)
    approved_by: str = Field(default="")
    notes: str = Field(default="")


async def _get_latest_approval(db, entity_type: str, entity_id: str):
    """Return the latest approval record for an entity, or None."""
    doc = await db[APPROVAL_LOGS_COLL].find_one(
        {"entity_type": entity_type, "entity_id": entity_id},
        {"_id": 0},
        sort=[("requested_at", -1)],
    )
    return doc


async def _get_approval_enrichment(db, entity_type: str, entity_id: str):
    """Return approval enrichment fields for summary/detail responses."""
    latest = await _get_latest_approval(db, entity_type, entity_id)
    count = await db[APPROVAL_LOGS_COLL].count_documents({"entity_type": entity_type, "entity_id": entity_id})
    if latest:
        return {
            "approval_status": latest["approval_status"],
            "latest_approval_type": latest.get("approval_type", ""),
            "latest_approval_at": latest.get("decided_at") or latest.get("requested_at", ""),
            "approval_history_count": count,
        }
    return {
        "approval_status": "not_requested",
        "latest_approval_type": "",
        "latest_approval_at": "",
        "approval_history_count": 0,
    }


@router.post("/approvals/request")
async def api_request_approval(body: ApprovalRequestIn):
    """Create a pending approval request for a Sales Order or PO Draft."""
    import uuid as _uuid

    if body.entity_type not in VALID_APPROVAL_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid entity_type '{body.entity_type}'. Must be one of: {VALID_APPROVAL_ENTITY_TYPES}")
    if body.approval_type not in VALID_APPROVAL_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid approval_type '{body.approval_type}'. Must be one of: {VALID_APPROVAL_TYPES}")

    db = get_db()

    # Validate entity exists
    if body.entity_type == "sales_order":
        # Check via order type collection or shipment logs
        pass  # SOs are referenced by ID, no strict collection to validate against
    elif body.entity_type == "po_draft":
        draft = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": body.entity_id}, {"_id": 0, "po_draft_id": 1})
        if not draft:
            raise HTTPException(status_code=404, detail=f"PO Draft '{body.entity_id}' not found")

    now = datetime.now(timezone.utc).isoformat()
    record = {
        "approval_id": f"APPR-{_uuid.uuid4().hex[:8].upper()}",
        "entity_type": body.entity_type,
        "entity_id": body.entity_id.strip(),
        "approval_type": body.approval_type,
        "approval_status": "pending",
        "requested_by": body.requested_by.strip(),
        "approved_by": None,
        "requested_at": now,
        "decided_at": None,
        "notes": body.notes.strip(),
    }
    await db[APPROVAL_LOGS_COLL].insert_one(record.copy())
    record.pop("_id", None)
    # System activity
    await _create_activity(db, body.entity_type, body.entity_id.strip(), "approval",
                           f"Approval requested ({body.approval_type})", body.notes.strip(),
                           body.requested_by.strip() or "system")
    return record


@router.patch("/approvals/{approval_id}")
async def api_decide_approval(approval_id: str, body: ApprovalDecisionIn):
    """Approve or reject an approval request."""
    if body.approval_status not in ("approved", "rejected"):
        raise HTTPException(status_code=422, detail="approval_status must be 'approved' or 'rejected'")

    db = get_db()
    existing = await db[APPROVAL_LOGS_COLL].find_one({"approval_id": approval_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Approval '{approval_id}' not found")

    if existing["approval_status"] != "pending":
        raise HTTPException(status_code=422, detail=f"Cannot change approval from '{existing['approval_status']}' to '{body.approval_status}'. Only pending approvals can be decided.")

    now = datetime.now(timezone.utc).isoformat()
    update = {
        "approval_status": body.approval_status,
        "approved_by": body.approved_by.strip(),
        "decided_at": now,
        "notes": body.notes.strip() if body.notes.strip() else existing.get("notes", ""),
    }
    await db[APPROVAL_LOGS_COLL].update_one({"approval_id": approval_id}, {"$set": update})

    result = {**existing, **update}
    # System activity for approval decision
    await _create_activity(db, existing["entity_type"], existing["entity_id"], "approval",
                           f"Approval {body.approval_status}", body.notes.strip(),
                           body.approved_by.strip() or "system")
    return result


@router.get("/approvals")
async def api_list_approvals(entity_type: str, entity_id: str):
    """List approval history for an entity."""
    if entity_type not in VALID_APPROVAL_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid entity_type '{entity_type}'.")
    db = get_db()
    cursor = db[APPROVAL_LOGS_COLL].find(
        {"entity_type": entity_type, "entity_id": entity_id}, {"_id": 0}
    ).sort("requested_at", -1)
    entries = await cursor.to_list(length=200)
    return {"entity_type": entity_type, "entity_id": entity_id, "total": len(entries), "approvals": entries}


# ═══════════════════════════════════════════════════════════════
# OPERATIONS QUEUE (UNIFIED WORKLIST)
# ═══════════════════════════════════════════════════════════════

PRIORITY_WEIGHTS = {
    "missing_approval": 50,
    "missing_documents": 40,
    "inventory_shortage": 35,
    "missing_po_draft": 30,
    "missing_vendor": 25,
    "pending_bc_export": 20,
    "pending_bc_response": 15,
    "pending_shipment": 10,
    "pending_invoice": 5,
}

ESCALATION_SCORE = {"due_soon": 10, "overdue": 20, "escalated": 30}


# ═══════════════════════════════════════════════════════════════
# ESCALATIONS & DUE DATES
# ═══════════════════════════════════════════════════════════════

ESCALATIONS_COLL = "escalations"
VALID_ESCALATION_STATUSES = ("on_track", "due_soon", "overdue", "escalated")


def _derive_escalation_status(due_date_str: str, current_status: str = ""):
    """Derive escalation status from due_date vs current date."""
    if current_status == "escalated":
        return "escalated"
    try:
        due = datetime.fromisoformat(due_date_str[:10]).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return "on_track"
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    delta = (due - now).days
    if delta < 0:
        return "overdue"
    if delta <= 3:
        return "due_soon"
    return "on_track"


def _calc_days(due_date_str: str):
    """Return (days_to_due, days_overdue) from due_date string."""
    try:
        due = datetime.fromisoformat(due_date_str[:10]).replace(tzinfo=timezone.utc)
    except (ValueError, TypeError):
        return None, None
    now = datetime.now(timezone.utc).replace(hour=0, minute=0, second=0, microsecond=0)
    delta = (due - now).days
    if delta >= 0:
        return delta, 0
    return 0, abs(delta)


async def _get_escalation(db, entity_type: str, entity_id: str):
    """Return latest escalation for an entity, or None."""
    doc = await db[ESCALATIONS_COLL].find_one(
        {"entity_type": entity_type, "entity_id": entity_id},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return doc


async def _get_escalation_enrichment(db, entity_type: str, entity_id: str):
    """Return escalation enrichment fields for summary/detail."""
    esc = await _get_escalation(db, entity_type, entity_id)
    if not esc:
        return {"due_date": "", "escalation_status": "", "days_to_due": None, "days_overdue": None}
    due = esc.get("due_date", "")
    status = _derive_escalation_status(due, esc.get("escalation_status", ""))
    days_to, days_over = _calc_days(due)
    return {"due_date": due, "escalation_status": status, "days_to_due": days_to, "days_overdue": days_over}


class EscalationIn(BaseModel):
    entity_type: str = Field(...)
    entity_id: str = Field(..., min_length=1)
    due_date: str = Field(..., min_length=1)
    notes: str = Field(default="")


class EscalationUpdateIn(BaseModel):
    due_date: str = Field(default="")
    escalation_status: str = Field(default="")
    notes: str = Field(default="")


@router.post("/escalations")
async def api_create_escalation(body: EscalationIn):
    """Create or upsert a due date / escalation record."""
    import uuid as _uuid

    if body.entity_type not in ("sales_order", "po_draft"):
        raise HTTPException(status_code=422, detail="entity_type must be sales_order or po_draft")

    db = get_db()
    # Validate PO draft exists if applicable
    if body.entity_type == "po_draft":
        draft = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": body.entity_id}, {"_id": 0, "po_draft_id": 1})
        if not draft:
            raise HTTPException(status_code=404, detail=f"PO Draft '{body.entity_id}' not found")

    now = datetime.now(timezone.utc).isoformat()
    derived_status = _derive_escalation_status(body.due_date.strip())

    # Upsert: replace existing record for same entity
    existing = await db[ESCALATIONS_COLL].find_one(
        {"entity_type": body.entity_type, "entity_id": body.entity_id.strip()}, {"_id": 0}
    )
    if existing:
        update = {
            "due_date": body.due_date.strip(),
            "escalation_status": derived_status,
            "notes": body.notes.strip(),
            "updated_at": now,
        }
        await db[ESCALATIONS_COLL].update_one(
            {"entity_type": body.entity_type, "entity_id": body.entity_id.strip()},
            {"$set": update},
        )
        result = {**existing, **update}
        return result

    record = {
        "escalation_id": f"ESC-{_uuid.uuid4().hex[:8].upper()}",
        "entity_type": body.entity_type,
        "entity_id": body.entity_id.strip(),
        "due_date": body.due_date.strip(),
        "escalation_status": derived_status,
        "escalation_reason": "",
        "notes": body.notes.strip(),
        "created_at": now,
        "updated_at": now,
    }
    await db[ESCALATIONS_COLL].insert_one(record.copy())
    record.pop("_id", None)
    # System activity
    await _create_activity(db, body.entity_type, body.entity_id.strip(), "escalation",
                           f"Due date set: {body.due_date.strip()}", body.notes.strip(), "system")
    return record


@router.get("/escalations")
async def api_list_escalations(entity_type: str = "", entity_id: str = ""):
    """List escalation records, optionally filtered."""
    db = get_db()
    query = {}
    if entity_type:
        query["entity_type"] = entity_type
    if entity_id:
        query["entity_id"] = entity_id
    cursor = db[ESCALATIONS_COLL].find(query, {"_id": 0}).sort("created_at", -1)
    entries = await cursor.to_list(length=200)
    # Refresh derived status
    for e in entries:
        e["escalation_status"] = _derive_escalation_status(e.get("due_date", ""), e.get("escalation_status", ""))
        days_to, days_over = _calc_days(e.get("due_date", ""))
        e["days_to_due"] = days_to
        e["days_overdue"] = days_over
    return {"total": len(entries), "entries": entries}


@router.patch("/escalations/{escalation_id}")
async def api_update_escalation(escalation_id: str, body: EscalationUpdateIn):
    """Update a due date / escalation record."""
    db = get_db()
    existing = await db[ESCALATIONS_COLL].find_one({"escalation_id": escalation_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Escalation '{escalation_id}' not found")

    now = datetime.now(timezone.utc).isoformat()
    update = {"updated_at": now}
    if body.due_date.strip():
        update["due_date"] = body.due_date.strip()
    if body.escalation_status.strip():
        if body.escalation_status not in VALID_ESCALATION_STATUSES:
            raise HTTPException(status_code=422, detail=f"Invalid escalation_status. Must be one of: {VALID_ESCALATION_STATUSES}")
        update["escalation_status"] = body.escalation_status
    if body.notes.strip():
        update["notes"] = body.notes.strip()

    # Re-derive status if due_date changed and not manually escalated
    new_status = update.get("escalation_status", existing.get("escalation_status", ""))
    new_due = update.get("due_date", existing.get("due_date", ""))
    if new_status != "escalated":
        update["escalation_status"] = _derive_escalation_status(new_due, new_status)

    await db[ESCALATIONS_COLL].update_one({"escalation_id": escalation_id}, {"$set": update})
    result = {**existing, **update}
    days_to, days_over = _calc_days(result.get("due_date", ""))
    result["days_to_due"] = days_to
    result["days_overdue"] = days_over
    # System activity
    esc_title = f"Escalation updated: {update.get('escalation_status', result.get('escalation_status', ''))}"
    await _create_activity(db, existing["entity_type"], existing["entity_id"], "escalation",
                           esc_title, body.notes.strip(), "system")
    return result


# ═══════════════════════════════════════════════════════════════
# ASSIGNMENTS & OWNERSHIP
# ═══════════════════════════════════════════════════════════════

ASSIGNMENTS_COLL = "assignments"
VALID_ASSIGNMENT_STATUSES = ("assigned", "in_progress", "waiting", "completed")


async def _get_active_assignment(db, entity_type: str, entity_id: str):
    """Return the latest active (non-completed) assignment for an entity, or None."""
    doc = await db[ASSIGNMENTS_COLL].find_one(
        {"entity_type": entity_type, "entity_id": entity_id, "assignment_status": {"$ne": "completed"}},
        {"_id": 0},
        sort=[("assigned_at", -1)],
    )
    return doc


async def _get_assignment_enrichment(db, entity_type: str, entity_id: str):
    """Return assignment enrichment fields for summary/detail/queue."""
    asgn = await _get_active_assignment(db, entity_type, entity_id)
    if not asgn:
        return {"current_owner": None, "assignment_status": "unassigned", "assignment_updated_at": None}
    return {
        "current_owner": asgn.get("assigned_to", ""),
        "assignment_status": asgn.get("assignment_status", "assigned"),
        "assignment_updated_at": asgn.get("updated_at", asgn.get("assigned_at", "")),
    }


class AssignmentIn(BaseModel):
    entity_type: str = Field(...)
    entity_id: str = Field(..., min_length=1)
    assigned_to: str = Field(..., min_length=1)
    assigned_by: str = Field(default="system")
    notes: str = Field(default="")


class AssignmentUpdateIn(BaseModel):
    assigned_to: str = Field(default="")
    assignment_status: str = Field(default="")
    notes: str = Field(default="")


@router.post("/assignments")
async def api_create_assignment(body: AssignmentIn):
    """Create or upsert the active assignment for an entity."""
    import uuid as _uuid

    if body.entity_type not in ("sales_order", "po_draft"):
        raise HTTPException(status_code=422, detail="entity_type must be sales_order or po_draft")

    db = get_db()
    # Validate entity exists
    if body.entity_type == "po_draft":
        draft = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": body.entity_id.strip()}, {"_id": 0, "po_draft_id": 1})
        if not draft:
            raise HTTPException(status_code=404, detail=f"PO Draft '{body.entity_id}' not found")

    now = datetime.now(timezone.utc).isoformat()

    # Upsert: update existing active assignment for same entity
    existing = await db[ASSIGNMENTS_COLL].find_one(
        {"entity_type": body.entity_type, "entity_id": body.entity_id.strip(), "assignment_status": {"$ne": "completed"}},
        {"_id": 0},
    )
    if existing:
        update = {
            "assigned_to": body.assigned_to.strip(),
            "assigned_by": body.assigned_by.strip(),
            "notes": body.notes.strip(),
            "updated_at": now,
            "assignment_status": "assigned",
        }
        await db[ASSIGNMENTS_COLL].update_one(
            {"assignment_id": existing["assignment_id"]},
            {"$set": update},
        )
        result = {**existing, **update}
        # System activity for reassignment
        await _create_activity(db, body.entity_type, body.entity_id.strip(), "assignment",
                               f"Reassigned to {body.assigned_to.strip()}", body.notes.strip(),
                               body.assigned_by.strip() or "system")
        return result

    record = {
        "assignment_id": f"ASGN-{_uuid.uuid4().hex[:8].upper()}",
        "entity_type": body.entity_type,
        "entity_id": body.entity_id.strip(),
        "assigned_to": body.assigned_to.strip(),
        "assigned_by": body.assigned_by.strip(),
        "assigned_at": now,
        "assignment_status": "assigned",
        "notes": body.notes.strip(),
        "updated_at": now,
    }
    await db[ASSIGNMENTS_COLL].insert_one(record.copy())
    record.pop("_id", None)
    # System activity for new assignment
    await _create_activity(db, body.entity_type, body.entity_id.strip(), "assignment",
                           f"Assigned to {body.assigned_to.strip()}", body.notes.strip(),
                           body.assigned_by.strip() or "system")
    return record


@router.get("/assignments")
async def api_list_assignments(entity_type: str = "", entity_id: str = ""):
    """List assignment records, optionally filtered."""
    db = get_db()
    query = {}
    if entity_type:
        query["entity_type"] = entity_type
    if entity_id:
        query["entity_id"] = entity_id
    cursor = db[ASSIGNMENTS_COLL].find(query, {"_id": 0}).sort("assigned_at", -1)
    entries = await cursor.to_list(length=200)
    return {"total": len(entries), "entries": entries}


@router.patch("/assignments/{assignment_id}")
async def api_update_assignment(assignment_id: str, body: AssignmentUpdateIn):
    """Update an assignment record."""
    db = get_db()
    existing = await db[ASSIGNMENTS_COLL].find_one({"assignment_id": assignment_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Assignment '{assignment_id}' not found")

    now = datetime.now(timezone.utc).isoformat()
    update = {"updated_at": now}
    if body.assigned_to.strip():
        update["assigned_to"] = body.assigned_to.strip()
    if body.assignment_status.strip():
        if body.assignment_status not in VALID_ASSIGNMENT_STATUSES:
            raise HTTPException(status_code=422, detail=f"Invalid assignment_status. Must be one of: {VALID_ASSIGNMENT_STATUSES}")
        update["assignment_status"] = body.assignment_status
    if body.notes.strip():
        update["notes"] = body.notes.strip()

    await db[ASSIGNMENTS_COLL].update_one({"assignment_id": assignment_id}, {"$set": update})
    result = {**existing, **update}
    # System activity for status update
    status_change = update.get("assignment_status", "")
    owner_change = update.get("assigned_to", "")
    title_parts = []
    if owner_change:
        title_parts.append(f"Reassigned to {owner_change}")
    if status_change:
        title_parts.append(f"Status: {status_change}")
    if title_parts:
        await _create_activity(db, existing["entity_type"], existing["entity_id"], "assignment",
                               " | ".join(title_parts), body.notes.strip(), "system")
    return result


# ═══════════════════════════════════════════════════════════════
# ACTIVITIES & NOTES TIMELINE
# ═══════════════════════════════════════════════════════════════

ACTIVITIES_COLL = "activities"
VALID_ACTIVITY_TYPES = (
    "note", "assignment", "approval", "document", "bc_export",
    "bc_response", "shipment", "invoice", "receipt", "escalation", "system",
)


async def _create_activity(db, entity_type: str, entity_id: str, activity_type: str,
                           title: str, body_text: str = "", created_by: str = "system", metadata: dict = None):
    """Internal helper to create an activity record."""
    import uuid as _uuid
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "activity_id": f"ACT-{_uuid.uuid4().hex[:8].upper()}",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "activity_type": activity_type,
        "title": title,
        "body": body_text,
        "created_by": created_by,
        "created_at": now,
        "metadata": metadata or {},
    }
    await db[ACTIVITIES_COLL].insert_one(record.copy())
    record.pop("_id", None)
    return record


async def _get_activity_enrichment(db, entity_type: str, entity_id: str):
    """Return activity enrichment fields for summary/detail."""
    latest = await db[ACTIVITIES_COLL].find_one(
        {"entity_type": entity_type, "entity_id": entity_id},
        {"_id": 0, "created_at": 1, "activity_type": 1},
        sort=[("created_at", -1)],
    )
    count = await db[ACTIVITIES_COLL].count_documents(
        {"entity_type": entity_type, "entity_id": entity_id}
    )
    if latest:
        return {
            "latest_activity_at": latest.get("created_at", ""),
            "latest_activity_type": latest.get("activity_type", ""),
            "activity_count": count,
        }
    return {"latest_activity_at": "", "latest_activity_type": "", "activity_count": 0}


class ActivityIn(BaseModel):
    entity_type: str = Field(...)
    entity_id: str = Field(..., min_length=1)
    activity_type: str = Field(default="note")
    title: str = Field(..., min_length=1)
    body: str = Field(default="")
    created_by: str = Field(default="user")


@router.post("/activities")
async def api_create_activity(req: ActivityIn):
    """Create a manual note or activity record."""
    if req.entity_type not in ("sales_order", "po_draft"):
        raise HTTPException(status_code=422, detail="entity_type must be sales_order or po_draft")
    if req.activity_type not in VALID_ACTIVITY_TYPES:
        raise HTTPException(status_code=422, detail=f"Invalid activity_type. Must be one of: {VALID_ACTIVITY_TYPES}")

    db = get_db()
    if req.entity_type == "po_draft":
        draft = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": req.entity_id.strip()}, {"_id": 0, "po_draft_id": 1})
        if not draft:
            raise HTTPException(status_code=404, detail=f"PO Draft '{req.entity_id}' not found")

    record = await _create_activity(
        db, req.entity_type, req.entity_id.strip(), req.activity_type,
        req.title.strip(), req.body.strip(), req.created_by.strip(),
    )
    return record


@router.get("/activities")
async def api_list_activities(
    entity_type: str = "", entity_id: str = "",
    activity_type: str = "", limit: int = 50, offset: int = 0,
):
    """List activities/notes, newest first."""
    db = get_db()
    query = {}
    if entity_type:
        query["entity_type"] = entity_type
    if entity_id:
        query["entity_id"] = entity_id
    if activity_type:
        query["activity_type"] = activity_type
    cursor = db[ACTIVITIES_COLL].find(query, {"_id": 0}).sort("created_at", -1).skip(offset).limit(limit)
    entries = await cursor.to_list(length=limit)
    total = await db[ACTIVITIES_COLL].count_documents(query)
    return {"total": total, "offset": offset, "limit": limit, "entries": entries}


# ═══════════════════════════════════════════════════════════════
# SAVED VIEWS & PERSONAL QUEUE PRESETS
# ═══════════════════════════════════════════════════════════════

SAVED_VIEWS_COLL = "saved_views"
VALID_VIEW_TYPES = ("operations_queue", "sales_orders", "po_drafts")


class SavedViewIn(BaseModel):
    view_type: str = Field(...)
    name: str = Field(..., min_length=1)
    is_default: bool = Field(default=False)
    created_by: str = Field(default="user")
    filters: dict = Field(default_factory=dict)
    sort: dict = Field(default_factory=dict)
    notes: str = Field(default="")


class SavedViewUpdateIn(BaseModel):
    name: str = Field(default="")
    is_default: bool = Field(default=None)
    filters: dict = Field(default=None)
    sort: dict = Field(default=None)
    notes: str = Field(default=None)


@router.post("/saved-views")
async def api_create_saved_view(body: SavedViewIn):
    """Create a saved view."""
    import uuid as _uuid

    if body.view_type not in VALID_VIEW_TYPES:
        raise HTTPException(status_code=422, detail=f"view_type must be one of: {VALID_VIEW_TYPES}")

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # If setting as default, unset previous default for same view_type + created_by
    if body.is_default:
        await db[SAVED_VIEWS_COLL].update_many(
            {"view_type": body.view_type, "created_by": body.created_by.strip(), "is_default": True},
            {"$set": {"is_default": False, "updated_at": now}},
        )

    record = {
        "saved_view_id": f"SV-{_uuid.uuid4().hex[:8].upper()}",
        "view_type": body.view_type,
        "name": body.name.strip(),
        "is_default": body.is_default,
        "created_by": body.created_by.strip(),
        "created_at": now,
        "updated_at": now,
        "filters": body.filters,
        "sort": body.sort,
        "notes": body.notes.strip(),
    }
    await db[SAVED_VIEWS_COLL].insert_one(record.copy())
    record.pop("_id", None)
    return record


@router.get("/saved-views")
async def api_list_saved_views(view_type: str = "", created_by: str = ""):
    """List saved views, optionally filtered."""
    db = get_db()
    query = {}
    if view_type:
        query["view_type"] = view_type
    if created_by:
        query["created_by"] = created_by
    cursor = db[SAVED_VIEWS_COLL].find(query, {"_id": 0}).sort("updated_at", -1)
    entries = await cursor.to_list(length=100)
    return {"total": len(entries), "entries": entries}


@router.patch("/saved-views/{saved_view_id}")
async def api_update_saved_view(saved_view_id: str, body: SavedViewUpdateIn):
    """Update a saved view."""
    db = get_db()
    existing = await db[SAVED_VIEWS_COLL].find_one({"saved_view_id": saved_view_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Saved view '{saved_view_id}' not found")

    now = datetime.now(timezone.utc).isoformat()
    update = {"updated_at": now}
    if body.name and body.name.strip():
        update["name"] = body.name.strip()
    if body.is_default is not None:
        update["is_default"] = body.is_default
        if body.is_default:
            await db[SAVED_VIEWS_COLL].update_many(
                {"view_type": existing["view_type"], "created_by": existing.get("created_by", "user"),
                 "is_default": True, "saved_view_id": {"$ne": saved_view_id}},
                {"$set": {"is_default": False, "updated_at": now}},
            )
    if body.filters is not None:
        update["filters"] = body.filters
    if body.sort is not None:
        update["sort"] = body.sort
    if body.notes is not None:
        update["notes"] = body.notes.strip() if body.notes else ""

    await db[SAVED_VIEWS_COLL].update_one({"saved_view_id": saved_view_id}, {"$set": update})
    result = {**existing, **update}
    return result


@router.delete("/saved-views/{saved_view_id}")
async def api_delete_saved_view(saved_view_id: str):
    """Delete a saved view."""
    db = get_db()
    result = await db[SAVED_VIEWS_COLL].delete_one({"saved_view_id": saved_view_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Saved view '{saved_view_id}' not found")
    return {"deleted": saved_view_id}


async def _build_so_queue_items(db, limit: int = 200):
    """Build queue items for Sales Orders that need attention."""
    items = []

    # Gather all known SOs from order_commitment movements + so_order_types + shipment/invoice logs
    so_ids = set()
    async for doc in db[SO_ORDER_TYPES_COLL].find({}, {"_id": 0, "sales_order_id": 1}):
        so_ids.add(doc["sales_order_id"])
    async for doc in db[MOVEMENTS_COLL].find(
        {"movement_type": "order_commitment"}, {"_id": 0, "reference_id": 1}
    ).limit(500):
        so_ids.add(doc["reference_id"])
    async for doc in db[BC_SHIPMENT_LOGS_COLL].find({}, {"_id": 0, "sales_order_id": 1}).limit(500):
        so_ids.add(doc["sales_order_id"])
    async for doc in db[DS_VENDOR_SHIPMENT_LOGS_COLL].find({}, {"_id": 0, "sales_order_id": 1}).limit(500):
        so_ids.add(doc["sales_order_id"])

    for so_id in so_ids:
        order_type = await _get_order_type(db, so_id)
        approval = await _get_latest_approval(db, "sales_order", so_id)
        doc_count, docs_by_type, _ = await _get_document_links_summary(db, "sales_order", so_id)

        score = 0
        actions = []

        # Approval missing
        approval_status = approval["approval_status"] if approval else "not_requested"
        if approval_status != "approved":
            score += PRIORITY_WEIGHTS["missing_approval"]
            actions.append("Approval missing" if approval_status == "not_requested" else f"Approval {approval_status}")

        # Customer PO document missing
        if docs_by_type.get("customer_po", 0) == 0:
            score += PRIORITY_WEIGHTS["missing_documents"]
            actions.append("Customer PO document missing")

        if order_type == "warehouse":
            # Inventory shortage: check if remaining committed > 0 and no shipment yet
            has_shipment = await db[BC_SHIPMENT_LOGS_COLL].count_documents({"sales_order_id": so_id}) > 0
            has_invoice = await db[BC_INVOICE_LOGS_COLL].count_documents({"sales_order_id": so_id}) > 0

            if not has_shipment:
                score += PRIORITY_WEIGHTS["pending_shipment"]
                actions.append("Shipment not yet recorded")
            if not has_invoice:
                score += PRIORITY_WEIGHTS["pending_invoice"]
                actions.append("Invoice not yet captured")
        else:
            # Drop-ship
            ds_draft_count = await db[PO_DRAFTS_COLL].count_documents(
                {"sales_order_id": so_id, "po_type": "drop_ship"}
            )
            if ds_draft_count == 0:
                score += PRIORITY_WEIGHTS["missing_po_draft"]
                actions.append("Drop-Ship PO draft not yet created")

            has_vendor_ship = await db[DS_VENDOR_SHIPMENT_LOGS_COLL].count_documents({"sales_order_id": so_id}) > 0
            has_bc_ship = await db[BC_SHIPMENT_LOGS_COLL].count_documents({"sales_order_id": so_id}) > 0
            has_invoice = await db[BC_INVOICE_LOGS_COLL].count_documents({"sales_order_id": so_id}) > 0

            if not has_vendor_ship and not has_bc_ship:
                score += PRIORITY_WEIGHTS["pending_shipment"]
                actions.append("Vendor shipment not recorded")
            if not has_invoice:
                score += PRIORITY_WEIGHTS["pending_invoice"]
                actions.append("Invoice not yet captured")

        if score == 0:
            continue  # Fully complete, no action needed

        # Determine next action
        next_action = actions[0] if actions else "Review"

        # Get created_at from the type record or first movement
        type_rec = await db[SO_ORDER_TYPES_COLL].find_one({"sales_order_id": so_id}, {"_id": 0, "set_at": 1})
        created_at = (type_rec or {}).get("set_at", "")

        checklist_items, checklist_complete = await _derive_so_checklist(db, so_id, order_type, doc_count, docs_by_type)

        items.append({
            "entity_type": "sales_order",
            "entity_id": so_id,
            "order_type": order_type,
            "vendor_name": "",
            "approval_status": approval_status,
            "checklist_complete": checklist_complete,
            "priority_score": score,
            "action_required": actions,
            "next_action": next_action,
            "created_at": created_at,
            "due_date": "",
            "escalation_status": "",
            "days_to_due": None,
            "days_overdue": None,
        })

    # Enrich with escalation data
    for item in items:
        esc = await _get_escalation(db, "sales_order", item["entity_id"])
        if esc:
            due = esc.get("due_date", "")
            esc_status = _derive_escalation_status(due, esc.get("escalation_status", ""))
            days_to, days_over = _calc_days(due)
            item["due_date"] = due
            item["escalation_status"] = esc_status
            item["days_to_due"] = days_to
            item["days_overdue"] = days_over
            item["priority_score"] += ESCALATION_SCORE.get(esc_status, 0)
            if esc_status in ("due_soon", "overdue", "escalated"):
                item["action_required"].append(f"{esc_status.replace('_', ' ').title()}: due {due}")

    return items


async def _build_po_draft_queue_items(db, limit: int = 200):
    """Build queue items for PO Drafts that need attention."""
    items = []
    cursor = db[PO_DRAFTS_COLL].find(
        {"status": {"$nin": ["archived"]}}, {"_id": 0}
    ).sort("created_at", -1).limit(limit)

    async for draft in cursor:
        draft_id = draft["po_draft_id"]
        score = 0
        actions = []

        # Vendor missing
        has_vendor = bool(draft.get("vendor_name") or draft.get("vendor_id"))
        if not has_vendor:
            score += PRIORITY_WEIGHTS["missing_vendor"]
            actions.append("Vendor not assigned")

        # Approval not granted
        approval = await _get_latest_approval(db, "po_draft", draft_id)
        approval_status = approval["approval_status"] if approval else "not_requested"
        if approval_status != "approved":
            score += PRIORITY_WEIGHTS["missing_approval"]
            actions.append("Approval not granted")

        # BC export not yet performed
        bc_payload = draft.get("bc_payload_snapshot")
        if not bc_payload:
            score += PRIORITY_WEIGHTS["pending_bc_export"]
            actions.append("BC export not yet performed")

        # BC response not yet captured
        bc_response = draft.get("bc_response_status")
        if not bc_response:
            score += PRIORITY_WEIGHTS["pending_bc_response"]
            actions.append("BC response not yet captured")

        if score == 0:
            continue

        next_action = actions[0] if actions else "Review"
        doc_count, docs_by_type, _ = await _get_document_links_summary(db, "po_draft", draft_id)
        checklist_items, checklist_complete = _derive_po_draft_checklist(draft, doc_count, docs_by_type, approval=approval)

        items.append({
            "entity_type": "po_draft",
            "entity_id": draft_id,
            "order_type": draft.get("po_type", "warehouse_supply"),
            "vendor_name": draft.get("vendor_name", ""),
            "approval_status": approval_status,
            "checklist_complete": checklist_complete,
            "priority_score": score,
            "action_required": actions,
            "next_action": next_action,
            "created_at": draft.get("created_at", ""),
            "due_date": "",
            "escalation_status": "",
            "days_to_due": None,
            "days_overdue": None,
        })

    # Enrich with escalation data
    for item in items:
        esc = await _get_escalation(db, "po_draft", item["entity_id"])
        if esc:
            due = esc.get("due_date", "")
            esc_status = _derive_escalation_status(due, esc.get("escalation_status", ""))
            days_to, days_over = _calc_days(due)
            item["due_date"] = due
            item["escalation_status"] = esc_status
            item["days_to_due"] = days_to
            item["days_overdue"] = days_over
            item["priority_score"] += ESCALATION_SCORE.get(esc_status, 0)
            if esc_status in ("due_soon", "overdue", "escalated"):
                item["action_required"].append(f"{esc_status.replace('_', ' ').title()}: due {due}")

    return items


@router.get("/operations-queue")
async def api_operations_queue(
    entity_type: str = "",
    status: str = "",
    escalation: str = "",
    assigned_to: str = "",
    assignment_status: str = "",
    unassigned_only: str = "",
    stale_days: int = 0,
    sort_by: str = "",
    limit: int = 100,
    offset: int = 0,
):
    """Return a prioritized list of entities requiring operational attention."""
    db = get_db()

    all_items = []
    if not entity_type or entity_type == "sales_order":
        all_items.extend(await _build_so_queue_items(db))
    if not entity_type or entity_type == "po_draft":
        all_items.extend(await _build_po_draft_queue_items(db))

    # Enrich with assignment + activity data
    for item in all_items:
        asgn = await _get_assignment_enrichment(db, item["entity_type"], item["entity_id"])
        item.update(asgn)
        act = await _get_activity_enrichment(db, item["entity_type"], item["entity_id"])
        item.update(act)
        # +10 priority for unassigned high-priority items
        if not item.get("current_owner") and item["priority_score"] >= 40:
            item["priority_score"] += 10

    # Filter by approval status if provided
    if status:
        all_items = [i for i in all_items if i["approval_status"] == status]

    # Filter by escalation status if provided
    if escalation:
        all_items = [i for i in all_items if i.get("escalation_status") == escalation]

    # Filter by assignment
    if assigned_to:
        all_items = [i for i in all_items if (i.get("current_owner") or "").lower() == assigned_to.lower()]
    if assignment_status:
        all_items = [i for i in all_items if i.get("assignment_status") == assignment_status]
    if unassigned_only.lower() in ("true", "1", "yes"):
        all_items = [i for i in all_items if not i.get("current_owner")]

    # Filter for stale items (no activity in N days)
    if stale_days > 0:
        cutoff = (datetime.now(timezone.utc) - timedelta(days=stale_days)).isoformat()
        all_items = [i for i in all_items if not i.get("latest_activity_at") or i["latest_activity_at"] < cutoff]

    # Sort
    if sort_by == "latest_activity":
        all_items.sort(key=lambda x: (x.get("latest_activity_at") or ""), reverse=True)
    else:
        all_items.sort(key=lambda x: (-x["priority_score"], x["created_at"] or ""))

    total = len(all_items)
    page = all_items[offset: offset + limit]
    high_priority = sum(1 for i in all_items if i["priority_score"] >= 40)
    due_soon_count = sum(1 for i in all_items if i.get("escalation_status") == "due_soon")
    overdue_count = sum(1 for i in all_items if i.get("escalation_status") == "overdue")
    escalated_count = sum(1 for i in all_items if i.get("escalation_status") == "escalated")

    # Assignment counts
    unassigned_count = sum(1 for i in all_items if not i.get("current_owner"))
    in_progress_count = sum(1 for i in all_items if i.get("assignment_status") == "in_progress")
    waiting_count = sum(1 for i in all_items if i.get("assignment_status") == "waiting")

    # Activity counts
    now_iso = datetime.now(timezone.utc)
    today_start = now_iso.replace(hour=0, minute=0, second=0, microsecond=0).isoformat()
    stale_cutoff = (now_iso - timedelta(days=7)).isoformat()
    recent_activity_today = sum(1 for i in all_items if i.get("latest_activity_at", "") >= today_start)
    no_recent_activity_7d = sum(1 for i in all_items if not i.get("latest_activity_at") or i["latest_activity_at"] < stale_cutoff)

    # Saved views counts
    sv_total = await db[SAVED_VIEWS_COLL].count_documents({"view_type": "operations_queue"})
    sv_default = await db[SAVED_VIEWS_COLL].find_one(
        {"view_type": "operations_queue", "is_default": True}, {"_id": 0, "name": 1}
    )

    return {
        "total": total,
        "high_priority_count": high_priority,
        "due_soon_count": due_soon_count,
        "overdue_count": overdue_count,
        "escalated_count": escalated_count,
        "unassigned_count": unassigned_count,
        "in_progress_count": in_progress_count,
        "waiting_count": waiting_count,
        "recent_activity_today": recent_activity_today,
        "no_recent_activity_7d": no_recent_activity_7d,
        "saved_views_count": sv_total,
        "default_view_name": sv_default["name"] if sv_default else "",
        "offset": offset,
        "limit": limit,
        "items": page,
    }


# ═══════════════════════════════════════════════════════════════
# BULK ACTIONS
# ═══════════════════════════════════════════════════════════════

VALID_BULK_ACTIONS = ("assign_owner", "update_assignment_status", "set_due_date", "set_escalation_status", "request_approval", "apply_template")


class BulkActionIn(BaseModel):
    entity_type: str = Field(...)
    entity_ids: list = Field(..., min_length=1)
    action: str = Field(...)
    payload: dict = Field(default_factory=dict)


@router.post("/operations-queue/bulk-action")
async def api_bulk_action(body: BulkActionIn):
    """Apply a bulk action to multiple entities."""
    import uuid as _uuid

    if body.entity_type not in ("sales_order", "po_draft"):
        raise HTTPException(status_code=422, detail="entity_type must be sales_order or po_draft")
    if body.action not in VALID_BULK_ACTIONS:
        raise HTTPException(status_code=422, detail=f"Invalid action. Must be one of: {VALID_BULK_ACTIONS}")
    if not body.entity_ids:
        raise HTTPException(status_code=422, detail="entity_ids must not be empty")

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    results = []

    for eid in body.entity_ids:
        eid = str(eid).strip()
        try:
            # Validate entity exists
            if body.entity_type == "po_draft":
                draft = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": eid}, {"_id": 0, "po_draft_id": 1})
                if not draft:
                    results.append({"entity_id": eid, "status": "failed", "message": f"PO Draft '{eid}' not found"})
                    continue

            if body.action == "assign_owner":
                assigned_to = body.payload.get("assigned_to", "").strip()
                notes = body.payload.get("notes", "").strip()
                if not assigned_to:
                    results.append({"entity_id": eid, "status": "failed", "message": "assigned_to is required"})
                    continue
                existing = await db[ASSIGNMENTS_COLL].find_one(
                    {"entity_type": body.entity_type, "entity_id": eid, "assignment_status": {"$ne": "completed"}}, {"_id": 0}
                )
                if existing:
                    await db[ASSIGNMENTS_COLL].update_one(
                        {"assignment_id": existing["assignment_id"]},
                        {"$set": {"assigned_to": assigned_to, "assignment_status": "assigned", "notes": notes, "updated_at": now}},
                    )
                else:
                    await db[ASSIGNMENTS_COLL].insert_one({
                        "assignment_id": f"ASGN-{_uuid.uuid4().hex[:8].upper()}",
                        "entity_type": body.entity_type, "entity_id": eid,
                        "assigned_to": assigned_to, "assigned_by": "bulk_action",
                        "assigned_at": now, "assignment_status": "assigned",
                        "notes": notes, "updated_at": now,
                    })
                await _create_activity(db, body.entity_type, eid, "assignment",
                                       f"Bulk assigned to {assigned_to}", notes, "bulk_action")
                results.append({"entity_id": eid, "status": "success", "message": f"Assigned to {assigned_to}"})

            elif body.action == "update_assignment_status":
                new_status = body.payload.get("assignment_status", "").strip()
                if new_status not in VALID_ASSIGNMENT_STATUSES:
                    results.append({"entity_id": eid, "status": "failed", "message": f"Invalid status: {new_status}"})
                    continue
                existing = await db[ASSIGNMENTS_COLL].find_one(
                    {"entity_type": body.entity_type, "entity_id": eid, "assignment_status": {"$ne": "completed"}}, {"_id": 0}
                )
                if not existing:
                    results.append({"entity_id": eid, "status": "failed", "message": "No active assignment found"})
                    continue
                await db[ASSIGNMENTS_COLL].update_one(
                    {"assignment_id": existing["assignment_id"]},
                    {"$set": {"assignment_status": new_status, "updated_at": now}},
                )
                await _create_activity(db, body.entity_type, eid, "assignment",
                                       f"Bulk status update: {new_status}", "", "bulk_action")
                results.append({"entity_id": eid, "status": "success", "message": f"Status updated to {new_status}"})

            elif body.action == "set_due_date":
                due_date = body.payload.get("due_date", "").strip()
                notes = body.payload.get("notes", "").strip()
                if not due_date:
                    results.append({"entity_id": eid, "status": "failed", "message": "due_date is required"})
                    continue
                derived_status = _derive_escalation_status(due_date)
                existing = await db[ESCALATIONS_COLL].find_one(
                    {"entity_type": body.entity_type, "entity_id": eid}, {"_id": 0}
                )
                if existing:
                    await db[ESCALATIONS_COLL].update_one(
                        {"entity_type": body.entity_type, "entity_id": eid},
                        {"$set": {"due_date": due_date, "escalation_status": derived_status, "notes": notes, "updated_at": now}},
                    )
                else:
                    await db[ESCALATIONS_COLL].insert_one({
                        "escalation_id": f"ESC-{_uuid.uuid4().hex[:8].upper()}",
                        "entity_type": body.entity_type, "entity_id": eid,
                        "due_date": due_date, "escalation_status": derived_status,
                        "notes": notes, "created_at": now, "updated_at": now,
                    })
                await _create_activity(db, body.entity_type, eid, "escalation",
                                       f"Bulk due date set: {due_date}", notes, "bulk_action")
                results.append({"entity_id": eid, "status": "success", "message": f"Due date set to {due_date} ({derived_status})"})

            elif body.action == "set_escalation_status":
                esc_status = body.payload.get("escalation_status", "").strip()
                if esc_status not in ("on_track", "due_soon", "overdue", "escalated"):
                    results.append({"entity_id": eid, "status": "failed", "message": f"Invalid escalation_status: {esc_status}"})
                    continue
                existing = await db[ESCALATIONS_COLL].find_one(
                    {"entity_type": body.entity_type, "entity_id": eid}, {"_id": 0}
                )
                if not existing:
                    results.append({"entity_id": eid, "status": "failed", "message": "No escalation record found. Set a due date first."})
                    continue
                await db[ESCALATIONS_COLL].update_one(
                    {"entity_type": body.entity_type, "entity_id": eid},
                    {"$set": {"escalation_status": esc_status, "updated_at": now}},
                )
                await _create_activity(db, body.entity_type, eid, "escalation",
                                       f"Bulk escalation: {esc_status}", "", "bulk_action")
                results.append({"entity_id": eid, "status": "success", "message": f"Escalation set to {esc_status}"})

            elif body.action == "request_approval":
                approval_type = body.payload.get("approval_type", "manager_review")
                notes = body.payload.get("notes", "").strip()
                requested_by = body.payload.get("requested_by", "bulk_action").strip()
                record = {
                    "approval_id": f"APR-{_uuid.uuid4().hex[:8].upper()}",
                    "entity_type": body.entity_type, "entity_id": eid,
                    "approval_type": approval_type,
                    "approval_status": "pending",
                    "requested_by": requested_by,
                    "requested_at": now,
                    "decided_by": "", "decided_at": "", "notes": notes,
                }
                await db[APPROVAL_LOGS_COLL].insert_one(record.copy())
                await _create_activity(db, body.entity_type, eid, "approval",
                                       f"Bulk approval requested ({approval_type})", notes, "bulk_action")
                results.append({"entity_id": eid, "status": "success", "message": f"Approval requested ({approval_type})"})

            elif body.action == "apply_template":
                tmpl_id = body.payload.get("template_id", "").strip()
                if not tmpl_id:
                    results.append({"entity_id": eid, "status": "failed", "message": "template_id is required"})
                    continue
                tmpl = await db[TEMPLATES_COLL].find_one({"template_id": tmpl_id, "is_active": True}, {"_id": 0})
                if not tmpl:
                    results.append({"entity_id": eid, "status": "failed", "message": f"Template '{tmpl_id}' not found or inactive"})
                    continue
                if tmpl["entity_type"] != body.entity_type:
                    results.append({"entity_id": eid, "status": "failed", "message": f"Template entity_type mismatch"})
                    continue
                apply_res = await _apply_template_to_entity(db, tmpl, body.entity_type, eid)
                results.append({"entity_id": eid, "status": "success", "message": f"Template applied: {', '.join(apply_res['actions_applied'])} | skipped: {', '.join(apply_res['actions_skipped'])}"})

        except Exception as e:
            results.append({"entity_id": eid, "status": "failed", "message": str(e)})

    succeeded = sum(1 for r in results if r["status"] == "success")
    failed = sum(1 for r in results if r["status"] == "failed")

    return {
        "action": body.action,
        "entity_type": body.entity_type,
        "processed_count": len(results),
        "succeeded_count": succeeded,
        "failed_count": failed,
        "results": results,
    }


# ═══════════════════════════════════════════════════════════════
# OPERATIONAL TEMPLATES
# ═══════════════════════════════════════════════════════════════

TEMPLATES_COLL = "operational_templates"
VALID_TEMPLATE_ENTITY_TYPES = ("sales_order", "po_draft")
VALID_ORDER_TYPES = ("warehouse", "drop_ship")


class TemplateIn(BaseModel):
    name: str = Field(..., min_length=1)
    entity_type: str = Field(...)
    applies_to_order_type: str = Field(default="")
    description: str = Field(default="")
    default_assignment_to: str = Field(default="")
    default_due_days: int = Field(default=0)
    default_escalation_status: str = Field(default="")
    auto_request_approval: bool = Field(default=False)
    notes: str = Field(default="")
    is_active: bool = Field(default=True)
    created_by: str = Field(default="user")


class TemplateUpdateIn(BaseModel):
    name: str = Field(default=None)
    description: str = Field(default=None)
    applies_to_order_type: str = Field(default=None)
    default_assignment_to: str = Field(default=None)
    default_due_days: int = Field(default=None)
    default_escalation_status: str = Field(default=None)
    auto_request_approval: bool = Field(default=None)
    notes: str = Field(default=None)
    is_active: bool = Field(default=None)


class TemplateApplyIn(BaseModel):
    entity_type: str = Field(...)
    entity_id: str = Field(..., min_length=1)


@router.post("/templates")
async def api_create_template(body: TemplateIn):
    """Create an operational template."""
    import uuid as _uuid
    if body.entity_type not in VALID_TEMPLATE_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"entity_type must be one of: {VALID_TEMPLATE_ENTITY_TYPES}")
    if body.applies_to_order_type and body.applies_to_order_type not in VALID_ORDER_TYPES:
        raise HTTPException(status_code=422, detail=f"applies_to_order_type must be one of: {VALID_ORDER_TYPES}")

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "template_id": f"TMPL-{_uuid.uuid4().hex[:8].upper()}",
        "name": body.name.strip(),
        "entity_type": body.entity_type,
        "applies_to_order_type": body.applies_to_order_type.strip() if body.applies_to_order_type else "",
        "description": body.description.strip(),
        "default_assignment_to": body.default_assignment_to.strip(),
        "default_due_days": body.default_due_days,
        "default_escalation_status": body.default_escalation_status.strip(),
        "auto_request_approval": body.auto_request_approval,
        "notes": body.notes.strip(),
        "is_active": body.is_active,
        "created_by": body.created_by.strip(),
        "created_at": now,
        "updated_at": now,
    }
    await db[TEMPLATES_COLL].insert_one(record.copy())
    record.pop("_id", None)
    return record


@router.get("/templates")
async def api_list_templates(entity_type: str = "", applies_to_order_type: str = "", is_active: str = ""):
    """List templates, optionally filtered."""
    db = get_db()
    query = {}
    if entity_type:
        query["entity_type"] = entity_type
    if applies_to_order_type:
        query["applies_to_order_type"] = applies_to_order_type
    if is_active.lower() in ("true", "1"):
        query["is_active"] = True
    elif is_active.lower() in ("false", "0"):
        query["is_active"] = False
    cursor = db[TEMPLATES_COLL].find(query, {"_id": 0}).sort("updated_at", -1)
    entries = await cursor.to_list(length=100)
    return {"total": len(entries), "entries": entries}


@router.patch("/templates/{template_id}")
async def api_update_template(template_id: str, body: TemplateUpdateIn):
    """Update an operational template."""
    db = get_db()
    existing = await db[TEMPLATES_COLL].find_one({"template_id": template_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    now = datetime.now(timezone.utc).isoformat()
    update = {"updated_at": now}
    if body.name is not None and body.name.strip():
        update["name"] = body.name.strip()
    if body.description is not None:
        update["description"] = body.description.strip() if body.description else ""
    if body.applies_to_order_type is not None:
        update["applies_to_order_type"] = body.applies_to_order_type.strip() if body.applies_to_order_type else ""
    if body.default_assignment_to is not None:
        update["default_assignment_to"] = body.default_assignment_to.strip() if body.default_assignment_to else ""
    if body.default_due_days is not None:
        update["default_due_days"] = body.default_due_days
    if body.default_escalation_status is not None:
        update["default_escalation_status"] = body.default_escalation_status.strip() if body.default_escalation_status else ""
    if body.auto_request_approval is not None:
        update["auto_request_approval"] = body.auto_request_approval
    if body.notes is not None:
        update["notes"] = body.notes.strip() if body.notes else ""
    if body.is_active is not None:
        update["is_active"] = body.is_active
    await db[TEMPLATES_COLL].update_one({"template_id": template_id}, {"$set": update})
    return {**existing, **update}


@router.delete("/templates/{template_id}")
async def api_delete_template(template_id: str):
    """Delete (or deactivate) a template."""
    db = get_db()
    existing = await db[TEMPLATES_COLL].find_one({"template_id": template_id}, {"_id": 0})
    if not existing:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found")
    now = datetime.now(timezone.utc).isoformat()
    await db[TEMPLATES_COLL].update_one(
        {"template_id": template_id},
        {"$set": {"is_active": False, "updated_at": now}},
    )
    return {"deactivated": template_id}


async def _apply_template_to_entity(db, tmpl: dict, entity_type: str, entity_id: str):
    """Apply a template to an entity. Returns actions_applied, actions_skipped, messages."""
    import uuid as _uuid
    now = datetime.now(timezone.utc).isoformat()
    applied = []
    skipped = []
    messages = []

    # Assignment
    if tmpl.get("default_assignment_to"):
        existing_asgn = await db[ASSIGNMENTS_COLL].find_one(
            {"entity_type": entity_type, "entity_id": entity_id, "assignment_status": {"$ne": "completed"}}, {"_id": 0}
        )
        if existing_asgn:
            skipped.append("assignment")
            messages.append(f"Assignment already exists ({existing_asgn.get('assigned_to', '')})")
        else:
            await db[ASSIGNMENTS_COLL].insert_one({
                "assignment_id": f"ASGN-{_uuid.uuid4().hex[:8].upper()}",
                "entity_type": entity_type, "entity_id": entity_id,
                "assigned_to": tmpl["default_assignment_to"],
                "assigned_by": "template", "assigned_at": now,
                "assignment_status": "assigned", "notes": f"From template: {tmpl['name']}",
                "updated_at": now,
            })
            await _create_activity(db, entity_type, entity_id, "assignment",
                                   f"Template assigned to {tmpl['default_assignment_to']}", f"Template: {tmpl['name']}", "template")
            applied.append("assignment")
            messages.append(f"Assigned to {tmpl['default_assignment_to']}")

    # Due date / escalation
    if tmpl.get("default_due_days", 0) > 0:
        existing_esc = await db[ESCALATIONS_COLL].find_one(
            {"entity_type": entity_type, "entity_id": entity_id}, {"_id": 0}
        )
        if existing_esc:
            skipped.append("due_date")
            messages.append(f"Due date already set ({existing_esc.get('due_date', '')})")
        else:
            due_date = (datetime.now(timezone.utc) + timedelta(days=tmpl["default_due_days"])).isoformat()
            esc_status = tmpl.get("default_escalation_status", "") or _derive_escalation_status(due_date)
            await db[ESCALATIONS_COLL].insert_one({
                "escalation_id": f"ESC-{_uuid.uuid4().hex[:8].upper()}",
                "entity_type": entity_type, "entity_id": entity_id,
                "due_date": due_date, "escalation_status": esc_status,
                "notes": f"From template: {tmpl['name']}", "created_at": now, "updated_at": now,
            })
            await _create_activity(db, entity_type, entity_id, "escalation",
                                   f"Template due date: +{tmpl['default_due_days']} days", f"Template: {tmpl['name']}", "template")
            applied.append("due_date")
            messages.append(f"Due date set to +{tmpl['default_due_days']} days")

    # Approval
    if tmpl.get("auto_request_approval"):
        existing_apr = await db[APPROVAL_LOGS_COLL].find_one(
            {"entity_type": entity_type, "entity_id": entity_id, "approval_status": "pending"}, {"_id": 0}
        )
        if existing_apr:
            skipped.append("approval")
            messages.append("Pending approval already exists")
        else:
            await db[APPROVAL_LOGS_COLL].insert_one({
                "approval_id": f"APR-{_uuid.uuid4().hex[:8].upper()}",
                "entity_type": entity_type, "entity_id": entity_id,
                "approval_type": "manager_review", "approval_status": "pending",
                "requested_by": "template", "requested_at": now,
                "decided_by": "", "decided_at": "",
                "notes": f"From template: {tmpl['name']}",
            })
            await _create_activity(db, entity_type, entity_id, "approval",
                                   f"Template approval requested (manager_review)", f"Template: {tmpl['name']}", "template")
            applied.append("approval")
            messages.append("Approval requested (manager_review)")

    # Activity for template applied
    await _create_activity(db, entity_type, entity_id, "system",
                           f"Template applied: {tmpl['name']}", f"Applied: {', '.join(applied) or 'none'}, Skipped: {', '.join(skipped) or 'none'}", "template")

    return {"template_id": tmpl["template_id"], "entity_type": entity_type, "entity_id": entity_id,
            "actions_applied": applied, "actions_skipped": skipped, "messages": messages}


@router.post("/templates/{template_id}/apply")
async def api_apply_template(template_id: str, body: TemplateApplyIn):
    """Apply a template to a single entity."""
    if body.entity_type not in VALID_TEMPLATE_ENTITY_TYPES:
        raise HTTPException(status_code=422, detail=f"entity_type must be one of: {VALID_TEMPLATE_ENTITY_TYPES}")

    db = get_db()
    tmpl = await db[TEMPLATES_COLL].find_one({"template_id": template_id, "is_active": True}, {"_id": 0})
    if not tmpl:
        raise HTTPException(status_code=404, detail=f"Template '{template_id}' not found or inactive")
    if tmpl["entity_type"] != body.entity_type:
        raise HTTPException(status_code=422, detail=f"Template entity_type '{tmpl['entity_type']}' does not match '{body.entity_type}'")

    # Validate entity exists
    if body.entity_type == "po_draft":
        draft = await db[PO_DRAFTS_COLL].find_one({"po_draft_id": body.entity_id.strip()}, {"_id": 0, "po_draft_id": 1})
        if not draft:
            raise HTTPException(status_code=404, detail=f"PO Draft '{body.entity_id}' not found")

    # Validate order type compatibility for SOs
    if body.entity_type == "sales_order" and tmpl.get("applies_to_order_type"):
        ot_doc = await db["so_order_types"].find_one({"sales_order_id": body.entity_id.strip()}, {"_id": 0})
        actual_ot = ot_doc.get("order_type", "warehouse") if ot_doc else "warehouse"
        if actual_ot != tmpl["applies_to_order_type"]:
            raise HTTPException(status_code=422, detail=f"Template requires order type '{tmpl['applies_to_order_type']}' but SO is '{actual_ot}'")

    result = await _apply_template_to_entity(db, tmpl, body.entity_type, body.entity_id.strip())
    return result


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
