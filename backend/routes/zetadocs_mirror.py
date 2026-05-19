"""
GPI Document Hub - Zetadocs Delivery Mirror Router

Preview-only parity helpers for replacing Zetadocs outbound delivery.

Safety rules:
- Preview-only by default.
- Optional read-only Business Central lookup when live_bc=true.
- No email sends.
- No BC writes.
- No SharePoint writes.
- Produces a preview package that can be compared to real Zetadocs output.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import os

import httpx
from fastapi import APIRouter, HTTPException, Query


router = APIRouter(prefix="/zetadocs-mirror", tags=["zetadocs-mirror"])

TENANT_ID = os.environ.get("TENANT_ID", "").strip()
BC_ENVIRONMENT = os.environ.get("BC_ENVIRONMENT", "").strip()
BC_COMPANY_NAME = os.environ.get("BC_COMPANY_NAME", "Gamer Packaging").strip()
BC_CLIENT_ID = os.environ.get("BC_CLIENT_ID", "").strip()
BC_CLIENT_SECRET = os.environ.get("BC_CLIENT_SECRET", "").strip()
DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"
BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"
BC_TIMEOUT_SECONDS = float(os.environ.get("BC_READ_TIMEOUT_SECONDS", "30"))

ORDER_CONFIRMATION_TEMPLATE = {
    "document_set_no": "ZD00006",
    "document_set_name": "Order Confirmations",
    "template_id": "ZT00006",
    "template_file": "ZD-Order Confirmation Template.zdt",
    "report_id": 50020,
    "report_name": "Sales - Confirmation",
    "subject_template": "Gamer Packaging Order Confirmation #: %%[ZetadocsRecordNo] for %%[Organization]",
    "body_template": (
        "Hello,\n\n"
        "Attached is a copy of your order confirmation related to your PO # %%[ExternalDocNo], "
        "the Gamer Order Confirmation # %%[ZetadocsRecordNo].\n\n"
        "Please review your order confirmation and let me know if you have any questions.\n\n"
        "Please note that Gamer Packaging’s Standard Terms and Conditions have recently been updated. "
        "Please ensure that you review these terms regularly, as revisions will be applicable at the time of posting on our website.\n\n"
        "http://gamerpackaging.com/terms-conditions/\n\n"
        "Thank you for your order!"
    ),
}


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _first_non_empty(*values: Any) -> str:
    for value in values:
        if value is None:
            continue
        value_str = str(value).strip()
        if value_str:
            return value_str
    return ""


def _replace_zetadocs_tokens(template: str, values: Dict[str, str]) -> str:
    rendered = template or ""
    for key, value in values.items():
        rendered = rendered.replace(f"%%[{key}]", value or "")
        rendered = rendered.replace(f"%%[{key} ]", value or "")
    return rendered


async def _get_bc_token() -> str:
    if DEMO_MODE or not BC_CLIENT_ID or not BC_CLIENT_SECRET:
        raise HTTPException(
            status_code=503,
            detail="BC credentials are not configured for live preview. Use live_bc=false with overrides, or set DEMO_MODE=false and BC_CLIENT_ID/BC_CLIENT_SECRET.",
        )

    async with httpx.AsyncClient(timeout=BC_TIMEOUT_SECONDS) as client:
        response = await client.post(
            f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": BC_CLIENT_ID,
                "client_secret": BC_CLIENT_SECRET,
                "scope": "https://api.businesscentral.dynamics.com/.default",
            },
        )

    data = response.json() if response.content else {}
    token = data.get("access_token")
    if response.status_code >= 400 or not token:
        raise HTTPException(
            status_code=502,
            detail=f"BC token request failed with HTTP {response.status_code}: {str(data)[:500]}",
        )
    return token


async def _get_bc_company(token: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=BC_TIMEOUT_SECONDS) as client:
        response = await client.get(
            f"{BC_API_BASE}/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
        )

    data = response.json() if response.content else {}
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"BC companies lookup failed: HTTP {response.status_code}: {str(data)[:500]}")

    companies = data.get("value", [])
    company = next(
        (c for c in companies if c.get("name") == BC_COMPANY_NAME or c.get("displayName") == BC_COMPANY_NAME),
        companies[0] if companies else None,
    )
    if not company:
        raise HTTPException(status_code=404, detail="No Business Central companies returned")
    return company


async def _get_sales_order(token: str, company_id: str, order_no: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=BC_TIMEOUT_SECONDS) as client:
        response = await client.get(
            f"{BC_API_BASE}/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/salesOrders",
            headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            params={"$filter": f"number eq '{order_no}'", "$top": "5"},
        )

    data = response.json() if response.content else {}
    if response.status_code >= 400:
        raise HTTPException(status_code=502, detail=f"BC sales order lookup failed: HTTP {response.status_code}: {str(data)[:500]}")

    matches = data.get("value", [])
    if not matches:
        raise HTTPException(status_code=404, detail=f"Sales order {order_no} was not found in BC {BC_ENVIRONMENT}/{BC_COMPANY_NAME}")
    return matches[0]


async def _get_customer(token: str, company_id: str, sales_order: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    customer_id = sales_order.get("customerId") or sales_order.get("customerID")
    customer_number = sales_order.get("customerNumber")

    async with httpx.AsyncClient(timeout=BC_TIMEOUT_SECONDS) as client:
        if customer_id:
            response = await client.get(
                f"{BC_API_BASE}/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/customers({customer_id})",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
            )
        elif customer_number:
            response = await client.get(
                f"{BC_API_BASE}/{TENANT_ID}/{BC_ENVIRONMENT}/api/v2.0/companies({company_id})/customers",
                headers={"Authorization": f"Bearer {token}", "Accept": "application/json"},
                params={"$filter": f"number eq '{customer_number}'", "$top": "1"},
            )
        else:
            return None

    if response.status_code >= 400:
        return None

    data = response.json() if response.content else {}
    if "value" in data:
        return data.get("value", [None])[0]
    return data


def _build_preview(
    order_no: str,
    sales_order: Dict[str, Any],
    customer: Optional[Dict[str, Any]],
    recipient_override: Optional[str],
    sender_override: Optional[str],
    organization_override: Optional[str],
    external_doc_no_override: Optional[str],
) -> Dict[str, Any]:
    organization = _first_non_empty(
        organization_override,
        sales_order.get("customerName"),
        sales_order.get("sellToCustomerName"),
        sales_order.get("billToName"),
        customer.get("displayName") if customer else None,
    )
    external_doc_no = _first_non_empty(
        external_doc_no_override,
        sales_order.get("externalDocumentNumber"),
        sales_order.get("externalDocumentNo"),
        sales_order.get("yourReference"),
        sales_order.get("customerPurchaseOrderReference"),
    )
    recipient = _first_non_empty(
        recipient_override,
        sales_order.get("email"),
        sales_order.get("contactEmail"),
        customer.get("email") if customer else None,
    )
    sender = _first_non_empty(sender_override, sales_order.get("salespersonEmail"), "")

    token_values = {
        "ZetadocsRecordNo": order_no,
        "ExternalDocNo": external_doc_no,
        "Organization": organization,
    }

    subject = _replace_zetadocs_tokens(ORDER_CONFIRMATION_TEMPLATE["subject_template"], token_values)
    body = _replace_zetadocs_tokens(ORDER_CONFIRMATION_TEMPLATE["body_template"], token_values)
    attachment_name = f"Sales-Order {order_no}.pdf"

    warnings = []
    if not recipient:
        warnings.append("Recipient could not be resolved from standard BC API fields; pass recipient_override or expose/contact source fields.")
    if not sender:
        warnings.append("Sender could not be resolved from standard BC API fields; pass sender_override or use authenticated BC user/action context.")
    if not external_doc_no:
        warnings.append("External document/customer PO was not resolved; pass external_doc_no_override or expose the BC field used by report 50020.")

    return {
        "success": True,
        "mode": "preview_only_no_send_no_write",
        "generated_at": _now_iso(),
        "order_no": order_no,
        "zetadocs": ORDER_CONFIRMATION_TEMPLATE,
        "bc": {
            "environment": BC_ENVIRONMENT,
            "company": BC_COMPANY_NAME,
            "sales_order": sales_order,
            "customer": customer,
        },
        "resolved_values": {
            "zetadocs_record_no": order_no,
            "external_doc_no": external_doc_no,
            "organization": organization,
            "to": recipient,
            "from": sender,
            "attachment_name": attachment_name,
        },
        "rendered_email": {
            "from": sender,
            "to": recipient,
            "cc": "",
            "bcc": "",
            "subject": subject,
            "body_text": body,
            "attachment_name": attachment_name,
        },
        "known_production_parity_sample": {
            "order_no": "100729",
            "subject": "Gamer Packaging Order Confirmation #: 100729 for Revelton Distilling Company",
            "from": "Jfortman@gamerpackaging.com",
            "to": "rob@reveltondistillery.com",
            "external_doc_no": "060125",
            "organization": "Revelton Distilling Company",
            "attachment_name": "Sales-Order 100729.pdf",
        },
        "warnings": warnings,
        "next_step": "Compare this preview against the real Zetadocs email. When subject/body/recipient match, add PDF retrieval/rendering and then a send-disabled delivery package record.",
    }


@router.get("/order-confirmations/{order_no}/preview")
async def preview_order_confirmation(
    order_no: str,
    live_bc: bool = Query(False, description="When true, read the sales order from BC. Default false is offline parity preview."),
    recipient_override: Optional[str] = Query(None, description="Optional recipient override for parity testing"),
    sender_override: Optional[str] = Query(None, description="Optional sender override for parity testing"),
    organization_override: Optional[str] = Query(None, description="Optional organization/customer name override"),
    external_doc_no_override: Optional[str] = Query(None, description="Optional customer PO/external document number override"),
):
    """Preview a GPI Hub replacement package for Zetadocs Order Confirmation delivery."""
    sales_order: Dict[str, Any] = {}
    customer: Optional[Dict[str, Any]] = None
    company: Dict[str, Any] = {"name": BC_COMPANY_NAME, "displayName": BC_COMPANY_NAME, "source": "offline_preview"}

    if live_bc:
        token = await _get_bc_token()
        company = await _get_bc_company(token)
        company_id = company.get("id")
        if not company_id:
            raise HTTPException(status_code=502, detail="BC company response did not include id")
        sales_order = await _get_sales_order(token, company_id, order_no)
        customer = await _get_customer(token, company_id, sales_order)

    preview = _build_preview(
        order_no=order_no,
        sales_order=sales_order,
        customer=customer,
        recipient_override=recipient_override,
        sender_override=sender_override,
        organization_override=organization_override,
        external_doc_no_override=external_doc_no_override,
    )
    preview["live_bc"] = live_bc
    preview["bc"]["company_record"] = company
    return preview
