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
        "lines": doc.get("line_items", [])
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
