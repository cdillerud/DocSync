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
import os
import uuid
from datetime import datetime, timezone
from typing import Optional

import httpx
from fastapi import APIRouter, HTTPException, Query, Request
from fastapi.responses import HTMLResponse
from pydantic import BaseModel, Field

from deps import get_db
from services.gpi_integration_service import (
    list_companies,
    create_sales_order,
    add_sales_order_lines,
    create_purchase_invoice,
    add_purchase_invoice_lines,
    delete_purchase_invoice_lines,
    attach_document_to_bc_record,
    create_gpi_document_link,
    create_customer,
    create_vendor,
    list_integration_logs,
    get_integration_status,
    HAS_CREDENTIALS,
    BC_SO_FALLBACK_GL_ACCOUNT,
    BC_SO_FALLBACK_ITEM_CODE,
)
from services.item_mapping_service import (
    map_line_to_item,
    record_mapping_history,
    list_mappings as list_item_mappings,
    create_mapping as create_item_mapping,
    update_mapping as update_item_mapping,
    delete_mapping as delete_item_mapping,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/gpi-integration", tags=["GPI Integration"])

# Document types eligible for BC Sales Order creation
SALES_ORDER_ELIGIBLE_TYPES = {"Sales_Order", "SalesOrder", "Order_Confirmation", "PurchaseOrder", "DS_Sales_Order", "WH_Sales_Order"}

# Document types eligible for BC Purchase Invoice creation
PURCHASE_INVOICE_ELIGIBLE_TYPES = {"AP_Invoice"}

# Default freight item code for PI lines
BC_PI_FREIGHT_ITEM = os.environ.get("BC_PI_FREIGHT_ITEM", os.environ.get("BC_DEFAULT_ITEM_CODE", "FREIGHT"))

# Document types that are primarily freight/transportation
FREIGHT_DOC_TYPES = {"AP_Invoice", "Freight_Document", "Bill_of_Lading", "FreightInvoice"}

# Default GPI warehouse location code used when so_type == "warehouse"
BC_DEFAULT_WAREHOUSE_CODE = os.environ.get("BC_DEFAULT_WAREHOUSE_CODE", "MAIN")


def _resolve_po_reference(doc: dict) -> str:
    """Extract the PO/BOL reference number from a document for use in BC PI line description.
    
    Priority: po_number_clean > po_number > bol_number > order_number > reference fields
    Returns the reference string, or empty string if none found.
    """
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    
    # Check normalized PO number first (cleanest)
    ref = doc.get("po_number_clean") or ""
    if ref:
        return ref
    
    # Raw PO number from extracted fields
    ref = nf.get("po_number") or ef.get("po_number") or doc.get("po_number") or ""
    if ref:
        return str(ref).strip()
    
    # BOL number (common on freight invoices)
    ref = nf.get("bol_number") or doc.get("bol_number") or ef.get("bol_number") or ""
    if ref:
        return str(ref).strip()
    
    # Order number
    ref = ef.get("order_number") or nf.get("order_number") or ""
    if ref:
        return str(ref).strip()
    
    # Reference field
    ref = ef.get("reference_number") or ef.get("reference") or ""
    if ref:
        return str(ref).strip()
    
    return ""


def _resolve_so_type(doc: dict) -> str:
    """Extract so_type from a document's extracted fields.

    Returns 'dropship', 'warehouse', or 'unknown'.
    """
    ef = doc.get("extracted_fields") or {}
    so_type = ef.get("so_type", "").lower().strip()
    if so_type in ("dropship", "drop_ship", "drop-ship"):
        return "dropship"
    if so_type in ("warehouse", "wh"):
        return "warehouse"
    return so_type if so_type else "unknown"


def _resolve_so_routing_fields(doc: dict, so_type: str) -> dict:
    """Return conditional BC Sales Order header fields based on so_type.

    For dropship orders:
      - ship_to_code: derived from the customer's ship-to address on the doc
      - ship_to_name: customer or consignee name
    For warehouse orders:
      - location_code: GPI warehouse code (env var BC_DEFAULT_WAREHOUSE_CODE)
    """
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}

    routing = {"so_type": so_type}

    if so_type == "dropship":
        # Dropship: Ship-to is the customer address, not GPI warehouse
        ship_to = ef.get("ship_to") or nf.get("ship_to") or ""
        ship_to_name = ef.get("customer") or nf.get("customer") or ""
        location_code = ef.get("location_code") or nf.get("location_code") or ""
        routing["ship_to_code"] = location_code  # BC alt-address code if present
        routing["ship_to_name"] = ship_to_name
        routing["ship_to_address"] = ship_to
        # Do NOT set location_code — dropship ships direct to customer
    elif so_type == "warehouse":
        # Warehouse: Ship-to is a GPI warehouse
        location_code = ef.get("location_code") or nf.get("location_code") or BC_DEFAULT_WAREHOUSE_CODE
        routing["location_code"] = location_code
        routing["ship_to_code"] = ""
        routing["ship_to_name"] = ""
    else:
        # Unknown — no special routing
        routing["ship_to_code"] = ""
        routing["ship_to_name"] = ""
        routing["location_code"] = ""

    return routing


async def _build_pi_lines_with_mapping(doc: dict, db, vendor_no: str = "") -> list:
    """Build BC Purchase Invoice lines with intelligent vendor profile-based mapping.
    
    Business rules:
    1. Fetch the vendor's invoice profile from BC history
    2. Check for posting pattern analysis (richer template from Phase 1)
    3. Use the profile's dominant line type and GL account/item code
    4. If AI extracted a specific item_number/SKU, use it (overrides profile)
    5. Description follows the vendor's historical pattern (PO ref, BOL ref, etc.)
    6. Flag deviations from the vendor's typical invoice pattern
    
    The profile learns from what's IN BC — making our output as accurate as a human.
    """
    from services.vendor_invoice_profile_service import (
        get_or_build_profile, build_smart_pi_lines, detect_deviations
    )

    doc_id = doc.get("id", "")
    
    # Get the PO/BOL reference
    po_ref = _resolve_po_reference(doc)
    
    # Resolve vendor_no if not passed
    if not vendor_no:
        vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
        if not vendor_no:
            vi = await _resolve_vendor_no(doc)
            vendor_no = vi.get("vendor_no", "")
    
    # Fetch the vendor's invoice profile from BC history
    profile = await get_or_build_profile(db, vendor_no)

    # Also check for the richer posting pattern analysis template
    posting_template = None
    try:
        from services.posting_pattern_analyzer import get_posting_profile_for_vendor
        posting_analysis = await get_posting_profile_for_vendor(db, vendor_no)
        if posting_analysis:
            posting_template = posting_analysis.get("posting_template", {})
    except Exception:
        pass
    
    if profile.get("bc_invoice_count", 0) > 0:
        # Use profile-driven line builder (learns from BC)
        bc_lines = build_smart_pi_lines(doc, profile, po_reference=po_ref)

        # Phase 2 enhancement: If a posting template exists, override line types
        # and item codes with the template's learned values (more accurate than basic profile)
        if posting_template and posting_template.get("confidence") in ("high", "medium"):
            line_templates = posting_template.get("line_templates", [])
            # Find the primary item from the template
            primary_templates = [lt for lt in line_templates if lt.get("rank") == "primary"]
            if not primary_templates:
                primary_templates = sorted(line_templates, key=lambda x: x.get("usage_rate", 0), reverse=True)[:1]

            if primary_templates:
                primary = primary_templates[0]
                template_item_no = primary.get("item_number") or primary.get("account_number", "")
                template_line_type = primary.get("type", "")
                template_desc_pattern = primary.get("common_description", "")

                if template_item_no and template_line_type:
                    for line in bc_lines:
                        # Override the line type and item/account code with the template's learned values
                        line["lineType"] = template_line_type
                        line["lineObjectNumber"] = template_item_no
                        line["source"] = "posting_template"

                        # Fix description to match production pattern
                        desc = line.get("description", "")
                        # If the item is a freight-type item, always use "Freight {ref}" format
                        if "freight" in template_item_no.lower():
                            ref = po_ref or desc
                            if ref and not ref.upper().startswith("FREIGHT"):
                                line["description"] = f"Freight {ref}"
                        elif template_desc_pattern and po_ref:
                            if "freight" in template_desc_pattern.lower():
                                line["description"] = f"Freight {po_ref}"

                    logger.info(
                        "[PI Lines] Template override for %s: %s/%s (confidence=%s)",
                        vendor_no, template_line_type, template_item_no, posting_template.get("confidence"),
                    )

        # Enhance lines with posting template reference patterns if available
        if posting_template and posting_template.get("reference_handling"):
            ref_handling = posting_template["reference_handling"]
            ref_pattern = ref_handling.get("pattern", "")
            for line in bc_lines:
                desc = line.get("description", "")
                # If the template says descriptions should include BOL/ref and we have a PO ref
                if po_ref and ref_pattern in ("freight_prefix_plus_ref", "bol_in_description"):
                    if ref_pattern == "freight_prefix_plus_ref" and not desc.upper().startswith("FREIGHT"):
                        line["description"] = f"Freight {po_ref}"
                    elif ref_pattern == "bol_in_description" and po_ref not in desc:
                        line["description"] = po_ref

        deviations = detect_deviations(doc, profile, bc_lines)
        
        if deviations:
            for d in deviations:
                logger.info("[PI Lines] Deviation for %s: [%s] %s", doc_id, d["severity"], d["message"])
            
            # Store deviations on the document for review
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "pi_deviations": deviations,
                    "pi_profile_used": {
                        "vendor_no": vendor_no,
                        "default_line_type": profile.get("default_line_type"),
                        "default_gl_account": profile.get("default_gl_account"),
                        "default_item_code": profile.get("default_item_code"),
                        "bc_invoice_count": profile.get("bc_invoice_count", 0),
                        "description_pattern": profile.get("description_pattern"),
                        "posting_template_confidence": posting_template.get("confidence", "none") if posting_template else "none",
                    },
                }}
            )
        
        logger.info(
            "[PI Lines] Using vendor profile for %s: type=%s, gl=%s, item=%s, pattern=%s (%d BC invoices analyzed, template=%s)",
            vendor_no, profile.get("default_line_type"), profile.get("default_gl_account"),
            profile.get("default_item_code"), profile.get("description_pattern"),
            profile.get("bc_invoice_count", 0),
            posting_template.get("confidence", "none") if posting_template else "none",
        )
        return bc_lines
    
    # Fallback: No BC history — use extraction + defaults (old behavior)
    logger.info("[PI Lines] No vendor profile for %s — falling back to extraction defaults", vendor_no)
    return await _build_pi_lines_fallback(doc, db, po_ref)



async def _build_pi_lines_fallback(doc: dict, db, po_ref: str) -> list:
    """Fallback PI line builder when no vendor profile exists.
    Uses extraction + default FREIGHT item (original behavior).
    """
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    doc_id = doc.get("id", "")

    line_items = nf.get("line_items") or ef.get("line_items") or doc.get("line_items") or []

    if not line_items:
        total_amount = 0
        for field in ["amount", "amount_float", "invoice_amount", "total_amount", "balance_due"]:
            val = nf.get(field) or ef.get(field) or doc.get(field)
            if val:
                cleaned = str(val).replace("$", "").replace(",", "").strip()
                try:
                    total_amount = float(cleaned)
                    break
                except (ValueError, TypeError):
                    continue
        if total_amount <= 0:
            return []
        line_items = [{
            "description": po_ref or f"Per invoice {ef.get('invoice_number', '')}".strip(),
            "quantity": 1,
            "unit_price": total_amount,
        }]

    bc_lines = []
    for idx, li in enumerate(line_items):
        desc = str(li.get("description", "")).strip()
        qty = float(li.get("quantity", 1) or 1)
        unit_cost = float(li.get("unit_price", 0) or li.get("unitCost", 0) or li.get("unit_cost", 0) or 0)
        if unit_cost == 0:
            unit_cost = float(li.get("total", 0) or li.get("amount", 0) or 0)

        explicit_item = li.get("item_number") or li.get("sku") or li.get("lineObjectNumber") or ""
        explicit_gl = li.get("gl_account") or li.get("account_number") or ""

        if explicit_item:
            mapping_result = await map_line_to_item(db, description=desc, extracted_sku=explicit_item, doc_id=doc_id)
            bc_line = {
                "lineType": mapping_result.get("line_type", "Item"),
                "lineObjectNumber": mapping_result.get("target_no", explicit_item),
                "description": po_ref if po_ref else desc,
                "quantity": qty,
                "unitCost": unit_cost,
            }
        elif explicit_gl:
            bc_line = {
                "lineType": "Account",
                "lineObjectNumber": explicit_gl,
                "description": po_ref if po_ref else desc,
                "quantity": qty,
                "unitCost": unit_cost,
            }
        else:
            bc_line = {
                "lineType": "Item",
                "lineObjectNumber": BC_PI_FREIGHT_ITEM,
                "description": po_ref if po_ref else desc,
                "quantity": qty,
                "unitCost": unit_cost,
            }

        bc_lines.append(bc_line)

    return bc_lines


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


@router.get("/bc-api-schema/{entity_set}")
async def get_bc_api_schema(entity_set: str):
    """Query BC custom API to discover available fields for an entity set."""
    if not HAS_CREDENTIALS:
        raise HTTPException(status_code=503, detail="BC credentials not configured")
    try:
        from services.gpi_integration_service import _api_request, BC_WRITE_ENVIRONMENT
        result = await _api_request("GET", entity_set, params={"$top": "1"}, environment=BC_WRITE_ENVIRONMENT)
        records = result.get("value", [])
        if records:
            return {"entity_set": entity_set, "fields": list(records[0].keys()), "sample": records[0]}
        return {"entity_set": entity_set, "fields": [], "message": "No records found"}
    except Exception as e:
        raise HTTPException(status_code=502, detail=str(e))



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

    customer_name = ef.get("customer") or ef.get("customer_name") or nf.get("customer") or nf.get("customer_name") or ""
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

    # 1.5 Check extracted_fields or normalized_fields for customer number
    if not customer_no:
        cno = ef.get("customer_no") or nf.get("bc_customer_no") or nf.get("customer_no") or ""
        if cno:
            customer_no = cno
            customer_name = customer_name or ef.get("customer_name") or nf.get("customer_name") or ""
            match_method = "extracted_field"
            confidence = 0.95

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


async def _resolve_sales_lines(doc: dict, customer_no: str = "") -> list:
    """Resolve the sales lines that will be created in BC.

    For each extracted line, attempts item mapping via the mapping service.
    Falls back to Comment/fallback lines when confidence is low.

    Priority:
      1. Extracted line_items → mapped to BC item via item_mapping_service
      2. Fallback: single line using G/L account or item code + total amount
      3. Empty list → caller must block creation

    Returns list of dicts with: lineType, lineObjectNumber, description,
    quantity, unitPrice, source, mapping metadata
    """
    db = get_db()
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    line_items = ef.get("line_items") or nf.get("line_items") or []

    resolved = []

    if line_items:
        for li in line_items:
            desc = li.get("description", "") or ""
            qty = float(li.get("quantity", 1) or 1)
            unit_price = float(li.get("unit_price", 0) or li.get("unitPrice", 0) or 0)
            total = float(li.get("total", 0) or li.get("amount", 0) or 0)

            if total > 0 and unit_price == 0 and qty > 0:
                unit_price = round(total / qty, 2)

            extracted_sku = li.get("item_number") or li.get("itemNumber") or li.get("item_no") or ""

            # Attempt item mapping
            mapping_result = await map_line_to_item(
                db,
                description=desc,
                extracted_sku=extracted_sku,
                customer_no=customer_no,
                doc_id=doc.get("id", ""),
            )

            if mapping_result["matched"]:
                resolved.append({
                    "lineType": mapping_result["line_type"],
                    "lineObjectNumber": mapping_result["target_no"],
                    "description": desc[:100] if desc else "Line item",
                    "quantity": qty,
                    "unitPrice": unit_price,
                    "source": "mapped",
                    "mapping": {
                        "matched": True,
                        "target_type": mapping_result["target_type"],
                        "target_no": mapping_result["target_no"],
                        "target_description": mapping_result.get("target_description", ""),
                        "confidence": mapping_result["confidence"],
                        "method": mapping_result["method"],
                        "mapping_id": mapping_result.get("mapping_id"),
                        "catalog_validated": mapping_result.get("catalog_validated", False),
                    },
                })
            else:
                resolved.append({
                    "lineType": "Comment",
                    "lineObjectNumber": "",
                    "description": desc[:100] if desc else "Line item",
                    "quantity": qty,
                    "unitPrice": unit_price,
                    "source": "extracted",
                    "mapping": {
                        "matched": False,
                        "target_type": "comment",
                        "target_no": "",
                        "target_description": "",
                        "confidence": 0,
                        "method": "none",
                        "mapping_id": None,
                        "catalog_validated": False,
                    },
                })

            # Add comment lines from the line item (e.g. "2,821/plt, 22 plt/TL")
            comments = li.get("comments") or []
            for comment_text in comments:
                if comment_text and isinstance(comment_text, str):
                    resolved.append({
                        "lineType": "Comment",
                        "lineObjectNumber": "",
                        "description": comment_text[:100],
                        "quantity": 0,
                        "unitPrice": 0,
                        "source": "extracted_comment",
                        "mapping": {
                            "matched": False, "target_type": "comment", "target_no": "",
                            "confidence": 0, "method": "none", "mapping_id": None,
                            "catalog_validated": False,
                        },
                    })
    else:
        # Fallback: create a single line from the document total
        amount = nf.get("amount") or ef.get("amount")
        if amount is not None:
            amount = float(amount)
        doc_desc = ef.get("description") or nf.get("description") or ""
        fallback_desc = doc_desc[:80] if doc_desc else "Imported from Document Hub"

        fallback_mapping = {
            "matched": False, "item_number": "", "confidence": 0,
            "method": "none", "mapping_id": None,
        }

        if BC_SO_FALLBACK_GL_ACCOUNT:
            resolved.append({
                "lineType": "Account",
                "lineObjectNumber": BC_SO_FALLBACK_GL_ACCOUNT,
                "description": fallback_desc,
                "quantity": 1,
                "unitPrice": amount or 0,
                "source": "fallback_gl_account",
                "mapping": fallback_mapping,
            })
        elif BC_SO_FALLBACK_ITEM_CODE:
            resolved.append({
                "lineType": "Item",
                "lineObjectNumber": BC_SO_FALLBACK_ITEM_CODE,
                "description": fallback_desc,
                "quantity": 1,
                "unitPrice": amount or 0,
                "source": "fallback_item",
                "mapping": fallback_mapping,
            })
        elif amount and amount > 0:
            resolved.append({
                "lineType": "Comment",
                "lineObjectNumber": "",
                "description": fallback_desc,
                "quantity": 1,
                "unitPrice": amount,
                "source": "fallback_amount_only",
                "mapping": fallback_mapping,
            })

    return resolved


@router.post("/sales-orders/preflight/{doc_id}")
async def sales_order_preflight(doc_id: str):
    """Preflight validation: structured review data before BC Sales Order creation.

    Returns document_summary, validation_checklist, resolved_lines (with mapping metadata),
    mapped_values, warnings, errors, and overall readiness.
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
            "document_summary": {},
            "validation_checklist": [],
            "mapped_values": {},
            "missing_fields": [],
            "warnings": ["A BC Sales Order has already been created for this document."],
            "errors": [],
            "resolved_lines": [],
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
    amount = nf.get("amount") or ef.get("amount")

    if not external_doc_no:
        missing_fields.append("external_doc_no")
        warnings.append("No PO number / external document number found.")

    if not order_date:
        missing_fields.append("order_date")
        warnings.append("No order date extracted. Current date will be used as fallback.")

    # Resolve sales lines (extracted or fallback) with item mapping
    resolved_lines = await _resolve_sales_lines(doc, customer_no=customer_no or "")

    # Auto-suggest dunnage lines from learned patterns
    suggested_lines = []
    if customer_no and resolved_lines:
        try:
            from services.order_line_patterns import get_suggested_lines, learn_from_bc_posted_orders
            # Check if customer-level patterns exist; if not, try learning from BC
            has_customer_pattern = await db.order_line_patterns.find_one(
                {"customer_no": customer_no, "trigger_item_no": "*"}, {"_id": 1}
            )
            if not has_customer_pattern:
                try:
                    await learn_from_bc_posted_orders(db, customer_no, order_limit=10, threshold=0.75)
                except Exception as e:
                    logger.debug("[Preflight] BC pattern learning skipped: %s", str(e))

            main_items = [ln for ln in resolved_lines if ln.get("lineType") != "Comment" and ln.get("unitPrice", 0) > 0]
            suggested_lines = await get_suggested_lines(db, customer_no, main_items)
            if suggested_lines:
                for sl in suggested_lines:
                    resolved_lines.append({
                        "lineType": sl["line_type"],
                        "lineObjectNumber": sl.get("item_no", ""),
                        "description": sl["description"],
                        "quantity": sl.get("quantity", 0),
                        "unitPrice": sl.get("unit_price", 0),
                        "source": "learned_pattern",
                        "suggested": True,
                        "pattern_confidence": sl.get("confidence", 0),
                        "pattern_frequency": sl.get("frequency", 0),
                        "pattern_occurrences": sl.get("occurrences", 0),
                        "trigger_item": sl.get("trigger_item", ""),
                        "qty_ratio": sl.get("qty_ratio"),
                        "fixed_qty": sl.get("fixed_qty"),
                        "mapping": {
                            "matched": bool(sl.get("item_no")),
                            "target_type": "item" if sl.get("item_no") else "comment",
                            "target_no": sl.get("item_no", ""),
                            "confidence": sl.get("confidence", 0),
                            "method": "learned_pattern",
                            "mapping_id": None,
                            "catalog_validated": False,
                        },
                    })
                warnings.append(f"{len(suggested_lines)} dunnage line(s) auto-suggested from {suggested_lines[0].get('occurrences', 0)}+ historical orders.")
        except Exception as e:
            logger.warning("[Preflight] Pattern suggestion error: %s", str(e))

    if not resolved_lines:
        errors.append("No sales lines could be resolved. The document has no extracted line items, no total amount, and no fallback G/L account or item code is configured. Header-only orders are not allowed.")
    else:
        line_sources = set(ln["source"] for ln in resolved_lines)
        mapped_count = sum(1 for ln in resolved_lines if ln.get("mapping", {}).get("matched"))
        unmapped_count = len(resolved_lines) - mapped_count

        if "fallback_gl_account" in line_sources:
            warnings.append(f"No line items extracted. A fallback line will be created using G/L Account '{BC_SO_FALLBACK_GL_ACCOUNT}' with the document total amount.")
        elif "fallback_item" in line_sources:
            warnings.append(f"No line items extracted. A fallback line will be created using item '{BC_SO_FALLBACK_ITEM_CODE}' with the document total amount.")
        elif "fallback_amount_only" in line_sources:
            warnings.append("No line items extracted. A comment line will be created with the document total amount. Configure BC_SO_FALLBACK_GL_ACCOUNT for proper G/L posting.")

        if mapped_count > 0:
            warnings.append(f"{mapped_count} of {len(resolved_lines)} line(s) mapped to BC item/GL targets.")
        if unmapped_count > 0 and "mapped" in line_sources:
            warnings.append(f"{unmapped_count} line(s) could not be mapped and will be created as Comment lines.")

    # Integration status
    if not HAS_CREDENTIALS:
        errors.append("BC credentials are not configured. Cannot create orders until credentials are set.")

    # Compute BC environment info
    from services.gpi_integration_service import BC_WRITE_ENVIRONMENT, BC_READ_ENVIRONMENT, BC_COMPANY_ID
    bc_company = BC_COMPANY_ID or "auto-detect"

    ready = eligible and bool(customer_no) and bool(resolved_lines) and not errors

    idempotency_key = _build_idempotency_key(doc_id)

    # ── Inventory Lookup ──
    inventory_workspace = None
    inventory_summary = None
    try:
        from services.inventory_so_integration import resolve_inventory_workspace, enrich_lines_with_inventory
        ws_result = await resolve_inventory_workspace(db, customer_no=customer_no or "", customer_name=customer_name or "")
        inventory_workspace = ws_result.get("workspace")
        all_workspaces = ws_result.get("all_workspaces", [])

        if inventory_workspace and resolved_lines:
            resolved_lines, inventory_summary = await enrich_lines_with_inventory(db, inventory_workspace["id"], resolved_lines)
            inventory_summary["workspace_name"] = inventory_workspace["name"]
            inventory_summary["workspace_code"] = inventory_workspace["code"]
            inventory_summary["negative_balance_policy"] = inventory_workspace.get("negative_balance_policy", "warn_only")
            inventory_summary["match_method"] = ws_result["match_method"]

            if inventory_summary["lines_short"] > 0:
                warnings.append(f"{inventory_summary['lines_short']} line(s) have inventory shortages in the {inventory_workspace['name']} workspace.")
        elif not inventory_workspace and all_workspaces:
            inventory_summary = {
                "workspace_id": None,
                "workspace_name": None,
                "lines_matched": 0, "lines_short": 0, "lines_no_match": len(resolved_lines) if resolved_lines else 0,
                "total_lines": len(resolved_lines) if resolved_lines else 0,
                "match_method": "no_match",
                "available_workspaces": [{"id": w["id"], "name": w["name"], "code": w["code"]} for w in all_workspaces],
            }
    except Exception as inv_err:
        logger.warning("Inventory lookup failed during preflight: %s", inv_err)

    # ── Document Summary ──
    capture_channel = doc.get("capture_channel", "")
    source_display = capture_channel.replace("_", " ").title() if capture_channel else (
        "Email" if doc.get("email_message_id") else "Upload"
    )
    extracted_field_count = sum(1 for v in ef.values() if v)
    total_possible_fields = max(len(ef), 1)
    extraction_completeness = round(extracted_field_count / total_possible_fields, 2)

    document_summary = {
        "document_id": doc_id,
        "file_name": doc.get("file_name", ""),
        "source": source_display,
        "document_type": doc_type,
        "customer_no": customer_no,
        "customer_name": customer_name,
        "external_doc_no": external_doc_no,
        "order_date": order_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
        "order_date_source": "extracted" if order_date else "fallback_today",
        "total_amount": amount,
        "extraction_completeness": extraction_completeness,
    }

    # ── SO Type Routing ──
    so_type = _resolve_so_type(doc)
    so_routing = _resolve_so_routing_fields(doc, so_type)
    document_summary["so_type"] = so_type

    # ── Duplicate Check ──
    duplicate_found = False
    duplicate_detail = "No duplicate found"
    if external_doc_no:
        dup = await db.hub_documents.find_one(
            {"id": {"$ne": doc_id}, "bc_sales_order.external_doc_no": external_doc_no, "bc_sales_order.success": True},
            {"_id": 0, "id": 1, "bc_sales_order.bc_record_no": 1},
        )
        if dup:
            duplicate_found = True
            dup_so = (dup.get("bc_sales_order") or {}).get("bc_record_no", "?")
            duplicate_detail = f"PO '{external_doc_no}' already used on SO {dup_so} (doc {dup['id'][:8]}...)"
            warnings.append(duplicate_detail)

    # ── Quantity Bounds Check ──
    bounds_check = {"in_bounds": True, "violations": []}
    if customer_no and resolved_lines:
        try:
            from services.order_line_patterns import check_quantity_bounds
            main_items = [ln for ln in resolved_lines if not ln.get("suggested") and ln.get("lineType") != "Comment"]
            bounds_check = await check_quantity_bounds(db, customer_no, main_items)
            if not bounds_check["in_bounds"]:
                for v in bounds_check["violations"]:
                    errors.append(
                        f"QUANTITY OUT OF BOUNDS: {v['item_no']} — PO qty {v['po_quantity']} is outside "
                        f"historical range [{v['expected_min']}–{v['expected_max']}] "
                        f"(mean {v['mean']}, ±2σ). {v['severity'].upper()} — requires review."
                    )
                # Flag document for review
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "bounds_alert": True,
                        "bounds_violations": bounds_check["violations"],
                        "workflow_status": "bounds_review",
                    }},
                )
                ready = False  # Block approval
        except Exception as e:
            logger.warning("[Preflight] Bounds check error: %s", str(e))

    # ── Validation Checklist ──
    validation_checklist = [
        {"label": "Customer resolved in BC", "passed": bool(customer_no), "detail": f"{customer_no} — {customer_name}" if customer_no else "Not resolved"},
        {"label": "Required fields present", "passed": "customer_no" not in missing_fields, "detail": f"Missing: {', '.join(missing_fields)}" if missing_fields else "All present"},
        {"label": "Duplicate check", "passed": not duplicate_found, "detail": duplicate_detail, "blocking": False},
        {"label": "Lines resolved", "passed": bool(resolved_lines), "detail": f"{len(resolved_lines)} line(s)" if resolved_lines else "No lines"},
        {"label": "Quantity bounds check", "passed": bounds_check["in_bounds"],
         "detail": f"{len(bounds_check['violations'])} item(s) outside historical range — requires review" if not bounds_check["in_bounds"] else "All quantities within historical norms",
         "blocking": not bounds_check["in_bounds"]},
        {"label": "Extraction completeness", "passed": extraction_completeness >= 0.5, "detail": f"{int(extraction_completeness * 100)}% of fields extracted", "blocking": False},
        {"label": "BC credentials configured", "passed": HAS_CREDENTIALS, "detail": "Connected" if HAS_CREDENTIALS else "Not configured"},
    ]

    return {
        "eligible": eligible,
        "ready": ready,
        "already_created": False,
        "existing_sales_order": None,
        "document_summary": document_summary,
        "validation_checklist": validation_checklist,
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
            "bc_read_environment": BC_READ_ENVIRONMENT,
            "bc_write_environment": BC_WRITE_ENVIRONMENT,
            "bc_environment": f"Read: {BC_READ_ENVIRONMENT} / Write: {BC_WRITE_ENVIRONMENT}",
            "idempotency_key": idempotency_key,
            "so_type": so_type,
            "so_routing": so_routing,
        },
        "resolved_lines": resolved_lines,
        "line_count": len(resolved_lines),
        "missing_fields": missing_fields,
        "warnings": warnings,
        "errors": errors,
        "inventory_summary": inventory_summary,
        "inventory_workspace": {
            "id": inventory_workspace["id"],
            "name": inventory_workspace["name"],
            "code": inventory_workspace["code"],
            "negative_balance_policy": inventory_workspace.get("negative_balance_policy", "warn_only"),
        } if inventory_workspace else None,
        "bounds_check": bounds_check,
    }


class CreateSOFromDocumentRequest(BaseModel):
    """Request body for creating a Sales Order from a document with user-edited lines."""
    customer_no_override: str = Field("", description="Override customer number")
    edited_lines: list = Field(default=None, description="User-edited lines (source of truth if provided)")
    inventory_workspace_id: str = Field("", description="Inventory workspace ID for commitment creation")


async def _validate_edited_lines(db, lines: list) -> dict:
    """Validate user-edited line targets against the synced catalog.
    Returns {valid: bool, lines: [...with validation], errors: [...]}.
    """
    from services.item_mapping_service import _validate_target
    validated = []
    validation_errors = []
    for i, ln in enumerate(lines):
        lt = ln.get("lineType", "Comment")
        obj = ln.get("lineObjectNumber", "")
        target_type = "gl_account" if lt == "Account" else "item" if lt == "Item" else "comment"

        catalog_check = {"valid": True, "reason": "comment", "description": ""}
        if target_type != "comment" and obj:
            catalog_check = await _validate_target(db, target_type, obj)
            if not catalog_check.get("valid"):
                validation_errors.append({
                    "line": i,
                    "target_type": target_type,
                    "target_no": obj,
                    "reason": catalog_check.get("reason", "unknown"),
                    "message": f"Line {i+1}: {target_type} '{obj}' {catalog_check.get('reason', 'invalid')}",
                })

        v_line = {**ln, "_catalog_valid": catalog_check.get("valid", True), "_catalog_desc": catalog_check.get("description", "")}
        validated.append(v_line)

    return {"valid": len(validation_errors) == 0, "lines": validated, "errors": validation_errors}


@router.post("/sales-orders/from-document/{doc_id}")
async def create_sales_order_from_document(doc_id: str, body: CreateSOFromDocumentRequest = None, request: Request = None):
    """Create a BC Sales Order from a GPI Hub document.

    If `edited_lines` are provided in the body, they are used as the source of truth
    (no re-resolution). Each line's target is validated against the synced catalog.
    If `edited_lines` is null/empty, lines are auto-resolved from document data.
    """
    if not HAS_CREDENTIALS:
        raise HTTPException(status_code=503, detail="BC credentials not configured")

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Parse body — support both JSON body and query param for backwards compat
    customer_no_override = ""
    user_edited_lines = None
    inv_workspace_id = ""
    if body:
        customer_no_override = body.customer_no_override or ""
        user_edited_lines = body.edited_lines
        inv_workspace_id = body.inventory_workspace_id or ""
    elif request:
        try:
            raw = await request.json()
            customer_no_override = raw.get("customer_no_override", "")
            user_edited_lines = raw.get("edited_lines")
            inv_workspace_id = raw.get("inventory_workspace_id", "")
        except Exception:
            pass

    # Check for existing SO (idempotency)
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
            "lines_added": existing_so.get("lines_added", 0),
            "lines_total": existing_so.get("lines_total", 0),
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

    # Determine lines: user-edited (source of truth) vs auto-resolved
    original_resolved_lines = await _resolve_sales_lines(doc, customer_no=customer_no)

    if user_edited_lines and len(user_edited_lines) > 0:
        # Validate user-edited targets against catalog
        validation = await _validate_edited_lines(db, user_edited_lines)
        if not validation["valid"]:
            raise HTTPException(status_code=422, detail={
                "error": "catalog_validation_failed",
                "message": "Some edited line targets are not valid in the BC catalog.",
                "validation_errors": validation["errors"],
            })
        submitted_lines = user_edited_lines
    else:
        submitted_lines = original_resolved_lines

    if not submitted_lines:
        raise HTTPException(status_code=422, detail={
            "error": "no_lines",
            "message": "Cannot create Sales Order: no sales lines to submit.",
        })

    external_doc_no = ef.get("po_number") or nf.get("po_number") or ""
    order_date = ef.get("order_date") or nf.get("order_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")

    # Resolve SO type routing (Drop-Ship vs Warehouse)
    so_type = _resolve_so_type(doc)
    so_routing = _resolve_so_routing_fields(doc, so_type)

    idempotency_key = _build_idempotency_key(doc_id)
    transaction_id = f"TXN_{uuid.uuid4().hex[:12]}"

    # Step 1: Create SO header via GPI custom API
    try:
        result = await create_sales_order(
            customer_no=customer_no,
            external_doc_no=external_doc_no,
            order_date=order_date,
            source_doc_id=doc_id,
            idempotency_key=idempotency_key,
            transaction_id=transaction_id,
            ship_to_code=so_routing.get("ship_to_code", ""),
            ship_to_name=so_routing.get("ship_to_name", ""),
            location_code=so_routing.get("location_code", ""),
        )
    except Exception as e:
        logger.error("Failed to create sales order header from doc %s: %s", doc_id, str(e))
        raise HTTPException(status_code=502, detail=f"BC API error (header): {str(e)}")

    if not result.get("success"):
        raise HTTPException(status_code=502, detail=f"BC header creation failed: {result.get('error_message', 'Unknown error')}")

    bc_system_id = result.get("bc_system_id", "")
    bc_record_no = result.get("bc_record_no", "")

    # Step 2: Add lines to the created SO via standard BC API
    line_result = {"added": 0, "total": len(submitted_lines), "errors": []}
    if bc_system_id:
        try:
            line_result = await add_sales_order_lines(bc_system_id, submitted_lines)
            logger.info("Added %d/%d lines to SO %s", line_result["added"], line_result["total"], bc_record_no)
        except Exception as e:
            logger.error("Failed to add lines to SO %s: %s", bc_record_no, str(e))
            line_result["errors"].append({"line": 0, "error": str(e)})
    else:
        logger.warning("No bc_system_id returned for SO %s — cannot add lines", bc_record_no)

    now = datetime.now(timezone.utc).isoformat()

    # Record mapping history for audit
    for idx, line in enumerate(submitted_lines):
        mapping_meta = line.get("mapping", {})
        try:
            await record_mapping_history(
                db, doc_id=doc_id, line_index=idx,
                description=line.get("description", ""),
                mapping_result=mapping_meta,
                customer_no=customer_no,
            )
        except Exception as mh_err:
            logger.warning("Failed to record mapping history for line %d: %s", idx, mh_err)

    # ── Audit log: store both original and submitted lines ──
    audit_entry = {
        "id": str(uuid.uuid4()),
        "doc_id": doc_id,
        "bc_record_no": bc_record_no,
        "bc_system_id": bc_system_id,
        "customer_no": customer_no,
        "customer_name": customer_info["customer_name"],
        "external_doc_no": external_doc_no,
        "order_date": order_date,
        "idempotency_key": idempotency_key,
        "transaction_id": transaction_id,
        "so_type": so_type,
        "so_routing": so_routing,
        "original_resolved_lines": _sanitize_lines(original_resolved_lines),
        "submitted_lines": _sanitize_lines(submitted_lines),
        "lines_were_edited": user_edited_lines is not None and len(user_edited_lines) > 0,
        "lines_added": line_result["added"],
        "lines_total": line_result["total"],
        "line_errors": line_result["errors"],
        "success": result.get("success", False),
        "status": result.get("status", ""),
        "error_message": result.get("error_message", ""),
        "created_at": now,
        "created_by": "gpi_hub",
    }
    try:
        await db.bc_so_creation_audit.insert_one(audit_entry)
    except Exception as ae:
        logger.warning("Failed to write SO creation audit: %s", ae)

    # ── Inventory Commitment Creation ──
    commitment_result = None
    if inv_workspace_id and result.get("success") and result.get("status") != "already_exists":
        try:
            from services.inventory_so_integration import create_order_commitments
            commitment_result = await create_order_commitments(
                db,
                workspace_id=inv_workspace_id,
                doc_id=doc_id,
                bc_record_no=bc_record_no,
                transaction_id=transaction_id,
                submitted_lines=submitted_lines,
                customer_no=customer_no,
                created_by="gpi_hub",
            )
            if commitment_result.get("blocked", 0) > 0:
                logger.warning("Some inventory commitments blocked for SO %s: %s", bc_record_no, commitment_result["errors"])
        except Exception as inv_err:
            logger.warning("Inventory commitment creation failed for SO %s: %s", bc_record_no, inv_err)
            commitment_result = {"committed": 0, "errors": [str(inv_err)]}

    bc_sales_order = {
        "bc_record_no": bc_record_no,
        "bc_system_id": bc_system_id,
        "idempotency_key": idempotency_key,
        "transaction_id": transaction_id,
        "status": result.get("status", ""),
        "success": result.get("success", False),
        "customer_no": customer_no,
        "customer_name": customer_info["customer_name"],
        "external_doc_no": external_doc_no,
        "order_date": order_date,
        "so_type": so_type,
        "so_routing": so_routing,
        "lines_added": line_result["added"],
        "lines_total": line_result["total"],
        "line_errors": line_result["errors"],
        "resolved_lines": _sanitize_lines(submitted_lines),
        "created_at": now,
        "created_by": "gpi_hub",
        "error_message": result.get("error_message", ""),
        "inventory_commitments": commitment_result,
    }

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "bc_sales_order": bc_sales_order,
            "so_type": so_type,
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
                event_type="bc.sales_order.created" if result.get("success") else "bc.sales_order.failed",
                source_service="gpi_integration",
                payload={
                    "bc_record_no": bc_record_no,
                    "customer_no": customer_no,
                    "external_doc_no": external_doc_no,
                    "idempotency_key": idempotency_key,
                    "status": result.get("status", ""),
                    "lines_added": line_result["added"],
                    "lines_total": line_result["total"],
                    "lines_were_edited": user_edited_lines is not None,
                    "so_type": so_type,
                },
                actor="system",
            )
    except Exception as evt_err:
        logger.warning("Failed to emit BC sales order event: %s", evt_err)

    # ── Auto-approve dropship SOs ──
    ds_auto_approved = False
    if so_type == "dropship" and result.get("success") and result.get("status") != "already_exists":
        try:
            ds_auto_approved = await _auto_approve_dropship_so(db, doc_id, bc_record_no, so_type)
        except Exception as ds_err:
            logger.warning("Dropship auto-approve failed for SO %s: %s", bc_record_no, ds_err)
        # Set ds_po_pending flag for the DS PO auto-creation path
        try:
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "ds_po_pending": True,
                    "so_subtype": "DS_Sales_Order",
                    "bc_record_id": bc_system_id,
                    "bc_record_no": bc_record_no,
                }},
            )
        except Exception:
            pass
        # Fire DS PO auto-creation as a background task
        try:
            import asyncio
            asyncio.create_task(_ds_po_auto_create_background(db, doc_id, bc_record_no))
        except Exception as ds_bg_err:
            logger.warning("DS PO background task spawn failed for SO %s: %s", bc_record_no, ds_bg_err)

    # ── Warehouse SO Booked Notifications ──
    notification_results = None
    if so_type == "warehouse" and result.get("success") and result.get("status") != "already_exists":
        try:
            from services.notification_service import on_warehouse_so_booked
            notification_results = await on_warehouse_so_booked(
                doc, bc_sales_order, dry_run=False, db=db,
            )
        except Exception as notif_err:
            logger.warning("Warehouse SO notification failed for SO %s: %s", bc_record_no, notif_err)
        # Tag subtype
        try:
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {"so_subtype": "WH_Sales_Order"}},
            )
        except Exception:
            pass

    return {
        "success": result.get("success", False),
        "already_exists": result.get("status") == "already_exists",
        "bc_record_no": bc_record_no,
        "bc_system_id": bc_system_id,
        "idempotency_key": idempotency_key,
        "transaction_id": transaction_id,
        "status": result.get("status", ""),
        "message": f"Sales Order {bc_record_no} created with {line_result['added']}/{line_result['total']} lines" if result.get("success") else result.get("error_message", "Creation failed"),
        "error_message": result.get("error_message", ""),
        "so_type": so_type,
        "so_routing": so_routing,
        "ds_auto_approved": ds_auto_approved,
        "lines_added": line_result["added"],
        "lines_total": line_result["total"],
        "line_errors": line_result["errors"],
        "created_at": now,
        "inventory_commitments": commitment_result,
        "notification_results": notification_results,
    }


async def _ds_po_auto_create_background(db, doc_id: str, bc_so_no: str):
    """Background task: wait briefly for BC to process the SO release, then auto-create the DS PO."""
    import asyncio
    # Small delay to allow BC to process the SO approval/release
    await asyncio.sleep(2)
    try:
        result = await ds_po_auto_create(doc_id)
        if result.get("success"):
            logger.info("[DS-PO-BG] Auto-created PO %s for SO %s (doc %s)",
                        result.get("ds_po_id"), bc_so_no, doc_id[:8])
        else:
            logger.info("[DS-PO-BG] PO not created for SO %s: %s",
                        bc_so_no, result.get("reason", result.get("status", "unknown")))
    except Exception as e:
        logger.warning("[DS-PO-BG] Auto-create failed for SO %s: %s", bc_so_no, str(e))


async def _auto_approve_dropship_so(db, doc_id: str, bc_record_no: str, so_type: str) -> bool:
    """Auto-approve a Drop-Ship Sales Order after successful BC creation.

    Drop-Ship POs bypass the normal warehouse approval workflow because
    goods ship directly from the vendor to the customer. The SO is
    auto-advanced to 'approved' status in the workflow engine.

    Returns True if auto-approve succeeded.
    """
    if so_type != "dropship":
        return False

    from services.workflow_engine import WorkflowEngine, WorkflowEvent

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        logger.warning("[DS-AutoApprove] Document %s not found", doc_id)
        return False

    current_status = doc.get("workflow_status")

    # Try to advance through the approval path
    # The document may be in various states; we try the most likely transitions
    engine = WorkflowEngine()
    advanced = False

    # First try: mark ready for approval (if in extracted/classified state)
    if current_status in ("extracted", "classified", "captured"):
        _, _, ok = engine.advance_workflow(
            doc, WorkflowEvent.ON_MARK_READY_FOR_APPROVAL.value,
            context={"reason": f"Drop-ship SO {bc_record_no} auto-approved", "metadata": {"so_type": "dropship", "bc_record_no": bc_record_no}},
            actor="ds_auto_approve",
        )
        if ok:
            current_status = doc.get("workflow_status")
            advanced = True

    # Second try: auto-approve (if in ready_for_approval state)
    if current_status == "ready_for_approval":
        _, _, ok = engine.advance_workflow(
            doc, WorkflowEvent.ON_APPROVED.value,
            context={"reason": f"Drop-ship SO {bc_record_no} auto-approved — direct ship to customer", "metadata": {"so_type": "dropship", "bc_record_no": bc_record_no}},
            actor="ds_auto_approve",
        )
        if ok:
            advanced = True

    if advanced:
        now = datetime.now(timezone.utc).isoformat()
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "workflow_status": doc.get("workflow_status"),
                "workflow_history": doc.get("workflow_history", []),
                "workflow_status_updated_utc": now,
                "ds_auto_approved": True,
                "ds_auto_approved_at": now,
                "updated_utc": now,
            }}
        )
        logger.info("[DS-AutoApprove] SO %s (doc %s) auto-approved as dropship", bc_record_no, doc_id)
        return True

    logger.info("[DS-AutoApprove] Could not auto-approve SO %s (doc %s) — current status: %s", bc_record_no, doc_id, current_status)
    return False


@router.post("/ds-purchase-orders/auto-create/{doc_id}")
async def ds_po_auto_create(doc_id: str):
    """Auto-create a Drop-Ship Purchase Order from a DS_Sales_Order document.

    Requires: doc_type=DS_Sales_Order, ds_po_pending=True, BC SO status=Released.
    Idempotent: if ds_po_created is already True, returns existing PO info.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    doc_type = doc.get("suggested_job_type") or doc.get("document_type") or ""
    if doc_type != "DS_Sales_Order":
        raise HTTPException(status_code=400, detail=f"Not a DS_Sales_Order (type={doc_type})")

    # Idempotency check
    if doc.get("ds_po_created"):
        return {
            "success": True,
            "status": "already_created",
            "ds_po_id": doc.get("ds_po_id", ""),
            "doc_id": doc_id,
        }

    if not doc.get("ds_po_pending"):
        raise HTTPException(status_code=400, detail="ds_po_pending is not True — SO not yet created in BC")

    # Verify BC SO status is Released
    bc_so_id = doc.get("bc_record_id") or doc.get("bc_system_id") or ""
    bc_so_no = doc.get("bc_record_no") or ""
    if not bc_so_id and not bc_so_no:
        raise HTTPException(status_code=400, detail="No BC SO record linked to this document")

    so_status = "unknown"
    if HAS_CREDENTIALS:
        try:
            from services.gpi_integration_service import _api_request
            if bc_so_id:
                so_data = await _api_request("GET", f"salesOrders({bc_so_id})")
            else:
                so_data = await _api_request("GET", "salesOrders", params={"$filter": f"number eq '{bc_so_no}'"})
                if isinstance(so_data, dict) and "value" in so_data:
                    so_data = so_data["value"][0] if so_data["value"] else {}
            so_status = (so_data.get("status") or so_data.get("resultStatus") or "").lower()
        except Exception as e:
            logger.warning("[DS-PO] Failed to verify SO status for %s: %s", doc_id, e)
            # In demo mode, allow proceeding
            if os.environ.get("DEMO_MODE", "").lower() == "true":
                so_status = "released"
            else:
                raise HTTPException(status_code=502, detail=f"Cannot verify SO status: {e}")
    else:
        # No BC credentials — check demo mode
        if os.environ.get("DEMO_MODE", "").lower() == "true":
            so_status = "released"
        else:
            raise HTTPException(status_code=503, detail="BC credentials not configured")

    if so_status != "released":
        return {
            "success": False,
            "reason": "so_not_released",
            "so_status": so_status,
            "doc_id": doc_id,
        }

    # Resolve vendor number
    vendor_no = doc.get("vendor_no") or doc.get("vendor_canonical") or ""
    if not vendor_no:
        ef = doc.get("extracted_fields") or {}
        vendor_no = ef.get("vendor_no") or ef.get("vendor") or ""
    if not vendor_no:
        raise HTTPException(status_code=400, detail="No vendor resolved for DS PO creation")

    # Resolve external doc number (SO number or customer PO)
    ef = doc.get("extracted_fields") or {}
    ext_doc_no = bc_so_no or ef.get("po_number") or ef.get("external_document_number") or ""

    # Create the PO in BC
    now = datetime.now(timezone.utc).isoformat()
    if HAS_CREDENTIALS:
        try:
            from services.gpi_integration_service import create_purchase_order
            po_result = await create_purchase_order(
                vendor_no=vendor_no,
                external_doc_no=ext_doc_no,
                source_doc_id=doc_id,
            )
        except Exception as e:
            raise HTTPException(status_code=502, detail=f"BC PO creation failed: {e}")
    else:
        # Demo mode — simulate
        import uuid as _uuid
        po_result = {
            "success": True,
            "bc_record_no": f"PO-DEMO-{_uuid.uuid4().hex[:6]}",
            "bc_system_id": f"demo-{_uuid.uuid4().hex[:8]}",
            "status": "created",
        }

    if not po_result.get("success"):
        return {
            "success": False,
            "reason": "bc_creation_failed",
            "error_message": po_result.get("error_message", "Unknown"),
            "doc_id": doc_id,
        }

    # Update document
    ds_po_id = po_result.get("bc_record_no") or po_result.get("bc_system_id") or ""
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "ds_po_created": True,
            "ds_po_id": ds_po_id,
            "ds_po_bc_system_id": po_result.get("bc_system_id", ""),
            "ds_po_pending": False,
            "ds_po_created_at": now,
            "ds_po_vendor_no": vendor_no,
        }},
    )

    # Create activity record
    await db.document_activities.insert_one({
        "document_id": doc_id,
        "activity_type": "ds_po_created",
        "details": {
            "po_number": ds_po_id,
            "vendor_no": vendor_no,
            "so_number": bc_so_no,
            "external_doc_no": ext_doc_no,
        },
        "created_at": now,
        "actor": "ds_auto_create",
    })

    logger.info("[DS-PO] Created PO %s for DS SO doc=%s vendor=%s", ds_po_id, doc_id[:8], vendor_no)

    return {
        "success": True,
        "status": "created",
        "ds_po_id": ds_po_id,
        "ds_po_bc_system_id": po_result.get("bc_system_id", ""),
        "vendor_no": vendor_no,
        "so_number": bc_so_no,
        "doc_id": doc_id,
    }


def _sanitize_lines(lines: list) -> list:
    """Strip internal fields from lines for storage."""
    sanitized = []
    for ln in (lines or []):
        clean = {k: v for k, v in ln.items() if not k.startswith("_")}
        sanitized.append(clean)
    return sanitized


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


async def auto_create_pi_from_document(doc_id: str, db) -> dict:
    """Automatically create a Purchase Invoice in BC sandbox from an auto-cleared AP_Invoice.
    
    Called from the intake pipeline after a document is auto-cleared.
    Returns a result dict with success/failure info. Never raises — all errors are caught.
    """
    try:
        doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        if not doc:
            return {"success": False, "reason": "document_not_found"}

        # Only AP_Invoice eligible
        doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
        if doc_type not in PURCHASE_INVOICE_ELIGIBLE_TYPES:
            return {"success": False, "reason": f"ineligible_type:{doc_type}", "skipped": True}

        # Skip if PI already exists
        if doc.get("bc_purchase_invoice"):
            return {"success": True, "reason": "already_exists", "skipped": True,
                    "bc_record_no": doc["bc_purchase_invoice"].get("bc_record_no", "")}

        if not HAS_CREDENTIALS:
            return {"success": False, "reason": "no_bc_credentials"}

        # Check BC write safety guard
        from services.bc_write_safety_guard import check_bc_write_allowed
        write_ok = await check_bc_write_allowed(doc_id, "auto_create_purchase_invoice")
        if not write_ok:
            return {"success": False, "reason": "bc_writes_disabled"}

        # ---- AP Validation (duplicate check, PO amount within 10%, required fields) ----
        from services.ap_validation_service import APValidationService
        from services.business_central_service import BusinessCentralService
        bc_svc = BusinessCentralService()
        ap_validator = APValidationService(db, bc_service=bc_svc)

        ef = doc.get("extracted_fields") or {}
        nf = doc.get("normalized_fields") or {}

        # Resolve vendor first (needed for validation)
        vendor_info = await _resolve_vendor_no(doc)
        vendor_no = vendor_info.get("vendor_no")
        vendor_match_result = {
            "matched": bool(vendor_no),
            "bc_vendor_number": vendor_no,
            "best_match": {"vendor_number": vendor_no, "name": vendor_info.get("vendor_name", "")},
            "source": vendor_info.get("match_method", ""),
            "score": vendor_info.get("match_score", 0),
        }

        validation = await ap_validator.validate_ap_invoice(doc, {**ef, **nf}, vendor_match_result)
        val_dict = validation.to_dict()

        # Store validation results on the document
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {"ap_validation": val_dict, "updated_utc": datetime.now(timezone.utc).isoformat()}}
        )

        if not val_dict["all_passed"]:
            logger.warning("[AutoPI] AP validation FAILED for doc %s: %s", doc_id, val_dict["blocking_issues"])
            return {
                "success": False,
                "reason": "ap_validation_failed",
                "blocking_issues": val_dict["blocking_issues"],
                "validation": val_dict,
            }

        logger.info("[AutoPI] AP validation passed for doc %s (state=%s, warnings=%d)",
                    doc_id, val_dict["validation_state"], len(val_dict["warnings"]))
        if not vendor_no:
            return {"success": False, "reason": "no_vendor_resolved"}

        vendor_invoice_no = ef.get("invoice_number") or nf.get("invoice_number") or ""
        document_date = ef.get("invoice_date") or nf.get("invoice_date") or datetime.now(timezone.utc).strftime("%Y-%m-%d")
        idempotency_key = _build_pi_idempotency_key(doc_id)
        transaction_id = f"TXN_{uuid.uuid4().hex[:12]}"

        # Step 1: Create PI header
        result = await create_purchase_invoice(
            vendor_no=vendor_no,
            vendor_invoice_no=vendor_invoice_no,
            document_date=document_date,
            posting_date=document_date,
            source_doc_id=doc_id,
            idempotency_key=idempotency_key,
            transaction_id=transaction_id,
        )

        if not result.get("success"):
            logger.error("[AutoPI] Failed to create PI for doc %s: %s", doc_id, result.get("error_message", ""))
            return {"success": False, "reason": "bc_api_error", "error": result.get("error_message", "")}

        # Step 2: Add line items using AI-driven item mapping
        line_results = None
        if result.get("bc_system_id"):
            bc_lines = await _build_pi_lines_with_mapping(doc, db, vendor_no=vendor_no)

            if bc_lines:
                try:
                    line_results = await add_purchase_invoice_lines(
                        invoice_system_id=result["bc_system_id"],
                        lines=bc_lines,
                    )
                except Exception as e:
                    logger.error("[AutoPI] Failed to add lines for doc %s: %s", doc_id, str(e))
                    line_results = {"added": 0, "total": len(bc_lines), "errors": [{"error": str(e)}]}

        # Step 3: Create GPI Document Link
        link_result = None
        if result.get("bc_system_id"):
            try:
                link_result = await create_gpi_document_link(
                    bc_system_id=result["bc_system_id"],
                    bc_document_no=result.get("bc_record_no", ""),
                    document_type="Purchase Invoice",
                    sharepoint_url=doc.get("sharepoint_share_link_url", ""),
                    sharepoint_drive_id=doc.get("sharepoint_drive_id", ""),
                    sharepoint_item_id=doc.get("sharepoint_item_id", ""),
                    uploaded_by="GPI Hub",
                    source="GPIHub_Auto",
                )
            except Exception as link_err:
                logger.warning("[AutoPI] GPI link failed for doc %s: %s", doc_id, str(link_err))

        # Step 4: Write back to document
        now = datetime.now(timezone.utc).isoformat()
        bc_purchase_invoice = {
            "bc_record_no": result.get("bc_record_no", ""),
            "bc_system_id": result.get("bc_system_id", ""),
            "idempotency_key": idempotency_key,
            "transaction_id": transaction_id,
            "status": result.get("status", ""),
            "success": True,
            "vendor_no": vendor_no,
            "vendor_name": vendor_info.get("vendor_name", ""),
            "vendor_invoice_no": vendor_invoice_no,
            "document_date": document_date,
            "posting_date": document_date,
            "created_at": now,
            "created_by": "auto_pipeline",
            "lines_added": line_results["added"] if line_results else 0,
            "lines_total": line_results["total"] if line_results else 0,
            "document_linked": link_result.get("success", False) if link_result else False,
        }
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {"bc_purchase_invoice": bc_purchase_invoice, "updated_utc": now}}
        )

        # Emit event
        try:
            from services.event_service import get_event_service
            es = get_event_service()
            if es:
                await es.emit_event(
                    document_id=doc_id,
                    event_type="bc.purchase_invoice.auto_created",
                    source_service="auto_pipeline",
                    payload={
                        "bc_record_no": result.get("bc_record_no", ""),
                        "vendor_no": vendor_no,
                        "vendor_invoice_no": vendor_invoice_no,
                    },
                    actor="system",
                )
        except Exception:
            pass

        logger.info("[AutoPI] Created PI %s for doc %s (lines: %d/%d, linked: %s)",
                     result.get("bc_record_no", ""), doc_id,
                     line_results["added"] if line_results else 0,
                     line_results["total"] if line_results else 0,
                     link_result.get("success", False) if link_result else False)

        return {
            "success": True,
            "bc_record_no": result.get("bc_record_no", ""),
            "bc_system_id": result.get("bc_system_id", ""),
            "lines_added": line_results["added"] if line_results else 0,
        }

    except Exception as e:
        logger.error("[AutoPI] Unexpected error for doc %s: %s", doc_id, str(e), exc_info=True)
        return {"success": False, "reason": "unexpected_error", "error": str(e)}



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

    from services.gpi_integration_service import BC_WRITE_ENVIRONMENT, BC_READ_ENVIRONMENT, BC_COMPANY_ID
    bc_company = BC_COMPANY_ID or "auto-detect"

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
            "bc_read_environment": BC_READ_ENVIRONMENT,
            "bc_write_environment": BC_WRITE_ENVIRONMENT,
            "bc_environment": f"Read: {BC_READ_ENVIRONMENT} / Write: {BC_WRITE_ENVIRONMENT}",
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


@router.post("/purchase-invoices/retry-lines/{doc_id}")
async def retry_purchase_invoice_lines(doc_id: str):
    """Add line items to an existing BC Purchase Invoice that was created without lines.
    First deletes any existing (bad) lines, then adds correct ones.
    Uses the stored bc_system_id from the existing PI record.
    """
    if not HAS_CREDENTIALS:
        raise HTTPException(status_code=503, detail="BC credentials not configured")

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    existing_pi = doc.get("bc_purchase_invoice")
    if not existing_pi or not existing_pi.get("bc_system_id"):
        raise HTTPException(status_code=422, detail="No existing BC Purchase Invoice found for this document. Use the create endpoint instead.")

    bc_system_id = existing_pi["bc_system_id"]
    bc_record_no = existing_pi.get("bc_record_no", "")

    # Step 1: Delete existing bad lines
    delete_result = {"deleted": 0, "errors": []}
    try:
        delete_result = await delete_purchase_invoice_lines(invoice_system_id=bc_system_id)
        logger.info("PI %s: deleted %d existing lines before retry", bc_record_no, delete_result.get("deleted", 0))
    except Exception as e:
        logger.warning("PI %s: failed to delete existing lines: %s", bc_record_no, str(e))
        delete_result["errors"].append({"error": f"Delete failed: {str(e)}"})

    # Step 2: Build new lines using vendor profile-driven mapping
    vendor_no = existing_pi.get("vendor_no", "") or doc.get("bc_vendor_number", "") or doc.get("vendor_no", "")
    bc_lines = await _build_pi_lines_with_mapping(doc, db, vendor_no=vendor_no)

    if not bc_lines:
        raise HTTPException(status_code=422, detail="No line items found and no total amount to create a fallback line. Re-process the document first.")

    # Step 3: Add new correct lines
    try:
        line_results = await add_purchase_invoice_lines(
            invoice_system_id=bc_system_id,
            lines=bc_lines,
        )
    except Exception as e:
        logger.error("Failed to add lines to PI %s: %s", bc_record_no, str(e))
        raise HTTPException(status_code=502, detail=f"BC API error adding lines: {str(e)}")

    # Update the document record with line results
    now = datetime.now(timezone.utc).isoformat()
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "bc_purchase_invoice.lines_added": line_results["added"],
            "bc_purchase_invoice.lines_total": line_results["total"],
            "bc_purchase_invoice.line_errors": line_results.get("errors", []),
            "bc_purchase_invoice.lines_retried_at": now,
            "bc_purchase_invoice.lines_deleted_before_retry": delete_result.get("deleted", 0),
            "updated_utc": now,
        }}
    )

    return {
        "success": line_results["added"] > 0,
        "bc_record_no": bc_record_no,
        "bc_system_id": bc_system_id,
        "lines_deleted": delete_result.get("deleted", 0),
        "lines_added": line_results["added"],
        "lines_total": line_results["total"],
        "line_errors": line_results.get("errors", []),
        "delete_errors": delete_result.get("errors", []),
        "message": f"Deleted {delete_result.get('deleted', 0)} old lines, added {line_results['added']}/{line_results['total']} new lines to PI #{bc_record_no}",
    }


@router.post("/purchase-invoices/from-document/{doc_id}")
async def create_purchase_invoice_from_document(
    doc_id: str,
    vendor_no_override: str = Query("", description="Override vendor number"),
    force: bool = Query(False, description="Force re-creation even if PI already exists"),
):
    """Create a BC Purchase Invoice from a GPI Hub document.
    Performs preflight, creates the invoice header, adds line items, and writes back to the document graph.
    """
    if not HAS_CREDENTIALS:
        raise HTTPException(status_code=503, detail="BC credentials not configured")

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Check for existing PI
    existing_pi = doc.get("bc_purchase_invoice")
    if existing_pi and not force:
        return {
            "success": True,
            "already_exists": True,
            "bc_record_no": existing_pi.get("bc_record_no", ""),
            "bc_system_id": existing_pi.get("bc_system_id", ""),
            "idempotency_key": existing_pi.get("idempotency_key", ""),
            "status": "already_exists",
            "message": "A BC Purchase Invoice was already created for this document. Use force=true to re-create.",
            "created_at": existing_pi.get("created_at", ""),
        }

    if force and existing_pi:
        logger.info("Force re-creating PI for doc %s (previous: %s)", doc_id, existing_pi.get("bc_record_no", ""))
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {"bc_purchase_invoice_previous": existing_pi},
             "$unset": {"bc_purchase_invoice": ""}}
        )
        doc.pop("bc_purchase_invoice", None)

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

    # Step 1: Create the Purchase Invoice header
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

    # Step 2: Add line items using vendor profile-driven mapping
    line_results = None
    bc_lines = []
    if result.get("success") and result.get("bc_system_id"):
        bc_lines = await _build_pi_lines_with_mapping(doc, db, vendor_no=vendor_no)

        if bc_lines:
            try:
                line_results = await add_purchase_invoice_lines(
                    invoice_system_id=result["bc_system_id"],
                    lines=bc_lines,
                )
                logger.info("PI %s: added %d/%d lines (ref=%s)", result["bc_record_no"], 
                           line_results["added"], line_results["total"],
                           bc_lines[0].get("description", "N/A") if bc_lines else "N/A")
            except Exception as e:
                logger.error("Failed to add lines to PI %s from doc %s: %s", result.get("bc_record_no"), doc_id, str(e))
                line_results = {"added": 0, "total": len(bc_lines), "errors": [{"error": str(e)}]}

    # Step 3: Create GPI Document Link in BC (populates the GPI Documents factbox)
    link_result = None
    if result.get("success") and result.get("bc_system_id"):
        try:
            link_result = await create_gpi_document_link(
                bc_system_id=result["bc_system_id"],
                bc_document_no=result.get("bc_record_no", ""),
                document_type="Purchase Invoice",
                sharepoint_url=doc.get("sharepoint_share_link_url", ""),
                sharepoint_drive_id=doc.get("sharepoint_drive_id", ""),
                sharepoint_item_id=doc.get("sharepoint_item_id", ""),
                uploaded_by="GPI Hub",
                source="GPIHub",
            )
            if link_result.get("success"):
                logger.info("PI %s: GPI Document Link created successfully", result.get("bc_record_no", ""))
            else:
                logger.warning("PI %s: failed to create GPI Document Link: %s", result.get("bc_record_no", ""), link_result.get("error", ""))
        except Exception as link_err:
            logger.warning("PI %s: exception creating GPI Document Link: %s", result.get("bc_record_no", ""), str(link_err))

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
        "lines_added": line_results["added"] if line_results else 0,
        "lines_total": line_results["total"] if line_results else 0,
        "line_errors": line_results.get("errors", []) if line_results else [],
        "document_linked": link_result.get("success", False) if link_result else False,
        "document_link_method": link_result.get("method", "") if link_result else "",
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

    # --- Continuous Learning: teach posting patterns from every successful PI ---
    if result.get("success"):
        try:
            from services.posting_pattern_analyzer import learn_from_posting
            await learn_from_posting(
                db=db,
                vendor_no=vendor_no,
                doc=doc,
                pi_lines=bc_lines,
                pi_result=result,
            )
        except Exception as learn_err:
            logger.debug("[PostingPatterns] Learning from posting failed (non-blocking): %s", learn_err)

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
        "lines_added": line_results["added"] if line_results else 0,
        "lines_total": line_results["total"] if line_results else 0,
        "line_errors": line_results.get("errors", []) if line_results else [],
        "document_linked": link_result.get("success", False) if link_result else False,
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


@router.get("/dashboard")
async def gpi_integration_dashboard(
    record_type: str = Query("", description="Filter by record type: sales_order, purchase_invoice"),
    status: str = Query("", description="Filter by status: created, already_exists, failed"),
    limit: int = Query(100, description="Max results", le=500),
    skip: int = Query(0, description="Offset for pagination"),
):
    """Aggregated integration dashboard from local document graph data."""
    db = get_db()

    # Build pipeline to find all docs with bc_sales_order or bc_purchase_invoice
    match_stage = {}
    or_conditions = []

    if record_type == "sales_order":
        or_conditions = [{"bc_sales_order": {"$exists": True}}]
    elif record_type == "purchase_invoice":
        or_conditions = [{"bc_purchase_invoice": {"$exists": True}}]
    else:
        or_conditions = [
            {"bc_sales_order": {"$exists": True}},
            {"bc_purchase_invoice": {"$exists": True}},
        ]

    match_stage["$or"] = or_conditions

    # Fetch documents
    docs = await db.hub_documents.find(
        match_stage,
        {"_id": 0, "id": 1, "document_type": 1, "bc_sales_order": 1, "bc_purchase_invoice": 1,
         "extracted_fields": 1, "normalized_fields": 1, "vendor_canonical": 1, "file_name": 1}
    ).sort("updated_utc", -1).to_list(500)

    # Build transaction records
    transactions = []
    counts = {"sales_order_created": 0, "purchase_invoice_created": 0, "already_exists": 0, "failed": 0, "total": 0}

    for doc in docs:
        so = doc.get("bc_sales_order")
        pi = doc.get("bc_purchase_invoice")

        if so:
            so_status = so.get("status", "")
            is_success = so.get("success", False)
            txn = {
                "record_type": "Sales Order",
                "source_document_id": doc.get("id", ""),
                "source_document_name": doc.get("file_name", ""),
                "bc_record_no": so.get("bc_record_no", ""),
                "bc_system_id": so.get("bc_system_id", ""),
                "idempotency_key": so.get("idempotency_key", ""),
                "transaction_id": so.get("transaction_id", ""),
                "status": so_status,
                "success": is_success,
                "customer_no": so.get("customer_no", ""),
                "customer_name": so.get("customer_name", ""),
                "vendor_no": "",
                "vendor_name": "",
                "external_ref": so.get("external_doc_no", ""),
                "error_message": so.get("error_message", ""),
                "created_at": so.get("created_at", ""),
                "created_by": so.get("created_by", ""),
            }
            transactions.append(txn)
            counts["total"] += 1
            if so_status == "already_exists":
                counts["already_exists"] += 1
            elif is_success:
                counts["sales_order_created"] += 1
            else:
                counts["failed"] += 1

        if pi:
            pi_status = pi.get("status", "")
            is_success = pi.get("success", False)
            txn = {
                "record_type": "Purchase Invoice",
                "source_document_id": doc.get("id", ""),
                "source_document_name": doc.get("file_name", ""),
                "bc_record_no": pi.get("bc_record_no", ""),
                "bc_system_id": pi.get("bc_system_id", ""),
                "idempotency_key": pi.get("idempotency_key", ""),
                "transaction_id": pi.get("transaction_id", ""),
                "status": pi_status,
                "success": is_success,
                "customer_no": "",
                "customer_name": "",
                "vendor_no": pi.get("vendor_no", ""),
                "vendor_name": pi.get("vendor_name", ""),
                "external_ref": pi.get("vendor_invoice_no", ""),
                "error_message": pi.get("error_message", ""),
                "created_at": pi.get("created_at", ""),
                "created_by": pi.get("created_by", ""),
            }
            transactions.append(txn)
            counts["total"] += 1
            if pi_status == "already_exists":
                counts["already_exists"] += 1
            elif is_success:
                counts["purchase_invoice_created"] += 1
            else:
                counts["failed"] += 1

    # Apply status filter
    if status:
        if status == "created":
            transactions = [t for t in transactions if t["success"] and t["status"] != "already_exists"]
        elif status == "already_exists":
            transactions = [t for t in transactions if t["status"] == "already_exists"]
        elif status == "failed":
            transactions = [t for t in transactions if not t["success"] and t["status"] != "already_exists"]

    # Sort by created_at descending
    transactions.sort(key=lambda t: t.get("created_at", ""), reverse=True)

    # Paginate
    total = len(transactions)
    transactions = transactions[skip:skip + limit]

    return {
        "counts": counts,
        "transactions": transactions,
        "total": total,
        "limit": limit,
        "skip": skip,
    }


# ── Item Mapping CRUD Endpoints ──

@router.get("/item-mappings")
async def get_item_mappings(customer_no: str = "", active_only: bool = False):
    """List all item mapping rules."""
    db = get_db()
    mappings = await list_item_mappings(db, customer_no=customer_no or None, active_only=active_only)
    return {"mappings": mappings, "total": len(mappings)}


@router.post("/item-mappings")
async def create_mapping_endpoint(request: Request):
    """Create a new item mapping rule."""
    data = await request.json()
    target_no = data.get("target_no") or data.get("bc_item_number")
    if not target_no:
        raise HTTPException(status_code=422, detail="target_no (or bc_item_number) is required")
    if not data.get("keyword_phrase") and not data.get("keywords"):
        raise HTTPException(status_code=422, detail="keyword_phrase or keywords is required")
    data["target_no"] = target_no
    db = get_db()
    mapping = await create_item_mapping(db, data)
    return {"success": True, "mapping": mapping}


@router.put("/item-mappings/{mapping_id}")
async def update_mapping_endpoint(mapping_id: str, request: Request):
    """Update an existing item mapping rule."""
    data = await request.json()
    db = get_db()
    mapping = await update_item_mapping(db, mapping_id, data)
    if not mapping:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return {"success": True, "mapping": mapping}


@router.delete("/item-mappings/{mapping_id}")
async def delete_mapping_endpoint(mapping_id: str):
    """Delete an item mapping rule."""
    db = get_db()
    deleted = await delete_item_mapping(db, mapping_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Mapping not found")
    return {"success": True}


# ── BC Catalog Sync Endpoints ──

@router.get("/catalog/health")
async def get_catalog_health_endpoint():
    """Get catalog sync health summary (last sync, staleness, counts)."""
    from services.bc_catalog_sync_service import get_catalog_health
    db = get_db()
    return await get_catalog_health(db)


@router.post("/catalog/sync")
async def trigger_catalog_sync(entity: str = Query("all", description="Sync entity: items, gl_accounts, or all")):
    """Trigger a manual BC catalog sync. Reads from Production environment."""
    from services.bc_catalog_sync_service import sync_items, sync_gl_accounts, sync_all
    db = get_db()
    if entity == "items":
        result = await sync_items(db)
    elif entity == "gl_accounts":
        result = await sync_gl_accounts(db)
    else:
        result = await sync_all(db)
    return {"success": True, "result": result}


@router.get("/catalog/status")
async def get_catalog_status():
    """Get the current catalog sync status."""
    from services.bc_catalog_sync_service import get_sync_status
    db = get_db()
    return await get_sync_status(db)


@router.get("/catalog/items")
async def search_catalog_items(q: str = "", blocked: bool = None, limit: int = 50):
    """Search synced BC items by number or description."""
    from services.bc_catalog_sync_service import search_items
    db = get_db()
    items = await search_items(db, query=q, blocked=blocked, limit=limit)
    return {"items": items, "total": len(items)}


@router.get("/catalog/items/{item_no}")
async def get_catalog_item(item_no: str):
    """Look up a single synced BC item."""
    from services.bc_catalog_sync_service import get_item_by_number
    db = get_db()
    item = await get_item_by_number(db, item_no)
    if not item:
        raise HTTPException(status_code=404, detail=f"Item '{item_no}' not found in synced catalog")
    return item


@router.get("/catalog/items/{item_no}/validate")
async def validate_catalog_item(item_no: str):
    """Validate that an item number exists and is usable for sales."""
    from services.bc_catalog_sync_service import validate_item_number
    db = get_db()
    return await validate_item_number(db, item_no)


@router.get("/catalog/gl-accounts")
async def search_catalog_gl_accounts(q: str = "", blocked: bool = None, limit: int = 50):
    """Search synced BC G/L accounts by number or name."""
    from services.bc_catalog_sync_service import search_gl_accounts
    db = get_db()
    accounts = await search_gl_accounts(db, query=q, blocked=blocked, limit=limit)
    return {"accounts": accounts, "total": len(accounts)}


@router.post("/catalog/suggest-items")
async def suggest_items_for_line(request: Request):
    """Suggest BC items for a given line description."""
    from services.bc_catalog_sync_service import suggest_items_for_description
    data = await request.json()
    description = data.get("description", "")
    limit = data.get("limit", 5)
    db = get_db()
    suggestions = await suggest_items_for_description(db, description, limit=limit)
    return {"description": description, "suggestions": suggestions, "total": len(suggestions)}



# =========================================================================
# Document Links — BC Factbox Integration (Zetadocs Replacement)
# Steps 1-3, 5: GET links, POST upload, DELETE link, migrate
# =========================================================================

MAX_UPLOAD_SIZE = 25 * 1024 * 1024  # 25 MB

DEMO_MODE = os.environ.get('DEMO_MODE', 'true').lower() == 'true'

def bc_entity_to_doc_type(entity: str) -> str:
    """Map BC entity set names to GPI Hub document types."""
    return {
        "purchaseOrders": "Purchase_Order",
        "purchaseInvoices": "AP_Invoice",
        "salesOrders": "Sales_Order",
    }.get(entity, "Document")


# =========================================================================
# FACTBOX UI — Self-contained HTML page for BC iframe embedding
# =========================================================================

@router.get("/factbox-ui/{bc_entity}/{bc_document_no}", response_class=HTMLResponse)
async def factbox_ui(bc_entity: str, bc_document_no: str, request: Request):
    """Serve a self-contained HTML page for embedding in a BC control add-in iframe.

    Shows linked documents with upload/delete capability. All CSS/JS inline.
    Works cross-origin (BC SaaS domain calling the hub domain).
    """
    # Use relative API path so JS works from any origin
    api_path = f"/api/gpi-integration/document-links/{bc_entity}/{bc_document_no}"

    html = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>Documents — {bc_document_no}</title>
<style>
  *, *::before, *::after {{ box-sizing: border-box; margin: 0; padding: 0; }}
  body {{
    font-family: -apple-system, BlinkMacSystemFont, 'Segoe UI', Roboto, sans-serif;
    font-size: 13px;
    color: #1a1a2e;
    background: #fff;
    padding: 10px 12px;
    line-height: 1.4;
  }}

  /* Header */
  .hdr {{
    display: flex;
    align-items: center;
    justify-content: space-between;
    margin-bottom: 8px;
    padding-bottom: 6px;
    border-bottom: 1px solid #e2e8f0;
  }}
  .hdr h1 {{
    font-size: 13px;
    font-weight: 600;
    color: #334155;
    letter-spacing: -0.01em;
  }}
  .hdr .cnt {{
    font-size: 11px;
    color: #64748b;
    background: #f1f5f9;
    padding: 2px 7px;
    border-radius: 10px;
    font-weight: 500;
  }}

  /* Document list */
  .doc-list {{ list-style: none; }}
  .doc-row {{
    display: flex;
    align-items: center;
    gap: 8px;
    padding: 6px 4px;
    border-bottom: 1px solid #f1f5f9;
    transition: background 0.15s;
  }}
  .doc-row:hover {{ background: #f8fafc; }}
  .doc-row:last-child {{ border-bottom: none; }}

  .doc-info {{ flex: 1; min-width: 0; }}
  .doc-name {{
    display: block;
    font-size: 12px;
    font-weight: 500;
    color: #2563eb;
    text-decoration: none;
    white-space: nowrap;
    overflow: hidden;
    text-overflow: ellipsis;
  }}
  .doc-name:hover {{ text-decoration: underline; color: #1d4ed8; }}
  .doc-meta {{
    font-size: 10px;
    color: #94a3b8;
    margin-top: 1px;
  }}

  /* Source badges */
  .badge {{
    font-size: 9px;
    font-weight: 600;
    padding: 1px 5px;
    border-radius: 3px;
    text-transform: uppercase;
    letter-spacing: 0.03em;
    white-space: nowrap;
    flex-shrink: 0;
  }}
  .badge-hub {{ background: #dbeafe; color: #1e40af; }}
  .badge-drop {{ background: #dcfce7; color: #166534; }}
  .badge-legacy {{ background: #f1f5f9; color: #64748b; }}

  /* Delete button */
  .del-btn {{
    width: 20px;
    height: 20px;
    border: none;
    background: transparent;
    color: #cbd5e1;
    cursor: pointer;
    font-size: 14px;
    line-height: 1;
    border-radius: 3px;
    flex-shrink: 0;
    display: flex;
    align-items: center;
    justify-content: center;
    transition: all 0.15s;
  }}
  .del-btn:hover {{ background: #fee2e2; color: #dc2626; }}

  /* Empty state */
  .empty {{
    text-align: center;
    padding: 20px 10px;
    color: #94a3b8;
    font-size: 12px;
  }}

  /* Upload drop zone */
  .dropzone {{
    margin-top: 10px;
    border: 2px dashed #cbd5e1;
    border-radius: 6px;
    padding: 14px 10px;
    text-align: center;
    cursor: pointer;
    transition: all 0.2s;
    background: #fafbfc;
  }}
  .dropzone:hover, .dropzone.drag-over {{
    border-color: #2563eb;
    background: #eff6ff;
  }}
  .dropzone-text {{
    font-size: 11px;
    color: #64748b;
    pointer-events: none;
  }}
  .dropzone-text strong {{ color: #2563eb; }}

  /* Upload progress */
  .upload-status {{
    margin-top: 6px;
    font-size: 11px;
    text-align: center;
    min-height: 16px;
  }}
  .upload-status.uploading {{ color: #2563eb; }}
  .upload-status.success {{ color: #16a34a; }}
  .upload-status.error {{ color: #dc2626; }}

  /* Spinner */
  @keyframes spin {{ to {{ transform: rotate(360deg); }} }}
  .spinner {{
    display: inline-block;
    width: 12px;
    height: 12px;
    border: 2px solid #bfdbfe;
    border-top-color: #2563eb;
    border-radius: 50%;
    animation: spin 0.6s linear infinite;
    vertical-align: middle;
    margin-right: 4px;
  }}

  /* Loading state */
  .loading {{
    text-align: center;
    padding: 24px 10px;
    color: #94a3b8;
    font-size: 12px;
  }}

  /* Error banner */
  .err-banner {{
    background: #fef2f2;
    border: 1px solid #fecaca;
    color: #991b1b;
    padding: 6px 10px;
    border-radius: 4px;
    font-size: 11px;
    margin-bottom: 8px;
    display: none;
  }}
</style>
</head>
<body>

<div class="err-banner" id="errBanner"></div>

<div class="hdr">
  <h1>Linked Documents</h1>
  <span class="cnt" id="docCount">...</span>
</div>

<div id="docListWrap">
  <div class="loading"><span class="spinner"></span> Loading...</div>
</div>

<div class="dropzone" id="dropzone">
  <div class="dropzone-text">
    Drag files here or <strong>click to browse</strong>
  </div>
</div>
<input type="file" id="fileInput" style="display:none" multiple>

<div class="upload-status" id="uploadStatus"></div>

<script>
(function() {{
  const API = "{api_path}";
  const listWrap = document.getElementById("docListWrap");
  const countEl  = document.getElementById("docCount");
  const dropzone = document.getElementById("dropzone");
  const fileInput = document.getElementById("fileInput");
  const statusEl = document.getElementById("uploadStatus");
  const errBanner = document.getElementById("errBanner");

  function fmtDate(iso) {{
    if (!iso) return "";
    try {{
      const d = new Date(iso);
      if (isNaN(d)) return "";
      return String(d.getMonth()+1).padStart(2,"0") + "/"
           + String(d.getDate()).padStart(2,"0") + "/"
           + d.getFullYear();
    }} catch(e) {{ return ""; }}
  }}

  function badgeClass(src) {{
    if (!src) return "badge-legacy";
    const s = src.toLowerCase();
    if (s === "hub" || s.includes("gpi")) return "badge-hub";
    if (s === "bc_drop" || s.includes("drop")) return "badge-drop";
    return "badge-legacy";
  }}

  function badgeLabel(src) {{
    if (!src) return "Legacy";
    const s = src.toLowerCase();
    if (s === "hub" || s.includes("gpi")) return "GPI Hub";
    if (s === "bc_drop" || s.includes("drop")) return "BC Drop";
    return "Legacy";
  }}

  function showError(msg) {{
    errBanner.textContent = msg;
    errBanner.style.display = "block";
    setTimeout(() => {{ errBanner.style.display = "none"; }}, 6000);
  }}

  async function loadDocs() {{
    listWrap.innerHTML = '<div class="loading"><span class="spinner"></span> Loading...</div>';
    try {{
      const resp = await fetch(API);
      if (!resp.ok) throw new Error("HTTP " + resp.status);
      const data = await resp.json();
      const docs = data.documents || [];
      countEl.textContent = docs.length;

      if (docs.length === 0) {{
        listWrap.innerHTML = '<div class="empty">No documents linked yet</div>';
        return;
      }}

      let html = '<ul class="doc-list">';
      for (const doc of docs) {{
        const url = doc.sharepoint_web_url || "#";
        const name = doc.file_name || "Untitled";
        const date = fmtDate(doc.created_utc);
        const src = doc.source || "";
        const docId = doc.doc_id || "";

        html += '<li class="doc-row">'
          + '<div class="doc-info">'
          +   '<a class="doc-name" href="' + url + '" target="_blank" rel="noopener" title="' + name + '">' + name + '</a>'
          +   '<div class="doc-meta">' + date + '</div>'
          + '</div>'
          + '<span class="badge ' + badgeClass(src) + '">' + badgeLabel(src) + '</span>'
          + '<button class="del-btn" data-id="' + docId + '" title="Remove link">&times;</button>'
          + '</li>';
      }}
      html += '</ul>';
      listWrap.innerHTML = html;

      // Attach delete handlers
      listWrap.querySelectorAll(".del-btn").forEach(btn => {{
        btn.addEventListener("click", async function(e) {{
          e.stopPropagation();
          const id = this.dataset.id;
          if (!id) return;
          if (!confirm("Remove this document link?")) return;
          this.disabled = true;
          this.textContent = "...";
          try {{
            const resp = await fetch(API + "/" + encodeURIComponent(id), {{ method: "DELETE" }});
            if (!resp.ok) throw new Error("HTTP " + resp.status);
            loadDocs();
          }} catch(err) {{
            showError("Delete failed: " + err.message);
            this.disabled = false;
            this.textContent = "\\u00d7";
          }}
        }});
      }});

    }} catch(err) {{
      listWrap.innerHTML = '<div class="empty">Failed to load documents</div>';
      showError("Load error: " + err.message);
      countEl.textContent = "!";
    }}
  }}

  // Upload logic
  async function uploadFiles(files) {{
    if (!files || files.length === 0) return;

    for (const file of files) {{
      if (file.size > 25 * 1024 * 1024) {{
        showError(file.name + " exceeds 25 MB limit");
        continue;
      }}

      statusEl.className = "upload-status uploading";
      statusEl.innerHTML = '<span class="spinner"></span> Uploading ' + file.name + '...';

      try {{
        const fd = new FormData();
        fd.append("file", file);
        fd.append("uploaded_by", "BC Drop");

        const resp = await fetch(API + "/upload", {{
          method: "POST",
          body: fd,
        }});

        if (!resp.ok) {{
          const errData = await resp.json().catch(() => ({{}}));
          throw new Error(errData.detail || "HTTP " + resp.status);
        }}

        statusEl.className = "upload-status success";
        statusEl.textContent = file.name + " uploaded";
        setTimeout(() => {{ statusEl.textContent = ""; statusEl.className = "upload-status"; }}, 3000);
        loadDocs();

      }} catch(err) {{
        statusEl.className = "upload-status error";
        statusEl.textContent = "Upload failed: " + err.message;
        setTimeout(() => {{ statusEl.textContent = ""; statusEl.className = "upload-status"; }}, 5000);
      }}
    }}
  }}

  // Drag and drop
  dropzone.addEventListener("dragover", function(e) {{
    e.preventDefault();
    e.stopPropagation();
    this.classList.add("drag-over");
  }});
  dropzone.addEventListener("dragleave", function(e) {{
    e.preventDefault();
    e.stopPropagation();
    this.classList.remove("drag-over");
  }});
  dropzone.addEventListener("drop", function(e) {{
    e.preventDefault();
    e.stopPropagation();
    this.classList.remove("drag-over");
    uploadFiles(e.dataTransfer.files);
  }});
  dropzone.addEventListener("click", function() {{
    fileInput.click();
  }});
  fileInput.addEventListener("change", function() {{
    uploadFiles(this.files);
    this.value = "";
  }});

  // Initial load
  loadDocs();
}})();
</script>
</body>
</html>"""

    return HTMLResponse(content=html, headers={
        "X-Frame-Options": "ALLOWALL",
        "Content-Security-Policy": "frame-ancestors *",
    })


async def _fetch_bc_document_links(bc_document_no: str) -> list:
    """Fetch documentLinks from BC gpi/documents/v1.0 API for a given document number.
    Returns list of dicts. In DEMO_MODE returns empty list."""
    if DEMO_MODE or not HAS_CREDENTIALS:
        logger.info("[DocLinks] DEMO_MODE — skipping BC documentLinks read for %s", bc_document_no)
        return []

    try:
        from services.gpi_integration_service import _get_token, _get_company_id_standard_api, GPI_API_BASE, BC_TENANT_ID, BC_READ_ENVIRONMENT
        token = await _get_token()
        company_id = await _get_company_id_standard_api()
        doc_link_api = "gpi/documents/v1.0"
        url = (f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/{doc_link_api}/"
               f"companies({company_id})/documentLinks"
               f"?$filter=bcDocumentNo eq '{bc_document_no}'")

        async with httpx.AsyncClient(timeout=30.0) as client:
            resp = await client.get(url, headers={
                "Authorization": f"Bearer {token}", "Accept": "application/json"
            })
            if resp.status_code != 200:
                logger.warning("[DocLinks] BC API returned %d for %s", resp.status_code, bc_document_no)
                return []
            return resp.json().get("value", [])
    except Exception as e:
        logger.warning("[DocLinks] Failed to fetch BC document links for %s: %s", bc_document_no, e)
        return []


# --- STEP 1: GET document links for a BC record ---

@router.get("/document-links/{bc_entity}/{bc_document_no}")
async def get_document_links(bc_entity: str, bc_document_no: str):
    """List all documents linked to a BC record (hub + BC API + legacy Zetadocs).

    Returns a combined, deduplicated list sorted by created_utc desc.
    """
    db = get_db()

    # 1) Query hub_documents for docs linked to this BC document
    hub_docs = await db.hub_documents.find(
        {
            "bc_document_no": bc_document_no,
            "sharepoint_web_url": {"$nin": [None, ""]},
            "$or": [{"deleted": {"$exists": False}}, {"deleted": False}],
        },
        {"_id": 0}
    ).sort("created_utc", -1).to_list(200)

    seen_urls = set()
    results = []

    for d in hub_docs:
        sp_url = d.get("sharepoint_web_url") or d.get("sharepoint_share_link_url") or ""
        if not sp_url or sp_url in seen_urls:
            continue
        seen_urls.add(sp_url)
        results.append({
            "doc_id": d.get("id", ""),
            "file_name": d.get("file_name", ""),
            "sharepoint_web_url": sp_url,
            "sharepoint_folder_path": d.get("sharepoint_folder_path", ""),
            "uploaded_by": d.get("uploaded_by", ""),
            "created_utc": d.get("created_utc", ""),
            "file_size_bytes": d.get("file_size_bytes"),
            "document_type": d.get("document_type", ""),
            "source": d.get("source", "hub"),
        })

    # 2) Query BC documentLinks API for this document number
    bc_links = await _fetch_bc_document_links(bc_document_no)
    for link in bc_links:
        sp_url = link.get("sharePointUrl", "")
        if not sp_url or sp_url in seen_urls:
            continue
        seen_urls.add(sp_url)
        source_val = link.get("source", "")
        if source_val in ("BCDrop", "GPIHub", "GPIHub_Auto"):
            display_source = "hub" if "GPI" in source_val else "bc_drop"
        else:
            display_source = "zetadocs_legacy"
        results.append({
            "doc_id": link.get("id", ""),
            "file_name": link.get("fileName", sp_url.rsplit("/", 1)[-1] if sp_url else ""),
            "sharepoint_web_url": sp_url,
            "sharepoint_folder_path": "",
            "uploaded_by": link.get("uploadedBy", ""),
            "created_utc": link.get("createdAt", ""),
            "file_size_bytes": None,
            "document_type": link.get("documentType", ""),
            "source": display_source,
        })

    # Sort combined list
    results.sort(key=lambda x: x.get("created_utc", ""), reverse=True)

    return {
        "bc_entity": bc_entity,
        "bc_document_no": bc_document_no,
        "documents": results,
        "total": len(results),
    }


# --- STEP 2: POST upload file from BC to SharePoint ---

from fastapi import UploadFile, File, Form

@router.post("/document-links/{bc_entity}/{bc_document_no}/upload")
async def upload_document_to_bc_record(
    bc_entity: str,
    bc_document_no: str,
    file: UploadFile = File(...),
    uploaded_by: str = Form("BC Drop"),
    vendor_context: str = Form(""),
):
    """Upload a file to SharePoint and link it to a BC record.

    1. Resolve the SP folder from existing hub_documents or routing rules.
    2. Upload to SharePoint.
    3. Create GPI Document Link in BC factbox.
    4. Create hub_documents record.
    """
    db = get_db()

    # Read file and enforce 25MB max
    file_content = await file.read()
    if len(file_content) > MAX_UPLOAD_SIZE:
        raise HTTPException(
            status_code=413,
            detail=f"File exceeds 25MB limit ({len(file_content) / (1024*1024):.1f}MB)"
        )

    # --- FOLDER RESOLUTION ---
    folder_source = "routing_rules"
    folder_path = ""

    # Try to find existing folder from hub_documents for this BC record
    existing = await db.hub_documents.find_one(
        {
            "bc_document_no": bc_document_no,
            "sharepoint_folder_path": {"$nin": [None, ""]},
        },
        {"sharepoint_folder_path": 1, "sharepoint_drive_id": 1, "_id": 0},
        sort=[("created_utc", -1)],
    )

    if existing and existing.get("sharepoint_folder_path"):
        folder_path = existing["sharepoint_folder_path"]
        folder_source = "matched"
        logger.info("[DocLinks] Folder matched from existing doc for %s: %s", bc_document_no, folder_path)
    else:
        # Fallback: use folder routing rules
        try:
            from services.folder_routing_service import determine_folder_path
            doc_type = bc_entity_to_doc_type(bc_entity)
            fake_doc = {
                "document_type": doc_type,
                "extracted_fields": {"vendor": vendor_context},
                "normalized_fields": {},
            }
            folder_path, _reason, _details = determine_folder_path(fake_doc)
            logger.info("[DocLinks] Folder from routing rules for %s: %s (%s)", bc_document_no, folder_path, _reason)
        except Exception as e:
            logger.warning("[DocLinks] Folder routing failed, using default: %s", e)
            folder_path = f"BC_Drops/{bc_entity}/{bc_document_no}"

    # --- UPLOAD TO SHAREPOINT ---
    try:
        from services.sharepoint_service import upload_to_sharepoint
        sp_result = await upload_to_sharepoint(file_content, file.filename, folder_path)
    except Exception as e:
        logger.error("[DocLinks] SharePoint upload failed for %s: %s", bc_document_no, e)
        raise HTTPException(status_code=502, detail=f"SharePoint upload failed: {str(e)}")

    # --- CREATE GPI DOCUMENT LINK IN BC ---
    bc_link_created = False
    try:
        link_result = await create_gpi_document_link(
            bc_system_id="",
            bc_document_no=bc_document_no,
            document_type=bc_entity_to_doc_type(bc_entity),
            sharepoint_url=sp_result.get("web_url", ""),
            sharepoint_drive_id=sp_result.get("drive_id", ""),
            sharepoint_item_id=sp_result.get("item_id", ""),
            uploaded_by=uploaded_by,
            source="BCDrop",
        )
        bc_link_created = link_result.get("success", False)
    except Exception as e:
        logger.warning("[DocLinks] BC link creation failed (non-blocking): %s", e)

    # --- CREATE HUB_DOCUMENTS RECORD ---
    now = datetime.now(timezone.utc).isoformat()
    new_doc_id = str(uuid.uuid4())
    hub_record = {
        "id": new_doc_id,
        "file_name": file.filename,
        "bc_document_no": bc_document_no,
        "bc_entity_type": bc_entity,
        "sharepoint_folder_path": folder_path,
        "sharepoint_web_url": sp_result.get("web_url", ""),
        "sharepoint_drive_id": sp_result.get("drive_id", ""),
        "sharepoint_item_id": sp_result.get("item_id", ""),
        "source": "bc_drop",
        "uploaded_by": uploaded_by,
        "created_utc": now,
        "updated_utc": now,
        "document_type": bc_entity_to_doc_type(bc_entity),
        "folder_source": folder_source,
        "file_size_bytes": len(file_content),
    }
    await db.hub_documents.insert_one(hub_record)
    hub_record.pop("_id", None)

    logger.info("[DocLinks] Uploaded %s to %s for %s/%s (folder_source=%s, bc_link=%s)",
                file.filename, folder_path, bc_entity, bc_document_no, folder_source, bc_link_created)

    return {
        "success": True,
        "doc_id": new_doc_id,
        "file_name": file.filename,
        "sharepoint_url": sp_result.get("web_url", ""),
        "folder_path": folder_path,
        "folder_source": folder_source,
        "bc_link_created": bc_link_created,
    }


# --- STEP 3: DELETE a document link (soft delete) ---

@router.delete("/document-links/{bc_entity}/{bc_document_no}/{doc_id_or_sp_item}")
async def delete_document_link(bc_entity: str, bc_document_no: str, doc_id_or_sp_item: str):
    """Soft-delete a document link. The SharePoint file remains for audit."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Find by id or sharepoint_item_id
    doc = await db.hub_documents.find_one(
        {"$or": [
            {"id": doc_id_or_sp_item, "bc_document_no": bc_document_no},
            {"sharepoint_item_id": doc_id_or_sp_item, "bc_document_no": bc_document_no},
        ]},
        {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document link not found")

    await db.hub_documents.update_one(
        {"id": doc.get("id")},
        {"$set": {"deleted": True, "deleted_utc": now, "deleted_by": "user"}}
    )

    logger.info("[DocLinks] Soft-deleted link %s for %s/%s", doc.get("id"), bc_entity, bc_document_no)
    return {"success": True, "message": f"Link removed for {doc.get('file_name', '')}. SharePoint file preserved."}


# --- STEP 5: Migrate existing Zetadocs links ---

@router.post("/document-links/migrate-from-zetadocs")
async def migrate_zetadocs_links():
    """Import existing Zetadocs-written links from BC into hub_documents.

    Idempotent — safe to run multiple times. Skips records that already exist.
    """
    if DEMO_MODE or not HAS_CREDENTIALS:
        return {
            "migrated": 0, "skipped": 0, "errors": [],
            "message": "DEMO_MODE active — no BC API calls made. In production this fetches all Zetadocs links."
        }

    try:
        from services.gpi_integration_service import _get_token, _get_company_id_standard_api, GPI_API_BASE, BC_TENANT_ID, BC_READ_ENVIRONMENT
    except ImportError as e:
        raise HTTPException(status_code=500, detail=f"Import error: {e}")

    db = get_db()
    token = await _get_token()
    company_id = await _get_company_id_standard_api()
    doc_link_api = "gpi/documents/v1.0"
    base_url = (f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENVIRONMENT}/api/{doc_link_api}/"
                f"companies({company_id})/documentLinks")

    migrated = 0
    skipped = 0
    errors = []
    page_url = f"{base_url}?$top=100&$filter=source ne 'BCDrop' and source ne 'GPIHub' and source ne 'GPIHub_Auto'"

    try:
        async with httpx.AsyncClient(timeout=60.0) as client:
            while page_url:
                resp = await client.get(page_url, headers={
                    "Authorization": f"Bearer {token}", "Accept": "application/json"
                })
                if resp.status_code != 200:
                    errors.append(f"BC API returned {resp.status_code}: {resp.text[:200]}")
                    break

                data = resp.json()
                links = data.get("value", [])

                for link in links:
                    sp_item_id = link.get("sharePointItemId", "")
                    sp_url = link.get("sharePointUrl", "")
                    bc_doc_no = link.get("bcDocumentNo", "")

                    if not sp_url:
                        continue

                    # Check if already exists
                    existing = await db.hub_documents.find_one(
                        {"$or": [
                            {"sharepoint_item_id": sp_item_id} if sp_item_id else {"sharepoint_web_url": sp_url},
                            {"sharepoint_web_url": sp_url},
                        ]},
                        {"_id": 0, "id": 1}
                    )
                    if existing:
                        skipped += 1
                        continue

                    # Create stub record
                    now = datetime.now(timezone.utc).isoformat()
                    stub = {
                        "id": str(uuid.uuid4()),
                        "source": "zetadocs_legacy",
                        "bc_document_no": bc_doc_no,
                        "sharepoint_web_url": sp_url,
                        "sharepoint_drive_id": link.get("sharePointDriveId", ""),
                        "sharepoint_item_id": sp_item_id,
                        "migrated_utc": now,
                        "created_utc": link.get("createdAt", now),
                        "document_type": link.get("documentType", ""),
                        "file_name": link.get("fileName", sp_url.rsplit("/", 1)[-1] if sp_url else ""),
                        "uploaded_by": link.get("uploadedBy", "Zetadocs"),
                    }
                    try:
                        await db.hub_documents.insert_one(stub)
                        stub.pop("_id", None)
                        migrated += 1
                    except Exception as e:
                        errors.append(f"Insert failed for {bc_doc_no}: {str(e)[:100]}")

                # Next page
                page_url = data.get("@odata.nextLink")

    except Exception as e:
        errors.append(f"Migration error: {str(e)[:200]}")

    logger.info("[DocLinks] Zetadocs migration: migrated=%d, skipped=%d, errors=%d", migrated, skipped, len(errors))
    return {"migrated": migrated, "skipped": skipped, "errors": errors}


# =========================================================================
# SH_INVOICE: Cost-Only Sales Order Endpoint
# =========================================================================

@router.post("/sales-orders/cost-only-from-document/{doc_id}")
async def create_cost_only_so_from_document(doc_id: str):
    """Create a cost-only Sales Order in BC from an approved SH_Invoice document.

    Cost-only SOs use GL Account type lines (not Item type) to post warehouse
    storage & handling charges without revenue recognition.

    Preconditions:
      - Document must be type SH_Invoice
      - workflow_status must be 'approved'
      - A customer must be resolvable
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    # Validate document type
    doc_type = doc.get("suggested_job_type") or doc.get("document_type") or ""
    if doc_type != "SH_Invoice":
        raise HTTPException(
            status_code=400,
            detail=f"Document type is '{doc_type}', expected SH_Invoice",
        )

    # Validate workflow status
    wf_status = doc.get("workflow_status", "")
    if wf_status != "approved":
        raise HTTPException(
            status_code=400,
            detail=f"SH_Invoice must be approved before posting. Current status: {wf_status}",
        )

    # Idempotency: check if SO already created
    existing_so = doc.get("bc_sales_order")
    if existing_so:
        return {
            "success": True,
            "status": "already_created",
            "bc_so_number": existing_so.get("bc_record_no", ""),
            "bc_system_id": existing_so.get("bc_system_id", ""),
            "processor": doc.get("processor", ""),
            "folder_path": doc.get("sh_folder_path", ""),
            "gl_account_used": existing_so.get("gl_account_used", ""),
            "doc_id": doc_id,
        }

    # Resolve customer
    customer_info = await _resolve_customer_no(doc)
    customer_no = customer_info["customer_no"]
    if not customer_no:
        raise HTTPException(
            status_code=400,
            detail="Cannot create cost-only SO: no BC customer resolved. "
                   "Ensure customer is mapped or provide via extracted_fields.",
        )

    # Determine GL account for lines
    gl_account_number = None
    gl_account_name = "Storage & Handling"
    try:
        from services.freight_gl_routing_service import get_freight_gl_service
        gl_svc = get_freight_gl_service()
        if gl_svc:
            gl_result = await gl_svc.classify_document(doc)
            recommended = gl_result.get("recommended_gl")
            if recommended:
                gl_account_number = recommended.get("gl_number")
                gl_account_name = recommended.get("gl_name", gl_account_name)
    except Exception as gl_err:
        logger.warning("[SH-SO] Freight GL classification failed: %s", gl_err)

    # Fallback: hub_config default
    if not gl_account_number:
        config = await db.hub_config.find_one({"_key": "sh_default_gl_account"}, {"_id": 0})
        gl_account_number = (config or {}).get("value", "")

    if not gl_account_number:
        raise HTTPException(
            status_code=400,
            detail="No GL account resolved for SH_Invoice. "
                   "Configure 'sh_default_gl_account' in hub_config or set up freight GL routing.",
        )

    # Build cost-only SO lines (Account type, NOT Item type)
    ef = doc.get("extracted_fields") or {}
    line_items = ef.get("line_items") or []
    so_lines = []

    if line_items:
        for item in line_items:
            amount = float(item.get("amount") or item.get("total") or item.get("unit_price") or 0)
            if amount <= 0:
                continue
            so_lines.append({
                "lineType": "Account",
                "lineObjectNumber": gl_account_number,
                "description": (item.get("description") or "Storage & Handling charges")[:100],
                "quantity": 1,
                "unitPrice": amount,
            })

    # Fallback: single line with total amount
    if not so_lines:
        total_amount = float(ef.get("total_amount") or ef.get("amount") or ef.get("invoice_total") or 0)
        if total_amount <= 0:
            raise HTTPException(
                status_code=400,
                detail="No line items and no total amount found on the document. Cannot create cost-only SO.",
            )
        so_lines.append({
            "lineType": "Account",
            "lineObjectNumber": gl_account_number,
            "description": "Storage & Handling charges",
            "quantity": 1,
            "unitPrice": total_amount,
        })

    # Determine processor for folder routing
    processor = doc.get("processor", "")
    if not processor:
        config = await db.hub_config.find_one({"_key": "sh_default_processor"}, {"_id": 0})
        processor = (config or {}).get("value", "Andy")

    # ── Create SO in BC (or DEMO_MODE) ──
    now = datetime.now(timezone.utc).isoformat()
    idempotency_key = f"SH_SO_{doc_id}_{now[:10]}"

    if not HAS_CREDENTIALS:
        # DEMO_MODE: simulate SO creation
        demo_so_no = f"SH-DEMO-{doc_id[:8].upper()}"
        demo_sys_id = f"demo-sh-{uuid.uuid4().hex[:12]}"
        logger.info("[SH-SO] DEMO MODE: simulated cost-only SO %s for doc %s", demo_so_no, doc_id[:8])

        so_record = {
            "bc_record_no": demo_so_no,
            "bc_system_id": demo_sys_id,
            "created_at": now,
            "idempotency_key": idempotency_key,
            "lines_added": len(so_lines),
            "lines_total": len(so_lines),
            "gl_account_used": gl_account_number,
            "cost_only": True,
            "demo_mode": True,
        }

        # Determine SharePoint folder path
        if processor.lower() == "ellie":
            folder_path = "S&H Invoices Approved Documents/Ellie to Process"
        else:
            folder_path = "S&H Invoices Approved Documents/Andy to Process"

        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "bc_sales_order": so_record,
                "workflow_status": "exported",
                "workflow_status_updated_utc": now,
                "processor": processor,
                "sh_folder_path": folder_path,
                "updated_utc": now,
            },
            "$push": {
                "workflow_history": {
                    "timestamp": now,
                    "from_status": "approved",
                    "to_status": "exported",
                    "event": "on_exported",
                    "actor": "sh_cost_only_so",
                    "reason": f"Cost-only SO {demo_so_no} created (demo)",
                    "metadata": {"bc_so_no": demo_so_no, "gl_account": gl_account_number, "processor": processor},
                },
            }},
        )

        return {
            "success": True,
            "status": "created",
            "bc_so_number": demo_so_no,
            "bc_system_id": demo_sys_id,
            "processor": processor,
            "folder_path": folder_path,
            "gl_account_used": gl_account_number,
            "lines_added": len(so_lines),
            "cost_only": True,
            "demo_mode": True,
            "doc_id": doc_id,
        }

    # ── Live BC creation ──
    try:
        from services.gpi_integration_service import create_sales_order, add_sales_order_lines

        # Step 1: Create SO header
        so_result = await create_sales_order(
            customer_no=customer_no,
            external_doc_no=ef.get("invoice_number") or ef.get("po_number") or "",
            source_doc_id=doc_id,
            idempotency_key=idempotency_key,
        )

        if not so_result.get("success"):
            raise HTTPException(
                status_code=502,
                detail=f"BC SO creation failed: {so_result.get('error_message', 'Unknown error')}",
            )

        bc_so_no = so_result["bc_record_no"]
        bc_sys_id = so_result["bc_system_id"]

        # Step 2: Add cost-only Account lines
        lines_result = await add_sales_order_lines(bc_sys_id, so_lines)

        # Determine SharePoint folder path
        if processor.lower() == "ellie":
            folder_path = "S&H Invoices Approved Documents/Ellie to Process"
        else:
            folder_path = "S&H Invoices Approved Documents/Andy to Process"

        so_record = {
            "bc_record_no": bc_so_no,
            "bc_system_id": bc_sys_id,
            "created_at": now,
            "idempotency_key": idempotency_key,
            "lines_added": lines_result.get("added", 0),
            "lines_total": lines_result.get("total", len(so_lines)),
            "gl_account_used": gl_account_number,
            "cost_only": True,
        }

        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "bc_sales_order": so_record,
                "workflow_status": "exported",
                "workflow_status_updated_utc": now,
                "processor": processor,
                "sh_folder_path": folder_path,
                "updated_utc": now,
            },
            "$push": {
                "workflow_history": {
                    "timestamp": now,
                    "from_status": "approved",
                    "to_status": "exported",
                    "event": "on_exported",
                    "actor": "sh_cost_only_so",
                    "reason": f"Cost-only SO {bc_so_no} created",
                    "metadata": {"bc_so_no": bc_so_no, "gl_account": gl_account_number, "processor": processor},
                },
            }},
        )

        # Move file in SharePoint
        try:
            from services.sharepoint_service import get_sharepoint_service
            sp = get_sharepoint_service()
            if sp:
                await sp.move_document(doc, folder_path)
        except Exception as sp_err:
            logger.warning("[SH-SO] SharePoint move failed: %s", sp_err)

        return {
            "success": True,
            "status": "created",
            "bc_so_number": bc_so_no,
            "bc_system_id": bc_sys_id,
            "processor": processor,
            "folder_path": folder_path,
            "gl_account_used": gl_account_number,
            "lines_added": lines_result.get("added", 0),
            "cost_only": True,
            "doc_id": doc_id,
        }

    except HTTPException:
        raise
    except Exception as e:
        logger.error("[SH-SO] Cost-only SO creation failed for %s: %s", doc_id[:8], str(e))
        raise HTTPException(status_code=502, detail=f"BC API error: {str(e)[:200]}")


# ════════════════════════════════════════════════════════════════════════
# ORDER LINE PATTERN LEARNING
# ════════════════════════════════════════════════════════════════════════

@router.post("/order-patterns/learn/{customer_no}")
async def learn_order_patterns(customer_no: str):
    """Analyze historical orders for a customer and learn dunnage patterns."""
    db = get_db()
    from services.order_line_patterns import learn_patterns_from_history
    result = await learn_patterns_from_history(db, customer_no)
    return result


@router.get("/order-patterns/{customer_no}")
async def get_order_patterns(customer_no: str):
    """Get learned dunnage patterns for a customer."""
    db = get_db()
    patterns = await db.order_line_patterns.find(
        {"customer_no": customer_no}, {"_id": 0}
    ).to_list(100)
    return {"customer_no": customer_no, "patterns": patterns}


@router.post("/order-patterns/suggest")
async def suggest_order_lines(payload: dict):
    """Get dunnage suggestions for given items and customer."""
    db = get_db()
    from services.order_line_patterns import get_suggested_lines
    customer_no = payload.get("customer_no", "")
    line_items = payload.get("line_items", [])
    suggestions = await get_suggested_lines(db, customer_no, line_items)
    return {"customer_no": customer_no, "suggestions": suggestions}
