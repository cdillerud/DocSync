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
    "routing_preupload_checked_at": 1,
    "routing_preupload_recheck": 1,
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
_FOLDER_SLASH_RE = re.compile(r"/+")

# The snapshot stores a path relative to the SharePoint staging root. Other
# writers may store either the full production path or only the staging tail.
_KNOWN_SHAREPOINT_BASES = (
    "general/accounting/accounts payable/temp folder",
    "temp folder",
)
_BASE_FOLDER_DISPLAY = "Temp Folder"
_NON_COMPARABLE_CAPTURE_TYPES = {
    "routing_gate_snapshot",
    "post_filing_routing_gate",
}


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


def _normalized_folder_path(value: Any) -> str:
    path = str(value or "").replace("\\", "/").strip()
    return _FOLDER_SLASH_RE.sub("/", path).strip("/").casefold()


def _is_known_base_folder(value: Any) -> bool:
    return _normalized_folder_path(value) in _KNOWN_SHAREPOINT_BASES


def _folder_comparison_key(value: Any) -> str:
    """Normalize relative and SharePoint-prefixed folder paths for comparison."""
    path = _normalized_folder_path(value)
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

    if suggested_key or final_key:
        return bool(suggested_key and final_key and suggested_key == final_key)

    # Empty relative folder means "use the configured SharePoint base folder."
    return _is_known_base_folder(suggested) and _is_known_base_folder(final)


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


def _snapshot_has_decision(snapshot: Any) -> bool:
    if not isinstance(snapshot, dict) or not snapshot:
        return False
    return (
        "folder_path" in snapshot
        or bool(snapshot.get("reason"))
        or bool(snapshot.get("source"))
    )


def _snapshot_capture_type(
    doc: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> str:
    capture_type = str(snapshot.get("capture_type") or "initial_snapshot")
    if capture_type != "pre_filing_routing":
        return capture_type

    origin = str(snapshot.get("capture_origin") or "")
    if origin in {"sharepoint_preupload_guard", "sharepoint_service"}:
        return "pre_filing_routing"
    if doc.get("routing_preupload_checked_at"):
        return "pre_filing_routing"

    # Legacy document_routing_service snapshots used the pre-filing label even
    # when the routing gate ran after SharePoint upload. Preserve the audit
    # record but do not present it as an initial recommendation.
    return "routing_gate_snapshot"


def _snapshot_display_folder(
    doc: Dict[str, Any],
    snapshot: Dict[str, Any],
) -> str:
    raw_folder = snapshot.get("folder_path")
    if raw_folder is not None and str(raw_folder).strip():
        return str(raw_folder).strip()

    if (
        "folder_path" in snapshot
        and _snapshot_capture_type(doc, snapshot) == "pre_filing_routing"
    ):
        return _BASE_FOLDER_DISPLAY
    return ""


def _has_stored_suggestion(doc: Dict[str, Any]) -> bool:
    snapshot = doc.get("routing_suggestion_snapshot")
    if _snapshot_has_decision(snapshot):
        return True

    human = doc.get("human_routing_decision") or {}
    return bool(_first_nonempty(
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


def _selected_suggestion(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Select one complete suggestion record without mixing provenance fields."""
    snapshot = doc.get("routing_suggestion_snapshot") or {}
    if _snapshot_has_decision(snapshot):
        return {
            "folder_path": _snapshot_display_folder(doc, snapshot),
            "reason": str(snapshot.get("reason") or ""),
            "source": str(snapshot.get("source") or ""),
            "suggested_at": str(snapshot.get("suggested_at") or ""),
            "capture_type": _snapshot_capture_type(doc, snapshot),
        }

    human = doc.get("human_routing_decision") or {}
    if human.get("suggested_folder"):
        return {
            "folder_path": str(human.get("suggested_folder")),
            "reason": str(human.get("suggested_reason") or ""),
            "source": str(human.get("source") or "human_routing_review"),
            "suggested_at": str(human.get("created_at") or ""),
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

    route_result = doc.get("route_result") or {}
    evidence = doc.get("routing_evidence") or {}
    stored_folder = _first_nonempty(
        doc.get("initial_suggested_folder"),
        doc.get("suggested_folder_path"),
        doc.get("suggested_folder"),
        route_result.get("suggested_folder"),
        route_result.get("folder_path"),
        evidence.get("suggested_folder"),
    )
    if stored_folder:
        return {
            "folder_path": str(stored_folder),
            "reason": str(_first_nonempty(
                doc.get("initial_routing_reason"),
                doc.get("routing_reason"),
                doc.get("folder_routing_reason"),
                route_result.get("reason"),
                evidence.get("reason"),
            )),
            "source": str(_first_nonempty(
                doc.get("initial_routing_source"),
                doc.get("routing_source"),
                route_result.get("source"),
                doc.get("sharepoint_folder_assigned_by"),
                "stored_routing_suggestion",
            )),
            "suggested_at": str(_first_nonempty(
                doc.get("initial_routing_suggested_at"),
                doc.get("routing_suggested_at"),
                doc.get("updated_utc"),
            )),
            "capture_type": "stored_suggestion",
        }

    display = doc.get("_display_suggestion") or {}
    if display.get("folder_path"):
        return {
            "folder_path": str(display.get("folder_path")),
            "reason": str(display.get("reason") or ""),
            "source": str(display.get("source") or "current_routing_rules"),
            "suggested_at": str(display.get("suggested_at") or ""),
            "capture_type": str(display.get("capture_type") or "computed_current_rule"),
        }

    return {}


def _routing_values(doc: Dict[str, Any]) -> Dict[str, Any]:
    human = doc.get("human_routing_decision") or {}
    suggestion = _selected_suggestion(doc)
    suggested = str(suggestion.get("folder_path") or "")
    final = str(_first_nonempty(
        doc.get("sharepoint_folder_path"),
        doc.get("sharepoint_folder"),
        doc.get("filed_folder"),
        doc.get("filed_to"),
        human.get("selected_folder"),
    ))
    suggestion_capture = str(suggestion.get("capture_type") or "")

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

    comparable = bool(suggested and final) and (
        suggestion_capture not in _NON_COMPARABLE_CAPTURE_TYPES
    )
    matches_final: Optional[bool]
    if comparable:
        matches_final = _folders_equivalent(suggested, final)
    else:
        matches_final = None

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
        "routing_reason": str(suggestion.get("reason") or ""),
        "routing_source": str(suggestion.get("source") or ""),
        "suggested_at": str(suggestion.get("suggested_at") or ""),
        "suggestion_capture": suggestion_capture,
        "suggestion_is_historical": (
            suggestion_capture != "computed_current_rule" and bool(suggestion)
        ),
        "suggestion_is_pre_filing": suggestion_capture == "pre_filing_routing",
        "suggestion_comparable": comparable,
        "suggestion_matches_final": matches_final,
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
    pre_filing = [
        row for row in rows if row.get("suggestion_capture") == "pre_filing_routing"
    ]
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
        "suggestion_comparable": sum(
            1 for row in rows if row.get("suggestion_comparable") is True
        ),
        "suggestion_matches_final": sum(
            1 for row in rows if row.get("suggestion_matches_final") is True
        ),
        "suggestion_mismatches_final": sum(
            1 for row in rows if row.get("suggestion_matches_final") is False
        ),
        "pre_filing_snapshots": len(pre_filing),
        "pre_filing_matches": sum(
            1 for row in pre_filing if row.get("suggestion_matches_final") is True
        ),
        "pre_filing_mismatches": sum(
            1 for row in pre_filing if row.get("suggestion_matches_final") is False
        ),
        "routing_gate_snapshots": sum(
            1 for row in rows if row.get("suggestion_capture") == "routing_gate_snapshot"
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
