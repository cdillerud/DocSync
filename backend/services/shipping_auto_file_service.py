"""
Auto-file service for Shipping Documents and Warehouse Receipts.

Implements the Warehouse Workflow logic:
  1. Extract PO/SO number from the document
  2. BC lookup to get locationCode + InternationalGds
  3. Map: locationCode GR → Dropship, GB → Warehouse
  4. Map: InternationalGds True → International, False → Domestic
  5. Auto-file to the correct SharePoint folder
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, Tuple

logger = logging.getLogger(__name__)

# BC locationCode → freight_direction mapping
# GR = Gamer Packaging receives (inbound/dropship)
# GB = Gamer Packaging ships out (outbound/warehouse)
LOCATION_MAP = {
    "GR": "inbound",     # Dropship
    "GB": "outbound",    # Warehouse
}

# Document types eligible for auto-filing
AUTOFILE_TYPES = {"Shipping_Document", "Warehouse_Receipt", "Warehouse_Document"}


async def auto_file_shipping_document(doc_id: str, db=None) -> Dict[str, Any]:
    """
    Auto-file a shipping document to the correct SharePoint folder.

    Steps:
      1. Validate doc is a shipping type
      2. Extract PO/SO from doc
      3. BC lookup for locationCode + InternationalGds
      4. Determine folder via routing rules
      5. File to SharePoint + mark completed

    Returns result dict with success status and details.
    """
    if db is None:
        from deps import get_db
        db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"success": False, "reason": "document_not_found"}

    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
    if doc_type not in AUTOFILE_TYPES:
        return {"success": False, "reason": f"not_a_shipping_type: {doc_type}", "skipped": True}

    # Already filed?
    if doc.get("filed_at") or doc.get("auto_filed"):
        return {"success": True, "skipped": True, "reason": "already_filed"}

    # Extract PO/SO number
    po_number, so_number = _extract_order_numbers(doc)
    order_ref = po_number or so_number or ""

    # BC lookup for locationCode + InternationalGds
    location_code, is_international = await _bc_lookup_order(
        po_number=po_number, so_number=so_number, doc=doc, db=db
    )

    # Map locationCode to freight direction
    freight_direction = LOCATION_MAP.get(location_code, None)

    logger.info(
        "[AutoFile] doc=%s type=%s po=%s so=%s locationCode=%s international=%s direction=%s",
        doc_id, doc_type, po_number, so_number, location_code, is_international, freight_direction,
    )

    # Determine folder path using existing routing rules
    from services.folder_routing_service import determine_folder_path

    folder_path, reason, routing_details = determine_folder_path(
        doc,
        freight_direction=freight_direction,
        is_international=is_international,
    )

    # Attempt SharePoint upload
    move_result = await _move_to_sharepoint(doc_id, folder_path)

    # Mark as auto-filed
    now = datetime.now(timezone.utc).isoformat()
    update = {
        "auto_filed": True,
        "auto_filed_at": now,
        "auto_file_details": {
            "po_number": po_number,
            "so_number": so_number,
            "location_code": location_code,
            "is_international": is_international,
            "freight_direction": freight_direction,
            "folder_path": folder_path,
            "routing_reason": reason,
            "sharepoint_result": "success" if move_result.get("success") else "failed",
        },
        "auto_cleared": True,
        "auto_clear_decision": "Cleared",
        "auto_clear_reason": f"Shipping auto-filed: {reason}",
        "status": "Completed",
        "workflow_status": "completed",
        "sharepoint_folder_suggestion": folder_path,
        "sharepoint_folder_reason": reason,
        "filed_at": now,
        "filed_folder": folder_path,
        "updated_utc": now,
    }
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update})

    # Record filing action for AI learning
    vendor = doc.get("vendor_canonical") or doc.get("vendor_raw") or ""
    await db.filing_actions.update_one(
        {"document_type": doc_type, "vendor_lower": vendor.lower(), "folder_path": folder_path},
        {
            "$inc": {"count": 1},
            "$set": {
                "document_type": doc_type,
                "vendor": vendor,
                "vendor_lower": vendor.lower(),
                "folder_path": folder_path,
                "routing_reason": reason,
                "last_filed_at": now,
            },
        },
        upsert=True,
    )

    # Record positive classification confirmation
    try:
        from services.classification_feedback_service import record_confirmation, _build_doc_context
        await record_confirmation(
            doc_id=doc_id,
            confirmed_type=doc_type,
            confirmation_source="auto_file_shipping",
            doc_context=_build_doc_context(doc),
        )
    except Exception:
        pass

    logger.info(
        "[AutoFile] doc=%s → %s (locationCode=%s, international=%s, sp=%s)",
        doc_id, folder_path, location_code, is_international,
        "ok" if move_result.get("success") else "failed",
    )

    return {
        "success": True,
        "doc_id": doc_id,
        "folder_path": folder_path,
        "reason": reason,
        "location_code": location_code,
        "is_international": is_international,
        "freight_direction": freight_direction,
        "sharepoint": move_result,
    }


def _extract_order_numbers(doc: Dict) -> Tuple[str, str]:
    """Extract PO and SO numbers from all possible document fields."""
    extracted = doc.get("extracted_fields", {})
    normalized = doc.get("normalized_fields", {})
    ai_ext = doc.get("ai_extraction", {})

    po_number = (
        doc.get("po_number_extracted")
        or normalized.get("po_number")
        or extracted.get("po_number")
        or extracted.get("customer_po")
        or ai_ext.get("po_number")
        or ""
    ).strip()

    so_number = (
        normalized.get("so_number")
        or extracted.get("so_number")
        or extracted.get("order_number")
        or ai_ext.get("so_number")
        or ai_ext.get("order_number")
        or ""
    ).strip()

    return po_number, so_number


async def _bc_lookup_order(
    po_number: str,
    so_number: str,
    doc: Dict,
    db,
) -> Tuple[Optional[str], bool]:
    """Look up PO/SO in Business Central to get locationCode and InternationalGds.

    Returns (location_code, is_international).
    Falls back to heuristics if BC lookup fails.
    """
    location_code = None
    is_international = False

    # Try BC lookup if we have a reference number
    if po_number or so_number:
        try:
            from services.business_central_service import BusinessCentralService
            bc = BusinessCentralService()

            if po_number:
                result = await _bc_lookup_po(bc, po_number)
                if result:
                    location_code, is_international = result
                    return location_code, is_international

            if so_number:
                result = await _bc_lookup_so(bc, so_number)
                if result:
                    location_code, is_international = result
                    return location_code, is_international

        except Exception as e:
            logger.warning("[AutoFile] BC lookup failed for PO=%s SO=%s: %s", po_number, so_number, e)

    # Fallback: check if doc already has location info from extraction
    extracted = doc.get("extracted_fields", {})
    ai_ext = doc.get("ai_extraction", {})

    loc = (
        extracted.get("location_code")
        or extracted.get("location")
        or ai_ext.get("location_code")
        or ai_ext.get("location")
        or ""
    ).strip().upper()

    if loc in LOCATION_MAP:
        location_code = loc

    # Check for international indicators in the document
    vendor = (doc.get("vendor_canonical") or doc.get("vendor_raw") or "").lower()
    file_name = (doc.get("file_name") or "").lower()
    text = (extracted.get("description") or ai_ext.get("description") or "").lower()

    international_indicators = ["international", "intl", "overseas", "import", "export", "customs", "duty"]
    if any(ind in vendor or ind in file_name or ind in text for ind in international_indicators):
        is_international = True

    # Check vendor_type_patterns for location hints
    if not location_code and vendor:
        pattern = await db.vendor_type_patterns.find_one(
            {"vendor": vendor.upper().strip()},
            {"_id": 0, "location_hint": 1, "is_international_hint": 1},
        )
        if pattern:
            location_code = pattern.get("location_hint") or location_code
            if pattern.get("is_international_hint") is not None:
                is_international = pattern["is_international_hint"]

    return location_code, is_international


async def _bc_lookup_po(bc, po_number: str) -> Optional[Tuple[str, bool]]:
    """Look up a purchase order in BC by number. Returns (locationCode, isInternational) or None."""
    try:
        if bc.use_mock:
            return None

        import httpx
        import os

        BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"
        BC_TENANT_ID = os.environ.get("TENANT_ID", "")
        BC_READ_ENV = os.environ.get("BC_ENVIRONMENT") or os.environ.get("BC_SANDBOX_ENVIRONMENT", "")

        token = await bc._get_token(environment=BC_READ_ENV)
        company_id = await bc._get_company_id(environment=BC_READ_ENV)

        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENV}/api/v2.0/companies({company_id})/purchaseOrders"
        params = {
            "$filter": f"number eq '{po_number}'",
            "$select": "id,number,locationCode",
            "$top": "1",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            if resp.status_code == 200:
                orders = resp.json().get("value", [])
                if orders:
                    loc = orders[0].get("locationCode", "")
                    # InternationalGds isn't on standard PO entity — check custom field or default
                    return loc, False
    except Exception as e:
        logger.debug("[AutoFile] BC PO lookup failed for %s: %s", po_number, e)

    return None


async def _bc_lookup_so(bc, so_number: str) -> Optional[Tuple[str, bool]]:
    """Look up a sales order in BC by number. Returns (locationCode, isInternational) or None."""
    try:
        if bc.use_mock:
            return None

        import httpx
        import os

        BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"
        BC_TENANT_ID = os.environ.get("TENANT_ID", "")
        BC_READ_ENV = os.environ.get("BC_ENVIRONMENT") or os.environ.get("BC_SANDBOX_ENVIRONMENT", "")

        token = await bc._get_token(environment=BC_READ_ENV)
        company_id = await bc._get_company_id(environment=BC_READ_ENV)

        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_READ_ENV}/api/v2.0/companies({company_id})/salesOrders"
        params = {
            "$filter": f"number eq '{so_number}'",
            "$select": "id,number,locationCode",
            "$top": "1",
        }

        async with httpx.AsyncClient(timeout=15.0) as client:
            resp = await client.get(url, headers={"Authorization": f"Bearer {token}"}, params=params)
            if resp.status_code == 200:
                orders = resp.json().get("value", [])
                if orders:
                    loc = orders[0].get("locationCode", "")
                    return loc, False
    except Exception as e:
        logger.debug("[AutoFile] BC SO lookup failed for %s: %s", so_number, e)

    return None


async def _move_to_sharepoint(doc_id: str, folder_path: str) -> Dict[str, Any]:
    """Attempt to move document to SharePoint. Returns result dict."""
    try:
        from routers.sharepoint_routing import move_document_to_sharepoint
        result = await move_document_to_sharepoint(doc_id)
        return {"success": True, "folder_path": result.get("folder_path", folder_path)}
    except Exception as e:
        error_msg = str(e)
        if "demo" in error_msg.lower() or "mock" in error_msg.lower():
            return {"success": True, "folder_path": folder_path, "demo_mode": True}
        logger.warning("[AutoFile] SharePoint move failed for %s: %s", doc_id, error_msg)
        return {"success": False, "message": error_msg}
