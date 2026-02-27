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

# BC Credentials - prefer BC_* then fallback to BC_SANDBOX_*
BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID') or os.environ.get('BC_SANDBOX_CLIENT_ID', '')
BC_CLIENT_SECRET = os.environ.get('BC_CLIENT_SECRET') or os.environ.get('BC_SANDBOX_CLIENT_SECRET', '')
BC_TENANT_ID = os.environ.get('TENANT_ID') or os.environ.get('BC_TENANT_ID') or os.environ.get('BC_SANDBOX_TENANT_ID', '')
BC_ENVIRONMENT = os.environ.get('BC_ENVIRONMENT') or os.environ.get('BC_SANDBOX_ENVIRONMENT', 'Sandbox')
BC_COMPANY_ID = os.environ.get('BC_COMPANY_ID', '')
BC_COMPANY_NAME = os.environ.get('BC_COMPANY_NAME') or os.environ.get('BC_SANDBOX_COMPANY_NAME', '')

# Mock mode control
BC_MOCK_MODE = os.environ.get('BC_MOCK_MODE', 'false').lower() == 'true'
DEMO_MODE = os.environ.get('DEMO_MODE', 'false').lower() == 'true'

# Feature flag for BC link writeback
BC_WRITEBACK_LINK_ENABLED = os.environ.get('BC_WRITEBACK_LINK_ENABLED', 'true').lower() == 'true'

# Auto-enable mock mode ONLY if explicitly set or credentials are missing
# Changed: DEMO_MODE=false now means use real BC
USE_MOCK = BC_MOCK_MODE or (not BC_CLIENT_ID) or (not BC_CLIENT_SECRET) or (not BC_TENANT_ID)

if USE_MOCK:
    logger.info("BusinessCentralService: MOCK MODE (BC_CLIENT_ID=%s, BC_CLIENT_SECRET=%s, BC_TENANT_ID=%s)", 
                bool(BC_CLIENT_ID), bool(BC_CLIENT_SECRET), bool(BC_TENANT_ID))

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
            use_mock: Override mock mode setting. If None, uses auto-detected mode.
        """
        self.use_mock = use_mock if use_mock is not None else USE_MOCK
        self._company_id = None
        
        if self.use_mock:
            logger.info("BusinessCentralService initialized in MOCK mode")
        else:
            logger.info("BusinessCentralService initialized in REAL mode (tenant=%s, env=%s)", 
                       BC_TENANT_ID[:8] + "..." if BC_TENANT_ID else "N/A", BC_ENVIRONMENT)
    
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
                            "mock": False
                        }
                
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
            line_result = None
            if invoice_data.get("lines") and len(invoice_data["lines"]) > 0:
                logger.info("Adding %d line items to invoice %s", len(invoice_data["lines"]), data.get("id"))
                line_result = await self._add_invoice_lines(data["id"], invoice_data["lines"], token, company_id)
            
            return {
                "success": True,
                "bcDocumentId": data.get("id"),
                "bcDocumentNumber": data.get("number"),
                "status": data.get("status", "Draft"),
                "message": "Purchase invoice created successfully",
                "mock": False,
                "createdAt": datetime.now(timezone.utc).isoformat(),
                "bcResponse": data,
                "linesAdded": line_result.get("added", 0) if line_result else 0,
                "linesTotal": line_result.get("total", 0) if line_result else 0,
                "lineErrors": line_result.get("errors", []) if line_result else []
            }
    
    async def _add_invoice_lines(self, invoice_id: str, lines: List[Dict], token: str, company_id: str):
        """
        Add line items to a purchase invoice using Item type.
        
        BC Purchase Invoice Lines API for Item type requires:
        - lineType: "Item"
        - lineObjectNumber: The Item code/number (e.g., "FREIGHT")
        - description: Line description (optional)
        - quantity: Quantity
        - unitCost: Cost per unit
        
        Uses BC_DEFAULT_ITEM_CODE (e.g., "FREIGHT") as the default item for all lines.
        BC will automatically resolve the itemId from the lineObjectNumber.
        """
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices({invoice_id})/purchaseInvoiceLines"
        
        added_count = 0
        errors = []
        
        # Get default Item code (BC will resolve the GUID from this number)
        default_item_code = os.environ.get("BC_DEFAULT_ITEM_CODE", "FREIGHT")
        logger.info("Using Item code '%s' for invoice lines (BC will resolve itemId)", default_item_code)
        
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            for idx, line in enumerate(lines):
                # Get values with fallbacks - support both AI extraction format and direct format
                description = line.get("description", "")
                quantity = float(line.get("quantity", 1) or 1)
                # AI extraction uses "unit_price", BC uses "unitCost"
                unit_price = float(line.get("unit_price") or line.get("unitCost") or 0)
                # AI extraction uses "total", also support "line_total"
                line_total = float(line.get("total") or line.get("line_total") or 0)
                
                # If we have a total but no unit price, calculate unit price
                if line_total > 0 and unit_price == 0 and quantity > 0:
                    unit_price = line_total / quantity
                
                # If we still have no unit price but have a total, use total as unit price (qty=1)
                if unit_price == 0 and line_total > 0:
                    unit_price = line_total
                    quantity = 1
                
                # Skip truly empty lines (no description AND no amount)
                if not description and unit_price == 0 and line_total == 0:
                    logger.debug("Skipping empty invoice line %d", idx)
                    continue
                
                # Build line payload using Item type
                # Use lineObjectNumber (item code) - BC will resolve itemId automatically
                line_payload = {
                    "lineType": "Item",
                    "lineObjectNumber": default_item_code,
                    "description": description[:100] if description else f"Line {idx + 1}",
                    "quantity": quantity,
                    "unitCost": unit_price,
                }
                
                logger.info("Adding invoice line %d: %s (Item=%s, qty=%s, unit=$%s)", 
                           idx + 1, description[:50], default_item_code, quantity, unit_price)
                
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
                    logger.info("Successfully added invoice line %d", idx + 1)
                else:
                    error_msg = resp.text[:300]
                    logger.warning("Failed to add invoice line %d: HTTP %d - %s", 
                                  idx + 1, resp.status_code, error_msg)
                    errors.append({
                        "line": idx + 1,
                        "description": description[:50],
                        "error": error_msg
                    })
        
        logger.info("Invoice line addition complete: %d/%d lines added", added_count, len(lines))
        return {"added": added_count, "total": len(lines), "errors": errors}
    
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
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/items"
        
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
                        logger.warning("Item '%s' not found in BC", item_code)
                        return None
                else:
                    logger.error("Failed to look up Item '%s': HTTP %d - %s", 
                                item_code, resp.status_code, resp.text[:200])
                    return None
        except Exception as e:
            logger.error("Error looking up Item '%s': %s", item_code, str(e))
            return None
    
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
            token = await get_bc_token()
            company_id = await self._get_company_id()
            
            # Use the GPI Document Links custom API endpoint
            api_base_url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/gpi/documents/v1.0/companies({company_id})/documentLinks"
            
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
            url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices({invoice_id})/purchaseInvoiceLines"
            
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
                    
        except Exception as e:
            logger.error("Exception writing SharePoint link to BC: %s", str(e))
            return {
                "success": False,
                "error": str(e)
            }


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
