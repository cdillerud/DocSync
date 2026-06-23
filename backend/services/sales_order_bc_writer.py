"""Business Central writer for validated draft sales orders.

This module keeps sales-order creation separate from the AP-oriented
BusinessCentralService. It sends the official salesOrderLine fields, includes
unitOfMeasureCode, retries transient responses, and rolls back the header if a
line cannot be created.
"""

from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

from services.business_central_service import (
    BC_API_BASE,
    BC_ENVIRONMENT,
    BC_REQUEST_TIMEOUT,
    BC_TENANT_ID,
    get_bc_token,
)

TRANSIENT_STATUS_CODES = {429, 500, 502, 503, 504}
MAX_ATTEMPTS = 3


async def create_sales_order_draft(
    bc_service,
    order_data: Dict[str, Any],
) -> Dict[str, Any]:
    """Create a complete draft order or roll back the header on line failure."""

    lines = order_data.get("lines") or []
    if not lines:
        return {
            "success": False,
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
    company_id = await bc_service._get_company_id()
    base_url = (
        f"{BC_API_BASE}/{BC_TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/"
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
            return {
                "success": False,
                "error": (
                    f"BC rejected sales-order line {line_errors[0]['line']}; "
                    + (
                        "header was rolled back"
                        if rollback["success"]
                        else "header rollback failed and manual cleanup is required"
                    )
                ),
                "bcDocumentId": order_id,
                "bcDocumentNumber": order_number,
                "status": "RolledBack" if rollback["success"] else "Partial",
                "linesAdded": added,
                "linesTotal": len(lines),
                "lineErrors": line_errors,
                "rolledBack": rollback["success"],
                "rollbackError": rollback.get("error"),
                "manualCleanupRequired": not rollback["success"],
                "mock": False,
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
    if line.get("unitPrice") is not None:
        payload["unitPrice"] = line["unitPrice"]
    if line.get("shipmentDate"):
        payload["shipmentDate"] = line["shipmentDate"]

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
