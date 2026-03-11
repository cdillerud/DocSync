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

Uses the same BC credentials as sandbox but targets PRODUCTION environment for reads.
"""

import os
import logging
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List
from enum import Enum
from dotenv import load_dotenv

load_dotenv()

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


# =============================================================================
# CONFIGURATION — sourced from centralized bc_config (always reads Production)
# =============================================================================

from services.bc_config import (
    BC_READ_TENANT_ID as BC_TENANT_ID,
    BC_READ_CLIENT_ID as BC_CLIENT_ID,
    BC_READ_CLIENT_SECRET as BC_CLIENT_SECRET,
    BC_READ_ENVIRONMENT as BC_PROD_ENVIRONMENT,
    BC_API_BASE,
)

logger.info(
    "[BC Reference Resolver] Config: tenant=%s, env=%s (via bc_config)",
    BC_TENANT_ID[:8] + "..." if BC_TENANT_ID else "NOT SET",
    BC_PROD_ENVIRONMENT
)


class BCReferenceResolver:
    """
    BC Reference Resolver - resolves reference numbers against BC Production tables.
    
    Uses same credentials as sandbox but targets Production environment.
    Checks local cache first, falls back to direct BC API.
    """
    
    def __init__(self):
        self.tenant_id = BC_TENANT_ID
        self.client_id = BC_CLIENT_ID
        self.client_secret = BC_CLIENT_SECRET
        self.environment = BC_PROD_ENVIRONMENT
        
        self._token = None
        self._token_expires = None
        self._company_id = None
        self._cache_service = None
    
    def set_cache_service(self, cache_service):
        """Inject the cache service for cache-first resolution."""
        self._cache_service = cache_service
        logger.info("[BC Reference Resolver] Cache service attached")
    
    async def _get_token(self) -> Optional[str]:
        """Get BC access token."""
        if not self.client_id or not self.client_secret or not self.tenant_id:
            logger.error(
                "[BC Reference Resolver] Missing credentials: tenant=%s, client=%s, secret=%s",
                bool(self.tenant_id), bool(self.client_id), bool(self.client_secret)
            )
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
                    self._token_expires = datetime.now(timezone.utc) + timedelta(minutes=50)
                    logger.info("[BC Reference Resolver] Token obtained successfully")
                    return self._token
                else:
                    logger.error(
                        "[BC Reference Resolver] Token error: %d - %s",
                        resp.status_code, resp.text[:200]
                    )
                    return None
        except Exception as e:
            logger.error("[BC Reference Resolver] Token error: %s", str(e))
            return None
    
    async def _get_company_id(self, token: str) -> Optional[str]:
        """Get BC company ID for Gamer Packaging."""
        if self._company_id:
            return self._company_id
        
        try:
            async with httpx.AsyncClient(timeout=30.0) as client:
                url = f"{BC_API_BASE}/{self.tenant_id}/{self.environment}/api/v2.0/companies"
                resp = await client.get(
                    url,
                    headers={"Authorization": f"Bearer {token}"}
                )
                
                if resp.status_code == 200:
                    companies = resp.json().get("value", [])
                    logger.info("[BC Reference Resolver] Found %d companies", len(companies))
                    
                    # Look for Gamer Packaging
                    for company in companies:
                        if "gamer" in company.get("name", "").lower():
                            self._company_id = company["id"]
                            logger.info(
                                "[BC Reference Resolver] Using company: %s (%s)",
                                company.get("name"), self._company_id
                            )
                            return self._company_id
                    
                    # Fall back to first company
                    if companies:
                        self._company_id = companies[0]["id"]
                        logger.info(
                            "[BC Reference Resolver] Using first company: %s (%s)",
                            companies[0].get("name"), self._company_id
                        )
                        return self._company_id
                else:
                    logger.error(
                        "[BC Reference Resolver] Company lookup error: %d - %s",
                        resp.status_code, resp.text[:200]
                    )
        except Exception as e:
            logger.error("[BC Reference Resolver] Company lookup error: %s", str(e))
        
        return None
    
    async def resolve_reference(
        self,
        reference_number: str,
        check_tables: List[str] = None
    ) -> ReferenceResolutionResult:
        """
        Resolve a reference number against BC Production tables.
        
        Flow:
        1. Check local cache first (fast, <50ms)
        2. If cache miss, query BC API directly (slower)
        """
        if not reference_number:
            return ReferenceResolutionResult(
                reference_number="",
                status=ReferenceResolutionStatus.ERROR.value,
                error="No reference number provided"
            )
        
        ref_clean = str(reference_number).strip()
        
        # Default order of tables to check
        if check_tables is None:
            check_tables = [
                "purchaseOrders",
                "purchaseInvoices",
                "salesOrders",
                "salesInvoices",
                "salesShipments"
            ]
        
        # --- CACHE-FIRST: Try local cache ---
        if self._cache_service:
            try:
                cache_result = await self._resolve_from_cache(ref_clean, check_tables)
                if cache_result and cache_result.status == ReferenceResolutionStatus.FOUND.value:
                    logger.info(
                        "[BC Reference Resolver] CACHE HIT: '%s' → %s (%s)",
                        ref_clean, cache_result.bc_document_no, cache_result.reference_type
                    )
                    return cache_result
            except Exception as e:
                logger.warning("[BC Reference Resolver] Cache lookup error: %s", str(e))
        
        # --- FALLBACK: Direct BC API ---
        return await self._resolve_from_api(ref_clean, check_tables)
    
    async def _resolve_from_cache(
        self, ref_clean: str, check_tables: List[str]
    ) -> Optional[ReferenceResolutionResult]:
        """Try to resolve from local cache."""
        # Map table names to entity types for filtering
        table_to_entity = {
            "purchaseOrders": "purchase_order",
            "purchaseInvoices": "posted_purchase_invoice",
            "salesOrders": "sales_order",
            "salesInvoices": "posted_sales_invoice",
            "salesShipments": "posted_sales_shipment",
        }
        entity_types = [table_to_entity[t] for t in check_tables if t in table_to_entity]
        
        results = await self._cache_service.search_multi(ref_clean, entity_types=entity_types)
        if not results:
            return None
        
        # Take best match (search_multi returns sorted by relevance)
        best = results[0]
        entity_type = best.get("bc_entity_type", "unknown")
        table = {v: k for k, v in table_to_entity.items()}.get(entity_type, "unknown")
        
        return ReferenceResolutionResult(
            reference_number=ref_clean,
            status=ReferenceResolutionStatus.FOUND.value,
            reference_type=entity_type,
            bc_record_id=best.get("bc_record_id"),
            bc_document_no=best.get("bc_document_no"),
            bc_record_info={
                "id": best.get("bc_record_id"),
                "number": best.get("bc_document_no"),
                "table": table,
                "environment": self.environment,
                "vendor_name": best.get("bc_vendor_name"),
                "vendor_number": best.get("bc_vendor_no"),
                "customer_name": best.get("bc_customer_name"),
                "customer_number": best.get("bc_customer_no"),
                "posting_date": best.get("bc_posting_date"),
                "order_date": best.get("bc_posting_date"),
                "status": best.get("bc_status"),
                "total_amount": best.get("bc_amount"),
                "source": "cache",
            },
            tables_checked=["cache"]
        )
    
    async def _resolve_from_api(
        self, ref_clean: str, check_tables: List[str]
    ) -> ReferenceResolutionResult:
        """Resolve via direct BC API calls (original logic)."""
        tables_checked = []
        
        token = await self._get_token()
        if not token:
            return ReferenceResolutionResult(
                reference_number=ref_clean,
                status=ReferenceResolutionStatus.ERROR.value,
                error="Could not obtain BC token - check credentials"
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
                    # Try vendorInvoiceNumber first
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
        """Check a single BC table for a matching reference."""
        try:
            url = f"{BC_API_BASE}/{self.tenant_id}/{self.environment}/api/v2.0/companies({company_id})/{table}"
            
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
                        "[BC Reference Resolver] FOUND '%s' in %s (Production)",
                        value, table
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
        """Extract relevant info from a BC record."""
        info = {
            "id": record.get("id"),
            "number": record.get("number"),
            "table": table,
            "environment": self.environment
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


def set_reference_resolver(resolver: BCReferenceResolver = None) -> BCReferenceResolver:
    """Set custom reference resolver."""
    global _reference_resolver
    _reference_resolver = resolver or BCReferenceResolver()
    return _reference_resolver
