"""Business Central writer for validated draft sales orders.

The standard API path creates a header and lines, retries transient failures,
and rolls the header back if any line fails. A custom AL import endpoint can be
configured for atomic creation and native Ship-to Code handling.
"""

from __future__ import annotations

import asyncio
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from services.business_central_service import (
    BC_API_BASE,
    BC_REQUEST_TIMEOUT,
    BC_TENANT_ID,
    get_bc_token,
)

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = int(os.environ.get("SALES_ORDER_BC_MAX_ATTEMPTS", "3"))

# Customer PO prices are comparison data by default. BC should calculate the
# actual sales price unless an authorized workflow explicitly enables override.
ALLOW_PO_PRICE_OVERRIDE = os.environ.get(
    "SALES_ORDER_ALLOW_PO_PRICE_OVERRIDE", "false"
).lower() in ("true", "1", "yes")

# Optional custom AL API. This endpoint can accept the full order atomically and
# apply Gamer-specific fields such as Ship-to Code.
CUSTOM_IMPORT_URL = os.environ.get("BC_SALES_ORDER_IMPORT_API_URL", "").strip()

WRITE_ENVIRONMENT_VARIABLE = "SALES_ORDER_BC_WRITE_ENVIRONMENT"
WRITE_COMPANY_ID_VARIABLE = "SALES_ORDER_BC_WRITE_COMPANY_ID"
WRITE_COMPANY_NAME_VARIABLE = "SALES_ORDER_BC_WRITE_COMPANY_NAME"
DEFAULT_WRITE_COMPANY_NAME = "Gamer Packaging"


def _configured_write_environment() -> str:
    environment = os.environ.get(
        WRITE_ENVIRONMENT_VARIABLE,
        "",
    ).strip()

    if not environment:
        raise ValueError(
            f"{WRITE_ENVIRONMENT_VARIABLE} must be explicitly configured "
            "before sales-order writes are enabled."
        )

    return environment


def _select_write_company_id(
    companies: List[Dict[str, Any]],
    company_name: str,
) -> str:
    expected = company_name.strip().casefold()

    matches = [
        company
        for company in companies
        if expected
        in {
            str(company.get("name") or "").strip().casefold(),
            str(company.get("displayName") or "").strip().casefold(),
        }
    ]

    if len(matches) != 1:
        raise ValueError(
            "Could not uniquely resolve the sales-order write company "
            f"'{company_name}'. Matches found: {len(matches)}."
        )

    company_id = str(matches[0].get("id") or "").strip()

    if not company_id:
        raise ValueError(
            "The resolved sales-order write company has no company ID."
        )

    return company_id


async def _resolve_write_target(token: str) -> tuple[str, str]:
    environment = _configured_write_environment()

    configured_company_id = os.environ.get(
        WRITE_COMPANY_ID_VARIABLE,
        "",
    ).strip()

    if configured_company_id:
        return environment, configured_company_id

    company_name = os.environ.get(
        WRITE_COMPANY_NAME_VARIABLE,
        DEFAULT_WRITE_COMPANY_NAME,
    ).strip()

    if not company_name:
        raise ValueError(
            f"{WRITE_COMPANY_NAME_VARIABLE} cannot be blank when "
            f"{WRITE_COMPANY_ID_VARIABLE} is not configured."
        )

    url = (
        f"{BC_API_BASE}/{BC_TENANT_ID}/{environment}"
        "/api/v2.0/companies"
    )

    async with httpx.AsyncClient(
        timeout=BC_REQUEST_TIMEOUT
    ) as client:
        response = await _request_with_retry(
            client,
            "GET",
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Accept": "application/json",
            },
            params={
                "$select": "id,name,displayName",
                "$top": "100",
            },
        )

    if response.status_code != 200:
        raise ValueError(
            "Could not validate the sales-order write environment "
            f"'{environment}': HTTP {response.status_code}: "
            f"{response.text[:500]}"
        )

    companies = response.json().get("value", [])

    return (
        environment,
        _select_write_company_id(
            companies,
            company_name,
        ),
    )


async def create_sales_order_draft(
    bc_service,
    order_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a complete draft order or return a structured failure."""

    lines = order_data.get("lines") or []
    if not lines:
        return {
            "success": False,
            "errorCode": "ORDER_LINES_REQUIRED",
            "error": "Sales order requires at least one line",
            "linesAdded": 0,
            "linesTotal": 0,
            "lineErrors": [],
        }

    if getattr(bc_service, "use_mock", False):
        mock_id = f"SO-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}"
        return {
            "success": True,
            "bcDocumentId": mock_id,
            "bcDocumentNumber": mock_id,
            "status": "Draft",
            "mock": True,
            "linesAdded": len(lines),
            "linesTotal": len(lines),
            "lineErrors": [],
            "rolledBack": False,
        }

    token = await get_bc_token()

    try:
        write_environment, company_id = await _resolve_write_target(
            token
        )
    except ValueError as exc:
        return {
            "success": False,
            "errorCode": "BC_WRITE_TARGET_INVALID",
            "error": str(exc),
            "linesAdded": 0,
            "linesTotal": len(lines),
            "lineErrors": [],
        }

    if CUSTOM_IMPORT_URL:
        return await _create_with_custom_import_api(
            token=token,
            environment=write_environment,
            company_id=company_id,
            order_data=order_data,
        )

    # Ship-to Code is not part of the standard salesOrders v2.0 header contract.
    # Refuse to silently discard it. Configure the custom AL API or resolve the
    # code to explicit address fields before calling this writer.
    if order_data.get("shipToCode"):
        return {
            "success": False,
            "errorCode": "SHIP_TO_CODE_REQUIRES_CUSTOM_API",
            "error": (
                "A BC Ship-to Code was supplied, but the standard salesOrders "
                "API cannot apply it. Configure BC_SALES_ORDER_IMPORT_API_URL "
                "or resolve the code to explicit ship-to address fields."
            ),
            "linesAdded": 0,
            "linesTotal": len(lines),
            "lineErrors": [],
        }

    base_url = (
        f"{BC_API_BASE}/{BC_TENANT_ID}/{write_environment}/api/v2.0/"
        f"companies({company_id})"
    )
    headers = {
        "Authorization": f"Bearer {token}",
        "Content-Type": "application/json",
    }

    header_payload = _build_header_payload(order_data)
    async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
        response = await _request_with_retry(
            client,
            "POST",
            f"{base_url}/salesOrders",
            headers=headers,
            json=header_payload,
        )
        if response.status_code not in (200, 201):
            return {
                "success": False,
                "errorCode": "BC_HEADER_CREATE_FAILED",
                "error": f"BC sales-order header failed: HTTP {response.status_code}",
                "details": response.text[:1000],
                "linesAdded": 0,
                "linesTotal": len(lines),
                "lineErrors": [],
            }

        order = response.json()
        order_id = order.get("id")
        order_number = order.get("number")
        order_etag = order.get("@odata.etag") or "*"
        line_errors: List[Dict[str, Any]] = []
        added = 0

        for index, line in enumerate(lines, start=1):
            line_payload = _build_line_payload(line)
            line_response = await _request_with_retry(
                client,
                "POST",
                f"{base_url}/salesOrders({order_id})/salesOrderLines",
                headers=headers,
                json=line_payload,
            )
            if line_response.status_code not in (200, 201):
                line_errors.append(
                    {
                        "line": index,
                        "itemNumber": line.get("itemNumber"),
                        "statusCode": line_response.status_code,
                        "error": line_response.text[:1000],
                    }
                )
                break
            added += 1

        if line_errors:
            rollback = await _rollback_sales_order(
                client=client,
                url=f"{base_url}/salesOrders({order_id})",
                token=token,
                etag=order_etag,
            )
            rolled_back = rollback["success"]
            return {
                "success": False,
                "errorCode": "BC_LINE_CREATE_FAILED",
                "error": (
                    f"BC rejected sales-order line {line_errors[0]['line']}; "
                    + (
                        "header was rolled back"
                        if rolled_back
                        else "header rollback failed and manual cleanup is required"
                    )
                ),
                "bcDocumentId": None if rolled_back else order_id,
                "bcDocumentNumber": None if rolled_back else order_number,
                "status": "RolledBack" if rolled_back else "Partial",
                "linesAdded": added,
                "linesTotal": len(lines),
                "lineErrors": line_errors,
                "rolledBack": rolled_back,
                "rollbackError": rollback.get("error"),
                "manualCleanupRequired": not rolled_back,
                "mock": False,
            }

        if added != len(lines):
            rollback = await _rollback_sales_order(
                client=client,
                url=f"{base_url}/salesOrders({order_id})",
                token=token,
                etag=order_etag,
            )
            rolled_back = rollback["success"]
            return {
                "success": False,
                "errorCode": "BC_LINE_COUNT_MISMATCH",
                "error": (
                    f"Expected {len(lines)} lines but created {added}; "
                    + (
                        "header was rolled back"
                        if rolled_back
                        else "manual cleanup is required"
                    )
                ),
                "bcDocumentId": None if rolled_back else order_id,
                "bcDocumentNumber": None if rolled_back else order_number,
                "linesAdded": added,
                "linesTotal": len(lines),
                "lineErrors": [],
                "rolledBack": rolled_back,
                "manualCleanupRequired": not rolled_back,
            }

        return {
            "success": True,
            "bcDocumentId": order_id,
            "bcDocumentNumber": order_number,
            "status": order.get("status", "Draft"),
            "message": "Sales order created successfully",
            "mock": False,
            "createdAt": datetime.now(timezone.utc).isoformat(),
            "bcResponse": order,
            "linesAdded": added,
            "linesTotal": len(lines),
            "lineErrors": [],
            "rolledBack": False,
            "manualCleanupRequired": False,
            "poPriceOverrideApplied": ALLOW_PO_PRICE_OVERRIDE,
        }


async def _create_with_custom_import_api(
    *,
    token: str,
    environment: str,
    company_id: str,
    order_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Submit the full candidate to a custom AL import API atomically."""

    url = CUSTOM_IMPORT_URL.format(
        company_id=company_id,
        environment=environment,
    )
    payload = dict(order_data)
    payload["allowPoPriceOverride"] = ALLOW_PO_PRICE_OVERRIDE

    async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
        response = await _request_with_retry(
            client,
            "POST",
            url,
            headers={
                "Authorization": f"Bearer {token}",
                "Content-Type": "application/json",
            },
            json=payload,
        )

    if response.status_code not in (200, 201):
        return {
            "success": False,
            "errorCode": "BC_CUSTOM_IMPORT_FAILED",
            "error": f"Custom BC import API failed: HTTP {response.status_code}",
            "details": response.text[:1000],
            "linesAdded": 0,
            "linesTotal": len(order_data.get("lines") or []),
            "lineErrors": [],
        }

    data = response.json()
    return {
        "success": True,
        "bcDocumentId": data.get("salesOrderId") or data.get("id"),
        "bcDocumentNumber": data.get("salesOrderNumber") or data.get("number"),
        "status": data.get("status", "Draft"),
        "message": "Sales order created through custom BC import API",
        "mock": False,
        "createdAt": datetime.now(timezone.utc).isoformat(),
        "bcResponse": data,
        "linesAdded": data.get("linesCreated", len(order_data.get("lines") or [])),
        "linesTotal": len(order_data.get("lines") or []),
        "lineErrors": [],
        "rolledBack": False,
        "manualCleanupRequired": False,
        "poPriceOverrideApplied": ALLOW_PO_PRICE_OVERRIDE,
    }


def _build_header_payload(order_data: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "customerNumber": order_data.get("customerNumber"),
        "externalDocumentNumber": order_data.get("externalDocumentNumber"),
        "currencyCode": order_data.get("currencyCode") or "USD",
    }

    optional_fields = {
        "orderDate": order_data.get("orderDate"),
        "requestedDeliveryDate": order_data.get("requestedDeliveryDate"),
        "shipToName": order_data.get("shipToName"),
        "shipToAddressLine1": order_data.get("shipToAddressLine1"),
        "shipToAddressLine2": order_data.get("shipToAddressLine2"),
        "shipToCity": order_data.get("shipToCity"),
        "shipToState": order_data.get("shipToState"),
        "shipToCountry": order_data.get("shipToCountry"),
        "shipToPostCode": order_data.get("shipToPostCode"),
    }
    payload.update({key: value for key, value in optional_fields.items() if value})

    return {key: value for key, value in payload.items() if value is not None}


def _build_line_payload(line: Dict[str, Any]) -> Dict[str, Any]:
    payload: Dict[str, Any] = {
        "lineType": "Item",
        "lineObjectNumber": line["itemNumber"],
        "quantity": line["quantity"],
        "unitOfMeasureCode": line["unitOfMeasureCode"],
    }

    if line.get("description"):
        payload["description"] = str(line["description"])[:100]
    if ALLOW_PO_PRICE_OVERRIDE and line.get("unitPrice") is not None:
        payload["unitPrice"] = line["unitPrice"]
    if line.get("shipmentDate"):
        payload["shipmentDate"] = line["shipmentDate"]
    if line.get("locationId"):
        payload["locationId"] = line["locationId"]

    return payload


async def _rollback_sales_order(
    *,
    client: httpx.AsyncClient,
    url: str,
    token: str,
    etag: str,
) -> Dict[str, Any]:
    response = await _request_with_retry(
        client,
        "DELETE",
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "If-Match": etag or "*",
        },
    )
    if response.status_code == 204:
        return {"success": True}
    return {
        "success": False,
        "error": f"HTTP {response.status_code}: {response.text[:500]}",
    }


async def _request_with_retry(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    **kwargs,
) -> httpx.Response:
    last_response: Optional[httpx.Response] = None
    for attempt in range(1, MAX_ATTEMPTS + 1):
        try:
            response = await client.request(method, url, **kwargs)
        except (httpx.TimeoutException, httpx.TransportError):
            if attempt == MAX_ATTEMPTS:
                raise
            await asyncio.sleep(2 ** (attempt - 1))
            continue

        last_response = response
        if response.status_code not in TRANSIENT_STATUS_CODES:
            return response
        if attempt == MAX_ATTEMPTS:
            return response

        retry_after = response.headers.get("Retry-After")
        try:
            delay = float(retry_after) if retry_after else 2 ** (attempt - 1)
        except ValueError:
            delay = 2 ** (attempt - 1)
        await asyncio.sleep(min(delay, 30))

    assert last_response is not None
    return last_response
