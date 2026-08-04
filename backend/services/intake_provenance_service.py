"""Persist truthful mailbox provenance outside canonical raw-bytes intake.

The canonical ``intake_document_from_bytes`` body is protected by historical
parity fixtures. Mailbox provenance is therefore attached immediately after
successful intake rather than changing that function's signature or body.
"""

from __future__ import annotations

from typing import Any, Dict, Mapping, Optional


PROVENANCE_FIELDS = (
    "source_mailbox",
    "source_mailbox_id",
    "source_lane",
    "original_mailbox_category",
    "routing_override_applied",
    "routing_override_from",
    "routing_override_to",
)


def _clean_text(value: Any) -> Optional[str]:
    if value is None:
        return None

    cleaned = str(value).strip()
    return cleaned or None


def build_intake_provenance_fields(
    *,
    source_mailbox: Any,
    source_mailbox_id: Any = None,
    source_lane: Any,
    mailbox_category: Any,
    routing_override_applied: bool = False,
) -> Dict[str, Any]:
    """Build the flat provenance fields consumed by Decision Queue hydration."""

    actual_mailbox = _clean_text(source_mailbox)
    actual_source_id = _clean_text(source_mailbox_id)
    original_lane = _clean_text(source_lane)
    final_lane = _clean_text(mailbox_category)

    override_applied = bool(
        routing_override_applied
        and original_lane
        and final_lane
        and original_lane != final_lane
    )

    fields: Dict[str, Any] = {
        "source_mailbox": actual_mailbox,
        "source_mailbox_id": actual_source_id,
        "source_lane": original_lane,
        "original_mailbox_category": original_lane,
        "routing_override_applied": override_applied,
        "routing_override_from": (
            original_lane if override_applied else None
        ),
        "routing_override_to": (
            final_lane if override_applied else None
        ),
    }

    if final_lane:
        fields["mailbox_category"] = final_lane

    return fields


def intake_result_document_id(
    intake_result: Mapping[str, Any],
) -> Optional[str]:
    """Extract a document ID from either supported intake return shape."""

    document = intake_result.get("document") or {}

    return _clean_text(
        intake_result.get("document_id")
        or document.get("id")
    )


async def persist_intake_provenance(
    db,
    intake_result: Mapping[str, Any],
    *,
    source_mailbox: Any,
    source_mailbox_id: Any = None,
    source_lane: Any,
    mailbox_category: Any,
    routing_override_applied: bool = False,
    email_id: Any = None,
) -> Dict[str, Any]:
    """Attach provenance to a newly ingested document.

    A duplicate result may only fill missing provenance when it points to the
    same original email ID. A later delivery of identical content through a
    different mailbox must never rewrite the original document's provenance.
    """

    document_id = intake_result_document_id(intake_result)

    if not document_id:
        return {
            "updated": False,
            "reason": "missing_document_id",
        }

    fields = build_intake_provenance_fields(
        source_mailbox=source_mailbox,
        source_mailbox_id=source_mailbox_id,
        source_lane=source_lane,
        mailbox_category=mailbox_category,
        routing_override_applied=routing_override_applied,
    )

    query: Dict[str, Any] = {"id": document_id}

    if intake_result.get("skipped_duplicate"):
        original_email_id = _clean_text(email_id)

        if not original_email_id:
            return {
                "updated": False,
                "document_id": document_id,
                "reason": "duplicate_without_email_identity",
            }

        query.update(
            {
                "email_id": original_email_id,
                "$or": [
                    {"source_mailbox": {"$exists": False}},
                    {"source_mailbox": None},
                    {"source_mailbox": ""},
                ],
            }
        )

    result = await db.hub_documents.update_one(
        query,
        {"$set": fields},
    )

    matched_count = int(
        getattr(result, "matched_count", 0) or 0
    )

    return {
        "updated": matched_count > 0,
        "document_id": document_id,
        "duplicate_result": bool(
            intake_result.get("skipped_duplicate")
        ),
        "matched_count": matched_count,
    }


def inherit_intake_provenance(
    parent_document: Mapping[str, Any],
) -> Dict[str, Any]:
    """Copy only persisted provenance fields from a split parent."""

    return {
        field: parent_document.get(field)
        for field in PROVENANCE_FIELDS
        if field in parent_document
    }
