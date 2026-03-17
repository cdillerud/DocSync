"""
GPI Document Hub - Document Intelligence Helpers

Functions extracted from server.py to decouple document_intelligence_service
from the monolithic server module.

Contents:
  - classify_document_with_ai() — Gemini-based doc classification + extraction
  - normalize_extracted_fields() — amount/date/string field normalization
  - compute_ap_normalized_fields() — AP-specific flat field computation
  - make_automation_decision() — decision matrix for automation level
  - validate_bc_match() — thin adapter to server.py (too entangled to extract)

Consumers:
  - document_intelligence_service  (primary)
  - server.py retains compatibility wrappers for other callers
"""

import os
import re
import uuid
import json
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List, Tuple

from dateutil import parser as date_parser

logger = logging.getLogger(__name__)

EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")


# ---------------------------------------------------------------------------
# 1. AI Classification + Extraction
# ---------------------------------------------------------------------------

import re as _re

# BOL keyword patterns for fast pre-AI detection
_BOL_FILENAME_PATTERNS = _re.compile(
    r'\b(bol|b[/-]?l|bill[_ -]?of[_ -]?lading|straight[_ -]?bill)\b', _re.IGNORECASE
)

# Warehouse receipt patterns — check BEFORE BOL to prevent misclassification
_WR_FILENAME_PATTERNS = _re.compile(
    r'\b(warehouse[_ -]?receipt|wh[_ -]?receipt|wr[_ -]?\d|non[_ -]?negotiable)\b', _re.IGNORECASE
)

_WR_TEXT_PATTERNS = _re.compile(
    r'(warehouse\s+receipt|non[- ]negotiable\s+warehouse|goods\s+receiv|'
    r'received\s+(?:in|at)\s+(?:good|apparent)|'
    r'stored\s+(?:in|at)\s+warehouse|warehouse\s+no)',
    _re.IGNORECASE,
)


def _check_obvious_warehouse_receipt(file_path: str, file_name: str) -> dict | None:
    """Fast heuristic: if filename or first-page text indicates a warehouse receipt,
    classify immediately. Must run BEFORE BOL check since WRs often contain shipping terms."""
    
    fn_lower = file_name.lower()
    if _WR_FILENAME_PATTERNS.search(fn_lower):
        logger.info("Pre-AI WR detection: filename match '%s'", file_name)
        return {
            "suggested_job_type": "Warehouse_Receipt",
            "confidence": 0.95,
            "model": "heuristic-wr-filename",
            "extracted_fields": {"wr_detected_by": "filename_pattern"},
        }
    
    ext = fn_lower.rsplit(".", 1)[-1] if "." in fn_lower else ""
    if ext == "pdf":
        try:
            import fitz
            with fitz.open(file_path) as pdf_doc:
                if len(pdf_doc) > 0:
                    page_text = pdf_doc[0].get_text()[:3000]
                    matches = _WR_TEXT_PATTERNS.findall(page_text)
                    if matches:
                        logger.info("Pre-AI WR detection: text match (%d indicators) in '%s'", len(matches), file_name)
                        fields = {"wr_detected_by": "text_pattern"}
                        # Extract receipt number
                        rcpt_m = _re.search(r'(?:receipt|rcpt)\s*(?:#|no\.?|number)?\s*[:\s]*([A-Z0-9-]{3,20})', page_text, _re.IGNORECASE)
                        client_m = _re.search(r'client[:\s]*([^\n]{5,60})', page_text, _re.IGNORECASE)
                        if rcpt_m:
                            fields["receipt_number"] = rcpt_m.group(1).strip()
                        if client_m:
                            fields["customer"] = client_m.group(1).strip()
                        return {
                            "suggested_job_type": "Warehouse_Receipt",
                            "confidence": 0.90,
                            "model": "heuristic-wr-text",
                            "extracted_fields": fields,
                        }
        except Exception as e:
            logger.debug("WR text check failed for %s: %s", file_name, e)
    
    return None

_BOL_TEXT_PATTERNS = _re.compile(
    r'(bill\s+of\s+lading|straight\s+bill\s+of\s+lading|'
    r'uniform\s+straight\s+bill\s+of\s+lading|'
    r'short\s+form\s+bill\s+of\s+lading|'
    r'shipper[\'s]*\s+no|consignee|'
    r'carrier[\'s]*\s+no|pro\s*number|'
    r'\bbol\s*#|\bb/l\s*no|\bbl\s*no)',
    _re.IGNORECASE,
)


def _check_obvious_bol(file_path: str, file_name: str) -> dict | None:
    """Fast heuristic: if filename or first-page text obviously indicates a BOL,
    return a classification result without calling the LLM."""
    
    # Check filename first (cheapest check)
    fn_lower = file_name.lower()
    if _BOL_FILENAME_PATTERNS.search(fn_lower):
        logger.info("Pre-AI BOL detection: filename match '%s'", file_name)
        return {
            "suggested_job_type": "Shipping_Document",
            "confidence": 0.95,
            "model": "heuristic-bol-filename",
            "extracted_fields": {"bol_detected_by": "filename_pattern"},
        }

    # Check first-page text for PDFs (slightly more expensive but still fast)
    ext = fn_lower.rsplit(".", 1)[-1] if "." in fn_lower else ""
    if ext == "pdf":
        try:
            import fitz  # PyMuPDF
            with fitz.open(file_path) as pdf_doc:
                if len(pdf_doc) > 0:
                    page_text = pdf_doc[0].get_text()[:2000]  # First 2000 chars of page 1
                    matches = _BOL_TEXT_PATTERNS.findall(page_text)
                    if len(matches) >= 2:  # Need at least 2 BOL indicators
                        logger.info("Pre-AI BOL detection: text match (%d indicators) in '%s'", len(matches), file_name)
                        # Extract basic fields from the text
                        fields = {"bol_detected_by": "text_pattern", "bol_indicators": len(matches)}
                        # Try to pull shipper/consignee
                        shipper_m = _re.search(r'(?:shipper|from)[:\s]*([^\n]{5,60})', page_text, _re.IGNORECASE)
                        consignee_m = _re.search(r'consignee[:\s]*([^\n]{5,60})', page_text, _re.IGNORECASE)
                        bol_num_m = _re.search(r'(?:bol|b/l|bl)\s*(?:#|no\.?|number)?\s*[:\s]*([A-Z0-9-]{3,20})', page_text, _re.IGNORECASE)
                        pro_m = _re.search(r'pro\s*(?:#|no\.?|number)?\s*[:\s]*([A-Z0-9-]{3,20})', page_text, _re.IGNORECASE)
                        if shipper_m:
                            fields["vendor"] = shipper_m.group(1).strip()
                        if consignee_m:
                            fields["customer"] = consignee_m.group(1).strip()
                        if bol_num_m:
                            fields["bol_number"] = bol_num_m.group(1).strip()
                        if pro_m:
                            fields["pro_number"] = pro_m.group(1).strip()
                        return {
                            "suggested_job_type": "Shipping_Document",
                            "confidence": 0.92,
                            "model": "heuristic-bol-text",
                            "extracted_fields": fields,
                        }
        except Exception as e:
            logger.debug("BOL text check failed for %s: %s", file_name, str(e))

    return None



async def classify_document_with_ai(file_path: str, file_name: str) -> dict:
    """
    Use Gemini to analyze a document and extract structured data.
    Returns classification and extracted fields.

    For multi-page PDFs, extracts only the first page to avoid
    classification confusion from supporting documents on later pages.
    """
    # Fast pre-AI heuristic: catch obvious warehouse receipts FIRST (before BOL check)
    wr_result = _check_obvious_warehouse_receipt(file_path, file_name)
    if wr_result:
        return wr_result
    
    # Fast pre-AI heuristic: catch obvious BOLs by filename before using LLM
    bol_result = _check_obvious_bol(file_path, file_name)
    if bol_result:
        return bol_result

    if not EMERGENT_LLM_KEY:
        return {
            "error": "EMERGENT_LLM_KEY not configured",
            "suggested_job_type": "Unknown",
            "confidence": 0.0,
            "extracted_fields": {},
        }

    try:
        from emergentintegrations.llm.chat import LlmChat, UserMessage, FileContentWithMimeType

        ext = file_name.lower().split(".")[-1] if "." in file_name else ""
        mime_map = {
            "pdf": "application/pdf",
            "png": "image/png",
            "jpg": "image/jpeg",
            "jpeg": "image/jpeg",
            "tiff": "image/tiff",
            "gif": "image/gif",
            "txt": "text/plain",
            "csv": "text/csv",
            "html": "text/html",
            "json": "application/json",
            "xml": "application/xml",
        }
        mime_type = mime_map.get(ext, "text/plain")

        # For multi-page PDFs, extract just page 1 to avoid misclassification
        actual_file_path = file_path
        temp_pdf_path = None
        page_count = 1
        if ext == "pdf":
            try:
                actual_file_path, temp_pdf_path, page_count = _extract_first_page_pdf(file_path)
                if page_count > 1:
                    logger.info(
                        "Multi-page PDF (%d pages): sending only page 1 for classification: %s",
                        page_count, file_name,
                    )
            except Exception as e:
                logger.warning("Failed to extract first page from %s: %s — sending full PDF", file_name, e)
                actual_file_path = file_path

        # Build dynamic prompt with learned examples
        dynamic_prompt = _CLASSIFY_SYSTEM_PROMPT
        try:
            from services.classification_feedback_service import (
                build_few_shot_prompt_section,
                build_vendor_hints_prompt_section,
            )
            few_shot_section = await build_few_shot_prompt_section()
            if few_shot_section:
                dynamic_prompt = dynamic_prompt + "\n" + few_shot_section
                logger.info("Injected few-shot examples into classification prompt")
            
            # If we can detect the vendor from filename, add vendor hint
            vendor_hint = await build_vendor_hints_prompt_section(file_name)
            if vendor_hint:
                dynamic_prompt = dynamic_prompt + "\n" + vendor_hint
        except Exception as e:
            logger.debug("Few-shot injection skipped: %s", e)

        chat = LlmChat(
            api_key=EMERGENT_LLM_KEY,
            session_id=f"classify-{uuid.uuid4()}",
            system_message=dynamic_prompt,
        ).with_model("gemini", "gemini-3-flash-preview")

        file_content = FileContentWithMimeType(file_path=actual_file_path, mime_type=mime_type)

        bundle_note = ""
        if page_count > 1:
            bundle_note = (
                f" NOTE: This is page 1 of a {page_count}-page document bundle. "
                "Classify based on THIS page only (the primary/lead document). "
                "Later pages contain supporting documents like BOLs or freight bills."
            )

        user_message = UserMessage(
            text=(
                "Please analyze this business document. "
                "Classify the document and extract all relevant fields. "
                "Also extract routing fields: is_international, is_tooling, is_storage_handling, "
                "is_credit_memo, is_dunnage, freight_direction."
                + bundle_note
                + " Respond with JSON only."
            ),
            file_contents=[file_content],
        )

        response = await chat.send_message(user_message)

        # Clean up temp file
        if temp_pdf_path:
            try:
                os.remove(temp_pdf_path)
            except Exception:
                pass

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

        extracted = result.get("extracted_fields", {})
        logger.info(
            "AI Classification result - doc_type: %s, confidence: %s, pages: %d",
            result.get("document_type"),
            result.get("confidence"),
            page_count,
        )
        logger.info("AI extracted invoice_date: %s", extracted.get("invoice_date"))

        return {
            "suggested_job_type": result.get("document_type", "Unknown"),
            "confidence": float(result.get("confidence", 0.0)),
            "extracted_fields": result.get("extracted_fields", {}),
            "reasoning": result.get("reasoning", ""),
            "model": "gemini-3-flash-preview",
            "page_count": page_count,
            "classified_from_page": 1 if page_count > 1 else None,
        }

    except Exception as e:
        logger.error("AI classification failed: %s", str(e))
        # Clean up temp file on error
        if 'temp_pdf_path' in dir() and temp_pdf_path:
            try:
                os.remove(temp_pdf_path)
            except Exception:
                pass
        return {
            "error": str(e),
            "suggested_job_type": "Unknown",
            "confidence": 0.0,
            "extracted_fields": {},
            "reasoning": f"Classification failed: {str(e)}",
        }


def _extract_first_page_pdf(file_path: str):
    """
    Extract the first page of a PDF into a temporary file.

    Returns:
        (actual_path, temp_path, page_count):
        - actual_path: path to use for classification (temp or original if single page)
        - temp_path: path to temp file (None if single page)
        - page_count: total pages in original PDF
    """
    import tempfile
    from pypdf import PdfReader, PdfWriter

    reader = PdfReader(file_path)
    page_count = len(reader.pages)

    if page_count <= 1:
        return file_path, None, page_count

    # Extract first page to temp file
    writer = PdfWriter()
    writer.add_page(reader.pages[0])

    temp_fd, temp_path = tempfile.mkstemp(suffix=".pdf")
    os.close(temp_fd)
    with open(temp_path, "wb") as f:
        writer.write(f)

    return temp_path, temp_path, page_count


# ---------------------------------------------------------------------------
# 2. Field Normalization
# ---------------------------------------------------------------------------

def normalize_extracted_fields(fields: dict) -> dict:
    """
    Normalize extracted fields before BC validation.

    - Convert amounts to decimal
    - Convert dates to ISO format
    - Clean up strings

    Extracted from server.py — identical behavior.
    """
    normalized = {}

    for key, value in fields.items():
        if value is None:
            continue

        if key in ("amount", "payment_amount", "total", "subtotal"):
            clean_amount = re.sub(r"[^\d.-]", "", str(value))
            try:
                normalized[key] = float(clean_amount) if clean_amount else None
                normalized[f"{key}_raw"] = value
            except ValueError:
                normalized[key] = None
                normalized[f"{key}_raw"] = value

        elif key in (
            "due_date", "invoice_date", "order_date", "payment_date",
            "ship_date", "delivery_date", "document_date",
        ):
            try:
                parsed_date = date_parser.parse(str(value))
                normalized[key] = parsed_date.strftime("%Y-%m-%d")
                normalized[f"{key}_raw"] = value
            except Exception:
                normalized[key] = None
                normalized[f"{key}_raw"] = value

        elif isinstance(value, str):
            normalized[key] = value.strip()
        else:
            normalized[key] = value

    return normalized


def compute_ap_normalized_fields(extracted_fields: dict) -> dict:
    """
    Compute normalized fields for AP_Invoice documents.

    Returns flat fields: vendor_raw/normalized, invoice_number_raw/clean,
    amount_raw/float, due_date_raw/iso, po_number_raw/clean, invoice_date,
    line_items.

    Extracted from server.py — identical behavior.
    """
    result = {}
    if not extracted_fields:
        return result

    # Vendor normalization
    vendor = extracted_fields.get("vendor")
    if vendor:
        vendor_str = str(vendor).strip()
        result["vendor_raw"] = vendor_str
        normalized = re.sub(r"\s+", " ", vendor_str.lower().strip())
        result["vendor_normalized"] = normalized
    else:
        result["vendor_raw"] = None
        result["vendor_normalized"] = None

    # Invoice number normalization
    invoice_num = extracted_fields.get("invoice_number")
    if invoice_num:
        inv_str = str(invoice_num).strip()
        result["invoice_number_raw"] = inv_str
        clean = re.sub(r"[\s,]+", "", inv_str).upper()
        result["invoice_number_clean"] = clean
    else:
        result["invoice_number_raw"] = None
        result["invoice_number_clean"] = None

    # Amount parsing to float
    amount = extracted_fields.get("amount")
    if amount is not None:
        result["amount_raw"] = str(amount)
        try:
            clean_amount = re.sub(r"[^\d.-]", "", str(amount))
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
            result["due_date_iso"] = parsed_date.strftime("%Y-%m-%d")
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
        result["po_number_clean"] = re.sub(r"[\s,]+", "", po_str).upper()
    else:
        result["po_number_raw"] = None
        result["po_number_clean"] = None

    # Invoice date to ISO
    invoice_date = extracted_fields.get("invoice_date")
    if invoice_date:
        result["invoice_date_raw"] = str(invoice_date)
        try:
            parsed_date = date_parser.parse(str(invoice_date))
            result["invoice_date"] = parsed_date.strftime("%Y-%m-%d")
        except Exception:
            result["invoice_date"] = None
    else:
        result["invoice_date_raw"] = None
        result["invoice_date"] = None

    # Line items normalization
    line_items = extracted_fields.get("line_items")
    if line_items and isinstance(line_items, list):
        normalized_items = []
        for item in line_items:
            if isinstance(item, dict):
                normalized_items.append({
                    "description": item.get("description", ""),
                    "quantity": float(item.get("quantity", 1) or 1),
                    "unit_price": float(item.get("unit_price", 0) or 0),
                    "total": float(item.get("total", 0) or 0),
                })
        result["line_items"] = normalized_items
    else:
        result["line_items"] = []

    return result


# ---------------------------------------------------------------------------
# 3. Automation Decision Matrix
# ---------------------------------------------------------------------------

def make_automation_decision(
    job_config: dict,
    ai_confidence: float,
    validation_results: dict,
) -> Tuple[str, str, dict]:
    """
    Decision matrix for automation level.

    Returns ``(decision, reasoning, metadata)`` where decision is one of:
    manual, needs_review, auto_link, auto_create.

    Extracted from server.py — identical behavior.
    """
    automation_level = job_config.get("automation_level", 0)
    link_threshold = job_config.get("min_confidence_to_auto_link", 0.85)
    create_threshold = job_config.get("min_confidence_to_auto_create_draft", 0.95)
    requires_review = job_config.get("requires_human_review_if_exception", True)

    metadata = {
        "vendor_candidates": validation_results.get("vendor_candidates", []),
        "customer_candidates": validation_results.get("customer_candidates", []),
        "warnings": validation_results.get("warnings", []),
    }

    if automation_level == 0:
        return "manual", "Job type configured for manual processing only", metadata

    if not validation_results.get("all_passed", False):
        failed_checks = [
            c["check_name"]
            for c in validation_results.get("checks", [])
            if not c["passed"] and c.get("required", True)
        ]
        has_candidates = (
            len(validation_results.get("vendor_candidates", [])) > 0
            or len(validation_results.get("customer_candidates", [])) > 0
        )
        reason_suffix = " (candidates available for quick resolution)" if has_candidates else ""
        if requires_review:
            return "needs_review", f"Validation failed: {', '.join(failed_checks)}{reason_suffix}", metadata
        return "manual", f"Validation failed but review not required: {', '.join(failed_checks)}", metadata

    warning_notes = ""
    if validation_results.get("warnings"):
        warning_notes = f" (with {len(validation_results['warnings'])} warning(s))"

    if ai_confidence < link_threshold:
        return "needs_review", f"Confidence {ai_confidence:.2%} below link threshold {link_threshold:.2%}", metadata

    if automation_level == 1:
        if ai_confidence >= link_threshold:
            return "auto_link", f"Confidence {ai_confidence:.2%} meets link threshold, auto-linking to existing BC record{warning_notes}", metadata
        return "needs_review", f"Confidence {ai_confidence:.2%} below threshold", metadata

    if automation_level >= 2:
        if ai_confidence >= create_threshold:
            return "auto_create", f"Confidence {ai_confidence:.2%} meets create threshold, creating draft BC document{warning_notes}", metadata
        elif ai_confidence >= link_threshold:
            return "auto_link", f"Confidence {ai_confidence:.2%} meets link threshold only, auto-linking{warning_notes}", metadata
        return "needs_review", f"Confidence {ai_confidence:.2%} below thresholds", metadata

    return "needs_review", "Default fallback to review", metadata


# ---------------------------------------------------------------------------
# 4. BC Validation — thin adapter (too entangled to fully extract)
# ---------------------------------------------------------------------------

async def validate_bc_match(
    job_type: str, extracted_fields: dict, job_config: dict
) -> dict:
    """Validate extracted fields against BC.

    Delegates to the authoritative implementation in bc_validation_service.
    """
    from services.bc_validation_service import validate_bc_match as _bc_validate

    return await _bc_validate(job_type, extracted_fields, job_config)


# ---------------------------------------------------------------------------
# System prompt (extracted from server.py classify_document_with_ai)
# ---------------------------------------------------------------------------

_CLASSIFY_SYSTEM_PROMPT = """You are a document classification and data extraction AI for Gamer Packaging, Inc.'s document management system.

IMPORTANT CONTEXT:
- Our company is "Gamer Packaging, Inc." (also known as "Gamer Packaging" or "GPI")
- Documents come from BOTH our Accounts Payable inbox AND Sales mailboxes
- You must classify documents into the correct category: AP (accounts payable) or Sales
- Classified documents are automatically routed to SharePoint folders based on type, vendor, and order

MULTI-PAGE BUNDLE HANDLING:
- PDFs often contain MULTIPLE related documents bundled together (e.g., a PO Confirmation + Bill of Lading + Freight Bill)
- ALWAYS classify based on the PRIMARY/LEAD document, which is typically the FIRST page
- Supporting documents (BOLs, freight bills, packing slips) attached after the primary document do NOT change the classification
- Examples of bundles:
  * PO Confirmation + BOL + Freight Bill → classify as Sales_Order (the PO is the primary doc)
  * Warehouse Receipt + BOL → classify as Warehouse_Receipt (the receipt is primary, NOT a Sales_Order)
  * Invoice + Packing Slip → classify as AP_Invoice (the invoice is primary)
  * Bill of Lading ONLY (no other lead doc) → classify as Shipping_Document
- Key rule: If page 1 is a PO, order, receipt, or invoice, classify based on THAT — not the supporting shipping docs that follow

DOCUMENT CATEGORIES AND TYPES:

== AP (Accounts Payable) Category ==
AP_Invoice: Vendor invoices we RECEIVE
- The VENDOR is the company sending us the invoice (NOT Gamer Packaging)
- If "Gamer Packaging" appears as Bill To/Customer, this is an AP_Invoice we received
- Extract: vendor name (the sender), invoice_number, invoice_date, amount, po_number (if present), due_date
- CRITICAL: Always extract invoice_date (the date on the invoice itself)
- CRITICAL: Extract ALL line items with description, quantity, unit_price, and total
- ROUTING NOTE: Also extract is_international (true/false), is_tooling (true if tooling/mold/die charges), is_storage_handling (true if S&H/storage/handling charges), is_credit_memo (true if credit memo/credit note/refund/adjustment), is_dunnage (true if dunnage/pallet/return freight related)

AR_Invoice: Invoices we send to customers (outgoing)
- Our company name appears as the sender
- Extract: customer name, invoice_number, invoice_date, amount, due_date

Remittance: Payment confirmations
- Extract: vendor/customer, payment_amount, payment_date, invoice_references
- Look for "Remittance Advice", "Payment", check numbers

Freight_Document: Shipping/freight INVOICES specifically — freight bills requesting payment
- Extract: shipper, consignee, tracking_number, carrier, origin, destination, freight charges
- Look for freight charges, rates, and billing — NOT just any BOL
- A standalone Bill of Lading or BOL without an invoice component is a Shipping_Document, not a Freight_Document

== Sales Category ==
Sales_Order: Customer purchase orders to us, PO confirmations
- Extract: customer name, po_number, order_date, amount, ship_to address
- Look for "Purchase Order", "PO#", "Order", "PO Confirmation", quantity, ship to
- If a PDF starts with a PO Confirmation followed by BOLs/freight bills, this is a Sales_Order

Sales_Quote: Price quotes or proposals to customers
- Extract: customer, amount, valid_until
- Look for "Quote", "Quotation", "Proposal", "Estimate"

Order_Confirmation: Order acknowledgments
- Extract: order_number, customer, amount
- Look for "Confirmation", "Acknowledged", "Order Acknowledgment"

Warehouse_Receipt: Non-negotiable or negotiable warehouse receipts — documents confirming goods received into storage
- These are issued by a warehouse/3PL (e.g., Koch Logistics) to the client (e.g., Gamer Packaging)
- Extract: receipt_number, receipt_date, warehouse, client, received_from, reference, carrier, items, quantities, weight, lot_numbers
- Look for "Warehouse Receipt", "Non-Negotiable Warehouse Receipt", "Goods Received", lot numbers, manufacture dates, bin/location info
- Key indicators: a warehouse company header, "Client" field, "Received From" field, detailed inventory line items with lot/batch tracking
- NOT the same as a PO or Sales Order — this is a receiving/storage confirmation
- A warehouse receipt + BOL bundle → classify as Warehouse_Receipt (the receipt is the primary doc)

Inventory_Report: Stock/inventory status reports
- Extract: warehouse, items, quantities
- Look for "Inventory", "Stock", "On Hand", "Available"

Shipping_Document: STANDALONE shipping documents — BOLs, Bills of Lading, delivery receipts
- Only use this when the document is PURELY a shipping/transport document with NO leading PO, invoice, or receipt
- Extract: bol_number, ship_date, po_number, shipper, consignee, carrier, tracking_number, pro_number, weight, pieces
- Look for "Ship", "Delivery", "Dispatch", "Bill of Lading", "BOL", "Straight Bill", "Shipper", "Consignee"
- BOL Number is the primary document identifier (often labeled "B/L No" or "BOL#")
- Pro Number is the carrier's tracking/reference number

Quality_Issue: Quality complaints or issues
- Extract: customer, item, description
- Look for "Quality", "Defect", "Complaint", "NCR", "Claim"

Return_Request: Return requests / RMAs / Credit Memos
- Extract: customer, amount, reason
- Look for "Return", "RMA", "Credit", "Refund", "Credit Memo", "Adjustment"

Unknown_Document: Cannot determine type confidently

Always respond with valid JSON in this exact format:
{
    "document_type": "AP_Invoice|AR_Invoice|Remittance|Freight_Document|Sales_Order|Sales_Quote|Order_Confirmation|Warehouse_Receipt|Inventory_Report|Shipping_Document|Quality_Issue|Return_Request|Unknown_Document",
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
        "receipt_number": "...",
        "receipt_date": "...",
        "received_from": "...",
        "lot_numbers": "...",
        "items": "...",
        "ship_to": "...",
        "is_international": false,
        "is_tooling": false,
        "is_storage_handling": false,
        "is_credit_memo": false,
        "is_dunnage": false,
        "freight_direction": "inbound|outbound|unknown",
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

ROUTING FIELDS (always include when detectable):
- is_international: true if the shipment/order involves international origins or destinations
- is_tooling: true if the document is for tooling, mold, die, or fixture charges
- is_storage_handling: true if the document is for storage and handling (S&H) charges
- is_credit_memo: true if the document is a credit memo, credit note, refund, or adjustment
- is_dunnage: true if the document involves dunnage, pallets, or return freight
- freight_direction: "inbound" for incoming shipments, "outbound" for outgoing, "unknown" if unclear

For freight/transportation invoices, line items may include:
- Weight, distance, rate, charges
- Fuel surcharges, accessorial charges
- Extract these as line items with appropriate descriptions

Only include fields that you can actually extract from the document. Leave out fields that are not present."""
