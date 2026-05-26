"""
GPI Document Hub - Zetadocs Delivery Mirror Router

Preview-only parity helpers for replacing Zetadocs outbound delivery.

Safety rules:
- Preview-only by default.
- Optional read-only Business Central lookup when live_bc=true.
- No email sends.
- No BC writes.
- No SharePoint writes.
- Delivery package records are send-disabled audit records only.
- Produces a preview package that can be compared to real Zetadocs output.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
import os
import uuid

import httpx
from fastapi import APIRouter, HTTPException, Query


router = APIRouter(prefix="/zetadocs-mirror", tags=["zetadocs-mirror"])

db = None

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

INTERNAL_CUSTOMER_MARKERS = {
    "GAMER",
    "GAMER PACKAGING",
    "GAMER PACKAGING INC",
    "GAMER PACKAGING, INC",
    "GAMER PACKAGING, INC.",
}

TRANSFER_AFFECTED_DOCUMENT_TYPES = {
    "WRN",
    "WAREHOUSE_RECEIVING_NOTICE",
    "WAREHOUSE_RECEIVING_NOTICE_DOCUMENT",
    "PICK_TICKET",
    "PICK_TICKET_DOCUMENT",
    "PICK_INSTRUCTION",
    "TRANSFER_ORDER",
    "TRANSFER",
}


def set_db(database):
    """Inject MongoDB dependency from server startup."""
    global db
    db = database


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


def _normalize_for_rule(value: Any) -> str:
    if value is None:
        return ""
    normalized = str(value).strip().upper()
    normalized = normalized.replace(".", "")
    normalized = " ".join(normalized.split())
    return normalized


def _is_gamer_internal_customer(*values: Any) -> bool:
    for value in values:
        normalized = _normalize_for_rule(value)
        if not normalized:
            continue
        if normalized in INTERNAL_CUSTOMER_MARKERS:
            return True
        if normalized.startswith("GAMER PACKAGING"):
            return True
    return False


def _replace_zetadocs_tokens(template: str, values: Dict[str, str]) -> str:
    rendered = template or ""
    for key, value in values.items():
        rendered = rendered.replace(f"%%[{key}]", value or "")
        rendered = rendered.replace(f"%%[{key} ]", value or "")
    return rendered


def _ensure_db():
    if db is None:
        raise HTTPException(
            status_code=503,
            detail="Zetadocs mirror database dependency is not initialized. Confirm set_zetadocs_mirror_db(db) runs during startup.",
        )


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


def _build_routing_context(
    source_document_type: Optional[str],
    source_order_type: Optional[str],
    managed_by_department: Optional[str],
    customer_no: Optional[str],
    sell_to_customer_no: Optional[str],
    bill_to_customer_no: Optional[str],
    ship_to_customer_no: Optional[str],
    organization: str,
    sales_order: Dict[str, Any],
    customer: Optional[Dict[str, Any]],
    is_transfer_order_override: Optional[bool],
    internal_customer_override: Optional[bool],
    include_osr_override: Optional[bool],
    include_isr_override: Optional[bool],
    show_in_sales_tiles_override: Optional[bool],
) -> Dict[str, Any]:
    document_type = _normalize_for_rule(source_document_type or "ORDER_CONFIRMATION")
    order_type = _normalize_for_rule(
        source_order_type
        or sales_order.get("orderType")
        or sales_order.get("documentType")
        or "SALES_ORDER"
    )

    resolved_customer_no = _first_non_empty(
        customer_no,
        sales_order.get("customerNumber"),
        customer.get("number") if customer else None,
    )
    resolved_sell_to_customer_no = _first_non_empty(
        sell_to_customer_no,
        sales_order.get("sellToCustomerNumber"),
        sales_order.get("sellToCustomerNo"),
    )
    resolved_bill_to_customer_no = _first_non_empty(
        bill_to_customer_no,
        sales_order.get("billToCustomerNumber"),
        sales_order.get("billToCustomerNo"),
    )
    resolved_ship_to_customer_no = _first_non_empty(
        ship_to_customer_no,
        sales_order.get("shipToCustomerNumber"),
        sales_order.get("shipToCustomerNo"),
    )

    inferred_internal_customer = _is_gamer_internal_customer(
        resolved_customer_no,
        resolved_sell_to_customer_no,
        resolved_bill_to_customer_no,
        resolved_ship_to_customer_no,
        organization,
        sales_order.get("customerName"),
        sales_order.get("sellToCustomerName"),
        sales_order.get("billToName"),
        customer.get("displayName") if customer else None,
    )
    internal_customer = internal_customer_override if internal_customer_override is not None else inferred_internal_customer

    inferred_transfer_order = "TRANSFER" in order_type or document_type in {"TRANSFER", "TRANSFER_ORDER"}
    is_transfer_order = is_transfer_order_override if is_transfer_order_override is not None else inferred_transfer_order

    affected_transfer_document = document_type in TRANSFER_AFFECTED_DOCUMENT_TYPES
    logistics_accounting_owned = bool(is_transfer_order or (internal_customer and affected_transfer_document))

    process_owner_department = _first_non_empty(
        managed_by_department,
        "Logistics/Accounting" if logistics_accounting_owned else "Sales",
    )

    include_osr = include_osr_override if include_osr_override is not None else not logistics_accounting_owned
    include_isr = include_isr_override if include_isr_override is not None else not logistics_accounting_owned
    show_in_sales_tiles = show_in_sales_tiles_override if show_in_sales_tiles_override is not None else not logistics_accounting_owned

    routing_exclusions: List[str] = []
    rule_notes: List[str] = []

    if logistics_accounting_owned:
        routing_rule_applied = "transfer_or_internal_customer_logistics_accounting_exclusion"
        routing_exclusions.extend([
            "exclude_sales_team_auto_copy",
            "exclude_sales_tile_visibility",
        ])
        rule_notes.append(
            "Transfer/internal-customer documents owned by logistics/accounting should not automatically copy sales teams or appear in sales tiles."
        )
    else:
        routing_rule_applied = "standard_sales_document_distribution"
        rule_notes.append(
            "Standard sales document routing remains eligible for OSR/ISR copy and sales tile visibility unless overridden."
        )

    if include_osr:
        audience_roles = ["external_recipient", "osr_copy"]
    else:
        audience_roles = ["external_recipient"]
    if include_isr:
        audience_roles.append("isr_visibility")

    return {
        "source_document_type": document_type,
        "source_order_type": order_type,
        "customer_no": resolved_customer_no,
        "sell_to_customer_no": resolved_sell_to_customer_no,
        "bill_to_customer_no": resolved_bill_to_customer_no,
        "ship_to_customer_no": resolved_ship_to_customer_no,
        "is_internal_customer": internal_customer,
        "is_transfer_order": is_transfer_order,
        "managed_by_department": process_owner_department,
        "include_osr": include_osr,
        "include_isr": include_isr,
        "show_in_sales_tiles": show_in_sales_tiles,
        "routing_rule_applied": routing_rule_applied,
        "routing_exclusions": routing_exclusions,
        "audience_roles": audience_roles,
        "rule_notes": rule_notes,
        "override_flags": {
            "is_transfer_order_override_used": is_transfer_order_override is not None,
            "internal_customer_override_used": internal_customer_override is not None,
            "include_osr_override_used": include_osr_override is not None,
            "include_isr_override_used": include_isr_override is not None,
            "show_in_sales_tiles_override_used": show_in_sales_tiles_override is not None,
        },
        "mission_alignment": "Do not blindly route by customer alone. Document type, order type, process owner, internal/customer-facing status, and visibility rules must control delivery and tile behavior.",
    }


def _build_preview(
    order_no: str,
    sales_order: Dict[str, Any],
    customer: Optional[Dict[str, Any]],
    recipient_override: Optional[str],
    sender_override: Optional[str],
    organization_override: Optional[str],
    external_doc_no_override: Optional[str],
    source_document_type: Optional[str],
    source_order_type: Optional[str],
    managed_by_department: Optional[str],
    customer_no: Optional[str],
    sell_to_customer_no: Optional[str],
    bill_to_customer_no: Optional[str],
    ship_to_customer_no: Optional[str],
    is_transfer_order_override: Optional[bool],
    internal_customer_override: Optional[bool],
    include_osr_override: Optional[bool],
    include_isr_override: Optional[bool],
    show_in_sales_tiles_override: Optional[bool],
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

    routing_context = _build_routing_context(
        source_document_type=source_document_type,
        source_order_type=source_order_type,
        managed_by_department=managed_by_department,
        customer_no=customer_no,
        sell_to_customer_no=sell_to_customer_no,
        bill_to_customer_no=bill_to_customer_no,
        ship_to_customer_no=ship_to_customer_no,
        organization=organization,
        sales_order=sales_order,
        customer=customer,
        is_transfer_order_override=is_transfer_order_override,
        internal_customer_override=internal_customer_override,
        include_osr_override=include_osr_override,
        include_isr_override=include_isr_override,
        show_in_sales_tiles_override=show_in_sales_tiles_override,
    )

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
        "routing_context": routing_context,
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
        "next_step": "Compare routing/audience context before adding PDF content or send behavior.",
    }


async def _build_order_confirmation_preview_payload(
    order_no: str,
    live_bc: bool,
    recipient_override: Optional[str],
    sender_override: Optional[str],
    organization_override: Optional[str],
    external_doc_no_override: Optional[str],
    source_document_type: Optional[str],
    source_order_type: Optional[str],
    managed_by_department: Optional[str],
    customer_no: Optional[str],
    sell_to_customer_no: Optional[str],
    bill_to_customer_no: Optional[str],
    ship_to_customer_no: Optional[str],
    is_transfer_order_override: Optional[bool],
    internal_customer_override: Optional[bool],
    include_osr_override: Optional[bool],
    include_isr_override: Optional[bool],
    show_in_sales_tiles_override: Optional[bool],
) -> Dict[str, Any]:
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
        source_document_type=source_document_type,
        source_order_type=source_order_type,
        managed_by_department=managed_by_department,
        customer_no=customer_no,
        sell_to_customer_no=sell_to_customer_no,
        bill_to_customer_no=bill_to_customer_no,
        ship_to_customer_no=ship_to_customer_no,
        is_transfer_order_override=is_transfer_order_override,
        internal_customer_override=internal_customer_override,
        include_osr_override=include_osr_override,
        include_isr_override=include_isr_override,
        show_in_sales_tiles_override=show_in_sales_tiles_override,
    )
    preview["live_bc"] = live_bc
    preview["bc"]["company_record"] = company
    return preview


def _build_delivery_package_record(
    order_no: str,
    preview: Dict[str, Any],
    created_by: str,
    notes: Optional[str],
) -> Dict[str, Any]:
    package_id = f"zdm-{uuid.uuid4()}"
    now = _now_iso()
    resolved = preview.get("resolved_values", {})
    rendered_email = preview.get("rendered_email", {})
    routing_context = preview.get("routing_context", {})

    return {
        "package_id": package_id,
        "created_utc": now,
        "updated_utc": now,
        "created_by": created_by,
        "updated_by": created_by,
        "source_system": "gpi_hub_zetadocs_mirror",
        "workflow_type": "order_confirmation",
        "status": "preview_created",
        "delivery_enabled": False,
        "email_send_status": "disabled_preview_only",
        "bc_write_status": "not_applicable_no_bc_write",
        "order_no": order_no,
        "bc_environment": preview.get("bc", {}).get("environment"),
        "bc_company": preview.get("bc", {}).get("company"),
        "document_set_no": preview.get("zetadocs", {}).get("document_set_no"),
        "document_set_name": preview.get("zetadocs", {}).get("document_set_name"),
        "template_id": preview.get("zetadocs", {}).get("template_id"),
        "template_file": preview.get("zetadocs", {}).get("template_file"),
        "report_id": preview.get("zetadocs", {}).get("report_id"),
        "report_name": preview.get("zetadocs", {}).get("report_name"),
        "routing_context": routing_context,
        "email": {
            "from": rendered_email.get("from", ""),
            "to": rendered_email.get("to", ""),
            "cc": rendered_email.get("cc", ""),
            "bcc": rendered_email.get("bcc", ""),
            "subject": rendered_email.get("subject", ""),
            "body_text": rendered_email.get("body_text", ""),
        },
        "attachments": [
            {
                "name": rendered_email.get("attachment_name") or resolved.get("attachment_name"),
                "type": "bc_report_pdf",
                "report_id": preview.get("zetadocs", {}).get("report_id"),
                "report_name": preview.get("zetadocs", {}).get("report_name"),
                "content_status": "not_generated_yet",
                "generation_status": "pending_future_step",
            }
        ],
        "resolved_values": resolved,
        "warnings": preview.get("warnings", []),
        "notes": notes or "",
        "audit_events": [
            {
                "event": "delivery_package_preview_created",
                "event_utc": now,
                "actor": created_by,
                "details": "Send-disabled Zetadocs mirror delivery package created from preview payload. No email was sent and no BC write occurred.",
            },
            {
                "event": "routing_context_evaluated",
                "event_utc": now,
                "actor": "system",
                "details": f"Routing rule applied: {routing_context.get('routing_rule_applied', 'unknown')}",
            },
        ],
        "preview_payload": preview,
    }


def _public_package_response(package: Dict[str, Any]) -> Dict[str, Any]:
    public = dict(package)
    public.pop("_id", None)
    return public


def _routing_query_kwargs(
    source_document_type: Optional[str],
    source_order_type: Optional[str],
    managed_by_department: Optional[str],
    customer_no: Optional[str],
    sell_to_customer_no: Optional[str],
    bill_to_customer_no: Optional[str],
    ship_to_customer_no: Optional[str],
    is_transfer_order: Optional[bool],
    internal_customer: Optional[bool],
    include_osr: Optional[bool],
    include_isr: Optional[bool],
    show_in_sales_tiles: Optional[bool],
) -> Dict[str, Any]:
    return {
        "source_document_type": source_document_type,
        "source_order_type": source_order_type,
        "managed_by_department": managed_by_department,
        "customer_no": customer_no,
        "sell_to_customer_no": sell_to_customer_no,
        "bill_to_customer_no": bill_to_customer_no,
        "ship_to_customer_no": ship_to_customer_no,
        "is_transfer_order_override": is_transfer_order,
        "internal_customer_override": internal_customer,
        "include_osr_override": include_osr,
        "include_isr_override": include_isr,
        "show_in_sales_tiles_override": show_in_sales_tiles,
    }


@router.get("/order-confirmations/{order_no}/preview")
async def preview_order_confirmation(
    order_no: str,
    live_bc: bool = Query(False, description="When true, read the sales order from BC. Default false is offline parity preview."),
    recipient_override: Optional[str] = Query(None, description="Optional recipient override for parity testing"),
    sender_override: Optional[str] = Query(None, description="Optional sender override for parity testing"),
    organization_override: Optional[str] = Query(None, description="Optional organization/customer name override"),
    external_doc_no_override: Optional[str] = Query(None, description="Optional customer PO/external document number override"),
    source_document_type: Optional[str] = Query("ORDER_CONFIRMATION", description="Document type used for routing rules"),
    source_order_type: Optional[str] = Query("SALES_ORDER", description="Order/process type used for routing rules"),
    managed_by_department: Optional[str] = Query(None, description="Optional process-owner override"),
    customer_no: Optional[str] = Query(None, description="Optional customer number override used for routing"),
    sell_to_customer_no: Optional[str] = Query(None, description="Optional sell-to customer number override used for routing"),
    bill_to_customer_no: Optional[str] = Query(None, description="Optional bill-to customer number override used for routing"),
    ship_to_customer_no: Optional[str] = Query(None, description="Optional ship-to customer number override used for routing"),
    is_transfer_order: Optional[bool] = Query(None, description="Optional transfer-order override used for routing"),
    internal_customer: Optional[bool] = Query(None, description="Optional internal-customer override used for routing"),
    include_osr: Optional[bool] = Query(None, description="Optional OSR copy/visibility override"),
    include_isr: Optional[bool] = Query(None, description="Optional ISR copy/visibility override"),
    show_in_sales_tiles: Optional[bool] = Query(None, description="Optional sales tile visibility override"),
):
    """Preview a GPI Hub replacement package for Zetadocs Order Confirmation delivery."""
    return await _build_order_confirmation_preview_payload(
        order_no=order_no,
        live_bc=live_bc,
        recipient_override=recipient_override,
        sender_override=sender_override,
        organization_override=organization_override,
        external_doc_no_override=external_doc_no_override,
        **_routing_query_kwargs(
            source_document_type=source_document_type,
            source_order_type=source_order_type,
            managed_by_department=managed_by_department,
            customer_no=customer_no,
            sell_to_customer_no=sell_to_customer_no,
            bill_to_customer_no=bill_to_customer_no,
            ship_to_customer_no=ship_to_customer_no,
            is_transfer_order=is_transfer_order,
            internal_customer=internal_customer,
            include_osr=include_osr,
            include_isr=include_isr,
            show_in_sales_tiles=show_in_sales_tiles,
        ),
    )


@router.post("/order-confirmations/{order_no}/delivery-package-preview")
async def create_order_confirmation_delivery_package_preview(
    order_no: str,
    live_bc: bool = Query(False, description="When true, read the sales order from BC. Default false is offline parity preview."),
    recipient_override: Optional[str] = Query(None, description="Optional recipient override for parity testing"),
    sender_override: Optional[str] = Query(None, description="Optional sender override for parity testing"),
    organization_override: Optional[str] = Query(None, description="Optional organization/customer name override"),
    external_doc_no_override: Optional[str] = Query(None, description="Optional customer PO/external document number override"),
    source_document_type: Optional[str] = Query("ORDER_CONFIRMATION", description="Document type used for routing rules"),
    source_order_type: Optional[str] = Query("SALES_ORDER", description="Order/process type used for routing rules"),
    managed_by_department: Optional[str] = Query(None, description="Optional process-owner override"),
    customer_no: Optional[str] = Query(None, description="Optional customer number override used for routing"),
    sell_to_customer_no: Optional[str] = Query(None, description="Optional sell-to customer number override used for routing"),
    bill_to_customer_no: Optional[str] = Query(None, description="Optional bill-to customer number override used for routing"),
    ship_to_customer_no: Optional[str] = Query(None, description="Optional ship-to customer number override used for routing"),
    is_transfer_order: Optional[bool] = Query(None, description="Optional transfer-order override used for routing"),
    internal_customer: Optional[bool] = Query(None, description="Optional internal-customer override used for routing"),
    include_osr: Optional[bool] = Query(None, description="Optional OSR copy/visibility override"),
    include_isr: Optional[bool] = Query(None, description="Optional ISR copy/visibility override"),
    show_in_sales_tiles: Optional[bool] = Query(None, description="Optional sales tile visibility override"),
    created_by: str = Query("gpi-hub-preview", description="Audit actor for the preview package"),
    notes: Optional[str] = Query(None, description="Optional audit note"),
):
    """Create a send-disabled delivery package record from an order confirmation preview."""
    _ensure_db()
    preview = await _build_order_confirmation_preview_payload(
        order_no=order_no,
        live_bc=live_bc,
        recipient_override=recipient_override,
        sender_override=sender_override,
        organization_override=organization_override,
        external_doc_no_override=external_doc_no_override,
        **_routing_query_kwargs(
            source_document_type=source_document_type,
            source_order_type=source_order_type,
            managed_by_department=managed_by_department,
            customer_no=customer_no,
            sell_to_customer_no=sell_to_customer_no,
            bill_to_customer_no=bill_to_customer_no,
            ship_to_customer_no=ship_to_customer_no,
            is_transfer_order=is_transfer_order,
            internal_customer=internal_customer,
            include_osr=include_osr,
            include_isr=include_isr,
            show_in_sales_tiles=show_in_sales_tiles,
        ),
    )
    package = _build_delivery_package_record(
        order_no=order_no,
        preview=preview,
        created_by=created_by,
        notes=notes,
    )
    await db.zetadocs_delivery_packages.insert_one(package)
    return {
        "success": True,
        "message": "Send-disabled delivery package preview created. No email was sent and no BC write occurred.",
        "package_id": package["package_id"],
        "delivery_enabled": False,
        "email_send_status": package["email_send_status"],
        "bc_write_status": package["bc_write_status"],
        "routing_rule_applied": package.get("routing_context", {}).get("routing_rule_applied"),
        "show_in_sales_tiles": package.get("routing_context", {}).get("show_in_sales_tiles"),
        "package": _public_package_response(package),
    }


@router.get("/delivery-packages/{package_id}")
async def get_delivery_package(package_id: str):
    """Get a previously created send-disabled delivery package preview."""
    _ensure_db()
    package = await db.zetadocs_delivery_packages.find_one({"package_id": package_id}, {"_id": 0})
    if not package:
        raise HTTPException(status_code=404, detail=f"Delivery package {package_id} was not found")
    return {"success": True, "package": package}


@router.get("/order-confirmations/{order_no}/delivery-packages")
async def list_order_confirmation_delivery_packages(
    order_no: str,
    limit: int = Query(25, ge=1, le=100),
) -> Dict[str, Any]:
    """List send-disabled delivery package previews for an order confirmation."""
    _ensure_db()
    packages: List[Dict[str, Any]] = await db.zetadocs_delivery_packages.find(
        {"workflow_type": "order_confirmation", "order_no": order_no},
        {"_id": 0},
    ).sort("created_utc", -1).limit(limit).to_list(limit)
    return {"success": True, "order_no": order_no, "count": len(packages), "packages": packages}
