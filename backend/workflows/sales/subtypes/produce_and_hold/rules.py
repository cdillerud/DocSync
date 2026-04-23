"""
GPI Hub — Produce & Hold gates (Lane C Step 4)

Three gate classes implementing the Gate Protocol from
workflows.core.gate_framework. Defined here but NOT auto-registered at
import time. Callers opt in via ``register_produce_and_hold_gates``.

Each gate defensively short-circuits with ``passed=True`` /
``severity="info"`` when the document lacks PH indicators — so even if a
future caller accidentally runs them through a global evaluation pass,
non-PH docs see no impact.

Severity ledger (per signed scope):
  - produce_and_hold_release_overdraw ..... block
  - produce_and_hold_blanket_match ......... warn
  - produce_and_hold_aging ................. warn
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Mapping, Optional, Set

from workflows.core.gate_framework import (
    Gate,
    GateContext,
    GateResult,
    GateRegistry,
    hash_evaluate_source,
)
from workflows.inventory import lineage as _lineage

from .classification import (
    PH_AGING_THRESHOLD_DAYS,
    PH_BLANKET_DIVERGENCE_FRACTION,
    classify_produce_and_hold,
)


ARCHETYPE = "produce_and_hold"


def _has_ph_signals(ctx: GateContext) -> bool:
    """Cheap check: does the doc look like a PH candidate?"""
    ef = (ctx.doc or {}).get("extracted_fields") or {}
    result = classify_produce_and_hold(ctx.doc or {}, ef)
    return result.is_produce_and_hold or bool(result.signals)


def _so_ref(ctx: GateContext) -> str:
    """Extract the sales-order reference used to key lineage events."""
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    for key in ("so_number", "sales_order_number", "order_number"):
        v = ef.get(key) or doc.get(key)
        if v:
            return str(v).strip()
    return ""


def _lines(ctx: GateContext) -> list[Mapping[str, Any]]:
    ef = (ctx.doc or {}).get("extracted_fields") or {}
    lines = ef.get("line_items") or ef.get("lines") or []
    return list(lines) if isinstance(lines, list) else []


def _line_item_no(line: Mapping[str, Any]) -> str:
    for key in ("item_no", "item_number", "sku"):
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


def _not_applicable(gate_id: str, version: str) -> GateResult:
    return GateResult(
        gate_id=gate_id,
        gate_version=version,
        passed=True,
        severity="info",
        detail="Gate not applicable — document lacks Produce & Hold indicators.",
        evidence={},
        resolution_hint=None,
    )


# ── Gate 1: release overdraw (BLOCK) ────────────────────────────────────────

class ProduceAndHoldReleaseOverdrawGate:
    id = "produce_and_hold_release_overdraw"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "block"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _has_ph_signals(ctx):
            return _not_applicable(self.id, self.version)

        so_ref = _so_ref(ctx)
        if not so_ref:
            return _not_applicable(self.id, self.version)

        overdraw_lines: list[dict[str, Any]] = []
        for line in _lines(ctx):
            item_no = _line_item_no(line)
            release_qty = _line_qty(line, "release_qty", "ship_qty", "quantity")
            if not item_no or release_qty <= 0:
                continue
            balance = await _lineage.get_hold_balance(
                ctx.db, so_ref=so_ref, item_no=item_no,
            )
            if release_qty > balance.available_qty + 1e-9:
                overdraw_lines.append({
                    "item_no": item_no,
                    "release_qty": release_qty,
                    "available_qty": balance.available_qty,
                    "received_qty": balance.received_qty,
                    "released_qty": balance.released_qty,
                })

        passed = len(overdraw_lines) == 0
        return GateResult(
            gate_id=self.id,
            gate_version=self.version,
            passed=passed,
            severity="block",
            detail=(
                f"{len(overdraw_lines)} line(s) attempt to release more than "
                f"the hold balance for SO {so_ref}."
                if not passed else "Release quantities fit within hold balance."
            ),
            evidence={"so_ref": so_ref, "overdraw_lines": overdraw_lines},
            resolution_hint=(
                "Wait for additional production receipts into hold, or split "
                "the shipment to match the available balance."
                if not passed else None
            ),
        )


# ── Gate 2: blanket-qty vs received-to-hold divergence (WARN) ───────────────

class ProduceAndHoldBlanketMatchGate:
    id = "produce_and_hold_blanket_match"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "warn"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _has_ph_signals(ctx):
            return _not_applicable(self.id, self.version)

        so_ref = _so_ref(ctx)
        if not so_ref:
            return _not_applicable(self.id, self.version)

        diverging_lines: list[dict[str, Any]] = []
        for line in _lines(ctx):
            item_no = _line_item_no(line)
            blanket_qty = _line_qty(line, "blanket_qty", "total_qty", "ordered_qty")
            if not item_no or blanket_qty <= 0:
                continue
            balance = await _lineage.get_hold_balance(
                ctx.db, so_ref=so_ref, item_no=item_no,
            )
            divergence = abs(balance.received_qty - blanket_qty) / blanket_qty
            if divergence > PH_BLANKET_DIVERGENCE_FRACTION:
                diverging_lines.append({
                    "item_no": item_no,
                    "blanket_qty": blanket_qty,
                    "received_qty": balance.received_qty,
                    "divergence_fraction": round(divergence, 4),
                })

        passed = len(diverging_lines) == 0
        return GateResult(
            gate_id=self.id,
            gate_version=self.version,
            passed=passed,
            severity="warn",
            detail=(
                f"{len(diverging_lines)} line(s) have received-to-hold qty "
                f"diverging from blanket qty by more than "
                f"{PH_BLANKET_DIVERGENCE_FRACTION:.0%}."
                if not passed else "Received-to-hold quantities match blanket."
            ),
            evidence={
                "so_ref": so_ref,
                "threshold": PH_BLANKET_DIVERGENCE_FRACTION,
                "diverging_lines": diverging_lines,
            },
            resolution_hint=(
                "Confirm whether additional production receipts are expected "
                "or whether the blanket quantity should be revised."
                if not passed else None
            ),
        )


# ── Gate 3: aging of held inventory (WARN) ──────────────────────────────────

class ProduceAndHoldAgingGate:
    id = "produce_and_hold_aging"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "warn"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _has_ph_signals(ctx):
            return _not_applicable(self.id, self.version)

        so_ref = _so_ref(ctx)
        if not so_ref:
            return _not_applicable(self.id, self.version)

        # Collect unique item_nos from the doc's lines so we can scan
        # per-item hold balances. If no lines are present, the gate
        # short-circuits cleanly.
        item_nos = sorted({_line_item_no(line) for line in _lines(ctx) if _line_item_no(line)})
        if not item_nos:
            return _not_applicable(self.id, self.version)

        now_utc = datetime.now(timezone.utc)
        aged_items: list[dict[str, Any]] = []

        for item_no in item_nos:
            balance = await _lineage.get_hold_balance(
                ctx.db, so_ref=so_ref, item_no=item_no,
            )
            if balance.available_qty <= 0:
                continue
            # An aged *available* balance means something received long ago
            # was never released. Check the earliest receive event against
            # the threshold.
            earliest_receive = None
            for ev in balance.events:
                if ev.event_type != "receive_to_hold":
                    continue
                try:
                    ts = datetime.fromisoformat(ev.created_utc.replace("Z", "+00:00"))
                except (ValueError, AttributeError):
                    continue
                if earliest_receive is None or ts < earliest_receive:
                    earliest_receive = ts
            if earliest_receive is None:
                continue
            age_days = (now_utc - earliest_receive).days
            if age_days > PH_AGING_THRESHOLD_DAYS:
                aged_items.append({
                    "item_no": item_no,
                    "available_qty": balance.available_qty,
                    "oldest_receive_utc": earliest_receive.isoformat(),
                    "age_days": age_days,
                })

        passed = len(aged_items) == 0
        return GateResult(
            gate_id=self.id,
            gate_version=self.version,
            passed=passed,
            severity="warn",
            detail=(
                f"{len(aged_items)} item(s) have hold inventory older than "
                f"{PH_AGING_THRESHOLD_DAYS} days for SO {so_ref}."
                if not passed else "No aged hold inventory detected."
            ),
            evidence={
                "so_ref": so_ref,
                "threshold_days": PH_AGING_THRESHOLD_DAYS,
                "aged_items": aged_items,
            },
            resolution_hint=(
                "Check with the customer on release timing or revisit the "
                "blanket-order schedule; aged inventory ties up warehouse "
                "capacity."
                if not passed else None
            ),
        )


# ── Opt-in registration ─────────────────────────────────────────────────────

_PH_GATE_CLASSES = (
    ProduceAndHoldReleaseOverdrawGate,
    ProduceAndHoldBlanketMatchGate,
    ProduceAndHoldAgingGate,
)


def register_produce_and_hold_gates(registry: GateRegistry) -> tuple[Gate, ...]:
    """Register the three PH gates on ``registry``. Idempotent.

    Unlike Step 2.75's global gates, PH gates are NOT auto-registered at
    import time. This helper is the single, opt-in entry point. Future
    callers that know they're evaluating a PH document invoke this once
    at startup (or per-request, idempotently) and then run
    ``registry.list_gates(archetype="produce_and_hold")``.
    """
    existing_ids = {g.id for g in registry.list_gates()}
    registered: list[Gate] = []
    for cls in _PH_GATE_CLASSES:
        gate = cls()
        if gate.id in existing_ids:
            # Idempotent: skip silently so the helper can be called multiple
            # times (startup + test setup, for example) without tripping the
            # registry's duplicate-id guard.
            continue
        registry.register(gate)
        registered.append(gate)
    return tuple(registered)


__all__ = [
    "ARCHETYPE",
    "ProduceAndHoldReleaseOverdrawGate",
    "ProduceAndHoldBlanketMatchGate",
    "ProduceAndHoldAgingGate",
    "register_produce_and_hold_gates",
]
