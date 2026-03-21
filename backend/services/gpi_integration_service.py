"""
GPI Document Hub - GPI Integration API Service

Python client for the GPI Hub Integration BC extension's custom API pages.
Uses SPLIT ENVIRONMENT model:
  - READ operations → BC_READ_ENVIRONMENT (Production)
  - WRITE operations → BC_WRITE_ENVIRONMENT (Sandbox)

Custom API endpoints (on the WRITE environment):
  - /api/gpi/integration/v1.0/companies({companyId})/salesOrderRequests
  - /api/gpi/integration/v1.0/companies({companyId})/purchaseInvoiceRequests
  - /api/gpi/integration/v1.0/companies({companyId})/customerRequests
  - /api/gpi/integration/v1.0/companies({companyId})/vendorRequests
  - /api/gpi/integration/v1.0/companies({companyId})/integrationLogs
  - /api/gpi/integration/v1.0/companies
"""

import os
import uuid
import logging
import httpx
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

# Configuration from environment — shared credentials
BC_TENANT_ID = os.environ.get('TENANT_ID') or os.environ.get('BC_TENANT_ID', '')
BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID') or os.environ.get('BC_SANDBOX_CLIENT_ID', '')
BC_CLIENT_SECRET = os.environ.get('BC_CLIENT_SECRET') or os.environ.get('BC_SANDBOX_CLIENT_SECRET', '')
BC_COMPANY_ID = os.environ.get('BC_COMPANY_ID', '')

# Split environment routing
BC_READ_ENVIRONMENT = os.environ.get('BC_READ_ENVIRONMENT') or os.environ.get('BC_PROD_ENVIRONMENT', 'Production')
BC_WRITE_ENVIRONMENT = os.environ.get('BC_WRITE_ENVIRONMENT') or os.environ.get('BC_SANDBOX_ENVIRONMENT', 'Sandbox_11_3_2025')
BC_BLOCK_PRODUCTION_WRITES = os.environ.get('BC_BLOCK_PRODUCTION_WRITES', 'true').lower() == 'true'

# Legacy alias (some code references BC_ENVIRONMENT)
BC_ENVIRONMENT = BC_READ_ENVIRONMENT

GPI_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"
GPI_API_GROUP = "gpi/integration/v1.0"
BC_STANDARD_API = "v2.0"
SOURCE_SYSTEM = "GPI_HUB"
REQUEST_TIMEOUT = 30.0

# Sales Order line defaults
BC_SO_FALLBACK_GL_ACCOUNT = os.environ.get('BC_SO_FALLBACK_GL_ACCOUNT', '')
BC_SO_FALLBACK_ITEM_CODE = os.environ.get('BC_SO_FALLBACK_ITEM_CODE', os.environ.get('BC_DEFAULT_ITEM_CODE', ''))

# Token cache
_token_cache = {"access_token": None, "expires_at": 0}

# Check if real BC credentials are available
HAS_CREDENTIALS = bool(BC_TENANT_ID and BC_CLIENT_ID and BC_CLIENT_SECRET)


async def _get_token() -> str:
    """Get OAuth2 token for BC API access."""
    import time
    if _token_cache["access_token"] and time.time() < _token_cache["expires_at"] - 60:
        return _token_cache["access_token"]

    token_url = f"https://login.microsoftonline.com/{BC_TENANT_ID}/oauth2/v2.0/token"
    async with httpx.AsyncClient(timeout=15.0) as client:
        resp = await client.post(token_url, data={
            "grant_type": "client_credentials",
            "client_id": BC_CLIENT_ID,
            "client_secret": BC_CLIENT_SECRET,
            "scope": "https://api.businesscentral.dynamics.com/.default",
        })
        resp.raise_for_status()
        data = resp.json()
        _token_cache["access_token"] = data["access_token"]
        _token_cache["expires_at"] = time.time() + data.get("expires_in", 3600)
        return data["access_token"]


def _check_write_protection(operation: str):
    """Hard guard: refuse writes to Production."""
    if not BC_BLOCK_PRODUCTION_WRITES:
        return
    target = BC_WRITE_ENVIRONMENT.lower()
    if target == "production" or target.startswith("prod"):
        raise ValueError(
            f"BLOCKED: Write operation '{operation}' refused — target environment "
            f"'{BC_WRITE_ENVIRONMENT}' resolves to Production and BC_BLOCK_PRODUCTION_WRITES=true."
        )


def _build_url(entity_set: str, environment: str = None) -> str:
    """Build the URL for a GPI custom API entity set."""
    env = environment or BC_WRITE_ENVIRONMENT
    if BC_COMPANY_ID:
        return f"{GPI_API_BASE}/{BC_TENANT_ID}/{env}/api/{GPI_API_GROUP}/companies({BC_COMPANY_ID})/{entity_set}"
    return f"{GPI_API_BASE}/{BC_TENANT_ID}/{env}/api/{GPI_API_GROUP}/{entity_set}"


async def _api_request(method: str, entity_set: str, payload: Optional[Dict] = None, params: Optional[Dict] = None, environment: str = None) -> Dict:
    """Make an authenticated request to the GPI custom BC API."""
    if not HAS_CREDENTIALS:
        raise ValueError("BC credentials not configured. Set BC_TENANT_ID, BC_CLIENT_ID, BC_CLIENT_SECRET in .env")

    token = await _get_token()
    url = _build_url(entity_set, environment=environment)
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
        "Accept": "application/json",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        if method == "GET":
            resp = await client.get(url, headers=headers, params=params)
        elif method == "POST":
            resp = await client.post(url, headers=headers, json=payload)
        else:
            raise ValueError(f"Unsupported method: {method}")

        if resp.status_code >= 400:
            logger.error("GPI API %s %s failed: %s %s", method, entity_set, resp.status_code, resp.text[:500])
        resp.raise_for_status()
        return resp.json()


def _generate_idempotency_key(prefix: str, source_doc_id: str = "") -> str:
    """Generate an idempotency key for a request."""
    if source_doc_id:
        return f"{prefix}_{source_doc_id}_{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
    return f"{prefix}_{uuid.uuid4().hex[:16]}"


# =========================================================================
# PUBLIC API
# =========================================================================

async def list_companies() -> List[Dict]:
    """List available BC companies via GPI custom API (READ environment)."""
    if not HAS_CREDENTIALS:
        return [{"name": "DEMO", "displayName": "Demo Company (no BC credentials)"}]

    url = f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/{GPI_API_GROUP}/companies"
    token = await _get_token()
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.get(url, headers=headers)
        resp.raise_for_status()
        data = resp.json()
        return data.get("value", [])


async def create_sales_order(
    customer_no: str,
    external_doc_no: str = "",
    order_date: str = "",
    source_doc_id: str = "",
    idempotency_key: str = "",
    transaction_id: str = "",
    ship_to_code: str = "",
    ship_to_name: str = "",
    location_code: str = "",
) -> Dict[str, Any]:
    """Create a Sales Order in BC WRITE environment (Sandbox) via GPI custom API.

    Optional fields for Drop-Ship vs Warehouse routing:
      ship_to_code  – BC Ship-to Code (customer alt-address for dropships)
      ship_to_name  – Ship-to name override
      location_code – BC Location Code (warehouse code, e.g. "MAIN")
    """
    _check_write_protection("create_sales_order")
    if not idempotency_key:
        idempotency_key = _generate_idempotency_key("SO", source_doc_id)
    if not transaction_id:
        transaction_id = f"TXN_{uuid.uuid4().hex[:12]}"

    payload = {
        "idempotencyKey": idempotency_key,
        "sourceSystem": SOURCE_SYSTEM,
        "sourceDocumentId": source_doc_id or "",
        "transactionId": transaction_id,
        "customerNo": customer_no,
        "externalDocumentNo": external_doc_no or "",
        "orderDate": order_date or datetime.now(timezone.utc).strftime("%Y-%m-%d"),
    }

    # Conditional routing fields for Drop-Ship vs Warehouse
    if ship_to_code:
        payload["shipToCode"] = ship_to_code
    if ship_to_name:
        payload["shipToName"] = ship_to_name
    if location_code:
        payload["locationCode"] = location_code

    result = await _api_request("POST", "salesOrderRequests", payload, environment=BC_WRITE_ENVIRONMENT)
    return {
        "success": result.get("resultSuccess", False),
        "bc_record_no": result.get("resultRecordNo", ""),
        "bc_system_id": result.get("resultSystemId", ""),
        "status": result.get("resultStatus", ""),
        "error_message": result.get("errorMessage", ""),
        "idempotency_key": idempotency_key,
        "transaction_id": transaction_id,
    }


async def _get_company_id_standard_api() -> str:
    """Get the BC company ID using the standard API (for line creation)."""
    token = await _get_token()
    url = f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/{BC_STANDARD_API}/companies"
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}", "Accept": "application/json"})
        resp.raise_for_status()
        companies = resp.json().get("value", [])
        if not companies:
            raise ValueError("No BC companies found")
        return companies[0]["id"]


async def add_sales_order_lines(
    order_system_id: str,
    lines: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Add line items to an existing Sales Order using the standard BC API.

    Each line dict should have:
      lineType: "Item" | "Account" | "Comment"
      lineObjectNumber: item number or G/L account number
      description: text
      quantity: number
      unitPrice: number
    """
    _check_write_protection("add_sales_order_lines")
    if not HAS_CREDENTIALS:
        raise ValueError("BC credentials not configured")

    token = await _get_token()
    company_id = await _get_company_id_standard_api()
    url = f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/{BC_STANDARD_API}/companies({company_id})/salesOrders({order_system_id})/salesOrderLines"

    added = 0
    errors = []

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for idx, line in enumerate(lines):
            line_payload = {
                "lineType": line.get("lineType", "Item"),
                "quantity": float(line.get("quantity", 1) or 1),
            }
            if line.get("lineObjectNumber"):
                line_payload["lineObjectNumber"] = line["lineObjectNumber"]
            if line.get("description"):
                line_payload["description"] = line["description"][:100]
            if line.get("unitPrice") is not None and float(line.get("unitPrice", 0)) > 0:
                line_payload["unitPrice"] = float(line["unitPrice"])

            logger.info("Adding SO line %d/%d: type=%s obj=%s qty=%s price=$%s",
                        idx + 1, len(lines), line_payload.get("lineType"),
                        line_payload.get("lineObjectNumber", "N/A"),
                        line_payload["quantity"], line_payload.get("unitPrice", 0))

            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=line_payload,
            )

            if resp.status_code in (200, 201):
                added += 1
            else:
                error_text = resp.text[:300]
                logger.warning("Failed to add SO line %d: HTTP %d - %s", idx + 1, resp.status_code, error_text)
                errors.append({"line": idx + 1, "status": resp.status_code, "error": error_text})

    return {"added": added, "total": len(lines), "errors": errors}


async def attach_document_to_bc_record(
    bc_record_id: str,
    file_name: str,
    file_content: bytes,
    bc_entity: str = "purchaseInvoices",
    content_type: str = None,
) -> Dict[str, Any]:
    """Attach a document to a BC record in the WRITE environment via documentAttachments API."""
    _check_write_protection("attach_document_to_bc_record")
    if not HAS_CREDENTIALS:
        raise ValueError("BC credentials not configured")

    token = await _get_token()
    company_id = await _get_company_id_standard_api()

    if not content_type:
        ext = file_name.lower().rsplit('.', 1)[-1] if '.' in file_name else ''
        ct_map = {'pdf': 'application/pdf', 'png': 'image/png', 'jpg': 'image/jpeg',
                  'jpeg': 'image/jpeg', 'doc': 'application/msword', 'xlsx': 'application/vnd.openxmlformats-officedocument.spreadsheetml.sheet',
                  'txt': 'text/plain'}
        content_type = ct_map.get(ext, 'application/octet-stream')

    base = f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/{BC_STANDARD_API}/companies({company_id})"
    attach_url = f"{base}/{bc_entity}({bc_record_id})/documentAttachments"

    async with httpx.AsyncClient(timeout=60.0) as client:
        # Step 1: Create attachment metadata
        create_resp = await client.post(
            attach_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"fileName": file_name},
        )
        if create_resp.status_code not in (200, 201):
            error_msg = create_resp.text[:300]
            try:
                error_msg = create_resp.json().get("error", {}).get("message", error_msg)
            except Exception:
                pass
            return {"success": False, "error": f"Failed to create attachment (HTTP {create_resp.status_code}): {error_msg}"}

        attachment_data = create_resp.json()
        attachment_id = attachment_data.get("id")
        if not attachment_id:
            return {"success": False, "error": "No attachment ID returned"}

        # Step 2: Upload file content
        content_url = f"{base}/{bc_entity}({bc_record_id})/documentAttachments({attachment_id})/attachmentContent"
        upload_resp = await client.patch(
            content_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": content_type, "If-Match": "*"},
            content=file_content,
        )
        if upload_resp.status_code not in (200, 204):
            error_msg = upload_resp.text[:300]
            return {"success": False, "error": f"Failed to upload content (HTTP {upload_resp.status_code}): {error_msg}"}

    logger.info("Attached '%s' to BC %s %s", file_name, bc_entity, bc_record_id)
    return {"success": True, "method": "api", "attachment_id": attachment_id}


async def create_gpi_document_link(
    bc_system_id: str,
    bc_document_no: str,
    document_type: str,
    sharepoint_url: str = "",
    sharepoint_drive_id: str = "",
    sharepoint_item_id: str = "",
    uploaded_by: str = "GPI Hub",
    source: str = "GPIHub",
) -> Dict[str, Any]:
    """Create a GPI Document Link record in BC via the gpi/documents/v1.0 API.
    This populates the GPI Documents factbox on the Purchase Invoice page.
    """
    _check_write_protection("create_gpi_document_link")
    if not HAS_CREDENTIALS:
        raise ValueError("BC credentials not configured")

    token = await _get_token()
    company_id = await _get_company_id_standard_api()
    doc_link_api = "gpi/documents/v1.0"
    url = f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/{doc_link_api}/companies({company_id})/documentLinks"

    payload = {
        "documentType": document_type,
        "targetSystemId": bc_system_id,
        "bcDocumentNo": bc_document_no,
        "sharePointUrl": sharepoint_url,
        "sharePointDriveId": sharepoint_drive_id,
        "sharePointItemId": sharepoint_item_id,
        "uploadedBy": uploaded_by,
        "source": source,
    }

    async with httpx.AsyncClient(timeout=30.0) as client:
        resp = await client.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        if resp.status_code in (200, 201):
            data = resp.json()
            logger.info("Created GPI Document Link for %s %s", document_type, bc_document_no)
            return {"success": True, "entry_no": data.get("entryNo"), "id": data.get("id")}
        else:
            error_msg = resp.text[:300]
            try:
                error_msg = resp.json().get("error", {}).get("message", error_msg)
            except Exception:
                pass
            logger.warning("Failed to create GPI Document Link (HTTP %d): %s", resp.status_code, error_msg)
            return {"success": False, "error": f"HTTP {resp.status_code}: {error_msg}"}


# Fallback defaults for purchase invoice lines
BC_PI_FALLBACK_GL_ACCOUNT = os.environ.get('BC_PI_FALLBACK_GL_ACCOUNT', '60500')
BC_PI_FALLBACK_ITEM_CODE = os.environ.get('BC_PI_FALLBACK_ITEM_CODE', os.environ.get('BC_DEFAULT_ITEM_CODE', ''))


async def delete_purchase_invoice_lines(
    invoice_system_id: str,
) -> Dict[str, Any]:
    """Delete all existing line items from a Purchase Invoice using the standard BC API.
    Returns {deleted: int, errors: [...]}.
    """
    _check_write_protection("delete_purchase_invoice_lines")
    if not HAS_CREDENTIALS:
        raise ValueError("BC credentials not configured")

    token = await _get_token()
    company_id = await _get_company_id_standard_api()
    base_url = f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/{BC_STANDARD_API}/companies({company_id})/purchaseInvoices({invoice_system_id})/purchaseInvoiceLines"

    deleted = 0
    errors = []

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        # Fetch existing lines
        resp = await client.get(
            base_url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )
        if resp.status_code != 200:
            return {"deleted": 0, "errors": [{"error": f"Failed to fetch lines: HTTP {resp.status_code}"}]}

        existing_lines = resp.json().get("value", [])
        if not existing_lines:
            return {"deleted": 0, "errors": []}

    # Delete each line in a fresh client to avoid connection reuse issues
    for line in existing_lines:
        line_id = line.get("id")
        if not line_id:
            continue
        etag = line.get("@odata.etag", "*")
        try:
            async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as del_client:
                del_resp = await del_client.delete(
                    f"{base_url}({line_id})",
                    headers={
                        "Authorization": f"Bearer {token}",
                        "If-Match": etag,
                    },
                )
                if del_resp.status_code in (200, 204):
                    deleted += 1
                else:
                    errors.append({"line_id": line_id, "status": del_resp.status_code, "error": del_resp.text[:200]})
        except Exception as e:
            # BC may close connection after DELETE; treat as success if line is gone
            logger.warning("Delete line %s raised %s, verifying...", line_id, str(e)[:100])
            try:
                async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as check_client:
                    check = await check_client.get(
                        f"{base_url}({line_id})",
                        headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                    )
                    if check.status_code == 404:
                        deleted += 1  # Line was deleted despite the error
                    else:
                        errors.append({"line_id": line_id, "error": str(e)[:200]})
            except Exception:
                errors.append({"line_id": line_id, "error": str(e)[:200]})

    logger.info("Deleted %d/%d existing lines from PI %s", deleted, len(existing_lines), invoice_system_id)
    return {"deleted": deleted, "total_existing": len(existing_lines), "errors": errors}


async def add_purchase_invoice_lines(
    invoice_system_id: str,
    lines: List[Dict[str, Any]],
) -> Dict[str, Any]:
    """Add line items to an existing Purchase Invoice using the standard BC API.

    Each line dict should have:
      lineType: "Item" | "Account" | "Comment"
      lineObjectNumber: item number or G/L account number
      description: text
      quantity: number
      unitCost: number
    """
    _check_write_protection("add_purchase_invoice_lines")
    if not HAS_CREDENTIALS:
        raise ValueError("BC credentials not configured")

    token = await _get_token()
    company_id = await _get_company_id_standard_api()
    url = f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/{BC_STANDARD_API}/companies({company_id})/purchaseInvoices({invoice_system_id})/purchaseInvoiceLines"

    added = 0
    errors = []

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for idx, line in enumerate(lines):
            line_type = line.get("lineType", "")
            line_obj = line.get("lineObjectNumber", "")

            # Resolve line type and object number
            if not line_type:
                if line_obj:
                    line_type = "Item"
                elif BC_PI_FALLBACK_GL_ACCOUNT:
                    line_type = "Account"
                    line_obj = BC_PI_FALLBACK_GL_ACCOUNT
                elif BC_PI_FALLBACK_ITEM_CODE:
                    line_type = "Item"
                    line_obj = BC_PI_FALLBACK_ITEM_CODE
                else:
                    # Default to Comment if no item/account available
                    line_type = "Comment"

            line_payload = {
                "lineType": line_type,
                "quantity": float(line.get("quantity", 1) or 1),
            }
            if line_obj and line_type != "Comment":
                line_payload["lineObjectNumber"] = line_obj
            if line.get("description"):
                line_payload["description"] = str(line["description"])[:100]
            if line.get("unitCost") is not None and float(line.get("unitCost", 0)) > 0:
                line_payload["unitCost"] = float(line["unitCost"])

            logger.info("Adding PI line %d/%d: type=%s obj=%s qty=%s cost=$%s desc=%s",
                        idx + 1, len(lines), line_payload.get("lineType"),
                        line_payload.get("lineObjectNumber", "N/A"),
                        line_payload["quantity"], line_payload.get("unitCost", 0),
                        line_payload.get("description", "")[:40])

            resp = await client.post(
                url,
                headers={
                    "Authorization": f"Bearer {token}",
                    "Content-Type": "application/json",
                    "Accept": "application/json",
                },
                json=line_payload,
            )

            if resp.status_code in (200, 201):
                added += 1
            else:
                error_text = resp.text[:300]
                logger.warning("Failed to add PI line %d: HTTP %d - %s", idx + 1, resp.status_code, error_text)
                errors.append({"line": idx + 1, "status": resp.status_code, "error": error_text})

    return {"added": added, "total": len(lines), "errors": errors}


async def create_purchase_invoice(
    vendor_no: str,
    vendor_invoice_no: str = "",
    document_date: str = "",
    posting_date: str = "",
    source_doc_id: str = "",
    idempotency_key: str = "",
    transaction_id: str = "",
) -> Dict[str, Any]:
    """Create a Purchase Invoice in BC WRITE environment (Sandbox) via GPI custom API."""
    _check_write_protection("create_purchase_invoice")
    if not idempotency_key:
        idempotency_key = _generate_idempotency_key("PI", source_doc_id)
    if not transaction_id:
        transaction_id = f"TXN_{uuid.uuid4().hex[:12]}"

    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    payload = {
        "idempotencyKey": idempotency_key,
        "sourceSystem": SOURCE_SYSTEM,
        "sourceDocumentId": source_doc_id or "",
        "transactionId": transaction_id,
        "vendorNo": vendor_no,
        "vendorInvoiceNo": vendor_invoice_no or "",
        "documentDate": document_date or today,
        "postingDate": posting_date or today,
    }

    result = await _api_request("POST", "purchaseInvoiceRequests", payload, environment=BC_WRITE_ENVIRONMENT)
    return {
        "success": result.get("resultSuccess", False),
        "bc_record_no": result.get("resultRecordNo", ""),
        "bc_system_id": result.get("resultSystemId", ""),
        "status": result.get("resultStatus", ""),
        "error_message": result.get("errorMessage", ""),
        "idempotency_key": idempotency_key,
        "transaction_id": transaction_id,
    }


async def create_customer(
    name: str,
    address: str = "",
    city: str = "",
    state_code: str = "",
    postal_code: str = "",
    country_code: str = "",
    source_doc_id: str = "",
    idempotency_key: str = "",
) -> Dict[str, Any]:
    """Create a Customer in BC WRITE environment (Sandbox) via GPI custom API."""
    _check_write_protection("create_customer")
    if not idempotency_key:
        idempotency_key = _generate_idempotency_key("CUST", source_doc_id)

    payload = {
        "idempotencyKey": idempotency_key,
        "sourceSystem": SOURCE_SYSTEM,
        "sourceDocumentId": source_doc_id or "",
        "name": name,
        "address": address or "",
        "city": city or "",
        "stateCode": state_code or "",
        "postalCode": postal_code or "",
        "countryCode": country_code or "",
    }

    result = await _api_request("POST", "customerRequests", payload, environment=BC_WRITE_ENVIRONMENT)
    return {
        "success": result.get("resultSuccess", False),
        "bc_record_no": result.get("resultRecordNo", ""),
        "bc_system_id": result.get("resultSystemId", ""),
        "status": result.get("resultStatus", ""),
        "error_message": result.get("errorMessage", ""),
        "idempotency_key": idempotency_key,
    }


async def create_vendor(
    name: str,
    address: str = "",
    city: str = "",
    state_code: str = "",
    postal_code: str = "",
    country_code: str = "",
    source_doc_id: str = "",
    idempotency_key: str = "",
) -> Dict[str, Any]:
    """Create a Vendor in BC WRITE environment (Sandbox) via GPI custom API."""
    _check_write_protection("create_vendor")
    if not idempotency_key:
        idempotency_key = _generate_idempotency_key("VEND", source_doc_id)

    payload = {
        "idempotencyKey": idempotency_key,
        "sourceSystem": SOURCE_SYSTEM,
        "sourceDocumentId": source_doc_id or "",
        "name": name,
        "address": address or "",
        "city": city or "",
        "stateCode": state_code or "",
        "postalCode": postal_code or "",
        "countryCode": country_code or "",
    }

    result = await _api_request("POST", "vendorRequests", payload, environment=BC_WRITE_ENVIRONMENT)
    return {
        "success": result.get("resultSuccess", False),
        "bc_record_no": result.get("resultRecordNo", ""),
        "bc_system_id": result.get("resultSystemId", ""),
        "status": result.get("resultStatus", ""),
        "error_message": result.get("errorMessage", ""),
        "idempotency_key": idempotency_key,
    }


async def list_integration_logs(
    record_type: str = "",
    status: str = "",
    top: int = 50,
) -> List[Dict]:
    """List integration logs from BC."""
    params = {"$top": str(top), "$orderby": "entryNo desc"}
    filters = []
    if record_type:
        filters.append(f"recordType eq '{record_type}'")
    if status:
        filters.append(f"requestStatus eq '{status}'")
    if filters:
        params["$filter"] = " and ".join(filters)

    result = await _api_request("GET", "integrationLogs", params=params)
    return result.get("value", [])


def get_integration_status() -> Dict:
    """Get the status of the GPI Integration API configuration."""
    return {
        "configured": HAS_CREDENTIALS,
        "tenant_id": BC_TENANT_ID[:8] + "..." if BC_TENANT_ID else "",
        "read_environment": BC_READ_ENVIRONMENT,
        "write_environment": BC_WRITE_ENVIRONMENT,
        "block_production_writes": BC_BLOCK_PRODUCTION_WRITES,
        "environment": BC_WRITE_ENVIRONMENT,
        "company_id": BC_COMPANY_ID[:8] + "..." if BC_COMPANY_ID else "auto-detect",
        "source_system": SOURCE_SYSTEM,
        "api_group": GPI_API_GROUP,
    }
