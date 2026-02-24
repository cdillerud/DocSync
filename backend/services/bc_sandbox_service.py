"""
GPI Document Hub - Business Central Sandbox Service

This module provides read-only access to the BC sandbox for vendor, customer,
purchase order, and invoice lookups. All functions are strictly read-only.

NO WRITES. NO POSTING. NO UPDATES.

Feature Flag: PILOT_MODE_ENABLED
- When True: Write operations throw PilotModeWriteBlockedError
- BC validation runs in observation mode (results logged, no external effects)

Configuration:
- BC_SANDBOX_CLIENT_ID: App registration client ID
- BC_SANDBOX_TENANT_ID: Azure AD tenant ID  
- BC_SANDBOX_CLIENT_SECRET: App registration client secret
- BC_SANDBOX_ENVIRONMENT: BC sandbox environment name (e.g., "Sandbox")
"""

import os
import logging
import time
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List, Tuple
from enum import Enum
import httpx

from services.pilot_config import (
    PILOT_MODE_ENABLED, is_external_write_blocked,
    create_pilot_log_entry
)

logger = logging.getLogger(__name__)


# =============================================================================
# CONFIGURATION
# =============================================================================

# BC Sandbox credentials - use provided app registration
BC_SANDBOX_CLIENT_ID = os.environ.get('BC_SANDBOX_CLIENT_ID', '22c4e601-51e8-4305-bd63-d4aa7d19defd')
BC_SANDBOX_TENANT_ID = os.environ.get('BC_SANDBOX_TENANT_ID', 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc')
# Check both env var names for the secret (BC_SANDBOX_CLIENT_SECRET or BC_CLIENT_SECRET)
BC_SANDBOX_CLIENT_SECRET = os.environ.get('BC_SANDBOX_CLIENT_SECRET') or os.environ.get('BC_CLIENT_SECRET', '')
BC_SANDBOX_ENVIRONMENT = os.environ.get('BC_SANDBOX_ENVIRONMENT', 'Sandbox')
BC_SANDBOX_COMPANY_NAME = os.environ.get('BC_SANDBOX_COMPANY_NAME', '')

# Demo mode for testing without real BC connection
DEMO_MODE = os.environ.get('DEMO_MODE', 'true').lower() == 'true'

# API base URL
BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"

# Request timeout
BC_REQUEST_TIMEOUT = 30.0


# =============================================================================
# EXCEPTIONS
# =============================================================================

class PilotModeWriteBlockedError(Exception):
    """
    Raised when a write operation is attempted during pilot mode.
    All BC write operations are blocked during the shadow pilot.
    """
    def __init__(self, operation: str, message: str = None):
        self.operation = operation
        self.message = message or f"Write operation '{operation}' blocked during pilot mode"
        super().__init__(self.message)


class BCSandboxError(Exception):
    """Base exception for BC Sandbox service errors."""
    def __init__(self, message: str, status_code: int = None, details: Dict = None):
        self.message = message
        self.status_code = status_code
        self.details = details or {}
        super().__init__(self.message)


class BCAuthenticationError(BCSandboxError):
    """Raised when BC authentication fails."""
    pass


class BCNotFoundError(BCSandboxError):
    """Raised when a requested resource is not found in BC."""
    pass


class BCValidationError(BCSandboxError):
    """Raised when BC validation fails."""
    pass


# =============================================================================
# LOOKUP RESULT TYPES
# =============================================================================

class BCLookupStatus(str, Enum):
    """Status of a BC lookup operation."""
    SUCCESS = "success"
    NOT_FOUND = "not_found"
    ERROR = "error"
    DEMO_MODE = "demo_mode"
    PILOT_BLOCKED = "pilot_blocked"


class BCLookupResult:
    """Result of a BC lookup operation with metadata."""
    
    def __init__(
        self,
        status: BCLookupStatus,
        data: Optional[Dict] = None,
        error: Optional[str] = None,
        timing_ms: int = 0,
        endpoint: str = "",
        response_size: int = 0
    ):
        self.status = status
        self.data = data or {}
        self.error = error
        self.timing_ms = timing_ms
        self.endpoint = endpoint
        self.response_size = response_size
        self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict:
        return {
            "status": self.status.value,
            "data": self.data,
            "error": self.error,
            "timing_ms": self.timing_ms,
            "endpoint": self.endpoint,
            "response_size": self.response_size,
            "timestamp": self.timestamp
        }
    
    @property
    def is_success(self) -> bool:
        return self.status == BCLookupStatus.SUCCESS
    
    @property
    def is_found(self) -> bool:
        return self.status in [BCLookupStatus.SUCCESS, BCLookupStatus.DEMO_MODE] and bool(self.data)


# =============================================================================
# MOCK DATA FOR DEMO MODE
# =============================================================================

MOCK_VENDORS = [
    {"number": "V10000", "displayName": "Acme Supplies Inc", "id": "v1-mock-id", "email": "ap@acmesupplies.com", "phoneNumber": "555-0100", "balance": 12500.00},
    {"number": "V10001", "displayName": "Global Packaging Co", "id": "v2-mock-id", "email": "billing@globalpack.com", "phoneNumber": "555-0101", "balance": 8750.50},
    {"number": "V10002", "displayName": "Industrial Materials Ltd", "id": "v3-mock-id", "email": "accounts@indmaterials.com", "phoneNumber": "555-0102", "balance": 3200.00},
    {"number": "V10003", "displayName": "TechParts Direct", "id": "v4-mock-id", "email": "ar@techpartsdirect.com", "phoneNumber": "555-0103", "balance": 15000.00},
    {"number": "V10004", "displayName": "Quality Components Inc", "id": "v5-mock-id", "email": "invoices@qualitycomp.com", "phoneNumber": "555-0104", "balance": 6800.25},
]

MOCK_CUSTOMERS = [
    {"number": "C20000", "displayName": "Acme Corp", "id": "c1-mock-id", "email": "purchasing@acmecorp.com", "phoneNumber": "555-1000", "balance": 45000.00},
    {"number": "C20001", "displayName": "Widget Co", "id": "c2-mock-id", "email": "orders@widgetco.com", "phoneNumber": "555-1001", "balance": 28000.00},
    {"number": "C20002", "displayName": "TechnoServ Ltd", "id": "c3-mock-id", "email": "procurement@technoserv.com", "phoneNumber": "555-1002", "balance": 62000.00},
    {"number": "C20003", "displayName": "PackRight Inc", "id": "c4-mock-id", "email": "ap@packright.com", "phoneNumber": "555-1003", "balance": 15500.00},
]

MOCK_PURCHASE_ORDERS = [
    {"number": "PO-001", "id": "po1-mock-id", "vendorNumber": "V10000", "vendorName": "Acme Supplies Inc", "orderDate": "2026-01-15", "status": "Open", "totalAmount": 5000.00},
    {"number": "PO-002", "id": "po2-mock-id", "vendorNumber": "V10001", "vendorName": "Global Packaging Co", "orderDate": "2026-01-20", "status": "Released", "totalAmount": 12500.00},
    {"number": "PO-003", "id": "po3-mock-id", "vendorNumber": "V10002", "vendorName": "Industrial Materials Ltd", "orderDate": "2026-02-01", "status": "Open", "totalAmount": 3200.00},
]

MOCK_PURCHASE_INVOICES = [
    {"number": "PI-1001", "id": "pi1-mock-id", "vendorNumber": "V10000", "vendorName": "Acme Supplies Inc", "vendorInvoiceNumber": "INV-2026-001", "postingDate": "2026-01-18", "status": "Open", "totalAmountIncludingTax": 5250.00},
    {"number": "PI-1002", "id": "pi2-mock-id", "vendorNumber": "V10001", "vendorName": "Global Packaging Co", "vendorInvoiceNumber": "GP-78542", "postingDate": "2026-01-22", "status": "Open", "totalAmountIncludingTax": 13125.00},
    {"number": "PI-1003", "id": "pi3-mock-id", "vendorNumber": "V10003", "vendorName": "TechParts Direct", "vendorInvoiceNumber": "TPD-2026-0045", "postingDate": "2026-02-05", "status": "Paid", "totalAmountIncludingTax": 8500.00},
]

MOCK_SALES_INVOICES = [
    {"number": "SI-5001", "id": "si1-mock-id", "customerNumber": "C20000", "customerName": "Acme Corp", "postingDate": "2026-01-10", "status": "Open", "totalAmountIncludingTax": 12500.00},
    {"number": "SI-5002", "id": "si2-mock-id", "customerNumber": "C20001", "customerName": "Widget Co", "postingDate": "2026-01-15", "status": "Paid", "totalAmountIncludingTax": 8750.00},
    {"number": "SI-5003", "id": "si3-mock-id", "customerNumber": "C20002", "customerName": "TechnoServ Ltd", "postingDate": "2026-02-01", "status": "Open", "totalAmountIncludingTax": 25000.00},
]


# =============================================================================
# AUTHENTICATION
# =============================================================================

_token_cache: Dict[str, Any] = {
    "token": None,
    "expires_at": None
}


async def get_bc_sandbox_token() -> str:
    """
    Get OAuth2 token for BC sandbox API access.
    Uses client credentials flow with caching.
    
    Returns:
        Access token string
        
    Raises:
        BCAuthenticationError: If authentication fails
    """
    global _token_cache
    
    # Check for demo mode
    if DEMO_MODE or not BC_SANDBOX_CLIENT_SECRET:
        logger.debug("BC Sandbox: Using mock token (DEMO_MODE or no secret)")
        return "mock-bc-sandbox-token"
    
    # Check cache
    if _token_cache["token"] and _token_cache["expires_at"]:
        if datetime.now(timezone.utc).timestamp() < _token_cache["expires_at"] - 60:
            return _token_cache["token"]
    
    # Request new token
    token_url = f"https://login.microsoftonline.com/{BC_SANDBOX_TENANT_ID}/oauth2/v2.0/token"
    
    start_time = time.time()
    try:
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            response = await client.post(
                token_url,
                data={
                    "grant_type": "client_credentials",
                    "client_id": BC_SANDBOX_CLIENT_ID,
                    "client_secret": BC_SANDBOX_CLIENT_SECRET,
                    "scope": "https://api.businesscentral.dynamics.com/.default"
                }
            )
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            
            if response.status_code != 200:
                error_data = response.json() if response.content else {}
                logger.error(
                    "BC Sandbox auth failed: status=%d, error=%s, timing=%dms",
                    response.status_code, error_data.get("error_description", "Unknown"), elapsed_ms
                )
                raise BCAuthenticationError(
                    f"BC authentication failed: {error_data.get('error_description', 'Unknown error')}",
                    status_code=response.status_code,
                    details=error_data
                )
            
            data = response.json()
            _token_cache["token"] = data["access_token"]
            _token_cache["expires_at"] = datetime.now(timezone.utc).timestamp() + data.get("expires_in", 3600)
            
            logger.info("BC Sandbox: Token acquired successfully, timing=%dms", elapsed_ms)
            return _token_cache["token"]
            
    except httpx.RequestError as e:
        logger.error("BC Sandbox auth request error: %s", str(e))
        raise BCAuthenticationError(f"BC authentication request failed: {str(e)}")


async def _get_companies() -> List[Dict]:
    """Get list of companies from BC sandbox."""
    if DEMO_MODE or not BC_SANDBOX_CLIENT_SECRET:
        return [{"id": "mock-company-id", "name": BC_SANDBOX_COMPANY_NAME or "Mock Company", "displayName": "Mock Company"}]
    
    token = await get_bc_sandbox_token()
    url = f"{BC_API_BASE}/{BC_SANDBOX_TENANT_ID}/{BC_SANDBOX_ENVIRONMENT}/api/v2.0/companies"
    
    async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
        response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if response.status_code == 200:
            return response.json().get("value", [])
        return []


async def _get_company_id() -> str:
    """Get the primary company ID for API calls."""
    companies = await _get_companies()
    if not companies:
        raise BCSandboxError("No companies found in BC sandbox")
    
    # Try to match by name first
    if BC_SANDBOX_COMPANY_NAME:
        for company in companies:
            if company.get("name", "").lower() == BC_SANDBOX_COMPANY_NAME.lower():
                return company["id"]
    
    # Return first company
    return companies[0]["id"]


# =============================================================================
# PILOT GUARDS - BLOCK ALL WRITE OPERATIONS
# =============================================================================

def _block_if_write_operation(operation: str):
    """
    Guard function that blocks any write operation during pilot mode.
    
    Args:
        operation: Name of the operation being attempted
        
    Raises:
        PilotModeWriteBlockedError: Always, because writes are never allowed
    """
    # ALWAYS block write operations - this service is READ-ONLY
    raise PilotModeWriteBlockedError(
        operation=operation,
        message=f"BC Sandbox Service is READ-ONLY. Write operation '{operation}' is not permitted."
    )


# The following are placeholder functions that will ALWAYS raise errors
# They exist only to provide clear error messages if someone tries to call them

async def create_vendor(*args, **kwargs):
    """BLOCKED: Vendor creation is not allowed."""
    _block_if_write_operation("create_vendor")

async def update_vendor(*args, **kwargs):
    """BLOCKED: Vendor updates are not allowed."""
    _block_if_write_operation("update_vendor")

async def delete_vendor(*args, **kwargs):
    """BLOCKED: Vendor deletion is not allowed."""
    _block_if_write_operation("delete_vendor")

async def create_purchase_invoice(*args, **kwargs):
    """BLOCKED: Purchase invoice creation is not allowed."""
    _block_if_write_operation("create_purchase_invoice")

async def post_purchase_invoice(*args, **kwargs):
    """BLOCKED: Purchase invoice posting is not allowed."""
    _block_if_write_operation("post_purchase_invoice")

async def update_purchase_invoice(*args, **kwargs):
    """BLOCKED: Purchase invoice updates are not allowed."""
    _block_if_write_operation("update_purchase_invoice")

async def create_sales_invoice(*args, **kwargs):
    """BLOCKED: Sales invoice creation is not allowed."""
    _block_if_write_operation("create_sales_invoice")

async def post_sales_invoice(*args, **kwargs):
    """BLOCKED: Sales invoice posting is not allowed."""
    _block_if_write_operation("post_sales_invoice")


# =============================================================================
# READ-ONLY LOOKUP FUNCTIONS
# =============================================================================

async def get_vendor(vendor_number: str) -> BCLookupResult:
    """
    Get vendor details by vendor number.
    
    Args:
        vendor_number: BC vendor number (e.g., "V10000")
        
    Returns:
        BCLookupResult with vendor data or error
    """
    start_time = time.time()
    endpoint = f"vendors?$filter=number eq '{vendor_number}'"
    
    logger.info("BC Sandbox: get_vendor called, vendor_number=%s", vendor_number)
    
    # Demo mode
    if DEMO_MODE or not BC_SANDBOX_CLIENT_SECRET:
        elapsed_ms = int((time.time() - start_time) * 1000)
        for vendor in MOCK_VENDORS:
            if vendor["number"] == vendor_number:
                logger.info(
                    "BC Sandbox [DEMO]: get_vendor SUCCESS, vendor=%s, timing=%dms",
                    vendor_number, elapsed_ms
                )
                return BCLookupResult(
                    status=BCLookupStatus.DEMO_MODE,
                    data=vendor,
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=len(str(vendor))
                )
        logger.info("BC Sandbox [DEMO]: get_vendor NOT_FOUND, vendor=%s", vendor_number)
        return BCLookupResult(
            status=BCLookupStatus.NOT_FOUND,
            error=f"Vendor {vendor_number} not found",
            timing_ms=elapsed_ms,
            endpoint=endpoint
        )
    
    try:
        token = await get_bc_sandbox_token()
        company_id = await _get_company_id()
        url = f"{BC_API_BASE}/{BC_SANDBOX_TENANT_ID}/{BC_SANDBOX_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"$filter": f"number eq '{vendor_number}'"}
            )
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            response_size = len(response.content)
            
            logger.info(
                "BC Sandbox: get_vendor response, vendor=%s, status=%d, size=%d bytes, timing=%dms, url=%s",
                vendor_number, response.status_code, response_size, elapsed_ms, url
            )
            
            if response.status_code == 200:
                data = response.json()
                vendors = data.get("value", [])
                if vendors:
                    return BCLookupResult(
                        status=BCLookupStatus.SUCCESS,
                        data=vendors[0],
                        timing_ms=elapsed_ms,
                        endpoint=endpoint,
                        response_size=response_size
                    )
                return BCLookupResult(
                    status=BCLookupStatus.NOT_FOUND,
                    error=f"Vendor {vendor_number} not found",
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=response_size
                )
            else:
                return BCLookupResult(
                    status=BCLookupStatus.ERROR,
                    error=f"BC API error: {response.status_code}",
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=response_size
                )
                
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error("BC Sandbox: get_vendor error, vendor=%s, error=%s", vendor_number, str(e))
        return BCLookupResult(
            status=BCLookupStatus.ERROR,
            error=str(e),
            timing_ms=elapsed_ms,
            endpoint=endpoint
        )


async def search_vendors_by_name(name_fragment: str, limit: int = 20) -> BCLookupResult:
    """
    Search vendors by name fragment (case-insensitive contains search).
    
    Args:
        name_fragment: Partial vendor name to search for
        limit: Maximum number of results
        
    Returns:
        BCLookupResult with list of matching vendors
    """
    start_time = time.time()
    endpoint = f"vendors?$filter=contains(displayName,'{name_fragment}')"
    
    logger.info("BC Sandbox: search_vendors_by_name called, fragment=%s", name_fragment)
    
    # Demo mode
    if DEMO_MODE or not BC_SANDBOX_CLIENT_SECRET:
        elapsed_ms = int((time.time() - start_time) * 1000)
        matches = [v for v in MOCK_VENDORS if name_fragment.lower() in v["displayName"].lower()][:limit]
        logger.info(
            "BC Sandbox [DEMO]: search_vendors SUCCESS, fragment=%s, matches=%d, timing=%dms",
            name_fragment, len(matches), elapsed_ms
        )
        return BCLookupResult(
            status=BCLookupStatus.DEMO_MODE,
            data={"vendors": matches, "count": len(matches)},
            timing_ms=elapsed_ms,
            endpoint=endpoint,
            response_size=len(str(matches))
        )
    
    try:
        token = await get_bc_sandbox_token()
        company_id = await _get_company_id()
        url = f"{BC_API_BASE}/{BC_SANDBOX_TENANT_ID}/{BC_SANDBOX_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": f"contains(displayName,'{name_fragment}')",
                    "$top": limit
                }
            )
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            response_size = len(response.content)
            
            logger.info(
                "BC Sandbox: search_vendors response, fragment=%s, status=%d, size=%d bytes, timing=%dms",
                name_fragment, response.status_code, response_size, elapsed_ms
            )
            
            if response.status_code == 200:
                data = response.json()
                vendors = data.get("value", [])
                return BCLookupResult(
                    status=BCLookupStatus.SUCCESS,
                    data={"vendors": vendors, "count": len(vendors)},
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=response_size
                )
            else:
                return BCLookupResult(
                    status=BCLookupStatus.ERROR,
                    error=f"BC API error: {response.status_code}",
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=response_size
                )
                
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error("BC Sandbox: search_vendors error, fragment=%s, error=%s", name_fragment, str(e))
        return BCLookupResult(
            status=BCLookupStatus.ERROR,
            error=str(e),
            timing_ms=elapsed_ms,
            endpoint=endpoint
        )


async def validate_vendor_exists(vendor_number: str) -> Tuple[bool, BCLookupResult]:
    """
    Validate that a vendor exists in BC.
    
    Args:
        vendor_number: BC vendor number
        
    Returns:
        Tuple of (exists: bool, lookup_result: BCLookupResult)
    """
    result = await get_vendor(vendor_number)
    exists = result.is_found
    logger.info(
        "BC Sandbox: validate_vendor_exists, vendor=%s, exists=%s, timing=%dms",
        vendor_number, exists, result.timing_ms
    )
    return (exists, result)


async def get_customer(customer_number: str) -> BCLookupResult:
    """
    Get customer details by customer number.
    
    Args:
        customer_number: BC customer number (e.g., "C20000")
        
    Returns:
        BCLookupResult with customer data or error
    """
    start_time = time.time()
    endpoint = f"customers?$filter=number eq '{customer_number}'"
    
    logger.info("BC Sandbox: get_customer called, customer_number=%s", customer_number)
    
    # Demo mode
    if DEMO_MODE or not BC_SANDBOX_CLIENT_SECRET:
        elapsed_ms = int((time.time() - start_time) * 1000)
        for customer in MOCK_CUSTOMERS:
            if customer["number"] == customer_number:
                logger.info(
                    "BC Sandbox [DEMO]: get_customer SUCCESS, customer=%s, timing=%dms",
                    customer_number, elapsed_ms
                )
                return BCLookupResult(
                    status=BCLookupStatus.DEMO_MODE,
                    data=customer,
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=len(str(customer))
                )
        return BCLookupResult(
            status=BCLookupStatus.NOT_FOUND,
            error=f"Customer {customer_number} not found",
            timing_ms=elapsed_ms,
            endpoint=endpoint
        )
    
    try:
        token = await get_bc_sandbox_token()
        company_id = await _get_company_id()
        url = f"{BC_API_BASE}/{BC_SANDBOX_TENANT_ID}/{BC_SANDBOX_ENVIRONMENT}/api/v2.0/companies({company_id})/customers"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"$filter": f"number eq '{customer_number}'"}
            )
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            response_size = len(response.content)
            
            logger.info(
                "BC Sandbox: get_customer response, customer=%s, status=%d, size=%d bytes, timing=%dms",
                customer_number, response.status_code, response_size, elapsed_ms
            )
            
            if response.status_code == 200:
                data = response.json()
                customers = data.get("value", [])
                if customers:
                    return BCLookupResult(
                        status=BCLookupStatus.SUCCESS,
                        data=customers[0],
                        timing_ms=elapsed_ms,
                        endpoint=endpoint,
                        response_size=response_size
                    )
                return BCLookupResult(
                    status=BCLookupStatus.NOT_FOUND,
                    error=f"Customer {customer_number} not found",
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=response_size
                )
            else:
                return BCLookupResult(
                    status=BCLookupStatus.ERROR,
                    error=f"BC API error: {response.status_code}",
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=response_size
                )
                
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error("BC Sandbox: get_customer error, customer=%s, error=%s", customer_number, str(e))
        return BCLookupResult(
            status=BCLookupStatus.ERROR,
            error=str(e),
            timing_ms=elapsed_ms,
            endpoint=endpoint
        )


async def get_purchase_order(po_number: str) -> BCLookupResult:
    """
    Get purchase order details by PO number.
    
    Args:
        po_number: Purchase order number (e.g., "PO-001")
        
    Returns:
        BCLookupResult with PO data or error
    """
    start_time = time.time()
    endpoint = f"purchaseOrders?$filter=number eq '{po_number}'"
    
    logger.info("BC Sandbox: get_purchase_order called, po_number=%s", po_number)
    
    # Demo mode
    if DEMO_MODE or not BC_SANDBOX_CLIENT_SECRET:
        elapsed_ms = int((time.time() - start_time) * 1000)
        for po in MOCK_PURCHASE_ORDERS:
            if po["number"] == po_number:
                logger.info(
                    "BC Sandbox [DEMO]: get_purchase_order SUCCESS, po=%s, timing=%dms",
                    po_number, elapsed_ms
                )
                return BCLookupResult(
                    status=BCLookupStatus.DEMO_MODE,
                    data=po,
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=len(str(po))
                )
        return BCLookupResult(
            status=BCLookupStatus.NOT_FOUND,
            error=f"Purchase Order {po_number} not found",
            timing_ms=elapsed_ms,
            endpoint=endpoint
        )
    
    try:
        token = await get_bc_sandbox_token()
        company_id = await _get_company_id()
        url = f"{BC_API_BASE}/{BC_SANDBOX_TENANT_ID}/{BC_SANDBOX_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseOrders"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"$filter": f"number eq '{po_number}'"}
            )
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            response_size = len(response.content)
            
            logger.info(
                "BC Sandbox: get_purchase_order response, po=%s, status=%d, size=%d bytes, timing=%dms",
                po_number, response.status_code, response_size, elapsed_ms
            )
            
            if response.status_code == 200:
                data = response.json()
                orders = data.get("value", [])
                if orders:
                    return BCLookupResult(
                        status=BCLookupStatus.SUCCESS,
                        data=orders[0],
                        timing_ms=elapsed_ms,
                        endpoint=endpoint,
                        response_size=response_size
                    )
                return BCLookupResult(
                    status=BCLookupStatus.NOT_FOUND,
                    error=f"Purchase Order {po_number} not found",
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=response_size
                )
            else:
                return BCLookupResult(
                    status=BCLookupStatus.ERROR,
                    error=f"BC API error: {response.status_code}",
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=response_size
                )
                
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error("BC Sandbox: get_purchase_order error, po=%s, error=%s", po_number, str(e))
        return BCLookupResult(
            status=BCLookupStatus.ERROR,
            error=str(e),
            timing_ms=elapsed_ms,
            endpoint=endpoint
        )


async def get_purchase_invoice(invoice_number: str) -> BCLookupResult:
    """
    Get purchase invoice details by invoice number.
    
    Args:
        invoice_number: Purchase invoice number (e.g., "PI-1001")
        
    Returns:
        BCLookupResult with invoice data or error
    """
    start_time = time.time()
    endpoint = f"purchaseInvoices?$filter=number eq '{invoice_number}'"
    
    logger.info("BC Sandbox: get_purchase_invoice called, invoice_number=%s", invoice_number)
    
    # Demo mode
    if DEMO_MODE or not BC_SANDBOX_CLIENT_SECRET:
        elapsed_ms = int((time.time() - start_time) * 1000)
        for invoice in MOCK_PURCHASE_INVOICES:
            if invoice["number"] == invoice_number:
                logger.info(
                    "BC Sandbox [DEMO]: get_purchase_invoice SUCCESS, invoice=%s, timing=%dms",
                    invoice_number, elapsed_ms
                )
                return BCLookupResult(
                    status=BCLookupStatus.DEMO_MODE,
                    data=invoice,
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=len(str(invoice))
                )
        return BCLookupResult(
            status=BCLookupStatus.NOT_FOUND,
            error=f"Purchase Invoice {invoice_number} not found",
            timing_ms=elapsed_ms,
            endpoint=endpoint
        )
    
    try:
        token = await get_bc_sandbox_token()
        company_id = await _get_company_id()
        url = f"{BC_API_BASE}/{BC_SANDBOX_TENANT_ID}/{BC_SANDBOX_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"$filter": f"number eq '{invoice_number}'"}
            )
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            response_size = len(response.content)
            
            logger.info(
                "BC Sandbox: get_purchase_invoice response, invoice=%s, status=%d, size=%d bytes, timing=%dms",
                invoice_number, response.status_code, response_size, elapsed_ms
            )
            
            if response.status_code == 200:
                data = response.json()
                invoices = data.get("value", [])
                if invoices:
                    return BCLookupResult(
                        status=BCLookupStatus.SUCCESS,
                        data=invoices[0],
                        timing_ms=elapsed_ms,
                        endpoint=endpoint,
                        response_size=response_size
                    )
                return BCLookupResult(
                    status=BCLookupStatus.NOT_FOUND,
                    error=f"Purchase Invoice {invoice_number} not found",
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=response_size
                )
            else:
                return BCLookupResult(
                    status=BCLookupStatus.ERROR,
                    error=f"BC API error: {response.status_code}",
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=response_size
                )
                
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error("BC Sandbox: get_purchase_invoice error, invoice=%s, error=%s", invoice_number, str(e))
        return BCLookupResult(
            status=BCLookupStatus.ERROR,
            error=str(e),
            timing_ms=elapsed_ms,
            endpoint=endpoint
        )


async def get_sales_invoice(invoice_number: str) -> BCLookupResult:
    """
    Get sales invoice details by invoice number.
    
    Args:
        invoice_number: Sales invoice number (e.g., "SI-5001")
        
    Returns:
        BCLookupResult with invoice data or error
    """
    start_time = time.time()
    endpoint = f"salesInvoices?$filter=number eq '{invoice_number}'"
    
    logger.info("BC Sandbox: get_sales_invoice called, invoice_number=%s", invoice_number)
    
    # Demo mode
    if DEMO_MODE or not BC_SANDBOX_CLIENT_SECRET:
        elapsed_ms = int((time.time() - start_time) * 1000)
        for invoice in MOCK_SALES_INVOICES:
            if invoice["number"] == invoice_number:
                logger.info(
                    "BC Sandbox [DEMO]: get_sales_invoice SUCCESS, invoice=%s, timing=%dms",
                    invoice_number, elapsed_ms
                )
                return BCLookupResult(
                    status=BCLookupStatus.DEMO_MODE,
                    data=invoice,
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=len(str(invoice))
                )
        return BCLookupResult(
            status=BCLookupStatus.NOT_FOUND,
            error=f"Sales Invoice {invoice_number} not found",
            timing_ms=elapsed_ms,
            endpoint=endpoint
        )
    
    try:
        token = await get_bc_sandbox_token()
        company_id = await _get_company_id()
        url = f"{BC_API_BASE}/{BC_SANDBOX_TENANT_ID}/{BC_SANDBOX_ENVIRONMENT}/api/v2.0/companies({company_id})/salesInvoices"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            response = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"$filter": f"number eq '{invoice_number}'"}
            )
            
            elapsed_ms = int((time.time() - start_time) * 1000)
            response_size = len(response.content)
            
            logger.info(
                "BC Sandbox: get_sales_invoice response, invoice=%s, status=%d, size=%d bytes, timing=%dms",
                invoice_number, response.status_code, response_size, elapsed_ms
            )
            
            if response.status_code == 200:
                data = response.json()
                invoices = data.get("value", [])
                if invoices:
                    return BCLookupResult(
                        status=BCLookupStatus.SUCCESS,
                        data=invoices[0],
                        timing_ms=elapsed_ms,
                        endpoint=endpoint,
                        response_size=response_size
                    )
                return BCLookupResult(
                    status=BCLookupStatus.NOT_FOUND,
                    error=f"Sales Invoice {invoice_number} not found",
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=response_size
                )
            else:
                return BCLookupResult(
                    status=BCLookupStatus.ERROR,
                    error=f"BC API error: {response.status_code}",
                    timing_ms=elapsed_ms,
                    endpoint=endpoint,
                    response_size=response_size
                )
                
    except Exception as e:
        elapsed_ms = int((time.time() - start_time) * 1000)
        logger.error("BC Sandbox: get_sales_invoice error, invoice=%s, error=%s", invoice_number, str(e))
        return BCLookupResult(
            status=BCLookupStatus.ERROR,
            error=str(e),
            timing_ms=elapsed_ms,
            endpoint=endpoint
        )


async def validate_invoice_exists(
    invoice_number: str,
    invoice_type: str = "purchase"
) -> Tuple[bool, BCLookupResult]:
    """
    Validate that an invoice exists in BC.
    
    Args:
        invoice_number: Invoice number
        invoice_type: "purchase" or "sales"
        
    Returns:
        Tuple of (exists: bool, lookup_result: BCLookupResult)
    """
    if invoice_type.lower() == "sales":
        result = await get_sales_invoice(invoice_number)
    else:
        result = await get_purchase_invoice(invoice_number)
    
    exists = result.is_found
    logger.info(
        "BC Sandbox: validate_invoice_exists, invoice=%s, type=%s, exists=%s, timing=%dms",
        invoice_number, invoice_type, exists, result.timing_ms
    )
    return (exists, result)


# =============================================================================
# WORKFLOW VALIDATION HELPERS
# =============================================================================

async def validate_ap_invoice_in_bc(
    vendor_number: str,
    invoice_number: str = None,
    po_number: str = None
) -> Dict[str, Any]:
    """
    Validate AP invoice data against BC records.
    
    This runs in observation mode - results are logged but don't block workflow.
    
    Args:
        vendor_number: Vendor number from document
        invoice_number: Optional invoice number for duplicate check
        po_number: Optional PO number for reference check
        
    Returns:
        Validation result dict with all check results
    """
    start_time = time.time()
    validation_result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pilot_mode": PILOT_MODE_ENABLED,
        "observation_only": True,
        "checks": [],
        "overall_valid": True,
        "warnings": [],
        "errors": []
    }
    
    # Check 1: Vendor exists
    vendor_exists, vendor_result = await validate_vendor_exists(vendor_number)
    validation_result["checks"].append({
        "check_name": "vendor_exists",
        "passed": vendor_exists,
        "vendor_number": vendor_number,
        "bc_lookup": vendor_result.to_dict()
    })
    if not vendor_exists:
        validation_result["warnings"].append(f"Vendor {vendor_number} not found in BC")
    
    # Check 2: PO reference (if provided)
    if po_number:
        po_result = await get_purchase_order(po_number)
        po_exists = po_result.is_found
        validation_result["checks"].append({
            "check_name": "po_exists",
            "passed": po_exists,
            "po_number": po_number,
            "bc_lookup": po_result.to_dict()
        })
        if not po_exists:
            validation_result["warnings"].append(f"PO {po_number} not found in BC")
    
    # Calculate timing
    elapsed_ms = int((time.time() - start_time) * 1000)
    validation_result["total_timing_ms"] = elapsed_ms
    
    # Overall result (in observation mode, we don't fail)
    validation_result["overall_valid"] = len(validation_result["errors"]) == 0
    
    logger.info(
        "BC Sandbox: validate_ap_invoice complete, vendor=%s, overall_valid=%s, warnings=%d, timing=%dms",
        vendor_number, validation_result["overall_valid"], len(validation_result["warnings"]), elapsed_ms
    )
    
    return validation_result


async def validate_sales_invoice_in_bc(
    customer_number: str,
    invoice_number: str = None
) -> Dict[str, Any]:
    """
    Validate sales invoice data against BC records.
    
    Args:
        customer_number: Customer number from document
        invoice_number: Optional invoice number for lookup
        
    Returns:
        Validation result dict
    """
    start_time = time.time()
    validation_result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pilot_mode": PILOT_MODE_ENABLED,
        "observation_only": True,
        "checks": [],
        "overall_valid": True,
        "warnings": [],
        "errors": []
    }
    
    # Check 1: Customer exists
    customer_result = await get_customer(customer_number)
    customer_exists = customer_result.is_found
    validation_result["checks"].append({
        "check_name": "customer_exists",
        "passed": customer_exists,
        "customer_number": customer_number,
        "bc_lookup": customer_result.to_dict()
    })
    if not customer_exists:
        validation_result["warnings"].append(f"Customer {customer_number} not found in BC")
    
    # Check 2: Invoice exists (if provided)
    if invoice_number:
        invoice_exists, invoice_result = await validate_invoice_exists(invoice_number, "sales")
        validation_result["checks"].append({
            "check_name": "invoice_exists",
            "passed": invoice_exists,
            "invoice_number": invoice_number,
            "bc_lookup": invoice_result.to_dict()
        })
    
    elapsed_ms = int((time.time() - start_time) * 1000)
    validation_result["total_timing_ms"] = elapsed_ms
    validation_result["overall_valid"] = len(validation_result["errors"]) == 0
    
    logger.info(
        "BC Sandbox: validate_sales_invoice complete, customer=%s, timing=%dms",
        customer_number, elapsed_ms
    )
    
    return validation_result


async def validate_purchase_order_in_bc(po_number: str) -> Dict[str, Any]:
    """
    Validate purchase order data against BC records.
    
    Args:
        po_number: PO number from document
        
    Returns:
        Validation result dict
    """
    start_time = time.time()
    validation_result = {
        "timestamp": datetime.now(timezone.utc).isoformat(),
        "pilot_mode": PILOT_MODE_ENABLED,
        "observation_only": True,
        "checks": [],
        "overall_valid": True,
        "warnings": [],
        "errors": []
    }
    
    # Check: PO exists
    po_result = await get_purchase_order(po_number)
    po_exists = po_result.is_found
    validation_result["checks"].append({
        "check_name": "po_exists",
        "passed": po_exists,
        "po_number": po_number,
        "bc_lookup": po_result.to_dict()
    })
    
    if po_exists and po_result.data:
        validation_result["bc_po_data"] = {
            "vendor_number": po_result.data.get("vendorNumber"),
            "vendor_name": po_result.data.get("vendorName"),
            "status": po_result.data.get("status"),
            "total_amount": po_result.data.get("totalAmount")
        }
    else:
        validation_result["warnings"].append(f"PO {po_number} not found in BC")
    
    elapsed_ms = int((time.time() - start_time) * 1000)
    validation_result["total_timing_ms"] = elapsed_ms
    validation_result["overall_valid"] = len(validation_result["errors"]) == 0
    
    logger.info(
        "BC Sandbox: validate_purchase_order complete, po=%s, exists=%s, timing=%dms",
        po_number, po_exists, elapsed_ms
    )
    
    return validation_result


# =============================================================================
# SERVICE STATUS
# =============================================================================

def get_bc_sandbox_status() -> Dict[str, Any]:
    """
    Get BC Sandbox service status and configuration.
    
    Returns:
        Status dict with config info (secrets masked)
    """
    return {
        "service": "bc_sandbox_service",
        "demo_mode": DEMO_MODE,
        "pilot_mode": PILOT_MODE_ENABLED,
        "read_only": True,
        "write_operations_blocked": True,
        "config": {
            "client_id": BC_SANDBOX_CLIENT_ID,
            "tenant_id": BC_SANDBOX_TENANT_ID,
            "environment": BC_SANDBOX_ENVIRONMENT,
            "company_name": BC_SANDBOX_COMPANY_NAME or "(not set)",
            "has_secret": bool(BC_SANDBOX_CLIENT_SECRET),
        },
        "api_base": BC_API_BASE,
        "available_operations": [
            "get_vendor",
            "search_vendors_by_name",
            "validate_vendor_exists",
            "get_customer",
            "get_purchase_order",
            "get_purchase_invoice",
            "get_sales_invoice",
            "validate_invoice_exists",
            "validate_ap_invoice_in_bc",
            "validate_sales_invoice_in_bc",
            "validate_purchase_order_in_bc"
        ],
        "blocked_operations": [
            "create_vendor",
            "update_vendor",
            "delete_vendor",
            "create_purchase_invoice",
            "post_purchase_invoice",
            "update_purchase_invoice",
            "create_sales_invoice",
            "post_sales_invoice"
        ]
    }
