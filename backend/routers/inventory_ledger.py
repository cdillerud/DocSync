"""
Customer Inventory Ledger Router

REST API for the customer-specific inventory ledger module.
All endpoints under /inventory-ledger/.
"""

import logging
import hashlib
import csv
import io
from datetime import datetime, timezone
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
        {"_id": 0, "po_draft_id": 1, "created_at": 1, "status": 1},
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
