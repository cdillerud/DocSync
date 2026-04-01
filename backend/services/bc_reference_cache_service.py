"""
GPI Document Hub - BC Reference Cache Service

Maintains a local searchable index of key BC entities in MongoDB.
Dramatically reduces BC API calls and enables fast reference resolution.

Cache is READ-ONLY - never writes to BC.

Cached entities:
- purchaseOrders
- purchaseInvoices (posted)
- salesOrders
- salesInvoices (posted)
- salesShipments (posted)

Population:
- Bulk sync: Fetches all records from BC on demand
- Incremental sync: Uses lastModifiedDateTime for delta updates
"""

import os
import re
import logging
import httpx
import asyncio
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# =============================================================================
# BC API CONFIG (reuse same creds as resolver)
# =============================================================================

BC_TENANT_ID = os.environ.get('TENANT_ID', '')
BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID') or os.environ.get('BC_SANDBOX_CLIENT_ID', '')
BC_CLIENT_SECRET = os.environ.get('BC_CLIENT_SECRET') or os.environ.get('BC_SANDBOX_CLIENT_SECRET', '')
BC_PROD_ENVIRONMENT = os.environ.get('BC_PROD_ENVIRONMENT', 'Production')
BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"

# Sync interval in minutes (default 10)
CACHE_SYNC_INTERVAL = int(os.environ.get('BC_CACHE_SYNC_INTERVAL', '10'))

# =============================================================================
# ENTITY DEFINITIONS - what to cache per BC table
# =============================================================================

ENTITY_CONFIGS = {
    "purchaseOrders": {
        "entity_type": "purchase_order",
        "domain": "purchase",
        "number_field": "number",
        "external_ref_field": None,
        "select_fields": "id,number,vendorName,vendorNumber,orderDate,status,lastModifiedDateTime",
        "extract_fields": lambda r: {
            "bc_record_id": r.get("id"),
            "bc_document_no": r.get("number", ""),
            "bc_external_document_no": None,
            "bc_vendor_no": r.get("vendorNumber", ""),
            "bc_vendor_name": r.get("vendorName", ""),
            "bc_customer_no": None,
            "bc_customer_name": None,
            "bc_posting_date": r.get("orderDate"),
            "bc_status": r.get("status", ""),
            "bc_amount": None,
            "bc_last_modified": r.get("lastModifiedDateTime"),
        }
    },
    "purchaseInvoices": {
        "entity_type": "posted_purchase_invoice",
        "domain": "purchase",
        "number_field": "number",
        "external_ref_field": "vendorInvoiceNumber",
        "select_fields": "id,number,vendorInvoiceNumber,vendorName,vendorNumber,postingDate,totalAmountIncludingTax,status,lastModifiedDateTime",
        "extract_fields": lambda r: {
            "bc_record_id": r.get("id"),
            "bc_document_no": r.get("number", ""),
            "bc_external_document_no": r.get("vendorInvoiceNumber", ""),
            "bc_vendor_no": r.get("vendorNumber", ""),
            "bc_vendor_name": r.get("vendorName", ""),
            "bc_customer_no": None,
            "bc_customer_name": None,
            "bc_posting_date": r.get("postingDate"),
            "bc_status": r.get("status", ""),
            "bc_amount": r.get("totalAmountIncludingTax"),
            "bc_last_modified": r.get("lastModifiedDateTime"),
        }
    },
    "salesOrders": {
        "entity_type": "sales_order",
        "domain": "sales",
        "number_field": "number",
        "external_ref_field": "externalDocumentNumber",
        "select_fields": "id,number,externalDocumentNumber,customerName,customerNumber,orderDate,status,totalAmountIncludingTax,lastModifiedDateTime",
        "extract_fields": lambda r: {
            "bc_record_id": r.get("id"),
            "bc_document_no": r.get("number", ""),
            "bc_external_document_no": r.get("externalDocumentNumber", ""),
            "bc_vendor_no": None,
            "bc_vendor_name": None,
            "bc_customer_no": r.get("customerNumber", ""),
            "bc_customer_name": r.get("customerName", ""),
            "bc_posting_date": r.get("orderDate"),
            "bc_status": r.get("status", ""),
            "bc_amount": r.get("totalAmountIncludingTax"),
            "bc_last_modified": r.get("lastModifiedDateTime"),
        }
    },
    "salesInvoices": {
        "entity_type": "posted_sales_invoice",
        "domain": "sales",
        "number_field": "number",
        "external_ref_field": None,
        "select_fields": "id,number,customerName,customerNumber,postingDate,totalAmountIncludingTax,status,lastModifiedDateTime",
        "extract_fields": lambda r: {
            "bc_record_id": r.get("id"),
            "bc_document_no": r.get("number", ""),
            "bc_external_document_no": "",
            "bc_vendor_no": None,
            "bc_vendor_name": None,
            "bc_customer_no": r.get("customerNumber", ""),
            "bc_customer_name": r.get("customerName", ""),
            "bc_posting_date": r.get("postingDate"),
            "bc_status": r.get("status", ""),
            "bc_amount": r.get("totalAmountIncludingTax"),
            "bc_last_modified": r.get("lastModifiedDateTime"),
        }
    },
    "salesShipments": {
        "entity_type": "posted_sales_shipment",
        "domain": "shipping",
        "number_field": "number",
        "external_ref_field": None,
        "select_fields": "id,number,customerName,customerNumber,orderNumber,lastModifiedDateTime",
        "extract_fields": lambda r: {
            "bc_record_id": r.get("id"),
            "bc_document_no": r.get("number", ""),
            "bc_external_document_no": r.get("externalDocumentNumber", ""),
            "bc_vendor_no": None,
            "bc_vendor_name": None,
            "bc_customer_no": r.get("customerNumber", ""),
            "bc_customer_name": r.get("customerName", ""),
            "bc_posting_date": None,
            "bc_status": "posted",
            "bc_amount": None,
            "bc_last_modified": r.get("lastModifiedDateTime"),
            "bc_order_number": r.get("orderNumber", ""),
        }
    },
    "customers": {
        "entity_type": "customer",
        "domain": "master",
        "number_field": "number",
        "external_ref_field": None,
        "select_fields": "id,number,displayName,salespersonCode,email,phoneNumber,lastModifiedDateTime",
        "extract_fields": lambda r: {
            "bc_record_id": r.get("id", ""),
            "bc_document_no": r.get("number", ""),
            "bc_customer_no": r.get("number", ""),
            "bc_customer_name": r.get("displayName", ""),
            "displayName": r.get("displayName", ""),
            "salesperson_code": r.get("salespersonCode", ""),
            "email": r.get("email", ""),
            "phone_number": r.get("phoneNumber", ""),
            "entity_type": "customer",
            "number": r.get("number", ""),
            "bc_last_modified": r.get("lastModifiedDateTime"),
        }
    },
    "salespeople": {
        "entity_type": "salesperson",
        "domain": "master",
        "number_field": "code",
        "external_ref_field": None,
        "select_fields": "code,name,email,lastModifiedDateTime",
        "extract_fields": lambda r: {
            "bc_record_id": r.get("code", ""),
            "bc_document_no": r.get("code", ""),
            "code": r.get("code", ""),
            "name": r.get("name", ""),
            "email": r.get("email", ""),
            "entity_type": "salesperson",
            "bc_last_modified": r.get("lastModifiedDateTime"),
        }
    },
}


def normalize_document_no(value: str) -> str:
    """Normalize a document number for consistent cache lookup."""
    if not value:
        return ""
    v = str(value).strip().upper()
    v = re.sub(r'^(PO[-#\s]*|BOL[-#\s]*|SO[-#\s]*|INV[-#\s]*|SI[-#\s]*|ORD[-#\s]*)', '', v)
    v = re.sub(r'[^A-Z0-9]', '', v)
    return v


class BCReferenceCacheService:
    """
    Local cache of BC reference entities stored in MongoDB.
    
    Provides fast local lookups to avoid repeated BC API calls.
    Remains strictly read-only against BC.
    """

    def __init__(self, db, event_service=None):
        self.db = db
        self.event_service = event_service
        self.collection = db.bc_reference_cache
        self.meta_collection = db.bc_cache_metadata
        self._token = None
        self._token_expires = None
        self._company_id = None
        self._sync_task = None
        self._initialized = False

    # =========================================================================
    # INITIALIZATION
    # =========================================================================

    async def initialize(self):
        """Create indexes and emit init event."""
        await self.collection.create_index("normalized_document_no")
        await self.collection.create_index("normalized_external_ref")
        await self.collection.create_index("bc_entity_type")
        await self.collection.create_index("bc_vendor_no")
        await self.collection.create_index("bc_customer_no")
        await self.collection.create_index("bc_record_id", unique=True, sparse=True)
        await self.collection.create_index([
            ("normalized_document_no", 1),
            ("bc_entity_type", 1),
        ])
        # Indexes for customer/salesperson lookup
        await self.collection.create_index("salesperson_code", sparse=True)
        await self.collection.create_index("code", sparse=True)

        self._initialized = True
        logger.info("[BC Cache] Indexes created on bc_reference_cache")

        if self.event_service:
            await self.event_service.emit(
                event_type="bc.cache.initialized",
                document_id="system",
                source_service="bc_reference_cache",
                payload={"status": "ready"}
            )

    # =========================================================================
    # BC AUTH (mirrors resolver auth)
    # =========================================================================

    async def _get_token(self) -> Optional[str]:
        if self._token and self._token_expires and datetime.now(timezone.utc) < self._token_expires:
            return self._token
        if not BC_CLIENT_ID or not BC_CLIENT_SECRET or not BC_TENANT_ID:
            logger.error("[BC Cache] Missing BC credentials")
            return None
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"https://login.microsoftonline.com/{BC_TENANT_ID}/oauth2/v2.0/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": BC_CLIENT_ID,
                        "client_secret": BC_CLIENT_SECRET,
                        "scope": "https://api.businesscentral.dynamics.com/.default"
                    }
                )
                if resp.status_code == 200:
                    data = resp.json()
                    self._token = data["access_token"]
                    self._token_expires = datetime.now(timezone.utc) + timedelta(minutes=50)
                    return self._token
                logger.error("[BC Cache] Token error: %d", resp.status_code)
        except Exception as e:
            logger.error("[BC Cache] Token error: %s", str(e))
        return None

    async def _get_company_id(self, token: str) -> Optional[str]:
        if self._company_id:
            return self._company_id
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_PROD_ENVIRONMENT}/api/v2.0/companies"
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
                if resp.status_code == 200:
                    companies = resp.json().get("value", [])
                    for c in companies:
                        if "gamer" in c.get("name", "").lower():
                            self._company_id = c["id"]
                            return self._company_id
                    if companies:
                        self._company_id = companies[0]["id"]
                        return self._company_id
        except Exception as e:
            logger.error("[BC Cache] Company lookup error: %s", str(e))
        return None

    # =========================================================================
    # SYNC: BULK + INCREMENTAL
    # =========================================================================

    async def sync_all(self, incremental: bool = False) -> Dict[str, Any]:
        """
        Sync all entity types from BC into cache.
        
        If incremental=True, only fetch records modified since last sync.
        """
        import time
        start = time.time()

        if self.event_service:
            await self.event_service.emit(
                event_type="bc.cache.sync.started",
                document_id="system",
                source_service="bc_reference_cache",
                payload={"mode": "incremental" if incremental else "bulk"}
            )

        token = await self._get_token()
        if not token:
            error_msg = "Cannot sync: failed to get BC token"
            logger.error("[BC Cache] %s", error_msg)
            if self.event_service:
                await self.event_service.emit(
                    event_type="bc.cache.sync.failed",
                    document_id="system",
                    source_service="bc_reference_cache",
                    status="error",
                    payload={"error": error_msg}
                )
            return {"status": "error", "error": error_msg}

        company_id = await self._get_company_id(token)
        if not company_id:
            error_msg = "Cannot sync: failed to get company ID"
            logger.error("[BC Cache] %s", error_msg)
            if self.event_service:
                await self.event_service.emit(
                    event_type="bc.cache.sync.failed",
                    document_id="system",
                    source_service="bc_reference_cache",
                    status="error",
                    payload={"error": error_msg}
                )
            return {"status": "error", "error": error_msg}

        # Get last sync time for incremental
        last_sync = None
        if incremental:
            meta = await self.meta_collection.find_one({"_id": "last_sync"})
            if meta:
                last_sync = meta.get("timestamp")

        results = {}
        total_records = 0

        for table_name, config in ENTITY_CONFIGS.items():
            try:
                count = await self._sync_entity(
                    token, company_id, table_name, config, last_sync
                )
                results[config["entity_type"]] = count
                total_records += count
                logger.info("[BC Cache] Synced %s: %d records", table_name, count)
            except Exception as e:
                logger.error("[BC Cache] Error syncing %s: %s", table_name, str(e))
                results[config["entity_type"]] = f"error: {str(e)}"

        # Update last sync time
        now = datetime.now(timezone.utc).isoformat()
        await self.meta_collection.update_one(
            {"_id": "last_sync"},
            {"$set": {"timestamp": now, "records_synced": total_records, "results": results}},
            upsert=True
        )

        duration_ms = int((time.time() - start) * 1000)

        if self.event_service:
            await self.event_service.emit(
                event_type="bc.cache.sync.completed",
                document_id="system",
                source_service="bc_reference_cache",
                payload={
                    "mode": "incremental" if incremental else "bulk",
                    "total_records": total_records,
                    "entity_counts": {k: v for k, v in results.items() if isinstance(v, int)},
                    "duration_ms": duration_ms
                }
            )

        logger.info(
            "[BC Cache] Sync complete: %d records in %dms (%s)",
            total_records, duration_ms, "incremental" if incremental else "bulk"
        )

        # Auto-seed knowledge base after successful cache sync
        if total_records > 0:
            try:
                from services.knowledge_seed_service import run_full_knowledge_seed
                logger.info("[BC Cache] Triggering auto knowledge seed after sync (%d new records)", total_records)
                seed_result = await run_full_knowledge_seed(self.db)
                logger.info("[BC Cache] Knowledge seed complete: aliases=%s, profiles=%s, domains=%s",
                    seed_result.get("vendor_aliases", {}).get("total_aliases"),
                    seed_result.get("vendor_profiles", {}).get("total_profiles"),
                    seed_result.get("sender_domains", {}).get("total_sender_mappings"))
            except Exception as e:
                logger.warning("[BC Cache] Auto knowledge seed failed (non-blocking): %s", e)

        return {
            "status": "completed",
            "mode": "incremental" if incremental else "bulk",
            "total_records": total_records,
            "entity_counts": results,
            "duration_ms": duration_ms,
            "synced_at": now
        }

    async def _sync_entity(
        self, token: str, company_id: str,
        table_name: str, config: Dict, last_sync: Optional[str]
    ) -> int:
        """Fetch records from a single BC entity table and upsert into cache."""
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_PROD_ENVIRONMENT}/api/v2.0/companies({company_id})/{table_name}"

        params = {"$select": config["select_fields"]}

        if last_sync:
            params["$filter"] = f"lastModifiedDateTime gt {last_sync}"

        count = 0
        next_url = url

        async with httpx.AsyncClient(timeout=120.0) as client:
            while next_url:
                if next_url == url:
                    resp = await client.get(next_url, headers={"Authorization": f"Bearer {token}"}, params=params)
                else:
                    resp = await client.get(next_url, headers={"Authorization": f"Bearer {token}"})

                if resp.status_code != 200:
                    logger.error("[BC Cache] %s fetch error: %d - %s", table_name, resp.status_code, resp.text[:300])
                    break

                data = resp.json()
                records = data.get("value", [])

                if records:
                    ops = []
                    for record in records:
                        cache_doc = self._build_cache_document(record, config)
                        if cache_doc and cache_doc.get("bc_record_id"):
                            from pymongo import ReplaceOne
                            ops.append(
                                ReplaceOne(
                                    {"bc_record_id": cache_doc["bc_record_id"]},
                                    cache_doc,
                                    upsert=True
                                )
                            )
                    if ops:
                        await self.collection.bulk_write(ops, ordered=False)
                        count += len(ops)

                next_url = data.get("@odata.nextLink")

        return count

    def _build_cache_document(self, record: Dict, config: Dict) -> Optional[Dict]:
        """Transform a BC record into a cache document.

        Standard fields are always included. Entity-specific extra fields
        (e.g. salesperson_code, email for customers) are merged in from
        the extract_fields result.
        """
        fields = config["extract_fields"](record)
        if not fields.get("bc_record_id"):
            return None

        doc_no = fields.get("bc_document_no", "")
        ext_ref = fields.get("bc_external_document_no", "") or ""

        doc = {
            "bc_entity_type": config["entity_type"],
            "bc_domain": config.get("domain", ""),
            "bc_record_id": fields["bc_record_id"],
            "bc_document_no": doc_no,
            "normalized_document_no": normalize_document_no(doc_no),
            "bc_external_document_no": ext_ref,
            "normalized_external_ref": normalize_document_no(ext_ref),
            "bc_vendor_no": fields.get("bc_vendor_no") or "",
            "bc_vendor_name": fields.get("bc_vendor_name") or "",
            "bc_customer_no": fields.get("bc_customer_no") or "",
            "bc_customer_name": fields.get("bc_customer_name") or "",
            "bc_posting_date": fields.get("bc_posting_date"),
            "bc_status": fields.get("bc_status") or "",
            "bc_amount": fields.get("bc_amount"),
            "bc_last_modified": fields.get("bc_last_modified"),
            "bc_order_number": fields.get("bc_order_number", ""),
            "cached_at": datetime.now(timezone.utc).isoformat(),
        }

        # Carry through entity-specific extra fields
        _standard_keys = {
            "bc_record_id", "bc_document_no", "bc_external_document_no",
            "bc_vendor_no", "bc_vendor_name", "bc_customer_no", "bc_customer_name",
            "bc_posting_date", "bc_status", "bc_amount", "bc_last_modified",
            "bc_order_number",
        }
        for key, val in fields.items():
            if key not in _standard_keys and key not in doc:
                doc[key] = val

        return doc

    # =========================================================================
    # BACKGROUND SYNC SCHEDULER
    # =========================================================================

    def start_background_sync(self, interval_minutes: int = None):
        """Start periodic incremental sync in background."""
        interval = interval_minutes or CACHE_SYNC_INTERVAL

        async def _sync_loop():
            while True:
                await asyncio.sleep(interval * 60)
                try:
                    logger.info("[BC Cache] Running incremental sync...")
                    await self.sync_all(incremental=True)
                except Exception as e:
                    logger.error("[BC Cache] Background sync error: %s", str(e))

        self._sync_task = asyncio.create_task(_sync_loop())
        logger.info("[BC Cache] Background sync started (every %d min)", interval)

    def stop_background_sync(self):
        if self._sync_task:
            self._sync_task.cancel()
            self._sync_task = None
            logger.info("[BC Cache] Background sync stopped")

    async def sync_entities(self, entity_table_names: List[str], incremental: bool = False) -> Dict[str, Any]:
        """Sync only the specified entity types (e.g. ['customers', 'salespeople']).

        Uses the same logic as sync_all but limited to the given table names.
        """
        token = await self._get_token()
        if not token:
            return {"status": "error", "error": "Failed to get BC token"}

        company_id = await self._get_company_id(token)
        if not company_id:
            return {"status": "error", "error": "Failed to get company ID"}

        last_sync = None
        if incremental:
            meta = await self.meta_collection.find_one({"_id": "last_sync"})
            if meta:
                last_sync = meta.get("timestamp")

        results = {}
        total = 0
        for name in entity_table_names:
            config = ENTITY_CONFIGS.get(name)
            if not config:
                results[name] = "unknown_entity"
                continue
            try:
                count = await self._sync_entity(token, company_id, name, config, last_sync)
                results[config["entity_type"]] = count
                total += count
            except Exception as e:
                logger.error("[BC Cache] Error syncing %s: %s", name, e)
                results[config["entity_type"]] = f"error: {e}"

        return {"status": "completed", "total_records": total, "entity_counts": results}

    # =========================================================================
    # SEARCH / QUERY METHODS
    # =========================================================================

    async def search_by_document_number(
        self, reference_value: str, entity_types: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Search cache by normalized document number."""
        normalized = normalize_document_no(reference_value)
        if not normalized:
            return []

        query = {
            "$or": [
                {"normalized_document_no": normalized},
                {"normalized_external_ref": normalized},
                {"bc_document_no": reference_value.strip()},
            ]
        }
        if entity_types:
            query["bc_entity_type"] = {"$in": entity_types}

        cursor = self.collection.find(query, {"_id": 0}).limit(20)
        return await cursor.to_list(length=20)

    async def search_by_external_reference(
        self, reference_value: str, entity_types: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Search cache by external document number."""
        normalized = normalize_document_no(reference_value)
        if not normalized:
            return []

        query = {"normalized_external_ref": normalized}
        if entity_types:
            query["bc_entity_type"] = {"$in": entity_types}

        cursor = self.collection.find(query, {"_id": 0}).limit(20)
        return await cursor.to_list(length=20)

    async def search_by_vendor(
        self, vendor_no: str, entity_types: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Search cache by vendor number."""
        query = {"bc_vendor_no": vendor_no.strip()}
        if entity_types:
            query["bc_entity_type"] = {"$in": entity_types}

        cursor = self.collection.find(query, {"_id": 0}).sort("bc_posting_date", -1).limit(50)
        return await cursor.to_list(length=50)

    async def search_by_customer(
        self, customer_no: str, entity_types: List[str] = None
    ) -> List[Dict[str, Any]]:
        """Search cache by customer number."""
        query = {"bc_customer_no": customer_no.strip()}
        if entity_types:
            query["bc_entity_type"] = {"$in": entity_types}

        cursor = self.collection.find(query, {"_id": 0}).sort("bc_posting_date", -1).limit(50)
        return await cursor.to_list(length=50)

    async def search_multi(
        self, reference_value: str, entity_types: List[str] = None
    ) -> List[Dict[str, Any]]:
        """
        Combined search: checks document number, external ref, and order number.
        Returns deduplicated results sorted by relevance.
        """
        normalized = normalize_document_no(reference_value)
        raw = reference_value.strip()
        if not normalized:
            return []

        query = {
            "$or": [
                {"normalized_document_no": normalized},
                {"normalized_external_ref": normalized},
                {"bc_document_no": raw},
                {"bc_external_document_no": raw},
                {"bc_order_number": raw},
            ]
        }
        if entity_types:
            query["bc_entity_type"] = {"$in": entity_types}

        cursor = self.collection.find(query, {"_id": 0}).limit(20)
        results = await cursor.to_list(length=20)

        # Score and sort: exact doc_no match first
        def sort_key(r):
            if r.get("bc_document_no") == raw:
                return 0
            if r.get("normalized_document_no") == normalized:
                return 1
            if r.get("bc_external_document_no") == raw:
                return 2
            return 3

        results.sort(key=sort_key)
        return results

    async def search_shipment_cluster(
        self, reference_value: str
    ) -> List[Dict[str, Any]]:
        """
        Shipment reference clustering: given a reference, find all shipment-related
        entities (sales shipments, sales orders) that share the same document number
        or order number. This helps the resolver when a BOL/shipment number matches
        across related entities.
        
        Returns clustered results: primary matches + related shipments/orders.
        """
        normalized = normalize_document_no(reference_value)
        raw = reference_value.strip()
        if not normalized:
            return []

        shipment_entity_types = ["salesShipments", "salesOrders"]

        # Primary search: find shipments/orders matching the reference
        primary_query = {
            "$or": [
                {"normalized_document_no": normalized},
                {"normalized_external_ref": normalized},
                {"bc_document_no": raw},
                {"bc_external_document_no": raw},
                {"bc_order_number": raw},
            ],
            "bc_entity_type": {"$in": shipment_entity_types}
        }
        primary = await self.collection.find(primary_query, {"_id": 0}).limit(10).to_list(10)

        if not primary:
            return []

        # Cluster expansion: for each primary match, find related entities
        seen_ids = {r.get("bc_record_id") for r in primary}
        related = []

        for record in primary:
            order_no = record.get("bc_order_number", "")
            doc_no = record.get("bc_document_no", "")

            # Find shipments linked to the same order
            if order_no:
                cluster_query = {
                    "$or": [
                        {"bc_order_number": order_no},
                        {"bc_document_no": order_no},
                        {"normalized_document_no": normalize_document_no(order_no)},
                    ],
                    "bc_entity_type": {"$in": shipment_entity_types}
                }
                cluster_results = await self.collection.find(
                    cluster_query, {"_id": 0}
                ).limit(10).to_list(10)

                for cr in cluster_results:
                    if cr.get("bc_record_id") not in seen_ids:
                        cr["_cluster_reason"] = f"linked_via_order:{order_no}"
                        related.append(cr)
                        seen_ids.add(cr.get("bc_record_id"))

        # Mark primary results
        for r in primary:
            r["_cluster_reason"] = "primary_match"

        return primary + related

    # =========================================================================
    # STATUS
    # =========================================================================

    async def get_status(self) -> Dict[str, Any]:
        """Get cache status: record counts, last sync, health."""
        pipeline = [
            {"$group": {"_id": "$bc_entity_type", "count": {"$sum": 1}}}
        ]
        entity_counts = {}
        async for doc in self.collection.aggregate(pipeline):
            entity_counts[doc["_id"]] = doc["count"]

        total = sum(entity_counts.values())

        meta = await self.meta_collection.find_one({"_id": "last_sync"}, {"_id": 0})
        last_sync = meta.get("timestamp") if meta else None

        health = "healthy" if total > 0 and last_sync else "empty"
        if last_sync:
            try:
                last_dt = datetime.fromisoformat(last_sync.replace("Z", "+00:00"))
                age_minutes = (datetime.now(timezone.utc) - last_dt).total_seconds() / 60
                if age_minutes > CACHE_SYNC_INTERVAL * 3:
                    health = "stale"
            except Exception:
                pass

        return {
            "status": health,
            "total_records": total,
            "entity_counts": entity_counts,
            "last_sync": last_sync,
            "sync_interval_minutes": CACHE_SYNC_INTERVAL,
            "initialized": self._initialized,
            "background_sync_active": self._sync_task is not None and not self._sync_task.done(),
        }


    async def lookup_po_location_codes(self, po_numbers: List[str]) -> Dict[str, str]:
        """
        Batch-lookup locationCode for a list of PO numbers.
        1. Search the BC cache for each PO to get the bc_record_id
        2. Query BC API purchaseOrderLines for the locationCode
        Returns: {po_number: locationCode}
        """
        if not po_numbers:
            return {}

        token = await self._get_token()
        if not token:
            logger.warning("[BC Cache] No token for PO location lookup")
            return {}

        company_id = await self._get_company_id(token)
        if not company_id:
            return {}

        results = {}
        # Batch: look up PO record IDs from cache first
        po_to_bc_id = {}
        for po in po_numbers:
            if not po or po in results:
                continue
            cached = await self.search_multi(po, entity_types=["purchase_order"])
            if cached:
                bc_id = cached[0].get("bc_record_id")
                if bc_id:
                    po_to_bc_id[po] = bc_id

        # Query BC API for purchaseOrderLines to get locationCode
        async with httpx.AsyncClient(timeout=30.0) as client:
            for po, bc_id in po_to_bc_id.items():
                try:
                    url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_PROD_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseOrders({bc_id})/purchaseOrderLines"
                    resp = await client.get(
                        url,
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$select": "locationCode", "$top": "1"}
                    )
                    if resp.status_code == 200:
                        lines = resp.json().get("value", [])
                        if lines:
                            loc = lines[0].get("locationCode", "")
                            results[po] = loc
                            logger.info("[BC Cache] PO %s → locationCode=%s", po, loc)
                except Exception as e:
                    logger.warning("[BC Cache] PO lines lookup error for %s: %s", po, str(e))

        return results


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_cache_service: Optional[BCReferenceCacheService] = None


def get_cache_service() -> Optional[BCReferenceCacheService]:
    return _cache_service


def set_cache_service(db, event_service=None) -> BCReferenceCacheService:
    global _cache_service
    _cache_service = BCReferenceCacheService(db, event_service)
    return _cache_service
