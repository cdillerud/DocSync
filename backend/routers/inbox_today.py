"""Daily Inbox drill-down for Square9 replacement verification.

The endpoint uses the same Chicago-local day boundary and batch-parent exclusion
as the Inbox Today KPI. It reports original source attachments separately from
produced documents and exposes classification, routing, and filing evidence.
"""

from __future__ import annotations

from collections import Counter
from datetime import datetime, timezone
import re
from typing import Any, Dict, Iterable, Optional
from zoneinfo import ZoneInfo

from fastapi import APIRouter, Query

from deps import get_db

router = APIRouter(prefix="/dashboard", tags=["Dashboard"])

GPI_TIMEZONE_NAME = "America/Chicago"
GPI_TZ = ZoneInfo(GPI_TIMEZONE_NAME)

TODAY_PROJECTION = {
    "_id": 0,
    "id": 1,
    "file_name": 1,
    "created_utc": 1,
    "received_utc": 1,
    "updated_utc": 1,
    "source": 1,
    "source_system": 1,
    "capture_channel": 1,
    "category": 1,
    "mailbox_category": 1,
    "pilot_mailbox": 1,
    "source_mailbox": 1,
    "mailbox_address": 1,
    "intake_mailbox": 1,
    "email_recipient": 1,
    "email_sender": 1,
    "sender": 1,
    "email_subject": 1,
    "document_type": 1,
    "doc_type": 1,
    "suggested_job_type": 1,
    "ai_confidence": 1,
    "classification_method": 1,
    "status": 1,
    "workflow_status": 1,
    "square9_stage": 1,
    "automation_decision": 1,
    "auto_cleared": 1,
    "sharepoint_folder": 1,
    "sharepoint_folder_path": 1,
    "sharepoint_folder_assigned_by": 1,
    "sharepoint_folder_assigned_at": 1,
    "sharepoint_item_id": 1,
    "sharepoint_web_url": 1,
    "filed_to": 1,
    "filed_folder": 1,
    "filed_at": 1,
    "sharepoint_folder_suggestion": 1,
    "sharepoint_folder_reason": 1,
    "initial_suggested_folder": 1,
    "initial_routing_reason": 1,
    "initial_routing_source": 1,
    "initial_routing_suggested_at": 1,
    "routing_suggestion_snapshot": 1,
    "routing_suggested_at": 1,
    "suggested_folder": 1,
    "suggested_folder_path": 1,
    "routing_reason": 1,
    "folder_routing_reason": 1,
    "routing_source": 1,
    "human_routing_decision": 1,
    "routing_evidence": 1,
    "route_result": 1,
    "vendor_canonical": 1,
    "vendor_raw": 1,
    "customer_name": 1,
    "is_duplicate": 1,
    "possible_duplicate": 1,
    "batch_parent_id": 1,
    "batch_source_filename": 1,
    "batch_group_num": 1,
    "batch_pages": 1,
    "batch_split_mode": 1,
    "email_id": 1,
    "internet_message_id": 1,
    "message_id": 1,
    "attachment_id": 1,
    "attachment_hash": 1,
    "sha256_hash": 1,
    "extracted_fields": 1,
    "normalized_fields": 1,
    "canonical_fields": 1,
    "po_number_clean": 1,
    "po_number_extracted": 1,
    "po_resolution": 1,
    "bc_po_resolved": 1,
    "is_international": 1,
    "location_code": 1,
    "resolved_location_code": 1,
    "freight_direction": 1,
    "tags": 1,
    "needs_logistics_approval": 1,
    "has_freight_issue": 1,
    "approved": 1,
}

_SPLIT_SUFFIX_RE = re.compile(r"(?i)(?:_(?:doc|p|part)\d+)(?=(?:\.[^.]+)?$)")
_FOLDER_SLASH_RE = re.compile(r"/+" )

# Production writes may persist either the complete SharePoint path, the base
# folder tail, or only the relative routing folder depending on the writer and
# schema generation. The suggestion snapshot intentionally stores the relative
# routing folder, so these known base forms must be removed before comparison.
_KNOWN_SHAREPOINT_BASES = (
    "general/accounting/accounts payable/temp folder",
    "temp folder",
)


def _first_nonempty(*values: Any) -> Any:
    for value in values:
        if value is None:
            continue
        if isinstance(value, str):
            if value.strip():
                return value.strip()
            continue
        if value:
            return value
    return ""


def _as_confidence_pct(value: Any) -> Optional[float]:
    if value is None or value == "":
        return None
    try:
        number = float(value)
    except (TypeError, ValueError):
        return None
    if number <= 1:
        number *= 100
    return round(max(0.0, min(number, 100.0)), 1)


def _local_iso(value: Any) -> str:
    if not value:
        return ""
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        if parsed.tzinfo is None:
            parsed = parsed.replace(tzinfo=timezone.utc)
        return parsed.astimezone(GPI_TZ).isoformat()
    except (TypeError, ValueError):
        return str(value)


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1", "true", "yes", "y", "international", "intl"
    }


def _folder_comparison_key(value: Any) -> str:
    """Normalize relative and SharePoint-prefixed folder paths for comparison.

    This removes only known SharePoint base folders. It does not use a generic
    suffix comparison, because that could incorrectly treat two genuinely
    different folder hierarchies as equivalent.
    """
    path = str(value or "").replace("\\", "/").strip()
    path = _FOLDER_SLASH_RE.sub("/", path).strip("/").casefold()
    if not path:
        return ""

    for base in _KNOWN_SHAREPOINT_BASES:
        if path == base:
            return ""
        prefix = f"{base}/"
        if path.startswith(prefix):
            return path[len(prefix):]
    return path


def _folders_equivalent(suggested: Any, final: Any) -> bool:
    suggested_key = _folder_comparison_key(suggested)
    final_key = _folder_comparison_key(final)
    return bool(suggested_key and final_key and suggested_key == final_key)


def build_today_filter(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Return the exact query shape used by the Inbox Today KPI."""
    now_ct = (now or datetime.now(GPI_TZ)).astimezone(GPI_TZ)
    today_start = now_ct.replace(hour=0, minute=0, second=0, microsecond=0)
    return {
        "created_utc": {"$gte": today_start.astimezone(timezone.utc).isoformat()},
        "status": {"$ne": "batch_parent"},
    }


def _lane_for_document(doc: Dict[str, Any]) -> str:
    configured_lane = str(
        _first_nonempty(doc.get("mailbox_category"), doc.get("category"))
    ).strip().lower()
    if configured_lane in {"ap", "billing", "accounts payable", "accounts_payable"}:
        return "AP"
    if configured_lane in {"operations", "warehouse", "shipping", "ops"}:
        return "Warehouse"
    if configured_lane in {"sales", "ar", "accounts receivable", "accounts_receivable"}:
        return "Sales"

    doc_type = str(_first_nonempty(
        doc.get("document_type"), doc.get("doc_type"), doc.get("suggested_job_type")
    )).lower()
    if any(token in doc_type for token in (
        "warehouse", "shipping", "shipment", "packing", "bill_of_lading", "bol"
    )):
        return "Warehouse"
    if any(token in doc_type for token in (
        "sales", "customer_po", "customer po", "order_confirmation"
    )):
        return "Sales"
    if any(token in doc_type for token in (
        "ap", "purchase", "invoice", "credit", "remittance", "freight"
    )):
        return "AP"
    return "Other"


def _canonical_source_filename(file_name: str) -> str:
    value = str(file_name or "").strip()
    return _SPLIT_SUFFIX_RE.sub("", value) if value else "Unknown source"


def _source_identity(doc: Dict[str, Any]) -> Dict[str, Any]:
    batch_parent_id = str(doc.get("batch_parent_id") or "").strip()
    batch_source_name = str(doc.get("batch_source_filename") or "").strip()
    file_name = str(doc.get("file_name") or "").strip()

    if batch_parent_id:
        return {
            "source_file_key": f"batch:{batch_parent_id}",
            "source_file_name": batch_source_name or _canonical_source_filename(file_name),
            "is_split_output": True,
        }

    message_id = str(_first_nonempty(
        doc.get("internet_message_id"), doc.get("message_id"), doc.get("email_id")
    )).strip()
    attachment_id = str(doc.get("attachment_id") or "").strip()
    attachment_hash = str(doc.get("attachment_hash") or "").strip()
    sha256_hash = str(doc.get("sha256_hash") or "").strip()
    source_name = batch_source_name or file_name or "Unknown source"

    if message_id and attachment_id:
        key = f"mail:{message_id}:attachment:{attachment_id}"
    elif message_id:
        key = f"mail:{message_id}:file:{source_name.casefold()}"
    elif attachment_hash:
        key = f"attachment-hash:{attachment_hash}"
    elif sha256_hash:
        key = f"content-hash:{sha256_hash}"
    else:
        key = f"document:{doc.get('id', source_name)}"

    return {
        "source_file_key": key,
        "source_file_name": source_name,
        "is_split_output": False,
    }


def _stored_suggestion_candidate(doc: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    if doc.get("routing_suggestion_snapshot"):
        return None

    human = doc.get("human_routing_decision") or {}
    if human.get("suggested_folder"):
        return {
            "folder_path": str(human.get("suggested_folder")),
            "reason": str(human.get("suggested_reason") or ""),
            "source": str(human.get("source") or "human_routing_review"),
            "suggested_at": str(
                human.get("created_at") or doc.get("sharepoint_folder_assigned_at") or ""
            ),
            "capture_type": "human_review",
        }

    if doc.get("sharepoint_folder_suggestion"):
        return {
            "folder_path": str(doc.get("sharepoint_folder_suggestion")),
            "reason": str(doc.get("sharepoint_folder_reason") or ""),
            "source": "file_and_clear",
            "suggested_at": str(doc.get("filed_at") or doc.get("updated_utc") or ""),
            "capture_type": "file_and_clear_decision",
        }

    stored_folder = _first_nonempty(
        doc.get("initial_suggested_folder"),
        doc.get("suggested_folder_path"),
        doc.get("suggested_folder"),
    )
    if not stored_folder:
        return None
    return {
        "folder_path": str(stored_folder),
        "reason": str(_first_nonempty(
            doc.get("initial_routing_reason"),
            doc.get("routing_reason"),
            doc.get("folder_routing_reason"),
        )),
        "source": str(_first_nonempty(
            doc.get("initial_routing_source"),
            doc.get("routing_source"),
            "stored_routing_suggestion",
        )),
        "suggested_at": str(_first_nonempty(
            doc.get("initial_routing_suggested_at"),
            doc.get("routing_suggested_at"),
            doc.get("updated_utc"),
        )),
        "capture_type": "stored_suggestion",
    }


async def _normalize_stored_suggestion(db, doc: Dict[str, Any]) -> None:
    """Copy an already-persisted decision into the stable snapshot schema."""
    candidate = _stored_suggestion_candidate(doc)
    doc_id = str(doc.get("id") or "")
    if not candidate or not doc_id:
        return

    snapshot = {
        **candidate,
        "normalized_at": datetime.now(timezone.utc).isoformat(),
    }
    update = {
        "routing_suggestion_snapshot": snapshot,
        "initial_suggested_folder": candidate["folder_path"],
        "initial_routing_reason": candidate["reason"],
        "initial_routing_source": candidate["source"],
        "initial_routing_suggested_at": candidate["suggested_at"],
    }
    result = await db.hub_documents.update_one(
        {
            "id": doc_id,
            "$or": [
                {"routing_suggestion_snapshot": {"$exists": False}},
                {"routing_suggestion_snapshot": None},
                {"routing_suggestion_snapshot": {}},
            ],
        },
        {"$set": update},
    )
    if result.modified_count:
        doc.update(update)


def _has_stored_suggestion(doc: Dict[str, Any]) -> bool:
    snapshot = doc.get("routing_suggestion_snapshot") or {}
    human = doc.get("human_routing_decision") or {}
    return bool(_first_nonempty(
        snapshot.get("folder_path"),
        doc.get("initial_suggested_folder"),
        human.get("suggested_folder"),
        doc.get("sharepoint_folder_suggestion"),
        doc.get("suggested_folder_path"),
        doc.get("suggested_folder"),
    ))


async def _add_current_rule_suggestion(doc: Dict[str, Any]) -> None:
    if _has_stored_suggestion(doc):
        return
    try:
        from services.folder_routing_service import route_with_feedback

        extracted = doc.get("extracted_fields") or {}
        is_international = _is_truthy(doc.get("is_international")) or _is_truthy(
            extracted.get("is_international")
        )
        folder, reason, details = await route_with_feedback(
            doc=doc,
            is_international=is_international,
            location_code=(
                doc.get("resolved_location_code")
                or doc.get("location_code")
                or extracted.get("location_code")
            ),
            freight_direction=(
                doc.get("freight_direction") or extracted.get("freight_direction")
            ),
        )
        if folder:
            doc["_display_suggestion"] = {
                "folder_path": folder,
                "reason": reason,
                "source": str((details or {}).get("source") or "current_routing_rules"),
                "suggested_at": datetime.now(timezone.utc).isoformat(),
                "capture_type": "computed_current_rule",
            }
    except Exception as error:
        doc["_display_suggestion_error"] = str(error)[:300]


def _routing_values(doc: Dict[str, Any]) -> Dict[str, Any]:
    human = doc.get("human_routing_decision") or {}
    route_result = doc.get("route_result") or {}
    evidence = doc.get("routing_evidence") or {}
    snapshot = doc.get("routing_suggestion_snapshot") or {}
    display = doc.get("_display_suggestion") or {}

    suggested = str(_first_nonempty(
        snapshot.get("folder_path"),
        doc.get("initial_suggested_folder"),
        human.get("suggested_folder"),
        doc.get("sharepoint_folder_suggestion"),
        doc.get("suggested_folder_path"),
        doc.get("suggested_folder"),
        route_result.get("suggested_folder"),
        route_result.get("folder_path"),
        evidence.get("suggested_folder"),
        display.get("folder_path"),
    ))
    final = str(_first_nonempty(
        doc.get("sharepoint_folder_path"),
        doc.get("sharepoint_folder"),
        doc.get("filed_folder"),
        doc.get("filed_to"),
        human.get("selected_folder"),
    ))
    reason = str(_first_nonempty(
        snapshot.get("reason"),
        doc.get("initial_routing_reason"),
        human.get("suggested_reason"),
        doc.get("sharepoint_folder_reason"),
        doc.get("routing_reason"),
        doc.get("folder_routing_reason"),
        route_result.get("reason"),
        evidence.get("reason"),
        display.get("reason"),
    ))
    source = str(_first_nonempty(
        snapshot.get("source"),
        doc.get("initial_routing_source"),
        human.get("source"),
        doc.get("routing_source"),
        route_result.get("source"),
        display.get("source"),
        doc.get("sharepoint_folder_assigned_by"),
    ))
    suggested_at = str(_first_nonempty(
        snapshot.get("suggested_at"),
        doc.get("initial_routing_suggested_at"),
        doc.get("routing_suggested_at"),
        human.get("created_at"),
        display.get("suggested_at"),
        doc.get("filed_at") if doc.get("sharepoint_folder_suggestion") else "",
    ))
    suggestion_capture = str(_first_nonempty(
        snapshot.get("capture_type"),
        "human_review" if human.get("suggested_folder") else "",
        "file_and_clear_decision" if doc.get("sharepoint_folder_suggestion") else "",
        "stored_suggestion" if _first_nonempty(
            doc.get("suggested_folder_path"), doc.get("suggested_folder")
        ) else "",
        display.get("capture_type"),
    ))

    status_text = f"{doc.get('status', '')} {doc.get('workflow_status', '')}".lower()
    has_file_evidence = bool(_first_nonempty(
        doc.get("sharepoint_item_id"), doc.get("sharepoint_web_url"), doc.get("filed_at")
    )) or any(token in status_text for token in ("filed", "storedinsp", "exported"))
    needs_review = any(token in status_text for token in (
        "needsreview", "needs_review", "pending_review", "manual_review", "exception"
    ))
    auto_routed = bool(final) and (
        str(doc.get("automation_decision") or "").lower() == "auto"
        or doc.get("auto_cleared") is True
    )

    decision_type = str(human.get("decision_type") or "").lower()
    if decision_type == "folder_correction":
        routing_status = "manual_override"
    elif decision_type == "folder_confirmation":
        routing_status = "human_confirmed"
    elif has_file_evidence and final:
        routing_status = "filed"
    elif final and auto_routed:
        routing_status = "auto_routed"
    elif final:
        routing_status = "assigned"
    elif needs_review:
        routing_status = "needs_review"
    elif suggested:
        routing_status = "suggested"
    else:
        routing_status = "unrouted"

    return {
        "routing_status": routing_status,
        "suggested_folder": suggested,
        "final_folder": final,
        "routing_reason": reason,
        "routing_source": source,
        "suggested_at": suggested_at,
        "suggestion_capture": suggestion_capture,
        "suggestion_is_historical": (
            suggestion_capture != "computed_current_rule" and bool(suggested)
        ),
        "suggestion_matches_final": _folders_equivalent(suggested, final),
        "filed": bool(has_file_evidence and final),
        "auto_routed": auto_routed,
        "needs_review": needs_review,
    }


def _row(doc: Dict[str, Any]) -> Dict[str, Any]:
    routing = _routing_values(doc)
    source_identity = _source_identity(doc)
    doc_type = str(_first_nonempty(
        doc.get("document_type"),
        doc.get("doc_type"),
        doc.get("suggested_job_type"),
        "Unknown",
    ))
    explicit_mailbox = _first_nonempty(
        doc.get("pilot_mailbox"),
        doc.get("source_mailbox"),
        doc.get("mailbox_address"),
        doc.get("intake_mailbox"),
        doc.get("email_recipient"),
    )
    lane = _lane_for_document(doc)
    inferred_mailbox = {
        "AP": "hub-ap-intake@gamerpackaging.com",
        "Warehouse": "whdocuments@gamerpackaging.com",
        "Sales": "hub-sales-intake@gamerpackaging.com",
    }.get(lane, str(_first_nonempty(doc.get("mailbox_category"), doc.get("source"))))
    mailbox = str(explicit_mailbox or inferred_mailbox or "")
    received_utc = str(_first_nonempty(
        doc.get("received_utc"), doc.get("created_utc"), doc.get("updated_utc")
    ))

    return {
        "id": doc.get("id", ""),
        "file_name": doc.get("file_name") or "Unnamed",
        "received_utc": received_utc,
        "received_local": _local_iso(received_utc),
        "mailbox": mailbox,
        "mailbox_inferred": not bool(explicit_mailbox),
        "source": doc.get("source") or "",
        "sender": _first_nonempty(doc.get("email_sender"), doc.get("sender")),
        "subject": doc.get("email_subject") or "",
        "lane": lane,
        "classification": doc_type,
        "classification_method": doc.get("classification_method") or "",
        "confidence_pct": _as_confidence_pct(doc.get("ai_confidence")),
        "status": doc.get("status") or "",
        "workflow_status": doc.get("workflow_status") or "",
        "square9_stage": doc.get("square9_stage") or "",
        "vendor_or_customer": _first_nonempty(
            doc.get("vendor_canonical"), doc.get("vendor_raw"), doc.get("customer_name")
        ),
        "is_duplicate": doc.get("is_duplicate") is True,
        "possible_duplicate": doc.get("possible_duplicate") is True,
        "source_part_number": doc.get("batch_group_num"),
        "source_pages": doc.get("batch_pages") or [],
        "source_output_count": 1,
        **source_identity,
        **routing,
    }


def _attach_source_counts(rows: list[Dict[str, Any]]) -> None:
    counts = Counter(row.get("source_file_key") for row in rows)
    for row in rows:
        row["source_output_count"] = counts.get(row.get("source_file_key"), 1)


def _count(rows: Iterable[Dict[str, Any]], key: str, value: Any) -> int:
    return sum(1 for row in rows if row.get(key) == value)


def _summary(rows: list[Dict[str, Any]]) -> Dict[str, int]:
    source_counts = Counter(row.get("source_file_key") for row in rows)
    return {
        "total": len(rows),
        "produced_documents": len(rows),
        "source_files": len(source_counts),
        "split_outputs": sum(1 for row in rows if row.get("is_split_output") is True),
        "multi_output_sources": sum(1 for count in source_counts.values() if count > 1),
        "ap": _count(rows, "lane", "AP"),
        "warehouse": _count(rows, "lane", "Warehouse"),
        "sales": _count(rows, "lane", "Sales"),
        "other": _count(rows, "lane", "Other"),
        "auto_routed": sum(1 for row in rows if row.get("auto_routed") is True),
        "needs_review": sum(1 for row in rows if row.get("needs_review") is True),
        "unrouted": _count(rows, "routing_status", "unrouted"),
        "filed": sum(1 for row in rows if row.get("filed") is True),
        "suggestion_matches_final": sum(
            1 for row in rows if row.get("suggestion_matches_final") is True
        ),
    }


@router.get("/inbox-today")
async def get_inbox_today(
    lane: str = Query("all", description="all, ap, warehouse, sales, or other"),
    routing_status: str = Query("all", description="Optional routing-status filter"),
    limit: int = Query(1000, ge=1, le=5000),
):
    db = get_db()
    docs = await db.hub_documents.find(
        build_today_filter(), TODAY_PROJECTION
    ).sort("created_utc", -1).to_list(None)

    for doc in docs:
        await _normalize_stored_suggestion(db, doc)
    for doc in docs:
        await _add_current_rule_suggestion(doc)

    rows = [_row(doc) for doc in docs]
    _attach_source_counts(rows)

    normalized_lane = lane.strip().lower()
    normalized_routing = routing_status.strip().lower()
    filtered = rows
    if normalized_lane != "all":
        filtered = [
            row for row in filtered if row.get("lane", "").lower() == normalized_lane
        ]
    if normalized_routing != "all":
        filtered = [
            row for row in filtered
            if row.get("routing_status", "").lower() == normalized_routing
        ]

    now_ct = datetime.now(GPI_TZ)
    summary = _summary(rows)
    filtered_summary = _summary(filtered)
    return {
        "date": now_ct.date().isoformat(),
        "timezone": GPI_TIMEZONE_NAME,
        "total": len(rows),
        "source_files_total": summary["source_files"],
        "filtered_total": len(filtered),
        "truncated": len(filtered) > limit,
        "summary": summary,
        "filtered_summary": filtered_summary,
        "documents": filtered[:limit],
    }
