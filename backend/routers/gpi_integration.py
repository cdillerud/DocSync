"""
GPI Document Hub - GPI Integration Router

Exposes the BC custom API endpoints for creating records via the
GPI Hub Integration AL extension. Acts as a bridge between the
GPI Hub frontend and the BC custom API.

Endpoints:
  GET  /gpi-integration/status          - Integration status
  GET  /gpi-integration/companies       - List BC companies
  POST /gpi-integration/sales-orders    - Create sales order
  POST /gpi-integration/purchase-invoices - Create purchase invoice
  POST /gpi-integration/customers       - Create customer
  POST /gpi-integration/vendors         - Create vendor
  GET  /gpi-integration/logs            - Integration audit logs
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from services.gpi_integration_service import (
    list_companies,
    create_sales_order,
    create_purchase_invoice,
    create_customer,
    create_vendor,
    list_integration_logs,
    get_integration_status,
    HAS_CREDENTIALS,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gpi-integration", tags=["GPI Integration"])


# =========================================================================
# Request/Response Models
# =========================================================================

class CreateSalesOrderRequest(BaseModel):
    customer_no: str = Field(..., description="BC Customer Number")
    external_doc_no: str = Field("", description="External document number (e.g. customer PO)")
    order_date: str = Field("", description="Order date (YYYY-MM-DD)")
    source_doc_id: str = Field("", description="GPI Hub document ID")
    idempotency_key: str = Field("", description="Caller-supplied idempotency key")
    transaction_id: str = Field("", description="Caller-supplied transaction ID")


class CreatePurchaseInvoiceRequest(BaseModel):
    vendor_no: str = Field(..., description="BC Vendor Number")
    vendor_invoice_no: str = Field("", description="Vendor's invoice number")
    document_date: str = Field("", description="Document date (YYYY-MM-DD)")
    posting_date: str = Field("", description="Posting date (YYYY-MM-DD)")
    source_doc_id: str = Field("", description="GPI Hub document ID")
    idempotency_key: str = Field("", description="Caller-supplied idempotency key")
    transaction_id: str = Field("", description="Caller-supplied transaction ID")


class CreateCustomerRequest(BaseModel):
    name: str = Field(..., description="Customer name")
    address: str = Field("", description="Street address")
    city: str = Field("", description="City")
    state_code: str = Field("", description="State/province code")
    postal_code: str = Field("", description="Postal/ZIP code")
    country_code: str = Field("", description="Country/region code (e.g. US, CA)")
    source_doc_id: str = Field("", description="GPI Hub document ID")
    idempotency_key: str = Field("", description="Caller-supplied idempotency key")


class CreateVendorRequest(BaseModel):
    name: str = Field(..., description="Vendor name")
    address: str = Field("", description="Street address")
    city: str = Field("", description="City")
    state_code: str = Field("", description="State/province code")
    postal_code: str = Field("", description="Postal/ZIP code")
    country_code: str = Field("", description="Country/region code (e.g. US, CA)")
    source_doc_id: str = Field("", description="GPI Hub document ID")
    idempotency_key: str = Field("", description="Caller-supplied idempotency key")


# =========================================================================
# Endpoints
# =========================================================================

@router.get("/status")
async def gpi_integration_status():
    """Get GPI Integration API configuration status."""
    return get_integration_status()


@router.get("/companies")
async def gpi_list_companies():
    """List available BC companies via GPI custom API."""
    try:
        companies = await list_companies()
        return {"companies": companies}
    except Exception as e:
        logger.error("Failed to list companies: %s", str(e))
        raise HTTPException(status_code=502, detail=f"BC API error: {str(e)}")


@router.post("/sales-orders")
async def gpi_create_sales_order(req: CreateSalesOrderRequest):
    """Create a Sales Order in BC via GPI custom API."""
    if not HAS_CREDENTIALS:
        raise HTTPException(status_code=503, detail="BC credentials not configured")

    try:
        result = await create_sales_order(
            customer_no=req.customer_no,
            external_doc_no=req.external_doc_no,
            order_date=req.order_date,
            source_doc_id=req.source_doc_id,
            idempotency_key=req.idempotency_key,
            transaction_id=req.transaction_id,
        )
        if not result["success"] and result["status"] != "already_exists":
            raise HTTPException(status_code=422, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create sales order: %s", str(e))
        raise HTTPException(status_code=502, detail=f"BC API error: {str(e)}")


@router.post("/purchase-invoices")
async def gpi_create_purchase_invoice(req: CreatePurchaseInvoiceRequest):
    """Create a Purchase Invoice in BC via GPI custom API."""
    if not HAS_CREDENTIALS:
        raise HTTPException(status_code=503, detail="BC credentials not configured")

    try:
        result = await create_purchase_invoice(
            vendor_no=req.vendor_no,
            vendor_invoice_no=req.vendor_invoice_no,
            document_date=req.document_date,
            posting_date=req.posting_date,
            source_doc_id=req.source_doc_id,
            idempotency_key=req.idempotency_key,
            transaction_id=req.transaction_id,
        )
        if not result["success"] and result["status"] != "already_exists":
            raise HTTPException(status_code=422, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create purchase invoice: %s", str(e))
        raise HTTPException(status_code=502, detail=f"BC API error: {str(e)}")


@router.post("/customers")
async def gpi_create_customer(req: CreateCustomerRequest):
    """Create a Customer in BC via GPI custom API."""
    if not HAS_CREDENTIALS:
        raise HTTPException(status_code=503, detail="BC credentials not configured")

    try:
        result = await create_customer(
            name=req.name,
            address=req.address,
            city=req.city,
            state_code=req.state_code,
            postal_code=req.postal_code,
            country_code=req.country_code,
            source_doc_id=req.source_doc_id,
            idempotency_key=req.idempotency_key,
        )
        if not result["success"] and result["status"] != "already_exists":
            raise HTTPException(status_code=422, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create customer: %s", str(e))
        raise HTTPException(status_code=502, detail=f"BC API error: {str(e)}")


@router.post("/vendors")
async def gpi_create_vendor(req: CreateVendorRequest):
    """Create a Vendor in BC via GPI custom API."""
    if not HAS_CREDENTIALS:
        raise HTTPException(status_code=503, detail="BC credentials not configured")

    try:
        result = await create_vendor(
            name=req.name,
            address=req.address,
            city=req.city,
            state_code=req.state_code,
            postal_code=req.postal_code,
            country_code=req.country_code,
            source_doc_id=req.source_doc_id,
            idempotency_key=req.idempotency_key,
        )
        if not result["success"] and result["status"] != "already_exists":
            raise HTTPException(status_code=422, detail=result)
        return result
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Failed to create vendor: %s", str(e))
        raise HTTPException(status_code=502, detail=f"BC API error: {str(e)}")


@router.get("/logs")
async def gpi_integration_logs(
    record_type: str = Query("", description="Filter by record type"),
    status: str = Query("", description="Filter by status"),
    top: int = Query(50, description="Max results", le=200),
):
    """List integration audit logs from BC."""
    if not HAS_CREDENTIALS:
        raise HTTPException(status_code=503, detail="BC credentials not configured")

    try:
        logs = await list_integration_logs(
            record_type=record_type,
            status=status,
            top=top,
        )
        return {"logs": logs, "count": len(logs)}
    except Exception as e:
        logger.error("Failed to list integration logs: %s", str(e))
        raise HTTPException(status_code=502, detail=f"BC API error: {str(e)}")
