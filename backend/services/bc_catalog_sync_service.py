"""
BC Catalog Sync Service

Pulls the live BC item catalog and G/L accounts from Business Central
and stores them locally in MongoDB for fast lookup by the item mapping service.

Reads from the Production (read) environment.
"""

import logging
import httpx
from datetime import datetime, timezone
from typing import Dict, Any, List, Optional

from services.business_central_service import (
    get_bc_token, get_bc_company_id, BC_API_BASE, BC_TENANT_ID,
    BC_READ_ENVIRONMENT, BC_REQUEST_TIMEOUT, USE_MOCK,
)

logger = logging.getLogger(__name__)

# MongoDB collections
ITEMS_COLLECTION = "bc_catalog_items"
GL_ACCOUNTS_COLLECTION = "bc_catalog_gl_accounts"
VENDORS_COLLECTION = "bc_catalog_vendors"
SYNC_META_COLLECTION = "bc_catalog_sync_meta"

# Standard BC API v2.0 endpoints
BC_API_VERSION = "v2.0"

async def _bc_get_paged(environment: str, endpoint: str, select: str = "", filter_str: str = "") -> List[Dict]:
    """Fetch all pages from a BC standard API endpoint."""
    token = await get_bc_token(environment=environment)
    company_id = await get_bc_company_id(environment=environment)
    base_url = f"{BC_API_BASE}/{BC_TENANT_ID}/{environment}/api/{BC_API_VERSION}/companies({company_id})/{endpoint}"

    # Do NOT send an explicit $top on the initial request. This BC OData
    # endpoint treats a client-supplied $top as a cap on the TOTAL result
    # set, not a per-page hint: when $top is present it returns exactly
    # that many records and omits @odata.nextLink, silently truncating the
    # sync (confirmed 2026-09-23: this capped the item sync at exactly
    # 1000 of 8972 real items, with zero errors logged - the nextLink loop
    # below never even saw a link to follow). bc_reference_cache_service.py's
    # _sync_entity() proves the fix: omitting $top lets BC apply its own
    # default page size while still returning @odata.nextLink correctly,
    # so the while-loop below then follows every page to completion.
    params: Dict[str, str] = {}
    if select:
        params["$select"] = select
    if filter_str:
        params["$filter"] = filter_str

    all_records = []
    url = base_url

    async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT * 2) as client:
        while url:
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                params=params if url == base_url else None,
            )
            if resp.status_code != 200:
                logger.error("BC catalog fetch failed for %s: %d %s", endpoint, resp.status_code, resp.text[:300])
                raise Exception(f"BC API error for {endpoint}: {resp.status_code}")

            data = resp.json()
            records = data.get("value", [])
            all_records.extend(records)

            # Follow @odata.nextLink for pagination
            url = data.get("@odata.nextLink")
            if url:
                params = None  # nextLink includes params already

    return all_records


async def sync_items(db) -> Dict[str, Any]:
    """Sync the BC item master from Production into local MongoDB."""
    logger.info("Starting BC item catalog sync from %s...", BC_READ_ENVIRONMENT)
    start = datetime.now(timezone.utc)

    if USE_MOCK:
        logger.warning("BC in mock mode — returning empty catalog")
        return {"synced": 0, "environment": "mock", "duration_s": 0}

    raw_items = await _bc_get_paged(
        environment=BC_READ_ENVIRONMENT,
        endpoint="items",
        select="id,number,displayName,type,blocked,unitPrice,unitCost,baseUnitOfMeasureCode,itemCategoryCode,inventory,lastModifiedDateTime",
    )

    logger.info("Fetched %d items from BC %s", len(raw_items), BC_READ_ENVIRONMENT)

    # Transform to our local schema
    docs = []
    for item in raw_items:
        docs.append({
            "bc_system_id": item.get("id", ""),
            "item_no": item.get("number", ""),
            "description": item.get("displayName", ""),
            "type": item.get("type", ""),
            "blocked": item.get("blocked", False),
            "unit_price": item.get("unitPrice", 0),
            "unit_cost": item.get("unitCost", 0),
            "base_uom": item.get("baseUnitOfMeasureCode", ""),
            "item_category_code": item.get("itemCategoryCode", ""),
            "inventory": item.get("inventory", 0),
            "last_modified": item.get("lastModifiedDateTime", ""),
            "synced_at": start.isoformat(),
            "source_environment": BC_READ_ENVIRONMENT,
        })

    # Bulk replace: drop old records and insert fresh
    if docs:
        await db[ITEMS_COLLECTION].delete_many({})
        await db[ITEMS_COLLECTION].insert_many(docs)
        # Create indexes for fast lookup
        await db[ITEMS_COLLECTION].create_index("item_no", unique=True)
        await db[ITEMS_COLLECTION].create_index("description")
        await db[ITEMS_COLLECTION].create_index("blocked")

    duration = (datetime.now(timezone.utc) - start).total_seconds()

    # Store sync metadata
    meta = {
        "entity": "items",
        "synced_at": start.isoformat(),
        "source_environment": BC_READ_ENVIRONMENT,
        "record_count": len(docs),
        "duration_s": round(duration, 2),
    }
    await db[SYNC_META_COLLECTION].update_one(
        {"entity": "items"}, {"$set": meta}, upsert=True
    )

    logger.info("Item catalog sync complete: %d items in %.1fs", len(docs), duration)
    return meta


async def sync_gl_accounts(db) -> Dict[str, Any]:
    """Sync G/L accounts from BC Production into local MongoDB."""
    logger.info("Starting BC G/L account sync from %s...", BC_READ_ENVIRONMENT)
    start = datetime.now(timezone.utc)

    if USE_MOCK:
        return {"synced": 0, "environment": "mock", "duration_s": 0}

    raw_accounts = await _bc_get_paged(
        environment=BC_READ_ENVIRONMENT,
        endpoint="accounts",
        select="id,number,displayName,category,subCategory,blocked,accountType,directPosting,lastModifiedDateTime",
    )

    logger.info("Fetched %d G/L accounts from BC %s", len(raw_accounts), BC_READ_ENVIRONMENT)

    docs = []
    for acct in raw_accounts:
        docs.append({
            "bc_system_id": acct.get("id", ""),
            "account_no": acct.get("number", ""),
            "name": acct.get("displayName", ""),
            "category": acct.get("category", ""),
            "sub_category": acct.get("subCategory", ""),
            "blocked": acct.get("blocked", False),
            "account_type": acct.get("accountType", ""),
            "direct_posting": acct.get("directPosting", False),
            "last_modified": acct.get("lastModifiedDateTime", ""),
            "synced_at": start.isoformat(),
            "source_environment": BC_READ_ENVIRONMENT,
        })

    if docs:
        await db[GL_ACCOUNTS_COLLECTION].delete_many({})
        await db[GL_ACCOUNTS_COLLECTION].insert_many(docs)
        await db[GL_ACCOUNTS_COLLECTION].create_index("account_no", unique=True)
        await db[GL_ACCOUNTS_COLLECTION].create_index("name")
        await db[GL_ACCOUNTS_COLLECTION].create_index("blocked")

    duration = (datetime.now(timezone.utc) - start).total_seconds()

    meta = {
        "entity": "gl_accounts",
        "synced_at": start.isoformat(),
        "source_environment": BC_READ_ENVIRONMENT,
        "record_count": len(docs),
        "duration_s": round(duration, 2),
    }
    await db[SYNC_META_COLLECTION].update_one(
        {"entity": "gl_accounts"}, {"$set": meta}, upsert=True
    )

    logger.info("G/L account sync complete: %d accounts in %.1fs", len(docs), duration)
    return meta


async def sync_vendors(db) -> Dict[str, Any]:
    """Sync the BC vendor master (including blocked vendors) from Production
    into local MongoDB.

    Added 2026-09-28: nothing in this codebase had ever synced BC's actual
    vendor master list directly. The vendor-review queue
    (routers/aliases.py get_unmatched_vendor_gaps) and every vendor-matching
    path only ever drew candidates from bc_reference_cache (itself only
    populated from posted purchase invoice/order *transactions*, see
    bc_reference_cache_service.py) and vendor_invoice_profiles (also
    transaction-derived). A real vendor with no captured transaction history
    in those narrow syncs -- confirmed in production: XPO Logistics
    ("XPOLOGI", status Blocked, balance $10,165.93) -- was invisible to
    every matching/candidate-suggestion path even though it genuinely
    exists in BC, making it look like a vendor that needed to be created
    from scratch rather than one that just needs unblocking.
    """
    logger.info("Starting BC vendor master sync from %s...", BC_READ_ENVIRONMENT)
    start = datetime.now(timezone.utc)

    if USE_MOCK:
        return {"synced": 0, "environment": "mock", "duration_s": 0}

    raw_vendors = await _bc_get_paged(
        environment=BC_READ_ENVIRONMENT,
        endpoint="vendors",
        select="id,number,displayName,blocked,balance,addressLine1,city,state,"
               "postalCode,country,phoneNumber,email,website,lastModifiedDateTime",
    )

    logger.info("Fetched %d vendors from BC %s", len(raw_vendors), BC_READ_ENVIRONMENT)

    docs = []
    for v in raw_vendors:
        docs.append({
            "bc_system_id": v.get("id", ""),
            "vendor_no": v.get("number", ""),
            "name": v.get("displayName", ""),
            # BC returns blocked as text: blank (OData "_x0020_"), "Payment" or
            # "All"; bool() of the blank marker made all 902 vendors blocked.
            "blocked": str(v.get("blocked") or "").strip() not in ("", "_x0020_"),
            "blocked_reason": str(v.get("blocked") or "").strip().replace("_x0020_", ""),
            "balance": v.get("balance", 0),
            "address_line1": v.get("addressLine1", ""),
            "city": v.get("city", ""),
            "state": v.get("state", ""),
            "postal_code": v.get("postalCode", ""),
            "country": v.get("country", ""),
            "phone_number": v.get("phoneNumber", ""),
            "email": v.get("email", ""),
            "website": v.get("website", ""),
            "last_modified": v.get("lastModifiedDateTime", ""),
            "synced_at": start.isoformat(),
            "source_environment": BC_READ_ENVIRONMENT,
        })

    if docs:
        await db[VENDORS_COLLECTION].delete_many({})
        await db[VENDORS_COLLECTION].insert_many(docs)
        await db[VENDORS_COLLECTION].create_index("vendor_no", unique=True)
        await db[VENDORS_COLLECTION].create_index("name")
        await db[VENDORS_COLLECTION].create_index("blocked")
        await mirror_vendors_to_hub_cache(db)

    duration = (datetime.now(timezone.utc) - start).total_seconds()

    meta = {
        "entity": "vendors",
        "synced_at": start.isoformat(),
        "source_environment": BC_READ_ENVIRONMENT,
        "record_count": len(docs),
        "duration_s": round(duration, 2),
    }
    await db[SYNC_META_COLLECTION].update_one(
        {"entity": "vendors"}, {"$set": meta}, upsert=True
    )

    logger.info("Vendor master sync complete: %d vendors in %.1fs", len(docs), duration)
    return meta


async def mirror_vendors_to_hub_cache(db) -> int:
    """Copy the synced BC vendor list into hub_bc_vendors, the collection
    vendor resolution, entity resolution and routing read (number,
    displayName, name_normalized). Nothing had written it, so it was empty
    (found 2026-10-05) and every "cached BC vendors" lookup returned nothing
    while bc_catalog_vendors held 902 current vendors."""
    from services.vendor_name_helpers import normalize_vendor_name
    now = datetime.now(timezone.utc).isoformat()
    docs = []
    async for v in db[VENDORS_COLLECTION].find({}, {"_id": 0}):
        number = str(v.get("vendor_no") or "").strip()
        if not number:
            continue
        name = str(v.get("name") or "").strip()
        docs.append({
            "number": number, "id": v.get("bc_system_id"), "displayName": name,
            "name_normalized": normalize_vendor_name(name) if name else "",
            "blocked": bool(v.get("blocked")), "email": v.get("email") or "",
            "source": VENDORS_COLLECTION, "mirrored_at": now,
        })
    if not docs:
        return 0
    await db.hub_bc_vendors.delete_many({})
    await db.hub_bc_vendors.insert_many(docs)
    await db.hub_bc_vendors.create_index("number")
    await db.hub_bc_vendors.create_index("name_normalized")
    logger.info("[BCCatalog] mirrored %d vendors into hub_bc_vendors", len(docs))
    return len(docs)


async def sync_all(db) -> Dict[str, Any]:
    """Run full catalog sync (items + G/L accounts + vendors)."""
    items_result = await sync_items(db)
    gl_result = await sync_gl_accounts(db)
    vendors_result = await sync_vendors(db)
    return {"items": items_result, "gl_accounts": gl_result, "vendors": vendors_result}


# ── Query functions ──

async def search_items(
    db, query: str = "", blocked: Optional[bool] = False, limit: int = 50
) -> List[Dict]:
    """Search synced BC items by number or description."""
    mongo_filter: Dict[str, Any] = {}
    if blocked is not None:
        mongo_filter["blocked"] = blocked
    if query:
        mongo_filter["$or"] = [
            {"item_no": {"$regex": query, "$options": "i"}},
            {"description": {"$regex": query, "$options": "i"}},
        ]
    items = await db[ITEMS_COLLECTION].find(mongo_filter, {"_id": 0}).limit(limit).to_list(limit)
    return items


async def search_gl_accounts(
    db, query: str = "", blocked: Optional[bool] = False, limit: int = 50
) -> List[Dict]:
    """Search synced BC G/L accounts by number or name."""
    mongo_filter: Dict[str, Any] = {}
    if blocked is not None:
        mongo_filter["blocked"] = blocked
    if query:
        mongo_filter["$or"] = [
            {"account_no": {"$regex": query, "$options": "i"}},
            {"name": {"$regex": query, "$options": "i"}},
        ]
    accounts = await db[GL_ACCOUNTS_COLLECTION].find(mongo_filter, {"_id": 0}).limit(limit).to_list(limit)
    return accounts


async def search_vendors(
    db, query: str = "", blocked: Optional[bool] = None, limit: int = 50
) -> List[Dict]:
    """Search the synced BC vendor master by number or name.

    Unlike search_items/search_gl_accounts, `blocked` defaults to None (no
    filter) rather than False -- the whole point of this sync is to surface
    blocked vendors as real candidates (with their blocked status visible)
    instead of hiding them the way the transaction-derived caches always
    have.
    """
    mongo_filter: Dict[str, Any] = {}
    if blocked is not None:
        mongo_filter["blocked"] = blocked
    if query:
        mongo_filter["$or"] = [
            {"vendor_no": {"$regex": query, "$options": "i"}},
            {"name": {"$regex": query, "$options": "i"}},
        ]
    vendors = await db[VENDORS_COLLECTION].find(mongo_filter, {"_id": 0}).limit(limit).to_list(limit)
    return vendors


async def get_vendor_by_number(db, vendor_no: str) -> Optional[Dict]:
    """Look up a single vendor by its BC vendor number."""
    return await db[VENDORS_COLLECTION].find_one({"vendor_no": vendor_no}, {"_id": 0})


async def get_item_by_number(db, item_no: str) -> Optional[Dict]:
    """Look up a single item by its BC item number."""
    item = await db[ITEMS_COLLECTION].find_one({"item_no": item_no}, {"_id": 0})
    return item


async def get_gl_account_by_number(db, account_no: str) -> Optional[Dict]:
    """Look up a single G/L account by its number."""
    acct = await db[GL_ACCOUNTS_COLLECTION].find_one({"account_no": account_no}, {"_id": 0})
    return acct


async def validate_item_number(db, item_no: str) -> Dict[str, Any]:
    """Validate that an item number exists in the synced catalog and is usable."""
    item = await get_item_by_number(db, item_no)
    if not item:
        return {"valid": False, "reason": "not_found", "item": None}
    if item.get("blocked"):
        return {"valid": False, "reason": "blocked", "item": item}
    return {"valid": True, "reason": "ok", "item": item}


async def suggest_items_for_description(
    db, description: str, limit: int = 5
) -> List[Dict]:
    """Suggest BC items that might match a given line description.
    Uses word-level matching against item descriptions in the catalog.
    """
    import re
    if not description:
        return []

    # Normalize and tokenize the input
    norm = re.sub(r'[^a-z0-9\s]', ' ', description.lower().strip())
    tokens = [t for t in norm.split() if len(t) > 2]  # Skip tiny words

    if not tokens:
        return []

    # Build a regex OR pattern for the tokens
    pattern = "|".join(re.escape(t) for t in tokens[:8])  # Limit to 8 tokens

    candidates = await db[ITEMS_COLLECTION].find(
        {"blocked": {"$ne": True}, "description": {"$regex": pattern, "$options": "i"}},
        {"_id": 0},
    ).limit(limit * 3).to_list(limit * 3)

    # Score each candidate by how many tokens match
    scored = []
    for item in candidates:
        item_desc_lower = (item.get("description") or "").lower()
        matched_tokens = sum(1 for t in tokens if t in item_desc_lower)
        if matched_tokens > 0:
            score = matched_tokens / len(tokens)
            scored.append({**item, "_match_score": round(score, 3), "_matched_tokens": matched_tokens})

    scored.sort(key=lambda x: x["_match_score"], reverse=True)
    return scored[:limit]


async def get_sync_status(db) -> Dict[str, Any]:
    """Get the current sync status for all entity types."""
    metas = await db[SYNC_META_COLLECTION].find({}, {"_id": 0}).to_list(10)
    status = {}
    for m in metas:
        entity = m.pop("entity", "unknown")
        status[entity] = m

    # Add counts from actual collections
    status["items_count"] = await db[ITEMS_COLLECTION].count_documents({})
    status["gl_accounts_count"] = await db[GL_ACCOUNTS_COLLECTION].count_documents({})

    return status


async def get_catalog_health(db) -> Dict[str, Any]:
    """Return a health summary suitable for dashboard embedding.

    Returns:
        {
            last_sync_at: str | None,
            item_count: int,
            gl_account_count: int,
            sync_age_hours: float | None,
            is_stale: bool,      # True if sync_age_hours > 25
        }
    """
    item_count = await db[ITEMS_COLLECTION].count_documents({})
    gl_count = await db[GL_ACCOUNTS_COLLECTION].count_documents({})

    metas = await db[SYNC_META_COLLECTION].find({}, {"_id": 0}).to_list(10)
    last_sync_at = None
    for m in metas:
        ts = m.get("synced_at")
        if ts and (not last_sync_at or ts > last_sync_at):
            last_sync_at = ts

    sync_age_hours = None
    is_stale = True  # stale by default if never synced
    if last_sync_at:
        try:
            if isinstance(last_sync_at, str):
                synced = datetime.fromisoformat(last_sync_at.replace("Z", "+00:00"))
            else:
                synced = last_sync_at
            if synced.tzinfo is None:
                synced = synced.replace(tzinfo=timezone.utc)
            age = datetime.now(timezone.utc) - synced
            sync_age_hours = round(age.total_seconds() / 3600, 2)
            is_stale = sync_age_hours > 25
        except Exception:
            pass

    return {
        "last_sync_at": last_sync_at,
        "item_count": item_count,
        "gl_account_count": gl_count,
        "sync_age_hours": sync_age_hours,
        "is_stale": is_stale,
    }
