"""Read-only Business Central lookups used before sales-order creation."""

from __future__ import annotations

import os
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


def resolve_bc_environment() -> str:
    """Return the environment used by production BC read services.

    The existing GPI Hub has both legacy sandbox-oriented configuration and newer
    production cache configuration. Read-only sales-order lookup must prefer the
    production environment when it is configured rather than silently falling back
    to ``Sandbox`` through the legacy service constant.
    """

    return str(
        os.environ.get("BC_PROD_ENVIRONMENT")
        or os.environ.get("BC_ENVIRONMENT")
        or os.environ.get("BC_SANDBOX_ENVIRONMENT")
        or BC_ENVIRONMENT
        or "Sandbox"
    ).strip()


async def find_existing_bc_sales_order(
    bc_service,
    *,
    customer_number: str = "",
    external_document_number: str,
) -> Optional[Dict[str, Any]]:
    """Return an existing BC sales order for the customer PO, when present.

    When a customer number is available, both customer and external document
    number are required to match. Historical shell records may not have a resolved
    customer yet; for those records, this read-only lookup can search by external
    document number alone and use the returned header to establish the customer.

    The custom AL import endpoint should still enforce the same uniqueness rule
    transactionally because another process could create an order after this lookup
    and before the write occurs.
    """

    external_document_number = str(external_document_number or "").strip()
    customer_number = str(customer_number or "").strip()
    if not external_document_number:
        return None

    if getattr(bc_service, "use_mock", False):
        return None

    token = await get_bc_token()
    company_id = await bc_service._get_company_id()
    environment = resolve_bc_environment()
    base_url = (
        f"{BC_API_BASE}/{BC_TENANT_ID}/{environment}/api/v2.0/"
        f"companies({company_id})/salesOrders"
    )

    external_number = _odata_literal(external_document_number)
    filters = [f"externalDocumentNumber eq '{external_number}'"]
    if customer_number:
        customer = _odata_literal(customer_number)
        filters.insert(0, f"customerNumber eq '{customer}'")

    params = {
        "$filter": " and ".join(filters),
        "$select": "id,number,customerNumber,externalDocumentNumber,status",
        "$top": "2",
    }

    async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
        response = await client.get(
            base_url,
            headers={"Authorization": f"Bearer {token}"},
            params=params,
        )

    if response.status_code != 200:
        raise RuntimeError(
            "Business Central duplicate lookup failed in environment "
            f"'{environment}': HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    values = response.json().get("value") or []
    if not values:
        return None

    result = dict(values[0])
    result["lookupSource"] = "bc_api"
    result["lookupEnvironment"] = environment
    result["lookupMatchedCustomer"] = bool(customer_number)
    result["multipleMatches"] = len(values) > 1
    return result
