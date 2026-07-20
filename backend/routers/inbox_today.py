"""Daily Inbox drill-down for Square9 replacement verification.

The endpoint intentionally uses the same local-day boundary and batch-parent
exclusion as ``GET /dashboard/inbox-stats`` so the modal total tracks the
Inbox "Today" KPI.
"""

from __future__ import annotations

from datetime import datetime, timezone
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
    "filed_at": 1,
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


def build_today_filter(now: Optional[datetime] = None) -> Dict[str, Any]:
    """Return the exact query shape used by the Inbox Today KPI."""
    now_ct = (now or datetime.now(GPI_TZ)).astimezone(GPI_TZ)
    today_start = now_ct.replace(hour=0, minute=0, second=0, microsecond=0)
    today_start_utc = today_start.astimezone(timezone.utc).isoformat()
    return {
        "created_utc": {"$gte": today_start_utc},
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

    doc_type = str(
        _first_nonempty(
            doc.get("document_type"),
            doc.get("doc_type"),
            doc.get("suggested_job_type"),
        )
    ).lower()
    if any(token in doc_type for token in ("warehouse", "shipping", "shipment", "packing", "bill_of_lading", "bol")):
        return "Warehouse"
    if any(token in doc_type for token in ("sales", "customer_po", "customer po", "order_confirmation")):
        return "Sales"
    if any(token in doc_type for token in ("ap", "purchase", "invoice", "credit", "remittance", "freight")):
        return "AP"
    return "Other"


def _routing_values(doc: Dict[str, Any]) -> Dict[str, Any]:
    human = doc.get("human_routing_decision") or {}
    route_result = doc.get("route_result") or {}
    evidence = doc.get("routing_evidence") or {}

    suggested = str(
        _first_nonempty(
            human.get("suggested_folder"),
            doc.get("suggested_folder_path"),
            doc.get("suggested_folder"),
            route_result.get("suggested_folder"),
            route_result.get("folder_path"),
            evidence.get("suggested_folder"),
        )
    )
    final = str(
        _first_nonempty(
            doc.get("sharepoint_folder_path"),
            doc.get("sharepoint_folder"),
            doc.get("filed_to"),
            human.get("selected_folder"),
        )
    )
    reason = str(
        _first_nonempty(
            human.get("suggested_reason"),
            doc.get("routing_reason"),
            doc.get("folder_routing_reason"),
            route_result.get("reason"),
            evidence.get("reason"),
        )
    )
    source = str(
        _first_nonempty(
            doc.get("sharepoint_folder_assigned_by"),
            human.get("source"),
            doc.get("routing_source"),
            route_result.get("source"),
        )
    )

    status_text = f"{doc.get('status', '')} {doc.get('workflow_status', '')}".lower()
    has_file_evidence = bool(
        _first_nonempty(
            doc.get("sharepoint_item_id"),
            doc.get("sharepoint_web_url"),
            doc.get("filed_at"),
        )
    ) or any(token in status_text for token in ("filed", "storedinsp", "exported"))
    needs_review = any(
        token in status_text
        for token in ("needsreview", "needs_review", "pending_review", "manual_review", "exception")
    )
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
        "filed": bool(has_file_evidence and final),
        "auto_routed": auto_routed,
        "needs_review": needs_review,
    }


def _row(doc: Dict[str, Any]) -> Dict[str, Any]:
    routing = _routing_values(doc)
    doc_type = str(
        _first_nonempty(
            doc.get("document_type"),
            doc.get("doc_type"),
            doc.get("suggested_job_type"),
            "Unknown",
        )
    )
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
    received_utc = str(
        _first_nonempty(doc.get("received_utc"), doc.get("created_utc"), doc.get("updated_utc"))
    )

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
        **routing,
    }


def _count(rows: Iterable[Dict[str, Any]], key: str, value: Any) -> int:
    return sum(1 for row in rows if row.get(key) == value)


def _summary(rows: list[Dict[str, Any]]) -> Dict[str, int]:
    return {
        "total": len(rows),
        "ap": _count(rows, "lane", "AP"),
        "warehouse": _count(rows, "lane", "Warehouse"),
        "sales": _count(rows, "lane", "Sales"),
        "other": _count(rows, "lane", "Other"),
        "auto_routed": sum(1 for row in rows if row.get("auto_routed") is True),
        "needs_review": sum(1 for row in rows if row.get("needs_review") is True),
        "unrouted": _count(rows, "routing_status", "unrouted"),
        "filed": sum(1 for row in rows if row.get("filed") is True),
    }


@router.get("/inbox-today")
async def get_inbox_today(
    lane: str = Query("all", description="all, ap, warehouse, sales, or other"),
    routing_status: str = Query("all", description="Optional routing-status filter"),
    limit: int = Query(1000, ge=1, le=5000),
):
    """Return today's documents with classification and routing evidence."""
    db = get_db()
    today_filter = build_today_filter()
    docs = await db.hub_documents.find(today_filter, TODAY_PROJECTION).sort("created_utc", -1).to_list(None)
    rows = [_row(doc) for doc in docs]

    normalized_lane = lane.strip().lower()
    normalized_routing = routing_status.strip().lower()
    filtered = rows
    if normalized_lane != "all":
        filtered = [row for row in filtered if row.get("lane", "").lower() == normalized_lane]
    if normalized_routing != "all":
        filtered = [
            row
            for row in filtered
            if row.get("routing_status", "").lower() == normalized_routing
        ]

    now_ct = datetime.now(GPI_TZ)
    return {
        "date": now_ct.date().isoformat(),
        "timezone": GPI_TIMEZONE_NAME,
        "total": len(rows),
        "filtered_total": len(filtered),
        "truncated": len(filtered) > limit,
        "summary": _summary(rows),
        "filtered_summary": _summary(filtered),
        "documents": filtered[:limit],
    }
