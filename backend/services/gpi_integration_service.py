"""
GPI Document Hub - GPI Integration API Service

Python client for the GPI Hub Integration BC extension's custom API pages.
Calls the BC REST API endpoints exposed by the AL extension:
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

# Configuration from environment
BC_TENANT_ID = os.environ.get('TENANT_ID') or os.environ.get('BC_TENANT_ID', '')
BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID') or os.environ.get('BC_SANDBOX_CLIENT_ID', '')
BC_CLIENT_SECRET = os.environ.get('BC_CLIENT_SECRET') or os.environ.get('BC_SANDBOX_CLIENT_SECRET', '')
BC_ENVIRONMENT = os.environ.get('BC_ENVIRONMENT') or os.environ.get('BC_SANDBOX_ENVIRONMENT', 'Sandbox')
BC_COMPANY_ID = os.environ.get('BC_COMPANY_ID', '')

GPI_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"
GPI_API_GROUP = "gpi/integration/v1.0"
SOURCE_SYSTEM = "GPI_HUB"
REQUEST_TIMEOUT = 30.0

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


def _build_url(entity_set: str) -> str:
    """Build the URL for a GPI custom API entity set."""
    if BC_COMPANY_ID:
        return f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/{GPI_API_GROUP}/companies({BC_COMPANY_ID})/{entity_set}"
    return f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/{GPI_API_GROUP}/{entity_set}"


async def _api_request(method: str, entity_set: str, payload: Optional[Dict] = None, params: Optional[Dict] = None) -> Dict:
    """Make an authenticated request to the GPI custom BC API."""
    if not HAS_CREDENTIALS:
        raise ValueError("BC credentials not configured. Set BC_TENANT_ID, BC_CLIENT_ID, BC_CLIENT_SECRET in .env")

    token = await _get_token()
    url = _build_url(entity_set)
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
    """List available BC companies via GPI custom API."""
    if not HAS_CREDENTIALS:
        return [{"name": "DEMO", "displayName": "Demo Company (no BC credentials)"}]

    url = f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/{GPI_API_GROUP}/companies"
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
) -> Dict[str, Any]:
    """Create a Sales Order in BC via GPI custom API."""
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

    result = await _api_request("POST", "salesOrderRequests", payload)
    return {
        "success": result.get("resultSuccess", False),
        "bc_record_no": result.get("resultRecordNo", ""),
        "bc_system_id": result.get("resultSystemId", ""),
        "status": result.get("resultStatus", ""),
        "error_message": result.get("errorMessage", ""),
        "idempotency_key": idempotency_key,
        "transaction_id": transaction_id,
    }


async def create_purchase_invoice(
    vendor_no: str,
    vendor_invoice_no: str = "",
    document_date: str = "",
    posting_date: str = "",
    source_doc_id: str = "",
    idempotency_key: str = "",
    transaction_id: str = "",
) -> Dict[str, Any]:
    """Create a Purchase Invoice in BC via GPI custom API."""
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

    result = await _api_request("POST", "purchaseInvoiceRequests", payload)
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
    """Create a Customer in BC via GPI custom API."""
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

    result = await _api_request("POST", "customerRequests", payload)
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
    """Create a Vendor in BC via GPI custom API."""
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

    result = await _api_request("POST", "vendorRequests", payload)
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
        "environment": BC_ENVIRONMENT,
        "company_id": BC_COMPANY_ID[:8] + "..." if BC_COMPANY_ID else "auto-detect",
        "source_system": SOURCE_SYSTEM,
        "api_group": GPI_API_GROUP,
    }
