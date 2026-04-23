"""
GPI Hub — Inventory lineage primitives (Lane C Step 4)

Captures Gamer-owned inventory transformations: receive-to-hold and
release-from-hold events keyed by (so_ref, item_no). Produce & Hold is
the first consumer; Assembly Order will reuse these primitives in a
future step.

This module is UNWIRED foundation. Nothing in production calls these
functions yet. The declared collection ``inventory_lineage_events`` is
lazy-created on first write and remains empty in live Mongo until a
future step wires PH intake into the ingestion pipeline.

Boundary with existing ledgers:
  - workflows.inventory.ledger.service manages CUSTOMER-owned ware
    (COW / Customer Storage) — untouched by this module.
  - inventory_lineage_events is Gamer-scoped PH/Assembly lineage — a
    separate collection with no cross-writes.

Writes exclusively to ``inventory_lineage_events``. Never touches
hub_documents, inventory_ledger, or any other collection.
"""

from __future__ import annotations

import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Literal, Mapping, Optional, Tuple

LineageEventType = Literal["receive_to_hold", "release_from_hold"]

LINEAGE_EVENT_TYPES: Tuple[LineageEventType, ...] = (
    "receive_to_hold",
    "release_from_hold",
)

COLLECTION = "inventory_lineage_events"


@dataclass(frozen=True)
class LineageEvent:
    """One entry in the PH/Assembly lineage audit log.

    Field semantics by event_type:
      - receive_to_hold: ``source_ref`` carries the PO reference that
        produced the receipt; ``location`` is the hold location; ``qty``
        is the quantity received into hold.
      - release_from_hold: ``source_ref`` is unused (stored as None);
        ``shipment_ref`` carries the outbound shipment reference; ``qty``
        is the quantity drawn from hold.
    """
    event_id: str
    event_type: LineageEventType
    so_ref: str
    item_no: str
    qty: float
    created_utc: str
    location: Optional[str] = None
    source_ref: Optional[str] = None
    shipment_ref: Optional[str] = None
    evidence: Mapping[str, Any] = None   # type: ignore[assignment]


@dataclass(frozen=True)
class HoldBalance:
    so_ref: str
    item_no: str
    received_qty: float
    released_qty: float
    available_qty: float
    events: Tuple[LineageEvent, ...]


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _validate_qty(qty: float) -> None:
    if qty is None or float(qty) <= 0:
        raise ValueError(f"qty must be > 0; got {qty!r}")


def _validate_ref(label: str, value: Any) -> None:
    if not value or not str(value).strip():
        raise ValueError(f"{label} must be a non-empty string")


def _event_from_doc(raw: Mapping[str, Any]) -> LineageEvent:
    return LineageEvent(
        event_id=raw["event_id"],
        event_type=raw["event_type"],
        so_ref=raw["so_ref"],
        item_no=raw["item_no"],
        qty=float(raw["qty"]),
        created_utc=raw["created_utc"],
        location=raw.get("location"),
        source_ref=raw.get("source_ref"),
        shipment_ref=raw.get("shipment_ref"),
        evidence=dict(raw.get("evidence") or {}),
    )


async def record_receive_to_hold(
    db: Any,
    *,
    so_ref: str,
    item_no: str,
    qty: float,
    location: str,
    source_ref: str,
    evidence: Optional[Mapping[str, Any]] = None,
) -> LineageEvent:
    """Record that a PO receipt satisfied ``qty`` of ``item_no`` into the
    hold lot for ``so_ref``.

    Raises ``ValueError`` on non-positive qty or missing required refs.
    """
    _validate_ref("so_ref", so_ref)
    _validate_ref("item_no", item_no)
    _validate_ref("location", location)
    _validate_ref("source_ref", source_ref)
    _validate_qty(qty)

    entry = {
        "event_id": str(uuid.uuid4()),
        "event_type": "receive_to_hold",
        "so_ref": so_ref,
        "item_no": item_no,
        "qty": float(qty),
        "location": location,
        "source_ref": source_ref,
        "shipment_ref": None,
        "created_utc": _now_iso(),
        "evidence": dict(evidence or {}),
    }
    await db[COLLECTION].insert_one(entry)
    return _event_from_doc(entry)


async def record_release_from_hold(
    db: Any,
    *,
    so_ref: str,
    item_no: str,
    qty: float,
    shipment_ref: str,
    evidence: Optional[Mapping[str, Any]] = None,
) -> LineageEvent:
    """Record that an outbound shipment drew ``qty`` of ``item_no`` from
    the hold lot for ``so_ref``.

    Raises ``ValueError`` on non-positive qty or missing required refs.
    """
    _validate_ref("so_ref", so_ref)
    _validate_ref("item_no", item_no)
    _validate_ref("shipment_ref", shipment_ref)
    _validate_qty(qty)

    entry = {
        "event_id": str(uuid.uuid4()),
        "event_type": "release_from_hold",
        "so_ref": so_ref,
        "item_no": item_no,
        "qty": float(qty),
        "location": None,
        "source_ref": None,
        "shipment_ref": shipment_ref,
        "created_utc": _now_iso(),
        "evidence": dict(evidence or {}),
    }
    await db[COLLECTION].insert_one(entry)
    return _event_from_doc(entry)


async def get_hold_balance(
    db: Any, *, so_ref: str, item_no: str,
) -> HoldBalance:
    """Return running hold balance for ``(so_ref, item_no)``.

    Empty balance returns zero totals and an empty events tuple — callers
    never have to None-guard.
    """
    _validate_ref("so_ref", so_ref)
    _validate_ref("item_no", item_no)

    cursor = db[COLLECTION].find(
        {"so_ref": so_ref, "item_no": item_no},
        {"_id": 0},
    ).sort("created_utc", 1)

    rows = await cursor.to_list(length=10_000)
    received = 0.0
    released = 0.0
    events = []
    for row in rows:
        qty = float(row.get("qty") or 0)
        if row.get("event_type") == "receive_to_hold":
            received += qty
        elif row.get("event_type") == "release_from_hold":
            released += qty
        events.append(_event_from_doc(row))

    return HoldBalance(
        so_ref=so_ref,
        item_no=item_no,
        received_qty=received,
        released_qty=released,
        available_qty=received - released,
        events=tuple(events),
    )


__all__ = [
    "LineageEvent",
    "LineageEventType",
    "LINEAGE_EVENT_TYPES",
    "HoldBalance",
    "COLLECTION",
    "record_receive_to_hold",
    "record_release_from_hold",
    "get_hold_balance",
]
