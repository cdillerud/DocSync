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
                "note": "No direct action exists yet for confirming/rejecting a "
                        "match itself - informational only. If the underlying "
                        "document's own doc_type or routing is actually wrong, "
                        "that can still be corrected via bulk-classify.",
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
                "note": "Informational only - this is a Square9 data-quality "
                        "observation, not a Hub classification or routing gap.",
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

        disposed_documents = await db.hub_documents.find(
            {
                "id": {"$in": doc_ids},
                "$or": [
                    {"non_transactional": True},
                    {"excluded_from_processing": True},
                ],
            },
            {
                "_id": 0,
                "id": 1,
            },
        ).to_list(len(doc_ids))

        disposed_ids = {
            document.get("id")
            for document in disposed_documents
            if document.get("id")
        }

        items = filter_dispositioned_items(
            items,
            disposed_ids,
        )

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
