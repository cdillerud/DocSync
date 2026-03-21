"""
GPI Document Hub - BC Draft Service

Extracted from server.py — authoritative implementation of:
  - create_purchase_invoice_header: Create a PI header in BC (Draft, no lines)
  - check_duplicate_purchase_invoice: Hard-dup check before PI creation
  - is_eligible_for_draft_creation: Thin wrapper → services.ap_computation

Falls back to mock behavior in DEMO_MODE or when BC_CLIENT_ID is not configured.
"""

import os
import uuid
import logging
import httpx
from datetime import datetime, timezone

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# ── BC Config ──
DEMO_MODE = os.environ.get('DEMO_MODE', 'true').lower() == 'true'
TENANT_ID = os.environ.get('TENANT_ID', '')
BC_ENVIRONMENT = os.environ.get('BC_ENVIRONMENT', '')
BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID', '')


async def _get_bc_token():
    from server import get_bc_token
    return await get_bc_token()


async def _get_bc_companies():
    from server import get_bc_companies
    return await get_bc_companies()


async def check_duplicate_purchase_invoice(
    vendor_no: str, external_doc_no: str, company_id: str, token: str
) -> dict:
    """
    Check if a Purchase Invoice already exists with the same vendor + external doc number.
    Hard duplicate check that MUST stop draft creation.
    """
    if DEMO_MODE or not BC_CLIENT_ID:
        return {"found": False, "method": "demo"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            filter_query = f"vendorNumber eq '{vendor_no}' and vendorInvoiceNumber eq '{external_doc_no}'"

            resp = await c.get(
                f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices",
                headers={"Authorization": f"Bearer {token}"},
                params={"$filter": filter_query, "$select": "id,number,vendorNumber,vendorInvoiceNumber,status,totalAmountIncludingTax"}
            )

            if resp.status_code == 200:
                invoices = resp.json().get("value", [])
                if invoices:
                    existing = invoices[0]
                    return {
                        "found": True,
                        "existing_invoice_id": existing.get("id"),
                        "existing_invoice_no": existing.get("number"),
                        "vendor_invoice_no": existing.get("vendorInvoiceNumber"),
                        "status": existing.get("status", "Unknown"),
                        "amount": existing.get("totalAmountIncludingTax"),
                        "method": "api"
                    }
            elif resp.status_code in (401, 403):
                logger.warning("BC permission denied during duplicate check")
                return {"found": False, "error": "Permission denied", "method": "api"}

            return {"found": False, "method": "api"}

    except Exception as e:
        logger.error("Duplicate check failed: %s", str(e))
        return {"found": False, "error": str(e), "method": "api"}


async def create_purchase_invoice_header(
    vendor_no: str,
    external_doc_no: str,
    document_date: str = None,
    due_date: str = None,
    currency_code: str = None,
    posting_date: str = None,
    company_id: str = None,
    token: str = None
) -> dict:
    """
    Create a Purchase Invoice HEADER only in Business Central.

    SAFETY RULES:
    - Creates ONLY the header, NO lines
    - Sets document to Draft status (does NOT post)
    - Does NOT set quantities or GL accounts
    """
    if DEMO_MODE or not BC_CLIENT_ID:
        mock_invoice_id = str(uuid.uuid4())
        return {
            "success": True,
            "method": "demo",
            "invoice_id": mock_invoice_id,
            "invoice_no": f"PI-DEMO-{mock_invoice_id[:6].upper()}",
            "status": "Draft",
            "note": "Demo mode: Purchase Invoice header would be created in production"
        }

    if not company_id or not token:
        try:
            token = await _get_bc_token()
            companies = await _get_bc_companies()
            if not companies:
                return {"success": False, "error": "No BC companies found"}
            company_id = companies[0]["id"]
        except Exception as e:
            return {"success": False, "error": f"Failed to get BC token/company: {str(e)}"}

    try:
        async with httpx.AsyncClient(timeout=60.0) as c:
            today = datetime.now(timezone.utc).strftime('%Y-%m-%d')

            invoice_payload = {
                "vendorNumber": vendor_no,
                "vendorInvoiceNumber": external_doc_no,
            }

            if document_date:
                invoice_payload["documentDate"] = document_date
            else:
                invoice_payload["documentDate"] = today

            if due_date:
                invoice_payload["dueDate"] = due_date

            if posting_date:
                invoice_payload["postingDate"] = posting_date
            else:
                invoice_payload["postingDate"] = today

            if currency_code and currency_code.upper() not in ('', 'USD', 'GBP', 'EUR'):
                invoice_payload["currencyCode"] = currency_code.upper()

            create_resp = await c.post(
                f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json"
                },
                json=invoice_payload
            )

            if create_resp.status_code in (401, 403):
                return {
                    "success": False, "method": "api",
                    "error": f"BC permission denied (HTTP {create_resp.status_code}). Ensure the app has D365 BUS FULL ACCESS permission set in BC."
                }

            if create_resp.status_code not in (200, 201):
                try:
                    error_data = create_resp.json()
                    error_msg = error_data.get("error", {}).get("message", str(error_data))
                except Exception:
                    error_msg = create_resp.text[:500]
                return {
                    "success": False, "method": "api",
                    "error": f"Failed to create Purchase Invoice (HTTP {create_resp.status_code}): {error_msg}"
                }

            invoice_data = create_resp.json()
            invoice_id = invoice_data.get("id")
            invoice_no = invoice_data.get("number")

            if not invoice_id:
                return {
                    "success": False, "method": "api",
                    "error": f"No invoice ID returned from BC: {invoice_data}"
                }

            logger.info(
                "Created Purchase Invoice draft header: ID=%s, No=%s, Vendor=%s, ExtDoc=%s",
                invoice_id, invoice_no, vendor_no, external_doc_no
            )

            return {
                "success": True,
                "method": "api",
                "invoice_id": invoice_id,
                "invoice_no": invoice_no,
                "vendor_no": vendor_no,
                "external_doc_no": external_doc_no,
                "status": "Draft",
                "header_only": True,
                "note": "Created by GPI Hub Automation - Header only, no lines"
            }

    except Exception as e:
        logger.error("Failed to create Purchase Invoice header: %s", str(e))
        return {
            "success": False, "method": "api",
            "error": f"Exception creating Purchase Invoice: {str(e)}"
        }


def is_eligible_for_draft_creation(
    job_type: str,
    match_method: str,
    match_score: float,
    ai_confidence: float,
    validation_results: dict,
    doc: dict
) -> tuple:
    """Thin delegation to services.ap_computation."""
    from services.ap_computation import is_eligible_for_draft_creation as _impl
    return _impl(job_type, match_method, match_score, ai_confidence, validation_results, doc)
