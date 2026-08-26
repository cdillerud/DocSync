"""Mailbox/message provenance persistence for authoritative document intake.

The first observed intake source is immutable. Later observations (including
content-hash duplicates, forwards, split-parent inheritance, or replays) are
appended without replacing original provenance. This gives AP/Warehouse cutover
reconciliation both a canonical origin and a complete observed-source history.
"""

from datetime import datetime, timezone
from typing import Optional


def _clean(value: Optional[str]) -> Optional[str]:
    if value is None:
        return None
    text = str(value).strip()
    return text or None


async def persist_mailbox_provenance(
    db,
    document_id: str,
    *,
    mailbox_address: Optional[str],
    mailbox_id: Optional[str] = None,
    mailbox_category: Optional[str] = None,
    graph_message_id: Optional[str] = None,
    internet_message_id: Optional[str] = None,
    attachment_id: Optional[str] = None,
    source: Optional[str] = None,
    set_first_seen: bool = True,
) -> dict:
    """Persist immutable first-seen provenance plus append-only observations.

    Existing canonical source fields are never overwritten. ``set_first_seen``
    may be disabled when an already-existing canonical document is merely being
    observed through another parent/replay path; in that mode only the
    observation history is appended.
    """
    if not document_id:
        return {"updated": False, "reason": "missing_document_id"}

    now = datetime.now(timezone.utc).isoformat()
    address = _clean(mailbox_address)
    source_id = _clean(mailbox_id)
    category = _clean(mailbox_category)
    graph_id = _clean(graph_message_id)
    internet_id = _clean(internet_message_id)
    attachment = _clean(attachment_id)
    source_name = _clean(source)

    observation = {
        "observed_utc": now,
        "mailbox_address": address,
        "mailbox_id": source_id,
        "mailbox_category": category,
        "graph_message_id": graph_id,
        "internet_message_id": internet_id,
        "attachment_id": attachment,
        "source": source_name,
    }
    observation = {k: v for k, v in observation.items() if v is not None}

    existing = await db.hub_documents.find_one(
        {"id": document_id},
        {
            "_id": 0,
            "source_mailbox_address": 1,
            "source_mailbox_id": 1,
            "source_mailbox_category": 1,
            "source_graph_message_id": 1,
            "source_internet_message_id": 1,
            "source_attachment_id": 1,
            "source_provenance_captured_utc": 1,
        },
    )
    if not existing:
        return {"updated": False, "reason": "document_not_found"}

    first_seen = {}
    canonical = {
        "source_mailbox_address": address,
        "source_mailbox_id": source_id,
        "source_mailbox_category": category,
        "source_graph_message_id": graph_id,
        "source_internet_message_id": internet_id,
        "source_attachment_id": attachment,
        "source_provenance_captured_utc": now,
    }
    if set_first_seen:
        for field, value in canonical.items():
            if value is not None and not existing.get(field):
                first_seen[field] = value

    update = {
        "$push": {"provenance_observations": observation},
        "$set": {"updated_utc": now},
    }
    if first_seen:
        update["$set"].update(first_seen)

    await db.hub_documents.update_one({"id": document_id}, update)
    return {
        "updated": True,
        "first_seen_fields_written": sorted(first_seen.keys()),
        "observation": observation,
        "set_first_seen": bool(set_first_seen),
    }


__all__ = ["persist_mailbox_provenance"]
