"""
GPI Document Hub - BC Draft Creation Service

Purchase Invoice duplicate checking and header-only draft creation
against the Business Central API.
Extracted from server.py during Architecture Hardening pass.

Dependencies:
  - deps: config vars (DEMO_MODE, BC_CLIENT_ID, TENANT_ID, BC_ENVIRONMENT)
  - services.bc_api_helpers: get_bc_companies
"""

import logging
import uuid
from datetime import datetime, timezone

import httpx

import deps

logger = logging.getLogger(__name__)


def _get_bc_token_fn():
    """Lazy import to avoid circular imports."""
    from services.graph_access import get_graph_token  # noqa: F401 — not needed here
    # BC token is separate from Graph token
    async def get_bc_token():
        if deps.DEMO_MODE or not deps.BC_CLIENT_ID:
            return "mock-bc-token"
        async with httpx.AsyncClient() as c:
            resp = await c.post(
                f"https://login.microsoftonline.com/{deps.TENANT_ID}/oauth2/v2.0/token",
                data={
                    "grant_type": "client_credentials",
                    "client_id": deps.BC_CLIENT_ID,
                    "client_secret": deps.BC_CLIENT_SECRET,
                    "scope": "https://api.businesscentral.dynamics.com/.default",
                },
            )
            data = resp.json()
            if "access_token" not in data:
                error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
                raise Exception(f"BC token error: {error_desc}")
            return data["access_token"]
    return get_bc_token


async def _get_bc_token():
    """Acquire BC API token."""
    fn = _get_bc_token_fn()
    return await fn()


async def _get_bc_companies():
    """Get BC companies list."""
    from services.bc_api_helpers import get_bc_companies
    return await get_bc_companies()


async def check_duplicate_purchase_invoice(
    vendor_no: str, external_doc_no: str, company_id: str, token: str
) -> dict:
    """
    Check if a Purchase Invoice already exists with the same vendor and external doc number.
    """
    if deps.DEMO_MODE or not deps.BC_CLIENT_ID:
        return {"found": False, "method": "demo"}

    try:
        async with httpx.AsyncClient(timeout=30.0) as c:
            filter_query = f"vendorNumber eq '{vendor_no}' and vendorInvoiceNumber eq '{external_doc_no}'"

            resp = await c.get(
                f"https://api.businesscentral.dynamics.com/v2.0/{deps.TENANT_ID}/{deps.BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": filter_query,
                    "$select": "id,number,vendorNumber,vendorInvoiceNumber,status,totalAmountIncludingTax",
                },
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
                        "method": "api",
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
    token: str = None,
) -> dict:
    """
    Create a Purchase Invoice HEADER only in Business Central.

    SAFETY RULES:
    - Creates ONLY the header, NO lines
    - Sets document to Draft status (does NOT post)
    - Does NOT set quantities or GL accounts
    """
    if deps.DEMO_MODE or not deps.BC_CLIENT_ID:
        mock_invoice_id = str(uuid.uuid4())
        return {
            "success": True,
            "method": "demo",
            "invoice_id": mock_invoice_id,
            "invoice_no": f"PI-DEMO-{mock_invoice_id[:6].upper()}",
            "status": "Draft",
            "note": "Demo mode: Purchase Invoice header would be created in production",
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
            today = datetime.now(timezone.utc).strftime("%Y-%m-%d")

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

            if currency_code and currency_code.upper() not in ("", "USD", "GBP", "EUR"):
                invoice_payload["currencyCode"] = currency_code.upper()

            create_resp = await c.post(
                f"https://api.businesscentral.dynamics.com/v2.0/{deps.TENANT_ID}/{deps.BC_ENVIRONMENT}/api/v2.0/companies({company_id})/purchaseInvoices",
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                },
                json=invoice_payload,
            )

            if create_resp.status_code in (401, 403):
                return {
                    "success": False,
                    "method": "api",
                    "error": f"BC permission denied (HTTP {create_resp.status_code}). Ensure the app has D365 BUS FULL ACCESS permission set in BC.",
                }

            if create_resp.status_code not in (200, 201):
                try:
                    error_data = create_resp.json()
                    error_msg = error_data.get("error", {}).get("message", str(error_data))
                except Exception:
                    error_msg = create_resp.text[:500]
                return {
                    "success": False,
                    "method": "api",
                    "error": f"Failed to create Purchase Invoice (HTTP {create_resp.status_code}): {error_msg}",
                }

            invoice_data = create_resp.json()
            invoice_id = invoice_data.get("id")
            invoice_no = invoice_data.get("number")

            if not invoice_id:
                return {
                    "success": False,
                    "method": "api",
                    "error": f"No invoice ID returned from BC: {invoice_data}",
                }

            logger.info(
                "Created Purchase Invoice draft header: ID=%s, No=%s, Vendor=%s, ExtDoc=%s",
                invoice_id, invoice_no, vendor_no, external_doc_no,
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
                "note": "Created by GPI Hub Automation - Header only, no lines",
            }

    except Exception as e:
        logger.error("Failed to create Purchase Invoice header: %s", str(e))
        return {
            "success": False,
            "method": "api",
            "error": f"Exception creating Purchase Invoice: {str(e)}",
        }
