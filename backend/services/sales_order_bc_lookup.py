"""Read-only Business Central lookups used before sales-order creation."""

from __future__ import annotations

import os
from typing import Any, Dict, Optional

import httpx

from services.business_central_service import (
    BC_API_BASE,
    BC_COMPANY_NAME,
    BC_REQUEST_TIMEOUT,
    BC_TENANT_ID,
    get_bc_token,
)


def _odata_literal(value: str) -> str:
    """Escape a string for use as an OData single-quoted literal."""

    return str(value).replace("'", "''")


def resolve_bc_environment() -> str:
    """Return the production environment used for historical read lookups.

    New sales-order writes are validated against a separate sandbox. Historical
    duplicate detection and order hydration must therefore never inherit the write
    environment from ``BC_ENVIRONMENT`` or ``BC_SANDBOX_ENVIRONMENT``.
    """

    return str(
        os.environ.get("BC_HISTORY_ENVIRONMENT")
        or os.environ.get("BC_PROD_ENVIRONMENT")
        or "Production"
    ).strip()


async def resolve_bc_company_id(
    bc_service,
    *,
    token: str,
    environment: str,
) -> str:
    """Resolve the company inside the production history environment."""

    history_cache_key = "_history_company_id"
    cached_company_id = getattr(bc_service, history_cache_key, None)
    if cached_company_id:
        return str(cached_company_id)

    configured_company_id = str(
        os.environ.get("BC_HISTORY_COMPANY_ID")
        or os.environ.get("BC_PROD_COMPANY_ID")
        or ""
    ).strip()
    if configured_company_id:
        setattr(bc_service, history_cache_key, configured_company_id)
        return configured_company_id

    companies_url = (
        f"{BC_API_BASE}/{BC_TENANT_ID}/{environment}/api/v2.0/companies"
    )
    async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
        response = await client.get(
            companies_url,
            headers={"Authorization": f"Bearer {token}"},
        )

    if response.status_code != 200:
        raise RuntimeError(
            "Business Central company lookup failed in history environment "
            f"'{environment}': HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    companies = response.json().get("value") or []
    if not companies:
        raise RuntimeError(
            f"No Business Central companies were found in '{environment}'"
        )

    company_name = str(
        os.environ.get("BC_HISTORY_COMPANY_NAME")
        or os.environ.get("BC_PROD_COMPANY_NAME")
        or os.environ.get("BC_COMPANY_NAME")
        or BC_COMPANY_NAME
        or ""
    ).strip().lower()

    selected = None
    if company_name:
        for company in companies:
            candidate_name = str(
                company.get("displayName") or company.get("name") or ""
            ).strip().lower()
            if candidate_name == company_name:
                selected = company
                break

    selected = selected or companies[0]
    company_id = str(selected.get("id") or "").strip()
    if not company_id:
        raise RuntimeError(
            f"Business Central company in '{environment}' had no ID"
        )

    setattr(bc_service, history_cache_key, company_id)
    return company_id


async def find_existing_bc_sales_order(
    bc_service,
    *,
    customer_number: str = "",
    external_document_number: str,
) -> Optional[Dict[str, Any]]:
    """Return an existing production BC sales order for a customer PO.

    When a customer number is available, both customer and external document
    number are required to match. Historical shell records may not have a resolved
    customer yet; for those records, this read-only lookup can search by external
    document number alone and use the returned header to establish the customer.

    This function is read-only. The separate sales-order writer remains configured
    for the validation sandbox and retains its own final duplicate guard.
    """

    external_document_number = str(external_document_number or "").strip()
    customer_number = str(customer_number or "").strip()
    if not external_document_number:
        return None

    if getattr(bc_service, "use_mock", False):
        return None

    token = await get_bc_token()
    environment = resolve_bc_environment()
    company_id = await resolve_bc_company_id(
        bc_service,
        token=token,
        environment=environment,
    )
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
            "Business Central duplicate lookup failed in history environment "
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
