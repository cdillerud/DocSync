"""
GPI Document Hub - Business Central Integration Service

This service provides methods for interacting with Business Central API
for vendor lookup, PO lookup, and posting purchase invoices.

Supports both mock mode (for development/testing) and real BC API calls.

Configuration via environment variables:
- BC_CLIENT_ID: App registration client ID
- BC_CLIENT_SECRET: App registration client secret  
- BC_TENANT_ID: Azure AD tenant ID
- BC_ENVIRONMENT: BC environment name (e.g., "Sandbox_11_3_2025")
- BC_COMPANY_ID: BC company GUID (optional, auto-detected if not set)
- BC_MOCK_MODE: Set to "true" to use mock responses
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
# CONFIGURATION
# =============================================================================

BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID') or os.environ.get('BC_SANDBOX_CLIENT_ID', '')
BC_CLIENT_SECRET = os.environ.get('BC_CLIENT_SECRET') or os.environ.get('BC_SANDBOX_CLIENT_SECRET', '')
BC_TENANT_ID = os.environ.get('BC_TENANT_ID') or os.environ.get('BC_SANDBOX_TENANT_ID', 'c7b2de14-71d9-4c49-a0b9-2bec103a6fdc')
BC_ENVIRONMENT = os.environ.get('BC_ENVIRONMENT') or os.environ.get('BC_SANDBOX_ENVIRONMENT', 'Sandbox')
BC_COMPANY_ID = os.environ.get('BC_COMPANY_ID', '')

# Mock mode for testing without real BC connection
BC_MOCK_MODE = os.environ.get('BC_MOCK_MODE', 'false').lower() == 'true'
DEMO_MODE = os.environ.get('DEMO_MODE', 'true').lower() == 'true'

BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"
BC_REQUEST_TIMEOUT = 30.0

# Token cache
_token_cache = {
    "access_token": None,
    "expires_at": 0
}


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

async def get_bc_token() -> str:
    """Get OAuth token for BC API calls. Uses caching to avoid repeated auth calls."""
    global _token_cache
    
    # Check cache
    if _token_cache["access_token"] and _token_cache["expires_at"] > datetime.now(timezone.utc).timestamp():
        return _token_cache["access_token"]
    
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
        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = datetime.now(timezone.utc).timestamp() + data.get("expires_in", 3600) - 60
        
        return _token_cache["access_token"]


async def get_bc_company_id() -> str:
    """Get the BC company ID. Uses configured value or auto-detects."""
    if BC_COMPANY_ID:
        return BC_COMPANY_ID
    
    token = await get_bc_token()
    url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies"
    
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
            use_mock: Override mock mode setting. If None, uses BC_MOCK_MODE env var.
        """
        self.use_mock = use_mock if use_mock is not None else (BC_MOCK_MODE or DEMO_MODE)
        self._company_id = None
    
    async def _get_company_id(self) -> str:
        """Get and cache the company ID."""
        if self._company_id:
            return self._company_id
        
        if self.use_mock:
            self._company_id = "mock-company-id"
        else:
            self._company_id = await get_bc_company_id()
        
        return self._company_id
    
    # =========================================================================
    # VENDOR METHODS
    # =========================================================================
    
    async def get_vendors(self, filter_text: Optional[str] = None, limit: int = 50) -> Dict[str, Any]:
        """
        Get vendors from BC, optionally filtered by name/number.
        
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
        
        # Real BC API call
        token = await get_bc_token()
        company_id = await self._get_company_id()
        
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors"
        params = {"$select": "id,number,displayName,email,phoneNumber", "$top": str(limit)}
        
        if filter_text:
            # Use OData filter for server-side filtering
            params["$filter"] = f"contains(displayName, '{filter_text}') or contains(number, '{filter_text}')"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            
            if resp.status_code != 200:
                logger.error("Failed to get vendors: %s", resp.text)
                raise Exception(f"Failed to get vendors: {resp.status_code}")
            
            data = resp.json()
            vendors = data.get("value", [])
            
            return {
                "vendors": vendors,
                "total": len(vendors),
                "mock": False
            }
    
    async def get_vendor_by_id(self, vendor_id: str) -> Optional[Dict[str, Any]]:
        """Get a specific vendor by ID."""
        if self.use_mock:
            for v in MOCK_VENDORS:
                if v["id"] == vendor_id or v["number"] == vendor_id:
                    return v
            return None
        
        token = await get_bc_token()
        company_id = await self._get_company_id()
        
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors({vendor_id})"
        
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
        
        # Real BC API call
        token = await get_bc_token()
        company_id = await self._get_company_id()
        
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseOrders"
        params = {
            "$select": "id,number,vendorNumber,vendorName,orderDate,status,totalAmountIncludingVat",
            "$filter": "status eq 'Open'",
            "$top": str(limit)
        }
        
        if vendor_id:
            params["$filter"] += f" and vendorNumber eq '{vendor_id}'"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
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
    
    # =========================================================================
    # PURCHASE INVOICE METHODS
    # =========================================================================
    
    async def create_purchase_invoice(self, invoice_data: Dict[str, Any]) -> Dict[str, Any]:
        """
        Create a purchase invoice in BC.
        
        Args:
            invoice_data: Invoice data including:
                - vendorId or vendorNumber: BC vendor reference
                - invoiceNumber: External document number
                - invoiceDate: Invoice date (YYYY-MM-DD)
                - dueDate: Due date (YYYY-MM-DD)
                - currencyCode: Currency (e.g., "USD")
                - lines: List of line items with description, quantity, unitCost
                
        Returns:
            Dict with created invoice details including bcDocumentId
        """
        if self.use_mock:
            # Generate mock response
            mock_bc_id = f"PI-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
            return {
                "success": True,
                "bcDocumentId": mock_bc_id,
                "bcDocumentNumber": mock_bc_id,
                "status": "Draft",
                "message": "Purchase invoice created (mock mode)",
                "mock": True,
                "createdAt": datetime.now(timezone.utc).isoformat()
            }
        
        # Real BC API call
        token = await get_bc_token()
        company_id = await self._get_company_id()
        
        # Build the invoice payload per BC API spec
        payload = {
            "vendorNumber": invoice_data.get("vendorNumber") or invoice_data.get("vendor_no"),
            "externalDocumentNumber": invoice_data.get("invoiceNumber") or invoice_data.get("invoice_number"),
            "invoiceDate": invoice_data.get("invoiceDate") or invoice_data.get("invoice_date"),
            "dueDate": invoice_data.get("dueDate") or invoice_data.get("due_date"),
            "currencyCode": invoice_data.get("currencyCode") or invoice_data.get("currency") or "USD",
        }
        
        # Remove None values
        payload = {k: v for k, v in payload.items() if v is not None}
        
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices"
        
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
            
            # Add line items if provided
            if invoice_data.get("lines"):
                await self._add_invoice_lines(data["id"], invoice_data["lines"], token, company_id)
            
            return {
                "success": True,
                "bcDocumentId": data.get("id"),
                "bcDocumentNumber": data.get("number"),
                "status": data.get("status", "Draft"),
                "message": "Purchase invoice created successfully",
                "mock": False,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "bcResponse": data
            }
    
    async def _add_invoice_lines(self, invoice_id: str, lines: List[Dict], token: str, company_id: str):
        """Add line items to a purchase invoice."""
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices({invoice_id})/purchaseInvoiceLines"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            for line in lines:
                line_payload = {
                    "description": line.get("description", ""),
                    "quantity": float(line.get("quantity", 1)),
                    "unitCost": float(line.get("unitCost") or line.get("unit_price", 0)),
                }
                
                resp = await client.post(
                    url,
                    headers={
                        "Authorization": f"Bearer {token}",
                        "Content-Type": "application/json"
                    },
                    json=line_payload
                )
                
                if resp.status_code not in (200, 201):
                    logger.warning("Failed to add invoice line: %s", resp.text[:200])
    
    async def get_purchase_invoice(self, invoice_id: str) -> Optional[Dict[str, Any]]:
        """Get a purchase invoice by ID."""
        if self.use_mock:
            return {
                "id": invoice_id,
                "number": f"PI-{invoice_id[:8]}",
                "status": "Draft",
                "mock": True
            }
        
        token = await get_bc_token()
        company_id = await self._get_company_id()
        
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices({invoice_id})"
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
            
            if resp.status_code == 404:
                return None
            if resp.status_code != 200:
                raise Exception(f"Failed to get purchase invoice: {resp.status_code}")
            
            return resp.json()


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
