"""
Customer Inventory Ledger Service

Core business logic for the customer-specific inventory ledger.
Ledger-based model: balances are always derived from immutable movements.

Balance bucket key: (customer_id, item, warehouse, ownership_type, unit_of_measure)

Movement immutability: movements are never edited. Corrections are handled
via offsetting `correction` entries.

Negative balance policy: configurable per customer workspace (warn_only | block_commitment).
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Optional

logger = logging.getLogger(__name__)

# ── Movement types ──
MOVEMENT_TYPES = {
    "opening_balance", "receipt", "order_commitment", "order_release",
    "manual_adjustment", "transfer", "writeoff", "correction",
    "outbound_shipment",
}

# ── Source types (provenance tracking) ──
SOURCE_TYPES = {
    "manual_entry", "spreadsheet_import", "sales_order_commitment",
    "sales_order_release", "incoming_supply", "receipt", "correction",
    "bc_shipment",
}

# ── Ownership types ──
OWNERSHIP_TYPES = {"customer_owned", "gamer_reserved", "mixed", "unknown"}

# ── Incoming supply statuses ──
SUPPLY_STATUSES = {"planned", "ordered", "expected", "in_transit", "received", "cancelled"}

# ── Negative balance policies ──
NEGATIVE_POLICIES = {"warn_only", "block_commitment"}

# ── Collections ──
CUSTOMERS_COLL = "inv_customers"
MOVEMENTS_COLL = "inv_movements"
INCOMING_COLL = "inv_incoming_supply"


# ═══════════════════════════════════════════════════════════════
# CUSTOMER WORKSPACES
# ═══════════════════════════════════════════════════════════════

async def list_customers(db, active_only=True):
    query = {"active": True} if active_only else {}
    docs = await db[CUSTOMERS_COLL].find(query, {"_id": 0}).sort("name", 1).to_list(200)
    return docs


async def get_customer(db, customer_id: str):
    return await db[CUSTOMERS_COLL].find_one({"id": customer_id}, {"_id": 0})


async def create_customer(db, name: str, code: str, negative_balance_policy: str = "warn_only", created_by: str = "system"):
    if negative_balance_policy not in NEGATIVE_POLICIES:
        negative_balance_policy = "warn_only"
    doc = {
        "id": str(uuid.uuid4()),
        "name": name,
        "code": code.upper().strip(),
        "negative_balance_policy": negative_balance_policy,
        "active": True,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "created_by": created_by,
    }
    await db[CUSTOMERS_COLL].insert_one(doc)
    doc.pop("_id", None)
    return doc


async def update_customer(db, customer_id: str, updates: dict):
    allowed = {"name", "code", "negative_balance_policy", "active"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if "negative_balance_policy" in safe and safe["negative_balance_policy"] not in NEGATIVE_POLICIES:
        safe.pop("negative_balance_policy")
    if "code" in safe:
        safe["code"] = safe["code"].upper().strip()
    safe["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db[CUSTOMERS_COLL].update_one({"id": customer_id}, {"$set": safe})
    return await get_customer(db, customer_id)


# ═══════════════════════════════════════════════════════════════
# MOVEMENTS (immutable ledger entries)
# ═══════════════════════════════════════════════════════════════

async def create_movement(
    db,
    customer_id: str,
    item: str,
    item_description: str,
    warehouse: str,
    ownership_type: str,
    movement_type: str,
    quantity_delta: float,
    unit_of_measure: str,
    source_type: str = "manual_entry",
    reference_type: str = "",
    reference_id: str = "",
    notes: str = "",
    created_by: str = "system",
    skip_balance_check: bool = False,
):
    """Create an immutable movement entry.

    Returns: {success, movement, warning} or raises ValueError.
    """
    if movement_type not in MOVEMENT_TYPES:
        raise ValueError(f"Invalid movement_type: {movement_type}. Must be one of {MOVEMENT_TYPES}")
    if ownership_type not in OWNERSHIP_TYPES:
        ownership_type = "unknown"
    if source_type not in SOURCE_TYPES:
        source_type = "manual_entry"

    # Validate customer exists
    cust = await get_customer(db, customer_id)
    if not cust:
        raise ValueError(f"Customer workspace '{customer_id}' not found")

    warning = None

    # Negative balance check for commitment movements
    if not skip_balance_check and movement_type == "order_commitment" and quantity_delta < 0:
        balances = await derive_balances(db, customer_id, item=item, warehouse=warehouse)
        bucket = next(
            (b for b in balances
             if b["item"] == item and b["warehouse"] == warehouse
             and b["ownership_type"] == ownership_type
             and b["unit_of_measure"] == unit_of_measure),
            None,
        )
        current_available = bucket["available"] if bucket else 0
        new_available = current_available + quantity_delta  # delta is negative
        if new_available < 0:
            policy = cust.get("negative_balance_policy", "warn_only")
            if policy == "block_commitment":
                raise ValueError(
                    f"Commitment blocked: available would become {new_available} {unit_of_measure}. "
                    f"Current available: {current_available}. Customer policy: block_commitment."
                )
            else:
                warning = f"Warning: available will be negative ({new_available} {unit_of_measure}) after this commitment."

    movement = {
        "id": str(uuid.uuid4()),
        "customer_id": customer_id,
        "item": item.strip(),
        "item_description": item_description.strip(),
        "warehouse": warehouse.strip(),
        "ownership_type": ownership_type,
        "movement_type": movement_type,
        "quantity_delta": quantity_delta,
        "unit_of_measure": unit_of_measure.strip(),
        "source_type": source_type,
        "reference_type": reference_type,
        "reference_id": reference_id,
        "notes": notes,
        "created_by": created_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db[MOVEMENTS_COLL].insert_one(movement)
    movement.pop("_id", None)
    return {"success": True, "movement": movement, "warning": warning}


async def list_movements(
    db, customer_id: str,
    item: str = "", warehouse: str = "",
    movement_type: str = "", source_type: str = "",
    skip: int = 0, limit: int = 100,
):
    query = {"customer_id": customer_id}
    if item:
        query["item"] = item
    if warehouse:
        query["warehouse"] = warehouse
    if movement_type:
        query["movement_type"] = movement_type
    if source_type:
        query["source_type"] = source_type

    total = await db[MOVEMENTS_COLL].count_documents(query)
    docs = await db[MOVEMENTS_COLL].find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)
    return {"movements": docs, "total": total}


def _compute_display_effect(movement_type: str, quantity_delta: float) -> float:
    """Compute display_effect: net impact on available inventory for UI display.

    order_release has negative delta but INCREASES available (frees committed),
    so we flip its sign for display.
    """
    if movement_type == "order_release":
        return -quantity_delta  # negative delta → positive display effect
    return quantity_delta


async def get_history(
    db, customer_id: str,
    item: str = "", reference: str = "",
    movement_type: str = "",
    skip: int = 0, limit: int = 100,
):
    """Return movement history with display_effect enrichment, reverse chronological."""
    query: dict = {"customer_id": customer_id}
    if item:
        query["item"] = item
    if reference:
        query["reference_id"] = reference
    if movement_type:
        query["movement_type"] = movement_type

    total = await db[MOVEMENTS_COLL].count_documents(query)
    docs = await db[MOVEMENTS_COLL].find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)

    for doc in docs:
        doc["display_effect"] = _compute_display_effect(
            doc.get("movement_type", ""), doc.get("quantity_delta", 0),
        )

    return {"movements": docs, "total": total}


async def item_audit_summary(db, customer_id: str, item: str):
    """Compact audit summary for a single item across all warehouses.

    Returns per-type totals + current balance values from derive_balances.
    """
    pipeline = [
        {"$match": {"customer_id": customer_id, "item": item}},
        {"$group": {
            "_id": "$movement_type",
            "total_qty": {"$sum": "$quantity_delta"},
            "count": {"$sum": 1},
        }},
    ]
    raw = await db[MOVEMENTS_COLL].aggregate(pipeline).to_list(100)
    type_totals = {r["_id"]: {"total_qty": r["total_qty"], "count": r["count"]} for r in raw}

    # Get current balances
    balances = await derive_balances(db, customer_id, item=item)

    totals = {
        "on_hand": sum(b.get("on_hand", 0) for b in balances),
        "incoming": sum(b.get("incoming", 0) for b in balances),
        "committed": sum(b.get("committed", 0) for b in balances),
        "available": sum(b.get("available", 0) for b in balances),
    }

    return {
        "item": item,
        "customer_id": customer_id,
        "movement_type_totals": type_totals,
        "current_balances": totals,
        "balance_details": balances,
    }



# ═══════════════════════════════════════════════════════════════
# BALANCE DERIVATION (ledger-computed, never hand-maintained)
# ═══════════════════════════════════════════════════════════════

async def derive_balances(
    db, customer_id: str,
    item: Optional[str] = None,
    warehouse: Optional[str] = None,
):
    """Derive current balances from the movement ledger.

    For each bucket (item, warehouse, ownership_type, unit_of_measure):
      on_hand   = SUM(delta) for all types EXCEPT order_commitment
      committed = abs(SUM(delta for order_commitment)) + SUM(delta for order_release)
                  [order_release reduces outstanding commitment]
      incoming  = from inv_incoming_supply (expected + in_transit)
      available = on_hand + incoming - committed
    """
    match = {"customer_id": customer_id}
    if item:
        match["item"] = item
    if warehouse:
        match["warehouse"] = warehouse

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {
                "item": "$item",
                "warehouse": "$warehouse",
                "ownership_type": "$ownership_type",
                "unit_of_measure": "$unit_of_measure",
            },
            "item_description": {"$last": "$item_description"},
            # Physical inventory: all types except order_commitment and order_release
            "on_hand": {"$sum": {"$cond": [
                {"$and": [
                    {"$ne": ["$movement_type", "order_commitment"]},
                    {"$ne": ["$movement_type", "order_release"]},
                ]},
                "$quantity_delta", 0,
            ]}},
            # Commitment deltas (stored negative)
            "commitment_raw": {"$sum": {"$cond": [
                {"$eq": ["$movement_type", "order_commitment"]},
                "$quantity_delta", 0,
            ]}},
            # Release deltas (stored negative — reduce outstanding commitment)
            "release_raw": {"$sum": {"$cond": [
                {"$eq": ["$movement_type", "order_release"]},
                "$quantity_delta", 0,
            ]}},
            "movement_count": {"$sum": 1},
            "last_movement": {"$max": "$created_at"},
        }},
    ]

    raw = await db[MOVEMENTS_COLL].aggregate(pipeline).to_list(5000)

    # Fetch incoming supply for this customer
    inc_match = {"customer_id": customer_id, "status": {"$in": ["planned", "ordered", "expected", "in_transit"]}}
    if item:
        inc_match["item"] = item
    if warehouse:
        inc_match["warehouse"] = warehouse

    inc_pipeline = [
        {"$match": inc_match},
        {"$group": {
            "_id": {
                "item": "$item",
                "warehouse": "$warehouse",
                "ownership_type": "$ownership_type",
                "unit_of_measure": "$unit_of_measure",
            },
            "incoming_qty": {"$sum": "$incoming_qty"},
        }},
    ]
    incoming_raw = await db[INCOMING_COLL].aggregate(inc_pipeline).to_list(5000)
    incoming_map = {
        (r["_id"]["item"], r["_id"]["warehouse"], r["_id"]["ownership_type"], r["_id"]["unit_of_measure"]): r["incoming_qty"]
        for r in incoming_raw
    }

    balances = []
    for r in raw:
        k = r["_id"]
        on_hand = round(r["on_hand"], 4)
        # committed = abs(commitment_raw) + release_raw
        # commitment_raw is negative (e.g. -100), multiply by -1 gives 100
        # release_raw is negative (e.g. -30), so 100 + (-30) = 70 outstanding
        committed = round((-1 * r["commitment_raw"]) + r["release_raw"], 4)
        if committed < 0:
            committed = 0  # safety: can't have negative commitment
        incoming = incoming_map.get(
            (k["item"], k["warehouse"], k["ownership_type"], k["unit_of_measure"]), 0
        )
        available = round(on_hand + incoming - committed, 4)

        balances.append({
            "item": k["item"],
            "item_description": r.get("item_description", ""),
            "warehouse": k["warehouse"],
            "ownership_type": k["ownership_type"],
            "unit_of_measure": k["unit_of_measure"],
            "on_hand": on_hand,
            "incoming": round(incoming, 4),
            "committed": committed,
            "available": available,
            "movement_count": r["movement_count"],
            "last_movement": r.get("last_movement", ""),
            "is_short": available < 0,
            "is_low": 0 <= available <= 5,  # simple threshold
        })

    # Sort: shorts first, then by item
    balances.sort(key=lambda b: (not b["is_short"], not b["is_low"], b["item"], b["warehouse"]))
    return balances


async def customer_summary(db, customer_id: str):
    """Fast summary counts for customer workspace strip."""
    balances = await derive_balances(db, customer_id)
    total_items = len(set(b["item"] for b in balances))
    total_on_hand = sum(b["on_hand"] for b in balances)
    total_incoming = sum(b["incoming"] for b in balances)
    total_committed = sum(b["committed"] for b in balances)
    shortage_count = sum(1 for b in balances if b["is_short"])
    low_count = sum(1 for b in balances if b["is_low"] and not b["is_short"])
    return {
        "total_items": total_items,
        "total_buckets": len(balances),
        "total_on_hand": round(total_on_hand, 2),
        "total_incoming": round(total_incoming, 2),
        "total_committed": round(total_committed, 2),
        "shortage_count": shortage_count,
        "low_count": low_count,
    }


# ═══════════════════════════════════════════════════════════════
# INCOMING SUPPLY
# ═══════════════════════════════════════════════════════════════

async def create_incoming(
    db, customer_id: str,
    item: str, item_description: str, warehouse: str,
    ownership_type: str, incoming_qty: float, unit_of_measure: str,
    eta: str = "", source_reference: str = "", notes: str = "",
    created_by: str = "system", status: str = "expected",
):
    if status not in SUPPLY_STATUSES:
        status = "expected"
    doc = {
        "id": str(uuid.uuid4()),
        "customer_id": customer_id,
        "item": item.strip(),
        "item_description": item_description.strip(),
        "warehouse": warehouse.strip(),
        "ownership_type": ownership_type if ownership_type in OWNERSHIP_TYPES else "unknown",
        "incoming_qty": incoming_qty,
        "unit_of_measure": unit_of_measure.strip(),
        "eta": eta,
        "source_reference": source_reference,
        "status": status,
        "notes": notes,
        "created_by": created_by,
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db[INCOMING_COLL].insert_one(doc)
    doc.pop("_id", None)
    return doc


async def update_incoming(db, supply_id: str, updates: dict):
    allowed = {"incoming_qty", "eta", "source_reference", "status", "notes", "warehouse"}
    safe = {k: v for k, v in updates.items() if k in allowed}
    if "status" in safe and safe["status"] not in SUPPLY_STATUSES:
        safe.pop("status")
    safe["updated_at"] = datetime.now(timezone.utc).isoformat()
    await db[INCOMING_COLL].update_one({"id": supply_id}, {"$set": safe})
    return await db[INCOMING_COLL].find_one({"id": supply_id}, {"_id": 0})


async def list_incoming(db, customer_id: str, status: str = "", item: str = ""):
    query = {"customer_id": customer_id}
    if status:
        query["status"] = status
    if item:
        query["item"] = item
    docs = await db[INCOMING_COLL].find(query, {"_id": 0}).sort("eta", 1).to_list(500)
    return docs


# ═══════════════════════════════════════════════════════════════
# DISTINCT ITEMS / WAREHOUSES for a customer
# ═══════════════════════════════════════════════════════════════

async def distinct_items(db, customer_id: str):
    return await db[MOVEMENTS_COLL].distinct("item", {"customer_id": customer_id})


async def distinct_warehouses(db, customer_id: str):
    return await db[MOVEMENTS_COLL].distinct("warehouse", {"customer_id": customer_id})


# ═══════════════════════════════════════════════════════════════
# BATCH SEED (import-friendly)
# ═══════════════════════════════════════════════════════════════

async def seed_opening_balances(db, customer_id: str, rows: list, created_by: str = "system"):
    """Seed multiple opening balance movements at once.

    Each row: {item, item_description, warehouse, ownership_type, quantity, unit_of_measure, notes?}
    """
    results = []
    for row in rows:
        try:
            await create_movement(
                db, customer_id,
                item=row["item"],
                item_description=row.get("item_description", ""),
                warehouse=row.get("warehouse", "MAIN"),
                ownership_type=row.get("ownership_type", "customer_owned"),
                movement_type="opening_balance",
                quantity_delta=float(row["quantity"]),
                unit_of_measure=row.get("unit_of_measure", "units"),
                source_type="spreadsheet_import",
                notes=row.get("notes", "Seeded from spreadsheet import"),
                created_by=created_by,
                skip_balance_check=True,
            )
            results.append({"item": row["item"], "success": True})
        except Exception as e:
            results.append({"item": row.get("item", "?"), "success": False, "error": str(e)})
    return {"seeded": sum(1 for r in results if r["success"]), "errors": sum(1 for r in results if not r["success"]), "details": results}


# ═══════════════════════════════════════════════════════════════
# INDEXES
# ═══════════════════════════════════════════════════════════════

async def ensure_indexes(db):
    await db[CUSTOMERS_COLL].create_index("id", unique=True)
    await db[CUSTOMERS_COLL].create_index("code", unique=True)
    await db[MOVEMENTS_COLL].create_index("id", unique=True)
    await db[MOVEMENTS_COLL].create_index([("customer_id", 1), ("item", 1), ("warehouse", 1)])
    await db[MOVEMENTS_COLL].create_index([("customer_id", 1), ("created_at", -1)])
    await db[MOVEMENTS_COLL].create_index("movement_type")
    await db[INCOMING_COLL].create_index("id", unique=True)
    await db[INCOMING_COLL].create_index([("customer_id", 1), ("status", 1)])
    logger.info("[InventoryLedger] Indexes created")
