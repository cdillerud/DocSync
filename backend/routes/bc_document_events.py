"""
GPI Document Hub - Business Central Document Events Router

This router is the safe API surface for the future Business Central AL extension.
It accepts native BC delivery and attachment events and records them in GPI Hub
without performing any Business Central writes.

Design rules:
- Additive only.
- No email polling.
- No BC writes.
- Idempotent event capture.
- Creates or updates hub_documents records using stable BC document event keys.
- Preserves event history for audit and troubleshooting.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import hashlib
import json
import uuid

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel, Field


router = APIRouter(prefix="/bc-document-events", tags=["bc-document-events"])

# Database reference - set by main app at startup
_db = None


def set_db(database):
    global _db
    _db = database


class EventType(str, Enum):
    DELIVERY_SENT = "delivery_sent"
    DELIVERY_FAILED = "delivery_failed"
    ATTACHMENT_LINKED = "attachment_linked"
    ATTACHMENT_SYNC_FAILED = "attachment_sync_failed"


class RecipientPayload(BaseModel):
    to: List[str] = Field(default_factory=list)
    cc: List[str] = Field(default_factory=list)
    bcc: List[str] = Field(default_factory=list)


class SharePointPayload(BaseModel):
    site_id: Optional[str] = None
    drive_id: Optional[str] = None
    item_id: Optional[str] = None
    web_url: Optional[str] = None
    folder_path: Optional[str] = None
    file_name: Optional[str] = None
    storage_status: Optional[str] = None


class BCRecordPayload(BaseModel):
    company_id: Optional[str] = None
    company_name: Optional[str] = None
    environment: Optional[str] = None
    record_type: str
    record_id: Optional[str] = None
    record_no: Optional[str] = None
    record_system_id: Optional[str] = None
    posted: Optional[bool] = None


class BCEventBase(BaseModel):
    event_id: Optional[str] = None
    idempotency_key: Optional[str] = None
    correlation_id: Optional[str] = None
    event_timestamp: Optional[str] = None
    source_app: str = "BC_AL_EXTENSION"
    source_system: str = "BC_NATIVE"
    actor: Optional[str] = None
    bc_record: BCRecordPayload
    document_no: Optional[str] = None
    document_type: Optional[str] = None
    file_name: Optional[str] = None
    hub_document_id: Optional[str] = None
    metadata: Dict[str, Any] = Field(default_factory=dict)


class DeliveryEventPayload(BCEventBase):
    delivery_method: Optional[str] = None
    delivery_status: Optional[str] = None
    template_code: Optional[str] = None
    subject: Optional[str] = None
    email_message_id: Optional[str] = None
    recipient_resolution_method: Optional[str] = None
    recipients: RecipientPayload = Field(default_factory=RecipientPayload)
    sharepoint: Optional[SharePointPayload] = None
    error: Optional[str] = None


class AttachmentEventPayload(BCEventBase):
    attachment_id: Optional[str] = None
    attachment_source: Optional[str] = None
    content_type: Optional[str] = None
    file_size_bytes: Optional[int] = None
    storage_status: Optional[str] = None
    sharepoint: Optional[SharePointPayload] = None
    error: Optional[str] = None


# -------------------- helpers --------------------

def _require_db():
    if _db is None:
        raise HTTPException(status_code=500, detail="BC document events router is not initialized with a database")
    return _db


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _jsonable(value: Any) -> Any:
    """Convert Pydantic/native values into Mongo-safe JSON-compatible data."""
    return json.loads(json.dumps(value, default=str))


def _sha256_text(value: str) -> str:
    return hashlib.sha256(value.encode("utf-8")).hexdigest()


def _stable_event_key(event_type: str, payload: BCEventBase) -> str:
    record = payload.bc_record
    base = "|".join([
        event_type,
        payload.idempotency_key or "",
        payload.correlation_id or "",
        record.company_id or record.company_name or "",
        record.environment or "",
        record.record_type or "",
        record.record_id or "",
        record.record_no or "",
        record.record_system_id or "",
        payload.document_no or "",
        payload.file_name or "",
        payload.event_timestamp or "",
    ])
    return f"bc_evt_{_sha256_text(base)[:32]}"


def _event_id(event_type: str, payload: BCEventBase) -> str:
    return payload.event_id or _stable_event_key(event_type, payload)


def _document_event_key(payload: BCEventBase) -> str:
    record = payload.bc_record
    base = "|".join([
        record.company_id or record.company_name or "",
        record.environment or "",
        record.record_type or "",
        record.record_id or "",
        record.record_no or "",
        record.record_system_id or "",
        payload.document_no or "",
        payload.file_name or "",
    ])
    return f"bc_doc_{_sha256_text(base)[:32]}"


def _document_id(payload: BCEventBase) -> str:
    return payload.hub_document_id or _document_event_key(payload)


def _infer_doc_type(payload: BCEventBase) -> str:
    explicit = (payload.document_type or "").upper().replace(" ", "_").replace("-", "_")
    if explicit:
        return explicit

    record_type = (payload.bc_record.record_type or "").lower()
    if "sales" in record_type and "credit" in record_type:
        return "SALES_CREDIT_MEMO"
    if "purchase" in record_type and "credit" in record_type:
        return "PURCHASE_CREDIT_MEMO"
    if "sales" in record_type and "invoice" in record_type:
        return "SALES_INVOICE"
    if "purchase" in record_type and "invoice" in record_type:
        return "AP_INVOICE"
    if "purchase" in record_type and "order" in record_type:
        return "PURCHASE_ORDER"
    if "sales" in record_type and "order" in record_type:
        return "SALES_ORDER"
    if "statement" in record_type:
        return "STATEMENT"
    if "reminder" in record_type:
        return "REMINDER"
    return "BC_DOCUMENT"


def _infer_category(doc_type: str) -> str:
    if doc_type in {"AP_INVOICE", "PURCHASE_CREDIT_MEMO", "PURCHASE_ORDER"}:
        return "AP"
    if doc_type in {"SALES_INVOICE", "SALES_CREDIT_MEMO", "SALES_ORDER"}:
        return "Sales"
    return "BC"


def _build_bc_source(payload: BCEventBase) -> Dict[str, Any]:
    record = payload.bc_record
    return {
        "company_id": record.company_id,
        "company_name": record.company_name,
        "environment": record.environment,
        "record_type": record.record_type,
        "record_id": record.record_id,
        "record_no": record.record_no,
        "record_system_id": record.record_system_id,
        "posted": record.posted,
        "document_no": payload.document_no,
    }


def _workflow_history_entry(event_type: str, event_id: str, payload: BCEventBase, note: Optional[str] = None) -> Dict[str, Any]:
    return {
        "timestamp": _now_iso(),
        "event": event_type,
        "actor": payload.actor or payload.source_app,
        "event_id": event_id,
        "correlation_id": payload.correlation_id,
        "note": note or f"Business Central document event received: {event_type}",
    }


def _base_event_document(event_type: str, event_id: str, payload: BCEventBase, specific_payload: Dict[str, Any]) -> Dict[str, Any]:
    now = _now_iso()
    return {
        "event_id": event_id,
        "event_type": event_type,
        "idempotency_key": payload.idempotency_key,
        "correlation_id": payload.correlation_id,
        "event_timestamp": payload.event_timestamp or now,
        "received_utc": now,
        "source_app": payload.source_app,
        "source_system": payload.source_system,
        "actor": payload.actor,
        "hub_document_id": _document_id(payload),
        "bc_document_event_key": _document_event_key(payload),
        "bc_source": _build_bc_source(payload),
        "document_no": payload.document_no,
        "document_type": payload.document_type,
        "file_name": payload.file_name,
        "payload": specific_payload,
        "metadata": payload.metadata,
    }


def _delivery_doc(payload: DeliveryEventPayload, event_type: str) -> Dict[str, Any]:
    return {
        "delivery_status": payload.delivery_status or ("sent" if event_type == EventType.DELIVERY_SENT.value else "failed"),
        "delivery_method": payload.delivery_method,
        "template_code": payload.template_code,
        "recipient_resolution_method": payload.recipient_resolution_method,
        "to": payload.recipients.to,
        "cc": payload.recipients.cc,
        "bcc": payload.recipients.bcc,
        "subject": payload.subject,
        "email_message_id": payload.email_message_id,
        "sent_at": payload.event_timestamp if event_type == EventType.DELIVERY_SENT.value else None,
        "failed_at": payload.event_timestamp if event_type == EventType.DELIVERY_FAILED.value else None,
        "sent_by": payload.actor,
        "error": payload.error,
    }


def _attachment_doc(payload: AttachmentEventPayload, event_type: str) -> Dict[str, Any]:
    return {
        "attachment_event_type": event_type,
        "attachment_id": payload.attachment_id,
        "attachment_source": payload.attachment_source,
        "file_name": payload.file_name,
        "content_type": payload.content_type,
        "file_size_bytes": payload.file_size_bytes,
        "storage_status": payload.storage_status or ("synced" if event_type == EventType.ATTACHMENT_LINKED.value else "failed"),
        "linked_at": payload.event_timestamp if event_type == EventType.ATTACHMENT_LINKED.value else None,
        "failed_at": payload.event_timestamp if event_type == EventType.ATTACHMENT_SYNC_FAILED.value else None,
        "error": payload.error,
        "sharepoint": _jsonable(payload.sharepoint.model_dump()) if payload.sharepoint else None,
    }


async def _record_event(event_type: str, payload: BCEventBase, specific_payload: Dict[str, Any]) -> Dict[str, Any]:
    db = _require_db()
    event_id = _event_id(event_type, payload)
    now = _now_iso()

    existing_event = await db.bc_document_events.find_one({"event_id": event_id}, {"_id": 0})
    if existing_event:
        return {
            "success": True,
            "duplicate": True,
            "event_id": event_id,
            "document_id": existing_event.get("hub_document_id"),
            "message": "Event already recorded; no duplicate document update performed",
        }

    event_doc = _base_event_document(event_type, event_id, payload, specific_payload)
    await db.bc_document_events.insert_one(_jsonable(event_doc))

    doc_id = _document_id(payload)
    doc_type = _infer_doc_type(payload)
    category = _infer_category(doc_type)
    doc_event_key = _document_event_key(payload)

    base_set_on_insert = {
        "id": doc_id,
        "bc_document_event_key": doc_event_key,
        "source": "bc_document_event",
        "source_system": payload.source_system,
        "capture_channel": "API",
        "doc_type": doc_type,
        "document_type": doc_type,
        "category": category,
        "status": "received",
        "workflow_status": "captured",
        "created_utc": now,
        "file_name": payload.file_name,
        "document_no": payload.document_no,
        "legacy_context": {
            "source_system": payload.source_system,
            "capture_channel": "API",
        },
    }

    update_set = {
        "updated_utc": now,
        "last_bc_event_type": event_type,
        "last_bc_event_id": event_id,
        "last_bc_event_utc": now,
        "bc_source": _build_bc_source(payload),
        "source_system": payload.source_system,
        "capture_channel": "API",
    }

    update_ops: Dict[str, Any] = {
        "$setOnInsert": base_set_on_insert,
        "$set": update_set,
        "$push": {
            "workflow_history": _workflow_history_entry(event_type, event_id, payload)
        },
        "$addToSet": {
            "bc_event_ids": event_id,
            "bc_event_types": event_type,
        },
    }

    await db.hub_documents.update_one(
        {"id": doc_id},
        update_ops,
        upsert=True,
    )

    return {
        "success": True,
        "duplicate": False,
        "event_id": event_id,
        "document_id": doc_id,
        "bc_document_event_key": doc_event_key,
        "event_type": event_type,
        "received_utc": now,
    }


async def _record_delivery_event(event_type: str, payload: DeliveryEventPayload) -> Dict[str, Any]:
    db = _require_db()
    delivery = _delivery_doc(payload, event_type)
    result = await _record_event(event_type, payload, delivery)

    if result.get("duplicate"):
        return result

    doc_update = {
        "delivery": delivery,
    }

    if payload.sharepoint:
        doc_update["sharepoint"] = _jsonable(payload.sharepoint.model_dump())

    if event_type == EventType.DELIVERY_SENT.value:
        doc_update["status"] = "sent"
        doc_update["workflow_status"] = "exported"
    else:
        doc_update["status"] = "delivery_failed"
        doc_update["workflow_status"] = "exception"

    await db.hub_documents.update_one(
        {"id": result["document_id"]},
        {"$set": _jsonable(doc_update)},
    )

    return result


async def _record_attachment_event(event_type: str, payload: AttachmentEventPayload) -> Dict[str, Any]:
    db = _require_db()
    attachment = _attachment_doc(payload, event_type)
    result = await _record_event(event_type, payload, attachment)

    if result.get("duplicate"):
        return result

    set_fields: Dict[str, Any] = {
        "status": "attachment_linked" if event_type == EventType.ATTACHMENT_LINKED.value else "attachment_sync_failed",
    }

    if payload.sharepoint:
        set_fields["sharepoint"] = _jsonable(payload.sharepoint.model_dump())

    await db.hub_documents.update_one(
        {"id": result["document_id"]},
        {
            "$set": _jsonable(set_fields),
            "$push": {"attachments": _jsonable(attachment)},
        },
    )

    return result


# -------------------- endpoints --------------------

@router.get("/status")
async def get_bc_document_events_status():
    """Return event-router status and basic counts."""
    db = _require_db()
    events_count = await db.bc_document_events.count_documents({})
    docs_count = await db.hub_documents.count_documents({"source": "bc_document_event"})
    return {
        "status": "ready",
        "events_recorded": events_count,
        "bc_event_documents": docs_count,
        "writes_to_bc": False,
        "mailbox_polling": False,
    }


@router.post("/delivery-sent")
async def delivery_sent(payload: DeliveryEventPayload):
    """Record a successful BC document delivery event."""
    return await _record_delivery_event(EventType.DELIVERY_SENT.value, payload)


@router.post("/delivery-failed")
async def delivery_failed(payload: DeliveryEventPayload):
    """Record a failed BC document delivery event."""
    return await _record_delivery_event(EventType.DELIVERY_FAILED.value, payload)


@router.post("/attachment-linked")
async def attachment_linked(payload: AttachmentEventPayload):
    """Record a BC attachment successfully linked/synced to SharePoint."""
    return await _record_attachment_event(EventType.ATTACHMENT_LINKED.value, payload)


@router.post("/attachment-sync-failed")
async def attachment_sync_failed(payload: AttachmentEventPayload):
    """Record a BC attachment sync failure."""
    return await _record_attachment_event(EventType.ATTACHMENT_SYNC_FAILED.value, payload)


@router.get("/records/{bc_record_type}/{bc_record_no}")
async def get_events_for_bc_record(
    bc_record_type: str,
    bc_record_no: str,
    limit: int = Query(50, ge=1, le=200),
):
    """Return GPI Hub documents and events for a specific BC record number."""
    db = _require_db()
    docs = await db.hub_documents.find(
        {
            "bc_source.record_type": bc_record_type,
            "bc_source.record_no": bc_record_no,
        },
        {"_id": 0},
    ).sort("updated_utc", -1).limit(limit).to_list(limit)

    events = await db.bc_document_events.find(
        {
            "bc_source.record_type": bc_record_type,
            "bc_source.record_no": bc_record_no,
        },
        {"_id": 0},
    ).sort("received_utc", -1).limit(limit).to_list(limit)

    return {
        "bc_record_type": bc_record_type,
        "bc_record_no": bc_record_no,
        "documents": docs,
        "events": events,
        "document_count": len(docs),
        "event_count": len(events),
    }
