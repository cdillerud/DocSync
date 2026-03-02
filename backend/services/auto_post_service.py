"""
GPI Document Hub - Auto-Post Service

Automatically posts AP invoices to Business Central when criteria are met:
1. AI extraction confidence >= 90%
2. Invoice number extracted
3. Invoice date extracted
4. Total amount extracted
5. Vendor matched to BC (vendor_id resolved)
6. Document stored in SharePoint

This replicates Square9 workflow automation behavior.
"""

import os
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional

logger = logging.getLogger(__name__)

# Configuration
AUTO_POST_ENABLED = os.environ.get("AUTO_POST_ENABLED", "true").lower() in ("true", "1", "yes")
AUTO_POST_CONFIDENCE_THRESHOLD = float(os.environ.get("AUTO_POST_CONFIDENCE_THRESHOLD", "0.90"))


class AutoPostResult:
    """Result of auto-post attempt."""
    
    def __init__(
        self,
        eligible: bool = False,
        attempted: bool = False,
        success: bool = False,
        bc_document_id: str = None,
        bc_document_number: str = None,
        error: str = None,
        reason: str = None
    ):
        self.eligible = eligible
        self.attempted = attempted
        self.success = success
        self.bc_document_id = bc_document_id
        self.bc_document_number = bc_document_number
        self.error = error
        self.reason = reason
        self.timestamp = datetime.now(timezone.utc).isoformat()
    
    def to_dict(self) -> Dict[str, Any]:
        return {
            "eligible": self.eligible,
            "attempted": self.attempted,
            "success": self.success,
            "bc_document_id": self.bc_document_id,
            "bc_document_number": self.bc_document_number,
            "error": self.error,
            "reason": self.reason,
            "timestamp": self.timestamp
        }


def check_auto_post_eligibility(doc: Dict[str, Any]) -> tuple[bool, str]:
    """
    Check if a document is eligible for auto-posting.
    
    Returns:
        (eligible: bool, reason: str)
    """
    if not AUTO_POST_ENABLED:
        return False, "Auto-post disabled (AUTO_POST_ENABLED=false)"
    
    # Check document type - only AP invoices
    doc_type = doc.get("doc_type", "").upper()
    if doc_type not in ("AP_INVOICE", "AP_Invoice"):
        return False, f"Not an AP invoice (doc_type={doc_type})"
    
    # Check AI extraction confidence
    ai_extraction = doc.get("ai_extraction", {})
    confidence = ai_extraction.get("confidence", 0) or doc.get("classification_confidence", 0)
    if confidence < AUTO_POST_CONFIDENCE_THRESHOLD:
        return False, f"Confidence too low ({confidence:.2f} < {AUTO_POST_CONFIDENCE_THRESHOLD})"
    
    # Check required fields extracted
    invoice_number = (
        doc.get("invoice_number_clean") or 
        doc.get("extracted_fields", {}).get("invoice_number") or
        ai_extraction.get("invoice_number")
    )
    if not invoice_number:
        return False, "Missing invoice number"
    
    invoice_date = (
        doc.get("invoice_date") or 
        doc.get("extracted_fields", {}).get("invoice_date") or
        ai_extraction.get("invoice_date")
    )
    if not invoice_date:
        return False, "Missing invoice date"
    
    total_amount = (
        doc.get("amount_float") or 
        doc.get("extracted_fields", {}).get("amount") or
        ai_extraction.get("total_amount")
    )
    if not total_amount:
        return False, "Missing total amount"
    
    # Check vendor is matched to BC
    vendor_id = doc.get("vendor_id") or doc.get("vendor_canonical")
    if not vendor_id:
        return False, "Vendor not matched to BC"
    
    # Check document is in SharePoint
    sharepoint_url = doc.get("sharepoint_share_link_url") or doc.get("sharepoint_web_url")
    if not sharepoint_url:
        return False, "Document not in SharePoint"
    
    # Check not already posted
    bc_posting_status = doc.get("bc_posting_status")
    if bc_posting_status == "posted":
        return False, "Already posted to BC"
    
    return True, "All criteria met"


async def attempt_auto_post(doc_id: str, doc: Dict[str, Any], db, bc_service) -> AutoPostResult:
    """
    Attempt to auto-post a document to Business Central.
    
    Args:
        doc_id: Document ID
        doc: Document data
        db: MongoDB database reference
        bc_service: BusinessCentralService instance
        
    Returns:
        AutoPostResult with outcome details
    """
    # Check eligibility
    eligible, reason = check_auto_post_eligibility(doc)
    
    if not eligible:
        logger.debug("Document %s not eligible for auto-post: %s", doc_id, reason)
        return AutoPostResult(eligible=False, reason=reason)
    
    logger.info("Document %s eligible for auto-post, attempting...", doc_id)
    
    # Build invoice data
    ai_extraction = doc.get("ai_extraction", {})
    extracted_fields = doc.get("extracted_fields", {})
    normalized_fields = doc.get("normalized_fields", {})
    
    # Extract BOL/Order number for line item description
    # This is critical for freight invoices to link back to sales orders
    order_reference = (
        doc.get("bol_number_extracted") or
        doc.get("po_number_extracted") or
        normalized_fields.get("bol_number") or
        normalized_fields.get("po_number_clean") or
        normalized_fields.get("po_number") or
        extracted_fields.get("bol_number") or
        extracted_fields.get("po_number") or
        extracted_fields.get("order_number") or
        ai_extraction.get("bol_number") or
        ai_extraction.get("po_number") or
        ai_extraction.get("order_number")
    )
    
    # Get existing line items or create default
    line_items = doc.get("line_items", [])
    
    # If we have an order reference, ensure it's in the line description
    # This matches Square9/BC pattern where Description field contains order #
    if order_reference:
        order_ref_str = str(order_reference).strip()
        logger.info("Auto-post: Using order reference '%s' for line description", order_ref_str)
        
        if not line_items:
            # No line items - create a default freight line with order # as description
            total_amount = float(
                doc.get("amount_float") or 
                extracted_fields.get("amount") or
                ai_extraction.get("total_amount") or 0
            )
            line_items = [{
                "description": order_ref_str,  # Order # goes in description
                "quantity": 1,
                "unit_price": total_amount
            }]
        else:
            # Have line items - prepend order # to each description
            for line in line_items:
                existing_desc = line.get("description", "")
                if order_ref_str not in str(existing_desc):
                    line["description"] = order_ref_str if not existing_desc else f"{order_ref_str} - {existing_desc}"
    elif not line_items:
        # No order reference and no line items - create default line with amount
        total_amount = float(
            doc.get("amount_float") or 
            extracted_fields.get("amount") or
            ai_extraction.get("total_amount") or 0
        )
        line_items = [{
            "description": "Freight",
            "quantity": 1,
            "unit_price": total_amount
        }]
    
    invoice_data = {
        "vendorNumber": doc.get("vendor_id") or doc.get("vendor_canonical"),
        "invoiceNumber": (
            doc.get("invoice_number_clean") or 
            extracted_fields.get("invoice_number") or
            ai_extraction.get("invoice_number")
        ),
        "invoiceDate": (
            doc.get("invoice_date") or 
            extracted_fields.get("invoice_date") or
            ai_extraction.get("invoice_date")
        ),
        "dueDate": (
            doc.get("due_date_iso") or 
            extracted_fields.get("due_date") or
            ai_extraction.get("due_date")
        ),
        "currencyCode": doc.get("currency", "USD"),
        "lines": line_items,
        "orderReference": order_reference  # Store for reference/logging
    }
    
    try:
        # Update status to posting
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "bc_posting_status": "auto_posting",
                "auto_post_attempted": True,
                "auto_post_attempted_at": datetime.now(timezone.utc).isoformat(),
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        # Call BC service to create purchase invoice
        result = await bc_service.create_purchase_invoice(invoice_data)
        
        if result.get("success"):
            bc_document_id = result.get("bcDocumentId")
            bc_document_number = result.get("bcDocumentNumber")
            
            # Attempt link writeback
            sharepoint_url = doc.get("sharepoint_share_link_url") or doc.get("sharepoint_web_url")
            link_writeback_status = "skipped"
            
            if sharepoint_url and bc_document_id:
                try:
                    writeback_result = await bc_service.update_purchase_invoice_link(
                        invoice_id=bc_document_id,
                        sharepoint_url=sharepoint_url,
                        bc_document_no=bc_document_number,
                        uploaded_by="GPI Hub (Auto-Post)"
                    )
                    link_writeback_status = "success" if writeback_result.get("success") else "failed"
                except Exception as wb_err:
                    logger.warning("Auto-post link writeback failed for %s: %s", doc_id, wb_err)
                    link_writeback_status = "failed"
            
            # Update document with success
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "bc_document_id": bc_document_id,
                    "bc_document_number": bc_document_number,
                    "bc_posting_status": "posted",
                    "bc_posting_error": None,
                    "bc_link_writeback_status": link_writeback_status,
                    "review_status": "auto_posted",
                    "status": "Posted",
                    "workflow_status": "posted",
                    "auto_post_success": True,
                    "posted_to_bc_utc": datetime.now(timezone.utc).isoformat(),
                    "updated_utc": datetime.now(timezone.utc).isoformat()
                }}
            )
            
            logger.info("AUTO-POST SUCCESS: Doc %s -> BC Invoice %s", doc_id, bc_document_number)
            
            return AutoPostResult(
                eligible=True,
                attempted=True,
                success=True,
                bc_document_id=bc_document_id,
                bc_document_number=bc_document_number,
                reason="Auto-posted successfully"
            )
        else:
            # Post failed
            error_msg = result.get("error") or result.get("details") or "Unknown error"
            
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "bc_posting_status": "auto_post_failed",
                    "bc_posting_error": error_msg,
                    "review_status": "needs_review",
                    "auto_post_success": False,
                    "updated_utc": datetime.now(timezone.utc).isoformat()
                }}
            )
            
            logger.warning("AUTO-POST FAILED: Doc %s - %s", doc_id, error_msg)
            
            return AutoPostResult(
                eligible=True,
                attempted=True,
                success=False,
                error=error_msg,
                reason="BC API error"
            )
            
    except Exception as e:
        error_msg = str(e)
        logger.error("AUTO-POST EXCEPTION: Doc %s - %s", doc_id, error_msg)
        
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "bc_posting_status": "auto_post_failed",
                "bc_posting_error": error_msg,
                "review_status": "needs_review",
                "auto_post_success": False,
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        return AutoPostResult(
            eligible=True,
            attempted=True,
            success=False,
            error=error_msg,
            reason="Exception during auto-post"
        )


async def process_document_for_auto_post(doc_id: str, db, bc_service) -> AutoPostResult:
    """
    Fetch document and attempt auto-post if eligible.
    
    Convenience function that fetches the document first.
    """
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        return AutoPostResult(eligible=False, reason=f"Document {doc_id} not found")
    
    return await attempt_auto_post(doc_id, doc, db, bc_service)


# =============================================================================
# AUTO-CREATE SALES ORDER (Square9-style)
# =============================================================================

AUTO_CREATE_SALES_ORDER_ENABLED = os.environ.get("AUTO_CREATE_SALES_ORDER_ENABLED", "true").lower() in ("true", "1", "yes")


def check_sales_order_eligibility(doc: Dict[str, Any]) -> tuple[bool, str]:
    """
    Check if a document is eligible for auto-creation of BC Sales Order.
    
    Returns:
        (eligible: bool, reason: str)
    """
    if not AUTO_CREATE_SALES_ORDER_ENABLED:
        return False, "Auto-create sales order disabled"
    
    # Check document type
    doc_type = doc.get("doc_type", "").upper()
    suggested_type = (doc.get("suggested_job_type") or "").upper()
    
    if "SALES" not in doc_type and "SALES" not in suggested_type:
        return False, f"Not a sales document (doc_type={doc_type})"
    
    # Check confidence
    confidence = doc.get("ai_confidence", 0) or doc.get("classification_confidence", 0)
    if confidence < AUTO_POST_CONFIDENCE_THRESHOLD:
        return False, f"Confidence too low ({confidence:.2f} < {AUTO_POST_CONFIDENCE_THRESHOLD})"
    
    # Check customer extracted
    customer = (
        doc.get("customer_extracted") or
        doc.get("extracted_fields", {}).get("customer") or
        doc.get("normalized_fields", {}).get("customer")
    )
    if not customer:
        return False, "Customer not extracted"
    
    # Check order/PO number
    order_number = (
        doc.get("order_number_extracted") or
        doc.get("extracted_fields", {}).get("order_number") or
        doc.get("extracted_fields", {}).get("po_number") or
        doc.get("normalized_fields", {}).get("customer_po")
    )
    if not order_number:
        return False, "Order/PO number not extracted"
    
    # Check SharePoint
    sharepoint_url = doc.get("sharepoint_share_link_url") or doc.get("sharepoint_web_url")
    if not sharepoint_url:
        return False, "Document not in SharePoint"
    
    # Check not already created
    if doc.get("bc_document_id") or doc.get("bc_sales_order_id"):
        return False, "BC Sales Order already created"
    
    return True, "All criteria met"


async def attempt_auto_create_sales_order(doc_id: str, doc: Dict[str, Any], db, bc_service) -> AutoPostResult:
    """
    Attempt to auto-create a BC Sales Order from a sales document.
    
    Args:
        doc_id: Document ID
        doc: Document data
        db: MongoDB database reference
        bc_service: BusinessCentralService instance
        
    Returns:
        AutoPostResult with outcome details
    """
    # Check eligibility
    eligible, reason = check_sales_order_eligibility(doc)
    
    if not eligible:
        logger.debug("Document %s not eligible for auto-create sales order: %s", doc_id, reason)
        return AutoPostResult(eligible=False, reason=reason)
    
    logger.info("Document %s eligible for auto-create sales order, attempting...", doc_id)
    
    # Extract customer and order data
    extracted = doc.get("extracted_fields", {})
    normalized = doc.get("normalized_fields", {})
    
    customer_name = (
        doc.get("customer_extracted") or
        extracted.get("customer") or
        normalized.get("customer")
    )
    
    order_number = (
        doc.get("order_number_extracted") or
        extracted.get("order_number") or
        extracted.get("po_number") or
        normalized.get("customer_po")
    )
    
    order_date = (
        extracted.get("order_date") or
        normalized.get("order_date") or
        datetime.now(timezone.utc).strftime("%Y-%m-%d")
    )
    
    # Look up customer in BC
    customer_number = await _lookup_bc_customer(customer_name, bc_service)
    
    if not customer_number:
        logger.warning("AUTO-CREATE: Customer '%s' not found in BC for doc %s", customer_name, doc_id)
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "auto_create_attempted": True,
                "auto_create_error": f"Customer '{customer_name}' not found in BC",
                "review_status": "needs_review",
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }}
        )
        return AutoPostResult(
            eligible=True,
            attempted=True,
            success=False,
            error=f"Customer '{customer_name}' not found in BC",
            reason="Customer lookup failed"
        )
    
    # Build sales order data
    line_items = doc.get("line_items", []) or extracted.get("line_items", [])
    
    order_data = {
        "customerNumber": customer_number,
        "externalDocumentNumber": str(order_number),
        "orderDate": order_date,
        "lines": line_items
    }
    
    try:
        # Update status to creating
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "bc_posting_status": "auto_creating",
                "auto_create_attempted": True,
                "auto_create_attempted_at": datetime.now(timezone.utc).isoformat(),
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        # Call BC service to create sales order
        result = await bc_service.create_sales_order(order_data)
        
        if result.get("success"):
            bc_document_id = result.get("bcDocumentId")
            bc_document_number = result.get("bcDocumentNumber")
            
            # Update document with success
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "bc_document_id": bc_document_id,
                    "bc_document_number": bc_document_number,
                    "bc_sales_order_id": bc_document_id,
                    "bc_sales_order_number": bc_document_number,
                    "bc_posting_status": "created",
                    "bc_posting_error": None,
                    "review_status": "auto_created",
                    "status": "Created",
                    "workflow_status": "exported",
                    "auto_create_success": True,
                    "created_in_bc_utc": datetime.now(timezone.utc).isoformat(),
                    "updated_utc": datetime.now(timezone.utc).isoformat()
                }}
            )
            
            logger.info("AUTO-CREATE SUCCESS: Doc %s -> BC Sales Order %s", doc_id, bc_document_number)
            
            return AutoPostResult(
                eligible=True,
                attempted=True,
                success=True,
                bc_document_id=bc_document_id,
                bc_document_number=bc_document_number,
                reason="Sales Order created successfully"
            )
        else:
            error_msg = result.get("error") or result.get("details") or "Unknown error"
            
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "bc_posting_status": "auto_create_failed",
                    "bc_posting_error": error_msg,
                    "review_status": "needs_review",
                    "auto_create_success": False,
                    "updated_utc": datetime.now(timezone.utc).isoformat()
                }}
            )
            
            logger.warning("AUTO-CREATE FAILED: Doc %s - %s", doc_id, error_msg)
            
            return AutoPostResult(
                eligible=True,
                attempted=True,
                success=False,
                error=error_msg,
                reason="BC API error"
            )
            
    except Exception as e:
        error_msg = str(e)
        logger.error("AUTO-CREATE EXCEPTION: Doc %s - %s", doc_id, error_msg)
        
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "bc_posting_status": "auto_create_failed",
                "bc_posting_error": error_msg,
                "review_status": "needs_review",
                "auto_create_success": False,
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }}
        )
        
        return AutoPostResult(
            eligible=True,
            attempted=True,
            success=False,
            error=error_msg,
            reason="Exception during auto-create"
        )


async def _lookup_bc_customer(customer_name: str, bc_service) -> Optional[str]:
    """
    Look up a customer in BC by name and return the customer number.
    
    Tries:
    1. Exact match on displayName
    2. Contains match on displayName
    3. First word match (company name prefix)
    """
    if not customer_name:
        return None
    
    try:
        # Use BC service to search for customer
        token = await bc_service._ensure_token()
        company_id = await bc_service._get_company_id()
        
        import httpx
        base_url = f"https://api.businesscentral.dynamics.com/v2.0/{bc_service.tenant_id}/{bc_service.environment}/api/v2.0"
        
        async with httpx.AsyncClient(timeout=30) as client:
            # Try exact match first
            resp = await client.get(
                f"{base_url}/companies({company_id})/customers",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": f"displayName eq '{customer_name}'",
                    "$select": "number,displayName",
                    "$top": "1"
                }
            )
            
            if resp.status_code == 200:
                customers = resp.json().get("value", [])
                if customers:
                    logger.info("Found exact customer match: %s -> %s", customer_name, customers[0]["number"])
                    return customers[0]["number"]
            
            # Try contains match
            # Escape single quotes in customer name
            safe_name = customer_name.replace("'", "''")
            resp = await client.get(
                f"{base_url}/companies({company_id})/customers",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": f"contains(displayName, '{safe_name}')",
                    "$select": "number,displayName",
                    "$top": "5"
                }
            )
            
            if resp.status_code == 200:
                customers = resp.json().get("value", [])
                if customers:
                    # Return first match
                    logger.info("Found customer contains match: %s -> %s (%s)", 
                               customer_name, customers[0]["number"], customers[0]["displayName"])
                    return customers[0]["number"]
            
            # Try first word match (common for "Company Name LLC" -> "Company Name")
            first_word = customer_name.split()[0] if customer_name else ""
            if first_word and len(first_word) > 3:
                resp = await client.get(
                    f"{base_url}/companies({company_id})/customers",
                    headers={"Authorization": f"Bearer {token}"},
                    params={
                        "$filter": f"startswith(displayName, '{first_word}')",
                        "$select": "number,displayName",
                        "$top": "5"
                    }
                )
                
                if resp.status_code == 200:
                    customers = resp.json().get("value", [])
                    if customers:
                        logger.info("Found customer prefix match: %s -> %s (%s)", 
                                   customer_name, customers[0]["number"], customers[0]["displayName"])
                        return customers[0]["number"]
        
        logger.warning("No BC customer found for: %s", customer_name)
        return None
        
    except Exception as e:
        logger.error("Error looking up BC customer '%s': %s", customer_name, str(e))
        return None
