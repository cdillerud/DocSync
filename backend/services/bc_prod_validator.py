"""
GPI Document Hub — Inside Sales Pilot BC Production Validator

Read-only cross-validation of pilot-ingested documents against
Business Central Production data.  Never writes to BC.

Checks:
  1. Customer match — does the extracted customer exist in BC?
  2. PO / Order lookup — does the extracted PO map to a real BC sales order?
  3. Item validation — are extracted items known in BC's item catalog?
  4. Amount range — is the total within normal range for this customer?
"""

import logging
import os
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from deps import get_db

logger = logging.getLogger(__name__)


async def validate_document_against_bc(doc_id: str) -> Dict[str, Any]:
    """
    Run read-only BC Production validation on a single pilot document.

    Returns a validation result dict that is persisted on the document
    as `bc_prod_validation`.  Never makes write calls.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": f"Document {doc_id} not found"}

    extraction = doc.get("sales_pilot_extraction") or {}
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}

    result: Dict[str, Any] = {
        "document_id": doc_id,
        "validated_at": datetime.now(timezone.utc).isoformat(),
        "customer_match": None,
        "order_lookup": None,
        "item_validation": None,
        "amount_check": None,
        "overall_score": 0,
        "checks_passed": 0,
        "checks_total": 0,
    }

    # ── 1. Customer Match ───────────────────────────────────
    customer_name = (
        extraction.get("customer_name")
        or ef.get("customer")
        or nf.get("customer")
    )
    customer_no = (
        doc.get("matched_customer_no")
        or doc.get("customer_no")
        or nf.get("customer_no")
    )
    result["customer_match"] = await _check_customer(db, customer_name, customer_no)
    result["checks_total"] += 1
    if result["customer_match"].get("found"):
        result["checks_passed"] += 1

    # ── 2. PO / Order Lookup ────────────────────────────────
    po_number = (
        extraction.get("po_number")
        or ef.get("po_number")
        or nf.get("customer_po")
    )
    order_number = (
        extraction.get("order_number")
        or ef.get("order_number")
        or nf.get("order_number")
    )
    result["order_lookup"] = await _check_order(
        db, po_number, order_number,
        result["customer_match"].get("bc_customer_no"),
    )
    result["checks_total"] += 1
    if result["order_lookup"].get("found"):
        result["checks_passed"] += 1

    # ── 3. Item Validation ──────────────────────────────────
    items = extraction.get("item_numbers") or ef.get("items") or []
    line_items = nf.get("line_items") or doc.get("line_items") or []
    # Also pull item descriptions from line preview
    item_descriptions = []
    for li in line_items:
        desc = li.get("description") or li.get("item_description") or ""
        if desc:
            item_descriptions.append(desc)
    result["item_validation"] = await _check_items(db, items, item_descriptions)
    result["checks_total"] += 1
    if result["item_validation"].get("match_rate", 0) > 0:
        result["checks_passed"] += 1

    # ── 4. Amount Range Check ───────────────────────────────
    amount = (
        nf.get("amount_float")
        or ef.get("total_amount")
        or doc.get("total_amount")
    )
    if amount and result["customer_match"].get("bc_customer_no"):
        result["amount_check"] = await _check_amount_range(
            db,
            result["customer_match"]["bc_customer_no"],
            float(amount) if amount else 0,
        )
        result["checks_total"] += 1
        if result["amount_check"].get("within_range"):
            result["checks_passed"] += 1
    else:
        result["amount_check"] = {"skipped": True, "reason": "No amount or customer"}

    # Overall score
    if result["checks_total"] > 0:
        result["overall_score"] = round(
            result["checks_passed"] / result["checks_total"] * 100
        )

    # Persist on the document
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {"bc_prod_validation": result}},
    )

    logger.info(
        "[BCProdValidation] doc=%s score=%d%% (%d/%d) customer=%s order=%s",
        doc_id[:8],
        result["overall_score"],
        result["checks_passed"],
        result["checks_total"],
        result["customer_match"].get("found"),
        result["order_lookup"].get("found"),
    )
    return result


# ─────────────────────────────────────────────────────────────
# CHECK 1: Customer
# ─────────────────────────────────────────────────────────────

async def _check_customer(
    db, customer_name: Optional[str], customer_no: Optional[str],
) -> Dict[str, Any]:
    """Look up the customer in the BC reference cache."""
    if not customer_name and not customer_no:
        return {"found": False, "reason": "No customer name or number extracted"}

    from services.bc_reference_cache_service import get_cache_service

    cache = get_cache_service()
    if not cache:
        # Fallback: search the cache collection directly
        return await _check_customer_direct(db, customer_name, customer_no)

    # Try by customer_no first
    if customer_no:
        results = await cache.search_by_customer(customer_no, ["customer"])
        if results:
            r = results[0]
            return {
                "found": True,
                "bc_customer_no": r.get("bc_customer_no"),
                "bc_customer_name": r.get("bc_customer_name") or r.get("displayName"),
                "match_method": "customer_no_exact",
            }

    # Try by name in the cache
    if customer_name:
        results = await db.bc_reference_cache.find(
            {
                "bc_entity_type": "customer",
                "$or": [
                    {"bc_customer_name": {"$regex": customer_name, "$options": "i"}},
                    {"displayName": {"$regex": customer_name, "$options": "i"}},
                ],
            },
            {"_id": 0, "bc_customer_no": 1, "bc_customer_name": 1, "displayName": 1},
        ).limit(5).to_list(5)

        if results:
            r = results[0]
            return {
                "found": True,
                "bc_customer_no": r.get("bc_customer_no"),
                "bc_customer_name": r.get("bc_customer_name") or r.get("displayName"),
                "match_method": "name_search",
                "candidates": len(results),
            }

    return {
        "found": False,
        "searched_name": customer_name,
        "searched_no": customer_no,
        "reason": "No matching customer in BC reference cache",
    }


async def _check_customer_direct(
    db, customer_name: Optional[str], customer_no: Optional[str],
) -> Dict[str, Any]:
    """Direct DB search when cache service isn't available."""
    query = {"bc_entity_type": "customer"}
    conditions = []
    if customer_no:
        conditions.append({"bc_customer_no": customer_no})
    if customer_name:
        conditions.append({"bc_customer_name": {"$regex": customer_name, "$options": "i"}})
        conditions.append({"displayName": {"$regex": customer_name, "$options": "i"}})
    if not conditions:
        return {"found": False, "reason": "Nothing to search"}
    query["$or"] = conditions

    result = await db.bc_reference_cache.find_one(query, {"_id": 0})
    if result:
        return {
            "found": True,
            "bc_customer_no": result.get("bc_customer_no"),
            "bc_customer_name": result.get("bc_customer_name") or result.get("displayName"),
            "match_method": "direct_cache_search",
        }
    return {"found": False, "reason": "Not found in BC cache"}


# ─────────────────────────────────────────────────────────────
# CHECK 2: Order / PO Lookup
# ─────────────────────────────────────────────────────────────

async def _check_order(
    db,
    po_number: Optional[str],
    order_number: Optional[str],
    bc_customer_no: Optional[str],
) -> Dict[str, Any]:
    """Search BC reference cache for a matching sales order."""
    refs_to_try = [r for r in [po_number, order_number] if r]
    if not refs_to_try:
        return {"found": False, "reason": "No PO or order number extracted"}

    from services.bc_reference_cache_service import get_cache_service

    cache = get_cache_service()

    for ref in refs_to_try:
        # Try cache service multi-search
        if cache:
            results = await cache.search_multi(ref, ["sales_order"])
            if results:
                r = results[0]
                return {
                    "found": True,
                    "bc_order_no": r.get("bc_document_no"),
                    "bc_external_ref": r.get("bc_external_document_no"),
                    "bc_customer_no": r.get("bc_customer_no"),
                    "bc_customer_name": r.get("bc_customer_name"),
                    "bc_status": r.get("bc_status"),
                    "bc_amount": r.get("bc_amount"),
                    "match_method": "cache_multi_search",
                    "matched_ref": ref,
                }

        # Direct DB fallback
        direct = await db.bc_reference_cache.find_one(
            {
                "bc_entity_type": "sales_order",
                "$or": [
                    {"bc_document_no": ref},
                    {"bc_external_document_no": ref},
                    {"bc_order_number": ref},
                ],
            },
            {"_id": 0},
        )
        if direct:
            return {
                "found": True,
                "bc_order_no": direct.get("bc_document_no"),
                "bc_external_ref": direct.get("bc_external_document_no"),
                "bc_customer_no": direct.get("bc_customer_no"),
                "bc_status": direct.get("bc_status"),
                "bc_amount": direct.get("bc_amount"),
                "match_method": "direct_cache_search",
                "matched_ref": ref,
            }

    # Try live BC API as last resort (read-only)
    try:
        from services.bc_api_helpers import get_bc_sales_orders
        for ref in refs_to_try:
            orders = await get_bc_sales_orders(order_no=ref)
            if orders:
                o = orders[0]
                return {
                    "found": True,
                    "bc_order_no": o.get("number"),
                    "bc_customer_name": o.get("customerName"),
                    "bc_status": o.get("status"),
                    "bc_amount": o.get("totalAmountIncludingVAT") or o.get("totalAmountIncludingTax"),
                    "match_method": "live_bc_api",
                    "matched_ref": ref,
                }
    except Exception as e:
        logger.debug("[BCProdValidation] Live BC order search failed: %s", e)

    return {
        "found": False,
        "searched_refs": refs_to_try,
        "reason": "No matching order found in BC cache or API",
    }


# ─────────────────────────────────────────────────────────────
# CHECK 3: Item Validation
# ─────────────────────────────────────────────────────────────

async def _check_items(
    db,
    item_numbers: List[str],
    item_descriptions: List[str],
) -> Dict[str, Any]:
    """Check if extracted items exist in the BC item catalog."""
    all_refs = [i for i in item_numbers if i] + [d for d in item_descriptions if d]
    if not all_refs:
        return {"match_rate": 0, "skipped": True, "reason": "No items extracted"}

    matched = []
    unmatched = []

    for ref in all_refs[:20]:  # Cap to avoid excessive queries
        # Search bc_reference_cache for items
        item_hit = await db.bc_reference_cache.find_one(
            {
                "bc_entity_type": "item",
                "$or": [
                    {"bc_document_no": ref},
                    {"displayName": {"$regex": ref[:30], "$options": "i"}},
                    {"description": {"$regex": ref[:30], "$options": "i"}},
                ],
            },
            {"_id": 0, "bc_document_no": 1, "displayName": 1, "description": 1},
        )
        if item_hit:
            matched.append({
                "extracted": ref[:50],
                "bc_item_no": item_hit.get("bc_document_no"),
                "bc_description": item_hit.get("displayName") or item_hit.get("description"),
            })
        else:
            unmatched.append(ref[:50])

    total = len(matched) + len(unmatched)
    return {
        "match_rate": round(len(matched) / total * 100) if total > 0 else 0,
        "matched_count": len(matched),
        "unmatched_count": len(unmatched),
        "matched": matched[:10],
        "unmatched": unmatched[:10],
    }


# ─────────────────────────────────────────────────────────────
# CHECK 4: Amount Range
# ─────────────────────────────────────────────────────────────

async def _check_amount_range(
    db, bc_customer_no: str, amount: float,
) -> Dict[str, Any]:
    """Check if the amount is within the historical range for this customer."""
    if not amount or amount <= 0:
        return {"within_range": True, "reason": "No amount to check"}

    # Look at customer posting profile for typical range
    profile = await db.customer_posting_profiles.find_one(
        {"customer_no": bc_customer_no, "status": "analyzed"},
        {"_id": 0, "typical_order_value": 1, "amount_range": 1},
    )

    if not profile:
        # No profile — check recent BC orders for this customer
        recent_orders = await db.bc_reference_cache.find(
            {"bc_entity_type": "sales_order", "bc_customer_no": bc_customer_no},
            {"_id": 0, "bc_amount": 1},
        ).limit(20).to_list(20)

        if not recent_orders:
            return {
                "within_range": True,
                "reason": "No historical data — cannot compare",
                "amount": amount,
            }

        amounts = [
            float(o["bc_amount"])
            for o in recent_orders
            if o.get("bc_amount") and float(o.get("bc_amount", 0)) > 0
        ]
        if not amounts:
            return {"within_range": True, "reason": "No amounts in history", "amount": amount}

        avg = sum(amounts) / len(amounts)
        mn = min(amounts)
        mx = max(amounts)
    else:
        ar = profile.get("amount_range") or {}
        avg = profile.get("typical_order_value") or ar.get("median") or 0
        mn = ar.get("min", 0)
        mx = ar.get("max", 0)

    if mn == 0 and mx == 0:
        return {"within_range": True, "reason": "Insufficient range data", "amount": amount}

    # Allow 50% margin beyond historical range
    lower = mn * 0.5
    upper = mx * 1.5
    within = lower <= amount <= upper

    return {
        "within_range": within,
        "amount": amount,
        "historical_min": round(mn, 2),
        "historical_max": round(mx, 2),
        "historical_avg": round(avg, 2),
        "allowed_range": f"${lower:,.2f} – ${upper:,.2f}",
        "orders_in_history": len(amounts) if not profile else "profile",
    }


# ─────────────────────────────────────────────────────────────
# BATCH VALIDATION
# ─────────────────────────────────────────────────────────────

async def validate_all_pilot_documents() -> Dict[str, Any]:
    """Run BC Production validation on all pilot documents that haven't been validated yet."""
    db = get_db()
    docs = await db.hub_documents.find(
        {
            "inside_sales_pilot": True,
            "$or": [
                {"bc_prod_validation": {"$exists": False}},
                {"bc_prod_validation": None},
            ],
        },
        {"_id": 0, "id": 1},
    ).to_list(200)

    results = {"total": len(docs), "validated": 0, "errors": 0, "scores": []}
    for doc in docs:
        try:
            r = await validate_document_against_bc(doc["id"])
            results["validated"] += 1
            results["scores"].append(r.get("overall_score", 0))
        except Exception as e:
            results["errors"] += 1
            logger.error("[BCProdValidation] Error on %s: %s", doc["id"][:8], e)

    if results["scores"]:
        results["avg_score"] = round(sum(results["scores"]) / len(results["scores"]))
    return results
