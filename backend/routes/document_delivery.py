"""
GPI Document Hub - Document Delivery Preflight API

Sprint 1 provides a production-shaped, preview-only contract for Business
Central Sales Order Confirmation delivery.

Safety rules:
- No email sends.
- No Business Central writes.
- No SharePoint writes.
- Deterministic routing only.
- Idempotent package creation by correlation_id + request hash.
"""

from datetime import datetime, timezone
from typing import Any, Dict, List, Literal, Optional
import hashlib
import json
import re

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError

from routes.bc_document_events import require_bc_document_events_api_key
from routes.zetadocs_mirror import (
    ORDER_CONFIRMATION_TEMPLATE,
    _build_routing_context,
    _replace_zetadocs_tokens,
)


router = APIRouter(prefix="/document-delivery/v1", tags=["document-delivery-v1"])

_db = None


def set_db(database):
    global _db
    _db = database


class DeliveryDocument(BaseModel):
    document_type: str = "SALES_ORDER_CONFIRMATION"
    record_type: str = "Sales Order"
    record_no: str = Field(min_length=1, max_length=50)
    system_id: Optional[str] = None
    report_id: int = ORDER_CONFIRMATION_TEMPLATE["report_id"]
    requested_action: Literal["PREVIEW"] = "PREVIEW"
    template_code: str = "SALES_ORDER_CONFIRMATION_DEFAULT"
    file_name: Optional[str] = None


class DeliveryCustomer(BaseModel):
    customer_no: Optional[str] = None
    sell_to_customer_no: Optional[str] = None
    bill_to_customer_no: Optional[str] = None
    ship_to_customer_no: Optional[str] = None
    organization: Optional[str] = None
    document_email: Optional[str] = None
    default_email: Optional[str] = None


class DeliveryOrder(BaseModel):
    order_type: str = "SALES_ORDER"
    external_document_no: Optional[str] = None
    location_code: Optional[str] = None
    is_transfer_order: Optional[bool] = None
    internal_customer: Optional[bool] = None


class DeliveryActors(BaseModel):
    initiated_by: Optional[str] = None
    sender_email: Optional[str] = None
    isr_code: Optional[str] = None
    isr_email: Optional[str] = None
    osr_code: Optional[str] = None
    osr_email: Optional[str] = None


class DeliveryOverrides(BaseModel):
    sender: Optional[str] = None
    to: List[str] = Field(default_factory=list)
    cc: List[str] = Field(default_factory=list)
    bcc: List[str] = Field(default_factory=list)
    managed_by_department: Optional[str] = None
    include_isr: Optional[bool] = None
    include_osr: Optional[bool] = None
    show_in_sales_tiles: Optional[bool] = None


class DeliveryPreflightRequest(BaseModel):
    correlation_id: str = Field(min_length=1, max_length=200)
    document: DeliveryDocument
    customer: DeliveryCustomer = Field(default_factory=DeliveryCustomer)
    order: DeliveryOrder = Field(default_factory=DeliveryOrder)
    actors: DeliveryActors = Field(default_factory=DeliveryActors)
    overrides: DeliveryOverrides = Field(default_factory=DeliveryOverrides)
    metadata: Dict[str, Any] = Field(default_factory=dict)


def _require_db():
    if _db is None:
        raise HTTPException(
            status_code=500,
            detail="Document delivery router is not initialized with a database",
        )
    return _db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _normalize(value: Optional[str]) -> str:
    return (value or "").strip()


def _normalize_document_type(value: Optional[str]) -> str:
    return re.sub(r"[^A-Z0-9]+", "_", (value or "").upper()).strip("_")


def _dedupe_emails(values: List[str], excluded: Optional[List[str]] = None) -> List[str]:
    excluded_set = {
        email.strip().lower()
        for email in (excluded or [])
        if email and email.strip()
    }
    seen = set()
    result: List[str] = []

    for value in values:
        email = (value or "").strip()
        key = email.lower()
        if not email or key in seen or key in excluded_set:
            continue
        seen.add(key)
        result.append(email)

    return result


def _request_hash(request: DeliveryPreflightRequest) -> str:
    payload = request.model_dump(mode="json", exclude_none=False)
    canonical = json.dumps(
        payload,
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    )
    return hashlib.sha256(canonical.encode("utf-8")).hexdigest()


def _package_id(correlation_id: str) -> str:
    digest = hashlib.sha256(correlation_id.encode("utf-8")).hexdigest()[:24]
    return f"gpi_dp_{digest}"


def _safe_path_segment(value: Optional[str], fallback: str) -> str:
    segment = re.sub(r'[<>:"/\\|?*]+', "-", _normalize(value))
    segment = re.sub(r"\s+", " ", segment).strip(" .")
    return segment or fallback


def _build_sales_order_confirmation_package(
    request: DeliveryPreflightRequest,
    request_hash: str,
) -> Dict[str, Any]:
    document_type = _normalize_document_type(request.document.document_type)
    if document_type not in {"SALES_ORDER_CONFIRMATION", "ORDER_CONFIRMATION"}:
        raise HTTPException(
            status_code=422,
            detail=(
                "Sprint 1 preflight currently supports "
                "SALES_ORDER_CONFIRMATION only; received "
                f"{request.document.document_type!r}"
            ),
        )

    if request.document.report_id != ORDER_CONFIRMATION_TEMPLATE["report_id"]:
        raise HTTPException(
            status_code=422,
            detail=(
                "Sprint 1 Sales Order Confirmation preflight requires BC report "
                f"{ORDER_CONFIRMATION_TEMPLATE['report_id']}; received "
                f"{request.document.report_id}"
            ),
        )

    customer = request.customer
    order = request.order
    actors = request.actors
    overrides = request.overrides

    organization = _normalize(customer.organization)
    external_document_no = _normalize(order.external_document_no)

    sales_order_context = {
        "orderType": order.order_type,
        "documentType": request.document.record_type,
        "customerNumber": customer.customer_no,
        "sellToCustomerNumber": customer.sell_to_customer_no,
        "billToCustomerNumber": customer.bill_to_customer_no,
        "shipToCustomerNumber": customer.ship_to_customer_no,
        "customerName": organization,
        "sellToCustomerName": organization,
        "externalDocumentNumber": external_document_no,
    }
    customer_context = {
        "number": customer.customer_no,
        "displayName": organization,
        "email": customer.default_email,
    }

    routing_context = _build_routing_context(
        source_document_type=document_type,
        source_order_type=order.order_type,
        managed_by_department=overrides.managed_by_department,
        customer_no=customer.customer_no,
        sell_to_customer_no=customer.sell_to_customer_no,
        bill_to_customer_no=customer.bill_to_customer_no,
        ship_to_customer_no=customer.ship_to_customer_no,
        organization=organization,
        sales_order=sales_order_context,
        customer=customer_context,
        is_transfer_order_override=order.is_transfer_order,
        internal_customer_override=order.internal_customer,
        include_osr_override=overrides.include_osr,
        include_isr_override=overrides.include_isr,
        show_in_sales_tiles_override=overrides.show_in_sales_tiles,
    )

    sender = _normalize(
        overrides.sender
        or actors.sender_email
        or actors.isr_email
        or actors.initiated_by
    )

    to_values = overrides.to or [
        _normalize(customer.document_email or customer.default_email)
    ]
    to_recipients = _dedupe_emails(to_values)

    if overrides.cc:
        cc_candidates = overrides.cc
    else:
        cc_candidates = []
        if routing_context.get("include_osr"):
            cc_candidates.append(_normalize(actors.osr_email))
        if routing_context.get("include_isr"):
            cc_candidates.append(_normalize(actors.isr_email))

    cc_recipients = _dedupe_emails(
        cc_candidates,
        excluded=to_recipients + ([sender] if sender else []),
    )
    bcc_recipients = _dedupe_emails(
        overrides.bcc,
        excluded=to_recipients + cc_recipients + ([sender] if sender else []),
    )

    token_values = {
        "ZetadocsRecordNo": request.document.record_no,
        "ExternalDocNo": external_document_no,
        "Organization": organization,
    }
    subject = _replace_zetadocs_tokens(
        ORDER_CONFIRMATION_TEMPLATE["subject_template"],
        token_values,
    )
    body_text = _replace_zetadocs_tokens(
        ORDER_CONFIRMATION_TEMPLATE["body_template"],
        token_values,
    )

    file_name = _normalize(
        request.document.file_name
        or f"Sales-Order {request.document.record_no}.pdf"
    )

    warnings: List[Dict[str, Any]] = []
    if not organization:
        warnings.append({
            "code": "ORGANIZATION_MISSING",
            "severity": "blocking",
            "message": "Customer organization could not be resolved.",
        })
    if not to_recipients:
        warnings.append({
            "code": "RECIPIENT_MISSING",
            "severity": "blocking",
            "message": "No external recipient could be resolved.",
        })
    if not sender:
        warnings.append({
            "code": "SENDER_MISSING",
            "severity": "blocking",
            "message": "No sender could be resolved from override, BC user, or ISR.",
        })
    if not external_document_no:
        warnings.append({
            "code": "EXTERNAL_DOCUMENT_NO_MISSING",
            "severity": "warning",
            "message": "Customer PO/external document number was not supplied.",
        })

    blocking_warnings = [
        warning
        for warning in warnings
        if warning["severity"] == "blocking"
    ]
    status = "PREFLIGHT_BLOCKED" if blocking_warnings else "PREFLIGHT_READY"

    customer_folder = _safe_path_segment(
        customer.customer_no
        or customer.sell_to_customer_no
        or customer.bill_to_customer_no,
        "UNKNOWN-CUSTOMER",
    )
    order_folder = _safe_path_segment(
        request.document.record_no,
        "UNKNOWN-ORDER",
    )

    now = _now_iso()
    package_id = _package_id(request.correlation_id)

    return {
        "package_id": package_id,
        "correlation_id": request.correlation_id,
        "request_hash": request_hash,
        "created_utc": now,
        "updated_utc": now,
        "source_system": "BC_NATIVE",
        "source_app": "BC_AL_EXTENSION",
        "workflow_type": "sales_order_confirmation",
        "status": status,
        "delivery_enabled": False,
        "email_send_status": "disabled_preview_only",
        "bc_write_status": "not_applicable_no_bc_write",
        "sharepoint_write_status": "not_applicable_no_sharepoint_write",
        "can_create_email_draft": status == "PREFLIGHT_READY",
        "document": {
            "document_type": document_type,
            "record_type": request.document.record_type,
            "record_no": request.document.record_no,
            "system_id": request.document.system_id,
            "report_id": request.document.report_id,
            "report_name": ORDER_CONFIRMATION_TEMPLATE["report_name"],
            "template_code": request.document.template_code,
            "document_set_no": ORDER_CONFIRMATION_TEMPLATE["document_set_no"],
            "document_set_name": ORDER_CONFIRMATION_TEMPLATE["document_set_name"],
            "file_name": file_name,
            "requested_action": request.document.requested_action,
        },
        "email": {
            "from": sender,
            "to": to_recipients,
            "cc": cc_recipients,
            "bcc": bcc_recipients,
            "subject": subject,
            "body_text": body_text,
        },
        "archive": {
            "provider": "SharePoint",
            "folder_path": f"Sales/{customer_folder}/Orders/{order_folder}",
            "file_name": file_name,
            "storage_status": "not_written_preview_only",
        },
        "routing": routing_context,
        "warnings": warnings,
        "blocking_warning_count": len(blocking_warnings),
        "metadata": request.metadata,
        "audit_events": [
            {
                "event": "preflight_requested",
                "event_utc": now,
                "actor": actors.initiated_by or "bc-user",
                "details": (
                    "Business Central requested a preview-only delivery preflight."
                ),
            },
            {
                "event": "routing_context_evaluated",
                "event_utc": now,
                "actor": "system",
                "details": (
                    "Routing rule applied: "
                    f"{routing_context.get('routing_rule_applied', 'unknown')}"
                ),
            },
            {
                "event": "preflight_completed",
                "event_utc": now,
                "actor": "system",
                "details": (
                    f"Preflight completed with status {status}. "
                    "No email, Business Central write, or SharePoint write occurred."
                ),
            },
        ],
        "request": request.model_dump(mode="json"),
    }


async def create_preflight_package(
    request: DeliveryPreflightRequest,
) -> Dict[str, Any]:
    database = _require_db()
    request_hash = _request_hash(request)

    existing = await database.zetadocs_delivery_packages.find_one(
        {"correlation_id": request.correlation_id},
        {"_id": 0},
    )
    if existing:
        if existing.get("request_hash") != request_hash:
            raise HTTPException(
                status_code=409,
                detail=(
                    "The correlation_id already exists with a different request "
                    "payload. Use a new correlation_id for a materially different "
                    "preflight."
                ),
            )
        return {
            "success": True,
            "duplicate": True,
            "message": "Existing idempotent preflight package returned.",
            "package": existing,
        }

    package = _build_sales_order_confirmation_package(request, request_hash)

    try:
        await database.zetadocs_delivery_packages.insert_one(dict(package))
    except DuplicateKeyError:
        existing = await database.zetadocs_delivery_packages.find_one(
            {"correlation_id": request.correlation_id},
            {"_id": 0},
        )
        if existing and existing.get("request_hash") == request_hash:
            return {
                "success": True,
                "duplicate": True,
                "message": "Existing idempotent preflight package returned.",
                "package": existing,
            }
        raise HTTPException(
            status_code=409,
            detail="A conflicting delivery package was created concurrently.",
        )

    package.pop("_id", None)
    return {
        "success": True,
        "duplicate": False,
        "message": (
            "Preview-only delivery preflight created. "
            "No email was sent and no BC or SharePoint write occurred."
        ),
        "package": package,
    }


@router.get(
    "/status",
    dependencies=[Depends(require_bc_document_events_api_key)],
)
async def get_document_delivery_status():
    database = _require_db()
    package_count = await database.zetadocs_delivery_packages.count_documents({})
    return {
        "status": "ready",
        "api_version": "v1",
        "supported_workflows": ["SALES_ORDER_CONFIRMATION"],
        "packages_recorded": package_count,
        "delivery_enabled": False,
        "email_sending": False,
        "writes_to_bc": False,
        "writes_to_sharepoint": False,
    }


@router.post(
    "/preflight",
    dependencies=[Depends(require_bc_document_events_api_key)],
)
async def create_document_delivery_preflight(
    request: DeliveryPreflightRequest,
):
    return await create_preflight_package(request)


@router.get(
    "/packages/{package_id}",
    dependencies=[Depends(require_bc_document_events_api_key)],
)
async def get_document_delivery_package(package_id: str):
    database = _require_db()
    package = await database.zetadocs_delivery_packages.find_one(
        {"package_id": package_id},
        {"_id": 0},
    )
    if not package:
        raise HTTPException(
            status_code=404,
            detail=f"Delivery package {package_id} was not found",
        )
    return {"success": True, "package": package}
