"""
human_review_queue_service.py
===============================
Unifies documents that genuinely need a human decision - across
different root causes that have accumulated separate, disconnected
diagnostics tonight (Bucket A root-cause analysis, Meghan's ambiguous
folder-tag labels) - into one clean, consistently-shaped feed a
reviewer (or a future UI) can work through.

Why this exists: Square9's own answer to ambiguity is a folder called
"Miscellaneous" that a human has to remember to go check, with no
structure, no AI suggestion, and nothing learned from the decision
once made. Hub already exceeds that baseline - /bulk-classify makes
any human correction teach the system automatically (see the routing-
learning-loop work earlier tonight) - but nothing actively SURFACES
what needs a decision; a reviewer would have to already know to go
looking in scattered CSV files. This closes that gap.

Two genuinely different kinds of item, both honestly labeled rather
than blurred together:

1. Items with a clear, already-working submit path: isolated,
   below-threshold misroutes and ambiguous doc_type labels. Both
   resolve via the same /bulk-classify action already proven tonight
   - correcting either field automatically teaches the system.

2. Items with NO submit path yet: Bucket A's low_confidence_match_
   ambiguous cases are a genuinely different kind of question ("is
   this Hub document actually the same document as this Square9
   document?") that nothing in this codebase - not tonight's work,
   not any endpoint found while searching for one - currently lets a
   human answer directly. These are still surfaced (visibility is
   itself valuable), but explicitly marked as informational only
   rather than implying a submit path that doesn't exist.
"""

from __future__ import annotations

import csv
import os
from typing import Any, Dict, List, Optional

from deps import get_db
from services.decision_queue_confirmation_service import (
    confirmation_matches_current_state,
    current_document_state,
)

BUCKET_A_CSV = "prod_reports/bucket_A_root_cause.csv"
AMBIGUOUS_LABELS_CSV = "prod_reports/manual_folder_labels_ambiguous.csv"

# Mirrors AMBIGUOUS_LABELS in ingest_manual_folder_labels.py - kept as
# a local copy rather than importing across a scripts/services
# boundary, since scripts/ isn't meant to be imported by the live app.
FOLDER_LABEL_CANDIDATES: Dict[str, List[str]] = {
    "wh not international": ["Shipping_Document", "Warehouse_Receipt"],
    "ds not international": ["Shipping_Document", "Warehouse_Receipt"],
    "ds internanational": ["Shipping_Document", "Warehouse_Receipt"],
    "ds international": ["Shipping_Document", "Warehouse_Receipt"],
}

BUSINESS_MAILBOX_ALIASES = {
    "hub-ap-intake@gamerpackaging.com": (
        "billing@gamerpackaging.com"
    ),
}

ROOT_CAUSE_SOURCE_LANES = {
    "operations_mailbox_captured_AP_invoice": (
        "Operations"
    ),
    "sales_mailbox_captured_AP_invoice": "Sales",
}


def _display_mailbox_address(
    address: Optional[str],
) -> str:
    normalized = (address or "").strip()

    if not normalized:
        return ""

    return BUSINESS_MAILBOX_ALIASES.get(
        normalized.lower(),
        normalized,
    )


async def _load_source_mailboxes_by_lane(
    db,
) -> Dict[str, str]:
    """Resolve currently active intake mailboxes by lane."""
    result: Dict[str, str] = {}

    sources = await db.mailbox_sources.find(
        {
            "enabled": {
                "$ne": False,
            },
        },
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
            result[lane] = _display_mailbox_address(
                str(address)
            )

    environment_sources = (
        (
            "AP",
            "EMAIL_POLLING_ENABLED",
            "EMAIL_POLLING_USER",
        ),
        (
            "Sales",
            "SALES_EMAIL_POLLING_ENABLED",
            "SALES_EMAIL_POLLING_USER",
        ),
    )

    for (
        lane,
        enabled_variable,
        address_variable,
    ) in environment_sources:
        enabled = os.getenv(
            enabled_variable,
            "",
        ).strip().lower() in {
            "1",
            "true",
            "yes",
            "on",
        }

        address = os.getenv(
            address_variable,
            "",
        ).strip()

        if enabled and address:
            result[lane] = _display_mailbox_address(
                address
            )

    return result


def resolve_source_mailbox(
    item: Dict[str, Any],
    document: Dict[str, Any],
    source_mailboxes_by_lane: Dict[str, str],
) -> str:
    """Resolve original intake mailbox without changing its lane."""
    context = item.get("context") or {}

    explicit_address = (
        document.get("source_mailbox")
        or document.get("intake_mailbox")
        or document.get("mailbox_address")
        or document.get("email_recipient")
        or context.get("source_mailbox")
    )

    if explicit_address:
        return _display_mailbox_address(
            str(explicit_address)
        )

    root_cause = (
        context.get("root_cause")
        or ""
    ).strip()

    source_lane = (
        ROOT_CAUSE_SOURCE_LANES.get(root_cause)
        or document.get(
            "original_mailbox_category"
        )
        or context.get(
            "source_mailbox_category"
        )
        or document.get("mailbox_category")
        or (
            item.get("current_state")
            or {}
        ).get("mailbox_category")
        or ""
    )

    return source_mailboxes_by_lane.get(
        str(source_lane).strip(),
        "",
    )


# root_cause values from bucket_A_root_cause_report.py that represent
# a real, isolated misroute a human can resolve with a single yes/no:
# "should this be mailbox_category=AP?" Excludes low_confidence_match_
# ambiguous (a different question - see module docstring) and
# square9_ap_folder_contains_non_ap_document (a Square9-side filing
# issue, not something correctable on the Hub side at all).
ACTIONABLE_MISROUTE_CAUSES = {
    "operations_mailbox_captured_AP_invoice",
    "sales_mailbox_captured_AP_invoice",
}


def _read_csv_rows(path: str) -> List[Dict[str, str]]:
    if not os.path.exists(path):
        return []
    with open(path, newline="", encoding="utf-8") as f:
        return list(csv.DictReader(f))


def _bucket_a_items() -> List[Dict[str, Any]]:
    rows = _read_csv_rows(BUCKET_A_CSV)
    items: List[Dict[str, Any]] = []

    for r in rows:
        root_cause = (r.get("root_cause") or "").strip()
        doc_id = (r.get("best_hub_doc_id") or "").strip()
        if not doc_id:
            continue

        try:
            score = float(r.get("best_match_score") or 0.0)
        except ValueError:
            score = 0.0

        current_doc_type = r.get("best_hub_doc_type") or "Unknown"
        current_mailbox = r.get("best_hub_mailbox_category") or ""
        file_name = r.get("best_hub_file_name") or r.get("square9_name") or ""

        context = {
            "vendor_or_sender": r.get("email_sender") or "",
            "square9_name": r.get("square9_name") or "",
            "square9_parent_root": r.get("square9_parent_root") or "",
            "match_reason": r.get("best_match_reason") or "",
            "root_cause": root_cause,
        }

        if root_cause in ACTIONABLE_MISROUTE_CAUSES:
            items.append({
                "doc_id": doc_id,
                "file_name": file_name,
                "issue_type": "isolated_misroute",
                "question": f"Should this be routed to AP? (currently: {current_mailbox or 'unset'})",
                "ai_confidence": score,
                "current_state": {"doc_type": current_doc_type, "mailbox_category": current_mailbox},
                "candidates": None,
                "context": context,
                "submit_via": "bulk-classify",
                "submit_hint": {
                    "doc_ids": [doc_id],
                    "doc_type": current_doc_type,
                    "mailbox_category": "AP",
                },
                "source": "bucket_A_root_cause",
            })
        elif root_cause == "low_confidence_match_ambiguous":
            items.append({
                "doc_id": doc_id,
                "file_name": file_name,
                "issue_type": "ambiguous_match",
                "question": "Is this Hub document actually the same document as the named Square9 file?",
                "ai_confidence": score,
                "current_state": {"doc_type": current_doc_type, "mailbox_category": current_mailbox},
                "candidates": None,
                "context": context,
                "submit_via": None,
                "submit_hint": None,
                "note": "Choose whether the Hub document and the listed "
                        "Square9 candidate are the same document, different "
                        "documents, or unable to determine. This decision does "
                        "not change classification or routing.",
                "source": "bucket_A_root_cause",
            })
        elif root_cause == "square9_ap_folder_contains_non_ap_document":
            items.append({
                "doc_id": doc_id,
                "file_name": file_name,
                "issue_type": "square9_side_issue",
                "question": "Square9's own AP folder contains a document that "
                             "doesn't look like an AP invoice - not something "
                             "correctable from the Hub side.",
                "ai_confidence": score,
                "current_state": {"doc_type": current_doc_type, "mailbox_category": current_mailbox},
                "candidates": None,
                "context": context,
                "submit_via": None,
                "submit_hint": None,
                "note": "This is a Square9-only data-quality observation. "
                        "Acknowledge it to resolve the queue issue without "
                        "changing the Hub document.",
                "source": "bucket_A_root_cause",
            })
        # "uncertain" and any other root_cause values are deliberately
        # excluded here rather than guessed at - genuinely unclear
        # cases without even a "isolated_misroute vs ambiguous_match"
        # classification aren't safe to present with a suggested action.

    return items


def _ambiguous_folder_label_items() -> List[Dict[str, Any]]:
    rows = _read_csv_rows(AMBIGUOUS_LABELS_CSV)
    items: List[Dict[str, Any]] = []

    for r in rows:
        doc_id = (r.get("doc_id") or "").strip()
        if not doc_id:
            continue

        label = (r.get("folder_label") or "").strip()
        candidates = FOLDER_LABEL_CANDIDATES.get(label.lower(), [])

        items.append({
            "doc_id": doc_id,
            "file_name": r.get("file_name") or "",
            "issue_type": "ambiguous_classification",
            "question": f"Meghan's team tagged this '{label}' - which specific "
                         f"type is it?",
            "ai_confidence": None,
            "current_state": {"doc_type": r.get("current_doc_type") or "OTHER"},
            "candidates": candidates,
            "context": {
                "vendor_or_sender": r.get("email_sender") or r.get("vendor_raw") or "",
                "folder_label": label,
            },
            "submit_via": "bulk-classify",
            "submit_hint": {
                "doc_ids": [doc_id],
                "doc_type": f"<pick one of: {', '.join(candidates)}>" if candidates else "<unknown - review manually>",
            },
            "source": "manual_folder_label",
        })

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

    doc_ids = sorted({
        item.get("doc_id")
        for item in items
        if item.get("doc_id")
    })

    if doc_ids:
        db = get_db()

        source_mailboxes_by_lane = (
            await _load_source_mailboxes_by_lane(db)
        )

        documents = await db.hub_documents.find(
            {
                "id": {"$in": doc_ids},
            },
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
            document = documents_by_id.get(
                item.get("doc_id")
            )

            if not document:
                hydrated_items.append(item)
                continue

            if (
                document.get("non_transactional")
                is True
                or document.get(
                    "excluded_from_processing"
                )
                is True
            ):
                continue

            item["current_state"] = {
                **(
                    item.get("current_state")
                    or {}
                ),
                **current_document_state(
                    document
                ),
            }

            item["current_state"][
                "source_mailbox"
            ] = resolve_source_mailbox(
                item,
                document,
                source_mailboxes_by_lane,
            )

            if document.get("file_name"):
                item["file_name"] = (
                    document["file_name"]
                )

            context = item.setdefault(
                "context",
                {},
            )

            if not context.get(
                "vendor_or_sender"
            ):
                context["vendor_or_sender"] = (
                    document.get("email_sender")
                    or document.get("vendor_raw")
                    or document.get(
                        "vendor_canonical"
                    )
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
        "informational_only_count": (
            len(items) - actionable_count
        ),
        "counts_by_issue_type": by_type,
        "items": items,
    }
