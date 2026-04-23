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
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Iterable, Literal, Mapping, Optional, Tuple

LineageEventType = Literal[
    "receive_to_hold",
    "release_from_hold",
    "component_consumed",
    "assembly_produced",
]

LINEAGE_EVENT_TYPES: Tuple[LineageEventType, ...] = (
    "receive_to_hold",
    "release_from_hold",
    "component_consumed",
    "assembly_produced",
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


# =============================================================================
# Assembly primitives (Lane C Step 4b)
# =============================================================================
# Same collection, same validators. Schema is a single document shape with
# optional fields used per event_type — no parallel collection, no
# cross-package imports. Assembly events never write so_ref; PH events
# never write work_order_ref. Readers filter by event_type.
# =============================================================================


@dataclass(frozen=True)
class AssemblyEvent:
    """One component-consume or parent-produce event in the assembly lineage.

    Field semantics by event_type:
      - component_consumed: ``item_no`` is the component; ``location`` is the
        source location pulled from; ``components`` is always ``()``.
      - assembly_produced:  ``item_no`` is the produced parent; ``location`` is
        where the parent lands; ``components`` is the BOM snapshot captured
        at production time — a tuple of ``{"item_no": str, "qty": float}``
        dicts.
    """
    event_id: str
    event_type: LineageEventType
    work_order_ref: str
    item_no: str
    qty: float
    created_utc: str
    location: Optional[str] = None
    components: Tuple[Mapping[str, Any], ...] = ()
    evidence: Mapping[str, Any] = field(default_factory=dict)


@dataclass(frozen=True)
class AssemblyLedger:
    work_order_ref: str
    produced_parents: Mapping[str, float]
    consumed_components: Mapping[str, float]
    events: Tuple[AssemblyEvent, ...]


def _assembly_event_from_doc(raw: Mapping[str, Any]) -> AssemblyEvent:
    return AssemblyEvent(
        event_id=raw["event_id"],
        event_type=raw["event_type"],
        work_order_ref=raw["work_order_ref"],
        item_no=raw["item_no"],
        qty=float(raw["qty"]),
        created_utc=raw["created_utc"],
        location=raw.get("location"),
        components=tuple(raw.get("components") or ()),
        evidence=dict(raw.get("evidence") or {}),
    )


def _normalize_components(components: Iterable[Mapping[str, Any]]) -> Tuple[dict, ...]:
    """Coerce a BOM-components iterable into a clean tuple of dicts.

    Entries missing ``item_no`` or ``qty`` are dropped silently — production
    callers can normalize upstream; this helper is defensive so a malformed
    BOM row does not corrupt the lineage event.
    """
    cleaned: list[dict] = []
    for raw in components or ():
        if not isinstance(raw, Mapping):
            continue
        item_no = raw.get("item_no") or raw.get("component_item_no")
        qty = raw.get("qty")
        if not item_no or qty is None:
            continue
        try:
            qty_f = float(qty)
        except (TypeError, ValueError):
            continue
        if qty_f <= 0:
            continue
        cleaned.append({"item_no": str(item_no).strip(), "qty": qty_f})
    return tuple(cleaned)


async def record_component_consumed(
    db: Any,
    *,
    work_order_ref: str,
    component_item_no: str,
    qty: float,
    source_location: str,
    evidence: Optional[Mapping[str, Any]] = None,
) -> AssemblyEvent:
    """Record that ``qty`` of ``component_item_no`` was pulled from
    ``source_location`` for assembly work order ``work_order_ref``.

    Raises ``ValueError`` on non-positive qty or missing required refs.
    """
    _validate_ref("work_order_ref", work_order_ref)
    _validate_ref("component_item_no", component_item_no)
    _validate_ref("source_location", source_location)
    _validate_qty(qty)

    entry = {
        "event_id": str(uuid.uuid4()),
        "event_type": "component_consumed",
        "work_order_ref": work_order_ref,
        "item_no": component_item_no,
        "qty": float(qty),
        "location": source_location,
        "components": [],
        "created_utc": _now_iso(),
        "evidence": dict(evidence or {}),
    }
    await db[COLLECTION].insert_one(entry)
    return _assembly_event_from_doc(entry)


async def record_assembly_produced(
    db: Any,
    *,
    work_order_ref: str,
    parent_item_no: str,
    qty: float,
    location: str,
    components: Iterable[Mapping[str, Any]] = (),
    evidence: Optional[Mapping[str, Any]] = None,
) -> AssemblyEvent:
    """Record that ``qty`` of ``parent_item_no`` was produced into
    ``location`` by assembly work order ``work_order_ref``.

    ``components`` is a BOM snapshot captured at production time.

    Raises ``ValueError`` on non-positive qty or missing required refs.
    """
    _validate_ref("work_order_ref", work_order_ref)
    _validate_ref("parent_item_no", parent_item_no)
    _validate_ref("location", location)
    _validate_qty(qty)

    cleaned_components = _normalize_components(components)

    entry = {
        "event_id": str(uuid.uuid4()),
        "event_type": "assembly_produced",
        "work_order_ref": work_order_ref,
        "item_no": parent_item_no,
        "qty": float(qty),
        "location": location,
        "components": list(cleaned_components),
        "created_utc": _now_iso(),
        "evidence": dict(evidence or {}),
    }
    await db[COLLECTION].insert_one(entry)
    return _assembly_event_from_doc(entry)


async def get_assembly_ledger(
    db: Any, *, work_order_ref: str,
) -> AssemblyLedger:
    """Return the running ledger for an assembly work order.

    Produced parents and consumed components are summed independently.
    Empty ledger returns zero totals and an empty events tuple.
    """
    _validate_ref("work_order_ref", work_order_ref)

    cursor = db[COLLECTION].find(
        {
            "work_order_ref": work_order_ref,
            "event_type": {"$in": ["component_consumed", "assembly_produced"]},
        },
        {"_id": 0},
    ).sort("created_utc", 1)

    rows = await cursor.to_list(length=10_000)
    produced: dict[str, float] = {}
    consumed: dict[str, float] = {}
    events: list[AssemblyEvent] = []
    for row in rows:
        qty = float(row.get("qty") or 0)
        item_no = row.get("item_no") or ""
        ev_type = row.get("event_type")
        if ev_type == "assembly_produced":
            produced[item_no] = produced.get(item_no, 0.0) + qty
        elif ev_type == "component_consumed":
            consumed[item_no] = consumed.get(item_no, 0.0) + qty
        events.append(_assembly_event_from_doc(row))

    return AssemblyLedger(
        work_order_ref=work_order_ref,
        produced_parents=produced,
        consumed_components=consumed,
        events=tuple(events),
    )


__all__ = [
    "LineageEvent",
    "LineageEventType",
    "LINEAGE_EVENT_TYPES",
    "HoldBalance",
    "AssemblyEvent",
    "AssemblyLedger",
    "COLLECTION",
    "record_receive_to_hold",
    "record_release_from_hold",
    "get_hold_balance",
    "record_component_consumed",
    "record_assembly_produced",
    "get_assembly_ledger",
]
