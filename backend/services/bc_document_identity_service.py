"""Resolve exact Business Central record identity for Gamer Documents linking.

BC document numbers are not globally unique. Operator uploads and recovery
therefore must resolve one exact record in the configured BC write environment
before any SharePoint upload/link operation can be considered import-ready.
"""

import httpx

from services.gpi_integration_service import (
    BC_WRITE_ENVIRONMENT,
    BC_STANDARD_API,
    BC_TENANT_ID,
    GPI_API_BASE,
    HAS_CREDENTIALS,
    REQUEST_TIMEOUT,
    _get_company_id_standard_api,
    _get_token,
)


SUPPORTED_STANDARD_ENTITIES = {
    "purchaseOrders",
    "purchaseInvoices",
    # Kept for existing UI compatibility. Sales remains operationally paused;
    # resolving identity does not enable or perform a Sales write.
    "salesOrders",
    "salesInvoices",
}


def _odata_quote(value: str) -> str:
    return str(value).replace("'", "''")


async def resolve_bc_document_system_id(
    bc_entity: str,
    bc_document_no: str,
    *,
    environment: str | None = None,
) -> dict:
    """Resolve exactly one BC record and return its SystemId.

    Defaults to BC_WRITE_ENVIRONMENT because the resulting SystemId is used by
    the BC documentLinks write API. Fails closed on unsupported entities, no
    match, or multiple matches.
    """
    if bc_entity not in SUPPORTED_STANDARD_ENTITIES:
        raise ValueError(f"Unsupported BC document entity: {bc_entity!r}")
    if not str(bc_document_no or "").strip():
        raise ValueError("BC document number is required")
    if not HAS_CREDENTIALS:
        raise ValueError("BC credentials not configured")

    env = environment or BC_WRITE_ENVIRONMENT
    token = await _get_token()
    company_id = await _get_company_id_standard_api(environment=env)
    url = (
        f"{GPI_API_BASE}/{BC_TENANT_ID}/{env}/api/{BC_STANDARD_API}/"
        f"companies({company_id})/{bc_entity}"
    )
    params = {
        "$filter": f"number eq '{_odata_quote(bc_document_no)}'",
        "$select": "id,number",
        "$top": "2",
    }

    async with httpx.AsyncClient(timeout=REQUEST_TIMEOUT) as client:
        resp = await client.get(
            url,
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params=params,
        )
        resp.raise_for_status()
        matches = resp.json().get("value", [])

    if len(matches) == 0:
        raise LookupError(
            f"BC {bc_entity} record {bc_document_no!r} was not found in {env}"
        )
    if len(matches) != 1:
        raise LookupError(
            f"BC {bc_entity} record {bc_document_no!r} is ambiguous in {env}"
        )

    system_id = str(matches[0].get("id") or "").strip()
    if not system_id:
        raise LookupError(
            f"BC {bc_entity} record {bc_document_no!r} returned no SystemId in {env}"
        )

    return {
        "bc_entity": bc_entity,
        "bc_document_no": str(matches[0].get("number") or bc_document_no),
        "bc_system_id": system_id,
        "environment": env,
    }


__all__ = ["resolve_bc_document_system_id", "SUPPORTED_STANDARD_ENTITIES"]
