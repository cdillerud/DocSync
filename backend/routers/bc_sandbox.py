"""GPI Document Hub - BC Sandbox Router (Read-Only)

Extracted from server.py. All BC Sandbox API endpoints.
READ-ONLY: No writes to BC Production or Sandbox.
"""

from fastapi import APIRouter, HTTPException, Query, Body, BackgroundTasks
from typing import Dict, Optional
from deps import get_db

router = APIRouter(tags=["BC Sandbox"])

# ==================== BC SANDBOX API (READ-ONLY) ====================

from services.bc_sandbox_service import (
    get_vendor, search_vendors_by_name, validate_vendor_exists,
    get_customer, get_purchase_order, get_purchase_invoice, get_sales_invoice,
    validate_invoice_exists, validate_ap_invoice_in_bc, validate_sales_invoice_in_bc,
    validate_purchase_order_in_bc, get_bc_sandbox_status,
    PilotModeWriteBlockedError, BCSandboxError, BCLookupResult
)
from workflows.core.engine import BCValidationHistoryEntry


@router.get("/bc-sandbox/status")
async def bc_sandbox_status():
    """Get BC Sandbox service status and configuration."""
    return get_bc_sandbox_status()


@router.get("/bc-sandbox/vendors/{vendor_number}")
async def bc_sandbox_get_vendor(vendor_number: str):
    """
    db = get_db()
    Get vendor details by vendor number.
    READ-ONLY operation.
    """
    result = await get_vendor(vendor_number)
    return result.to_dict()


@router.get("/bc-sandbox/vendors/search/{name_fragment}")
async def bc_sandbox_search_vendors(name_fragment: str, limit: int = Query(20, le=100)):
    """
    Search vendors by name fragment (case-insensitive).
    READ-ONLY operation.
    """
    result = await search_vendors_by_name(name_fragment, limit)
    return result.to_dict()


@router.get("/bc-sandbox/customers/{customer_number}")
async def bc_sandbox_get_customer(customer_number: str):
    """
    Get customer details by customer number.
    READ-ONLY operation.
    """
    db = get_db()
    result = await get_customer(customer_number)
    return result.to_dict()


@router.get("/bc-sandbox/purchase-orders/{po_number}")
async def bc_sandbox_get_purchase_order(po_number: str):
    """
    Get purchase order details by PO number.
    READ-ONLY operation.
    """
    db = get_db()
    result = await get_purchase_order(po_number)
    return result.to_dict()


@router.get("/bc-sandbox/purchase-invoices/{invoice_number}")
async def bc_sandbox_get_purchase_invoice(invoice_number: str):
    """
    Get purchase invoice details by invoice number.
    READ-ONLY operation.
    """
    db = get_db()
    result = await get_purchase_invoice(invoice_number)
    return result.to_dict()


@router.get("/bc-sandbox/sales-invoices/{invoice_number}")
async def bc_sandbox_get_sales_invoice(invoice_number: str):
    """
    Get sales invoice details by invoice number.
    READ-ONLY operation.
    """
    db = get_db()
    result = await get_sales_invoice(invoice_number)
    return result.to_dict()


@router.post("/bc-sandbox/validate/vendor")
async def bc_sandbox_validate_vendor(vendor_number: str = Query(...)):
    """
    Validate that a vendor exists in BC.
    READ-ONLY operation.
    """
    exists, result = await validate_vendor_exists(vendor_number)
    return {
        "exists": exists,
        "lookup_result": result.to_dict()
    }


@router.post("/bc-sandbox/validate/invoice")
async def bc_sandbox_validate_invoice(
    invoice_number: str = Query(...),
    invoice_type: str = Query("purchase", regex="^(purchase|sales)$")
):
    """
    Validate that an invoice exists in BC.
    READ-ONLY operation.
    """
    exists, result = await validate_invoice_exists(invoice_number, invoice_type)
    return {
        "exists": exists,
        "invoice_type": invoice_type,
        "lookup_result": result.to_dict()
    }


@router.post("/bc-sandbox/validate/ap-invoice")
async def bc_sandbox_validate_ap_invoice(
    vendor_number: str = Query(...),
    invoice_number: Optional[str] = Query(None),
    po_number: Optional[str] = Query(None)
):
    """
    Full AP invoice validation against BC (observation mode).
    Validates vendor existence, PO reference, etc.
    READ-ONLY operation - results logged but don't block workflow.
    """
    validation_result = await validate_ap_invoice_in_bc(
        vendor_number=vendor_number,
        invoice_number=invoice_number,
        po_number=po_number
    )
    return validation_result


@router.post("/bc-sandbox/validate/sales-invoice")
async def bc_sandbox_validate_sales_invoice(
    customer_number: str = Query(...),
    invoice_number: Optional[str] = Query(None)
):
    """
    Full sales invoice validation against BC (observation mode).
    READ-ONLY operation.
    """
    validation_result = await validate_sales_invoice_in_bc(
        customer_number=customer_number,
        invoice_number=invoice_number
    )
    return validation_result


@router.post("/bc-sandbox/validate/purchase-order")
async def bc_sandbox_validate_purchase_order(po_number: str = Query(...)):
    """
    Purchase order validation against BC (observation mode).
    READ-ONLY operation.
    """
    validation_result = await validate_purchase_order_in_bc(po_number)
    return validation_result


@router.post("/bc/sales-orders/create")
async def create_bc_sales_order(
    customer_number: str = Query(..., description="BC Customer Number (e.g., 'NEW')"),
    external_doc_number: str = Query(None, description="Customer PO number"),
    order_date: str = Query(None, description="Order date (YYYY-MM-DD)"),
    delivery_date: str = Query(None, description="Requested delivery date (YYYY-MM-DD)")
):
    """
    Create a Sales Order in Business Central.
    
    Test endpoint for creating sales orders from customer POs.
    """
    from services.business_central_service import get_bc_service
    
    bc_service = get_bc_service()
    
    order_data = {
        "customerNumber": customer_number,
        "externalDocumentNumber": external_doc_number,
        "orderDate": order_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "requestedDeliveryDate": delivery_date,
        "lines": []  # Empty lines for now - just test header creation
    }
    
    result = await bc_service.create_sales_order(order_data)
    return result


@router.post("/bc-sandbox/document/{doc_id}/validate")
async def bc_sandbox_validate_document(doc_id: str, background_tasks: BackgroundTasks):
    """
    Validate a document against BC and add validation results to workflow history.
    This is the main integration point for workflow validation.
    
    READ-ONLY operation in observation mode.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    doc_type = doc.get("doc_type", "OTHER")
    validation_result = None
    history_entry = None
    
    # Run appropriate validation based on doc_type
    if doc_type == "AP_INVOICE":
        vendor_number = doc.get("vendor_canonical") or doc.get("vendor_raw") or doc.get("extracted_data", {}).get("vendor_number")
        invoice_number = doc.get("invoice_number") or doc.get("extracted_data", {}).get("invoice_number")
        po_number = doc.get("po_number") or doc.get("extracted_data", {}).get("po_number")
        
        if vendor_number:
            validation_result = await validate_ap_invoice_in_bc(
                vendor_number=vendor_number,
                invoice_number=invoice_number,
                po_number=po_number
            )
            history_entry = BCValidationHistoryEntry.create_bc_validation_entry(
                validation_type="ap_invoice",
                validation_result=validation_result
            )
        else:
            validation_result = {"error": "No vendor number available for validation", "observation_only": True}
            
    elif doc_type == "SALES_INVOICE":
        customer_number = doc.get("customer_number") or doc.get("extracted_data", {}).get("customer_number")
        invoice_number = doc.get("invoice_number") or doc.get("extracted_data", {}).get("invoice_number")
        
        if customer_number:
            validation_result = await validate_sales_invoice_in_bc(
                customer_number=customer_number,
                invoice_number=invoice_number
            )
            history_entry = BCValidationHistoryEntry.create_bc_validation_entry(
                validation_type="sales_invoice",
                validation_result=validation_result
            )
        else:
            validation_result = {"error": "No customer number available for validation", "observation_only": True}
            
    elif doc_type == "PURCHASE_ORDER":
        po_number = doc.get("po_number") or doc.get("extracted_data", {}).get("po_number")
        
        if po_number:
            validation_result = await validate_purchase_order_in_bc(po_number)
            history_entry = BCValidationHistoryEntry.create_bc_validation_entry(
                validation_type="purchase_order",
                validation_result=validation_result
            )
        else:
            validation_result = {"error": "No PO number available for validation", "observation_only": True}
    else:
        validation_result = {"info": f"No BC validation defined for doc_type: {doc_type}", "observation_only": True}
    
    # Add history entry to document (if we have one)
    if history_entry:
        await db.hub_documents.update_one(
            {"id": doc_id},
            {
                "$push": {"workflow_history": history_entry},
                "$set": {
                    "bc_validation_result": validation_result,
                    "bc_validation_timestamp": datetime.now(timezone.utc).isoformat()
                }
            }
        )
    
    return {
        "document_id": doc_id,
        "doc_type": doc_type,
        "validation_result": validation_result,
        "history_entry_added": history_entry is not None,
        "observation_only": True
    }


# ==================== BC SIMULATION API (Phase 2 Shadow Pilot) ====================
