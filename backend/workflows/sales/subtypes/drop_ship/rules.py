"""
GPI Hub — Drop Ship gates (Lane C Step 6)

Three gate classes providing authoritative-equivalent scaffolding for
the Drop Ship archetype. Parity with the live
``services.so_rules_engine._check_drop_ship_rules`` SO-008/SO-009 rules,
but expressed in the adapter-driven gate framework.

DS subtype classification remains the live responsibility of
``services.document_intel_helpers._classify_so_subtype``. Gates read
``doc.so_subtype == "DS_Sales_Order"`` directly as the trigger axis —
duplicating that detection here would create exactly the parallel
surface the project is avoiding.

Severity ledger (parity with live rules; signed):
  - drop_ship_po_missing ................... block   (SO-008 parity)
  - drop_ship_po_cost_unverified ........... warn    (SO-009 parity)
  - drop_ship_inventory_line_not_marked .... warn    (ancillary parity)

Opt-in registration only — mirrors the WH Step-5 pattern. No
auto-registration at import time.

Runtime behavior in Step 6: ZERO. The live ``so_rules_engine`` path is
not modified, wrapped, or deleted. Wire-in is a separately signed step.
"""

from __future__ import annotations

from typing import Any, Mapping, Optional, Set

from workflows.core.gate_framework import (
    Gate,
    GateContext,
    GateResult,
    GateRegistry,
    hash_evaluate_source,
)


ARCHETYPE = "drop_ship"

_DS_SUBTYPES: Set[str] = {"DS_Sales_Order", "ds_sales_order"}


def _is_ds_doc(ctx: GateContext) -> bool:
    """Trigger axis: is this a drop-ship sales order per the live classifier?"""
    doc = ctx.doc or {}
    subtype = doc.get("so_subtype") or (doc.get("extracted_fields") or {}).get("so_subtype")
    return str(subtype or "").strip() in _DS_SUBTYPES


def _has_po_linkage(ctx: GateContext) -> bool:
    """Mirror of ``so_rules_engine._build_order_context.has_po_linkage``.

    A DS order is PO-linked if any of the following are present:
      - ``extracted_fields.purchase_order_no``
      - ``doc.linked_po``
      - ``normalized_fields.purchase_order_number``
    """
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    if ef.get("purchase_order_no"):
        return True
    if doc.get("linked_po"):
        return True
    if nf.get("purchase_order_number"):
        return True
    return False


def _line_items(ctx: GateContext) -> list[Mapping[str, Any]]:
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    raw = (
        nf.get("line_items")
        or doc.get("line_items")
        or ef.get("line_items")
        or ef.get("lines")
        or []
    )
    return [li for li in raw if isinstance(li, Mapping)]


def _is_freight_line(line: Mapping[str, Any]) -> bool:
    desc = str(line.get("description") or "").lower()
    item_no = str(line.get("item_no") or line.get("item_number") or "").upper()
    li_type = str(line.get("type") or line.get("line_type") or "").lower()
    return (
        "freight" in desc
        or "shipping" in desc
        or "FREIGHT" in item_no
        or li_type == "charge"
    )


def _is_ds_marked_line(line: Mapping[str, Any]) -> bool:
    """Mirror of the ``ds_lines`` predicate in ``_check_drop_ship_rules``."""
    if line.get("drop_shipment"):
        return True
    if str(line.get("purchasing_code") or "").strip().upper() == "DROP SHIP":
        return True
    return False


def _not_applicable(gate_id: str, version: str, reason: str) -> GateResult:
    return GateResult(
        gate_id=gate_id,
        gate_version=version,
        passed=True,
        severity="info",
        detail=f"Gate not applicable — {reason}.",
        evidence={},
        resolution_hint=None,
    )


# ── Gate 1: drop-ship PO missing (BLOCK) ───────────────────────────────────

class DropShipPoMissingGate:
    """SO-008 parity: DS order with no PO linkage → block.

    Live equivalent: ``so_rules_engine._check_drop_ship_rules`` where
    ``is_drop_ship and not has_po_linkage`` appends
    ``"SO-008: Drop ship order AND PO missing → stage = Drop Ship PO Needed"``
    to ``blocking_issues`` and routes ``_determine_stage`` to the
    ``"Drop Ship PO Needed"`` stage.
    """

    id = "drop_ship_po_missing"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "block"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _is_ds_doc(ctx):
            return _not_applicable(self.id, self.version, "not a Drop Ship Sales Order")

        if _has_po_linkage(ctx):
            return GateResult(
                gate_id=self.id, gate_version=self.version,
                passed=True, severity="block",
                detail="Drop-ship PO linkage is present.",
                evidence={"has_po_linkage": True},
                resolution_hint=None,
            )

        return GateResult(
            gate_id=self.id, gate_version=self.version,
            passed=False, severity="block",
            detail=(
                "Drop-ship order has no linked purchase order "
                "(SO-008 parity: stage = Drop Ship PO Needed)."
            ),
            evidence={"has_po_linkage": False},
            resolution_hint=(
                "Create the corresponding purchase order for the "
                "drop-ship lines and link it to this sales order."
            ),
        )


# ── Gate 2: drop-ship PO cost unverified (WARN) ────────────────────────────

class DropShipPoCostUnverifiedGate:
    """SO-009 parity: DS order with PO linkage → warn (PO cost cannot be
    verified from the SO document alone).

    Live equivalent: ``so_rules_engine._check_drop_ship_rules`` where
    ``is_drop_ship and has_po_linkage`` appends
    ``"SO-009: Drop ship PO exists — verify PO cost is entered (cannot
    confirm from SO data alone)"`` to ``business_rules_triggered``.
    """

    id = "drop_ship_po_cost_unverified"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "warn"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _is_ds_doc(ctx):
            return _not_applicable(self.id, self.version, "not a Drop Ship Sales Order")

        if not _has_po_linkage(ctx):
            # Missing-PO case is Gate 1's concern.
            return _not_applicable(
                self.id, self.version,
                "no PO linkage — deferred to drop_ship_po_missing",
            )

        return GateResult(
            gate_id=self.id, gate_version=self.version,
            passed=False, severity="warn",
            detail=(
                "Drop-ship PO is linked, but PO cost cannot be verified "
                "from SO data alone (SO-009 parity)."
            ),
            evidence={"has_po_linkage": True},
            resolution_hint=(
                "Open the linked PO and confirm that unit costs and "
                "quantities match the sales-order lines before release."
            ),
        )


# ── Gate 3: inventory line not marked drop-ship (WARN) ─────────────────────

class DropShipInventoryLineNotMarkedGate:
    """Ancillary parity: DS order with inventory lines but no line marked
    as a drop shipment → warn (verify purchasing code).

    Live equivalent: ``so_rules_engine._check_drop_ship_rules`` where
    ``non_freight_lines and not ds_lines`` appends
    ``"SO-008: Inventory lines found but none marked as Drop Shipment —
    verify purchasing code"`` to ``business_rules_triggered``.
    """

    id = "drop_ship_inventory_line_not_marked"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "warn"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _is_ds_doc(ctx):
            return _not_applicable(self.id, self.version, "not a Drop Ship Sales Order")

        lines = _line_items(ctx)
        if not lines:
            return _not_applicable(self.id, self.version, "no line items on document")

        non_freight_lines = [li for li in lines if not _is_freight_line(li)]
        if not non_freight_lines:
            return _not_applicable(
                self.id, self.version,
                "no non-freight inventory lines",
            )

        ds_marked = [li for li in lines if _is_ds_marked_line(li)]

        if ds_marked:
            return GateResult(
                gate_id=self.id, gate_version=self.version,
                passed=True, severity="warn",
                detail=(
                    f"{len(ds_marked)} of {len(lines)} lines are marked "
                    "as drop shipment."
                ),
                evidence={
                    "line_count": len(lines),
                    "non_freight_line_count": len(non_freight_lines),
                    "ds_marked_count": len(ds_marked),
                },
                resolution_hint=None,
            )

        return GateResult(
            gate_id=self.id, gate_version=self.version,
            passed=False, severity="warn",
            detail=(
                f"{len(non_freight_lines)} inventory line(s) present but "
                "none are marked as drop shipment (verify purchasing code)."
            ),
            evidence={
                "line_count": len(lines),
                "non_freight_line_count": len(non_freight_lines),
                "ds_marked_count": 0,
            },
            resolution_hint=(
                "Verify the purchasing code on each inventory line; "
                "drop-ship lines should carry purchasing_code=\"DROP SHIP\" "
                "or drop_shipment=true."
            ),
        )


# ── Opt-in registration ─────────────────────────────────────────────────────

_DS_GATE_CLASSES = (
    DropShipPoMissingGate,
    DropShipPoCostUnverifiedGate,
    DropShipInventoryLineNotMarkedGate,
)


def register_drop_ship_gates(registry: GateRegistry) -> tuple[Gate, ...]:
    """Register the three Drop Ship gates on ``registry``. Idempotent.

    Not auto-registered at import time. Callers opt in explicitly.
    Returns the gates newly registered on this invocation (empty tuple
    on subsequent calls).
    """
    existing_ids = {g.id for g in registry.list_gates()}
    registered: list[Gate] = []
    for cls in _DS_GATE_CLASSES:
        gate = cls()
        if gate.id in existing_ids:
            continue
        registry.register(gate)
        registered.append(gate)
    return tuple(registered)


__all__ = [
    "ARCHETYPE",
    "DropShipPoMissingGate",
    "DropShipPoCostUnverifiedGate",
    "DropShipInventoryLineNotMarkedGate",
    "register_drop_ship_gates",
]
