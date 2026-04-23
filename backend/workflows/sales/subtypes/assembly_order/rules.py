"""
GPI Hub — Assembly Order gates (Lane C Step 4b)

Two gate classes — one block, one warn. Opt-in registration only;
not auto-registered at import time. Defensive short-circuit on
non-Assembly documents.

Severity ledger:
  - assembly_order_produced_overdraw ... block
  - assembly_order_bom_completeness .... warn

Aging gate is intentionally deferred to a later PH↔Assembly chaining
step (per signed scope and the 4b Pre-Change Declaration).
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
from workflows.inventory import lineage as _lineage

from .classification import classify_assembly_order


ARCHETYPE = "assembly_order"


def _has_assembly_signals(ctx: GateContext) -> bool:
    ef = (ctx.doc or {}).get("extracted_fields") or {}
    result = classify_assembly_order(ctx.doc or {}, ef)
    return result.is_assembly_order or bool(result.signals)


def _work_order_ref(ctx: GateContext) -> str:
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    for key in ("work_order_ref", "work_order_number", "work_order_no", "assembly_ref"):
        v = ef.get(key) or doc.get(key)
        if v:
            return str(v).strip()
    return ""


def _lines(ctx: GateContext) -> list[Mapping[str, Any]]:
    ef = (ctx.doc or {}).get("extracted_fields") or {}
    lines = ef.get("line_items") or ef.get("lines") or []
    return list(lines) if isinstance(lines, list) else []


def _line_item_no(line: Mapping[str, Any]) -> str:
    for key in ("item_no", "parent_item_no", "item_number", "sku"):
        v = line.get(key)
        if v:
            return str(v).strip()
    return ""


def _line_qty(line: Mapping[str, Any], *keys: str) -> float:
    for key in keys:
        v = line.get(key)
        if v is not None:
            try:
                return float(v)
            except (TypeError, ValueError):
                continue
    return 0.0


def _doc_bom(ctx: GateContext) -> list[Mapping[str, Any]]:
    """Extract the doc's declared BOM (flat list of component entries).

    Accepted shapes: a top-level ``bom`` / ``components`` / ``kit_items``
    field carrying a list of ``{item_no, qty}`` dicts.
    """
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    for key in ("bom", "components", "kit_items", "assembly_components"):
        val = ef.get(key) or doc.get(key)
        if isinstance(val, list):
            return list(val)
    return []


def _not_applicable(gate_id: str, version: str) -> GateResult:
    return GateResult(
        gate_id=gate_id,
        gate_version=version,
        passed=True,
        severity="info",
        detail="Gate not applicable — document lacks Assembly Order indicators.",
        evidence={},
        resolution_hint=None,
    )


# ── Gate 1: produced overdraw (BLOCK) ──────────────────────────────────────

class AssemblyOrderProducedOverdrawGate:
    id = "assembly_order_produced_overdraw"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "block"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _has_assembly_signals(ctx):
            return _not_applicable(self.id, self.version)
        work_ref = _work_order_ref(ctx)
        if not work_ref:
            return _not_applicable(self.id, self.version)

        ledger = await _lineage.get_assembly_ledger(
            ctx.db, work_order_ref=work_ref,
        )

        overdraw_lines: list[dict[str, Any]] = []
        for line in _lines(ctx):
            parent = _line_item_no(line)
            ship_qty = _line_qty(line, "release_qty", "ship_qty", "quantity")
            if not parent or ship_qty <= 0:
                continue
            produced = float(ledger.produced_parents.get(parent, 0.0))
            if ship_qty > produced + 1e-9:
                overdraw_lines.append({
                    "parent_item_no": parent,
                    "ship_qty": ship_qty,
                    "produced_qty": produced,
                })

        passed = len(overdraw_lines) == 0
        return GateResult(
            gate_id=self.id,
            gate_version=self.version,
            passed=passed,
            severity="block",
            detail=(
                f"{len(overdraw_lines)} line(s) attempt to ship more than "
                f"work order {work_ref} produced."
                if not passed else "Ship quantities fit within produced qty."
            ),
            evidence={
                "work_order_ref": work_ref,
                "overdraw_lines": overdraw_lines,
            },
            resolution_hint=(
                "Wait for additional assembly production or split the "
                "shipment to match produced quantity."
                if not passed else None
            ),
        )


# ── Gate 2: BOM completeness (WARN) ────────────────────────────────────────

class AssemblyOrderBomCompletenessGate:
    id = "assembly_order_bom_completeness"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "warn"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _has_assembly_signals(ctx):
            return _not_applicable(self.id, self.version)
        work_ref = _work_order_ref(ctx)
        if not work_ref:
            return _not_applicable(self.id, self.version)

        declared_bom = _doc_bom(ctx)
        if not declared_bom:
            # No declared BOM → nothing to check; pass silently.
            return GateResult(
                gate_id=self.id,
                gate_version=self.version,
                passed=True,
                severity="warn",
                detail="No declared BOM on document; completeness not checked.",
                evidence={"work_order_ref": work_ref},
                resolution_hint=None,
            )

        ledger = await _lineage.get_assembly_ledger(
            ctx.db, work_order_ref=work_ref,
        )

        missing: list[dict[str, Any]] = []
        for entry in declared_bom:
            if not isinstance(entry, Mapping):
                continue
            comp = entry.get("item_no") or entry.get("component_item_no")
            if not comp:
                continue
            consumed_qty = float(ledger.consumed_components.get(str(comp), 0.0))
            if consumed_qty <= 0:
                missing.append({
                    "component_item_no": str(comp),
                    "declared_qty": entry.get("qty"),
                    "consumed_qty": consumed_qty,
                })

        passed = len(missing) == 0
        return GateResult(
            gate_id=self.id,
            gate_version=self.version,
            passed=passed,
            severity="warn",
            detail=(
                f"{len(missing)} BOM component(s) have no recorded consumption "
                f"on work order {work_ref}."
                if not passed else "All declared BOM components have consumption events."
            ),
            evidence={
                "work_order_ref": work_ref,
                "missing_components": missing,
            },
            resolution_hint=(
                "Verify component pulls were recorded, or confirm the BOM "
                "entries are expected to be substituted / unused."
                if not passed else None
            ),
        )


# ── Opt-in registration ─────────────────────────────────────────────────────

_ASSEMBLY_GATE_CLASSES = (
    AssemblyOrderProducedOverdrawGate,
    AssemblyOrderBomCompletenessGate,
)


def register_assembly_order_gates(registry: GateRegistry) -> tuple[Gate, ...]:
    """Register the two Assembly gates on ``registry``. Idempotent.

    Not auto-registered at import time. Callers opt in explicitly.
    """
    existing_ids = {g.id for g in registry.list_gates()}
    registered: list[Gate] = []
    for cls in _ASSEMBLY_GATE_CLASSES:
        gate = cls()
        if gate.id in existing_ids:
            continue
        registry.register(gate)
        registered.append(gate)
    return tuple(registered)


__all__ = [
    "ARCHETYPE",
    "AssemblyOrderProducedOverdrawGate",
    "AssemblyOrderBomCompletenessGate",
    "register_assembly_order_gates",
]
