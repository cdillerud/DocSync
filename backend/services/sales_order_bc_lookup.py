"""Read-only Business Central lookups used before sales-order creation."""

from __future__ import annotations

from typing import Any, Dict, Optional

import httpx

from services.business_central_service import (
    BC_API_BASE,
    BC_ENVIRONMENT,
    BC_REQUEST_TIMEOUT,
    BC_TENANT_ID,
    get_bc_token,
)


def _odata_literal(value: str) -> str:
    """Escape a string for use as an OData single-quoted literal."""

    return str(value).replace("'", "''")


async def find_existing_bc_sales_order(
    bc_service,
    *,
    customer_number: str,
    external_document_number: str,
) -> Optional[Dict[str, Any]]:
    """Return an existing BC sales order for the customer PO, when present.

    This is a read-only guard. The custom AL import endpoint should still enforce
    the same uniqueness rule transactionally because another process could create
    an order after this lookup and before the write occurs.
    """

    if getattr(bc_service, "use_mock", False):
        return None

    token = await get_bc_token()
    company_id = await bc_service._get_company_id()
    base_url = (
        f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/"
        f"companies({company_id})/salesOrders"
    )

    customer = _odata_literal(customer_number)
    external_number = _odata_literal(external_document_number)
    params = {
        "$filter": (
            f"customerNumber eq '{customer}' and "
            f"externalDocumentNumber eq '{external_number}'"
        ),
        "$select": "id,number,customerNumber,externalDocumentNumber,status",
        "$top": "1",
    }

    async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
        response = await client.get(
            base_url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )

    if response.status_code != 200:
        raise RuntimeError(
            "Business Central duplicate lookup failed: "
            f"HTTP {response.status_code}: {response.text[:500]}"
        )

    values = response.json().get("value") or []
    return values[0] if values else None
