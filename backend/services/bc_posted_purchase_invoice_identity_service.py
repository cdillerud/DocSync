"""Resolve the real posted Purchase Invoice record identity after BC posting.

Business Central API v2 ``purchaseInvoices.id`` is an aggregate/API identity.
Microsoft documents that it can differ from the ``Purch. Inv. Header`` SystemId
because the draft identity is carried into the API aggregate after posting. The
read-only ``microsoft/automate/v1.0/postedPurchaseInvoices`` API exposes both the
real posted record ``id`` and the aggregate ``apiId``. This service reconciles
those identities so GPI_SourceSystemId for source table 122 is never guessed.
"""

import asyncio
from typing import Any, Dict

import httpx

from services.gpi_integration_service import (
    GPI_API_BASE,
    BC_TENANT_ID,
    BC_WRITE_ENVIRONMENT,
    HAS_CREDENTIALS,
    REQUEST_TIMEOUT,
    _get_token,
    _resolve_company_id,
)


class PostedPurchaseInvoiceIdentityNotFound(RuntimeError):
    pass


async def resolve_posted_purchase_invoice_identity(
    api_id: str,
    *,
    max_attempts: int = 4,
) -> Dict[str, Any]:
    """Map a v2 purchaseInvoices API id to the real posted header SystemId.

    This is read-only. A short bounded retry handles the normal post/materialize
    timing window. Exactly one apiId match is required; zero/ambiguous results
    fail closed.
    """
    aggregate_id = str(api_id or "").strip()
    if not aggregate_id:
        raise ValueError("Posted Purchase Invoice reconciliation requires API id")
    if not HAS_CREDENTIALS:
        raise ValueError("BC credentials not configured")

    token = await _get_token()
    company_id = await _resolve_company_id(environment=BC_WRITE_ENVIRONMENT)
    url = (
        f"{GPI_API_BASE}/{BC_TENANT_ID}/{BC_WRITE_ENVIRONMENT}/api/"
        f"microsoft/automate/v1.0/companies({company_id})/postedPurchaseInvoices"
    )
    headers = {"Authorization": f"Bearer {token}", "Accept": "application/json"}
    params = {
        "$filter": f"apiId eq {aggregate_id}",
        "$select": "id,number,apiId",
    }

    attempts = max(1, int(max_attempts))
    last_detail = ""
    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        for attempt in range(1, attempts + 1):
            response = await client.get(url, headers=headers, params=params)
            if response.status_code == 200:
                values = response.json().get("value", [])
                exact = [
                    row for row in values
                    if str(row.get("apiId") or "").lower() == aggregate_id.lower()
                ]
                if len(exact) == 1:
                    row = exact[0]
                    system_id = str(row.get("id") or "").strip()
                    number = str(row.get("number") or "").strip()
                    if system_id and number:
                        return {
                            "posted_system_id": system_id,
                            "posted_number": number,
                            "api_id": aggregate_id,
                            "attempts": attempt,
                        }
                    last_detail = "matched posted record lacked id or number"
                elif len(exact) > 1:
                    raise PostedPurchaseInvoiceIdentityNotFound(
                        f"Ambiguous posted Purchase Invoice identity for apiId {aggregate_id}: {len(exact)} matches"
                    )
                else:
                    last_detail = "no matching postedPurchaseInvoices row yet"
            else:
                last_detail = f"HTTP {response.status_code}: {response.text[:500]}"

            if attempt < attempts:
                await asyncio.sleep(0.5 * (2 ** (attempt - 1)))

    raise PostedPurchaseInvoiceIdentityNotFound(
        f"Could not resolve posted Purchase Invoice for apiId {aggregate_id} after {attempts} attempts: {last_detail}"
    )


__all__ = [
    "resolve_posted_purchase_invoice_identity",
    "PostedPurchaseInvoiceIdentityNotFound",
]
