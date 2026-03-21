"""
GPI Document Hub - Sales Rep Assignment Service

Resolves the sales representative for a given customer by:
  1. Checking the customer_rep_overrides collection (manual overrides first).
  2. Falling back to the BC reference cache: customer → salesperson_code → salesperson record.

Also provides:
  - sync_reps_from_bc(): triggers cache sync for customers + salespeople only.
  - list_rep_assignments(): aggregates rep→customer mappings from the cache.
  - override_rep_for_customer(): stores a manual rep override.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger(__name__)

OVERRIDES_COLL = "customer_rep_overrides"


# =========================================================================
# Core Lookup
# =========================================================================

async def get_rep_for_customer(db, customer_no: str) -> Optional[Dict[str, Any]]:
    """Look up the sales rep assigned to a customer.

    Resolution order:
      1. Manual override in customer_rep_overrides collection.
      2. BC reference cache: customer record → salesperson_code → salesperson record.

    Returns {rep_email, rep_name, salesperson_code, source} or None.
    """
    if not customer_no:
        return None

    customer_no = customer_no.strip()

    # 1. Check overrides first
    override = await db[OVERRIDES_COLL].find_one(
        {"customer_no": customer_no, "active": True},
        {"_id": 0},
    )
    if override:
        return {
            "rep_email": override.get("rep_email", ""),
            "rep_name": override.get("rep_name", ""),
            "salesperson_code": override.get("salesperson_code", ""),
            "source": "override",
        }

    # 2. Look up customer in BC reference cache
    customer_rec = await db.bc_reference_cache.find_one(
        {"bc_entity_type": "customer", "bc_customer_no": customer_no},
        {"_id": 0},
    )
    if not customer_rec:
        # Try case-insensitive
        customer_rec = await db.bc_reference_cache.find_one(
            {
                "bc_entity_type": "customer",
                "bc_document_no": {"$regex": f"^{customer_no}$", "$options": "i"},
            },
            {"_id": 0},
        )

    if not customer_rec:
        return None

    sp_code = customer_rec.get("salesperson_code", "")
    if not sp_code:
        # Customer exists but has no salesperson code
        return {
            "rep_email": "",
            "rep_name": "",
            "salesperson_code": "",
            "source": "bc_cache",
            "note": "customer has no salesperson_code in BC",
        }

    # 3. Look up salesperson by code
    sp_rec = await db.bc_reference_cache.find_one(
        {"bc_entity_type": "salesperson", "code": sp_code},
        {"_id": 0},
    )
    if not sp_rec:
        # Salesperson code exists on customer but salesperson record not cached yet
        return {
            "rep_email": "",
            "rep_name": "",
            "salesperson_code": sp_code,
            "source": "bc_cache",
            "note": f"salesperson_code '{sp_code}' not found in cache",
        }

    return {
        "rep_email": sp_rec.get("email", ""),
        "rep_name": sp_rec.get("name", ""),
        "salesperson_code": sp_code,
        "source": "bc_cache",
    }


# =========================================================================
# Sync
# =========================================================================

async def sync_reps_from_bc(db) -> Dict[str, Any]:
    """Trigger BC reference cache sync for customers and salespeople only.

    Returns sync result with counts per entity type.
    """
    from services.bc_reference_cache_service import get_cache_service

    svc = get_cache_service()
    if not svc:
        return {"status": "error", "error": "BC reference cache service not initialized"}

    result = await svc.sync_entities(["customers", "salespeople"])
    return result


# =========================================================================
# List Assignments
# =========================================================================

async def list_rep_assignments(db) -> List[Dict[str, Any]]:
    """Aggregate rep assignments from the BC reference cache.

    For each distinct salesperson_code found on customer records,
    returns: {salesperson_code, rep_name, rep_email, customer_count, customers[]}.
    """
    # Aggregate: group customers by salesperson_code
    pipeline = [
        {"$match": {"bc_entity_type": "customer", "salesperson_code": {"$ne": ""}}},
        {"$group": {
            "_id": "$salesperson_code",
            "customer_count": {"$sum": 1},
            "customers": {"$push": {
                "customer_no": "$bc_customer_no",
                "customer_name": "$bc_customer_name",
            }},
        }},
        {"$sort": {"_id": 1}},
    ]

    raw = await db.bc_reference_cache.aggregate(pipeline).to_list(500)

    # Enrich with salesperson name/email from the salesperson cache records
    assignments = []
    for group in raw:
        sp_code = group["_id"]

        # Look up salesperson record
        sp_rec = await db.bc_reference_cache.find_one(
            {"bc_entity_type": "salesperson", "code": sp_code},
            {"_id": 0},
        )

        assignments.append({
            "salesperson_code": sp_code,
            "rep_name": sp_rec.get("name", "") if sp_rec else "",
            "rep_email": sp_rec.get("email", "") if sp_rec else "",
            "customer_count": group["customer_count"],
            "customers": group["customers"][:50],  # Cap to avoid huge payloads
        })

    # Also include overrides that don't match a BC salesperson
    overrides = await db[OVERRIDES_COLL].find(
        {"active": True}, {"_id": 0}
    ).to_list(500)

    override_codes = set()
    for ov in overrides:
        code = ov.get("salesperson_code", "OVERRIDE")
        if code not in {a["salesperson_code"] for a in assignments}:
            override_codes.add(code)

    for code in override_codes:
        matched = [ov for ov in overrides if ov.get("salesperson_code", "OVERRIDE") == code]
        if matched:
            assignments.append({
                "salesperson_code": code,
                "rep_name": matched[0].get("rep_name", ""),
                "rep_email": matched[0].get("rep_email", ""),
                "customer_count": len(matched),
                "customers": [
                    {"customer_no": m["customer_no"], "customer_name": ""}
                    for m in matched[:50]
                ],
                "source": "override",
            })

    return assignments


# =========================================================================
# Override
# =========================================================================

async def override_rep_for_customer(
    db,
    customer_no: str,
    rep_email: str,
    rep_name: str,
    salesperson_code: str = "",
    created_by: str = "admin",
) -> Dict[str, Any]:
    """Store or update a manual rep override for a customer.

    Overrides take priority over BC data in get_rep_for_customer().
    Setting rep_email="" and rep_name="" effectively clears the override
    (sets active=False).
    """
    customer_no = customer_no.strip()
    rep_email = rep_email.strip()
    rep_name = rep_name.strip()

    now = datetime.now(timezone.utc).isoformat()
    is_clear = not rep_email and not rep_name

    existing = await db[OVERRIDES_COLL].find_one(
        {"customer_no": customer_no}, {"_id": 0}
    )

    if existing:
        await db[OVERRIDES_COLL].update_one(
            {"customer_no": customer_no},
            {"$set": {
                "rep_email": rep_email,
                "rep_name": rep_name,
                "salesperson_code": salesperson_code,
                "active": not is_clear,
                "updated_at": now,
                "updated_by": created_by,
            }},
        )
    else:
        await db[OVERRIDES_COLL].insert_one({
            "id": str(uuid.uuid4()),
            "customer_no": customer_no,
            "rep_email": rep_email,
            "rep_name": rep_name,
            "salesperson_code": salesperson_code,
            "active": not is_clear,
            "created_at": now,
            "created_by": created_by,
            "updated_at": now,
            "updated_by": created_by,
        })

    result = await db[OVERRIDES_COLL].find_one(
        {"customer_no": customer_no}, {"_id": 0}
    )
    logger.info(
        "[RepAssignment] Override %s for customer %s → %s <%s>",
        "cleared" if is_clear else "set",
        customer_no, rep_name, rep_email,
    )
    return result
