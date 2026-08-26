"""Guarded Business Central purchase-invoice posting boundary.

Creating a ``purchaseInvoices`` resource creates/reuses the invoice document; it
is not proof that the invoice was posted.  This module owns the explicit BC v2.0
bound ``Microsoft.NAV.post`` action so callers may only report ``Posted`` after
Business Central accepts the posting request.
"""

from typing import Dict, Any

import httpx

from services.gpi_integration_service import (
    BC_API_BASE,
    BC_STANDARD_API,
    BC_TENANT_ID,
    BC_WRITE_ENVIRONMENT,
    HAS_CREDENTIALS,
    REQUEST_TIMEOUT,
    _check_write_protection,
    _get_token,
    _resolve_company_id,
)
from services.business_central_service import bc_http_with_retry


async def post_purchase_invoice_system_id(bc_system_id: str) -> Dict[str, Any]:
    """Post one existing BC Purchase Invoice in the configured write environment.

    Returns a small explicit result.  Missing identity fails before any network
    call.  Production targeting remains blocked by the central write guard.
    Transient HTTP failures use the same bounded retry policy as other BC writes.
    """
    system_id = str(bc_system_id or "").strip()
    if not system_id:
        raise ValueError("Cannot post Purchase Invoice without exact BC SystemId")
    if not HAS_CREDENTIALS:
        raise ValueError("BC credentials not configured")

    _check_write_protection("post_purchase_invoice")
    token = await _get_token()
    company_id = await _resolve_company_id(environment=BC_WRITE_ENVIRONMENT)
    url = (
        f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/{BC_STANDARD_API}/"
        f"companies({company_id})/purchaseInvoices({system_id})/Microsoft.NAV.post"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        async def _send():
            return await client.post(url, headers=headers, content=b"")

        response = await bc_http_with_retry(_send, op="post_purchase_invoice")

    if response.status_code not in (200, 204):
        detail = response.text[:1000] if response.text else ""
        raise RuntimeError(
            f"BC Purchase Invoice post failed: HTTP {response.status_code}: {detail}"
        )

    retry_meta = getattr(response, "extensions", {}).get("bc_retry", {})
    return {
        "success": True,
        "posted": True,
        "bc_system_id": system_id,
        "http_status": response.status_code,
        "environment": BC_WRITE_ENVIRONMENT,
        "retry": retry_meta,
    }


__all__ = ["post_purchase_invoice_system_id"]
