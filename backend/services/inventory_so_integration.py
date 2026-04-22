"""
Inventory ↔ Sales Order Integration Service

Bridges the Customer Inventory Ledger with the SO preflight and creation flow:
  1. Workspace resolution: match customer_no/name to an inventory workspace
  2. Line-level inventory lookup: for each SO line, find the matching bucket
  3. Commitment creation: create order_commitment movements on successful SO create
  4. Idempotent commitment protection: prevent duplicate commitments on retry
  5. Release: create order_release movements when SO lines are fulfilled or cancelled
"""

import logging
from typing import Optional
from workflows.inventory.ledger.service import (
    derive_balances, create_movement, list_movements,
    create_incoming, get_customer,
    CUSTOMERS_COLL, MOVEMENTS_COLL, INCOMING_COLL,
)

logger = logging.getLogger(__name__)


async def resolve_inventory_workspace(db, customer_no: str = "", customer_name: str = ""):
    """Try to find the matching inventory workspace for a BC customer.

    Strategy:
      1. Exact match on customer code (case-insensitive)
      2. Partial match on customer name
      3. Return all active workspaces if no match (let user pick)
    """
    if not customer_no and not customer_name:
        return {"workspace": None, "match_method": "none", "all_workspaces": []}

    all_ws = await db[CUSTOMERS_COLL].find({"active": True}, {"_id": 0}).to_list(200)

    # 1. Exact code match
    if customer_no:
        for ws in all_ws:
            if ws["code"].upper() == customer_no.upper():
                return {"workspace": ws, "match_method": "code_exact", "all_workspaces": all_ws}

    # 2. Name substring match
    if customer_name:
        name_lower = customer_name.lower()
        for ws in all_ws:
            if ws["name"].lower() in name_lower or name_lower in ws["name"].lower():
                return {"workspace": ws, "match_method": "name_partial", "all_workspaces": all_ws}
            if ws["code"].lower() in name_lower:
                return {"workspace": ws, "match_method": "code_in_name", "all_workspaces": all_ws}

    return {"workspace": None, "match_method": "no_match", "all_workspaces": all_ws}


async def lookup_line_inventory(db, workspace_id: str, item: str, warehouse: str = ""):
    """Look up inventory for a single SO line against the customer workspace.

    Returns inventory data for the best-matching bucket, or NO_MATCH.
    """
    if not workspace_id or not item:
        return {"status": "NO_MATCH", "matched": False}

    # Derive balances for this item across all warehouses
    balances = await derive_balances(db, workspace_id, item=item, warehouse=warehouse or None)

    if not balances:
        # Try fuzzy: item might be mapped to a different code in the ledger
        # For now, try a case-insensitive search across all items
        all_balances = await derive_balances(db, workspace_id)
        item_upper = item.upper().strip()
        balances = [b for b in all_balances if b["item"].upper().strip() == item_upper]

    if not balances:
        return {"status": "NO_MATCH", "matched": False}

    # Aggregate across all matching buckets (might span warehouses/ownership)
    total_on_hand = sum(b["on_hand"] for b in balances)
    total_incoming = sum(b["incoming"] for b in balances)
    total_committed = sum(b["committed"] for b in balances)
    total_available = sum(b["available"] for b in balances)

    # Determine status
    status = "OK"
    if total_available <= 0:
        status = "SHORT"
    elif total_available <= 5:
        status = "LOW"

    return {
        "matched": True,
        "status": status,
        "on_hand": round(total_on_hand, 2),
        "incoming": round(total_incoming, 2),
        "committed": round(total_committed, 2),
        "available": round(total_available, 2),
        "buckets": len(balances),
        "unit_of_measure": balances[0].get("unit_of_measure", ""),
        "warehouse": balances[0].get("warehouse", "") if len(balances) == 1 else "multiple",
        "ownership_type": balances[0].get("ownership_type", "") if len(balances) == 1 else "mixed",
    }


async def enrich_lines_with_inventory(db, workspace_id: str, resolved_lines: list):
    """Enrich each resolved SO line with inventory lookup data.

    Adds `inventory` field to each line dict.
    Returns (enriched_lines, inventory_summary).
    """
    matched_count = 0
    shortage_count = 0
    no_match_count = 0

    for line in resolved_lines:
        # Use the mapped item/GL number as the lookup key
        item_key = line.get("lineObjectNumber", "") or ""
        desc = line.get("description", "")

        # For Comment lines or empty targets, try description-based match
        if not item_key and desc:
            # Extract potential SKU from description (first word or hyphenated pattern)
            parts = desc.split()
            item_key = parts[0] if parts else ""

        inv = await lookup_line_inventory(db, workspace_id, item_key)

        if not inv["matched"] and item_key != desc:
            # Second attempt with full description
            inv = await lookup_line_inventory(db, workspace_id, desc.split()[0] if desc else "")

        line["inventory"] = inv

        if inv["matched"]:
            matched_count += 1
            ordered = float(line.get("quantity", 0))
            if inv["available"] < ordered:
                shortage_count += 1
                if inv["available"] <= 0:
                    inv["status"] = "SHORT"
                else:
                    inv["status"] = "LOW"
        else:
            no_match_count += 1

    summary = {
        "workspace_id": workspace_id,
        "lines_matched": matched_count,
        "lines_short": shortage_count,
        "lines_no_match": no_match_count,
        "total_lines": len(resolved_lines),
    }

    return resolved_lines, summary


async def create_order_commitments(
    db,
    workspace_id: str,
    doc_id: str,
    bc_record_no: str,
    transaction_id: str,
    submitted_lines: list,
    customer_no: str = "",
    created_by: str = "gpi_hub",
) -> dict:
    """Create order_commitment movements for each SO line that has inventory.

    Idempotent: checks if commitments already exist for this doc_id.
    Respects negative balance policy via the create_movement function.

    Returns: {committed: int, skipped: int, blocked: int, warnings: [], movement_ids: [], errors: []}
    """
    result = {"committed": 0, "skipped": 0, "blocked": 0, "warnings": [], "movement_ids": [], "errors": []}

    if not workspace_id:
        return result

    # Idempotency: check if commitments already exist for this doc
    existing = await db[MOVEMENTS_COLL].count_documents({
        "customer_id": workspace_id,
        "movement_type": "order_commitment",
        "reference_type": "sales_order",
        "reference_id": bc_record_no,
    })
    if existing > 0:
        logger.info("Commitments already exist for SO %s (doc %s) — skipping", bc_record_no, doc_id)
        result["skipped"] = existing
        return result

    for idx, line in enumerate(submitted_lines):
        inv = line.get("inventory", {})
        if not inv or not inv.get("matched"):
            result["skipped"] += 1
            continue

        item_key = line.get("lineObjectNumber", "") or ""
        if not item_key:
            result["skipped"] += 1
            continue

        qty = float(line.get("quantity", 0))
        if qty <= 0:
            result["skipped"] += 1
            continue

        uom = inv.get("unit_of_measure", "units")
        warehouse = inv.get("warehouse", "MAIN")
        if warehouse == "multiple":
            warehouse = "MAIN"  # Default when spanning warehouses
        ownership = inv.get("ownership_type", "customer_owned")
        if ownership == "mixed":
            ownership = "customer_owned"

        try:
            mv_result = await create_movement(
                db, workspace_id,
                item=item_key,
                item_description=line.get("description", "")[:100],
                warehouse=warehouse,
                ownership_type=ownership,
                movement_type="order_commitment",
                quantity_delta=-qty,  # Negative = committed out
                unit_of_measure=uom,
                source_type="sales_order_commitment",
                reference_type="sales_order",
                reference_id=bc_record_no,
                notes=f"SO {bc_record_no} line {idx+1} (doc {doc_id[:8]}). Txn: {transaction_id}",
                created_by=created_by,
                skip_balance_check=False,
            )
            if mv_result["success"]:
                result["committed"] += 1
                result["movement_ids"].append(mv_result["movement"]["id"])
                if mv_result.get("warning"):
                    result["warnings"].append(mv_result["warning"])
            else:
                result["errors"].append(f"Line {idx+1}: movement creation failed")
        except ValueError as ve:
            # block_commitment policy triggered
            result["blocked"] += 1
            result["errors"].append(f"Line {idx+1} ({item_key}): {str(ve)}")
        except Exception as e:
            result["errors"].append(f"Line {idx+1}: {str(e)}")

    logger.info(
        "Inventory commitments for SO %s: committed=%d skipped=%d blocked=%d",
        bc_record_no, result["committed"], result["skipped"], result["blocked"],
    )
    return result


async def release_order_commitments(
    db,
    sales_order_id: str,
    lines: list,
    created_by: str = "gpi_hub",
) -> dict:
    """Release committed inventory for a Sales Order.

    For each line in `lines` (with keys `item` and `qty`):
      1. Look up existing order_commitment movements for this SO + item.
      2. Look up existing order_release movements for this SO + item.
      3. Validate that release qty does not exceed outstanding committed qty.
      4. Create an order_release movement.

    Returns: {released: int, skipped: int, errors: [], movement_ids: [], updated_balances: []}
    Raises ValueError (→ 422) when release exceeds committed.
    """
    result = {"released": 0, "skipped": 0, "errors": [], "movement_ids": [], "updated_balances": []}

    if not lines:
        return result

    # Find the workspace that holds commitments for this SO + requested items
    requested_items = [ln.get("item", "").strip() for ln in lines if ln.get("item")]
    sample_query = {"movement_type": "order_commitment", "reference_id": sales_order_id}
    if requested_items:
        sample_query["item"] = {"$in": requested_items}
    sample_commitment = await db[MOVEMENTS_COLL].find_one(sample_query, {"_id": 0, "customer_id": 1})
    if not sample_commitment:
        raise ValueError(f"No order_commitment movements found for sales order '{sales_order_id}'")

    workspace_id = sample_commitment["customer_id"]
    cust = await get_customer(db, workspace_id)
    if not cust:
        raise ValueError(f"Customer workspace '{workspace_id}' not found")

    for line in lines:
        item = (line.get("item") or "").strip()
        release_qty = float(line.get("qty", 0))

        if not item or release_qty <= 0:
            result["skipped"] += 1
            continue

        # Sum existing commitments for this SO + item (stored as negative deltas)
        commitment_pipeline = [
            {"$match": {
                "customer_id": workspace_id,
                "movement_type": "order_commitment",
                "reference_id": sales_order_id,
                "item": item,
            }},
            {"$group": {"_id": None, "total": {"$sum": "$quantity_delta"}}},
        ]
        commit_agg = await db[MOVEMENTS_COLL].aggregate(commitment_pipeline).to_list(1)
        committed_delta = commit_agg[0]["total"] if commit_agg else 0  # negative
        committed_qty = abs(committed_delta)  # positive

        # Sum existing releases for this SO + item (stored as negative deltas)
        release_pipeline = [
            {"$match": {
                "customer_id": workspace_id,
                "movement_type": "order_release",
                "reference_id": sales_order_id,
                "item": item,
            }},
            {"$group": {"_id": None, "total": {"$sum": "$quantity_delta"}}},
        ]
        release_agg = await db[MOVEMENTS_COLL].aggregate(release_pipeline).to_list(1)
        already_released_delta = release_agg[0]["total"] if release_agg else 0  # negative
        already_released_qty = abs(already_released_delta)  # positive

        outstanding = committed_qty - already_released_qty

        if outstanding <= 0:
            result["errors"].append(
                f"Item '{item}': nothing to release (committed={committed_qty}, already released={already_released_qty})"
            )
            continue

        if release_qty > outstanding:
            raise ValueError(
                f"Release quantity {release_qty} exceeds outstanding commitment "
                f"{outstanding} for item '{item}' on SO '{sales_order_id}' "
                f"(committed={committed_qty}, already_released={already_released_qty})"
            )

        # Find warehouse/ownership/uom from the original commitment
        sample_line = await db[MOVEMENTS_COLL].find_one(
            {"customer_id": workspace_id, "movement_type": "order_commitment",
             "reference_id": sales_order_id, "item": item},
            {"_id": 0},
        )
        warehouse = sample_line.get("warehouse", "MAIN") if sample_line else "MAIN"
        ownership = sample_line.get("ownership_type", "customer_owned") if sample_line else "customer_owned"
        uom = sample_line.get("unit_of_measure", "units") if sample_line else "units"
        item_desc = sample_line.get("item_description", "") if sample_line else ""

        mv_result = await create_movement(
            db, workspace_id,
            item=item,
            item_description=item_desc,
            warehouse=warehouse,
            ownership_type=ownership,
            movement_type="order_release",
            quantity_delta=-release_qty,  # Negative delta, same convention as commitment
            unit_of_measure=uom,
            source_type="sales_order_release",
            reference_type="sales_order",
            reference_id=sales_order_id,
            notes=f"Released {release_qty} {uom} from SO {sales_order_id}",
            created_by=created_by,
            skip_balance_check=True,
        )
        if mv_result["success"]:
            result["released"] += 1
            result["movement_ids"].append(mv_result["movement"]["id"])
        else:
            result["errors"].append(f"Item '{item}': movement creation failed")

    # Return updated balances for the workspace
    if result["released"] > 0:
        result["updated_balances"] = await derive_balances(db, workspace_id)

    logger.info(
        "Inventory releases for SO %s: released=%d skipped=%d errors=%d",
        sales_order_id, result["released"], result["skipped"], len(result["errors"]),
    )
    return result


async def create_shortage_supply(
    db,
    sales_order_id: str,
    lines: list,
    created_by: str = "gpi_hub",
) -> dict:
    """Create incoming supply records for SHORT items on a Sales Order.

    For each line: shortage = qty_needed - qty_available.
    Rejects if shortage <= 0, or if a duplicate supply record already exists
    for the same item + order reference (HTTP 409).

    Returns: {created: int, skipped: int, supply_ids: [], errors: [], duplicates: []}
    """
    result = {"created": 0, "skipped": 0, "supply_ids": [], "errors": [], "duplicates": []}

    if not lines:
        return result

    # Find the workspace from the commitment for this SO
    sample = await db[MOVEMENTS_COLL].find_one(
        {"movement_type": "order_commitment", "reference_id": sales_order_id},
        {"_id": 0, "customer_id": 1},
    )
    if not sample:
        raise ValueError(f"No order_commitment found for sales order '{sales_order_id}'")

    workspace_id = sample["customer_id"]
    cust = await get_customer(db, workspace_id)
    if not cust:
        raise ValueError(f"Customer workspace '{workspace_id}' not found")

    for line in lines:
        item = (line.get("item") or "").strip()
        qty_needed = float(line.get("qty_needed", 0))
        qty_available = float(line.get("qty_available", 0))
        shortage = qty_needed - qty_available

        if not item:
            result["skipped"] += 1
            continue

        if shortage <= 0:
            result["errors"].append(
                f"Item '{item}': no shortage (needed={qty_needed}, available={qty_available})"
            )
            continue

        # Duplicate check: same item + source_reference in this workspace
        existing = await db[INCOMING_COLL].find_one({
            "customer_id": workspace_id,
            "item": item,
            "source_reference": sales_order_id,
            "status": {"$nin": ["cancelled", "received"]},
        }, {"_id": 0, "id": 1})
        if existing:
            result["duplicates"].append(item)
            continue

        # Get item metadata from the commitment movement
        commitment_doc = await db[MOVEMENTS_COLL].find_one(
            {"customer_id": workspace_id, "movement_type": "order_commitment",
             "reference_id": sales_order_id, "item": item},
            {"_id": 0},
        )
        warehouse = commitment_doc.get("warehouse", "MAIN") if commitment_doc else "MAIN"
        ownership = commitment_doc.get("ownership_type", "customer_owned") if commitment_doc else "customer_owned"
        uom = commitment_doc.get("unit_of_measure", "units") if commitment_doc else "units"
        item_desc = commitment_doc.get("item_description", "") if commitment_doc else ""

        supply_doc = await create_incoming(
            db, workspace_id,
            item=item,
            item_description=item_desc,
            warehouse=warehouse,
            ownership_type=ownership,
            incoming_qty=round(shortage, 4),
            unit_of_measure=uom,
            source_reference=sales_order_id,
            notes=f"Auto-created from shortage on SO {sales_order_id} (needed={qty_needed}, available={qty_available})",
            created_by=created_by,
            status="planned",
        )
        result["created"] += 1
        result["supply_ids"].append(supply_doc["id"])

    logger.info(
        "Shortage supply for SO %s: created=%d skipped=%d duplicates=%d errors=%d",
        sales_order_id, result["created"], result["skipped"],
        len(result["duplicates"]), len(result["errors"]),
    )
    return result


# ═══════════════════════════════════════════════════════════════
# INCOMING SUPPLY STATUS TRANSITIONS
# ═══════════════════════════════════════════════════════════════

VALID_TRANSITIONS = {
    "planned": {"ordered", "cancelled"},
    "ordered": {"received", "cancelled"},
    # Legacy statuses (backward compat)
    "expected": {"ordered", "cancelled"},
    "in_transit": {"received", "cancelled"},
}


async def transition_supply_status(
    db,
    supply_id: str,
    new_status: str,
    created_by: str = "gpi_hub",
) -> dict:
    """Transition an incoming supply record through its lifecycle.

    Valid transitions: planned→ordered, planned→cancelled,
                       ordered→received, ordered→cancelled.

    When transitioning to 'received', creates a receipt ledger movement
    to move the quantity into on_hand.

    Returns: {supply: <updated record>, receipt_movement_id: str|None}
    Raises ValueError (→422) for invalid transition.
    Raises DuplicateError (→409) if already received.
    """
    record = await db[INCOMING_COLL].find_one({"id": supply_id}, {"_id": 0})
    if not record:
        raise ValueError(f"Incoming supply record '{supply_id}' not found")

    current = record["status"]

    # Already in target state
    if current == new_status:
        if new_status == "received":
            raise DuplicateReceiptError(
                f"Supply '{supply_id}' is already received"
            )
        return {"supply": record, "receipt_movement_id": None}

    # Check valid transition
    allowed = VALID_TRANSITIONS.get(current, set())
    if new_status not in allowed:
        raise ValueError(
            f"Invalid transition: '{current}' → '{new_status}'. "
            f"Allowed from '{current}': {sorted(allowed) if allowed else 'none (terminal state)'}"
        )

    from datetime import datetime, timezone
    update_doc = {"status": new_status, "updated_at": datetime.now(timezone.utc).isoformat()}
    await db[INCOMING_COLL].update_one({"id": supply_id}, {"$set": update_doc})

    receipt_movement_id = None

    # If received → create a receipt ledger movement
    if new_status == "received":
        cust = await get_customer(db, record["customer_id"])
        if not cust:
            raise ValueError(f"Customer workspace '{record['customer_id']}' not found")

        mv_result = await create_movement(
            db, record["customer_id"],
            item=record["item"],
            item_description=record.get("item_description", ""),
            warehouse=record.get("warehouse", "MAIN"),
            ownership_type=record.get("ownership_type", "customer_owned"),
            movement_type="receipt",
            quantity_delta=record["incoming_qty"],  # Positive = adds to on_hand
            unit_of_measure=record.get("unit_of_measure", "units"),
            source_type="incoming_supply",
            reference_type="incoming_supply",
            reference_id=supply_id,
            notes=f"Receipt from incoming supply (source: {record.get('source_reference', 'N/A')})",
            created_by=created_by,
            skip_balance_check=True,
        )
        if mv_result["success"]:
            receipt_movement_id = mv_result["movement"]["id"]

    updated = await db[INCOMING_COLL].find_one({"id": supply_id}, {"_id": 0})
    logger.info(
        "Supply '%s' transitioned %s → %s (receipt_mv=%s)",
        supply_id, current, new_status, receipt_movement_id,
    )
    return {"supply": updated, "receipt_movement_id": receipt_movement_id}


class DuplicateReceiptError(Exception):
    """Raised when trying to receive an already-received supply."""
    pass


# ═══════════════════════════════════════════════════════════════
# SALES ORDER COMMITMENT RECONCILIATION
# ═══════════════════════════════════════════════════════════════

async def _get_net_committed(db, workspace_id: str, sales_order_id: str, item: str = None):
    """Return dict of {item: net_committed_qty} for the given SO.

    net_committed = abs(sum(order_commitment)) - abs(sum(order_release))
    """
    match = {
        "customer_id": workspace_id,
        "reference_id": sales_order_id,
        "movement_type": {"$in": ["order_commitment", "order_release"]},
    }
    if item:
        match["item"] = item

    pipeline = [
        {"$match": match},
        {"$group": {
            "_id": {"item": "$item", "movement_type": "$movement_type"},
            "total": {"$sum": "$quantity_delta"},
        }},
    ]
    raw = await db[MOVEMENTS_COLL].aggregate(pipeline).to_list(5000)

    # Build per-item sums
    commitments = {}  # item → abs(sum of commitment deltas)
    releases = {}     # item → abs(sum of release deltas)
    for r in raw:
        it = r["_id"]["item"]
        mt = r["_id"]["movement_type"]
        val = abs(r["total"])
        if mt == "order_commitment":
            commitments[it] = commitments.get(it, 0) + val
        else:
            releases[it] = releases.get(it, 0) + val

    all_items = set(commitments.keys()) | set(releases.keys())
    return {
        it: round(commitments.get(it, 0) - releases.get(it, 0), 4)
        for it in all_items
    }


async def _get_item_metadata(db, workspace_id: str, sales_order_id: str, item: str):
    """Get warehouse/ownership/uom from the original commitment for this item."""
    doc = await db[MOVEMENTS_COLL].find_one(
        {"customer_id": workspace_id, "movement_type": "order_commitment",
         "reference_id": sales_order_id, "item": item},
        {"_id": 0},
    )
    if not doc:
        return "MAIN", "customer_owned", "units", ""
    return (
        doc.get("warehouse", "MAIN"),
        doc.get("ownership_type", "customer_owned"),
        doc.get("unit_of_measure", "units"),
        doc.get("item_description", ""),
    )


async def reconcile_sales_order(
    db,
    sales_order_id: str,
    lines: list,
    cancelled: bool = False,
    created_by: str = "gpi_hub",
) -> dict:
    """Reconcile inventory commitments for an edited or cancelled Sales Order.

    When `cancelled=True`: release all remaining net commitments for every
    item tied to this SO.  Idempotent — repeating cancel when net is already
    zero creates no movements.

    When `cancelled=False`: for each line compare the new qty to the current
    net committed and create delta commitment or release movements.

    Returns: {adjustments: int, movement_ids: [], per_line: [...], updated_balances: []}
    """
    result = {
        "adjustments": 0,
        "movement_ids": [],
        "per_line": [],
        "updated_balances": [],
    }

    # Find workspace
    sample = await db[MOVEMENTS_COLL].find_one(
        {"movement_type": "order_commitment", "reference_id": sales_order_id},
        {"_id": 0, "customer_id": 1},
    )
    if not sample:
        raise ValueError(f"No order_commitment found for sales order '{sales_order_id}'")

    workspace_id = sample["customer_id"]
    cust = await get_customer(db, workspace_id)
    if not cust:
        raise ValueError(f"Customer workspace '{workspace_id}' not found")

    net_committed = await _get_net_committed(db, workspace_id, sales_order_id)

    if cancelled:
        # Release ALL remaining net commitment for every item
        for item, outstanding in net_committed.items():
            if outstanding <= 0:
                result["per_line"].append({
                    "item": item, "previous_committed": 0,
                    "new_qty": 0, "delta": 0, "action": "none",
                })
                continue

            warehouse, ownership, uom, item_desc = await _get_item_metadata(
                db, workspace_id, sales_order_id, item,
            )
            mv = await create_movement(
                db, workspace_id,
                item=item, item_description=item_desc,
                warehouse=warehouse, ownership_type=ownership,
                movement_type="order_release",
                quantity_delta=-outstanding,
                unit_of_measure=uom,
                source_type="sales_order_release",
                reference_type="sales_order",
                reference_id=sales_order_id,
                notes=f"SO {sales_order_id} cancelled — released {outstanding} {uom}",
                created_by=created_by,
                skip_balance_check=True,
            )
            if mv["success"]:
                result["adjustments"] += 1
                result["movement_ids"].append(mv["movement"]["id"])
            result["per_line"].append({
                "item": item, "previous_committed": outstanding,
                "new_qty": 0, "delta": -outstanding, "action": "release",
            })
    else:
        # Per-line reconciliation
        for line in lines:
            item = (line.get("item") or "").strip()
            new_qty = float(line.get("qty", 0))

            if not item:
                continue
            if new_qty < 0:
                raise ValueError(f"Negative quantity {new_qty} for item '{item}'")

            prev = net_committed.get(item, 0)
            delta = round(new_qty - prev, 4)

            if delta == 0:
                result["per_line"].append({
                    "item": item, "previous_committed": prev,
                    "new_qty": new_qty, "delta": 0, "action": "none",
                })
                continue

            warehouse, ownership, uom, item_desc = await _get_item_metadata(
                db, workspace_id, sales_order_id, item,
            )

            if delta > 0:
                # Need more commitment
                mv = await create_movement(
                    db, workspace_id,
                    item=item, item_description=item_desc,
                    warehouse=warehouse, ownership_type=ownership,
                    movement_type="order_commitment",
                    quantity_delta=-delta,
                    unit_of_measure=uom,
                    source_type="sales_order_commitment",
                    reference_type="sales_order",
                    reference_id=sales_order_id,
                    notes=f"SO {sales_order_id} edit — additional commitment of {delta} {uom}",
                    created_by=created_by,
                    skip_balance_check=True,
                )
                action = "commit"
            else:
                # Release excess
                release_amt = abs(delta)
                mv = await create_movement(
                    db, workspace_id,
                    item=item, item_description=item_desc,
                    warehouse=warehouse, ownership_type=ownership,
                    movement_type="order_release",
                    quantity_delta=delta,  # already negative
                    unit_of_measure=uom,
                    source_type="sales_order_release",
                    reference_type="sales_order",
                    reference_id=sales_order_id,
                    notes=f"SO {sales_order_id} edit — released {release_amt} {uom}",
                    created_by=created_by,
                    skip_balance_check=True,
                )
                action = "release"

            if mv["success"]:
                result["adjustments"] += 1
                result["movement_ids"].append(mv["movement"]["id"])
            result["per_line"].append({
                "item": item, "previous_committed": prev,
                "new_qty": new_qty, "delta": delta, "action": action,
            })

    # Updated balances
    if result["adjustments"] > 0:
        result["updated_balances"] = await derive_balances(db, workspace_id)

    logger.info(
        "Reconcile SO %s (cancelled=%s): adjustments=%d lines=%d",
        sales_order_id, cancelled, result["adjustments"], len(result["per_line"]),
    )
    return result


# ═══════════════════════════════════════════════════════════════
# BC SHIPMENT SYNC → INVENTORY LEDGER
# ═══════════════════════════════════════════════════════════════

import os
import httpx
from datetime import datetime, timezone, timedelta

BC_SHIPMENT_SYNC_COLL = "bc_shipment_sync"
_SYNC_STATUS_KEY = "bc_shipment_sync_status"


async def _fetch_bc_shipment_lines(since_iso: str) -> list:
    """Query BC Sales Shipment Lines API for shipments since a given ISO timestamp.

    Uses the standard BC v2.0 OData API (read-only, Production environment).
    Returns a list of shipment line dicts, or [] if BC is unavailable.
    """
    from services.gpi_integration_service import (
        _get_token, GPI_API_BASE, BC_TENANT_ID, BC_READ_ENVIRONMENT,
        BC_COMPANY_ID, BC_STANDARD_API, HAS_CREDENTIALS, REQUEST_TIMEOUT,
    )

    if not HAS_CREDENTIALS:
        logger.warning("[ShipmentSync] BC credentials not configured — skipping fetch")
        return []

    try:
        token = await _get_token()
    except Exception as e:
        logger.warning("[ShipmentSync] BC token acquisition failed: %s", e)
        return []

    # Standard BC OData v2.0 endpoint for posted sales shipment lines
    base = f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/{BC_STANDARD_API}"
    if BC_COMPANY_ID:
        url = f"{base}/companies({BC_COMPANY_ID})/salesShipmentLines"
    else:
        url = f"{base}/salesShipmentLines"

    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {
        "$filter": f"shipmentDate ge {since_iso[:10]}",
        "$orderby": "shipmentDate desc",
        "$top": "500",
    }

    try:
        async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers=headers, params=params)
            resp.raise_for_status()
            data = resp.json()
            return data.get("value", [])
    except Exception as e:
        logger.warning("[ShipmentSync] BC shipment lines fetch failed: %s", e)
        return []


async def _is_shipment_already_synced(db, shipment_key: str) -> bool:
    """Check if a shipment line has already been synced (idempotency guard)."""
    existing = await db[BC_SHIPMENT_SYNC_COLL].find_one(
        {"shipment_key": shipment_key}, {"_id": 0, "shipment_key": 1}
    )
    return existing is not None


async def _mark_shipment_synced(db, shipment_key: str, movement_id: str, line_data: dict):
    """Record that a shipment line has been synced to the inventory ledger."""
    import uuid as _uuid
    await db[BC_SHIPMENT_SYNC_COLL].insert_one({
        "id": str(_uuid.uuid4()),
        "shipment_key": shipment_key,
        "movement_id": movement_id,
        "document_no": line_data.get("documentNo", ""),
        "line_no": line_data.get("lineNo", 0),
        "item_no": line_data.get("number", ""),
        "quantity": line_data.get("quantity", 0),
        "shipment_date": line_data.get("shipmentDate", ""),
        "synced_at": datetime.now(timezone.utc).isoformat(),
    })


async def _update_sync_status(db, shipments_processed: int = 0, error: str = ""):
    """Update the persistent sync status record."""
    now = datetime.now(timezone.utc).isoformat()
    update = {
        "_key": _SYNC_STATUS_KEY,
        "last_sync_at": now,
        "updated_utc": now,
    }
    if error:
        update["last_error"] = error
        update["last_error_at"] = now
    else:
        update["last_error"] = ""

    # Increment today's counter
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    await db.hub_config.update_one(
        {"_key": _SYNC_STATUS_KEY},
        {
            "$set": update,
            "$inc": {"shipments_processed_today": shipments_processed},
            "$setOnInsert": {"today_date": today},
        },
        upsert=True,
    )

    # Reset counter if day rolled over
    status = await db.hub_config.find_one({"_key": _SYNC_STATUS_KEY}, {"_id": 0})
    if status and status.get("today_date") != today:
        await db.hub_config.update_one(
            {"_key": _SYNC_STATUS_KEY},
            {"$set": {"today_date": today, "shipments_processed_today": shipments_processed}},
        )


async def get_sync_status(db) -> dict:
    """Return the current BC shipment sync status."""
    status = await db.hub_config.find_one({"_key": _SYNC_STATUS_KEY}, {"_id": 0})
    if not status:
        return {
            "last_sync_at": None,
            "shipments_processed_today": 0,
            "last_error": "",
        }
    return {
        "last_sync_at": status.get("last_sync_at"),
        "shipments_processed_today": status.get("shipments_processed_today", 0),
        "last_error": status.get("last_error", ""),
    }


async def sync_bc_shipments(db, lookback_hours: int = 24) -> dict:
    """Sync recent BC Sales Shipment Lines into inventory outbound_shipment movements.

    Workflow:
      1. Fetch recent shipment lines from BC (last `lookback_hours` hours).
      2. For each line, build a unique shipment_key (documentNo + lineNo).
      3. Skip lines already synced (idempotency).
      4. Resolve the inventory workspace from the shipment's customer number.
      5. Create an outbound_shipment movement (negative qty_delta).
      6. Mark as synced.

    Returns: {synced: int, skipped: int, errors: [], total_fetched: int}
    """
    result = {"synced": 0, "skipped": 0, "errors": [], "total_fetched": 0}

    since = (datetime.now(timezone.utc) - timedelta(hours=lookback_hours)).isoformat()
    lines = await _fetch_bc_shipment_lines(since)
    result["total_fetched"] = len(lines)

    if not lines:
        await _update_sync_status(db, error="" if lines is not None else "No shipment data returned")
        return result

    for line in lines:
        doc_no = line.get("documentNo", "")
        line_no = line.get("lineNo", 0)
        shipment_key = f"{doc_no}_{line_no}"

        # Idempotency check
        if await _is_shipment_already_synced(db, shipment_key):
            result["skipped"] += 1
            continue

        # Extract line data
        item_no = line.get("number", "") or line.get("No", "")
        description = line.get("description", "") or ""
        quantity = float(line.get("quantity", 0))
        uom = line.get("unitOfMeasureCode", "units") or "units"
        shipment_date = line.get("shipmentDate", "")

        # The sell-to customer number comes from the shipment header
        # In standard BC API, salesShipmentLines may carry sellToCustomerNo
        customer_no = line.get("sellToCustomerNo", "") or line.get("billToCustomerNo", "")

        if not item_no or quantity <= 0:
            result["skipped"] += 1
            continue

        # Resolve inventory workspace
        ws_result = await resolve_inventory_workspace(db, customer_no=customer_no)
        workspace = ws_result.get("workspace")
        if not workspace:
            result["errors"].append(
                f"Shipment {doc_no} line {line_no}: no inventory workspace for customer '{customer_no}'"
            )
            continue

        workspace_id = workspace["id"]

        # The order number is the linked sales order (stored as orderNo in the shipment)
        order_no = line.get("orderNo", doc_no)
        location_code = line.get("locationCode", "MAIN") or "MAIN"

        try:
            mv_result = await create_movement(
                db, workspace_id,
                item=item_no,
                item_description=description[:100],
                warehouse=location_code,
                ownership_type="customer_owned",
                movement_type="outbound_shipment",
                quantity_delta=-quantity,  # Negative: goods leaving warehouse
                unit_of_measure=uom,
                source_type="bc_shipment",
                reference_type="sales_order",
                reference_id=order_no,
                notes=f"BC Shipment {doc_no} line {line_no} (shipped {shipment_date})",
                created_by="bc_shipment_sync",
                skip_balance_check=True,
            )
            if mv_result["success"]:
                await _mark_shipment_synced(db, shipment_key, mv_result["movement"]["id"], line)
                result["synced"] += 1
            else:
                result["errors"].append(f"Shipment {doc_no} line {line_no}: movement creation failed")
        except Exception as e:
            result["errors"].append(f"Shipment {doc_no} line {line_no}: {str(e)}")

    await _update_sync_status(db, shipments_processed=result["synced"])

    logger.info(
        "[ShipmentSync] Completed: synced=%d skipped=%d errors=%d total_fetched=%d",
        result["synced"], result["skipped"], len(result["errors"]), result["total_fetched"],
    )
    return result
