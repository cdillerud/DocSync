"""
GPI Document Hub - Business Central Integration Service

Split-environment BC integration:
  - READ operations (vendor lookup, PO validation, etc.) → BC_READ_ENVIRONMENT (Production)
  - WRITE operations (create invoice, create SO, etc.) → BC_WRITE_ENVIRONMENT (Sandbox)

Hard protection: if BC_BLOCK_PRODUCTION_WRITES=true, any write targeting Production is refused.

Configuration via environment variables:
- BC_CLIENT_ID / BC_CLIENT_SECRET: App registration credentials (same for both envs)
- BC_TENANT_ID: Azure AD tenant ID
- BC_READ_ENVIRONMENT: BC environment for reads (e.g., "Production")
- BC_WRITE_ENVIRONMENT: BC environment for writes (e.g., "Sandbox_11_3_2025")
- BC_BLOCK_PRODUCTION_WRITES: Hard guard against Production writes (default: true)
"""

import os
import logging
import httpx
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List
from dotenv import load_dotenv

load_dotenv()

logger = logging.getLogger(__name__)

# =============================================================================
# CONFIGURATION — SPLIT ENVIRONMENT MODEL
# =============================================================================

# Shared credentials (same Azure AD app registration for both environments)
BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID') or os.environ.get('BC_SANDBOX_CLIENT_ID', '')
BC_CLIENT_SECRET = os.environ.get('BC_CLIENT_SECRET') or os.environ.get('BC_SANDBOX_CLIENT_SECRET', '')
BC_TENANT_ID = os.environ.get('TENANT_ID') or os.environ.get('BC_TENANT_ID', '')
BC_COMPANY_ID = os.environ.get('BC_COMPANY_ID', '')
BC_COMPANY_NAME = os.environ.get('BC_COMPANY_NAME', '')

# Split environment routing
BC_READ_ENVIRONMENT = os.environ.get('BC_READ_ENVIRONMENT') or os.environ.get('BC_PROD_ENVIRONMENT', 'Production')
BC_WRITE_ENVIRONMENT = os.environ.get('BC_WRITE_ENVIRONMENT') or os.environ.get('BC_SANDBOX_ENVIRONMENT', 'Sandbox_11_3_2025')
BC_BLOCK_PRODUCTION_WRITES = os.environ.get('BC_BLOCK_PRODUCTION_WRITES', 'true').lower() == 'true'

# Legacy fallback vars (kept for backward compat with bc_sandbox_service)
BC_ENVIRONMENT = os.environ.get('BC_ENVIRONMENT', BC_READ_ENVIRONMENT)
BC_PROD_CLIENT_ID = os.environ.get('BC_PROD_CLIENT_ID', BC_CLIENT_ID)
BC_PROD_CLIENT_SECRET = os.environ.get('BC_PROD_CLIENT_SECRET', BC_CLIENT_SECRET)
BC_PROD_TENANT_ID = os.environ.get('BC_PROD_TENANT_ID', BC_TENANT_ID)
BC_PROD_ENVIRONMENT = os.environ.get('BC_PROD_ENVIRONMENT', 'Production')

# Mock mode control
BC_MOCK_MODE = os.environ.get('BC_MOCK_MODE', 'false').lower() == 'true'
DEMO_MODE = os.environ.get('DEMO_MODE', 'false').lower() == 'true'

# Feature flag for BC link writeback
BC_WRITEBACK_LINK_ENABLED = os.environ.get('BC_WRITEBACK_LINK_ENABLED', 'true').lower() == 'true'

USE_MOCK = BC_MOCK_MODE or (not BC_CLIENT_ID) or (not BC_CLIENT_SECRET) or (not BC_TENANT_ID)
USE_PROD_FOR_READS = True  # Always use read environment for reads

if USE_MOCK:
    logger.info("BusinessCentralService: MOCK MODE (BC_CLIENT_ID=%s, BC_CLIENT_SECRET=%s, BC_TENANT_ID=%s)", 
                bool(BC_CLIENT_ID), bool(BC_CLIENT_SECRET), bool(BC_TENANT_ID))
else:
    logger.info("BusinessCentralService: SPLIT ENVIRONMENT MODE")
    logger.info("  READ  → %s (tenant=%s)", BC_READ_ENVIRONMENT, BC_TENANT_ID[:12] + "..." if BC_TENANT_ID else "N/A")
    logger.info("  WRITE → %s (tenant=%s)", BC_WRITE_ENVIRONMENT, BC_TENANT_ID[:12] + "..." if BC_TENANT_ID else "N/A")
    logger.info("  BLOCK_PRODUCTION_WRITES=%s", BC_BLOCK_PRODUCTION_WRITES)

BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"
BC_REQUEST_TIMEOUT = 30.0

# Token caches — one per environment
_token_cache = {"access_token": None, "expires_at": 0}
_prod_token_cache = {"access_token": None, "expires_at": 0}


class ProductionWriteBlockedError(Exception):
    """Raised when a write operation targets Production and BC_BLOCK_PRODUCTION_WRITES is true."""
    def __init__(self, operation: str):
        self.operation = operation
        super().__init__(
            f"BLOCKED: Write operation '{operation}' refused — target environment "
            f"'{BC_WRITE_ENVIRONMENT}' resolves to Production and BC_BLOCK_PRODUCTION_WRITES=true. "
            f"Change BC_WRITE_ENVIRONMENT to a Sandbox to proceed, or set BC_BLOCK_PRODUCTION_WRITES=false for go-live."
        )


def _check_write_protection(operation: str):
    """Hard guard: refuse writes to Production unless explicitly overridden."""
    if not BC_BLOCK_PRODUCTION_WRITES:
        return
    target = BC_WRITE_ENVIRONMENT.lower()
    if target == "production" or target.startswith("prod"):
        raise ProductionWriteBlockedError(operation)


# =============================================================================
# MOCK DATA
# =============================================================================

MOCK_VENDORS = [
    {"id": "v001-0000-0000-0000-000000000001", "number": "V00001", "displayName": "Acme Supplies Inc", "email": "ap@acme.com", "phoneNumber": "555-0101"},
    {"id": "v002-0000-0000-0000-000000000002", "number": "V00002", "displayName": "Global Parts Co", "email": "billing@globalparts.com", "phoneNumber": "555-0102"},
    {"id": "v003-0000-0000-0000-000000000003", "number": "V00003", "displayName": "Tech Solutions Ltd", "email": "ar@techsolutions.com", "phoneNumber": "555-0103"},
    {"id": "v004-0000-0000-0000-000000000004", "number": "V00004", "displayName": "Office Depot", "email": "commercial@officedepot.com", "phoneNumber": "555-0104"},
    {"id": "v005-0000-0000-0000-000000000005", "number": "V00005", "displayName": "Shipping Express", "email": "accounts@shippingexpress.com", "phoneNumber": "555-0105"},
    {"id": "v006-0000-0000-0000-000000000006", "number": "TUMALOC", "displayName": "Tumalo Creek Transportation", "email": "billing@tumalocreek.com", "phoneNumber": "555-0106"},
    {"id": "v007-0000-0000-0000-000000000007", "number": "V00007", "displayName": "Valley Distributing", "email": "ap@valleydist.com", "phoneNumber": "555-0107"},
    {"id": "v008-0000-0000-0000-000000000008", "number": "V00008", "displayName": "Industrial Packaging Corp", "email": "finance@indpack.com", "phoneNumber": "555-0108"},
]

MOCK_PURCHASE_ORDERS = [
    {"id": "po001-0000-0000-0000-000000000001", "number": "PO-2026-0001", "vendorNumber": "V00001", "vendorName": "Acme Supplies Inc", "orderDate": "2026-02-01", "status": "Open", "totalAmountIncludingVat": 5250.00},
    {"id": "po002-0000-0000-0000-000000000002", "number": "PO-2026-0002", "vendorNumber": "V00002", "vendorName": "Global Parts Co", "orderDate": "2026-02-05", "status": "Open", "totalAmountIncludingVat": 12800.00},
    {"id": "po003-0000-0000-0000-000000000003", "number": "PO-2026-0003", "vendorNumber": "V00003", "vendorName": "Tech Solutions Ltd", "orderDate": "2026-02-10", "status": "Open", "totalAmountIncludingVat": 3450.00},
    {"id": "po004-0000-0000-0000-000000000004", "number": "30360297", "vendorNumber": "TUMALOC", "vendorName": "Tumalo Creek Transportation", "orderDate": "2026-02-15", "status": "Open", "totalAmountIncludingVat": 8900.00},
    {"id": "po005-0000-0000-0000-000000000005", "number": "PO-2026-0005", "vendorNumber": "V00007", "vendorName": "Valley Distributing", "orderDate": "2026-02-18", "status": "Open", "totalAmountIncludingVat": 2100.00},
]


# =============================================================================
# AUTHENTICATION
# =============================================================================

async def get_bc_token(environment: str = None) -> str:
    """Get OAuth token for BC API calls. Uses caching. Environment param selects cache."""
    global _token_cache, _prod_token_cache
    
    # Select the right cache based on environment
    env = environment or BC_WRITE_ENVIRONMENT
    is_read_env = (env == BC_READ_ENVIRONMENT)
    cache = _prod_token_cache if is_read_env else _token_cache
    
    if cache["access_token"] and cache["expires_at"] > datetime.now(timezone.utc).timestamp():
        return cache["access_token"]
    
    if not BC_CLIENT_ID or not BC_CLIENT_SECRET:
        raise ValueError("BC_CLIENT_ID and BC_CLIENT_SECRET must be configured")
    
    token_url = f"https://login.microsoftonline.com/{BC_TENANT_ID}/oauth2/v2.0/token"
    
    async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
        resp = await client.post(
            token_url,
            data={
                "grant_type": "client_credentials",
                "client_id": BC_CLIENT_ID,
                "client_secret": BC_CLIENT_SECRET,
                "scope": "https://api.businesscentral.dynamics.com/.default"
            }
        )
        
        if resp.status_code != 200:
            logger.error("BC token request failed: %s", resp.text)
            raise Exception(f"Failed to get BC token: {resp.status_code}")
        
        data = resp.json()
        cache["access_token"] = data["access_token"]
        cache["expires_at"] = datetime.now(timezone.utc).timestamp() + data.get("expires_in", 3600) - 60
        
        return cache["access_token"]


async def get_bc_prod_token() -> str:
    """Get an access token for the READ environment (Production)."""
    return await get_bc_token(environment=BC_READ_ENVIRONMENT)


def get_bc_read_config():
    """Get BC configuration for READ operations (Production)."""
    return {
        "tenant_id": BC_TENANT_ID,
        "environment": BC_READ_ENVIRONMENT,
        "label": f"Production ({BC_READ_ENVIRONMENT})"
    }


def get_bc_write_config():
    """Get BC configuration for WRITE operations (Sandbox)."""
    return {
        "tenant_id": BC_TENANT_ID,
        "environment": BC_WRITE_ENVIRONMENT,
        "label": f"Sandbox ({BC_WRITE_ENVIRONMENT})"
    }


def get_environment_status() -> Dict[str, Any]:
    """Return full split-environment status for the frontend."""
    return {
        "read_environment": BC_READ_ENVIRONMENT,
        "write_environment": BC_WRITE_ENVIRONMENT,
        "block_production_writes": BC_BLOCK_PRODUCTION_WRITES,
        "tenant_id": BC_TENANT_ID[:12] + "..." if BC_TENANT_ID else "",
        "has_credentials": bool(BC_CLIENT_ID and BC_CLIENT_SECRET and BC_TENANT_ID),
        "mock_mode": USE_MOCK,
        "company_name": BC_COMPANY_NAME,
        "read_label": f"Production ({BC_READ_ENVIRONMENT})",
        "write_label": f"Sandbox ({BC_WRITE_ENVIRONMENT})",
    }


async def get_bc_company_id(environment: str = None) -> str:
    """Get the BC company ID for a given environment. Uses configured value or auto-detects."""
    if BC_COMPANY_ID:
        return BC_COMPANY_ID
    
    env = environment or BC_READ_ENVIRONMENT
    token = await get_bc_token(environment=env)
    url = f"{BC_API_BASE}/{BC_TENANT_ID}/{env}/api/v2.0/companies"
    
    async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        
        if resp.status_code != 200:
            raise Exception(f"Failed to get BC companies: {resp.status_code}")
        
        companies = resp.json().get("value", [])
        if not companies:
            raise Exception("No BC companies found")
        
        return companies[0]["id"]


# =============================================================================
# BUSINESS CENTRAL SERVICE CLASS
# =============================================================================

class BusinessCentralService:
    """
    Service for interacting with Business Central API.
    Supports both mock mode and real API calls.
    """
    
    def __init__(self, use_mock: bool = None):
        """
        Initialize the service.
        
        Args:
            use_mock: Override mock mode setting. If None, uses auto-detected mode.
        """
        self.use_mock = use_mock if use_mock is not None else USE_MOCK
        self._company_id = None
        self._company_id_cache = {}  # env -> company_id
        
        if self.use_mock:
            logger.info("BusinessCentralService initialized in MOCK mode")
        else:
            logger.info("BusinessCentralService initialized: READ→%s, WRITE→%s", 
                       BC_READ_ENVIRONMENT, BC_WRITE_ENVIRONMENT)
    
    async def _get_company_id(self, environment: str = None) -> str:
        """Get and cache the company ID for a specific environment."""
        env = environment or BC_READ_ENVIRONMENT
        if env in self._company_id_cache:
            return self._company_id_cache[env]
        
        if self.use_mock:
            self._company_id_cache[env] = "mock-company-id"
        else:
            self._company_id_cache[env] = await get_bc_company_id(environment=env)
        
        return self._company_id_cache[env]
    
    async def _get_company_id_for_env(self, tenant_id: str, environment: str, token: str) -> str:
        """Get company ID for a specific BC environment."""
        # Use cache key based on environment
        cache_key = f"_company_id_{tenant_id[:8]}_{environment}"
        cached = getattr(self, cache_key, None)
        if cached:
            return cached
        
        url = f"{BC_API_BASE}/{tenant_id}/{environment}/api/v2.0/companies"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            
            if resp.status_code != 200:
                logger.error("Failed to get companies for %s/%s: %s", tenant_id[:8], environment, resp.text)
                raise Exception(f"Failed to get BC companies: {resp.status_code}")
            
            companies = resp.json().get("value", [])
            if not companies:
                raise Exception(f"No BC companies found in {environment}")
            
            company_id = companies[0]["id"]
            setattr(self, cache_key, company_id)
            return company_id
    
    # =========================================================================
    # VENDOR METHODS
    # =========================================================================
    
    async def get_vendors(self, filter_text: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """
        Get vendors from BC, optionally filtered by name/number.
        Uses PRODUCTION BC for reads if configured.
        
        Args:
            filter_text: Optional text to filter vendors by name or number
            limit: Maximum number of vendors to return
            
        Returns:
            Dict with "vendors" list and "total" count
        """
        if self.use_mock:
            vendors = MOCK_VENDORS
            if filter_text:
                filter_lower = filter_text.lower()
                vendors = [v for v in vendors if filter_lower in v["displayName"].lower() or filter_lower in v["number"].lower()]
            return {
                "vendors": vendors[:limit],
                "total": len(vendors),
                "mock": True
            }
        
        # Use READ environment (Production) for vendor lookups
        read_config = get_bc_read_config()
        token = await get_bc_token(environment=BC_READ_ENVIRONMENT)
        company_id = await self._get_company_id(environment=BC_READ_ENVIRONMENT)
        
        url = f"{BC_API_BASE}/{read_config['tenant_id']}/{read_config['environment']}/api/v2.0/companies({company_id})/vendors"
        params = {"$select": "id,number,displayName,email,phoneNumber", "$top": str(limit)}
        
        if filter_text:
            # BC doesn't support OR on distinct fields, so filter by displayName only
            # We'll do client-side filtering for number matches
            params["$filter"] = f"contains(displayName, '{filter_text}')"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            
            if resp.status_code != 200:
                # If filter fails, try without filter and do client-side filtering
                if filter_text:
                    logger.warning("BC vendor filter failed, falling back to client-side filter")
                    params.pop("$filter", None)
                    params["$top"] = "500"  # Get more to filter client-side
                    resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        vendors = data.get("value", [])
                        filter_lower = filter_text.lower()
                        vendors = [v for v in vendors if filter_lower in v.get("displayName", "").lower() or filter_lower in v.get("number", "").lower()]
                        return {
                            "vendors": vendors[:limit],
                            "total": len(vendors),
                            "mock": False,
                            "bc_environment": read_config["label"]
                        }
                
                logger.error("Failed to get vendors: %s", resp.text)
                raise Exception(f"Failed to get vendors: {resp.status_code}")
            
            data = resp.json()
            vendors = data.get("value", [])
            
            return {
                "vendors": vendors,
                "total": len(vendors),
                "mock": False,
                "bc_environment": read_config["label"]
            }
    
    async def get_vendor_by_id(self, vendor_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific vendor by ID. Uses READ environment."""
        if self.use_mock:
            for v in MOCK_VENDORS:
                if v["id"] == vendor_id or v["number"] == vendor_id:
                    return v
            return None
        
        token = await get_bc_token(environment=BC_READ_ENVIRONMENT)
        company_id = await self._get_company_id(environment=BC_READ_ENVIRONMENT)
        
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors({vendor_id})"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            
            if resp.status_code == 404:
                return None
            if resp.status_code != 200:
                raise Exception(f"Failed to get vendor: {resp.status_code}")
            
            return resp.json()
    
    # =========================================================================
    # PURCHASE ORDER METHODS
    # =========================================================================
    
    async def get_open_purchase_orders(self, vendor_id: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """
        Get open purchase orders, optionally filtered by vendor.
        
        Args:
            vendor_id: Optional vendor ID/number to filter by
            limit: Maximum number of POs to return
            
        Returns:
            Dict with "purchaseOrders" list and "total" count
        """
        if self.use_mock:
            pos = MOCK_PURCHASE_ORDERS
            if vendor_id:
                pos = [po for po in pos if po["vendorNumber"] == vendor_id or po["vendorName"].lower() == vendor_id.lower()]
            return {
                "purchaseOrders": pos[:limit],
                "total": len(pos),
                "mock": True
            }
        
        # Real BC API call — use READ environment (Production)
        token = await get_bc_token(environment=BC_READ_ENVIRONMENT)
        company_id = await self._get_company_id(environment=BC_READ_ENVIRONMENT)
        
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseOrders"
        # Note: BC purchaseOrders API has different field names - use valid ones only
        params = {
            "$select": "id,number,vendorNumber,vendorName,orderDate,status",
            "$filter": "status eq 'Open'",
            "$top": str(limit)
        }
        
        if vendor_id:
            params["$filter"] += f" and vendorNumber eq '{vendor_id}'"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            
            if resp.status_code != 200:
                # Try without status filter if it fails
                logger.warning("PO search with filter failed: %s, trying without status filter", resp.text[:200])
                params = {
                    "$select": "id,number,vendorNumber,vendorName,orderDate",
                    "$top": str(limit)
                }
                if vendor_id:
                    params["$filter"] = f"vendorNumber eq '{vendor_id}'"
                
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
                
                if resp.status_code != 200:
                    logger.error("Failed to get purchase orders: %s", resp.text)
                    raise Exception(f"Failed to get purchase orders: {resp.status_code}")
            
            data = resp.json()
            pos = data.get("value", [])
            
            return {
                "purchaseOrders": pos,
                "total": len(pos),
                "mock": False
            }

    async def find_purchase_order_by_number(self, po_number: str) -> Optional[Dict[str, Any]]:
        """Look up a purchase order by its number. Returns the PO with amount and locationCode."""
        if self.use_mock or not po_number:
            return None

        token = await get_bc_token(environment=BC_READ_ENVIRONMENT)
        company_id = await self._get_company_id(environment=BC_READ_ENVIRONMENT)

        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseOrders"
        params = {
            "$filter": f"number eq '{po_number}'",
            "$select": "id,number,vendorNumber,vendorName,orderDate,status,totalAmountIncludingTax,totalAmountExcludingTax",
            "$top": "1",
        }
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            if resp.status_code == 200:
                orders = resp.json().get("value", [])
                return orders[0] if orders else None
        return None

    async def check_duplicate_purchase_invoice(self, vendor_no: str, vendor_invoice_no: str) -> Optional[Dict[str, Any]]:
        """Check if a purchase invoice with the same vendor + invoice number already exists in BC.
        Returns the existing PI if found, None otherwise."""
        if self.use_mock or not vendor_no or not vendor_invoice_no:
            return None

        token = await get_bc_token(environment=BC_READ_ENVIRONMENT)
        company_id = await self._get_company_id(environment=BC_READ_ENVIRONMENT)

        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices"
        params = {
            "$filter": f"vendorNumber eq '{vendor_no}' and vendorInvoiceNumber eq '{vendor_invoice_no}'",
            "$select": "id,number,vendorNumber,vendorInvoiceNumber,totalAmountIncludingTax,status",
            "$top": "1",
        }
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            if resp.status_code == 200:
                invoices = resp.json().get("value", [])
                return invoices[0] if invoices else None
        return None


    # =========================================================================
    # POSTED PURCHASE INVOICE ANALYSIS (Learn from Human Postings)
    # =========================================================================

    async def get_posted_purchase_invoices(
        self, vendor_id: str = None, limit: int = 100, skip: int = 0
    ) -> Dict[str, Any]:
        """
        Query BC Production for ALL purchase invoices — no status filter.
        Every invoice (Draft, Open, Paid, Corrective, etc.) is part of the
        learning dataset. "Why exclude ANYTHING that can help the AI?"
        """
        if self.use_mock:
            return {"invoices": [], "total": 0, "mock": True}

        token = await get_bc_token(environment=BC_READ_ENVIRONMENT)
        company_id = await self._get_company_id(environment=BC_READ_ENVIRONMENT)

        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices"
        params = {
            "$select": "id,number,vendorNumber,vendorName,vendorInvoiceNumber,"
                       "invoiceDate,dueDate,currencyCode,totalAmountExcludingTax,"
                       "totalAmountIncludingTax,totalTaxAmount,status,"
                       "buyFromAddressLine1,buyFromCity,buyFromState,buyFromPostCode",
            "$orderby": "invoiceDate desc",
            "$top": str(limit),
            "$skip": str(skip),
        }
        # No status filter — ingest ALL statuses for maximum learning data
        if vendor_id:
            params["$filter"] = f"vendorNumber eq '{vendor_id}'"

        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)

            if resp.status_code != 200:
                # Fallback: try with minimal fields if BC rejects the query
                logger.warning("PI query failed (%s), trying with minimal fields", resp.status_code)
                params = {
                    "$select": "id,number,vendorNumber,vendorName,vendorInvoiceNumber,"
                               "invoiceDate,dueDate,currencyCode,totalAmountExcludingTax,"
                               "totalAmountIncludingTax,status",
                    "$orderby": "invoiceDate desc",
                    "$top": str(limit),
                    "$skip": str(skip),
                }
                if vendor_id:
                    params["$filter"] = f"vendorNumber eq '{vendor_id}'"
                resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
                if resp.status_code != 200:
                    logger.error("PI query failed: %s - %s", resp.status_code, resp.text[:300])
                    return {"invoices": [], "total": 0, "error": resp.text[:300]}

            data = resp.json()
            invoices = data.get("value", [])
            return {"invoices": invoices, "total": len(invoices), "mock": False}

    async def get_historical_posted_purchase_invoices(
        self, vendor_id: str = None, limit: int = 100, skip: int = 0
    ) -> Dict[str, Any]:
        """
        Query BC for POSTED (completed/historical) purchase invoices from the
        separate postedPurchaseInvoices entity. In BC, once a Purchase Invoice
        is 'Posted', it moves from purchaseInvoices to this separate table.
        This captures years of historical data that no longer appears in the
        standard purchaseInvoices endpoint.
        """
        if self.use_mock:
            return {"invoices": [], "total": 0, "mock": True}

        token = await get_bc_token(environment=BC_READ_ENVIRONMENT)
        company_id = await self._get_company_id(environment=BC_READ_ENVIRONMENT)
        headers = {"Authorization": f"Bearer {token}"}

        # Try multiple endpoint names — BC versions vary
        endpoints = [
            f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/postedPurchaseInvoices",
            f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseCreditMemos",
        ]

        params = {
            "$select": "id,number,vendorNumber,vendorName,vendorInvoiceNumber,"
                       "invoiceDate,dueDate,currencyCode,totalAmountExcludingTax,"
                       "totalAmountIncludingTax,status",
            "$orderby": "invoiceDate desc",
            "$top": str(limit),
            "$skip": str(skip),
        }
        if vendor_id:
            params["$filter"] = f"vendorNumber eq '{vendor_id}'"

        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            for url in endpoints:
                try:
                    resp = await client.get(url, headers=headers, params=params)
                    if resp.status_code == 200:
                        data = resp.json()
                        invoices = data.get("value", [])
                        entity_name = url.split("/")[-1]
                        logger.info("Historical PI query via %s: got %d invoices (skip=%d)",
                                    entity_name, len(invoices), skip)
                        return {"invoices": invoices, "total": len(invoices), "mock": False,
                                "source": entity_name}
                    elif resp.status_code == 404:
                        logger.debug("Endpoint %s not available (404), trying next", url.split("/")[-1])
                        continue
                    else:
                        logger.debug("Endpoint %s returned %s, trying next", url.split("/")[-1], resp.status_code)
                        continue
                except Exception as e:
                    logger.debug("Endpoint %s failed: %s, trying next", url.split("/")[-1], str(e))
                    continue

        logger.info("No historical posted PI endpoints available — standard purchaseInvoices will be sole data source")
        return {"invoices": [], "total": 0, "mock": False, "source": "none_available"}

    async def get_historical_invoice_lines(self, invoice_id: str, source: str = "postedPurchaseInvoices") -> List[Dict[str, Any]]:
        """
        Get line items for a historical posted purchase invoice.
        Tries the posted-specific line endpoints.
        """
        if self.use_mock:
            return []

        token = await get_bc_token(environment=BC_READ_ENVIRONMENT)
        company_id = await self._get_company_id(environment=BC_READ_ENVIRONMENT)
        headers = {"Authorization": f"Bearer {token}"}

        # Try sub-entity navigation for the posted invoice
        endpoints = [
            f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/"
            f"companies({company_id})/{source}({invoice_id})/postedPurchaseInvoiceLines",
            f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/"
            f"companies({company_id})/{source}({invoice_id})/purchaseInvoiceLines",
        ]

        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            for url in endpoints:
                try:
                    resp = await client.get(url, headers=headers)
                    if resp.status_code == 200:
                        lines = resp.json().get("value", [])
                        if lines:
                            return lines
                except Exception:
                    continue

        # Fallback to standard line fetch
        return await self.get_purchase_invoice_lines(invoice_id)

    async def get_purchase_invoice_lines(self, invoice_id: str) -> List[Dict[str, Any]]:
        """
        Get line items for a specific purchase invoice.
        This is where the GL accounts, quantities, and amounts live.
        Tries multiple approaches since BC API field names vary by version.
        """
        if self.use_mock:
            return []

        token = await get_bc_token(environment=BC_READ_ENVIRONMENT)
        company_id = await self._get_company_id(environment=BC_READ_ENVIRONMENT)
        headers = {"Authorization": f"Bearer {token}"}

        # Approach 1: Sub-entity navigation (standard v2.0)
        url = (f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/"
               f"companies({company_id})/purchaseInvoices({invoice_id})/purchaseInvoiceLines")

        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            # Try without $select first — get all fields, then we know what exists
            resp = await client.get(url, headers=headers)
            if resp.status_code == 200:
                lines = resp.json().get("value", [])
                if lines:
                    return lines

            # Approach 2: Try the standalone purchaseInvoiceLines entity with filter
            url2 = (f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/"
                    f"companies({company_id})/purchaseInvoiceLines")
            params2 = {"$filter": f"documentId eq {invoice_id}", "$top": "50"}
            resp2 = await client.get(url2, headers=headers, params=params2)
            if resp2.status_code == 200:
                lines = resp2.json().get("value", [])
                if lines:
                    return lines

            # Approach 3: Try OData v4 endpoint (some BC setups use this)
            url3 = (f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/ODataV4/"
                    f"Company('{company_id}')/PurchInvLines")
            params3 = {"$filter": f"Document_No eq '{invoice_id}'", "$top": "50"}
            resp3 = await client.get(url3, headers=headers, params=params3)
            if resp3.status_code == 200:
                lines = resp3.json().get("value", [])
                if lines:
                    return lines

            # Log what we got so the user can debug
            logger.warning(
                "PI lines: All approaches failed for invoice %s. "
                "Approach1=%s, Approach2=%s, Approach3=%s",
                invoice_id, resp.status_code, resp2.status_code, resp3.status_code
            )
            # Log first response body for debugging
            if resp.status_code != 200:
                logger.debug("PI lines approach1 body: %s", resp.text[:300])
            if resp2.status_code != 200:
                logger.debug("PI lines approach2 body: %s", resp2.text[:300])

            return []

    
    # =========================================================================
    # PURCHASE INVOICE METHODS
    # =========================================================================
    
    async def create_purchase_invoice(self, invoice_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a purchase invoice in BC WRITE environment (Sandbox).
        Hard-blocked from writing to Production when BC_BLOCK_PRODUCTION_WRITES=true.
        """
        if self.use_mock:
            mock_bc_id = f"PI-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            return {
                "success": True,
                "bcDocumentId": mock_bc_id,
                "bcDocumentNumber": mock_bc_id,
                "status": "Draft",
                "message": "Purchase invoice created (mock mode)",
                "mock": True,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "bc_write_environment": BC_WRITE_ENVIRONMENT,
            }
        
        # HARD GUARD: refuse writes to Production
        _check_write_protection("create_purchase_invoice")
        
        token = await get_bc_token(environment=BC_WRITE_ENVIRONMENT)
        company_id = await self._get_company_id(environment=BC_WRITE_ENVIRONMENT)
        
        # Build the invoice payload per BC API spec
        # Note: BC API uses 'vendorInvoiceNumber' (not 'externalDocumentNumber') for the vendor's invoice reference
        payload = {
            "vendorNumber": invoice_data.get("vendorNumber") or invoice_data.get("vendor_no"),
            "vendorInvoiceNumber": invoice_data.get("invoiceNumber") or invoice_data.get("invoice_number"),
            "invoiceDate": invoice_data.get("invoiceDate") or invoice_data.get("invoice_date"),
            "dueDate": invoice_data.get("dueDate") or invoice_data.get("due_date"),
            "currencyCode": invoice_data.get("currencyCode") or invoice_data.get("currency") or "USD",
        }
        
        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}
        
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            
            if resp.status_code not in (200, 201):
                error_detail = resp.text[:500]
                logger.error("Failed to create purchase invoice: %s", error_detail)
                return {
                    "success": False,
                    "error": f"BC API error: {resp.status_code}",
                    "details": error_detail,
                    "mock": False
                }
            
            data = resp.json()
            bc_invoice_id = data.get("id")

            # Add line items if provided
            line_result = None
            if invoice_data.get("lines") and len(invoice_data["lines"]) > 0:
                logger.info("Adding %d line items to invoice %s", len(invoice_data["lines"]), bc_invoice_id)
                line_result = await self._add_invoice_lines(bc_invoice_id, invoice_data["lines"], token, company_id)

            # ── PARTIAL-POST DETECTION ─────────────────────────────────────
            # A header-created + lines-failed situation would previously return
            # success=True with linesAdded=0. Downstream code then flipped the
            # document to 'posted' and the user saw "Posted ✅" while BC held
            # an empty draft. That's a bookkeeping trap — detect & report.
            if line_result is not None:
                lines_total = line_result.get("total", 0)
                lines_added = line_result.get("added", 0)
                if lines_total > 0 and lines_added < lines_total:
                    partial_msg = (
                        f"BC header created (id={bc_invoice_id}, "
                        f"number={data.get('number')}) but only "
                        f"{lines_added}/{lines_total} lines were accepted. "
                        f"Draft header is orphaned in BC and must be "
                        f"deleted or completed manually."
                    )
                    logger.error(
                        "[BCCreatePI] Partial posting detected: %s", partial_msg
                    )
                    # Best-effort cleanup of the orphaned draft header so we
                    # don't leak empty drafts on repeated retries.
                    deletion_status = await self._try_delete_draft_invoice(
                        bc_invoice_id, token, company_id
                    )
                    return {
                        "success": False,
                        "error": "partial_post",
                        "details": partial_msg,
                        "bcDocumentId": bc_invoice_id,
                        "bcDocumentNumber": data.get("number"),
                        "linesAdded": lines_added,
                        "linesTotal": lines_total,
                        "lineErrors": line_result.get("errors", []),
                        "orphan_header_deletion": deletion_status,
                        "bc_write_environment": BC_WRITE_ENVIRONMENT,
                    }

            return {
                "success": True,
                "bcDocumentId": bc_invoice_id,
                "bcDocumentNumber": data.get("number"),
                "status": data.get("status", "Draft"),
                "message": "Purchase invoice created successfully",
                "mock": False,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "bcResponse": data,
                "linesAdded": line_result.get("added", 0) if line_result else 0,
                "linesTotal": line_result.get("total", 0) if line_result else 0,
                "lineErrors": line_result.get("errors", []) if line_result else [],
                "bc_write_environment": BC_WRITE_ENVIRONMENT,
            }

    async def _try_delete_draft_invoice(
        self, invoice_id: str, token: str, company_id: str
    ) -> str:
        """Best-effort delete of a draft PI header whose lines failed. Only
        valid when the invoice is still Draft — BC rejects deletion of
        posted invoices. Returns one of {'deleted','failed','skipped'}."""
        try:
            url = (
                f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}"
                f"/api/v2.0/companies({company_id})/purchaseInvoices({invoice_id})"
            )
            async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
                resp = await client.delete(
                    url, headers={"Authorization": f"Bearer {token}"}
                )
                if resp.status_code in (200, 204):
                    logger.info(
                        "[BCCreatePI] Orphan draft %s deleted after partial-post",
                        invoice_id,
                    )
                    return "deleted"
                logger.warning(
                    "[BCCreatePI] Failed to delete orphan draft %s: %d %s",
                    invoice_id, resp.status_code, resp.text[:200],
                )
                return "failed"
        except Exception as e:
            logger.warning(
                "[BCCreatePI] Exception deleting orphan draft %s: %s",
                invoice_id, e,
            )
            return "failed"
    
    async def _add_invoice_lines(self, invoice_id: str, lines: List[Dict], token: str, company_id: str):
        """Add line items to a purchase invoice.

        HONORS each line's ``lineType`` and ``lineObjectNumber`` produced by
        ``vendor_invoice_profile_service.build_smart_pi_lines`` — previously
        every line was posted as ``lineType=Item`` with a single hardcoded
        ``BC_DEFAULT_ITEM_CODE`` (e.g. "FREIGHT"), which collapsed the
        vendor-profile-learned GL mapping and produced uniformly wrong
        postings.

        Supported line types:
          * ``"Account"`` -> posts ``{"lineType": "Account", "accountId": <guid>}``
            (the GL account GUID is looked up from ``lineObjectNumber``)
          * ``"Item"``    -> posts ``{"lineType": "Item", "itemId": <guid>}``

        If a line's ``lineObjectNumber`` cannot be resolved to a BC GUID,
        that line is marked as failed — we do NOT silently fall back to
        the legacy FREIGHT item (that's the class of bug we're removing).
        Invoice-level partial-post detection (upstream in
        ``create_purchase_invoice``) then blocks success-reporting if any
        line failed.

        The legacy ``BC_DEFAULT_ITEM_CODE`` / ``BC_PI_FREIGHT_ITEM`` env
        vars remain as a compatibility bridge ONLY when a line arrives with
        neither a ``lineType`` nor a ``lineObjectNumber`` (truly unclassified
        extraction).
        """
        url = (
            f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/v2.0/"
            f"companies({company_id})/purchaseInvoices({invoice_id})/"
            f"purchaseInvoiceLines"
        )

        # Legacy fallback — only used when a line has no lineType/lineObjectNumber.
        legacy_item_code = os.environ.get(
            "BC_DEFAULT_ITEM_CODE", os.environ.get("BC_PI_FREIGHT_ITEM", "")
        )

        # Per-call caches so N lines referencing the same GL/item don't
        # trigger N lookups against BC.
        account_id_cache: Dict[str, Optional[str]] = {}
        item_id_cache: Dict[str, Optional[str]] = {}

        async def resolve_account(code: str) -> Optional[str]:
            if code in account_id_cache:
                return account_id_cache[code]
            gid = await self._get_account_id_by_number(code, token, company_id)
            account_id_cache[code] = gid
            return gid

        async def resolve_item(code: str) -> Optional[str]:
            if code in item_id_cache:
                return item_id_cache[code]
            gid = await self._get_item_id_by_code(code, token, company_id)
            item_id_cache[code] = gid
            return gid

        added_count = 0
        errors: List[Dict[str, Any]] = []

        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            for idx, line in enumerate(lines):
                description = str(line.get("description", "") or "").strip()
                quantity = float(line.get("quantity", 1) or 1)
                unit_price = float(
                    line.get("unitCost") or line.get("unit_price") or 0
                )
                line_total = float(line.get("total") or line.get("line_total") or 0)

                # Derive unit_price from total when missing (same math as before).
                if line_total and unit_price == 0 and quantity > 0:
                    unit_price = line_total / quantity
                if unit_price == 0 and line_total:
                    unit_price = line_total
                    quantity = 1

                if not description and unit_price == 0 and line_total == 0:
                    logger.debug("Skipping empty invoice line %d", idx)
                    continue

                # ── Resolve BC reference (Account or Item) ──
                requested_type = (line.get("lineType") or "").strip()
                requested_obj = (line.get("lineObjectNumber") or "").strip()

                bc_line: Optional[Dict[str, Any]] = None
                resolution_error: Optional[str] = None

                if requested_type == "Account" and requested_obj:
                    account_id = await resolve_account(requested_obj)
                    if account_id:
                        bc_line = {
                            "lineType": "Account",
                            "accountId": account_id,
                            "description": description[:100] or f"Line {idx + 1}",
                            "quantity": quantity,
                            "unitCost": unit_price,
                        }
                    else:
                        resolution_error = (
                            f"GL account '{requested_obj}' not found in BC"
                        )

                elif requested_type == "Item" and requested_obj:
                    item_id = await resolve_item(requested_obj)
                    if item_id:
                        bc_line = {
                            "lineType": "Item",
                            "itemId": item_id,
                            "description": description[:100] or f"Line {idx + 1}",
                            "quantity": quantity,
                            "unitCost": unit_price,
                        }
                    else:
                        resolution_error = (
                            f"Item '{requested_obj}' not found in BC"
                        )

                elif not requested_type and not requested_obj and legacy_item_code:
                    # No classification at all — last-ditch fallback to the
                    # env default. Emits a warning so we can see how often
                    # this path is still hit in production.
                    item_id = await resolve_item(legacy_item_code)
                    if item_id:
                        logger.warning(
                            "[BCAddLines] Line %d had no lineType/lineObjectNumber "
                            "— falling back to legacy default item '%s'. "
                            "This indicates an incomplete vendor-profile GL "
                            "mapping and should be fixed upstream.",
                            idx + 1, legacy_item_code,
                        )
                        bc_line = {
                            "lineType": "Item",
                            "itemId": item_id,
                            "description": description[:100] or f"Line {idx + 1}",
                            "quantity": quantity,
                            "unitCost": unit_price,
                        }
                    else:
                        resolution_error = (
                            f"Legacy default item '{legacy_item_code}' "
                            f"not found in BC; cannot post unclassified line"
                        )
                else:
                    resolution_error = (
                        f"Unsupported line classification: "
                        f"lineType={requested_type!r}, "
                        f"lineObjectNumber={requested_obj!r}"
                    )

                if bc_line is None:
                    logger.error(
                        "[BCAddLines] Line %d NOT posted: %s (desc=%r)",
                        idx + 1, resolution_error, description[:40],
                    )
                    errors.append({
                        "line": idx + 1,
                        "description": description[:50],
                        "error": resolution_error,
                        "requested_type": requested_type,
                        "requested_obj": requested_obj,
                    })
                    continue

                logger.info(
                    "[BCAddLines] Posting line %d: %s/%s qty=%s unit=$%.2f desc=%r",
                    idx + 1, bc_line["lineType"],
                    requested_obj or legacy_item_code,
                    quantity, unit_price, description[:40],
                )

                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json",
                    },
                    json=bc_line,
                )
                if resp.status_code in (200, 201):
                    added_count += 1
                else:
                    error_msg = resp.text[:300]
                    logger.warning(
                        "[BCAddLines] Line %d HTTP %d: %s",
                        idx + 1, resp.status_code, error_msg,
                    )
                    errors.append({
                        "line": idx + 1,
                        "description": description[:50],
                        "error": error_msg,
                        "http_status": resp.status_code,
                    })

        logger.info(
            "[BCAddLines] Invoice line addition complete: %d/%d lines added",
            added_count, len(lines),
        )
        return {"added": added_count, "total": len(lines), "errors": errors}

    async def _get_account_id_by_number(
        self, account_number: str, token: str, company_id: str
    ) -> Optional[str]:
        """Look up a BC GL account's GUID by its number (e.g. '60500').
        Returns None if not found. Mirrors ``_get_item_id_by_code``."""
        url = (
            f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/v2.0/"
            f"companies({company_id})/accounts"
        )
        try:
            async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params={
                        "$filter": f"number eq '{account_number}'",
                        "$select": "id,number,displayName",
                    },
                )
                if resp.status_code == 200:
                    accounts = resp.json().get("value", [])
                    if accounts:
                        acc = accounts[0]
                        logger.info(
                            "[BCAddLines] Resolved GL '%s' -> %s (%s)",
                            account_number, acc.get("displayName"), acc["id"],
                        )
                        return acc["id"]
                    logger.warning(
                        "[BCAddLines] GL account '%s' not found in BC",
                        account_number,
                    )
                    return None
                logger.error(
                    "[BCAddLines] Failed GL lookup '%s': HTTP %d",
                    account_number, resp.status_code,
                )
                return None
        except Exception as e:
            logger.error(
                "[BCAddLines] Exception looking up GL '%s': %s",
                account_number, e,
            )
            return None
    
    async def _get_item_id_by_code(self, item_code: str, token: str, company_id: str) -> Optional[str]:
        """
        Look up an Item's GUID by its number/code.
        
        Args:
            item_code: The item number (e.g., "FREIGHT")
            token: BC API access token
            company_id: BC company GUID
            
        Returns:
            The item's GUID if found, None otherwise
        """
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/v2.0/companies({company_id})/items"
        
        try:
            async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"},
                    params={
                        "$filter": f"number eq '{item_code}'",
                        "$select": "id,number,displayName"
                    }
                )
                
                if resp.status_code == 200:
                    items = resp.json().get("value", [])
                    if items:
                        item = items[0]
                        logger.info("Found Item '%s': %s (ID: %s)", 
                                   item_code, item.get("displayName"), item["id"])
                        return item["id"]
                    else:
                        # Item not found - log available items to help debug
                        logger.warning("Item '%s' not found in BC. Listing available items...", item_code)
                        list_resp = await client.get(
                            url,
                            headers={"Authorization": f"Bearer {token}"},
                            params={"$select": "number,displayName", "$top": "20"}
                        )
                        if list_resp.status_code == 200:
                            available = list_resp.json().get("value", [])
                            item_list = [f"{i.get('number')}: {i.get('displayName')}" for i in available]
                            logger.warning("Available items in BC: %s", ", ".join(item_list[:10]))
                        return None
                else:
                    logger.error("Failed to look up Item '%s': HTTP %d - %s", 
                                item_code, resp.status_code, resp.text[:200])
                    return None
        except Exception as e:
            logger.error("Error looking up Item '%s': %s", item_code, str(e))
            return None
    
    async def get_purchase_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        """Get a purchase invoice by ID. Uses READ environment."""
        if self.use_mock:
            return {
                "id": invoice_id,
                "number": f"PI-{invoice_id[:8]}",
                "status": "Draft",
                "mock": True
            }
        
        token = await get_bc_token(environment=BC_READ_ENVIRONMENT)
        company_id = await self._get_company_id(environment=BC_READ_ENVIRONMENT)
        
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices({invoice_id})"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            
            if resp.status_code == 404:
                return None
            if resp.status_code != 200:
                raise Exception(f"Failed to get purchase invoice: {resp.status_code}")
            
            return resp.json()
    
    async def update_purchase_invoice_link(
        self, 
        invoice_id: str, 
        sharepoint_url: str,
        bc_document_no: str = None,
        sharepoint_drive_id: str = None,
        sharepoint_item_id: str = None,
        uploaded_by: str = "GPI Hub"
    ) -> Dict[str, Any]:
        """
        Write SharePoint link to BC via the GPI Document Links custom API.
        
        This creates or updates a record in the GPI Document Link table in BC,
        which is displayed in the "GPI Documents" factbox on Purchase Invoice pages.
        
        Args:
            invoice_id: The BC purchase invoice ID (SystemId/GUID)
            sharepoint_url: The SharePoint sharing link or web URL
            bc_document_no: Optional BC document number for display
            sharepoint_drive_id: Optional SharePoint drive ID
            sharepoint_item_id: Optional SharePoint item ID
            uploaded_by: Who uploaded the document (default: "GPI Hub")
            
        Returns:
            Dict with success status and any error details
        """
        # Check feature flag
        if not BC_WRITEBACK_LINK_ENABLED:
            return {
                "success": False,
                "skipped": True,
                "reason": "BC_WRITEBACK_LINK_ENABLED is false"
            }
        
        if self.use_mock:
            logger.info("MOCK: Would write SharePoint link to BC GPI Document Links for invoice %s: %s", invoice_id, sharepoint_url)
            return {
                "success": True,
                "mock": True,
                "message": "SharePoint link writeback simulated (mock mode)"
            }
        
        try:
            # HARD GUARD: refuse writes to Production
            _check_write_protection("update_purchase_invoice_link")
            
            token = await get_bc_token(environment=BC_WRITE_ENVIRONMENT)
            company_id = await self._get_company_id(environment=BC_WRITE_ENVIRONMENT)
            
            # Use the GPI Document Links custom API endpoint
            api_base_url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/gpi/documents/v1.0/companies({company_id})/documentLinks"
            
            async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
                # First, check if a link already exists for this invoice
                filter_query = f"documentType eq 'Purchase Invoice' and targetSystemId eq {invoice_id}"
                check_url = f"{api_base_url}?$filter={filter_query}"
                
                check_resp = await client.get(
                    check_url,
                    headers={"Authorization": f"Bearer {token}"}
                )
                
                existing_link = None
                if check_resp.status_code == 200:
                    data = check_resp.json()
                    links = data.get("value", [])
                    if links:
                        existing_link = links[0]
                
                # Build the payload
                payload = {
                    "documentType": "Purchase Invoice",
                    "targetSystemId": invoice_id,
                    "sharePointUrl": sharepoint_url,
                    "uploadedAt": datetime.now(timezone.utc).isoformat(),
                    "uploadedBy": uploaded_by,
                    "source": "GPIHub"
                }
                
                if bc_document_no:
                    payload["bcDocumentNo"] = bc_document_no
                if sharepoint_drive_id:
                    payload["sharePointDriveId"] = sharepoint_drive_id
                if sharepoint_item_id:
                    payload["sharePointItemId"] = sharepoint_item_id
                
                if existing_link:
                    # PATCH existing record
                    link_id = existing_link.get("id")
                    patch_url = f"{api_base_url}({link_id})"
                    resp = await client.patch(
                        patch_url,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json",
                            "If-Match": "*"  # Overwrite regardless of etag
                        },
                        json=payload
                    )
                    action = "updated"
                else:
                    # POST new record
                    resp = await client.post(
                        api_base_url,
                        headers={
                            "Authorization": f"Bearer {token}",
                            "Content-Type": "application/json"
                        },
                        json=payload
                    )
                    action = "created"
                
                if resp.status_code in (200, 201):
                    link_data = resp.json()
                    logger.info("Successfully %s GPI Document Link for BC invoice %s (link id: %s)", 
                               action, invoice_id, link_data.get("id"))
                    return {
                        "success": True,
                        "action": action,
                        "linkId": link_data.get("id"),
                        "entryNo": link_data.get("entryNo"),
                        "message": f"SharePoint link {action} in BC GPI Documents"
                    }
                else:
                    error_text = resp.text[:500]
                    logger.error("Failed to write GPI Document Link for BC invoice %s: HTTP %s - %s", 
                               invoice_id, resp.status_code, error_text)
                    
                    # If custom API not available, fall back to comment line method
                    if resp.status_code == 404 and "api/gpi" in str(resp.url):
                        logger.warning("GPI custom API not found, falling back to comment line method")
                        return await self._write_link_as_comment_line(invoice_id, sharepoint_url, company_id, token)
                    
                    return {
                        "success": False,
                        "error": f"BC API error (HTTP {resp.status_code})",
                        "details": error_text
                    }
                    
        except Exception as e:
            logger.error("Exception writing GPI Document Link to BC: %s", str(e))
            return {
                "success": False,
                "error": str(e)
            }
    
    async def _write_link_as_comment_line(
        self, 
        invoice_id: str, 
        sharepoint_url: str, 
        company_id: str, 
        token: str
    ) -> Dict[str, Any]:
        """
        Fallback method: Write SharePoint link as a comment line on the purchase invoice.
        Used when the GPI custom API extension is not installed.
        """
        try:
            url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices({invoice_id})/purchaseInvoiceLines"
            
            # Truncate URL if too long (BC description field is typically 100 chars)
            link_text = f"GPI Doc: {sharepoint_url}"
            if len(link_text) > 100:
                link_text = sharepoint_url[:100]
            
            async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    json={
                        "lineType": "Comment",
                        "description": link_text
                    }
                )
                
                if resp.status_code in (200, 201):
                    line_data = resp.json()
                    logger.info("Fallback: Wrote SharePoint link as comment line on BC invoice %s", invoice_id)
                    return {
                        "success": True,
                        "fallback": True,
                        "lineId": line_data.get("id"),
                        "message": "SharePoint link written as comment line (GPI extension not installed)"
                    }
                else:
                    return {
                        "success": False,
                        "error": f"Fallback failed: HTTP {resp.status_code}",
                        "details": resp.text[:300]
                    }
        except Exception as e:
            return {
                "success": False,
                "error": f"Fallback exception: {str(e)}"
            }

    async def create_sales_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a Sales Order in BC WRITE environment (Sandbox).
        Hard-blocked from writing to Production when BC_BLOCK_PRODUCTION_WRITES=true.
        """
        if self.use_mock:
            mock_bc_id = f"SO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            return {
                "success": True,
                "bcDocumentId": mock_bc_id,
                "bcDocumentNumber": mock_bc_id,
                "status": "Draft",
                "salesperson": order_data.get("salesperson", ""),
                "message": "Sales order created (mock mode)",
                "mock": True,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "bc_write_environment": BC_WRITE_ENVIRONMENT,
            }
        
        # HARD GUARD: refuse writes to Production
        _check_write_protection("create_sales_order")
        
        token = await get_bc_token(environment=BC_WRITE_ENVIRONMENT)
        company_id = await self._get_company_id(environment=BC_WRITE_ENVIRONMENT)
        
        # Build the sales order payload per BC API spec
        payload = {
            "customerNumber": order_data.get("customerNumber") or order_data.get("customer_no"),
            "orderDate": order_data.get("orderDate") or order_data.get("order_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "externalDocumentNumber": order_data.get("externalDocumentNumber") or order_data.get("po_number") or order_data.get("customer_po"),
            "currencyCode": order_data.get("currencyCode") or order_data.get("currency") or "USD",
        }
        
        # Add salesperson code (rep assignment)
        if order_data.get("salesperson"):
            payload["salesperson"] = order_data["salesperson"]
        
        # Add optional fields
        if order_data.get("requestedDeliveryDate") or order_data.get("delivery_date"):
            payload["requestedDeliveryDate"] = order_data.get("requestedDeliveryDate") or order_data.get("delivery_date")
        
        if order_data.get("shipToName"):
            payload["shipToName"] = order_data.get("shipToName")
        if order_data.get("shipToAddressLine1"):
            payload["shipToAddressLine1"] = order_data.get("shipToAddressLine1")
        if order_data.get("shipToCity"):
            payload["shipToCity"] = order_data.get("shipToCity")
        if order_data.get("shipToState"):
            payload["shipToState"] = order_data.get("shipToState")
        if order_data.get("shipToPostCode"):
            payload["shipToPostCode"] = order_data.get("shipToPostCode")
        
        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}
        
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/v2.0/companies({company_id})/salesOrders"
        
        logger.info("Creating Sales Order in BC WRITE env (%s) for customer %s", BC_WRITE_ENVIRONMENT, payload.get("customerNumber"))
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=payload
            )
            
            if resp.status_code not in (200, 201):
                error_detail = resp.text[:500]
                logger.error("Failed to create sales order: %s", error_detail)
                return {
                    "success": False,
                    "error": f"BC API error: {resp.status_code}",
                    "details": error_detail,
                    "mock": False
                }
            
            data = resp.json()
            
            # Add line items if provided
            line_result = None
            if order_data.get("lines") and len(order_data["lines"]) > 0:
                logger.info("Adding %d line items to sales order %s", len(order_data["lines"]), data.get("id"))
                line_result = await self._add_sales_order_lines(data["id"], order_data["lines"], token, company_id)
            
            logger.info("Sales Order created successfully: %s", data.get("number"))
            
            return {
                "success": True,
                "bcDocumentId": data.get("id"),
                "bcDocumentNumber": data.get("number"),
                "status": data.get("status", "Draft"),
                "message": "Sales order created successfully",
                "mock": False,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "bcResponse": data,
                "linesAdded": line_result.get("added", 0) if line_result else 0,
                "linesTotal": line_result.get("total", 0) if line_result else 0,
                "lineErrors": line_result.get("errors", []) if line_result else [],
                "bc_write_environment": BC_WRITE_ENVIRONMENT,
            }

    async def _add_sales_order_lines(self, order_id: str, lines: List[Dict], token: str, company_id: str):
        """
        Add line items to a sales order.
        
        BC Sales Order Lines API requires:
        - lineType: "Item"
        - itemNumber or itemId
        - quantity
        - unitPrice
        """
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/v2.0/companies({company_id})/salesOrders({order_id})/salesOrderLines"
        
        added_count = 0
        errors = []
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            for idx, line in enumerate(lines):
                # Get values
                item_number = line.get("itemNumber") or line.get("item_number") or line.get("item_no")
                description = line.get("description", "")
                quantity = float(line.get("quantity", 1) or 1)
                unit_price = float(line.get("unitPrice") or line.get("unit_price", 0) or 0)
                
                # Skip empty lines
                if not item_number and not description:
                    continue
                
                line_payload = {
                    "lineType": "Item",
                    "quantity": quantity,
                }
                
                if item_number:
                    line_payload["itemNumber"] = item_number
                if description:
                    line_payload["description"] = description[:100]
                if unit_price > 0:
                    line_payload["unitPrice"] = unit_price
                
                logger.info("Adding sales order line %d: item=%s, qty=%s, price=$%s", 
                           idx + 1, item_number or description[:30], quantity, unit_price)
                
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    json=line_payload
                )
                
                if resp.status_code in (200, 201):
                    added_count += 1
                else:
                    error_msg = resp.text[:300]
                    logger.warning("Failed to add sales order line %d: HTTP %d - %s", 
                                  idx + 1, resp.status_code, error_msg)
                    errors.append({
                        "line": idx + 1,
                        "error": error_msg
                    })
        
        return {"added": added_count, "total": len(lines), "errors": errors}


# =============================================================================
# MODULE-LEVEL CONVENIENCE FUNCTIONS
# =============================================================================

# Create a default service instance
_default_service = None

def get_bc_service(use_mock: bool = None) -> BusinessCentralService:
    """Get the BusinessCentralService instance."""
    global _default_service
    if _default_service is None or use_mock is not None:
        _default_service = BusinessCentralService(use_mock=use_mock)
    return _default_service


async def search_vendors(filter_text: str = None, limit: int = 50) -> Dict[str, Any]:
    """Convenience function to search vendors."""
    service = get_bc_service()
    return await service.get_vendors(filter_text, limit)


async def search_purchase_orders(vendor_id: str = None, limit: int = 50) -> Dict[str, Any]:
    """Convenience function to search purchase orders."""
    service = get_bc_service()
    return await service.get_open_purchase_orders(vendor_id, limit)


async def post_purchase_invoice(invoice_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function to create a purchase invoice."""
    service = get_bc_service()
    return await service.create_purchase_invoice(invoice_data)


async def post_sales_order(order_data: Dict[str, Any]) -> Dict[str, Any]:
    """Convenience function to create a sales order."""
    service = get_bc_service()
    return await service.create_sales_order(order_data)
