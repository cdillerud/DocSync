"""Guarded Business Central gateway for GPI Order Intake write tests.

Restricted to PRE_GAMERDOCS_CUTOVER_20260831 + Gamer Packaging. This gateway can
read order/customer/item data and create/delete tagged Open test Sales Orders.
It intentionally exposes no release, shipment, invoice, or posting operations.
"""

from __future__ import annotations

import os
from typing import Any, Dict, List, Optional

import httpx

from services.business_central_service import (
    BC_API_BASE,
    BC_CLIENT_ID,
    BC_CLIENT_SECRET,
    BC_REQUEST_TIMEOUT,
    BC_TENANT_ID,
    get_bc_token,
)

APPROVED_ENVIRONMENT = "PRE_GAMERDOCS_CUTOVER_20260831"
APPROVED_COMPANY_NAME = "Gamer Packaging"
TEST_EXTERNAL_DOC_PREFIX = "AITEST-"
WRITE_FLAG_NAME = "GPI_ORDER_INTAKE_BC_WRITE_TESTS_ENABLED"


class OrderIntakeBCGuardError(RuntimeError):
    pass


class OrderIntakeBCTestGateway:
    def __init__(self):
        self.environment = (
            os.environ.get("BC_ENVIRONMENT")
            or os.environ.get("BC_SANDBOX_ENVIRONMENT")
            or ""
        )
        self.configured_company_id = os.environ.get("BC_COMPANY_ID", "").strip()
        self._company_id: Optional[str] = None
        self._company: Optional[Dict[str, Any]] = None

    @staticmethod
    def _odata_literal(value: str) -> str:
        return str(value).replace("'", "''")

    def assert_target_environment(self) -> None:
        if self.environment != APPROVED_ENVIRONMENT:
            raise OrderIntakeBCGuardError(
                f"Order Intake BC tests are restricted to {APPROVED_ENVIRONMENT}; "
                f"configured environment is {self.environment or '<blank>'}."
            )
        if not BC_CLIENT_ID or not BC_CLIENT_SECRET or not BC_TENANT_ID:
            raise OrderIntakeBCGuardError(
                "BC_CLIENT_ID, BC_CLIENT_SECRET, and BC_TENANT_ID/TENANT_ID are required."
            )

    def assert_write_enabled(self) -> None:
        self.assert_target_environment()
        if os.environ.get(WRITE_FLAG_NAME, "false").strip().lower() != "true":
            raise OrderIntakeBCGuardError(
                f"BC write testing is disabled. Set {WRITE_FLAG_NAME}=true explicitly."
            )

    async def _headers(self) -> Dict[str, str]:
        self.assert_target_environment()
        token = await get_bc_token()
        return {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}

    async def resolve_company(self) -> Dict[str, Any]:
        if self._company:
            return self._company
        headers = await self._headers()
        url = f"{BC_API_BASE}/{BC_TENANT_ID}/{self.environment}/api/v2.0/companies"
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(url, headers=headers)
        if resp.status_code != 200:
            raise OrderIntakeBCGuardError(
                f"Unable to read BC companies: HTTP {resp.status_code}: {resp.text[:300]}"
            )
        companies = resp.json().get("value", [])
        if self.configured_company_id:
            selected = next((c for c in companies if c.get("id") == self.configured_company_id), None)
            if not selected:
                raise OrderIntakeBCGuardError("Configured BC_COMPANY_ID was not found in the approved environment.")
        else:
            exact = [
                c for c in companies
                if (c.get("name") or c.get("displayName") or "").strip().lower()
                == APPROVED_COMPANY_NAME.lower()
            ]
            if len(exact) != 1:
                raise OrderIntakeBCGuardError(
                    f"Expected exactly one '{APPROVED_COMPANY_NAME}' company; found {len(exact)}."
                )
            selected = exact[0]
        company_name = (selected.get("name") or selected.get("displayName") or "").strip()
        if company_name.lower() != APPROVED_COMPANY_NAME.lower():
            raise OrderIntakeBCGuardError(
                f"Resolved company '{company_name}' is not approved for Order Intake tests."
            )
        self._company = selected
        self._company_id = selected["id"]
        return selected

    async def _base_url(self) -> str:
        await self.resolve_company()
        return (
            f"{BC_API_BASE}/{BC_TENANT_ID}/{self.environment}/api/v2.0/"
            f"companies({self._company_id})"
        )

    async def preflight(self) -> Dict[str, Any]:
        company = await self.resolve_company()
        return {
            "environment": self.environment,
            "company": company.get("name") or company.get("displayName"),
            "companyId": company.get("id"),
            "writeTestsEnabled": os.environ.get(WRITE_FLAG_NAME, "false").strip().lower() == "true",
            "allowedWriteOperations": [
                "create tagged Open Sales Order",
                "create tagged Sales Order lines",
                "delete tagged Open test Sales Order",
            ],
            "blockedOperations": ["release", "ship", "invoice", "post"],
        }

    async def find_customers(self, search_text: str, top: int = 25) -> List[Dict[str, Any]]:
        """Read-only customer discovery for initial customer-profile setup."""
        headers = await self._headers()
        base = await self._base_url()
        needle = self._odata_literal(search_text)
        params = {
            "$select": "id,number,displayName,email,phoneNumber,blocked",
            "$filter": f"contains(displayName, '{needle}')",
            "$top": str(top),
        }
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(f"{base}/customers", headers=headers, params=params)
        if resp.status_code != 200:
            raise OrderIntakeBCGuardError(
                f"Customer lookup failed: HTTP {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json().get("value", [])

    async def resolve_item(self, item_number: str) -> Dict[str, Any]:
        """Resolve one exact BC Item No. to its GUID before creating a line."""
        headers = await self._headers()
        base = await self._base_url()
        number = self._odata_literal(item_number)
        params = {
            "$select": "id,number,displayName,type,blocked,baseUnitOfMeasureCode",
            "$filter": f"number eq '{number}'",
            "$top": "2",
        }
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(f"{base}/items", headers=headers, params=params)
        if resp.status_code != 200:
            raise OrderIntakeBCGuardError(
                f"Item lookup failed: HTTP {resp.status_code}: {resp.text[:300]}"
            )
        matches = resp.json().get("value", [])
        if len(matches) != 1:
            raise OrderIntakeBCGuardError(
                f"Expected exactly one BC item for number '{item_number}'; found {len(matches)}."
            )
        item = matches[0]
        if item.get("blocked") is True:
            raise OrderIntakeBCGuardError(f"BC item '{item_number}' is blocked.")
        return item

    async def find_sales_orders(
        self,
        *,
        customer_number: str,
        external_document_number: str,
        top: int = 20,
    ) -> List[Dict[str, Any]]:
        headers = await self._headers()
        base = await self._base_url()
        customer = self._odata_literal(customer_number)
        external = self._odata_literal(external_document_number)
        params = {
            "$select": "id,number,customerNumber,customerName,externalDocumentNumber,status,orderDate,requestedDeliveryDate",
            "$filter": f"customerNumber eq '{customer}' and externalDocumentNumber eq '{external}'",
            "$top": str(top),
        }
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(f"{base}/salesOrders", headers=headers, params=params)
        if resp.status_code != 200:
            raise OrderIntakeBCGuardError(
                f"Sales Order duplicate lookup failed: HTTP {resp.status_code}: {resp.text[:300]}"
            )
        return resp.json().get("value", [])

    async def get_sales_order(self, order_id: str, *, include_lines: bool = True) -> Dict[str, Any]:
        headers = await self._headers()
        base = await self._base_url()
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.get(f"{base}/salesOrders({order_id})", headers=headers)
            if resp.status_code != 200:
                raise OrderIntakeBCGuardError(
                    f"Sales Order read failed: HTTP {resp.status_code}: {resp.text[:300]}"
                )
            order = resp.json()
            if include_lines:
                line_resp = await client.get(
                    f"{base}/salesOrders({order_id})/salesOrderLines", headers=headers
                )
                if line_resp.status_code != 200:
                    raise OrderIntakeBCGuardError(
                        f"Sales Order line read failed: HTTP {line_resp.status_code}: {line_resp.text[:300]}"
                    )
                order["lines"] = line_resp.json().get("value", [])
        return order

    @staticmethod
    def _validate_test_external_document(external_document_number: str) -> None:
        if not external_document_number.startswith(TEST_EXTERNAL_DOC_PREFIX):
            raise OrderIntakeBCGuardError(
                f"Write-test externalDocumentNumber must start with '{TEST_EXTERNAL_DOC_PREFIX}'."
            )

    async def create_test_sales_order(self, order_data: Dict[str, Any]) -> Dict[str, Any]:
        """Create a tagged Open test order and read it back.

        Unit price is intentionally not supplied. Live PRE_GAMERDOCS testing proved
        that the standard v2.0 line-create API can leave unitPrice at zero, so this
        method is transport plumbing only and must not be treated as pricing proof.
        Each item number is resolved to the exact BC item GUID first.
        """
        self.assert_write_enabled()
        external = str(order_data.get("externalDocumentNumber") or "")
        self._validate_test_external_document(external)
        customer_number = str(order_data.get("customerNumber") or "").strip()
        if not customer_number:
            raise OrderIntakeBCGuardError("customerNumber is required for write testing.")

        lines = order_data.get("lines") or []
        resolved_lines: List[Dict[str, Any]] = []
        for index, line in enumerate(lines, start=1):
            item_number = str(line.get("itemNumber") or "").strip()
            if not item_number:
                raise OrderIntakeBCGuardError(f"Test line {index} is missing itemNumber.")
            quantity = float(line.get("quantity") or 0)
            if quantity <= 0:
                raise OrderIntakeBCGuardError(f"Test line {index} quantity must be > 0.")
            item = await self.resolve_item(item_number)
            resolved_lines.append({"source": line, "item": item, "quantity": quantity})

        headers = await self._headers()
        base = await self._base_url()
        payload: Dict[str, Any] = {
            "customerNumber": customer_number,
            "externalDocumentNumber": external,
        }
        for field_name in ("orderDate", "requestedDeliveryDate"):
            if order_data.get(field_name):
                payload[field_name] = order_data[field_name]

        created_order: Optional[Dict[str, Any]] = None
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.post(f"{base}/salesOrders", headers=headers, json=payload)
            if resp.status_code not in (200, 201):
                raise OrderIntakeBCGuardError(
                    f"Test Sales Order create failed: HTTP {resp.status_code}: {resp.text[:500]}"
                )
            created_order = resp.json()
            order_id = created_order["id"]
            try:
                for index, resolved in enumerate(resolved_lines, start=1):
                    source = resolved["source"]
                    item = resolved["item"]
                    line_payload: Dict[str, Any] = {
                        "lineType": "Item",
                        "itemId": item["id"],
                        "lineObjectNumber": item["number"],
                        "quantity": resolved["quantity"],
                    }
                    if source.get("unitOfMeasureCode"):
                        line_payload["unitOfMeasureCode"] = source["unitOfMeasureCode"]
                    if source.get("description"):
                        line_payload["description"] = str(source["description"])[:100]
                    line_resp = await client.post(
                        f"{base}/salesOrders({order_id})/salesOrderLines",
                        headers=headers,
                        json=line_payload,
                    )
                    if line_resp.status_code not in (200, 201):
                        raise OrderIntakeBCGuardError(
                            f"Test Sales Order line {index} create failed: "
                            f"HTTP {line_resp.status_code}: {line_resp.text[:500]}"
                        )
            except Exception:
                try:
                    await self.delete_test_sales_order(order_id)
                finally:
                    raise

        return await self.get_sales_order(created_order["id"], include_lines=True)

    async def delete_test_sales_order(self, order_id: str) -> Dict[str, Any]:
        self.assert_write_enabled()
        order = await self.get_sales_order(order_id, include_lines=False)
        external = str(order.get("externalDocumentNumber") or "")
        self._validate_test_external_document(external)
        status = str(order.get("status") or "").strip().lower()
        if status not in {"open", "draft"}:
            raise OrderIntakeBCGuardError(
                f"Refusing to delete test Sales Order in status '{order.get('status')}'."
            )
        headers = await self._headers()
        headers["If-Match"] = "*"
        base = await self._base_url()
        async with httpx.AsyncClient(timeout=BC_REQUEST_TIMEOUT) as client:
            resp = await client.delete(f"{base}/salesOrders({order_id})", headers=headers)
        if resp.status_code not in (200, 202, 204):
            raise OrderIntakeBCGuardError(
                f"Test Sales Order delete failed: HTTP {resp.status_code}: {resp.text[:500]}"
            )
        return {
            "deleted": True,
            "id": order_id,
            "number": order.get("number"),
            "externalDocumentNumber": external,
        }
