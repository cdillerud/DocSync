"""
GPI Document Hub - GPI Integration Router

Exposes the BC custom API endpoints for creating records via the
GPI Hub Integration AL extension. Acts as a bridge between the
GPI Hub frontend and the BC custom API.

Endpoints:
  GET  /gpi-integration/status          - Integration status
  GET  /gpi-integration/companies       - List BC companies
  POST /gpi-integration/sales-orders    - Create sales order
  POST /gpi-integration/sales-orders/preflight/{doc_id} - Preflight validation
  POST /gpi-integration/sales-orders/from-document/{doc_id} - Create from document
  POST /gpi-integration/purchase-invoices - Create purchase invoice
  POST /gpi-integration/customers       - Create customer
  POST /gpi-integration/vendors         - Create vendor
  GET  /gpi-integration/logs            - Integration audit logs
"""

import hashlib
import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field

from deps import get_db
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

# Document types eligible for BC Sales Order creation
SALES_ORDER_ELIGIBLE_TYPES = {"Sales_Order", "SalesOrder", "Order_Confirmation", "PurchaseOrder"}

# Document types eligible for BC Purchase Invoice creation
PURCHASE_INVOICE_ELIGIBLE_TYPES = {"AP_Invoice"}


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


def _build_idempotency_key(doc_id: str) -> str:
    """Build a stable, deterministic idempotency key from a document ID."""
    return f"SO_{hashlib.sha256(doc_id.encode()).hexdigest()[:24]}"


async def _resolve_customer_no(doc: dict) -> dict:
    """Try to resolve a BC customer number from document data.
    Returns {customer_no, customer_name, match_method, confidence}.
    """
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    vr = doc.get("validation_results") or {}

    customer_name = ef.get("customer") or nf.get("customer") or ""
    customer_no = ""
    match_method = "none"
    confidence = 0.0

    # 1. Check if a BC customer number was already resolved (e.g. validation)
    bc_record_info = vr.get("bc_record_info") or {}
    if bc_record_info.get("number"):
        customer_no = bc_record_info["number"]
        customer_name = customer_name or bc_record_info.get("displayName", "")
        match_method = vr.get("match_method", "validation")
        confidence = float(vr.get("match_score", 0.9))

    # 2. Try customer_candidates on the doc
    if not customer_no:
        for cand in (doc.get("customer_candidates") or []):
            if cand.get("number"):
                customer_no = cand["number"]
                customer_name = customer_name or cand.get("displayName", "")
                match_method = "customer_candidate"
                confidence = float(cand.get("score", 0.8))
                break

    # 3. Try bc_reference_cache lookup
    if not customer_no and customer_name:
        db = get_db()
        cached = await db.bc_reference_cache.find_one(
            {"displayName": {"$regex": customer_name[:30], "$options": "i"}, "entity_type": {"$in": ["customer", "Customer"]}},
            {"_id": 0, "number": 1, "displayName": 1, "entity_type": 1}
        )
        if cached:
            customer_no = cached.get("number", "")
            customer_name = customer_name or cached.get("displayName", "")
            match_method = "cache_lookup"
            confidence = 0.7

    return {
        "customer_no": customer_no,
        "customer_name": customer_name,
        "match_method": match_method,
        "confidence": confidence,
    }


@router.post("/sales-orders/preflight/{doc_id}")
async def sales_order_preflight(doc_id: str):
    """Preflight validation: check if a document is ready for BC Sales Order creation.
    Returns mapped values, missing fields, warnings, and overall readiness.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    warnings = []
    missing_fields = []
    errors = []

    # Check eligibility
    doc_type = doc.get("document_type", "")
    eligible = doc_type in SALES_ORDER_ELIGIBLE_TYPES
    if not eligible:
        errors.append(f"Document type '{doc_type}' is not eligible for Sales Order creation. Expected: {', '.join(SALES_ORDER_ELIGIBLE_TYPES)}")

    # Check for existing BC Sales Order
    existing_so = doc.get("bc_sales_order")
    if existing_so:
        return {
            "eligible": eligible,
            "ready": False,
            "already_created": True,
            "existing_sales_order": existing_so,
            "mapped_values": {},
            "missing_fields": [],
            "warnings": ["A BC Sales Order has already been created for this document."],
            "errors": [],
            "line_count": 0,
        }

    # Resolve customer
    customer_info = await _resolve_customer_no(doc)
    customer_no = customer_info["customer_no"]
    customer_name = customer_info["customer_name"]

    if not customer_no:
        missing_fields.append("customer_no")
        warnings.append("No BC customer number could be resolved. Manual customer mapping may be required.")

    # Extract key fields
    external_doc_no = ef.get("po_number") or nf.get("po_number") or ""
    order_date = ef.get("order_date") or nf.get("order_date") or ""
    line_items = ef.get("line_items") or nf.get("line_items") or []
    amount = ef.get("amount") or nf.get("amount")

    if not external_doc_no:
        missing_fields.append("external_doc_no")
        warnings.append("No PO number / external document number found.")

    if not order_date:
        missing_fields.append("order_date")
        warnings.append("No order date extracted. Current date will be used as fallback.")

    if not line_items:
        warnings.append("No line items extracted. A header-only sales order will be created.")

    # Integration status
    if not HAS_CREDENTIALS:
        errors.append("BC credentials are not configured. Cannot create orders until credentials are set.")

    # Compute BC company
    from services.gpi_integration_service import BC_ENVIRONMENT, BC_COMPANY_ID
    bc_company = BC_COMPANY_ID or "auto-detect"
    bc_environment = BC_ENVIRONMENT

    ready = eligible and bool(customer_no) and not errors

    idempotency_key = _build_idempotency_key(doc_id)

    return {
        "eligible": eligible,
        "ready": ready,
        "already_created": False,
        "existing_sales_order": None,
        "mapped_values": {
            "customer_no": customer_no,
            "customer_name": customer_name,
            "customer_match_method": customer_info["match_method"],
            "customer_match_confidence": customer_info["confidence"],
            "external_doc_no": external_doc_no,
            "order_date": order_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "order_date_source": "extracted" if order_date else "fallback_today",
            "total_amount": amount,
            "bc_company": bc_company,
            "bc_environment": bc_environment,
            "idempotency_key": idempotency_key,
        },
        "line_items": [
            {
                "description": li.get("description", ""),
                "quantity": li.get("quantity", 0),
                "unit_price": li.get("unit_price", 0),
                "total": li.get("total", 0),
            }
            for li in line_items
        ],
        "line_count": len(line_items),
        "missing_fields": missing_fields,
        "warnings": warnings,
        "errors": errors,
    }


@router.post("/sales-orders/from-document/{doc_id}")
async def create_sales_order_from_document(doc_id: str, customer_no_override: str = Query("", description="Override customer number")):
    """Create a BC Sales Order from a GPI Hub document.
    Performs preflight, creates the order, and writes back to the document graph.
    """
    if not HAS_CREDENTIALS:
        raise HTTPException(status_code=503, detail="BC credentials not configured")

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check for existing SO
    existing_so = doc.get("bc_sales_order")
    if existing_so:
        return {
            "success": True,
            "already_exists": True,
            "bc_record_no": existing_so.get("bc_record_no", ""),
            "bc_system_id": existing_so.get("bc_system_id", ""),
            "idempotency_key": existing_so.get("idempotency_key", ""),
            "status": "already_exists",
            "message": "A BC Sales Order was already created for this document.",
            "created_at": existing_so.get("created_at", ""),
        }

    # Check eligibility
    doc_type = doc.get("document_type", "")
    if doc_type not in SALES_ORDER_ELIGIBLE_TYPES:
        raise HTTPException(status_code=422, detail=f"Document type '{doc_type}' is not eligible for Sales Order creation")

    # Resolve fields
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}

    customer_info = await _resolve_customer_no(doc)
    customer_no = customer_no_override or customer_info["customer_no"]
    if not customer_no:
        raise HTTPException(status_code=422, detail={
            "error": "missing_customer",
            "message": "Cannot create Sales Order: no BC customer number resolved. Provide customer_no_override or map the customer first.",
        })

    external_doc_no = ef.get("po_number") or nf.get("po_number") or ""
    order_date = ef.get("order_date") or nf.get("order_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    idempotency_key = _build_idempotency_key(doc_id)
    transaction_id = f"TXN_{uuid.uuid4().hex[:12]}"

    try:
        result = await create_sales_order(
            customer_no=customer_no,
            external_doc_no=external_doc_no,
            order_date=order_date,
            source_doc_id=doc_id,
            idempotency_key=idempotency_key,
            transaction_id=transaction_id,
        )
    except Exception as e:
        logger.error("Failed to create sales order from doc %s: %s", doc_id, str(e))
        raise HTTPException(status_code=502, detail=f"BC API error: {str(e)}")

    # Graph writeback: store the BC Sales Order reference on the document
    now = datetime.now(timezone.utc).isoformat()
    bc_sales_order = {
        "bc_record_no": result.get("bc_record_no", ""),
        "bc_system_id": result.get("bc_system_id", ""),
        "idempotency_key": idempotency_key,
        "transaction_id": transaction_id,
        "status": result.get("status", ""),
        "success": result.get("success", False),
        "customer_no": customer_no,
        "customer_name": customer_info["customer_name"],
        "external_doc_no": external_doc_no,
        "order_date": order_date,
        "created_at": now,
        "created_by": "gpi_hub",
        "error_message": result.get("error_message", ""),
    }

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "bc_sales_order": bc_sales_order,
            "updated_utc": now,
        }}
    )

    # Also emit an event if event service is available
    try:
        from services.event_service import get_event_service
        es = get_event_service()
        if es:
            await es.emit_event(
                document_id=doc_id,
                event_type="bc.sales_order.created" if result.get("success") else "bc.sales_order.failed",
                source_service="gpi_integration",
                payload={
                    "bc_record_no": result.get("bc_record_no", ""),
                    "customer_no": customer_no,
                    "external_doc_no": external_doc_no,
                    "idempotency_key": idempotency_key,
                    "status": result.get("status", ""),
                },
                actor="system",
            )
    except Exception as evt_err:
        logger.warning("Failed to emit BC sales order event: %s", evt_err)

    return {
        "success": result.get("success", False),
        "already_exists": result.get("status") == "already_exists",
        "bc_record_no": result.get("bc_record_no", ""),
        "bc_system_id": result.get("bc_system_id", ""),
        "idempotency_key": idempotency_key,
        "transaction_id": transaction_id,
        "status": result.get("status", ""),
        "message": "Sales Order created successfully" if result.get("success") else result.get("error_message", "Creation failed"),
        "error_message": result.get("error_message", ""),
        "created_at": now,
    }


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


async def _resolve_vendor_no(doc: dict) -> dict:
    """Try to resolve a BC vendor number from document data.
    Returns {vendor_no, vendor_name, match_method, confidence}.
    """
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    vr = doc.get("validation_results") or {}

    vendor_name = ef.get("vendor") or nf.get("vendor") or ""
    vendor_no = doc.get("vendor_canonical") or ""
    match_method = "vendor_canonical" if vendor_no else "none"
    confidence = 0.85 if vendor_no else 0.0

    # 1. Check if BC vendor was resolved via validation_results
    bc_record_info = vr.get("bc_record_info") or {}
    if bc_record_info.get("number"):
        vendor_no = bc_record_info["number"]
        vendor_name = vendor_name or bc_record_info.get("displayName", "")
        match_method = "validation"
        confidence = 0.95

    # 2. Try vendor_candidates on the doc or in validation_results
    if not vendor_no:
        candidates = doc.get("vendor_candidates") or vr.get("vendor_candidates") or []
        for cand in candidates:
            cand_no = cand.get("number") or cand.get("vendor_id") or ""
            if cand_no and cand_no != "null":
                vendor_no = cand_no if len(cand_no) < 30 else ""
                vendor_name = vendor_name or cand.get("display_name") or cand.get("displayName", "")
                match_method = f"candidate_{cand.get('source', 'unknown')}"
                confidence = float(cand.get("score", 0.8))
                break

    # 3. Try bc_reference_cache lookup
    if not vendor_no and vendor_name:
        db = get_db()
        cached = await db.bc_reference_cache.find_one(
            {"displayName": {"$regex": vendor_name[:30], "$options": "i"}, "entity_type": {"$in": ["vendor", "Vendor"]}},
            {"_id": 0, "number": 1, "displayName": 1, "entity_type": 1}
        )
        if cached:
            vendor_no = cached.get("number", "")
            vendor_name = vendor_name or cached.get("displayName", "")
            match_method = "cache_lookup"
            confidence = 0.7

    return {
        "vendor_no": vendor_no,
        "vendor_name": vendor_name,
        "match_method": match_method,
        "confidence": confidence,
    }


def _build_pi_idempotency_key(doc_id: str) -> str:
    """Build a stable, deterministic idempotency key for purchase invoice from a document ID."""
    return f"PI_{hashlib.sha256(doc_id.encode()).hexdigest()[:24]}"


@router.post("/purchase-invoices/preflight/{doc_id}")
async def purchase_invoice_preflight(doc_id: str):
    """Preflight validation: check if a document is ready for BC Purchase Invoice creation."""
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    warnings = []
    missing_fields = []
    errors = []

    # Check eligibility
    doc_type = doc.get("document_type", "")
    eligible = doc_type in PURCHASE_INVOICE_ELIGIBLE_TYPES
    if not eligible:
        errors.append(f"Document type '{doc_type}' is not eligible for Purchase Invoice creation. Expected: {', '.join(PURCHASE_INVOICE_ELIGIBLE_TYPES)}")

    # Check for existing BC Purchase Invoice
    existing_pi = doc.get("bc_purchase_invoice")
    if existing_pi:
        return {
            "eligible": eligible,
            "ready": False,
            "already_created": True,
            "existing_purchase_invoice": existing_pi,
            "mapped_values": {},
            "missing_fields": [],
            "warnings": ["A BC Purchase Invoice has already been created for this document."],
            "errors": [],
            "line_count": 0,
        }

    # Resolve vendor
    vendor_info = await _resolve_vendor_no(doc)
    vendor_no = vendor_info["vendor_no"]
    vendor_name = vendor_info["vendor_name"]

    if not vendor_no:
        missing_fields.append("vendor_no")
        warnings.append("No BC vendor number could be resolved. Manual vendor mapping may be required.")

    # Extract key fields
    vendor_invoice_no = ef.get("invoice_number") or nf.get("invoice_number") or ""
    document_date = ef.get("invoice_date") or nf.get("invoice_date") or ""
    posting_date = document_date  # Default posting date = invoice date
    due_date = ef.get("due_date") or nf.get("due_date") or ""
    line_items = ef.get("line_items") or nf.get("line_items") or []
    amount = nf.get("amount") or ef.get("amount")
    po_number = ef.get("po_number") or nf.get("po_number") or ""

    if not vendor_invoice_no:
        missing_fields.append("vendor_invoice_no")
        warnings.append("No vendor invoice number found.")

    if not document_date:
        missing_fields.append("document_date")
        warnings.append("No invoice date extracted. Current date will be used as fallback.")

    if not line_items:
        warnings.append("No line items extracted. A header-only purchase invoice will be created.")

    if not HAS_CREDENTIALS:
        errors.append("BC credentials are not configured. Cannot create invoices until credentials are set.")

    from services.gpi_integration_service import BC_ENVIRONMENT, BC_COMPANY_ID
    bc_company = BC_COMPANY_ID or "auto-detect"
    bc_environment = BC_ENVIRONMENT

    ready = eligible and bool(vendor_no) and not errors

    idempotency_key = _build_pi_idempotency_key(doc_id)

    return {
        "eligible": eligible,
        "ready": ready,
        "already_created": False,
        "existing_purchase_invoice": None,
        "mapped_values": {
            "vendor_no": vendor_no,
            "vendor_name": vendor_name,
            "vendor_match_method": vendor_info["match_method"],
            "vendor_match_confidence": vendor_info["confidence"],
            "vendor_invoice_no": vendor_invoice_no,
            "document_date": document_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "document_date_source": "extracted" if document_date else "fallback_today",
            "posting_date": posting_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
            "posting_date_source": "extracted" if posting_date else "fallback_today",
            "due_date": due_date,
            "po_number": po_number,
            "total_amount": amount,
            "bc_company": bc_company,
            "bc_environment": bc_environment,
            "idempotency_key": idempotency_key,
        },
        "line_items": [
            {
                "description": li.get("description", ""),
                "quantity": li.get("quantity", 0),
                "unit_price": li.get("unit_price", 0),
                "total": li.get("total", 0),
            }
            for li in line_items
        ],
        "line_count": len(line_items),
        "missing_fields": missing_fields,
        "warnings": warnings,
        "errors": errors,
    }


@router.post("/purchase-invoices/from-document/{doc_id}")
async def create_purchase_invoice_from_document(doc_id: str, vendor_no_override: str = Query("", description="Override vendor number")):
    """Create a BC Purchase Invoice from a GPI Hub document.
    Performs preflight, creates the invoice, and writes back to the document graph.
    """
    if not HAS_CREDENTIALS:
        raise HTTPException(status_code=503, detail="BC credentials not configured")

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check for existing PI
    existing_pi = doc.get("bc_purchase_invoice")
    if existing_pi:
        return {
            "success": True,
            "already_exists": True,
            "bc_record_no": existing_pi.get("bc_record_no", ""),
            "bc_system_id": existing_pi.get("bc_system_id", ""),
            "idempotency_key": existing_pi.get("idempotency_key", ""),
            "status": "already_exists",
            "message": "A BC Purchase Invoice was already created for this document.",
            "created_at": existing_pi.get("created_at", ""),
        }

    # Check eligibility
    doc_type = doc.get("document_type", "")
    if doc_type not in PURCHASE_INVOICE_ELIGIBLE_TYPES:
        raise HTTPException(status_code=422, detail=f"Document type '{doc_type}' is not eligible for Purchase Invoice creation")

    # Resolve fields
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}

    vendor_info = await _resolve_vendor_no(doc)
    vendor_no = vendor_no_override or vendor_info["vendor_no"]
    if not vendor_no:
        raise HTTPException(status_code=422, detail={
            "error": "missing_vendor",
            "message": "Cannot create Purchase Invoice: no BC vendor number resolved. Provide vendor_no_override or map the vendor first.",
        })

    vendor_invoice_no = ef.get("invoice_number") or nf.get("invoice_number") or ""
    document_date = ef.get("invoice_date") or nf.get("invoice_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
    posting_date = document_date

    idempotency_key = _build_pi_idempotency_key(doc_id)
    transaction_id = f"TXN_{uuid.uuid4().hex[:12]}"

    try:
        result = await create_purchase_invoice(
            vendor_no=vendor_no,
            vendor_invoice_no=vendor_invoice_no,
            document_date=document_date,
            posting_date=posting_date,
            source_doc_id=doc_id,
            idempotency_key=idempotency_key,
            transaction_id=transaction_id,
        )
    except Exception as e:
        logger.error("Failed to create purchase invoice from doc %s: %s", doc_id, str(e))
        raise HTTPException(status_code=502, detail=f"BC API error: {str(e)}")

    # Graph writeback
    now = datetime.now(timezone.utc).isoformat()
    bc_purchase_invoice = {
        "bc_record_no": result.get("bc_record_no", ""),
        "bc_system_id": result.get("bc_system_id", ""),
        "idempotency_key": idempotency_key,
        "transaction_id": transaction_id,
        "status": result.get("status", ""),
        "success": result.get("success", False),
        "vendor_no": vendor_no,
        "vendor_name": vendor_info["vendor_name"],
        "vendor_invoice_no": vendor_invoice_no,
        "document_date": document_date,
        "posting_date": posting_date,
        "created_at": now,
        "created_by": "gpi_hub",
        "error_message": result.get("error_message", ""),
    }

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "bc_purchase_invoice": bc_purchase_invoice,
            "updated_utc": now,
        }}
    )

    # Emit event
    try:
        from services.event_service import get_event_service
        es = get_event_service()
        if es:
            await es.emit_event(
                document_id=doc_id,
                event_type="bc.purchase_invoice.created" if result.get("success") else "bc.purchase_invoice.failed",
                source_service="gpi_integration",
                payload={
                    "bc_record_no": result.get("bc_record_no", ""),
                    "vendor_no": vendor_no,
                    "vendor_invoice_no": vendor_invoice_no,
                    "idempotency_key": idempotency_key,
                    "status": result.get("status", ""),
                },
                actor="system",
            )
    except Exception as evt_err:
        logger.warning("Failed to emit BC purchase invoice event: %s", evt_err)

    return {
        "success": result.get("success", False),
        "already_exists": result.get("status") == "already_exists",
        "bc_record_no": result.get("bc_record_no", ""),
        "bc_system_id": result.get("bc_system_id", ""),
        "idempotency_key": idempotency_key,
        "transaction_id": transaction_id,
        "status": result.get("status", ""),
        "message": "Purchase Invoice created successfully" if result.get("success") else result.get("error_message", "Creation failed"),
        "error_message": result.get("error_message", ""),
        "created_at": now,
    }


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
