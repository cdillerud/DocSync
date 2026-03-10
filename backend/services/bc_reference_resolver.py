"""
GPI Document Hub - BC Reference Resolver Service

This service resolves reference numbers (PO, Order, Shipment, etc.) against 
multiple BC tables to find matches.

Resolution Order:
1. Purchase Orders
2. Posted Purchase Invoices
3. Sales Orders
4. Posted Sales Invoices
5. Posted Sales Shipments (optional)

Returns:
- reference_type: The type of BC record found
- bc_record_id: BC record ID
- bc_document_no: BC document number
- status: found | not_found | error
"""

import os
import logging
import httpx
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List
from enum import Enum

logger = logging.getLogger(__name__)


class ReferenceType(str, Enum):
    """BC reference types that can be resolved."""
    PURCHASE_ORDER = "purchase_order"
    POSTED_PURCHASE_INVOICE = "posted_purchase_invoice"
    SALES_ORDER = "sales_order"
    POSTED_SALES_INVOICE = "posted_sales_invoice"
    POSTED_SALES_SHIPMENT = "posted_sales_shipment"
    NOT_FOUND = "not_found"


class ReferenceResolutionStatus(str, Enum):
    """Status of reference resolution."""
    FOUND = "found"
    NOT_FOUND = "not_found"
    ERROR = "error"


class ReferenceResolutionResult:
    """Result of reference resolution."""
    
    def __init__(
        self,
        reference_number: str,
        status: str = ReferenceResolutionStatus.NOT_FOUND.value,
        reference_type: str = None,
        bc_record_id: str = None,
        bc_document_no: str = None,
        bc_record_info: Dict = None,
        tables_checked: List[str] = None,
        error: str = None
    ):
        self.reference_number = reference_number
        self.status = status
        self.reference_type = reference_type
        self.bc_record_id = bc_record_id
        self.bc_document_no = bc_document_no
        self.bc_record_info = bc_record_info or {}
        self.tables_checked = tables_checked or []
        self.error = error
        self.resolved_at = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "reference_number": self.reference_number,
            "status": self.status,
            "reference_type": self.reference_type,
            "bc_record_id": self.bc_record_id,
            "bc_document_no": self.bc_document_no,
            "bc_record_info": self.bc_record_info,
            "tables_checked": self.tables_checked,
            "error": self.error,
            "resolved_at": self.resolved_at
        }


class BCReferenceResolver:
    """
    BC Reference Resolver - resolves reference numbers against BC tables.
    
    Uses Production BC for read-only lookups.
    """
    
    def __init__(self):
        # BC Production credentials for READ operations
        self.tenant_id = os.environ.get("BC_PROD_TENANT_ID") or os.environ.get("BC_TENANT_ID", "")
        self.client_id = os.environ.get("BC_PROD_CLIENT_ID") or os.environ.get("BC_CLIENT_ID", "")
        self.client_secret = os.environ.get("BC_PROD_CLIENT_SECRET") or os.environ.get("BC_CLIENT_SECRET", "")
        self.environment = os.environ.get("BC_PROD_ENVIRONMENT") or os.environ.get("BC_ENVIRONMENT", "Production")
        
        self._token = None
        self._token_expires = None
        self._company_id = None
        
        self.bc_api_base = "https://api.businesscentral.dynamics.com/v2.0"
    
    async def _get_token(self) -> Optional[str]:
        """Get BC access token."""
        if not self.client_id or not self.client_secret:
            logger.warning("[BC Reference Resolver] No BC credentials configured")
            return None
        
        # Check if token is still valid
        if self._token and self._token_expires and datetime.now(timezone.utc) < self._token_expires:
            return self._token
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.post(
                    f"https://login.microsoftonline.com/{self.tenant_id}/oauth2/v2.0/token",
                    data={
                        "grant_type": "client_credentials",
                        "client_id": self.client_id,
                        "client_secret": self.client_secret,
                        "scope": "https://api.businesscentral.dynamics.com/.default"
                    }
                )
                
                if resp.status_code == 200:
                    data = resp.json()
                    self._token = data["access_token"]
                    # Token expires in ~1 hour, refresh at 50 minutes
                    from datetime import timedelta
                    self._token_expires = datetime.now(timezone.utc) + timedelta(minutes=50)
                    return self._token
                else:
                    logger.error("[BC Reference Resolver] Token error: %d", resp.status_code)
                    return None
        except Exception as e:
            logger.error("[BC Reference Resolver] Token error: %s", str(e))
            return None
    
    async def _get_company_id(self, token: str) -> Optional[str]:
        """Get BC company ID."""
        if self._company_id:
            return self._company_id
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                resp = await client.get(
                    f"{self.bc_api_base}/{self.tenant_id}/{self.environment}/api/v2.0/companies",
                    headers={"Authorization": f"Bearer {token}"}
                )
                
                if resp.status_code == 200:
                    companies = resp.json().get("value", [])
                    if companies:
                        self._company_id = companies[0]["id"]
                        return self._company_id
        except Exception as e:
            logger.error("[BC Reference Resolver] Company lookup error: %s", str(e))
        
        return None
    
    async def resolve_reference(
        self,
        reference_number: str,
        check_tables: List[str] = None
    ) -> ReferenceResolutionResult:
        """
        Resolve a reference number against BC tables.
        
        Args:
            reference_number: The reference number to look up
            check_tables: Optional list of tables to check (defaults to all)
            
        Returns:
            ReferenceResolutionResult with match details
        """
        if not reference_number:
            return ReferenceResolutionResult(
                reference_number="",
                status=ReferenceResolutionStatus.ERROR.value,
                error="No reference number provided"
            )
        
        ref_clean = str(reference_number).strip()
        tables_checked = []
        
        # Default order of tables to check
        if check_tables is None:
            check_tables = [
                "purchaseOrders",
                "purchaseInvoices",  # Posted purchase invoices
                "salesOrders",
                "salesInvoices",     # Posted sales invoices
                "salesShipments"     # Posted sales shipments
            ]
        
        token = await self._get_token()
        if not token:
            return ReferenceResolutionResult(
                reference_number=ref_clean,
                status=ReferenceResolutionStatus.ERROR.value,
                error="Could not obtain BC token"
            )
        
        company_id = await self._get_company_id(token)
        if not company_id:
            return ReferenceResolutionResult(
                reference_number=ref_clean,
                status=ReferenceResolutionStatus.ERROR.value,
                error="Could not get BC company ID"
            )
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                
                # 1. Check Purchase Orders
                if "purchaseOrders" in check_tables:
                    tables_checked.append("purchaseOrders")
                    result = await self._check_table(
                        client, token, company_id, 
                        "purchaseOrders", "number", ref_clean,
                        ReferenceType.PURCHASE_ORDER.value
                    )
                    if result:
                        result.tables_checked = tables_checked
                        return result
                
                # 2. Check Posted Purchase Invoices
                if "purchaseInvoices" in check_tables:
                    tables_checked.append("purchaseInvoices")
                    # Try vendorInvoiceNumber first (external invoice number)
                    result = await self._check_table(
                        client, token, company_id,
                        "purchaseInvoices", "vendorInvoiceNumber", ref_clean,
                        ReferenceType.POSTED_PURCHASE_INVOICE.value
                    )
                    if result:
                        result.tables_checked = tables_checked
                        return result
                    
                    # Also try BC's internal number
                    result = await self._check_table(
                        client, token, company_id,
                        "purchaseInvoices", "number", ref_clean,
                        ReferenceType.POSTED_PURCHASE_INVOICE.value
                    )
                    if result:
                        result.tables_checked = tables_checked
                        return result
                
                # 3. Check Sales Orders
                if "salesOrders" in check_tables:
                    tables_checked.append("salesOrders")
                    result = await self._check_table(
                        client, token, company_id,
                        "salesOrders", "number", ref_clean,
                        ReferenceType.SALES_ORDER.value
                    )
                    if result:
                        result.tables_checked = tables_checked
                        return result
                
                # 4. Check Posted Sales Invoices
                if "salesInvoices" in check_tables:
                    tables_checked.append("salesInvoices")
                    result = await self._check_table(
                        client, token, company_id,
                        "salesInvoices", "number", ref_clean,
                        ReferenceType.POSTED_SALES_INVOICE.value
                    )
                    if result:
                        result.tables_checked = tables_checked
                        return result
                
                # 5. Check Posted Sales Shipments
                if "salesShipments" in check_tables:
                    tables_checked.append("salesShipments")
                    result = await self._check_table(
                        client, token, company_id,
                        "salesShipments", "number", ref_clean,
                        ReferenceType.POSTED_SALES_SHIPMENT.value
                    )
                    if result:
                        result.tables_checked = tables_checked
                        return result
            
            # Not found in any table
            logger.info(
                "[BC Reference Resolver] Reference '%s' not found in: %s",
                ref_clean, ", ".join(tables_checked)
            )
            
            return ReferenceResolutionResult(
                reference_number=ref_clean,
                status=ReferenceResolutionStatus.NOT_FOUND.value,
                reference_type=ReferenceType.NOT_FOUND.value,
                tables_checked=tables_checked
            )
            
        except Exception as e:
            logger.error("[BC Reference Resolver] Error resolving '%s': %s", ref_clean, str(e))
            return ReferenceResolutionResult(
                reference_number=ref_clean,
                status=ReferenceResolutionStatus.ERROR.value,
                tables_checked=tables_checked,
                error=str(e)
            )
    
    async def _check_table(
        self,
        client: httpx.AsyncClient,
        token: str,
        company_id: str,
        table: str,
        field: str,
        value: str,
        ref_type: str
    ) -> Optional[ReferenceResolutionResult]:
        """
        Check a single BC table for a matching reference.
        
        Returns ReferenceResolutionResult if found, None if not found.
        """
        try:
            url = f"{self.bc_api_base}/{self.tenant_id}/{self.environment}/api/v2.0/companies({company_id})/{table}"
            
            resp = await client.get(
                url,
                headers={"Authorization": f"Bearer {token}"},
                params={"$filter": f"{field} eq '{value}'"}
            )
            
            if resp.status_code == 200:
                records = resp.json().get("value", [])
                if records:
                    record = records[0]
                    
                    logger.info(
                        "[BC Reference Resolver] Found '%s' in %s as %s",
                        value, table, ref_type
                    )
                    
                    return ReferenceResolutionResult(
                        reference_number=value,
                        status=ReferenceResolutionStatus.FOUND.value,
                        reference_type=ref_type,
                        bc_record_id=record.get("id"),
                        bc_document_no=record.get("number"),
                        bc_record_info=self._extract_record_info(record, table)
                    )
            elif resp.status_code != 200:
                logger.warning(
                    "[BC Reference Resolver] Error checking %s: HTTP %d",
                    table, resp.status_code
                )
        except Exception as e:
            logger.warning("[BC Reference Resolver] Error checking %s: %s", table, str(e))
        
        return None
    
    def _extract_record_info(self, record: Dict, table: str) -> Dict[str, Any]:
        """Extract relevant info from a BC record based on table type."""
        info = {
            "id": record.get("id"),
            "number": record.get("number"),
            "table": table
        }
        
        if table == "purchaseOrders":
            info.update({
                "vendor_name": record.get("vendorName"),
                "vendor_number": record.get("vendorNumber"),
                "order_date": record.get("orderDate"),
                "status": record.get("status")
            })
        elif table == "purchaseInvoices":
            info.update({
                "vendor_name": record.get("vendorName"),
                "vendor_number": record.get("vendorNumber"),
                "vendor_invoice_number": record.get("vendorInvoiceNumber"),
                "posting_date": record.get("postingDate"),
                "total_amount": record.get("totalAmountIncludingTax")
            })
        elif table == "salesOrders":
            info.update({
                "customer_name": record.get("customerName"),
                "customer_number": record.get("customerNumber"),
                "order_date": record.get("orderDate"),
                "status": record.get("status"),
                "total_amount": record.get("totalAmountIncludingTax")
            })
        elif table == "salesInvoices":
            info.update({
                "customer_name": record.get("customerName"),
                "customer_number": record.get("customerNumber"),
                "posting_date": record.get("postingDate"),
                "total_amount": record.get("totalAmountIncludingTax")
            })
        elif table == "salesShipments":
            info.update({
                "customer_name": record.get("customerName"),
                "customer_number": record.get("customerNumber"),
                "shipment_date": record.get("shipmentDate"),
                "order_number": record.get("orderNumber")
            })
        
        return info


# Global instance
_reference_resolver: Optional[BCReferenceResolver] = None


def get_reference_resolver() -> BCReferenceResolver:
    """Get or create the global reference resolver instance."""
    global _reference_resolver
    if _reference_resolver is None:
        _reference_resolver = BCReferenceResolver()
    return _reference_resolver
