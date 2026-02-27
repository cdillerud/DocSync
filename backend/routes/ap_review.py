"""
GPI Document Hub - AP Review Routes

API endpoints for AP Invoice review workflow:
- Vendor search
- PO search  
- Save AP review edits
- Post to Business Central
"""

import logging
from datetime import datetime, timezone
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

logger = logging.getLogger(__name__)

# Create router
ap_review_router = APIRouter(prefix="/api/ap-review", tags=["AP Review"])


# =============================================================================
# REQUEST/RESPONSE MODELS
# =============================================================================

class APReviewData(BaseModel):
    """Data for saving AP review edits."""
    vendor_id: Optional[str] = None
    vendor_name_resolved: Optional[str] = None
    invoice_number: Optional[str] = None
    invoice_date: Optional[str] = None
    due_date: Optional[str] = None
    currency: Optional[str] = "USD"
    total_amount: Optional[float] = None
    tax_amount: Optional[float] = None
    po_number: Optional[str] = None
    line_items: Optional[List[dict]] = None
    notes: Optional[str] = None


class PostToBCRequest(BaseModel):
    """Request to post document to BC."""
    vendor_id: str
    vendor_number: Optional[str] = None
    invoice_number: str
    invoice_date: str
    due_date: Optional[str] = None
    currency: str = "USD"
    total_amount: float
    line_items: Optional[List[dict]] = None


class PostToBCResponse(BaseModel):
    """Response from posting to BC."""
    success: bool
    bc_document_id: Optional[str] = None
    bc_document_number: Optional[str] = None
    bc_posting_status: str
    message: str
    error: Optional[str] = None
    # Link writeback status
    sharepoint_url: Optional[str] = None
    bc_link_writeback_status: Optional[str] = None  # "success", "failed", "skipped"
    bc_link_writeback_error: Optional[str] = None


# =============================================================================
# DEPENDENCY: Get DB and BC Service
# =============================================================================

# These will be set by the main server.py when including this router
db = None
bc_service = None

def set_dependencies(database, business_central_service):
    """Set dependencies injected from main server."""
    global db, bc_service
    db = database
    bc_service = business_central_service


# =============================================================================
# VENDOR SEARCH ENDPOINTS
# =============================================================================

@ap_review_router.get("/vendors")
async def search_vendors(
    q: Optional[str] = Query(None, description="Search text for vendor name/number"),
    limit: int = Query(50, description="Max results to return")
):
    """
    Search vendors from Business Central.
    Returns list of vendors matching the search criteria.
    """
    if bc_service is None:
        # Fallback to importing the service
        from services.business_central_service import get_bc_service
        service = get_bc_service()
    else:
        service = bc_service
    
    try:
        result = await service.get_vendors(filter_text=q, limit=limit)
        return {
            "vendors": result.get("vendors", []),
            "total": result.get("total", 0),
            "mock": result.get("mock", False)
        }
    except Exception as e:
        logger.error("Vendor search failed: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Vendor search failed: {str(e)}")


@ap_review_router.get("/vendors/{vendor_id}")
async def get_vendor(vendor_id: str):
    """Get a specific vendor by ID or number."""
    if bc_service is None:
        from services.business_central_service import get_bc_service
        service = get_bc_service()
    else:
        service = bc_service
    
    try:
        vendor = await service.get_vendor_by_id(vendor_id)
        if not vendor:
            raise HTTPException(status_code=404, detail="Vendor not found")
        return vendor
    except HTTPException:
        raise
    except Exception as e:
        logger.error("Get vendor failed: %s", str(e))
        raise HTTPException(status_code=500, detail=f"Get vendor failed: {str(e)}")


# =============================================================================
# PURCHASE ORDER SEARCH ENDPOINTS
# =============================================================================

@ap_review_router.get("/purchase-orders")
async def search_purchase_orders(
    vendor_id: Optional[str] = Query(None, description="Filter by vendor ID/number"),
    limit: int = Query(50, description="Max results to return")
):
    """
    Search open purchase orders from Business Central.
    Optionally filter by vendor.
    """
    if bc_service is None:
        from services.business_central_service import get_bc_service
        service = get_bc_service()
    else:
        service = bc_service
    
    try:
        result = await service.get_open_purchase_orders(vendor_id=vendor_id, limit=limit)
        return {
            "purchaseOrders": result.get("purchaseOrders", []),
            "total": result.get("total", 0),
            "mock": result.get("mock", False)
        }
    except Exception as e:
        logger.error("PO search failed: %s", str(e))
        raise HTTPException(status_code=500, detail=f"PO search failed: {str(e)}")


# =============================================================================
# AP REVIEW SAVE/UPDATE ENDPOINTS
# =============================================================================

@ap_review_router.put("/documents/{doc_id}")
async def save_ap_review(doc_id: str, data: APReviewData):
    """
    Save AP review edits to a document.
    Updates vendor, invoice details, line items, etc.
    """
    logger.info(f"AP Review Save: doc_id={doc_id}, vendor_id={data.vendor_id}, invoice={data.invoice_number}")
    
    if db is None:
        logger.error("AP Review Save failed: Database not initialized")
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    # Find document
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Build update data
    update_data = {
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }
    
    # Map AP review fields to document fields
    if data.vendor_id is not None:
        update_data["vendor_id"] = data.vendor_id
        update_data["vendor_canonical"] = data.vendor_id
    if data.vendor_name_resolved is not None:
        update_data["vendor_name_resolved"] = data.vendor_name_resolved
        update_data["vendor_raw"] = data.vendor_name_resolved
    if data.invoice_number is not None:
        update_data["invoice_number_clean"] = data.invoice_number
        # Also update extracted_fields
        extracted = doc.get("extracted_fields", {})
        extracted["invoice_number"] = data.invoice_number
        update_data["extracted_fields"] = extracted
    if data.invoice_date is not None:
        update_data["invoice_date"] = data.invoice_date
        extracted = update_data.get("extracted_fields") or doc.get("extracted_fields", {})
        extracted["invoice_date"] = data.invoice_date
        update_data["extracted_fields"] = extracted
    if data.due_date is not None:
        update_data["due_date_iso"] = data.due_date
        extracted = update_data.get("extracted_fields") or doc.get("extracted_fields", {})
        extracted["due_date"] = data.due_date
        update_data["extracted_fields"] = extracted
    if data.currency is not None:
        update_data["currency"] = data.currency
    if data.total_amount is not None:
        update_data["amount_float"] = data.total_amount
        extracted = update_data.get("extracted_fields") or doc.get("extracted_fields", {})
        extracted["amount"] = str(data.total_amount)
        update_data["extracted_fields"] = extracted
    if data.tax_amount is not None:
        update_data["tax_amount"] = data.tax_amount
    if data.po_number is not None:
        update_data["po_number_clean"] = data.po_number
        extracted = update_data.get("extracted_fields") or doc.get("extracted_fields", {})
        extracted["po_number"] = data.po_number
        update_data["extracted_fields"] = extracted
    if data.line_items is not None:
        update_data["line_items"] = data.line_items
    if data.notes is not None:
        update_data["ap_review_notes"] = data.notes
    
    # Update document
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": update_data}
    )
    
    # Fetch updated document
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    
    logger.info(f"AP Review Save SUCCESS: doc_id={doc_id}")
    
    return {
        "success": True,
        "message": "AP review saved",
        "document": updated_doc
    }


@ap_review_router.post("/documents/{doc_id}/mark-ready")
async def mark_ready_for_post(doc_id: str):
    """
    Mark a document as ready for posting to BC.
    Sets review_status to 'ready_for_post'.
    """
    logger.info(f"AP Review Mark Ready: doc_id={doc_id}")
    
    if db is None:
        logger.error("AP Review Mark Ready failed: Database not initialized")
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    # Find document
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Validate required fields
    missing_fields = []
    if not doc.get("vendor_id") and not doc.get("vendor_canonical"):
        missing_fields.append("vendor")
    if not doc.get("invoice_number_clean") and not doc.get("extracted_fields", {}).get("invoice_number"):
        missing_fields.append("invoice_number")
    if not doc.get("amount_float") and not doc.get("extracted_fields", {}).get("amount"):
        missing_fields.append("amount")
    
    if missing_fields:
        raise HTTPException(
            status_code=400, 
            detail=f"Cannot mark ready: missing required fields: {', '.join(missing_fields)}"
        )
    
    # Update status
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "review_status": "ready_for_post",
            "bc_posting_status": "not_posted",
            "status": "ReadyForPost",
            "workflow_status": "ready_for_post",
            "updated_utc": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    
    logger.info(f"AP Review Mark Ready SUCCESS: doc_id={doc_id}")
    
    return {
        "success": True,
        "message": "Document marked as ready for posting",
        "review_status": "ready_for_post",
        "document": updated_doc
    }


# =============================================================================
# POST TO BC ENDPOINT
# =============================================================================

@ap_review_router.post("/documents/{doc_id}/post-to-bc")
async def post_document_to_bc(doc_id: str, request: Optional[PostToBCRequest] = None):
    """
    Post a document to Business Central as a purchase invoice.
    Creates a purchase invoice in BC with the document's extracted data.
    On success, stores the BC document ID and updates posting status.
    On failure, records error details for retry.
    """
    logger.info(f"AP Review Post to BC: doc_id={doc_id}")
    
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    # Find document
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    # Check document is ready for posting
    review_status = doc.get("review_status", "")
    if review_status not in ("ready_for_post", "data_correction_pending"):
        # Allow posting from ready_for_post or retry from data_correction
        if doc.get("bc_posting_status") != "failed":
            raise HTTPException(
                status_code=400,
                detail=f"Document must be marked 'ready_for_post' before posting. Current status: {review_status}"
            )
    
    # Check not already posted
    if doc.get("bc_posting_status") == "posted":
        raise HTTPException(
            status_code=400,
            detail=f"Document already posted to BC. BC Document ID: {doc.get('bc_document_id')}"
        )
    
    # Get BC service
    if bc_service is None:
        from services.business_central_service import get_bc_service
        service = get_bc_service()
    else:
        service = bc_service
    
    # Build invoice data from document or request
    extracted = doc.get("extracted_fields", {})
    
    if request:
        invoice_data = {
            "vendorNumber": request.vendor_number or doc.get("vendor_id") or doc.get("vendor_canonical"),
            "invoiceNumber": request.invoice_number,
            "invoiceDate": request.invoice_date,
            "dueDate": request.due_date,
            "currencyCode": request.currency,
            "lines": request.line_items or doc.get("line_items", [])
        }
    else:
        # Build from document data
        invoice_data = {
            "vendorNumber": doc.get("vendor_id") or doc.get("vendor_canonical") or extracted.get("vendor_no"),
            "invoiceNumber": doc.get("invoice_number_clean") or extracted.get("invoice_number"),
            "invoiceDate": doc.get("invoice_date") or extracted.get("invoice_date"),
            "dueDate": doc.get("due_date_iso") or extracted.get("due_date"),
            "currencyCode": doc.get("currency", "USD"),
            "lines": doc.get("line_items", [])
        }
    
    # Validate required fields
    if not invoice_data.get("vendorNumber"):
        raise HTTPException(status_code=400, detail="Vendor is required for posting")
    if not invoice_data.get("invoiceNumber"):
        raise HTTPException(status_code=400, detail="Invoice number is required for posting")
    if not invoice_data.get("invoiceDate"):
        raise HTTPException(status_code=400, detail="Invoice date is required for posting")
    
    # Update status to posting
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "bc_posting_status": "posting",
            "updated_utc": datetime.now(timezone.utc).isoformat()
        }}
    )
    
    try:
        # Call BC service to create purchase invoice
        result = await service.create_purchase_invoice(invoice_data)
        
        if result.get("success"):
            bc_document_id = result.get("bcDocumentId")
            bc_document_number = result.get("bcDocumentNumber")
            
            # Get SharePoint URL from document (if uploaded)
            sharepoint_url = doc.get("sharepoint_share_link_url") or doc.get("sharepoint_web_url")
            
            # Attempt to write SharePoint link back to BC (non-blocking)
            link_writeback_status = "skipped"
            link_writeback_error = None
            
            if sharepoint_url and bc_document_id:
                try:
                    # Get additional SharePoint details from document
                    sp_drive_id = doc.get("sharepoint_drive_id")
                    sp_item_id = doc.get("sharepoint_item_id")
                    
                    writeback_result = await service.update_purchase_invoice_link(
                        invoice_id=bc_document_id,
                        sharepoint_url=sharepoint_url,
                        bc_document_no=bc_document_number,
                        sharepoint_drive_id=sp_drive_id,
                        sharepoint_item_id=sp_item_id,
                        uploaded_by="GPI Hub"
                    )
                    if writeback_result.get("success"):
                        link_writeback_status = "success"
                        if writeback_result.get("fallback"):
                            link_writeback_status = "success_fallback"
                        logger.info("SharePoint link written to BC for invoice %s (action: %s)", 
                                   bc_document_id, writeback_result.get("action", "unknown"))
                    elif writeback_result.get("skipped"):
                        link_writeback_status = "skipped"
                        link_writeback_error = writeback_result.get("reason")
                    else:
                        link_writeback_status = "failed"
                        link_writeback_error = writeback_result.get("error") or writeback_result.get("details")
                        logger.warning("BC link writeback failed for doc %s: %s", doc_id, link_writeback_error)
                except Exception as wb_err:
                    link_writeback_status = "failed"
                    link_writeback_error = str(wb_err)
                    logger.warning("BC link writeback exception for doc %s: %s", doc_id, wb_err)
            elif not sharepoint_url:
                link_writeback_status = "skipped"
                link_writeback_error = "No SharePoint URL available"
            
            # Success - update document with BC details and writeback status
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "bc_document_id": bc_document_id,
                    "bc_document_number": bc_document_number,
                    "bc_posting_status": "posted",
                    "bc_posting_error": None,
                    "bc_link_writeback_status": link_writeback_status,
                    "bc_link_writeback_error": link_writeback_error,
                    "review_status": "posted",
                    "status": "Posted",
                    "workflow_status": "posted",
                    "posted_to_bc_utc": datetime.now(timezone.utc).isoformat(),
                    "updated_utc": datetime.now(timezone.utc).isoformat()
                }}
            )
            
            updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
            
            return PostToBCResponse(
                success=True,
                bc_document_id=bc_document_id,
                bc_document_number=bc_document_number,
                bc_posting_status="posted",
                message=result.get("message", "Posted successfully"),
                sharepoint_url=sharepoint_url,
                bc_link_writeback_status=link_writeback_status,
                bc_link_writeback_error=link_writeback_error
            )
        else:
            # Failure - record error
            error_msg = result.get("error") or result.get("details") or "Unknown error"
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "bc_posting_status": "failed",
                    "bc_posting_error": error_msg,
                    "review_status": "ready_for_post",  # Keep ready for retry
                    "updated_utc": datetime.now(timezone.utc).isoformat()
                }}
            )
            
            return PostToBCResponse(
                success=False,
                bc_posting_status="failed",
                message="Failed to post to Business Central",
                error=error_msg
            )
            
    except Exception as e:
        # Exception - record error
        error_msg = str(e)
        logger.error("Post to BC failed for doc %s: %s", doc_id, error_msg)
        
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "bc_posting_status": "failed",
                "bc_posting_error": error_msg,
                "review_status": "ready_for_post",
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        return PostToBCResponse(
            success=False,
            bc_posting_status="failed",
            message="Error posting to Business Central",
            error=error_msg
        )


@ap_review_router.get("/documents/{doc_id}/bc-status")
async def get_bc_posting_status(doc_id: str):
    """Get the BC posting status for a document."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    return {
        "document_id": doc_id,
        "review_status": doc.get("review_status"),
        "bc_posting_status": doc.get("bc_posting_status"),
        "bc_document_id": doc.get("bc_document_id"),
        "bc_document_number": doc.get("bc_document_number"),
        "bc_posting_error": doc.get("bc_posting_error"),
        "posted_to_bc_utc": doc.get("posted_to_bc_utc")
    }
