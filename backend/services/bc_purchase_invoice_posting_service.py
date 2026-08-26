"""Guarded Business Central purchase-invoice posting boundary.

Creating a ``purchaseInvoices`` resource creates/reuses the invoice document; it
is not proof that the invoice was posted. This module owns the explicit BC v2.0
bound ``Microsoft.NAV.post`` action and reconciles the aggregate API identity to
the real posted ``Purch. Inv. Header`` SystemId before callers may report a
fully-ready Posted state.
"""

from typing import Dict, Any

import httpx

from services.gpi_integration_service import (
    GPI_API_BASE,
    BC_STANDARD_API,
    BC_TENANT_ID,
    BC_WRITE_ENVIRONMENT,
    HAS_CREDENTIALS,
    REQUEST_TIMEOUT,
    _check_write_protection,
    _get_token,
    _resolve_company_id,
)
from services.business_central_service import bc_http_with_retry, BCRetriesExhausted
from services.bc_posted_purchase_invoice_identity_service import (
    resolve_posted_purchase_invoice_identity,
)


def _invoice_base_url(company_id: str, system_id: str) -> str:
    return (
        f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/{BC_STANDARD_API}/"
        f"companies({company_id})/purchaseInvoices({system_id})"
    )


async def _verify_posted_by_pdf(client, base_url: str, headers: Dict[str, str]) -> bool:
    """Read-only proof that BC considers the invoice posted."""
    try:
        response = await client.get(f"{base_url}/pdfDocument", headers=headers)
        return response.status_code == 200
    except Exception:
        return False


async def post_purchase_invoice_system_id(bc_system_id: str) -> Dict[str, Any]:
    """Post one existing BC Purchase Invoice and reconcile its real posted identity.

    ``bc_system_id`` is the v2 purchaseInvoices aggregate/draft API identity. It
    is intentionally *not* returned as the table-122 source SystemId. After BC
    confirms posting, the read-only automate API maps this apiId to the actual
    posted Purchase Invoice Header ``id`` and final ``number``.
    """
    system_id = str(bc_system_id or "").strip()
    if not system_id:
        raise ValueError("Cannot post Purchase Invoice without exact BC SystemId")
    if not HAS_CREDENTIALS:
        raise ValueError("BC credentials not configured")

    _check_write_protection("post_purchase_invoice")
    token = await _get_token()
    company_id = await _resolve_company_id(environment=BC_WRITE_ENVIRONMENT)
    base_url = _invoice_base_url(company_id, system_id)
    post_url = f"{base_url}/Microsoft.NAV.post"
    headers = {
        "Authorization": f"Bearer {token}",
        "Accept": "application/json",
        "Content-Type": "application/json",
    }

    response = None
    recovery_verified = False
    retry_meta: Dict[str, Any] = {}

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        async def _send():
            return await client.post(post_url, headers=headers, content=b"")

        try:
            response = await bc_http_with_retry(_send, op="post_purchase_invoice")
            retry_meta = getattr(response, "extensions", {}).get("bc_retry", {})
        except BCRetriesExhausted as exc:
            recovery_verified = await _verify_posted_by_pdf(client, base_url, headers)
            if not recovery_verified:
                raise
            retry_meta = {
                "attempts": exc.attempts,
                "retry_reasons": list(exc.retry_reasons),
                "recovered_after_ambiguous_response": True,
            }

        if response is not None and response.status_code not in (200, 204):
            recovery_verified = await _verify_posted_by_pdf(client, base_url, headers)
            if not recovery_verified:
                detail = response.text[:1000] if response.text else ""
                raise RuntimeError(
                    f"BC Purchase Invoice post failed: HTTP {response.status_code}: {detail}"
                )

    # Critical parity boundary: the API aggregate/draft id may differ from the
    # actual posted Purch. Inv. Header SystemId. Never label table 122 ready until
    # Microsoft automate API gives us the real posted identity.
    posted_identity = await resolve_posted_purchase_invoice_identity(system_id)

    return {
        "success": True,
        "posted": True,
        "bc_api_id": system_id,
        "posted_system_id": posted_identity["posted_system_id"],
        "posted_number": posted_identity["posted_number"],
        "identity_resolution_attempts": posted_identity.get("attempts", 1),
        "http_status": response.status_code if response is not None else None,
        "environment": BC_WRITE_ENVIRONMENT,
        "retry": retry_meta,
        "recovery_verified": recovery_verified,
    }


__all__ = ["post_purchase_invoice_system_id"]
