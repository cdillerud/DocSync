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
from services.inventory_ledger_service import (
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
