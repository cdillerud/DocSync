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
SYNC_META_COLLECTION = "bc_catalog_sync_meta"

# Standard BC API v2.0 endpoints
BC_API_VERSION = "v2.0"

# Page size for BC API calls (max 1000)
PAGE_SIZE = 1000


async def _bc_get_paged(environment: str, endpoint: str, select: str = "", filter_str: str = "") -> List[Dict]:
    """Fetch all pages from a BC standard API endpoint."""
    token = await get_bc_token(environment=environment)
    company_id = await get_bc_company_id(environment=environment)
    base_url = f"{BC_API_BASE}/{BC_TENANT_ID}/{environment}/api/{BC_API_VERSION}/companies({company_id})/{endpoint}"

    params = {"$top": str(PAGE_SIZE)}
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


async def sync_all(db) -> Dict[str, Any]:
    """Run full catalog sync (items + G/L accounts)."""
    items_result = await sync_items(db)
    gl_result = await sync_gl_accounts(db)
    return {"items": items_result, "gl_accounts": gl_result}


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
