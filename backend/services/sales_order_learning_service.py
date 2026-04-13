"""
GPI Document Hub — Sales Order Learning Service

Reads existing BC sales orders and builds customer posting profiles,
mirroring what posting_pattern_analyzer.py does for AP vendors.

Collections used:
  - customer_posting_profiles  (one doc per customer_no)
  - sales_posting_learning_events  (append-only event log)
  - sales_learning_jobs  (background job status)
"""

import logging
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

MIN_ORDERS_FOR_PROFILE = 3


# =============================================================================
# 1. Per-customer analysis
# =============================================================================

async def analyze_customer_ordering_patterns(
    db,
    customer_no: str,
    orders: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """
    Analyze a list of BC sales order dicts to extract structural patterns.
    Returns the customer profile dict ready for upsert.
    """
    now = datetime.now(timezone.utc).isoformat()

    if len(orders) < MIN_ORDERS_FOR_PROFILE:
        return {
            "customer_no": customer_no,
            "customer_name": _pick_customer_name(orders),
            "status": "insufficient_data",
            "invoices_analyzed": len(orders),
            "last_analyzed": now,
            "template_confidence": "low",
        }

    # ── Aggregate metrics ──
    item_counter = Counter()
    uom_counter = Counter()
    po_patterns = Counter()
    line_count_dist = Counter()
    amounts = []
    ship_to_counter = Counter()
    days_to_ship = []
    bc_order_ids = []

    for order in orders:
        oid = order.get("id", "")
        if oid:
            bc_order_ids.append(oid)

        # Line count
        lines = order.get("salesOrderLines", order.get("lines", []))
        lc = len(lines) if isinstance(lines, list) else 0
        bucket = "3+" if lc >= 3 else str(lc)
        line_count_dist[bucket] += 1

        # Amounts
        total = _safe_float(order.get("totalAmountExcludingTax")
                            or order.get("totalAmountIncludingTax")
                            or order.get("amount"))
        if total > 0:
            amounts.append(total)

        # PO pattern
        ext_doc = order.get("externalDocumentNumber") or order.get("poNumber") or ""
        po_patterns[_classify_po(ext_doc)] += 1

        # Ship-to
        ship_to = order.get("shipToName") or order.get("sellToCustomerName") or ""
        if ship_to:
            ship_to_counter[ship_to] += 1

        # Days to ship
        order_date = order.get("orderDate") or ""
        req_ship = order.get("requestedDeliveryDate") or ""
        if order_date and req_ship and req_ship > order_date:
            try:
                d1 = datetime.fromisoformat(order_date[:10])
                d2 = datetime.fromisoformat(req_ship[:10])
                days_to_ship.append((d2 - d1).days)
            except (ValueError, TypeError):
                pass

        # Line-level stats
        if isinstance(lines, list):
            for line in lines:
                item = (line.get("lineObjectNumber") or line.get("itemId")
                        or line.get("description") or "")
                if item:
                    item_counter[item] += 1
                uom = line.get("unitOfMeasureCode") or line.get("uom") or ""
                if uom:
                    uom_counter[uom] += 1

    n = len(orders)
    avg_lines = sum(int(k.replace("3+", "3")) * v for k, v in line_count_dist.items()) / max(n, 1)

    if n >= 20:
        confidence = "high"
    elif n >= 5:
        confidence = "medium"
    else:
        confidence = "low"

    profile = {
        "customer_no": customer_no,
        "customer_name": _pick_customer_name(orders),
        "status": "analyzed",
        "invoices_analyzed": n,
        "last_analyzed": now,
        "template_confidence": confidence,
        "typical_line_count": round(avg_lines, 1),
        "line_count_distribution": dict(line_count_dist),
        "common_items": [item for item, _ in item_counter.most_common(10)],
        "common_uoms": [u for u, _ in uom_counter.most_common(5)],
        "po_number_pattern": po_patterns.most_common(1)[0][0] if po_patterns else "unknown",
        "typical_order_value": round(sum(amounts) / max(len(amounts), 1), 2) if amounts else 0.0,
        "amount_range": {"min": round(min(amounts), 2), "max": round(max(amounts), 2)} if amounts else {"min": 0, "max": 0},
        "typical_ship_to": ship_to_counter.most_common(1)[0][0] if ship_to_counter else None,
        "days_to_ship_p50": _median(days_to_ship) if days_to_ship else None,
        "bc_order_ids_learned": bc_order_ids,
        "continuous_learning_count": 0,
        "last_continuous_learning": None,
    }

    return profile


# =============================================================================
# 2. Bulk BC backfill
# =============================================================================

async def build_all_customer_posting_profiles(
    db,
    bc_service,
    top_n: int = 50,
) -> Dict[str, Any]:
    """
    Fetch recent BC sales orders, group by customer, analyze each.
    """
    now = datetime.now(timezone.utc).isoformat()
    job = {
        "started_at": now,
        "status": "running",
        "orders_fetched": 0,
        "customers_found": 0,
        "customers_analyzed": 0,
        "errors": 0,
    }
    await db.sales_learning_jobs.insert_one({**job})

    try:
        # Fetch orders from BC
        all_orders = await _fetch_bc_sales_orders(bc_service)
        job["orders_fetched"] = len(all_orders)

        # Group by customer
        by_customer: Dict[str, List[Dict]] = defaultdict(list)
        for order in all_orders:
            cust = order.get("customerNumber") or order.get("sellToCustomerNumber") or ""
            if cust:
                by_customer[cust].append(order)

        job["customers_found"] = len(by_customer)

        # Sort by order count descending, take top_n
        sorted_customers = sorted(by_customer.items(), key=lambda x: len(x[1]), reverse=True)[:top_n]

        for customer_no, orders in sorted_customers:
            if len(orders) < MIN_ORDERS_FOR_PROFILE:
                continue

            try:
                # Check for recent analysis (skip if <7 days old)
                existing = await db.customer_posting_profiles.find_one(
                    {"customer_no": customer_no, "status": "analyzed"},
                    {"_id": 0, "last_analyzed": 1},
                )
                if existing:
                    last = existing.get("last_analyzed", "")
                    if last:
                        try:
                            dt = datetime.fromisoformat(last.replace("Z", "+00:00"))
                            if (datetime.now(timezone.utc) - dt).days < 7:
                                continue
                        except (ValueError, TypeError):
                            pass

                profile = await analyze_customer_ordering_patterns(db, customer_no, orders)
                if profile.get("status") == "analyzed":
                    await db.customer_posting_profiles.update_one(
                        {"customer_no": customer_no},
                        {"$set": profile},
                        upsert=True,
                    )
                    job["customers_analyzed"] += 1

            except Exception as exc:
                job["errors"] += 1
                logger.warning("[SalesLearning] Error analyzing customer %s: %s", customer_no, exc)

        job["status"] = "completed"

    except Exception as exc:
        job["status"] = "failed"
        job["error"] = str(exc)[:500]
        logger.error("[SalesLearning] Backfill failed: %s", exc)

    job["completed_at"] = datetime.now(timezone.utc).isoformat()
    # Remove _id from the initial insert, update in place
    await db.sales_learning_jobs.update_one(
        {"started_at": now},
        {"$set": job},
    )

    logger.info("[SalesLearning] Backfill complete: %d orders, %d customers analyzed, %d errors",
                job["orders_fetched"], job["customers_analyzed"], job["errors"])

    job.pop("_id", None)
    return job


# =============================================================================
# 3. Incremental learning (called after each posted SO)
# =============================================================================

async def learn_from_sales_order_posting(
    db,
    customer_no: str,
    doc: Dict[str, Any],
    so_lines: List[Dict[str, Any]],
    so_result: Dict[str, Any],
) -> None:
    """
    Update a customer's profile incrementally after a successful sales order creation.
    """
    if not customer_no:
        return

    now = datetime.now(timezone.utc).isoformat()

    # Extract features from posted SO
    items = []
    uoms = []
    for line in (so_lines or []):
        item = (line.get("lineObjectNumber") or line.get("itemId")
                or line.get("item_number") or "")
        if item:
            items.append(item)
        uom = line.get("unitOfMeasureCode") or line.get("uom") or ""
        if uom:
            uoms.append(uom)

    amount = _safe_float(so_result.get("totalAmountExcludingTax")
                         or doc.get("amount_float") or 0)
    line_count = len(so_lines) if so_lines else 0

    # Record learning event
    await db.sales_posting_learning_events.insert_one({
        "customer_no": customer_no,
        "doc_id": doc.get("id", ""),
        "event_type": "so_posted",
        "items": items,
        "uoms": uoms,
        "amount": amount,
        "line_count": line_count,
        "learned_at": now,
    })

    # Incremental profile update
    existing = await db.customer_posting_profiles.find_one(
        {"customer_no": customer_no}, {"_id": 0}
    )

    if existing and existing.get("status") == "analyzed":
        n = existing.get("invoices_analyzed", 0) + 1
        old_avg = existing.get("typical_order_value", 0)
        new_avg = round(((old_avg * (n - 1)) + amount) / n, 2) if n > 0 else amount

        # Update range
        arange = existing.get("amount_range", {"min": 0, "max": 0})
        if amount > 0:
            arange["min"] = round(min(arange.get("min", amount), amount), 2)
            arange["max"] = round(max(arange.get("max", amount), amount), 2)

        # Merge common items
        old_items = existing.get("common_items", [])
        merged_items = list(dict.fromkeys(old_items + items))[:15]

        # Confidence
        if n >= 20:
            confidence = "high"
        elif n >= 5:
            confidence = "medium"
        else:
            confidence = "low"

        await db.customer_posting_profiles.update_one(
            {"customer_no": customer_no},
            {"$set": {
                "invoices_analyzed": n,
                "typical_order_value": new_avg,
                "amount_range": arange,
                "common_items": merged_items,
                "template_confidence": confidence,
                "continuous_learning_count": existing.get("continuous_learning_count", 0) + 1,
                "last_continuous_learning": now,
                "last_analyzed": now,
            },
            "$addToSet": {"common_uoms": {"$each": uoms}}},
        )
    else:
        # Create a minimal profile
        await db.customer_posting_profiles.update_one(
            {"customer_no": customer_no},
            {"$set": {
                "customer_no": customer_no,
                "customer_name": doc.get("customer_name", ""),
                "status": "analyzed",
                "invoices_analyzed": 1,
                "last_analyzed": now,
                "template_confidence": "low",
                "typical_line_count": line_count,
                "line_count_distribution": {str(min(line_count, 3)) + ("+" if line_count >= 3 else ""): 1},
                "common_items": items[:10],
                "common_uoms": uoms[:5],
                "po_number_pattern": "unknown",
                "typical_order_value": amount,
                "amount_range": {"min": amount, "max": amount},
                "typical_ship_to": None,
                "days_to_ship_p50": None,
                "bc_order_ids_learned": [],
                "continuous_learning_count": 1,
                "last_continuous_learning": now,
            }},
            upsert=True,
        )

    logger.info("[SalesLearning] Learned from SO posting: customer=%s, items=%s, amount=%.2f",
                customer_no, items, amount)


# =============================================================================
# 4. Detect posted sales order drafts
# =============================================================================

async def detect_posted_sales_drafts(db) -> Dict[str, Any]:
    """
    Find GPI-created SO drafts and check their BC status.
    If posted, mark as learned and record positive completion event.
    """
    docs = await db.hub_documents.find(
        {
            "so_draft_created": True,
            "draft_review_status": {"$nin": ["feedback_synced"]},
        },
        {"_id": 0, "id": 1, "customer_no": 1, "bc_sales_order": 1}
    ).limit(100).to_list(100)

    results = {"checked": 0, "posted_found": 0, "errors": 0}

    for doc_stub in docs:
        doc_id = doc_stub.get("id", "")
        if not doc_id:
            continue
        results["checked"] += 1

        try:
            bc_so = doc_stub.get("bc_sales_order") or {}
            bc_status = bc_so.get("status", "")

            if bc_status.lower() in ("open", "released", "posted"):
                results["posted_found"] += 1

                customer_no = doc_stub.get("customer_no", "")
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "draft_review_status": "feedback_synced",
                        "so_draft_posted_in_bc": True,
                        "so_draft_posted_detected_at": datetime.now(timezone.utc).isoformat(),
                    }}
                )

                await db.sales_posting_learning_events.insert_one({
                    "customer_no": customer_no,
                    "doc_id": doc_id,
                    "event_type": "so_draft_posted_in_bc",
                    "posted_at": datetime.now(timezone.utc).isoformat(),
                    "feedback": "positive_completion",
                    "bc_status": bc_status,
                })

        except Exception as exc:
            results["errors"] += 1
            logger.warning("[SalesLearning] Error checking SO draft %s: %s", doc_id[:8], exc)

    logger.info("[SalesLearning] SO draft detection: checked=%d, posted=%d",
                results["checked"], results["posted_found"])
    return results


# =============================================================================
# Helpers
# =============================================================================

async def _fetch_bc_sales_orders(bc_service, max_pages: int = 5) -> List[Dict]:
    """Fetch recent sales orders from BC Production, paginating."""
    from services.bc_api_helpers import get_bc_sales_orders
    try:
        orders = await get_bc_sales_orders()
        if isinstance(orders, list):
            return orders
        return []
    except Exception as exc:
        logger.error("[SalesLearning] BC fetch failed: %s", exc)
        raise


def _pick_customer_name(orders: List[Dict]) -> str:
    names = [o.get("customerName") or o.get("sellToCustomerName") or "" for o in orders]
    c = Counter(n for n in names if n)
    return c.most_common(1)[0][0] if c else ""


def _classify_po(po: str) -> str:
    if not po:
        return "unknown"
    po = po.strip()
    if po.isdigit():
        return "numeric"
    if po[0].isalpha() and any(c.isdigit() for c in po):
        return "prefixed"
    if any(c.isdigit() for c in po):
        return "alphanumeric"
    return "unknown"


def _safe_float(val) -> float:
    if val is None:
        return 0.0
    try:
        return float(str(val).replace("$", "").replace(",", "").strip())
    except (ValueError, TypeError):
        return 0.0


def _median(vals: List[int]) -> int:
    if not vals:
        return 0
    s = sorted(vals)
    n = len(s)
    if n % 2 == 0:
        return (s[n // 2 - 1] + s[n // 2]) // 2
    return s[n // 2]
