"""Build and reconcile the human Decision Queue.

The queue combines historical Square9 analysis with live Hub state.
Document classification feedback may be learned from a correction, but
routing-lane changes remain document-scoped unless sender-wide learning
is requested through a separate explicit workflow.
"""

from __future__ import annotations

import csv
import os
import re
from typing import Any, Dict, List, Optional

from deps import get_db
from services.decision_queue_confirmation_service import (
    confirmation_matches_current_state,
    current_document_state,
)

BUCKET_A_CSV = "prod_reports/bucket_A_root_cause.csv"
AMBIGUOUS_LABELS_CSV = "prod_reports/manual_folder_labels_ambiguous.csv"

FOLDER_LABEL_CANDIDATES: Dict[str, List[str]] = {
    "wh not international": ["Shipping_Document", "Warehouse_Receipt"],
    "ds not international": ["Shipping_Document", "Warehouse_Receipt"],
    "ds internanational": ["Shipping_Document", "Warehouse_Receipt"],
    "ds international": ["Shipping_Document", "Warehouse_Receipt"],
}

BUSINESS_MAILBOX_ALIASES = {
    "hub-ap-intake@gamerpackaging.com": "billing@gamerpackaging.com",
}

ROOT_CAUSE_SOURCE_LANES = {
    "operations_mailbox_captured_AP_invoice": "Operations",
    "sales_mailbox_captured_AP_invoice": "Sales",
}

ACTIONABLE_MISROUTE_CAUSES = {
    "operations_mailbox_captured_AP_invoice",
    "sales_mailbox_captured_AP_invoice",
}

CLEARLY_NON_AP_DOCUMENT_TYPES = {
    "bill_of_lading",
    "bol",
    "delivery_receipt",
    "ds_sales_order",
    "graphics_artwork",
    "order_confirmation",
    "packing_list",
    "purchase_order",
    "quality_document",
    "sales_order",
    "shipping_document",
    "warehouse_receipt",
    "wh_sales_order",
}


def _display_mailbox_address(address: Optional[str]) -> str:
    normalized = (address or "").strip()
    if not normalized:
        return ""
    return BUSINESS_MAILBOX_ALIASES.get(
        normalized.lower(),
        normalized,
    )


async def _load_source_mailboxes_by_lane(db) -> Dict[str, str]:
    """Resolve active intake mailboxes by configured lane."""
    result: Dict[str, str] = {}

    sources = await db.mailbox_sources.find(
        {"enabled": {"$ne": False}},
        {
            "_id": 0,
            "mailbox_address": 1,
            "email_address": 1,
            "address": 1,
            "mailbox": 1,
            "default_category": 1,
            "mailbox_category": 1,
            "category": 1,
            "lane": 1,
        },
    ).to_list(100)

    for source in sources:
        address = (
            source.get("mailbox_address")
            or source.get("email_address")
            or source.get("address")
            or source.get("mailbox")
            or ""
        )
        lane = (
            source.get("default_category")
            or source.get("mailbox_category")
            or source.get("category")
            or source.get("lane")
            or ""
        )
        lane = str(lane).strip()
        if lane and address:
            result[lane] = _display_mailbox_address(str(address))

    environment_sources = (
        ("AP", "EMAIL_POLLING_ENABLED", "EMAIL_POLLING_USER"),
        (
            "Sales",
            "SALES_EMAIL_POLLING_ENABLED",
            "SALES_EMAIL_POLLING_USER",
        ),
    )

    for lane, enabled_variable, address_variable in environment_sources:
        enabled = os.getenv(enabled_variable, "").strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }
        address = os.getenv(address_variable, "").strip()
        if enabled and address:
            result[lane] = _display_mailbox_address(address)

    return result


def resolve_source_mailbox(
    item: Dict[str, Any],
    document: Dict[str, Any],
    source_mailboxes_by_lane: Dict[str, str],
) -> str:
    """Resolve original intake mailbox from provenance evidence only.

    A document's current ``mailbox_category`` is a routing lane, not proof
    of which mailbox received it. Never translate the current lane into a
    mailbox address. When provenance was not persisted, return an empty
    value rather than presenting an inferred address as fact.
    """
    context = item.get("context") or {}

    explicit_address = (
        document.get("source_mailbox")
        or document.get("intake_mailbox")
        or document.get("mailbox_address")
        or document.get("email_recipient")
        or context.get("source_mailbox")
    )
    if explicit_address:
        return _display_mailbox_address(str(explicit_address))

    root_cause = str(context.get("root_cause") or "").strip()
    source_lane = (
        ROOT_CAUSE_SOURCE_LANES.get(root_cause)
        or document.get("original_mailbox_category")
        or context.get("source_mailbox_category")
        or ""
    )

    if not source_lane:
        return ""

    return source_mailboxes_by_lane.get(
        str(source_lane).strip(),
        "",
    )


def _document_type_key(value: Any) -> str:
    return re.sub(
        r"[^a-z0-9]+",
        "_",
        str(value or "").strip().lower(),
    ).strip("_")


def is_clearly_non_ap_document_type(document_type: Any) -> bool:
    return _document_type_key(document_type) in CLEARLY_NON_AP_DOCUMENT_TYPES


def reconcile_item_with_live_state(
    item: Dict[str, Any],
    document: Dict[str, Any],
) -> Dict[str, Any]:
    """Reconcile historical findings with the live document state."""
    if item.get("issue_type") != "isolated_misroute":
        return item

    context = item.setdefault("context", {})
    root_cause = str(context.get("root_cause") or "").strip()
    if root_cause not in ACTIONABLE_MISROUTE_CAUSES:
        return item

    current_state = item.get("current_state") or current_document_state(document)
    document_type = str(current_state.get("doc_type") or "").strip()
    current_lane = str(current_state.get("mailbox_category") or "").strip()

    if not is_clearly_non_ap_document_type(document_type):
        return item

    original_source_lane = ROOT_CAUSE_SOURCE_LANES.get(root_cause) or ""
    if (
        original_source_lane
        and current_lane
        and current_lane.lower() != original_source_lane.lower()
    ):
        return item

    original_question = item.get("question") or ""
    item["issue_type"] = "square9_side_issue"
    item["question"] = (
        "Historical Square9 analysis flagged this as a possible AP "
        "misroute, but the live Hub document is "
        f"{document_type or 'a non-AP document'} in "
        f"{current_lane or 'its current lane'}."
    )
    item["submit_via"] = None
    item["submit_hint"] = None
    item["note"] = (
        "The live Hub classification and lane indicate this is not an "
        "AP-routing correction. Acknowledge this historical observation "
        "without changing the document."
    )
    context["original_issue_type"] = "isolated_misroute"
    context["original_question"] = original_question
    context["live_state_reconciliation"] = "clearly_non_ap_document"
    return item


def _read_csv_rows(path: str) -> List[Dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as handle:
        return list(csv.DictReader(handle))


def _bucket_a_items() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    for row in _read_csv_rows(BUCKET_A_CSV):
        root_cause = (row.get("root_cause") or "").strip()
        doc_id = (row.get("best_hub_doc_id") or "").strip()
        if not doc_id:
            continue

        try:
            score = float(row.get("best_match_score") or 0.0)
        except ValueError:
            score = 0.0

        current_doc_type = row.get("best_hub_doc_type") or "Unknown"
        current_mailbox = row.get("best_hub_mailbox_category") or ""
        file_name = (
            row.get("best_hub_file_name")
            or row.get("square9_name")
            or ""
        )
        context = {
            "vendor_or_sender": row.get("email_sender") or "",
            "square9_name": row.get("square9_name") or "",
            "square9_parent_root": row.get("square9_parent_root") or "",
            "match_reason": row.get("best_match_reason") or "",
            "root_cause": root_cause,
        }

        if root_cause in ACTIONABLE_MISROUTE_CAUSES:
            items.append(
                {
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "issue_type": "isolated_misroute",
                    "question": (
                        "Should this be routed to AP? "
                        f"(currently: {current_mailbox or 'unset'})"
                    ),
                    "ai_confidence": score,
                    "current_state": {
                        "doc_type": current_doc_type,
                        "mailbox_category": current_mailbox,
                    },
                    "candidates": None,
                    "context": context,
                    "submit_via": "bulk-classify",
                    "submit_hint": {
                        "doc_ids": [doc_id],
                        "doc_type": current_doc_type,
                        "mailbox_category": "AP",
                    },
                    "source": "bucket_A_root_cause",
                }
            )
        elif root_cause == "low_confidence_match_ambiguous":
            items.append(
                {
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "issue_type": "ambiguous_match",
                    "question": (
                        "Is this Hub document actually the same document "
                        "as the named Square9 file?"
                    ),
                    "ai_confidence": score,
                    "current_state": {
                        "doc_type": current_doc_type,
                        "mailbox_category": current_mailbox,
                    },
                    "candidates": None,
                    "context": context,
                    "submit_via": None,
                    "submit_hint": None,
                    "note": (
                        "Choose whether the Hub document and the listed "
                        "Square9 candidate are the same document, different "
                        "documents, or unable to determine. This decision "
                        "does not change classification or routing."
                    ),
                    "source": "bucket_A_root_cause",
                }
            )
        elif root_cause == "square9_ap_folder_contains_non_ap_document":
            items.append(
                {
                    "doc_id": doc_id,
                    "file_name": file_name,
                    "issue_type": "square9_side_issue",
                    "question": (
                        "Square9's own AP folder contains a document that "
                        "doesn't look like an AP invoice, which is not "
                        "correctable from the Hub side."
                    ),
                    "ai_confidence": score,
                    "current_state": {
                        "doc_type": current_doc_type,
                        "mailbox_category": current_mailbox,
                    },
                    "candidates": None,
                    "context": context,
                    "submit_via": None,
                    "submit_hint": None,
                    "note": (
                        "This is a Square9-only data-quality observation. "
                        "Acknowledge it to resolve the queue issue without "
                        "changing the Hub document."
                    ),
                    "source": "bucket_A_root_cause",
                }
            )

    return items


def _ambiguous_folder_label_items() -> List[Dict[str, Any]]:
    items: List[Dict[str, Any]] = []

    for row in _read_csv_rows(AMBIGUOUS_LABELS_CSV):
        doc_id = (row.get("doc_id") or "").strip()
        if not doc_id:
            continue

        label = (row.get("folder_label") or "").strip()
        candidates = FOLDER_LABEL_CANDIDATES.get(label.lower(), [])
        candidate_text = ", ".join(candidates)

        items.append(
            {
                "doc_id": doc_id,
                "file_name": row.get("file_name") or "",
                "issue_type": "ambiguous_classification",
                "question": (
                    f"Meghan's team tagged this '{label}', which specific "
                    "type is it?"
                ),
                "ai_confidence": None,
                "current_state": {
                    "doc_type": row.get("current_doc_type") or "OTHER"
                },
                "candidates": candidates,
                "context": {
                    "vendor_or_sender": (
                        row.get("email_sender")
                        or row.get("vendor_raw")
                        or ""
                    ),
                    "folder_label": label,
                },
                "submit_via": "bulk-classify",
                "submit_hint": {
                    "doc_ids": [doc_id],
                    "doc_type": (
                        f"<pick one of: {candidate_text}>"
                        if candidates
                        else "<unknown - review manually>"
                    ),
                },
                "source": "manual_folder_label",
            }
        )

    return items


def filter_dispositioned_items(
    items: List[Dict[str, Any]],
    dispositioned_ids: set,
) -> List[Dict[str, Any]]:
    """Remove documents already marked non-transactional."""
    return [
        item
        for item in items
        if item.get("doc_id") not in dispositioned_ids
    ]


async def get_human_review_queue() -> Dict[str, Any]:
    """Return unresolved decisions, excluding dispositioned documents."""
    items = _bucket_a_items() + _ambiguous_folder_label_items()
    doc_ids = sorted(
        {
            item.get("doc_id")
            for item in items
            if item.get("doc_id")
        }
    )

    if doc_ids:
        db = get_db()
        source_mailboxes_by_lane = await _load_source_mailboxes_by_lane(db)
        documents = await db.hub_documents.find(
            {"id": {"$in": doc_ids}},
            {
                "_id": 0,
                "id": 1,
                "file_name": 1,
                "doc_type": 1,
                "document_type": 1,
                "suggested_job_type": 1,
                "mailbox_category": 1,
                "original_mailbox_category": 1,
                "source_mailbox": 1,
                "source_mailbox_id": 1,
                "source_lane": 1,
                "intake_mailbox": 1,
                "mailbox_address": 1,
                "email_recipient": 1,
                "email_sender": 1,
                "vendor_raw": 1,
                "vendor_canonical": 1,
                "non_transactional": 1,
                "excluded_from_processing": 1,
                "decision_queue_confirmation": 1,
                "decision_queue_confirmations": 1,
            },
        ).to_list(len(doc_ids))
        documents_by_id = {
            document.get("id"): document
            for document in documents
            if document.get("id")
        }
        hydrated_items = []

        for item in items:
            document = documents_by_id.get(item.get("doc_id"))
            if not document:
                hydrated_items.append(item)
                continue

            if (
                document.get("non_transactional") is True
                or document.get("excluded_from_processing") is True
            ):
                continue

            item["current_state"] = {
                **(item.get("current_state") or {}),
                **current_document_state(document),
            }
            item["current_state"]["source_mailbox"] = (
                resolve_source_mailbox(
                    item,
                    document,
                    source_mailboxes_by_lane,
                )
            )
            item = reconcile_item_with_live_state(item, document)

            if document.get("file_name"):
                item["file_name"] = document["file_name"]

            context = item.setdefault("context", {})
            if not context.get("vendor_or_sender"):
                context["vendor_or_sender"] = (
                    document.get("email_sender")
                    or document.get("vendor_raw")
                    or document.get("vendor_canonical")
                    or ""
                )

            if confirmation_matches_current_state(
                document,
                item.get("issue_type", ""),
            ):
                continue

            hydrated_items.append(item)

        items = hydrated_items

    by_type: Dict[str, int] = {}
    actionable_count = 0

    for item in items:
        issue_type = item["issue_type"]
        by_type[issue_type] = by_type.get(issue_type, 0) + 1
        if item.get("submit_via"):
            actionable_count += 1

    return {
        "total_items": len(items),
        "actionable_count": actionable_count,
        "informational_only_count": len(items) - actionable_count,
        "counts_by_issue_type": by_type,
        "items": items,
    }
