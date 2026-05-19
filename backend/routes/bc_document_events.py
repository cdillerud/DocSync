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
- Requires X-GPI-Hub-Api-Key when BC_DOCUMENT_EVENTS_API_KEY is configured.
"""

from datetime import datetime, timezone
from enum import Enum
from typing import Any, Dict, List, Optional
import hashlib
import json
import os
import secrets

from fastapi import APIRouter, Depends, Header, HTTPException, Query
from pydantic import BaseModel, Field
from pymongo.errors import DuplicateKeyError


router = APIRouter(prefix="/bc-document-events", tags=["bc-document-events"])

# Database reference - set by main app at startup
_db = None

BC_DOCUMENT_EVENTS_API_KEY = os.environ.get("BC_DOCUMENT_EVENTS_API_KEY", "").strip()
BC_DOCUMENT_EVENTS_REQUIRE_API_KEY = os.environ.get("BC_DOCUMENT_EVENTS_REQUIRE_API_KEY", "true").lower() != "false"


def set_db(database):
    global _db
    _db = database


async def require_bc_document_events_api_key(x_gpi_hub_api_key: Optional[str] = Header(default=None)):
    """Protect write/repair endpoints when a BC document-events API key is configured."""
    if not BC_DOCUMENT_EVENTS_REQUIRE_API_KEY:
        return

    if not BC_DOCUMENT_EVENTS_API_KEY:
        raise HTTPException(
            status_code=503,
            detail="BC document-events API key is not configured on the server"
        )

    if not x_gpi_hub_api_key:
        raise HTTPException(status_code=401, detail="Missing X-GPI-Hub-Api-Key header")

    if not secrets.compare_digest(x_gpi_hub_api_key, BC_DOCUMENT_EVENTS_API_KEY):
        raise HTTPException(status_code=401, detail="Invalid X-GPI-Hub-Api-Key header")


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


def _normalize_doc_type(value: Optional[str]) -> str:
    return (value or "").upper().replace(" ", "_").replace("-", "_")


def _infer_doc_type_from_record_type(record_type: Optional[str], explicit: Optional[str] = None) -> str:
    normalized_explicit = _normalize_doc_type(explicit)
    if normalized_explicit:
        return normalized_explicit

    rt = (record_type or "").lower()
    if "sales" in rt and "credit" in rt:
        return "SALES_CREDIT_MEMO"
    if "purchase" in rt and "credit" in rt:
        return "PURCHASE_CREDIT_MEMO"
    if "sales" in rt and "invoice" in rt:
        return "SALES_INVOICE"
    if "purchase" in rt and "invoice" in rt:
        return "AP_INVOICE"
    if "purchase" in rt and "order" in rt:
        return "PURCHASE_ORDER"
    if "sales" in rt and "order" in rt:
        return "SALES_ORDER"
    if "statement" in rt:
        return "STATEMENT"
    if "reminder" in rt:
        return "REMINDER"
    return "BC_DOCUMENT"


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
    return _infer_doc_type_from_record_type(payload.bc_record.record_type, payload.document_type)


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


def _status_for_event_type(event_type: str) -> Dict[str, str]:
    if event_type == EventType.DELIVERY_SENT.value:
        return {"status": "sent", "workflow_status": "exported"}
    if event_type == EventType.DELIVERY_FAILED.value:
        return {"status": "delivery_failed", "workflow_status": "exception"}
    if event_type == EventType.ATTACHMENT_LINKED.value:
        return {"status": "attachment_linked", "workflow_status": "captured"}
    if event_type == EventType.ATTACHMENT_SYNC_FAILED.value:
        return {"status": "attachment_sync_failed", "workflow_status": "exception"}
    return {"status": "received", "workflow_status": "captured"}


async def _repair_hub_document_from_existing_event(existing_event: Dict[str, Any]) -> bool:
    """Repair an orphan event whose event row exists but hub_documents was not created."""
    db = _require_db()
    doc_id = existing_event.get("hub_document_id")
    if not doc_id:
        return False

    already_exists = await db.hub_documents.find_one({"id": doc_id}, {"_id": 1})
    if already_exists:
        return False

    now = _now_iso()
    event_type = existing_event.get("event_type", "bc_document_event")
    event_id = existing_event.get("event_id")
    bc_source = existing_event.get("bc_source") or {}
    payload = existing_event.get("payload") or {}
    doc_type = _infer_doc_type_from_record_type(bc_source.get("record_type"), existing_event.get("document_type"))
    category = _infer_category(doc_type)
    statuses = _status_for_event_type(event_type)

    repaired_doc = {
        "id": doc_id,
        "bc_document_event_key": existing_event.get("bc_document_event_key"),
        "source": "bc_document_event",
        "source_system": existing_event.get("source_system") or "BC_NATIVE",
        "capture_channel": "API",
        "doc_type": doc_type,
        "document_type": doc_type,
        "category": category,
        "status": statuses["status"],
        "workflow_status": statuses["workflow_status"],
        "created_utc": now,
        "updated_utc": now,
        "file_name": existing_event.get("file_name"),
        "document_no": existing_event.get("document_no"),
        "bc_source": bc_source,
        "last_bc_event_type": event_type,
        "last_bc_event_id": event_id,
        "last_bc_event_utc": now,
        "bc_event_ids": [event_id] if event_id else [],
        "bc_event_types": [event_type],
        "legacy_context": {
            "source_system": existing_event.get("source_system") or "BC_NATIVE",
            "capture_channel": "API",
        },
        "workflow_history": [{
            "timestamp": now,
            "event": event_type,
            "actor": existing_event.get("actor") or existing_event.get("source_app") or "BC_DOCUMENT_EVENTS_REPAIR",
            "event_id": event_id,
            "correlation_id": existing_event.get("correlation_id"),
            "note": "Repaired hub document from previously recorded BC document event",
        }],
    }

    if event_type in {EventType.DELIVERY_SENT.value, EventType.DELIVERY_FAILED.value}:
        repaired_doc["delivery"] = payload
    elif event_type in {EventType.ATTACHMENT_LINKED.value, EventType.ATTACHMENT_SYNC_FAILED.value}:
        repaired_doc["attachments"] = [payload]

    await db.hub_documents.insert_one(_jsonable(repaired_doc))
    return True


async def _record_event(event_type: str, payload: BCEventBase, specific_payload: Dict[str, Any]) -> Dict[str, Any]:
    db = _require_db()
    event_id = _event_id(event_type, payload)
    now = _now_iso()

    existing_event = await db.bc_document_events.find_one({"event_id": event_id}, {"_id": 0})
    if existing_event:
        doc_id = existing_event.get("hub_document_id")
        repaired = await _repair_hub_document_from_existing_event(existing_event)
        doc_exists = bool(doc_id and await db.hub_documents.find_one({"id": doc_id}, {"_id": 1}))
        return {
            "success": True,
            "duplicate": True,
            "repaired_document": repaired,
            "orphaned_document": not doc_exists,
            "event_id": event_id,
            "document_id": doc_id,
            "message": "Event already recorded; hub document checked and repaired if needed",
        }

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

    # Upsert the hub document before recording the event row. This avoids an
    # orphan event if the document update fails.
    await db.hub_documents.update_one(
        {"id": doc_id},
        _jsonable(update_ops),
        upsert=True,
    )

    event_doc = _base_event_document(event_type, event_id, payload, specific_payload)
    try:
        await db.bc_document_events.insert_one(_jsonable(event_doc))
    except DuplicateKeyError:
        # Another caller recorded the same event after the hub document upsert.
        return {
            "success": True,
            "duplicate": True,
            "event_id": event_id,
            "document_id": doc_id,
            "bc_document_event_key": doc_event_key,
            "event_type": event_type,
            "received_utc": now,
            "message": "Event already recorded after hub document update",
        }

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

    doc_update = {
        "delivery": delivery,
    }

    if payload.sharepoint:
        doc_update["sharepoint"] = _jsonable(payload.sharepoint.model_dump())

    doc_update.update(_status_for_event_type(event_type))

    if result.get("document_id"):
        await db.hub_documents.update_one(
            {"id": result["document_id"]},
            {"$set": _jsonable(doc_update)},
        )

    return result


async def _record_attachment_event(event_type: str, payload: AttachmentEventPayload) -> Dict[str, Any]:
    db = _require_db()
    attachment = _attachment_doc(payload, event_type)
    result = await _record_event(event_type, payload, attachment)

    set_fields: Dict[str, Any] = _status_for_event_type(event_type)

    if payload.sharepoint:
        set_fields["sharepoint"] = _jsonable(payload.sharepoint.model_dump())

    if result.get("document_id") and not result.get("duplicate"):
        await db.hub_documents.update_one(
            {"id": result["document_id"]},
            {
                "$set": _jsonable(set_fields),
                "$push": {"attachments": _jsonable(attachment)},
            },
        )
    elif result.get("document_id"):
        await db.hub_documents.update_one(
            {"id": result["document_id"]},
            {"$set": _jsonable(set_fields)},
        )

    return result


# -------------------- endpoints --------------------

@router.get("/status")
async def get_bc_document_events_status():
    """Return event-router status and basic counts."""
    db = _require_db()
    events_count = await db.bc_document_events.count_documents({})
    docs_count = await db.hub_documents.count_documents({"source": "bc_document_event"})
    orphan_count = await db.bc_document_events.count_documents({
        "hub_document_id": {"$nin": await db.hub_documents.distinct("id", {"source": "bc_document_event"})}
    })
    return {
        "status": "ready",
        "events_recorded": events_count,
        "bc_event_documents": docs_count,
        "orphan_events": orphan_count,
        "writes_to_bc": False,
        "mailbox_polling": False,
        "api_key_required": BC_DOCUMENT_EVENTS_REQUIRE_API_KEY,
        "api_key_configured": bool(BC_DOCUMENT_EVENTS_API_KEY),
    }


@router.post("/delivery-sent", dependencies=[Depends(require_bc_document_events_api_key)])
async def delivery_sent(payload: DeliveryEventPayload):
    """Record a successful BC document delivery event."""
    return await _record_delivery_event(EventType.DELIVERY_SENT.value, payload)


@router.post("/delivery-failed", dependencies=[Depends(require_bc_document_events_api_key)])
async def delivery_failed(payload: DeliveryEventPayload):
    """Record a failed BC document delivery event."""
    return await _record_delivery_event(EventType.DELIVERY_FAILED.value, payload)


@router.post("/attachment-linked", dependencies=[Depends(require_bc_document_events_api_key)])
async def attachment_linked(payload: AttachmentEventPayload):
    """Record a BC attachment successfully linked/synced to SharePoint."""
    return await _record_attachment_event(EventType.ATTACHMENT_LINKED.value, payload)


@router.post("/attachment-sync-failed", dependencies=[Depends(require_bc_document_events_api_key)])
async def attachment_sync_failed(payload: AttachmentEventPayload):
    """Record a BC attachment sync failure."""
    return await _record_attachment_event(EventType.ATTACHMENT_SYNC_FAILED.value, payload)


@router.post("/repair-orphans", dependencies=[Depends(require_bc_document_events_api_key)])
async def repair_orphan_events():
    """Repair any BC document events that exist without matching hub_documents rows."""
    db = _require_db()
    events = await db.bc_document_events.find({}, {"_id": 0}).to_list(10000)
    repaired = 0
    checked = 0

    for event_doc in events:
        checked += 1
        doc_id = event_doc.get("hub_document_id")
        if not doc_id:
            continue
        existing_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 1})
        if existing_doc:
            continue
        if await _repair_hub_document_from_existing_event(event_doc):
            repaired += 1

    return {
        "success": True,
        "checked_events": checked,
        "repaired_documents": repaired,
    }


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
