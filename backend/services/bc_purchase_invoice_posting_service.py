"""Guarded Business Central purchase-invoice posting boundary.

Creating a ``purchaseInvoices`` resource creates/reuses the invoice document; it
is not proof that the invoice was posted. This module owns the explicit BC v2.0
bound ``Microsoft.NAV.post`` action so callers may only report ``Posted`` after
Business Central accepts the posting request or a read-only posted-state check
proves the prior request actually succeeded.
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


def _invoice_base_url(company_id: str, system_id: str) -> str:
    return (
        f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/{BC_STANDARD_API}/"
        f"companies({company_id})/purchaseInvoices({system_id})"
    )


async def _verify_posted_by_pdf(client, base_url: str, headers: Dict[str, str]) -> bool:
    """Read-only proof that BC considers the invoice posted.

    Business Central documents that the purchase-invoice ``pdfDocument``
    navigation is unsupported for unposted invoices. A successful read is
    therefore a strong recovery check after an ambiguous/lost post response.
    """
    try:
        response = await client.get(f"{base_url}/pdfDocument", headers=headers)
        return response.status_code == 200
    except Exception:
        return False


async def post_purchase_invoice_system_id(bc_system_id: str) -> Dict[str, Any]:
    """Post one existing BC Purchase Invoice in the configured write environment.

    Missing identity fails before any network call. Production targeting remains
    blocked by the central write guard. Transient HTTP failures use bounded retry.
    If the post response is ambiguous, a read-only posted-state probe prevents a
    successfully posted invoice from being treated as failed or recreated.
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
            # The server may have committed the post while the client lost every
            # response. Prove posted state before surfacing a retryable failure.
            recovery_verified = await _verify_posted_by_pdf(client, base_url, headers)
            if not recovery_verified:
                raise
            retry_meta = {
                "attempts": exc.attempts,
                "retry_reasons": list(exc.retry_reasons),
                "recovered_after_ambiguous_response": True,
            }

        if response is not None and response.status_code not in (200, 204):
            # A repeat post can be rejected because the first attempt already
            # succeeded. Confirm actual state before treating the rejection as a
            # failure; never infer success from error text alone.
            recovery_verified = await _verify_posted_by_pdf(client, base_url, headers)
            if not recovery_verified:
                detail = response.text[:1000] if response.text else ""
                raise RuntimeError(
                    f"BC Purchase Invoice post failed: HTTP {response.status_code}: {detail}"
                )

    return {
        "success": True,
        "posted": True,
        "bc_system_id": system_id,
        "http_status": response.status_code if response is not None else None,
        "environment": BC_WRITE_ENVIRONMENT,
        "retry": retry_meta,
        "recovery_verified": recovery_verified,
    }


__all__ = ["post_purchase_invoice_system_id"]
