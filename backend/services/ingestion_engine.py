"""
Document ingestion/classification/validation engine.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 9). No logic changed - this is
the AP invoice processing pipeline: AI classification, field normalization,
vendor/customer alias + fuzzy matching against BC, duplicate detection,
BC validation, automation decision, and workflow status transitions.

NOTE: lines 2303-2604 of the original server.py (email watcher helpers:
get_email_watcher_config, subscribe_to_mailbox_notifications,
fetch_email_with_attachments, move_email_to_folder, and the dead/unused
on_document_ingested) were interspersed in this region but are NOT part of
this engine - they're only used by the not-yet-migrated Graph webhook and
job-types/email-watcher settings groups, and were deliberately left in
server.py. See MIGRATION_PROGRESS.md.

NOTE: is_eligible_for_draft_creation, check_duplicate_purchase_invoice, and
create_purchase_invoice_header are called from routes/ingestion.py's
intake_document (Phase 4 draft-creation path) but are NOT defined or
imported anywhere in the original server.py either - this is a pre-existing
latent bug, not introduced by this migration. It's unreachable under the
default DEFAULT_JOB_TYPES config (AP_Invoice's automation_level=1 means
make_automation_decision() can never return "auto_create", which is the
only way that code path is entered) and ENABLE_CREATE_DRAFT_HEADER defaults
to false. Preserved as-is; flagged here rather than silently "fixed" by
guessing at intent.
"""
import os
import re
import uuid
import hashlib
import httpx
from datetime import datetime, timezone, timedelta
from typing import Dict, Optional, List
from dateutil import parser as date_parser
import logging

from core.db import db
from core import config
from core.paths import UPLOAD_DIR
from core.job_config import DEFAULT_JOB_TYPES, VENDOR_ALIAS_MAP
from core.config import AI_CLASSIFICATION_ENABLED, AI_CLASSIFICATION_THRESHOLD, EMERGENT_LLM_KEY
from core.legacy_hub_helpers import (
    get_bc_token, get_bc_companies, upload_to_sharepoint, create_sharing_link,
)
from services.workflow_engine import (
    WorkflowEngine, WorkflowStatus, WorkflowEvent,
    DocType, SourceSystem, CaptureChannel, DocumentClassifier,
)
from services.ai_classifier import (
    classify_doc_type_with_ai, DEFAULT_CONFIDENCE_THRESHOLD,
)
from services.bc_sandbox_service import search_vendors_by_name, BCLookupStatus
from services.pilot_config import (
    PILOT_MODE_ENABLED, get_pilot_capture_channel, get_pilot_metadata,
)
from services.auto_post_service import (
    AUTO_POST_ENABLED, attempt_auto_post,
    AUTO_CREATE_SALES_ORDER_ENABLED, attempt_auto_create_sales_order,
)
from services.business_central_service import get_bc_service

logger = logging.getLogger(__name__)

# ==================== AI CLASSIFICATION SERVICE ====================

async def classify_document_with_ai(file_path: str, file_name: str) -> dict:
    """
    Use Gemini to analyze a document and extract structured data.
    Returns classification and extracted fields.
    """
    if not EMERGENT_LLM_KEY:
        return {
            "error": "EMERGENT_LLM_KEY not configured",
            "suggested_job_type": "Unknown",
            "confidence": 0.0,
            "extracted_fields": {}
        }
    
    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType
        
        # Determine MIME type
        ext = file_name.lower().split('.')[-1] if '.' in file_name else ''
        mime_map = {
            'pdf': 'application/pdf',
            'png': 'image/png',
            'jpg': 'image/jpeg',
            'jpeg': 'image/jpeg',
            'tiff': 'image/tiff',
            'gif': 'image/gif',
            'txt': 'text/plain',
            'csv': 'text/csv',
            'html': 'text/html',
            'json': 'application/json',
            'xml': 'application/xml'
        }
        mime_type = mime_map.get(ext, 'text/plain')  # Default to text/plain for better compatibility
        
        # Initialize chat with Gemini (required for file attachments)
        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"classify-{uuid.uuid4()}",
            system_message="""You are a document classification and data extraction AI for Gamer Packaging, Inc.'s document management system.

IMPORTANT CONTEXT:
- Our company is "Gamer Packaging, Inc." (also known as "Gamer Packaging" or "GPI")
- Documents come from BOTH our Accounts Payable inbox AND Sales mailboxes
- You must classify documents into the correct category: AP (accounts payable) or Sales

DOCUMENT CATEGORIES AND TYPES:

== AP (Accounts Payable) Category ==
AP_Invoice: Vendor invoices we RECEIVE
- The VENDOR is the company sending us the invoice (NOT Gamer Packaging)
- If "Gamer Packaging" appears as Bill To/Customer, this is an AP_Invoice we received
- Extract: vendor name (the sender), invoice_number, invoice_date, amount, po_number (if present), due_date
- CRITICAL: Always extract invoice_date (the date on the invoice itself)
- CRITICAL: Extract ALL line items with description, quantity, unit_price, and total

AR_Invoice: Invoices we send to customers (outgoing)
- Our company name appears as the sender
- Extract: customer name, invoice_number, invoice_date, amount, due_date

Remittance: Payment confirmations
- Extract: vendor/customer, payment_amount, payment_date, invoice_references
- Look for "Remittance Advice", "Payment", check numbers

Freight_Document: Shipping/freight documents  
- Extract: shipper, consignee, tracking_number, carrier, origin, destination
- Look for "Bill of Lading", "BOL", "HAWB", tracking numbers

== Sales Category ==
Sales_Order: Customer purchase orders to us
- Extract: customer name, po_number, order_date, amount, ship_to address
- Look for "Purchase Order", "PO#", "Order", quantity, ship to

Sales_Quote: Price quotes or proposals to customers
- Extract: customer, amount, valid_until
- Look for "Quote", "Quotation", "Proposal", "Estimate"

Order_Confirmation: Order acknowledgments
- Extract: order_number, customer, amount
- Look for "Confirmation", "Acknowledged", "Order Acknowledgment"

Inventory_Report: Stock/inventory status reports
- Extract: warehouse, items, quantities
- Look for "Inventory", "Stock", "On Hand", "Available"

Shipping_Document: Shipping documents, BOLs, Bills of Lading
- Extract: bol_number, ship_date, po_number, shipper, consignee, carrier, tracking_number, pro_number, weight, pieces
- Look for "Ship", "Delivery", "Dispatch", "Bill of Lading", "BOL", "Straight Bill", "Shipper", "Consignee"
- BOL Number is the primary document identifier (often labeled "B/L No" or "BOL#")
- Pro Number is the carrier's tracking/reference number

Quality_Issue: Quality complaints or issues
- Extract: customer, item, description
- Look for "Quality", "Defect", "Complaint", "NCR", "Claim"

Return_Request: Return requests / RMAs
- Extract: customer, amount, reason  
- Look for "Return", "RMA", "Credit", "Refund"

Unknown_Document: Cannot determine type confidently

Always respond with valid JSON in this exact format:
{
    "document_type": "AP_Invoice|AR_Invoice|Remittance|Freight_Document|Sales_Order|Sales_Quote|Order_Confirmation|Inventory_Report|Shipping_Document|Quality_Issue|Return_Request|Unknown_Document",
    "confidence": 0.0-1.0,
    "extracted_fields": {
        "vendor": "...",
        "customer": "...",
        "invoice_number": "...",
        "invoice_date": "YYYY-MM-DD format",
        "po_number": "...",
        "order_number": "...",
        "amount": "...",
        "due_date": "YYYY-MM-DD format",
        "order_date": "...",
        "ship_date": "...",
        "payment_date": "...",
        "payment_amount": "...",
        "tracking_number": "...",
        "bol_number": "...",
        "pro_number": "...",
        "shipper": "...",
        "consignee": "...",
        "carrier": "...",
        "weight": "...",
        "pieces": "...",
        "warehouse": "...",
        "items": "...",
        "ship_to": "...",
        "line_items": [
            {
                "description": "Item/service description",
                "quantity": 1.0,
                "unit_price": 0.00,
                "total": 0.00
            }
        ]
    },
    "reasoning": "Brief explanation of classification"
}

IMPORTANT: For invoices (AP_Invoice, AR_Invoice), you MUST extract:
- invoice_date: The date the invoice was issued (NOT due_date)
- line_items: ALL line items showing what was purchased/charged

For freight/transportation invoices, line items may include:
- Weight, distance, rate, charges
- Fuel surcharges, accessorial charges
- Extract these as line items with appropriate descriptions

Only include fields that you can actually extract from the document. Leave out fields that are not present."""
        ).with_model("gemini", "gemini-3-flash-preview")
        
        # Create file attachment
        file_content = FileContentWithMimeType(
            file_path=file_path,
            mime_type=mime_type
        )
        
        # Send for classification
        user_message = UserMessage(
            text="Please analyze this business document. Classify it and extract all relevant fields. Respond with JSON only.",
            file_contents=[file_content]
        )
        
        response = await chat.send_message(user_message)
        
        # Parse JSON response
        import json
        # Clean response - extract JSON from possible markdown code blocks
        response_text = response.strip()
        if response_text.startswith("```"):
            lines = response_text.split("\n")
            json_lines = []
            in_json = False
            for line in lines:
                if line.startswith("```json"):
                    in_json = True
                    continue
                if line.startswith("```") and in_json:
                    break
                if in_json:
                    json_lines.append(line)
            response_text = "\n".join(json_lines)
        
        result = json.loads(response_text)
        
        # Log what we got from AI for debugging
        extracted = result.get("extracted_fields", {})
        logger.info("AI Classification result - doc_type: %s, confidence: %s", 
                   result.get("document_type"), result.get("confidence"))
        logger.info("AI extracted invoice_date: %s", extracted.get("invoice_date"))
        logger.info("AI extracted line_items: %s", extracted.get("line_items"))
        
        return {
            "suggested_job_type": result.get("document_type", "Unknown"),
            "confidence": float(result.get("confidence", 0.0)),
            "extracted_fields": result.get("extracted_fields", {}),
            "reasoning": result.get("reasoning", ""),
            "model": "gemini-3-flash-preview"
        }
        
    except Exception as e:
        logger.error("AI classification failed: %s", str(e))
        return {
            "error": str(e),
            "suggested_job_type": "Unknown",
            "confidence": 0.0,
            "extracted_fields": {},
            "reasoning": f"Classification failed: {str(e)}"
        }

# ==================== FIELD NORMALIZATION ====================

def normalize_extracted_fields(fields: dict) -> dict:
    """
    Normalize extracted fields before BC validation.
    - Convert amounts to decimal
    - Convert dates to ISO format
    - Clean up strings
    """
    normalized = {}
    
    for key, value in fields.items():
        if value is None:
            continue
            
        # Amount fields
        if key in ('amount', 'payment_amount', 'total', 'subtotal'):
            # Remove currency symbols, commas, spaces
            clean_amount = re.sub(r'[^\d.-]', '', str(value))
            try:
                normalized[key] = float(clean_amount) if clean_amount else None
                normalized[f"{key}_raw"] = value  # Keep original for display
            except ValueError:
                normalized[key] = None
                normalized[f"{key}_raw"] = value
        
        # Date fields
        elif key in ('due_date', 'invoice_date', 'order_date', 'payment_date', 'ship_date', 'delivery_date', 'document_date'):
            try:
                parsed_date = date_parser.parse(str(value))
                normalized[key] = parsed_date.strftime('%Y-%m-%d')
                normalized[f"{key}_raw"] = value
            except Exception:
                normalized[key] = None
                normalized[f"{key}_raw"] = value
        
        # String fields - trim whitespace
        elif isinstance(value, str):
            normalized[key] = value.strip()
        else:
            normalized[key] = value
    
    return normalized


def compute_ap_normalized_fields(extracted_fields: dict) -> dict:
    """
    Phase 7: Compute normalized fields for AP_Invoice documents.
    
    Returns flat fields to be stored directly on the document:
    - vendor_raw, vendor_normalized
    - invoice_number_raw, invoice_number_clean
    - amount_raw, amount_float
    - due_date_raw, due_date_iso
    - po_number_raw, po_number_clean
    
    These are stored alongside extracted_fields, not nested.
    """
    result = {}
    
    if not extracted_fields:
        return result
    
    # Vendor normalization
    vendor = extracted_fields.get("vendor")
    if vendor:
        vendor_str = str(vendor).strip()
        result["vendor_raw"] = vendor_str
        # Lowercase, trimmed, collapse multiple internal spaces
        normalized = re.sub(r'\s+', ' ', vendor_str.lower().strip())
        result["vendor_normalized"] = normalized
    else:
        result["vendor_raw"] = None
        result["vendor_normalized"] = None
    
    # Invoice number normalization
    invoice_num = extracted_fields.get("invoice_number")
    if invoice_num:
        inv_str = str(invoice_num).strip()
        result["invoice_number_raw"] = inv_str
        # Strip spaces and commas, normalize casing for comparison
        clean = re.sub(r'[\s,]+', '', inv_str).upper()
        result["invoice_number_clean"] = clean
    else:
        result["invoice_number_raw"] = None
        result["invoice_number_clean"] = None
    
    # Amount parsing to float
    amount = extracted_fields.get("amount")
    if amount is not None:
        result["amount_raw"] = str(amount)
        try:
            # Remove currency symbols, commas, spaces
            clean_amount = re.sub(r'[^\d.-]', '', str(amount))
            result["amount_float"] = float(clean_amount) if clean_amount else None
        except (ValueError, TypeError):
            result["amount_float"] = None
    else:
        result["amount_raw"] = None
        result["amount_float"] = None
    
    # Due date to ISO
    due_date = extracted_fields.get("due_date")
    if due_date:
        result["due_date_raw"] = str(due_date)
        try:
            parsed_date = date_parser.parse(str(due_date))
            result["due_date_iso"] = parsed_date.strftime('%Y-%m-%d')
        except Exception:
            result["due_date_iso"] = None
    else:
        result["due_date_raw"] = None
        result["due_date_iso"] = None
    
    # PO number normalization
    po_number = extracted_fields.get("po_number")
    if po_number:
        po_str = str(po_number).strip()
        result["po_number_raw"] = po_str
        result["po_number_clean"] = re.sub(r'[\s,]+', '', po_str).upper()
    else:
        result["po_number_raw"] = None
        result["po_number_clean"] = None
    
    # Invoice date to ISO (CRITICAL for BC posting)
    invoice_date = extracted_fields.get("invoice_date")
    if invoice_date:
        result["invoice_date_raw"] = str(invoice_date)
        try:
            parsed_date = date_parser.parse(str(invoice_date))
            result["invoice_date"] = parsed_date.strftime('%Y-%m-%d')
        except Exception:
            result["invoice_date"] = None
    else:
        result["invoice_date_raw"] = None
        result["invoice_date"] = None
    
    # Line items (CRITICAL for BC posting)
    line_items = extracted_fields.get("line_items")
    if line_items and isinstance(line_items, list):
        # Normalize line items
        normalized_items = []
        for item in line_items:
            if isinstance(item, dict):
                normalized_items.append({
                    "description": item.get("description", ""),
                    "quantity": float(item.get("quantity", 1) or 1),
                    "unit_price": float(item.get("unit_price", 0) or 0),
                    "total": float(item.get("total", 0) or 0)
                })
        result["line_items"] = normalized_items
    else:
        result["line_items"] = []
    
    return result


async def lookup_vendor_alias(vendor_normalized: str) -> dict:
    """
    Phase 7: Look up vendor in alias collection, BC cache, or live BC API.
    
    Returns:
    - vendor_canonical: the canonical_vendor_id if found, else None
    - vendor_match_method: "alias", "exact_name", "bc_search", "fuzzy_bc", or "none"
    - vendor_name: matched vendor name
    - vendor_no: matched vendor number
    """
    if not vendor_normalized:
        return {"vendor_canonical": None, "vendor_match_method": "none"}
    
    # Check vendor_aliases collection
    alias_doc = await db.vendor_aliases.find_one({
        "$or": [
            {"normalized": vendor_normalized},
            {"normalized_alias": vendor_normalized},
            {"alias_string": {"$regex": f"^{re.escape(vendor_normalized)}$", "$options": "i"}}
        ]
    }, {"_id": 0})
    
    if alias_doc:
        canonical_id = alias_doc.get("canonical_vendor_id") or alias_doc.get("vendor_no") or alias_doc.get("vendor_name")
        return {
            "vendor_canonical": canonical_id,
            "vendor_match_method": "alias",
            "vendor_name": alias_doc.get("vendor_name"),
            "vendor_no": alias_doc.get("vendor_no")
        }
    
    # Check if exact match in cached BC vendors (if available)
    bc_vendor = await db.hub_bc_vendors.find_one({
        "$or": [
            {"name_normalized": vendor_normalized},
            {"displayName": {"$regex": f"^{re.escape(vendor_normalized)}$", "$options": "i"}}
        ]
    }, {"_id": 0})
    
    if bc_vendor:
        return {
            "vendor_canonical": bc_vendor.get("number") or bc_vendor.get("id"),
            "vendor_match_method": "exact_name",
            "vendor_name": bc_vendor.get("displayName"),
            "vendor_no": bc_vendor.get("number")
        }
    
    # Try live BC search with different search terms
    try:
        # Get the original vendor name (before normalization) for better matching
        vendor_search_term = vendor_normalized.title()  # Convert to title case
        
        # Try BC API search
        bc_result = await search_vendors_by_name(vendor_search_term, limit=10)
        
        if bc_result.status == BCLookupStatus.SUCCESS:
            vendors = bc_result.data.get("vendors", [])
            
            if vendors:
                # Try to find best match
                for vendor in vendors:
                    bc_name = vendor.get("displayName", "").lower()
                    # Check if normalized names match (case-insensitive)
                    bc_normalized = re.sub(r'\s+', ' ', bc_name.strip())
                    
                    if bc_normalized == vendor_normalized:
                        # Exact match found
                        return {
                            "vendor_canonical": vendor.get("number") or vendor.get("id"),
                            "vendor_match_method": "bc_search",
                            "vendor_name": vendor.get("displayName"),
                            "vendor_no": vendor.get("number")
                        }
                
                # If no exact match, try fuzzy matching
                best_match = None
                best_score = 0
                
                for vendor in vendors:
                    bc_name = vendor.get("displayName", "").lower()
                    bc_normalized = re.sub(r'\s+', ' ', bc_name.strip())
                    
                    # Simple similarity: check if all words from search are in BC name or vice versa
                    search_words = set(vendor_normalized.split())
                    bc_words = set(bc_normalized.split())
                    
                    # Calculate overlap score
                    overlap = len(search_words & bc_words)
                    total = len(search_words | bc_words)
                    score = overlap / total if total > 0 else 0
                    
                    if score > best_score and score >= 0.6:  # At least 60% overlap
                        best_score = score
                        best_match = vendor
                
                if best_match:
                    return {
                        "vendor_canonical": best_match.get("number") or best_match.get("id"),
                        "vendor_match_method": "fuzzy_bc",
                        "vendor_name": best_match.get("displayName"),
                        "vendor_no": best_match.get("number"),
                        "match_score": best_score
                    }
        
        # Try with first word only (company name often starts with key identifier)
        first_word = vendor_normalized.split()[0] if vendor_normalized else ""
        if first_word and len(first_word) >= 3:
            bc_result2 = await search_vendors_by_name(first_word.title(), limit=10)
            
            if bc_result2.status == BCLookupStatus.SUCCESS:
                vendors2 = bc_result2.data.get("vendors", [])
                
                for vendor in vendors2:
                    bc_name = vendor.get("displayName", "").lower()
                    bc_normalized = re.sub(r'\s+', ' ', bc_name.strip())
                    
                    # Check if vendor name starts with same word
                    if bc_normalized.startswith(first_word):
                        search_words = set(vendor_normalized.split())
                        bc_words = set(bc_normalized.split())
                        overlap = len(search_words & bc_words)
                        total = len(search_words | bc_words)
                        score = overlap / total if total > 0 else 0
                        
                        if score >= 0.5:  # At least 50% overlap for partial match
                            return {
                                "vendor_canonical": vendor.get("number") or vendor.get("id"),
                                "vendor_match_method": "fuzzy_bc",
                                "vendor_name": vendor.get("displayName"),
                                "vendor_no": vendor.get("number"),
                                "match_score": score
                            }
                            
    except Exception as e:
        logger.warning(f"BC vendor search failed: {e}")
    
    return {"vendor_canonical": None, "vendor_match_method": "none"}


async def check_duplicate_document(vendor_normalized: str, vendor_canonical: str, invoice_number_clean: str, current_doc_id: str) -> dict:
    """
    Phase 7: Check for potential duplicate AP invoice in the Hub.
    
    A document is a possible duplicate if another non-deleted doc exists with:
    - same vendor_canonical (if set) OR same vendor_normalized
    - same invoice_number_clean
    
    Returns:
    - possible_duplicate: boolean
    - duplicate_of_document_id: id of existing doc or None
    """
    if not invoice_number_clean:
        return {"possible_duplicate": False, "duplicate_of_document_id": None}
    
    # Build query
    vendor_match = {}
    if vendor_canonical:
        vendor_match = {"$or": [
            {"vendor_canonical": vendor_canonical},
            {"vendor_normalized": vendor_normalized}
        ]}
    elif vendor_normalized:
        vendor_match = {"vendor_normalized": vendor_normalized}
    else:
        return {"possible_duplicate": False, "duplicate_of_document_id": None}
    
    query = {
        **vendor_match,
        "invoice_number_clean": invoice_number_clean,
        "id": {"$ne": current_doc_id},  # Exclude current document
        "status": {"$nin": ["Deleted", "Rejected"]}  # Exclude deleted
    }
    
    existing = await db.hub_documents.find_one(query, {"id": 1, "_id": 0})
    
    if existing:
        return {
            "possible_duplicate": True,
            "duplicate_of_document_id": existing.get("id")
        }
    
    return {"possible_duplicate": False, "duplicate_of_document_id": None}


def compute_ap_validation(
    document_type: str,
    vendor_normalized: str,
    invoice_number_clean: str,
    amount_float: float,
    po_number_clean: str,
    ai_confidence: float,
    possible_duplicate: bool
) -> dict:
    """
    Phase 7: Compute validation_errors, validation_warnings, and draft_candidate for AP invoices.
    
    Required fields for AP invoice header readiness:
    - vendor_normalized
    - invoice_number_clean
    - amount_float
    
    draft_candidate = True when all three required fields are present and valid
    
    This does NOT create drafts or change status logic (handled separately).
    """
    validation_errors = []
    validation_warnings = []
    
    # Only process AP_Invoice documents
    if document_type not in ("AP_Invoice", "AP Invoice"):
        return {
            "draft_candidate": False,
            "validation_errors": [],
            "validation_warnings": []
        }
    
    # Check required fields
    if not vendor_normalized:
        validation_errors.append("missing_vendor")
    
    if not invoice_number_clean:
        validation_errors.append("missing_invoice_number")
    
    if amount_float is None:
        validation_errors.append("missing_amount")
    
    # Check confidence
    if ai_confidence is not None and ai_confidence < 0.90:
        validation_errors.append("low_classification_confidence")
    
    # Check duplicate
    if possible_duplicate:
        validation_errors.append("potential_duplicate_invoice")
    
    # Warnings (non-blocking)
    if not po_number_clean:
        validation_warnings.append("missing_po_number")
    
    # draft_candidate is True only when all required fields present and no errors
    draft_candidate = (
        len(validation_errors) == 0 and
        vendor_normalized is not None and
        invoice_number_clean is not None and
        amount_float is not None
    )
    
    return {
        "draft_candidate": draft_candidate,
        "validation_errors": validation_errors,
        "validation_warnings": validation_warnings
    }


def compute_ap_status(
    document_type: str,
    ai_confidence: float,
    validation_errors: list,
    draft_candidate: bool,
    current_status: str
) -> str:
    """
    Phase 7: Determine status for AP_Invoice documents.
    
    Status logic (observation mode - conservative):
    - If not AP_Invoice: unchanged (let other workflows handle)
    - If ai_confidence < 0.90: NeedsReview
    - If any validation_errors: NeedsReview
    - Else (no errors, draft_candidate=True): NeedsReview (but draft_candidate flag visible)
    
    In Phase 7, we do NOT auto-advance to any status that triggers BC writes.
    """
    if document_type not in ("AP_Invoice", "AP Invoice"):
        return current_status  # Unchanged for non-AP
    
    # All AP_Invoice documents stay in NeedsReview during Phase 7
    # The draft_candidate flag indicates readiness without changing status
    return "NeedsReview"


# Legacy wrapper for backward compatibility
def compute_canonical_fields(extracted_fields: dict) -> dict:
    """Legacy wrapper - calls compute_ap_normalized_fields"""
    return compute_ap_normalized_fields(extracted_fields)


def compute_draft_candidate_flag(
    document_type: str,
    extracted_fields: dict,
    canonical_fields: dict,
    ai_confidence: float
) -> dict:
    """
    Legacy wrapper for backward compatibility.
    Now delegates to compute_ap_validation.
    """
    # Extract normalized values
    vendor_normalized = canonical_fields.get("vendor_normalized")
    invoice_number_clean = canonical_fields.get("invoice_number_clean")
    amount_float = canonical_fields.get("amount_float")
    po_number_clean = canonical_fields.get("po_number_clean")
    
    result = compute_ap_validation(
        document_type=document_type,
        vendor_normalized=vendor_normalized,
        invoice_number_clean=invoice_number_clean,
        amount_float=amount_float,
        po_number_clean=po_number_clean,
        ai_confidence=ai_confidence,
        possible_duplicate=False  # Legacy doesn't have this
    )
    
    # Map to legacy format
    return {
        "draft_candidate": result["draft_candidate"],
        "draft_candidate_reason": result["validation_errors"] + result["validation_warnings"],
        "draft_candidate_score": 100.0 if result["draft_candidate"] else 0.0
    }


def normalize_vendor_name(name: str) -> str:
    """
    Normalize vendor name for matching.
    Strips common suffixes, punctuation, and converts to lowercase.
    """
    if not name:
        return ""
    
    # Convert to lowercase
    name = name.lower()
    
    # Remove common business suffixes
    suffixes = [
        r'\s*,?\s*(inc\.?|incorporated)$',
        r'\s*,?\s*(llc\.?|l\.l\.c\.?)$',
        r'\s*,?\s*(ltd\.?|limited)$',
        r'\s*,?\s*(corp\.?|corporation)$',
        r'\s*,?\s*(co\.?|company)$',
        r'\s*,?\s*(plc\.?)$',
        r'\s*,?\s*(gmbh)$',
        r'\s*,?\s*(ag)$',
    ]
    
    for suffix in suffixes:
        name = re.sub(suffix, '', name, flags=re.IGNORECASE)
    
    # Remove punctuation and extra spaces
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    
    return name

def calculate_fuzzy_score(name1: str, name2: str) -> float:
    """
    Calculate fuzzy match score between two strings.
    Uses simple token overlap ratio.
    Also handles BC vendor names that include vendor codes like "TUMALOC - Tumalo Creek"
    """
    if not name1 or not name2:
        return 0.0
    
    # Strip potential vendor code prefixes (e.g., "TUMALOC - " from "TUMALOC - Tumalo Creek")
    # BC sometimes stores vendors as "CODE - Name"
    def clean_bc_name(name):
        n = name
        if ' - ' in n:
            # Try removing code prefix
            parts = n.split(' - ', 1)
            if len(parts) == 2 and len(parts[0]) <= 10:  # Short code prefix
                n = parts[1]
        return n
    
    name1_clean = clean_bc_name(name1)
    name2_clean = clean_bc_name(name2)
    
    tokens1 = set(normalize_vendor_name(name1_clean).split())
    tokens2 = set(normalize_vendor_name(name2_clean).split())
    
    if not tokens1 or not tokens2:
        return 0.0
    
    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    
    base_score = len(intersection) / len(union)
    
    # Also try matching original names (in case the code IS the match)
    orig_tokens1 = set(normalize_vendor_name(name1).split())
    orig_tokens2 = set(normalize_vendor_name(name2).split())
    orig_intersection = orig_tokens1 & orig_tokens2
    orig_union = orig_tokens1 | orig_tokens2
    orig_score = len(orig_intersection) / len(orig_union) if orig_union else 0
    
    # Return the better of the two scores
    return max(base_score, orig_score)

# ==================== BC MATCHING SERVICE ====================

async def match_vendor_in_bc(
    vendor_name: str,
    strategies: List[str],
    threshold: float,
    token: str,
    company_id: str
) -> dict:
    """
    Multi-strategy vendor matching against BC.
    Uses server-side filtering for efficient matching.
    Returns candidates and best match.
    """
    result = {
        "matched": False,
        "match_method": None,
        "selected_vendor": None,
        "vendor_candidates": [],
        "score": 0.0
    }
    
    if not vendor_name:
        return result
    
    normalized_input = normalize_vendor_name(vendor_name)
    
    # Extract key search terms for server-side filtering
    # Use the longest word (likely the most distinctive) for filtering
    search_terms = [w for w in normalized_input.split() if len(w) >= 3]
    primary_search_term = max(search_terms, key=len) if search_terms else None
    
    async with httpx.AsyncClient(timeout=30.0) as c:
        vendors = []
        
        # Strategy 1: Try server-side search with contains() filter
        if primary_search_term and len(primary_search_term) >= 4:
            # Use OData $filter to narrow down results server-side
            filter_query = f"contains(displayName, '{primary_search_term}')"
            resp = await c.get(
                f"https://api.businesscentral.dynamics.com/v2.0/{config.TENANT_ID}/{config.BC_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors",
                headers={"Authorization": f"Bearer {token}"},
                params={"$select": "id,number,displayName", "$filter": filter_query, "$top": "100"}
            )
            
            if resp.status_code == 200:
                vendors = resp.json().get("value", [])
                logger.info("BC vendor search for '%s' returned %d candidates", primary_search_term, len(vendors))
        
        # Strategy 2: If no results from filtered search, fall back to broader fetch
        if not vendors:
            resp = await c.get(
                f"https://api.businesscentral.dynamics.com/v2.0/{config.TENANT_ID}/{config.BC_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors",
                headers={"Authorization": f"Bearer {token}"},
                params={"$select": "id,number,displayName", "$top": "1000"}
            )
            
            if resp.status_code != 200:
                return result
            
            vendors = resp.json().get("value", [])
        
        # Check alias map first (case-insensitive)
        if "alias" in strategies:
            # Try exact match, then lowercase, then normalized
            alias_target = (
                VENDOR_ALIAS_MAP.get(vendor_name) or 
                VENDOR_ALIAS_MAP.get(vendor_name.lower()) or 
                VENDOR_ALIAS_MAP.get(normalized_input)
            )
            if alias_target:
                # alias_target is the vendor_name or vendor_no from the alias
                for v in vendors:
                    v_display = v.get("displayName", "")
                    v_number = v.get("number", "")
                    # Match against vendor name or number
                    if (v_display.lower() == alias_target.lower() or 
                        v_number.lower() == alias_target.lower()):
                        result["matched"] = True
                        result["match_method"] = "alias"
                        result["selected_vendor"] = v
                        result["score"] = 1.0
                        return result
        
        # Try each strategy in order
        candidates = []
        
        for vendor in vendors:
            vendor_display = vendor.get("displayName", "")
            vendor_number = vendor.get("number", "")
            
            # Exact match on number
            if "exact_no" in strategies:
                if vendor_number.lower() == vendor_name.lower():
                    result["matched"] = True
                    result["match_method"] = "exact_no"
                    result["selected_vendor"] = vendor
                    result["score"] = 1.0
                    return result
            
            # Exact match on name
            if "exact_name" in strategies:
                if vendor_display.lower() == vendor_name.lower():
                    result["matched"] = True
                    result["match_method"] = "exact_name"
                    result["selected_vendor"] = vendor
                    result["score"] = 1.0
                    return result
            
            # Normalized match
            if "normalized" in strategies:
                normalized_bc = normalize_vendor_name(vendor_display)
                if normalized_input and normalized_bc == normalized_input:
                    result["matched"] = True
                    result["match_method"] = "normalized"
                    result["selected_vendor"] = vendor
                    result["score"] = 0.95
                    return result
            
            # Fuzzy match - collect all candidates
            if "fuzzy" in strategies:
                score = calculate_fuzzy_score(vendor_name, vendor_display)
                if score > 0.3:  # Minimum threshold for candidate list
                    candidates.append({
                        "vendor": vendor,
                        "score": score,
                        "display_name": vendor_display,
                        "vendor_id": vendor.get("id")
                    })
        
        # Sort candidates by score
        candidates.sort(key=lambda x: x["score"], reverse=True)
        result["vendor_candidates"] = candidates[:5]  # Top 5
        
        # Check if best fuzzy match meets threshold
        if candidates and candidates[0]["score"] >= threshold:
            result["matched"] = True
            result["match_method"] = "fuzzy"
            result["selected_vendor"] = candidates[0]["vendor"]
            result["score"] = candidates[0]["score"]
        elif candidates:
            # Have candidates but below threshold - needs review
            result["matched"] = False
            result["match_method"] = "fuzzy_candidates"
            result["score"] = candidates[0]["score"] if candidates else 0
    
    return result

async def match_customer_in_bc(
    customer_name: str,
    strategies: List[str],
    threshold: float,
    token: str,
    company_id: str
) -> dict:
    """
    Multi-strategy customer matching against BC.
    Similar to vendor matching but for customers.
    """
    result = {
        "matched": False,
        "match_method": None,
        "selected_customer": None,
        "customer_candidates": [],
        "score": 0.0
    }
    
    if not customer_name:
        return result
    
    normalized_input = normalize_vendor_name(customer_name)
    
    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.get(
            f"https://api.businesscentral.dynamics.com/v2.0/{config.TENANT_ID}/{config.BC_ENVIRONMENT}/api/v2.0/companies({company_id})/customers",
            headers={"Authorization": f"Bearer {token}"},
            params={"$select": "id,number,displayName", "$top": "500"}
        )
        
        if resp.status_code != 200:
            return result
        
        customers = resp.json().get("value", [])
        candidates = []
        
        for customer in customers:
            customer_display = customer.get("displayName", "")
            customer_number = customer.get("number", "")
            
            # Exact match on number
            if "exact_no" in strategies and customer_number.lower() == customer_name.lower():
                result["matched"] = True
                result["match_method"] = "exact_no"
                result["selected_customer"] = customer
                result["score"] = 1.0
                return result
            
            # Exact match on name
            if "exact_name" in strategies and customer_display.lower() == customer_name.lower():
                result["matched"] = True
                result["match_method"] = "exact_name"
                result["selected_customer"] = customer
                result["score"] = 1.0
                return result
            
            # Normalized match
            if "normalized" in strategies:
                normalized_bc = normalize_vendor_name(customer_display)
                if normalized_input and normalized_bc == normalized_input:
                    result["matched"] = True
                    result["match_method"] = "normalized"
                    result["selected_customer"] = customer
                    result["score"] = 0.95
                    return result
            
            # Fuzzy match
            if "fuzzy" in strategies:
                score = calculate_fuzzy_score(customer_name, customer_display)
                if score > 0.3:
                    candidates.append({
                        "customer": customer,
                        "score": score,
                        "display_name": customer_display,
                        "customer_id": customer.get("id")
                    })
        
        candidates.sort(key=lambda x: x["score"], reverse=True)
        result["customer_candidates"] = candidates[:5]
        
        if candidates and candidates[0]["score"] >= threshold:
            result["matched"] = True
            result["match_method"] = "fuzzy"
            result["selected_customer"] = candidates[0]["customer"]
            result["score"] = candidates[0]["score"]
        elif candidates:
            result["matched"] = False
            result["match_method"] = "fuzzy_candidates"
            result["score"] = candidates[0]["score"] if candidates else 0
    
    return result

async def validate_bc_match(job_type: str, extracted_fields: dict, job_config: dict) -> dict:
    """
    Validate extracted data against Business Central records.
    Returns structured validation results with candidates for review.
    
    match_method values: exact_no, exact_name, normalized, alias, fuzzy, manual, none
    """
    # Normalize fields first
    normalized_fields = normalize_extracted_fields(extracted_fields)
    
    validation_results = {
        "all_passed": True,
        "checks": [],
        "warnings": [],
        "bc_record_id": None,
        "bc_record_info": None,
        "vendor_candidates": [],
        "customer_candidates": [],
        "normalized_fields": normalized_fields,
        "match_method": "none",  # Top-level match method for tracking
        "match_score": 0.0,
        # Phase 7 extraction quality metrics
        "extraction_quality": {
            "vendor_extracted": bool(normalized_fields.get("vendor")),
            "invoice_number_extracted": bool(normalized_fields.get("invoice_number")),
            "amount_extracted": normalized_fields.get("amount") is not None,
            "po_detected": bool(normalized_fields.get("po_number")),
            "due_date_extracted": bool(normalized_fields.get("due_date")),
            "completeness_score": 0.0,  # Will be calculated
            "ready_for_draft_candidate": False
        }
    }
    
    # Calculate extraction completeness score - use job config required fields
    required_fields = job_config.get("required_extractions", ["vendor", "invoice_number", "amount"])
    optional_fields = job_config.get("optional_extractions", ["po_number", "due_date"])
    
    # Count how many required/optional fields were extracted
    required_count = sum(1 for f in required_fields if normalized_fields.get(f) or extracted_fields.get(f))
    optional_count = sum(1 for f in optional_fields if normalized_fields.get(f) or extracted_fields.get(f))
    
    # Completeness: required fields worth 80%, optional worth 20%
    if required_fields:
        req_score = (required_count / len(required_fields)) * 0.8
    else:
        req_score = 0.8  # No required fields = full required score
    
    if optional_fields:
        opt_score = (optional_count / len(optional_fields)) * 0.2
    else:
        opt_score = 0.2  # No optional fields = full optional score
    
    completeness = req_score + opt_score
    validation_results["extraction_quality"]["completeness_score"] = round(completeness, 2)
    validation_results["extraction_quality"]["required_fields"] = required_fields
    validation_results["extraction_quality"]["required_extracted"] = required_count
    validation_results["extraction_quality"]["optional_fields"] = optional_fields
    validation_results["extraction_quality"]["optional_extracted"] = optional_count
    
    # Ready for draft candidate if all required fields extracted
    validation_results["extraction_quality"]["ready_for_draft_candidate"] = required_count == len(required_fields) if required_fields else True
    
    if config.DEMO_MODE or not config.BC_CLIENT_ID:
        validation_results["checks"].append({
            "check_name": "demo_mode",
            "passed": True,
            "details": "Running in demo mode - validation simulated",
            "required": False
        })
        return validation_results
    
    try:
        token = await get_bc_token()
        companies = await get_bc_companies()
        if not companies:
            validation_results["all_passed"] = False
            validation_results["checks"].append({
                "check_name": "bc_connection",
                "passed": False,
                "details": "No BC companies found",
                "required": True
            })
            return validation_results
        
        company_id = companies[0]["id"]
        
        # Get matching configuration
        match_strategies = job_config.get("vendor_match_strategies", ["exact_no", "exact_name", "normalized", "fuzzy"])
        match_threshold = job_config.get("vendor_match_threshold", 0.80)
        po_mode = job_config.get("po_validation_mode", "PO_IF_PRESENT")
        
        async with httpx.AsyncClient(timeout=30.0) as c:
            # Vendor match for AP_Invoice, Remittance
            if job_type in ("AP_Invoice", "Remittance"):
                vendor_name = normalized_fields.get("vendor") or extracted_fields.get("vendor", "")
                if vendor_name:
                    vendor_result = await match_vendor_in_bc(
                        vendor_name, match_strategies, match_threshold, token, company_id
                    )
                    
                    validation_results["vendor_candidates"] = vendor_result.get("vendor_candidates", [])
                    
                    if vendor_result["matched"]:
                        # Set top-level match method for tracking
                        validation_results["match_method"] = vendor_result["match_method"]
                        validation_results["match_score"] = vendor_result["score"]
                        
                        validation_results["checks"].append({
                            "check_name": "vendor_match",
                            "passed": True,
                            "details": f"Found vendor via {vendor_result['match_method']}: {vendor_result['selected_vendor'].get('displayName')} (score: {vendor_result['score']:.0%})",
                            "required": True,
                            "match_method": vendor_result["match_method"],
                            "score": vendor_result["score"]
                        })
                        validation_results["bc_record_id"] = vendor_result["selected_vendor"].get("id")
                        validation_results["bc_record_info"] = vendor_result["selected_vendor"]
                    else:
                        validation_results["all_passed"] = False
                        validation_results["match_method"] = "none"
                        details = f"No vendor found matching '{vendor_name}'"
                        if vendor_result["vendor_candidates"]:
                            top_candidate = vendor_result["vendor_candidates"][0]
                            details += f". Best candidate: {top_candidate['display_name']} ({top_candidate['score']:.0%})"
                        
                        validation_results["checks"].append({
                            "check_name": "vendor_match",
                            "passed": False,
                            "details": details,
                            "required": True,
                            "candidates_available": len(vendor_result["vendor_candidates"]) > 0
                        })
                
                # PO validation based on mode
                po_number = normalized_fields.get("po_number") or extracted_fields.get("po_number", "")
                
                if po_mode == "PO_REQUIRED":
                    # PO must exist and match
                    if not po_number:
                        validation_results["all_passed"] = False
                        validation_results["checks"].append({
                            "check_name": "po_validation",
                            "passed": False,
                            "details": "PO number required but not extracted from document",
                            "required": True
                        })
                    else:
                        await _validate_po(c, token, company_id, po_number, validation_results, required=True)
                
                elif po_mode == "PO_IF_PRESENT":
                    # Validate only if PO was extracted
                    if po_number:
                        await _validate_po(c, token, company_id, po_number, validation_results, required=False)
                    else:
                        validation_results["warnings"].append({
                            "check_name": "po_not_present",
                            "details": "No PO number extracted - skipping PO validation"
                        })
                
                # else PO_NOT_REQUIRED - skip PO validation entirely
                
                # Duplicate invoice check
                invoice_number = normalized_fields.get("invoice_number") or extracted_fields.get("invoice_number")
                if invoice_number:
                    resp = await c.get(
                        f"https://api.businesscentral.dynamics.com/v2.0/{config.TENANT_ID}/{config.BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$filter": f"vendorInvoiceNumber eq '{invoice_number}'"}
                    )
                    if resp.status_code == 200:
                        existing = resp.json().get("value", [])
                        if existing and not job_config.get("allow_duplicate_check_override"):
                            validation_results["all_passed"] = False
                            validation_results["checks"].append({
                                "check_name": "duplicate_check",
                                "passed": False,
                                "details": f"Duplicate invoice found: {invoice_number}",
                                "required": True,
                                "existing_invoice_id": existing[0].get("id")
                            })
                        else:
                            validation_results["checks"].append({
                                "check_name": "duplicate_check",
                                "passed": True,
                                "details": "No duplicate invoice found",
                                "required": True
                            })
            
            # Customer match for Sales_PO, AR_Invoice
            elif job_type in ("Sales_PO", "AR_Invoice"):
                customer_name = normalized_fields.get("customer") or extracted_fields.get("customer", "")
                if customer_name:
                    customer_result = await match_customer_in_bc(
                        customer_name, match_strategies, match_threshold, token, company_id
                    )
                    
                    validation_results["customer_candidates"] = customer_result.get("customer_candidates", [])
                    
                    if customer_result["matched"]:
                        # Set top-level match method for tracking
                        validation_results["match_method"] = customer_result["match_method"]
                        validation_results["match_score"] = customer_result["score"]
                        
                        validation_results["checks"].append({
                            "check_name": "customer_match",
                            "passed": True,
                            "details": f"Found customer via {customer_result['match_method']}: {customer_result['selected_customer'].get('displayName')} (score: {customer_result['score']:.0%})",
                            "required": True,
                            "match_method": customer_result["match_method"],
                            "score": customer_result["score"]
                        })
                        validation_results["bc_record_id"] = customer_result["selected_customer"].get("id")
                        validation_results["bc_record_info"] = customer_result["selected_customer"]
                    else:
                        validation_results["all_passed"] = False
                        validation_results["match_method"] = "none"
                        details = f"No customer found matching '{customer_name}'"
                        if customer_result["customer_candidates"]:
                            top_candidate = customer_result["customer_candidates"][0]
                            details += f". Best candidate: {top_candidate['display_name']} ({top_candidate['score']:.0%})"
                        
                        validation_results["checks"].append({
                            "check_name": "customer_match",
                            "passed": False,
                            "details": details,
                            "required": True,
                            "candidates_available": len(customer_result["customer_candidates"]) > 0
                        })
    
    except Exception as e:
        logger.error("BC validation failed: %s", str(e))
        validation_results["all_passed"] = False
        validation_results["checks"].append({
            "check_name": "bc_error",
            "passed": False,
            "details": f"BC validation error: {str(e)}",
            "required": True
        })
    
    return validation_results

async def _validate_po(c, token: str, company_id: str, po_number: str, validation_results: dict, required: bool):
    """Helper to validate PO number in BC."""
    resp = await c.get(
        f"https://api.businesscentral.dynamics.com/v2.0/{config.TENANT_ID}/{config.BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseOrders",
        headers={"Authorization": f"Bearer {token}"},
        params={"$filter": f"number eq '{po_number}'"}
    )
    if resp.status_code == 200:
        pos = resp.json().get("value", [])
        if pos:
            validation_results["checks"].append({
                "check_name": "po_validation",
                "passed": True,
                "details": f"Found PO: {po_number}",
                "required": required
            })
        else:
            if required:
                validation_results["all_passed"] = False
            validation_results["checks"].append({
                "check_name": "po_validation",
                "passed": False,
                "details": f"PO '{po_number}' not found in BC",
                "required": required
            })
            if not required:
                validation_results["warnings"].append({
                    "check_name": "po_not_found",
                    "details": f"PO '{po_number}' was extracted but not found in BC - not blocking"
                })

# ==================== AUTOMATION DECISION ENGINE ====================

def make_automation_decision(
    job_config: dict,
    ai_confidence: float,
    validation_results: dict
) -> tuple:
    """
    Decision matrix for automation level.
    Returns (decision, reasoning, metadata)
    
    Metadata includes candidates if available for quick resolution.
    """
    automation_level = job_config.get("automation_level", 0)
    link_threshold = job_config.get("min_confidence_to_auto_link", 0.85)
    create_threshold = job_config.get("min_confidence_to_auto_create_draft", 0.95)
    requires_review = job_config.get("requires_human_review_if_exception", True)
    
    metadata = {
        "vendor_candidates": validation_results.get("vendor_candidates", []),
        "customer_candidates": validation_results.get("customer_candidates", []),
        "warnings": validation_results.get("warnings", [])
    }
    
    # Level 0: Manual only
    if automation_level == 0:
        return "manual", "Job type configured for manual processing only", metadata
    
    # Check validation results
    if not validation_results.get("all_passed", False):
        failed_checks = [c["check_name"] for c in validation_results.get("checks", []) if not c["passed"] and c.get("required", True)]
        
        # Check if we have candidates for failed checks (can be resolved with one click)
        has_candidates = (
            len(validation_results.get("vendor_candidates", [])) > 0 or
            len(validation_results.get("customer_candidates", [])) > 0
        )
        
        reason_suffix = ""
        if has_candidates:
            reason_suffix = " (candidates available for quick resolution)"
        
        if requires_review:
            return "needs_review", f"Validation failed: {', '.join(failed_checks)}{reason_suffix}", metadata
        return "manual", f"Validation failed but review not required: {', '.join(failed_checks)}", metadata
    
    # Check warnings (non-blocking issues)
    warning_notes = ""
    if validation_results.get("warnings"):
        warning_notes = f" (with {len(validation_results['warnings'])} warning(s))"
    
    # Check confidence thresholds
    if ai_confidence < link_threshold:
        return "needs_review", f"Confidence {ai_confidence:.2%} below link threshold {link_threshold:.2%}", metadata
    
    # Level 1: Auto-link only
    if automation_level == 1:
        if ai_confidence >= link_threshold:
            return "auto_link", f"Confidence {ai_confidence:.2%} meets link threshold, auto-linking to existing BC record{warning_notes}", metadata
        return "needs_review", f"Confidence {ai_confidence:.2%} below threshold", metadata
    
    # Level 2: Auto-create draft
    if automation_level >= 2:
        if ai_confidence >= create_threshold:
            return "auto_create", f"Confidence {ai_confidence:.2%} meets create threshold, creating draft BC document{warning_notes}", metadata
        elif ai_confidence >= link_threshold:
            return "auto_link", f"Confidence {ai_confidence:.2%} meets link threshold only, auto-linking{warning_notes}", metadata
        return "needs_review", f"Confidence {ai_confidence:.2%} below thresholds", metadata
    
    return "needs_review", "Default fallback to review", metadata

async def _update_standard_workflow_status(
    doc_id: str,
    doc_type: str,
    confidence: float,
    normalized_fields: Dict
):
    """
    Update workflow status for non-AP document types.
    Implements Square9-style workflow for warehouse and sales documents.
    
    Warehouse Workflow (SHIPMENT, RECEIPT):
    - Import -> Classification -> PO Validation -> Location Validation -> Export
    
    Sales Workflow (SALES_ORDER, SALES_INVOICE):
    - Import -> Classification -> Customer Match -> BC Validation -> Export/Create
    """
    from services.square9_workflow import (
        initialize_retry_state, increment_retry, validate_location_code,
        validate_required_fields, determine_square9_stage, Square9Stage,
        reset_retry_counter
    )
    
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        return
    
    now = datetime.now(timezone.utc).isoformat()
    
    # Initialize retry state if not present
    if "retry_count" not in doc:
        retry_state = initialize_retry_state(doc)
        doc.update(retry_state)
        await db.hub_documents.update_one({"id": doc_id}, {"$set": retry_state})
    
    # Step 1: Classification done - move from captured to classified
    if confidence > 0:
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value,
            context={"reason": f"AI classification completed with confidence {confidence:.2f}"}
        )
    else:
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_CLASSIFICATION_FAILED.value,
            context={"reason": "Classification failed or returned Unknown"}
        )
        # Save and return early for failed classification
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "workflow_status": doc.get("workflow_status"),
                "workflow_history": doc.get("workflow_history", []),
                "workflow_status_updated_utc": now,
                "square9_stage": Square9Stage.UNCLASSIFIED.value
            }}
        )
        return
    
    # =============== WAREHOUSE WORKFLOW (Square9-aligned) ===============
    # Follows Square9 diagram exactly:
    # 1. PO Number Is Empty? -> Set WF Status to "Missing PO Number"
    # 2. Invoice Number Is Empty? -> Set WF Status to "Missing Invoice Number" (BOL# for shipping)
    # 3. Document Date Is Empty? -> Set WF Status to "Missing Location"
    # 4. Counter >= 4? -> Delete Document
    # 5. All pass -> Send to SharePoint
    
    if doc_type in [DocType.SHIPMENT.value, DocType.RECEIPT.value, "Shipping_Document", "Warehouse_Document"]:
        
        # Helper function to handle validation failure with retry/delete logic
        async def handle_warehouse_validation_failure(doc, doc_id, field_name, stage, status_label):
            """Handle validation failure - increment retry, delete if max reached"""
            update_dict, should_delete, message = increment_retry(doc, status_label, stage)
            
            if should_delete and update_dict.get("square9_stage") == Square9Stage.DELETED.value:
                # Counter >= 4: DELETE DOCUMENT (Square9 behavior)
                logger.warning("[Warehouse Workflow] Doc %s: MAX RETRIES REACHED - DELETING. Reason: %s", doc_id, status_label)
                await db.hub_documents.delete_one({"id": doc_id})
                # Also delete from workflows collection
                await db.hub_workflows.delete_many({"document_id": doc_id})
                return True  # Document deleted
            else:
                # Counter < 4: Set status and wait for retry
                update_dict["workflow_status"] = "data_correction_pending"
                update_dict["status"] = "NeedsReview"
                update_dict["square9_stage"] = stage
                update_dict["workflow_status_updated_utc"] = now
                await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})
                logger.info("[Warehouse Workflow] Doc %s: %s - %s", doc_id, status_label, message)
                return False  # Document not deleted, needs review
        
        # Extract fields
        po_number = (normalized_fields.get("po_number_clean") or 
                    normalized_fields.get("po_number_raw") or 
                    normalized_fields.get("po_number"))
        
        # For shipping docs, "Invoice Number" = BOL Number
        bol_number = (normalized_fields.get("bol_number") or 
                     normalized_fields.get("tracking_number") or
                     normalized_fields.get("pro_number"))
        
        # Document Date = Ship Date
        document_date = (normalized_fields.get("ship_date") or 
                        normalized_fields.get("document_date") or
                        normalized_fields.get("delivery_date"))
        
        # ===== STEP 1: PO Number Is Empty? =====
        if not po_number or str(po_number).strip() == "":
            deleted = await handle_warehouse_validation_failure(
                doc, doc_id, "po_number", 
                Square9Stage.MISSING_PO.value, 
                "Missing PO Number"
            )
            if deleted:
                return  # Document was deleted
            return  # Needs review
        
        # ===== STEP 2: Invoice Number (BOL#) Is Empty? =====
        if not bol_number or str(bol_number).strip() == "":
            deleted = await handle_warehouse_validation_failure(
                doc, doc_id, "bol_number",
                Square9Stage.MISSING_INVOICE.value,
                "Missing Invoice Number"  # Square9 label (BOL# for shipping docs)
            )
            if deleted:
                return
            return
        
        # ===== STEP 3: Document Date Is Empty? -> "Missing Location" (Square9 quirk) =====
        if not document_date or str(document_date).strip() == "":
            deleted = await handle_warehouse_validation_failure(
                doc, doc_id, "document_date",
                Square9Stage.MISSING_LOCATION.value,  # Square9 uses "Missing Location" for date
                "Missing Location"  # Square9 label
            )
            if deleted:
                return
            return
        
        # ===== ALL VALIDATIONS PASSED - Send to SharePoint =====
        
        # Location code validation (optional, use fallback if missing)
        location_code = normalized_fields.get("location_code") or normalized_fields.get("warehouse")
        is_valid_location, location_msg, resolved_location = validate_location_code(location_code, doc_type)
        
        if not is_valid_location:
            normalized_fields["location_code_resolved"] = resolved_location
            logger.info("[Warehouse Workflow] Doc %s: %s - using fallback: %s", doc_id, location_msg, resolved_location)
        
        # Reset retry counter on success
        reset_update = reset_retry_counter(doc, "Validation passed")
        
        # Advance workflow to exported
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value,
            context={"reason": "Warehouse document validated - PO, BOL, Date all present"}
        )
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_REVIEW_COMPLETE.value,
            context={"reason": "Warehouse validation complete - sending to SharePoint"}
        )
        
        # Mark as completed and archived
        final_update = {
            **reset_update,
            "workflow_status": "exported",
            "status": "Completed",
            "square9_stage": Square9Stage.EXPORTED.value,
            "workflow_history": doc.get("workflow_history", []),
            "workflow_status_updated_utc": now,
            "location_code_resolved": resolved_location if not is_valid_location else location_code,
            "bol_number_extracted": bol_number,
            "po_number_extracted": po_number,
            "document_date_extracted": document_date,
            "archived": True,
            "archived_utc": now
        }
        
        await db.hub_documents.update_one({"id": doc_id}, {"$set": final_update})
        logger.info("[Warehouse Workflow] Doc %s: COMPLETED - PO=%s, BOL=%s, Date=%s, archived to SharePoint", 
                   doc_id, po_number, bol_number, document_date)
        return
    
    # =============== SALES WORKFLOW ===============
    elif doc_type in [DocType.SALES_ORDER.value, DocType.SALES_INVOICE.value, "SalesOrder", "SalesInvoice"]:
        # Step 2: Check Customer
        customer = normalized_fields.get("customer") or normalized_fields.get("customer_raw")
        if not customer:
            update_dict, escalated, message = increment_retry(doc, "Missing Customer", Square9Stage.MISSING_VENDOR.value)
            update_dict["workflow_status"] = "data_correction_pending"
            update_dict["status"] = "NeedsReview"
            update_dict["square9_stage"] = Square9Stage.MISSING_VENDOR.value
            await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})
            logger.info("[Sales Workflow] Doc %s: Missing Customer - %s", doc_id, message)
            return
        
        # Step 3: Check Order/Invoice Number
        order_number = (normalized_fields.get("order_number") or 
                       normalized_fields.get("invoice_number_clean") or
                       normalized_fields.get("customer_po"))
        if not order_number:
            update_dict, escalated, message = increment_retry(doc, "Missing Order/Invoice Number", Square9Stage.MISSING_INVOICE.value)
            update_dict["workflow_status"] = "data_correction_pending"
            update_dict["status"] = "NeedsReview"
            update_dict["square9_stage"] = Square9Stage.MISSING_INVOICE.value
            await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})
            logger.info("[Sales Workflow] Doc %s: Missing Order Number - %s", doc_id, message)
            return
        
        # All sales validations passed - mark as validated
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value,
            context={"reason": "Sales document validated successfully"}
        )
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_REVIEW_COMPLETE.value,
            context={"reason": "Sales validation complete - ready for BC creation"}
        )
        
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "workflow_status": "validated",
                "status": "Validated",
                "square9_stage": Square9Stage.VALID.value,
                "workflow_history": doc.get("workflow_history", []),
                "workflow_status_updated_utc": now,
                "bc_create_ready": True,
                "customer_extracted": customer,
                "order_number_extracted": order_number
            }}
        )
        logger.info("[Sales Workflow] Doc %s: VALIDATED - ready for BC Sales Order creation", doc_id)
        
        # AUTO-CREATE: Attempt to create BC Sales Order
        if AUTO_CREATE_SALES_ORDER_ENABLED:
            try:
                # Refresh document after validation update
                updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
                if updated_doc:
                    bc_service = get_bc_service()
                    auto_create_result = await attempt_auto_create_sales_order(doc_id, updated_doc, db, bc_service)
                    
                    if auto_create_result.eligible:
                        if auto_create_result.success:
                            logger.info("AUTO-CREATE: Document %s auto-created as BC Sales Order %s", 
                                       doc_id, auto_create_result.bc_document_number)
                        else:
                            logger.warning("AUTO-CREATE: Document %s eligible but failed: %s", 
                                          doc_id, auto_create_result.error)
                    else:
                        logger.debug("AUTO-CREATE: Document %s not eligible: %s", 
                                    doc_id, auto_create_result.reason)
            except Exception as e:
                logger.error("AUTO-CREATE: Exception for %s: %s", doc_id, str(e))
        
        return
    
    # =============== DEFAULT/OTHER WORKFLOW ===============
    # Step 2: Check extraction quality
    vendor = normalized_fields.get("vendor_normalized") or normalized_fields.get("vendor_raw")
    invoice_number = normalized_fields.get("invoice_number_clean")
    amount = normalized_fields.get("amount_float")
    
    # For non-AP types, we're more lenient on required fields
    has_basic_data = any([vendor, invoice_number, amount is not None])
    
    if not has_basic_data or confidence < 0.3:
        # Low confidence or no data - needs review
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_FAILED.value,
            context={
                "reason": "Extraction incomplete or very low confidence",
                "metadata": {
                    "has_vendor": bool(vendor),
                    "has_invoice_number": bool(invoice_number),
                    "has_amount": amount is not None,
                    "confidence": confidence
                }
            }
        )
    else:
        # Extraction succeeded
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value,
            context={"reason": "Extraction completed successfully"}
        )
        
        # For standard workflow types (not AP), skip vendor/BC validation
        # Move directly to ready_for_approval or auto-approve based on doc_type
        if doc_type in [DocType.STATEMENT.value, DocType.REMINDER.value, 
                        DocType.FINANCE_CHARGE_MEMO.value, DocType.QUALITY_DOC.value,
                        DocType.OTHER.value]:
            # Simplified types can go directly to extracted -> exportable
            pass  # Stay at extracted, can be approved/exported manually
        else:
            # Standard business docs (Sales, PO, Credit Memo) advance to ready_for_approval
            WorkflowEngine.advance_workflow(
                doc,
                WorkflowEvent.ON_REVIEW_COMPLETE.value,
                context={"reason": f"Automatic review complete for {doc_type}"}
            )
    
    # Save workflow updates
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": doc.get("workflow_status"),
            "workflow_history": doc.get("workflow_history", []),
            "workflow_status_updated_utc": now,
            "square9_stage": determine_square9_stage(doc)
        }}
    )


async def _update_ap_workflow_status(
    doc_id: str,
    confidence: float,
    normalized_fields: Dict,
    vendor_alias_result: Dict,
    validation_results: Dict,
    ap_validation: Dict
):
    """
    Update workflow status for AP_Invoice documents based on processing results.
    This implements the Square9-style workflow routing.
    """
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        return
    
    now = datetime.now(timezone.utc).isoformat()
    workflow_updates = []
    
    # Step 1: Classification done - move from captured to classified
    WorkflowEngine.advance_workflow(
        doc,
        WorkflowEvent.ON_CLASSIFICATION_SUCCESS.value,
        context={"reason": f"AI classification completed with confidence {confidence:.2f}"}
    )
    workflow_updates.append("classified")
    
    # Step 2: Check extraction quality
    vendor = normalized_fields.get("vendor_normalized")
    invoice_number = normalized_fields.get("invoice_number_clean")
    amount = normalized_fields.get("amount_float")
    
    if not all([vendor, invoice_number, amount is not None]) or confidence < 0.5:
        # Low confidence or missing required fields - needs data correction
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_LOW_CONFIDENCE.value,
            context={
                "reason": "Extraction incomplete or low confidence",
                "metadata": {
                    "has_vendor": bool(vendor),
                    "has_invoice_number": bool(invoice_number),
                    "has_amount": amount is not None,
                    "confidence": confidence
                }
            }
        )
        workflow_updates.append("data_correction_pending")
    else:
        # Extraction succeeded
        WorkflowEngine.advance_workflow(
            doc,
            WorkflowEvent.ON_EXTRACTION_SUCCESS.value,
            context={"reason": "Extraction completed successfully"}
        )
        workflow_updates.append("extracted")
        
        # Step 3: Check vendor match
        vendor_canonical = vendor_alias_result.get("vendor_canonical")
        vendor_match_method = vendor_alias_result.get("vendor_match_method")
        
        if not vendor_canonical or vendor_match_method == "none":
            # Vendor not matched - needs manual resolution
            WorkflowEngine.advance_workflow(
                doc,
                WorkflowEvent.ON_VENDOR_MISSING.value,
                context={
                    "reason": "Vendor could not be matched automatically",
                    "metadata": {"vendor_raw": normalized_fields.get("vendor_raw")}
                }
            )
            workflow_updates.append("vendor_pending")
        else:
            # Vendor matched
            WorkflowEngine.advance_workflow(
                doc,
                WorkflowEvent.ON_VENDOR_MATCHED.value,
                context={
                    "reason": f"Vendor matched via {vendor_match_method}",
                    "metadata": {
                        "vendor_canonical": vendor_canonical,
                        "match_method": vendor_match_method
                    }
                }
            )
            workflow_updates.append("bc_validation_pending")
            
            # Step 4: Check BC validation
            all_passed = validation_results.get("all_passed", False)
            draft_candidate = ap_validation.get("draft_candidate", False)
            
            if all_passed or draft_candidate:
                # BC validation passed - ready for approval
                WorkflowEngine.advance_workflow(
                    doc,
                    WorkflowEvent.ON_BC_VALID.value,
                    context={
                        "reason": "BC validation passed",
                        "metadata": {
                            "all_passed": all_passed,
                            "draft_candidate": draft_candidate
                        }
                    }
                )
                workflow_updates.append("ready_for_approval")
            else:
                # BC validation failed
                validation_errors = ap_validation.get("validation_errors", [])
                WorkflowEngine.advance_workflow(
                    doc,
                    WorkflowEvent.ON_BC_INVALID.value,
                    context={
                        "reason": "BC validation failed",
                        "metadata": {"validation_errors": validation_errors}
                    }
                )
                workflow_updates.append("bc_validation_failed")
    
    # Save workflow updates
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "workflow_status": doc.get("workflow_status"),
            "workflow_history": doc.get("workflow_history", []),
            "workflow_status_updated_utc": now
        }}
    )
    
    logger.info("[Workflow] Document %s workflow updated: %s", doc_id, " -> ".join(workflow_updates))


async def classify_document_type(
    document: Dict,
    extracted_fields: Dict,
    suggested_type: str,
    confidence: float,
    metadata: Optional[Dict] = None
) -> Dict:
    """
    Deterministic-first document type classification pipeline.
    
    Step 1: Run deterministic rules (Zetadocs codes, Square9 workflows, mailbox category)
    Step 2: If doc_type is not OTHER, keep it and skip AI
    Step 3: If doc_type is OTHER and AI classification is enabled, try AI
    Step 4: Apply AI result if confidence >= threshold
    
    Args:
        document: The document dict
        extracted_fields: Fields extracted from the document
        suggested_type: Legacy suggested_job_type from classification
        confidence: Legacy AI classification confidence
        metadata: Additional metadata (zetadocs_set, square9_workflow, mailbox_category)
    
    Returns:
        Dict with doc_type, category, ai_classification (if used)
    """
    metadata = metadata or {}
    result = {
        "doc_type": DocType.OTHER.value,
        "category": "Other",
        "ai_classification": None,
        "classification_method": "default"
    }
    
    # Step 1a: Check Zetadocs set code
    zetadocs_set = metadata.get("zetadocs_set") or document.get("zetadocs_set_code")
    if zetadocs_set:
        doc_type, capture_channel = DocumentClassifier.classify_from_zetadocs_set(zetadocs_set)
        if doc_type != DocType.OTHER:
            result["doc_type"] = doc_type.value
            result["classification_method"] = f"zetadocs:{zetadocs_set}"
            logger.info("Deterministic classification: Zetadocs set %s -> %s", zetadocs_set, doc_type.value)
    
    # Step 1b: Check Square9 workflow name
    if result["doc_type"] == DocType.OTHER.value:
        square9_workflow = metadata.get("square9_workflow") or document.get("square9_workflow_name")
        if square9_workflow:
            doc_type = DocumentClassifier.classify_from_square9_workflow(square9_workflow)
            if doc_type != DocType.OTHER:
                result["doc_type"] = doc_type.value
                result["classification_method"] = f"square9:{square9_workflow}"
                logger.info("Deterministic classification: Square9 workflow %s -> %s", square9_workflow, doc_type.value)
    
    # Step 1c: Check mailbox category (from email polling config)
    if result["doc_type"] == DocType.OTHER.value:
        mailbox_category = metadata.get("mailbox_category") or document.get("mailbox_category")
        if mailbox_category:
            doc_type = DocumentClassifier.classify_from_mailbox_category(mailbox_category)
            if doc_type != DocType.OTHER:
                result["doc_type"] = doc_type.value
                result["classification_method"] = f"mailbox:{mailbox_category}"
                logger.info("Deterministic classification: Mailbox category %s -> %s", mailbox_category, doc_type.value)
    
    # Step 1d: Check legacy suggested_job_type from existing AI extraction
    if result["doc_type"] == DocType.OTHER.value and suggested_type and suggested_type != "Unknown":
        doc_type = DocumentClassifier.classify_from_ai_result(suggested_type)
        if doc_type != DocType.OTHER:
            result["doc_type"] = doc_type.value
            result["classification_method"] = f"legacy_ai:{suggested_type}"
            logger.info("Classification from legacy AI: %s -> %s", suggested_type, doc_type.value)
    
    # Step 2: If we have a definitive type, set category and return
    if result["doc_type"] != DocType.OTHER.value:
        result["category"] = _get_category_for_doc_type(result["doc_type"])
        return result
    
    # Step 3: doc_type is still OTHER - try AI classification if enabled
    if AI_CLASSIFICATION_ENABLED and os.environ.get("EMERGENT_LLM_KEY"):
        logger.info("Deterministic classification returned OTHER, invoking AI classifier for doc %s", document.get("id"))
        
        try:
            ai_result = await classify_doc_type_with_ai(
                document=document,
                extracted_text=extracted_fields.get("raw_text"),
                metadata=metadata
            )
            
            # Always record the AI classification attempt
            result["ai_classification"] = ai_result.to_dict()
            
            # Step 4: Apply if confidence meets threshold
            if ai_result.should_accept(AI_CLASSIFICATION_THRESHOLD):
                result["doc_type"] = ai_result.proposed_doc_type
                result["classification_method"] = f"ai:{ai_result.model_name}:{ai_result.confidence:.2f}"
                logger.info(
                    "AI classification accepted for doc %s: %s (confidence: %.2f)",
                    document.get("id"), ai_result.proposed_doc_type, ai_result.confidence
                )
            else:
                logger.info(
                    "AI classification NOT accepted for doc %s: %s (confidence: %.2f, threshold: %.2f)",
                    document.get("id"), ai_result.proposed_doc_type, ai_result.confidence, AI_CLASSIFICATION_THRESHOLD
                )
        except Exception as e:
            logger.error("AI classification failed for doc %s: %s", document.get("id"), str(e))
            result["ai_classification"] = {
                "error": str(e),
                "timestamp": datetime.now(timezone.utc).isoformat()
            }
    
    # Final category assignment
    result["category"] = _get_category_for_doc_type(result["doc_type"])
    
    return result


def _get_category_for_doc_type(doc_type: str) -> str:
    """Map doc_type to category for backward compatibility."""
    if doc_type == DocType.AP_INVOICE.value:
        return "AP"
    elif doc_type in [DocType.SALES_INVOICE.value, DocType.SALES_CREDIT_MEMO.value]:
        return "Sales"
    elif doc_type == DocType.PURCHASE_ORDER.value:
        return "Purchase"
    else:
        return "Other"


async def _internal_intake_document(
    file_content: bytes,
    filename: str,
    content_type: str,
    source: str = "email_poll",
    sender: Optional[str] = None,
    subject: Optional[str] = None,
    email_id: Optional[str] = None
) -> dict:
    """
    Internal function to process document intake from email polling.
    Similar to intake_document but accepts raw bytes instead of UploadFile.
    """
    computed_hash = hashlib.sha256(file_content).hexdigest()
    doc_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    
    # Store file locally
    file_path = UPLOAD_DIR / doc_id
    file_path.write_bytes(file_content)
    
    # Apply pilot capture channel if pilot mode is enabled
    base_capture_channel = CaptureChannel.EMAIL.value if "email" in source.lower() else CaptureChannel.UPLOAD.value
    capture_channel = get_pilot_capture_channel(base_capture_channel) if PILOT_MODE_ENABLED else base_capture_channel
    
    # Create document record with workflow tracking
    doc = {
        "id": doc_id,
        "source": source,
        "file_name": filename,
        "sha256_hash": computed_hash,
        "file_size": len(file_content),
        "content_type": content_type,
        "email_sender": sender,
        "email_subject": subject,
        "email_id": email_id,
        "email_received_utc": now,
        "sharepoint_drive_id": None,
        "sharepoint_item_id": None,
        "sharepoint_web_url": None,
        "sharepoint_share_link_url": None,
        "document_type": None,
        "category": None,
        "suggested_job_type": None,
        "ai_confidence": None,
        "extracted_fields": None,
        "validation_results": None,
        "automation_decision": None,
        "bc_record_type": None,
        "bc_company_id": None,
        "bc_record_id": None,
        "bc_document_no": None,
        "status": "Received",
        # Workflow tracking fields
        "workflow_status": WorkflowStatus.CAPTURED.value,
        "workflow_history": [{
            "timestamp": now,
            "from_status": None,
            "to_status": WorkflowStatus.CAPTURED.value,
            "event": WorkflowEvent.ON_CAPTURE.value,
            "actor": "system",
            "reason": "Document captured from " + source,
            "metadata": {"source": source, "sender": sender}
        }],
        "workflow_status_updated_utc": now,
        "created_utc": now,
        "updated_utc": now,
        "last_error": None,
        # Pilot metadata (added if pilot mode enabled)
        **get_pilot_metadata()
    }
    await db.hub_documents.insert_one(doc)
    
    # Run AI extraction (for field extraction, not doc_type classification)
    logger.info("Running AI field extraction for document %s", doc_id)
    classification = await classify_document_with_ai(str(file_path), filename)
    
    suggested_type = classification.get("suggested_job_type", "Unknown")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})
    
    # Deterministic-first document type classification
    # Step 1: Try deterministic rules (Zetadocs, Square9, mailbox category)
    # Step 2: If still OTHER, try AI classification if enabled
    classification_result = await classify_document_type(
        document=doc,
        extracted_fields=extracted_fields,
        suggested_type=suggested_type,
        confidence=confidence,
        metadata={
            "mailbox_category": doc.get("mailbox_category"),
            "zetadocs_set": doc.get("zetadocs_set_code"),
            "square9_workflow": doc.get("square9_workflow_name")
        }
    )
    
    doc_type_value = classification_result["doc_type"]
    category = classification_result["category"]
    ai_classification_audit = classification_result.get("ai_classification")
    classification_method = classification_result.get("classification_method", "unknown")
    
    logger.info(
        "Document %s classified as %s (category: %s, method: %s)",
        doc_id, doc_type_value, category, classification_method
    )
    
    # Phase 7: Compute normalized fields (flat, stored on document)
    normalized_fields = compute_ap_normalized_fields(extracted_fields)
    
    # Phase 7: Vendor alias lookup
    vendor_alias_result = await lookup_vendor_alias(normalized_fields.get("vendor_normalized"))

    # Phase 8: Spiro context enrichment (Shadow Mode - logs only, doesn't affect decisions)
    spiro_context_dict = None
    try:
        from services.spiro import get_spiro_context_for_document
        from services.spiro.spiro_client import is_spiro_enabled
        
        if is_spiro_enabled():
            doc_metadata = {
                "vendor_raw": normalized_fields.get("vendor_raw"),
                "vendor_normalized": normalized_fields.get("vendor_normalized"),
                "extracted_fields": extracted_fields
            }
            spiro_context = await get_spiro_context_for_document(doc_metadata)
            spiro_context_dict = spiro_context.to_dict()
            
            if spiro_context.matched_companies:
                best = spiro_context.matched_companies[0]
                logger.info("Spiro match for %s: %s (%.2f, ISR: %s)", 
                           doc_id[:8], best.name, best.match_score, best.data.get("assigned_isr"))
    except Exception as e:
        logger.debug("Spiro context skipped: %s", str(e))

    
    # Phase 7: Duplicate check
    duplicate_result = await check_duplicate_document(
        vendor_normalized=normalized_fields.get("vendor_normalized"),
        vendor_canonical=vendor_alias_result.get("vendor_canonical"),
        invoice_number_clean=normalized_fields.get("invoice_number_clean"),
        current_doc_id=doc_id
    )
    
    # Phase 7: Compute validation errors/warnings and draft_candidate
    ap_validation = compute_ap_validation(
        document_type=suggested_type,
        vendor_normalized=normalized_fields.get("vendor_normalized"),
        invoice_number_clean=normalized_fields.get("invoice_number_clean"),
        amount_float=normalized_fields.get("amount_float"),
        po_number_clean=normalized_fields.get("po_number_clean"),
        ai_confidence=confidence,
        possible_duplicate=duplicate_result.get("possible_duplicate", False)
    )
    
    # Get job type config
    job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])
    
    # Run BC validation (existing logic)
    validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)
    
    # Make automation decision
    decision, reasoning, decision_metadata = make_automation_decision(job_configs, confidence, validation_results)
    
    # Upload to SharePoint
    folder = job_configs.get("sharepoint_folder", "Incoming")
    sp_result = None
    share_link = None
    sp_error = None
    
    try:
        sp_result = await upload_to_sharepoint(file_content, filename, folder)
        share_link = await create_sharing_link(sp_result["drive_id"], sp_result["item_id"])
        logger.info("Document %s stored in SharePoint: %s", doc_id, sp_result.get("web_url"))
    except Exception as e:
        sp_error = str(e)
        logger.error("SharePoint upload failed for document %s: %s", doc_id, sp_error)
    
    # Phase 7: Determine status for AP_Invoice using new logic
    if suggested_type in ("AP_Invoice", "AP Invoice"):
        # All AP_Invoice documents stay in NeedsReview during Phase 7
        # The draft_candidate flag indicates readiness
        final_status = "NeedsReview"
    else:
        # Non-AP documents use existing logic
        if decision == "auto_link" and validation_results.get("all_passed"):
            final_status = "ReadyToLink"
        elif decision in ("needs_review", "manual"):
            final_status = "NeedsReview"
        elif decision == "exception":
            final_status = "Exception"
        elif sp_result:
            final_status = "StoredInSP"
        else:
            final_status = "Classified"
    
    # Get the category from job type config (fallback to our computed category)
    doc_category = category if category != "Other" else job_configs.get("category", category)
    
    update_data = {
        "suggested_job_type": suggested_type,
        "document_type": suggested_type,
        "category": doc_category,
        # Document classification fields
        "doc_type": doc_type_value,
        "source_system": SourceSystem.GPI_HUB_NATIVE.value,
        "capture_channel": capture_channel,  # Use pilot-aware channel
        "classification_method": classification_method,
        "ai_confidence": confidence,
        "extracted_fields": extracted_fields,
        # Phase 7: Flat normalized fields on document
        "vendor_raw": normalized_fields.get("vendor_raw"),
        "vendor_normalized": normalized_fields.get("vendor_normalized"),
        "invoice_number_raw": normalized_fields.get("invoice_number_raw"),
        "invoice_number_clean": normalized_fields.get("invoice_number_clean"),
        "amount_raw": normalized_fields.get("amount_raw"),
        "amount_float": normalized_fields.get("amount_float"),
        "due_date_raw": normalized_fields.get("due_date_raw"),
        "due_date_iso": normalized_fields.get("due_date_iso"),
        "po_number_raw": normalized_fields.get("po_number_raw"),
        "po_number_clean": normalized_fields.get("po_number_clean"),
        # Phase 8: Invoice date and line items for automatic BC posting
        "invoice_date": normalized_fields.get("invoice_date"),
        "invoice_date_raw": normalized_fields.get("invoice_date_raw"),
        "line_items": normalized_fields.get("line_items", []),
        # Phase 7: Vendor alias results
        "vendor_canonical": vendor_alias_result.get("vendor_canonical"),
        "vendor_match_method": vendor_alias_result.get("vendor_match_method"),
        # Phase 7: Duplicate detection
        "possible_duplicate": duplicate_result.get("possible_duplicate", False),
        "duplicate_of_document_id": duplicate_result.get("duplicate_of_document_id"),
        # Phase 7: Validation errors/warnings and draft_candidate
        "validation_errors": ap_validation.get("validation_errors", []),
        "validation_warnings": ap_validation.get("validation_warnings", []),
        "draft_candidate": ap_validation.get("draft_candidate", False),
        # Legacy fields (keep for backward compat)
        "canonical_fields": normalized_fields,
        "normalized_fields": validation_results.get("normalized_fields", {}),
        "validation_results": validation_results,
        "automation_decision": decision,
        "match_method": validation_results.get("match_method", "none"),
        "match_score": validation_results.get("match_score", 0.0),
        "vendor_candidates": decision_metadata.get("vendor_candidates", []),
        "customer_candidates": decision_metadata.get("customer_candidates", []),
        "warnings": decision_metadata.get("warnings", []),
        "status": final_status,
        "workflow_state": "Validated",
        "updated_utc": datetime.now(timezone.utc).isoformat()
    }
    
    if sp_result:
        update_data["sharepoint_drive_id"] = sp_result["drive_id"]
        update_data["sharepoint_item_id"] = sp_result["item_id"]
        update_data["sharepoint_web_url"] = sp_result["web_url"]
        update_data["sharepoint_share_link_url"] = share_link
    else:
        update_data["last_error"] = f"SharePoint upload failed: {sp_error}"
    
    # Add AI classification audit trail if AI was invoked
    if ai_classification_audit:
        update_data["ai_classification"] = ai_classification_audit
    
    # Phase 8: Save Spiro context to document (Shadow Mode)
    if spiro_context_dict:
        update_data["spiro_context"] = spiro_context_dict
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    
    # Update workflow status based on processing results and doc_type
    if doc_type_value == DocType.AP_INVOICE.value:
        # Full AP workflow with vendor matching, BC validation, etc.
        await _update_ap_workflow_status(
            doc_id, 
            confidence, 
            normalized_fields, 
            vendor_alias_result, 
            validation_results,
            ap_validation
        )
        
        # AUTO-POST: Attempt automatic posting to BC for eligible AP invoices
        if AUTO_POST_ENABLED:
            # Refresh document after workflow update to get latest state
            updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
            if updated_doc:
                try:
                    bc_service = get_bc_service()
                    auto_post_result = await attempt_auto_post(doc_id, updated_doc, db, bc_service)
                    
                    if auto_post_result.eligible:
                        if auto_post_result.success:
                            logger.info("AUTO-POST: Document %s auto-posted to BC as %s", 
                                       doc_id, auto_post_result.bc_document_number)
                            final_status = "Posted"  # Update final status for return
                        else:
                            logger.warning("AUTO-POST: Document %s eligible but failed: %s", 
                                          doc_id, auto_post_result.error)
                    else:
                        logger.debug("AUTO-POST: Document %s not eligible: %s", 
                                    doc_id, auto_post_result.reason)
                except Exception as e:
                    logger.error("AUTO-POST: Exception for %s: %s", doc_id, str(e))
    else:
        # For non-AP documents, use simplified workflow
        await _update_standard_workflow_status(
            doc_id, 
            doc_type_value,
            confidence, 
            normalized_fields
        )
    
    # Create workflow audit trail entry
    workflow_run_id = uuid.uuid4().hex[:8]
    workflow = {
        "id": str(uuid.uuid4()),
        "run_id": workflow_run_id,
        "document_id": doc_id,
        "workflow_name": source,
        "workflow_type": "intake_validation",
        "started_utc": now,
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Completed",
        "correlation_id": uuid.uuid4().hex[:8],
        "steps": [
            {"step": "AI Classification", "status": "Completed", "timestamp": now, 
             "details": {"document_type": suggested_type, "confidence": confidence}},
            {"step": "SharePoint Upload", "status": "Completed" if sp_result else "Failed", 
             "timestamp": datetime.now(timezone.utc).isoformat(),
             "details": sp_result if sp_result else {"error": sp_error}},
            {"step": "BC Validation", "status": "Completed", "timestamp": datetime.now(timezone.utc).isoformat(),
             "details": {
                 "match_method": validation_results.get("match_method", "none"),
                 "match_score": validation_results.get("match_score", 0.0),
                 "all_passed": validation_results.get("all_passed", False)
             }},
            {"step": "Automation Decision", "status": "Completed", "timestamp": datetime.now(timezone.utc).isoformat(),
             "details": {"decision": decision, "reasoning": reasoning, "final_status": final_status}}
        ],
        "error": None
    }
    await db.hub_workflow_runs.insert_one(workflow)
    
    logger.info("[Workflow:%s] Intake complete: %s → status=%s, decision=%s, score=%.2f", 
                workflow_run_id, filename, final_status, decision, validation_results.get("match_score", 0.0))
    
    return {
        "document": {"id": doc_id, "status": final_status},
        "classification": classification,
        "automation_decision": decision,
        "sharepoint": sp_result
    }
