"""
Order Line Pattern Learning Service

Learns dunnage/ancillary line patterns from historical BC sales orders.
When a new PO comes in for a known item, the system auto-suggests
the dunnage lines (pallets, tier sheets, etc.) that always accompany it.

Two pattern types:
  1. **Product-level**: Tied to a specific trigger item (e.g., C-9874 → pallets)
     - trigger_item_no = "C-9874-10001833"
     - qty calculated via qty_ratio * trigger_item_qty
  2. **Customer-level**: Applies to ALL orders for a customer (e.g., Energy Surcharge)
     - trigger_item_no = "*"
     - qty is fixed (e.g., 1 EA), price pulled from most recent BC order

Pattern structure:
{
    "customer_no": "C-10250",
    "trigger_item_no": "C-9874-10001833",         # "*" = customer-level
    "trigger_item_pattern": "C-9874-*",            # Wildcard for similar items
    "associated_lines": [
        {
            "line_type": "Item",
            "item_no": "OIPALLET",
            "description": "OI Pallet - RETURN REQUIRED",
            "qty_ratio": 0.354,                      # qty = trigger_qty * ratio (product-level)
            "fixed_qty": null,                        # or fixed qty (customer-level)
            "unit_price": 0,
            "occurrences": 12,
            "frequency": 0.80,
        },
    ],
    "total_orders_analyzed": 15,
    "confidence": 0.80,
    "last_updated": "2026-03-25T..."
}
"""

import logging
import math
import re
from datetime import datetime, timezone

logger = logging.getLogger(__name__)


async def learn_patterns_from_history(db, customer_no: str, limit: int = 100) -> dict:
    """Analyze historical BC sales orders for a customer to learn dunnage patterns.

    Looks at completed sales orders and identifies which ancillary lines
    (dunnage, comments, surcharges) consistently accompany main item lines.

    Returns: { patterns_learned: int, patterns: [...] }
    """
    # Get historical orders from bc_reference_cache or a dedicated collection
    orders = await db.bc_sales_orders_cache.find(
        {"customerNumber": customer_no},
        {"_id": 0}
    ).sort("orderDate", -1).limit(limit).to_list(limit)

    if not orders:
        logger.info("[PatternLearn] No historical orders for customer %s", customer_no)
        return {"patterns_learned": 0, "patterns": []}

    # Build item → associated lines map
    item_associations = {}  # trigger_item_no → { line_key → { count, examples } }

    for order in orders:
        lines = order.get("salesOrderLines", order.get("lines", []))
        if not lines:
            continue

        # Identify "main" items (priced items) vs "ancillary" items (zero-price, comments)
        main_items = []
        ancillary_items = []

        for line in lines:
            line_type = line.get("lineType", line.get("lineObjectType", ""))
            item_no = line.get("lineObjectNumber", line.get("number", ""))
            unit_price = float(line.get("unitPrice", 0) or 0)
            qty = float(line.get("quantity", 0) or 0)

            if line_type == "Comment" or (not item_no and line.get("description")):
                ancillary_items.append({
                    "type": "Comment",
                    "item_no": "",
                    "description": line.get("description", ""),
                    "qty": 0,
                    "unit_price": 0,
                })
            elif unit_price > 0 and qty > 0:
                main_items.append({
                    "type": "Item",
                    "item_no": item_no,
                    "description": line.get("description", ""),
                    "qty": qty,
                    "unit_price": unit_price,
                    "uom": line.get("unitOfMeasureCode", ""),
                })
            elif item_no and unit_price == 0:
                ancillary_items.append({
                    "type": "Item",
                    "item_no": item_no,
                    "description": line.get("description", ""),
                    "qty": qty,
                    "unit_price": 0,
                    "uom": line.get("unitOfMeasureCode", ""),
                })

        # For each main item, associate the ancillary items
        for main in main_items:
            key = main["item_no"]
            if key not in item_associations:
                item_associations[key] = {"total_orders": 0, "associations": {}}

            item_associations[key]["total_orders"] += 1

            for anc in ancillary_items:
                anc_key = anc.get("item_no") or f"comment:{anc['description'][:50]}"
                if anc_key not in item_associations[key]["associations"]:
                    item_associations[key]["associations"][anc_key] = {
                        "type": anc["type"],
                        "item_no": anc.get("item_no", ""),
                        "description": anc["description"],
                        "count": 0,
                        "qty_ratios": [],
                        "fixed_qtys": [],
                        "unit_price": anc.get("unit_price", 0),
                    }

                assoc = item_associations[key]["associations"][anc_key]
                assoc["count"] += 1

                # Track qty ratio (ancillary_qty / main_qty)
                if main["qty"] > 0 and anc.get("qty", 0) > 0:
                    ratio = anc["qty"] / main["qty"]
                    assoc["qty_ratios"].append(ratio)
                elif anc.get("qty", 0) > 0:
                    assoc["fixed_qtys"].append(anc["qty"])

    # Convert to patterns (only keep associations seen in >=50% of orders)
    patterns = []
    now = datetime.now(timezone.utc).isoformat()

    for trigger_item, data in item_associations.items():
        total = data["total_orders"]
        if total < 2:
            continue

        associated_lines = []
        for anc_key, assoc in data["associations"].items():
            frequency = assoc["count"] / total
            if frequency < 0.5:
                continue  # Skip if seen in less than 50% of orders

            # Calculate median qty ratio or fixed qty
            qty_ratio = None
            fixed_qty = None
            if assoc["qty_ratios"]:
                sorted_ratios = sorted(assoc["qty_ratios"])
                mid = len(sorted_ratios) // 2
                qty_ratio = sorted_ratios[mid]
            elif assoc["fixed_qtys"]:
                sorted_qtys = sorted(assoc["fixed_qtys"])
                mid = len(sorted_qtys) // 2
                fixed_qty = sorted_qtys[mid]

            associated_lines.append({
                "line_type": assoc["type"],
                "item_no": assoc["item_no"],
                "description": assoc["description"],
                "qty_ratio": qty_ratio,
                "fixed_qty": fixed_qty,
                "unit_price": assoc["unit_price"],
                "occurrences": assoc["count"],
                "frequency": round(frequency, 2),
            })

        if not associated_lines:
            continue

        # Generate wildcard pattern from item number
        item_pattern = _make_item_pattern(trigger_item)

        pattern = {
            "customer_no": customer_no,
            "trigger_item_no": trigger_item,
            "trigger_item_pattern": item_pattern,
            "associated_lines": sorted(associated_lines, key=lambda x: -x["frequency"]),
            "total_orders_analyzed": total,
            "confidence": round(max(al["frequency"] for al in associated_lines), 2),
            "last_updated": now,
        }
        patterns.append(pattern)

        # Upsert to DB
        await db.order_line_patterns.update_one(
            {"customer_no": customer_no, "trigger_item_no": trigger_item},
            {"$set": pattern},
            upsert=True,
        )

    logger.info(
        "[PatternLearn] Customer %s: analyzed %d orders, learned %d patterns",
        customer_no, len(orders), len(patterns),
    )
    return {"patterns_learned": len(patterns), "patterns": patterns}


async def learn_from_bc_posted_orders(
    db,
    customer_no: str,
    order_limit: int = 10,
    threshold: float = 0.75,
) -> dict:
    """Learn customer-level patterns from BC posted sales invoices/orders.

    Queries BC for the last N posted orders for this customer,
    analyzes which non-PO line items appear consistently (≥threshold),
    and saves them as customer-level patterns (trigger_item_no = "*").

    For items like ENERGY surcharge that appear in 8 of 10 orders,
    the most recent unit price is used as the default.

    Returns: { patterns_learned: int, customer_patterns: [...] }
    """
    import os
    demo_mode = os.environ.get("DEMO_MODE", "true").lower() == "true"

    all_order_lines = []  # list of list-of-lines per order

    if not demo_mode:
        try:
            from services.gpi_integration_service import (
                _api_request, BC_READ_ENVIRONMENT, HAS_CREDENTIALS,
            )
            if not HAS_CREDENTIALS:
                logger.info("[BCLearn] No BC credentials — skipping live query for %s", customer_no)
            else:
                # Query posted sales invoices for this customer (READ environment)
                result = await _api_request(
                    "GET",
                    "salesInvoices",
                    params={
                        "$filter": f"customerNumber eq '{customer_no}'",
                        "$orderby": "invoiceDate desc",
                        "$top": str(order_limit),
                        "$expand": "salesInvoiceLines",
                    },
                    environment=BC_READ_ENVIRONMENT,
                )
                invoices = result.get("value", [])
                logger.info("[BCLearn] Fetched %d posted invoices for %s", len(invoices), customer_no)

                for inv in invoices:
                    lines = inv.get("salesInvoiceLines", [])
                    all_order_lines.append(lines)
        except Exception as e:
            logger.warning("[BCLearn] BC API error for %s: %s — falling back to cached data", customer_no, str(e))

    # Fallback: check local cache
    if not all_order_lines:
        cached_orders = await db.bc_sales_orders_cache.find(
            {"customerNumber": customer_no},
            {"_id": 0},
        ).sort("orderDate", -1).limit(order_limit).to_list(order_limit)

        for order in cached_orders:
            lines = order.get("salesOrderLines", order.get("lines", []))
            if lines:
                all_order_lines.append(lines)

    total_orders = len(all_order_lines)
    if total_orders < 2:
        logger.info("[BCLearn] Not enough orders (%d) for %s to learn patterns", total_orders, customer_no)
        return {"patterns_learned": 0, "customer_patterns": []}

    # --- Count frequency of every item across all orders ---
    # Also track: all PO-line items (the "main" products) vs recurring extras
    item_frequency = {}  # item_no → { count, descriptions, qtys, prices, line_types }

    for order_lines in all_order_lines:
        seen_in_order = set()
        for line in order_lines:
            item_no = (
                line.get("lineObjectNumber")
                or line.get("number")
                or line.get("itemId", "")
            )
            if not item_no or item_no in seen_in_order:
                continue
            seen_in_order.add(item_no)

            if item_no not in item_frequency:
                item_frequency[item_no] = {
                    "count": 0,
                    "descriptions": [],
                    "qtys": [],
                    "prices": [],
                    "line_type": line.get("lineType", line.get("lineObjectType", "Item")),
                }
            freq = item_frequency[item_no]
            freq["count"] += 1
            desc = line.get("description", "")
            if desc and desc not in freq["descriptions"]:
                freq["descriptions"].append(desc)
            qty = float(line.get("quantity", 0) or 0)
            if qty:
                freq["qtys"].append(qty)
            price = float(line.get("unitPrice", 0) or 0)
            if price:
                freq["prices"].append(price)

    # --- Identify customer-level patterns: items above threshold ---
    now = datetime.now(timezone.utc).isoformat()
    customer_lines = []

    for item_no, freq in item_frequency.items():
        frequency = freq["count"] / total_orders
        if frequency < threshold:
            continue

        # Use most recent price (last in the list since orders are sorted desc)
        latest_price = freq["prices"][-1] if freq["prices"] else 0
        # Use most common qty (median)
        fixed_qty = None
        if freq["qtys"]:
            sorted_q = sorted(freq["qtys"])
            fixed_qty = sorted_q[len(sorted_q) // 2]

        customer_lines.append({
            "line_type": freq["line_type"] if freq["line_type"] in ("Item", "G/L Account") else "Item",
            "item_no": item_no,
            "description": freq["descriptions"][0] if freq["descriptions"] else item_no,
            "qty_ratio": None,
            "fixed_qty": fixed_qty or 1,
            "unit_price": latest_price,
            "occurrences": freq["count"],
            "frequency": round(frequency, 2),
        })

    if not customer_lines:
        logger.info("[BCLearn] No customer-level patterns met threshold (%.0f%%) for %s", threshold * 100, customer_no)
        return {"patterns_learned": 0, "customer_patterns": []}

    # Save as a single customer-level pattern
    pattern = {
        "customer_no": customer_no,
        "trigger_item_no": "*",
        "trigger_item_pattern": "*",
        "associated_lines": sorted(customer_lines, key=lambda x: -x["frequency"]),
        "total_orders_analyzed": total_orders,
        "confidence": round(max(cl["frequency"] for cl in customer_lines), 2),
        "last_updated": now,
    }

    await db.order_line_patterns.update_one(
        {"customer_no": customer_no, "trigger_item_no": "*"},
        {"$set": pattern},
        upsert=True,
    )

    logger.info(
        "[BCLearn] Customer %s: analyzed %d orders, learned %d customer-level lines (threshold %.0f%%)",
        customer_no, total_orders, len(customer_lines), threshold * 100,
    )
    return {"patterns_learned": len(customer_lines), "customer_patterns": customer_lines}


async def get_suggested_lines(db, customer_no: str, line_items: list) -> list:
    """Given a customer and their PO line items, suggest dunnage lines based on learned patterns.

    Handles two pattern types:
      - Product-level (trigger_item_no = specific item): qty calculated from trigger item qty
      - Customer-level (trigger_item_no = "*"): fixed qty/price, applies to all orders
    Returns a list of suggested lines to add to the sales order.
    """
    if not customer_no or not line_items:
        return []

    # Look up patterns for this customer
    patterns = await db.order_line_patterns.find(
        {"customer_no": customer_no},
        {"_id": 0},
    ).to_list(100)

    if not patterns:
        return []

    suggestions = []
    seen_keys = set()

    # --- Product-level patterns (tied to specific trigger items) ---
    product_patterns = [p for p in patterns if p.get("trigger_item_no") != "*"]
    for item in line_items:
        item_no = item.get("item_no") or item.get("lineObjectNumber") or ""
        item_qty = float(item.get("quantity") or item.get("qty") or 0)

        for pattern in product_patterns:
            if not _item_matches(item_no, pattern["trigger_item_no"], pattern.get("trigger_item_pattern")):
                continue

            for assoc in pattern["associated_lines"]:
                dedup_key = f"{assoc['item_no']}:{assoc['description'][:30]}"
                if dedup_key in seen_keys:
                    continue
                seen_keys.add(dedup_key)

                suggested_qty = 0
                if assoc.get("qty_ratio") and item_qty > 0:
                    suggested_qty = round(item_qty * assoc["qty_ratio"])
                elif assoc.get("fixed_qty"):
                    suggested_qty = assoc["fixed_qty"]

                suggestions.append({
                    "line_type": assoc["line_type"],
                    "item_no": assoc["item_no"],
                    "description": assoc["description"],
                    "quantity": suggested_qty,
                    "unit_price": assoc.get("unit_price", 0),
                    "source": "learned_pattern",
                    "confidence": pattern["confidence"],
                    "occurrences": assoc["occurrences"],
                    "frequency": assoc["frequency"],
                    "trigger_item": pattern["trigger_item_no"],
                    "qty_ratio": assoc.get("qty_ratio"),
                    "fixed_qty": assoc.get("fixed_qty"),
                })

    # --- Customer-level patterns (trigger_item_no = "*") ---
    customer_patterns = [p for p in patterns if p.get("trigger_item_no") == "*"]
    for pattern in customer_patterns:
        for assoc in pattern["associated_lines"]:
            dedup_key = f"{assoc['item_no']}:{assoc['description'][:30]}"
            if dedup_key in seen_keys:
                continue
            seen_keys.add(dedup_key)

            suggestions.append({
                "line_type": assoc["line_type"],
                "item_no": assoc.get("item_no", ""),
                "description": assoc["description"],
                "quantity": assoc.get("fixed_qty") or assoc.get("qty_ratio") or 0,
                "unit_price": assoc.get("unit_price", 0),
                "source": "learned_pattern",
                "confidence": pattern["confidence"],
                "occurrences": assoc["occurrences"],
                "frequency": assoc["frequency"],
                "trigger_item": "*",
                "qty_ratio": None,
                "fixed_qty": assoc.get("fixed_qty"),
            })

    logger.info(
        "[PatternSuggest] Customer %s: %d items → %d suggestions (%d product, %d customer patterns)",
        customer_no, len(line_items), len(suggestions), len(product_patterns), len(customer_patterns),
    )
    return suggestions


def _make_item_pattern(item_no: str) -> str:
    """Generate a wildcard pattern from an item number.
    E.g., 'C-9874-10001833' → 'C-9874-*'
    """
    if not item_no:
        return "*"
    parts = re.split(r'[-_]', item_no)
    if len(parts) >= 2:
        return f"{parts[0]}-{parts[1]}-*"
    return f"{item_no[:4]}*"


def _item_matches(item_no: str, trigger_exact: str, trigger_pattern: str = None) -> bool:
    """Check if an item matches a trigger (exact or wildcard pattern)."""
    if not item_no:
        return False
    if item_no == trigger_exact:
        return True
    if trigger_pattern:
        regex = trigger_pattern.replace("*", ".*")
        return bool(re.match(regex, item_no, re.IGNORECASE))
    return False
