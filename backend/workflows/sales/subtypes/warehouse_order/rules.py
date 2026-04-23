"""
GPI Hub — Warehouse Order gates (Lane C Step 5)

Three gate classes that consume the canonical shipment-method registry
(workflows.freight.shipment_methods) as the SOLE source of shipment-method
truth. This package intentionally contains NO classifier:
``services.document_intel_helpers._classify_so_subtype`` is the live
authority for DS vs WH classification; duplicating that here would
create exactly the parallel workflow surface the project is avoiding.

Gates read ``doc.so_subtype == "WH_Sales_Order"`` directly as the
trigger axis, then defer to ``resolve_rules`` for rule semantics.

Severity ledger (per signed scope):
  - warehouse_order_shipment_method_unknown ............ block
  - warehouse_order_shipment_method_archetype_mismatch . warn
  - warehouse_order_freight_expectation_mismatch ....... warn

Opt-in registration only — mirrors the PH/Assembly pattern. No
auto-registration at import time.
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
from workflows.freight.shipment_methods import resolve_rules


ARCHETYPE = "warehouse_order"

_WH_SUBTYPES: Set[str] = {"WH_Sales_Order", "wh_sales_order"}


def _is_wh_doc(ctx: GateContext) -> bool:
    """Trigger axis: is this a warehouse sales order per the live classifier?"""
    doc = ctx.doc or {}
    subtype = doc.get("so_subtype") or (doc.get("extracted_fields") or {}).get("so_subtype")
    return str(subtype or "").strip() in _WH_SUBTYPES


def _shipment_method_code(ctx: GateContext) -> str:
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    for key in ("shipment_method_code", "shipmentMethodCode", "shipment_method"):
        v = ef.get(key) or doc.get(key)
        if v:
            return str(v).strip()
    return ""


def _has_freight_line(ctx: GateContext) -> bool:
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    for line in (ef.get("line_items") or ef.get("lines") or []):
        if not isinstance(line, Mapping):
            continue
        item_no = str(line.get("item_no") or line.get("item_number") or "").upper()
        desc = str(line.get("description") or "").upper()
        if "FREIGHT" in item_no or "FREIGHT" in desc:
            return True
    return False


def _freight_line_has_sell_price(ctx: GateContext) -> bool:
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    for line in (ef.get("line_items") or ef.get("lines") or []):
        if not isinstance(line, Mapping):
            continue
        item_no = str(line.get("item_no") or line.get("item_number") or "").upper()
        desc = str(line.get("description") or "").upper()
        if "FREIGHT" not in item_no and "FREIGHT" not in desc:
            continue
        for price_key in ("unit_price", "sell_price", "price"):
            v = line.get(price_key)
            if v is not None:
                try:
                    if float(v) > 0:
                        return True
                except (TypeError, ValueError):
                    continue
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


# ── Gate 1: unknown shipment method (BLOCK) ────────────────────────────────

class WarehouseOrderShipmentMethodUnknownGate:
    id = "warehouse_order_shipment_method_unknown"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "block"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _is_wh_doc(ctx):
            return _not_applicable(self.id, self.version, "not a Warehouse Sales Order")
        code = _shipment_method_code(ctx)
        if not code:
            return _not_applicable(self.id, self.version, "no shipment_method_code on document")

        rules = resolve_rules(code, archetype=ARCHETYPE)
        if rules.known:
            return GateResult(
                gate_id=self.id, gate_version=self.version,
                passed=True, severity="block",
                detail=f"Shipment method {code} is recognized.",
                evidence={"code": code, "display_name": rules.display_name},
                resolution_hint=None,
            )
        return GateResult(
            gate_id=self.id, gate_version=self.version,
            passed=False, severity="block",
            detail=f"Shipment method code {code!r} is not in the canonical 13-code registry.",
            evidence={"code": code},
            resolution_hint=(
                "Correct the shipment_method_code on the source document or add "
                "the code to workflows.freight.shipment_methods.registry."
            ),
        )


# ── Gate 2: archetype mismatch (WARN) ──────────────────────────────────────

class WarehouseOrderShipmentMethodArchetypeMismatchGate:
    id = "warehouse_order_shipment_method_archetype_mismatch"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "warn"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _is_wh_doc(ctx):
            return _not_applicable(self.id, self.version, "not a Warehouse Sales Order")
        code = _shipment_method_code(ctx)
        if not code:
            return _not_applicable(self.id, self.version, "no shipment_method_code on document")

        rules = resolve_rules(code, archetype=ARCHETYPE)
        if not rules.known:
            # Unknown-code is Gate 1's concern; defer.
            return _not_applicable(self.id, self.version, "unknown code deferred to overdraw gate")

        passed = bool(rules.archetype_allowed)
        return GateResult(
            gate_id=self.id, gate_version=self.version,
            passed=passed, severity="warn",
            detail=(
                f"Shipment method {code} ({rules.display_name}) is not typically "
                f"used for warehouse orders."
                if not passed else
                f"Shipment method {code} is compatible with warehouse orders."
            ),
            evidence={
                "code": code,
                "allowed_archetypes": list(rules.allowed_archetypes),
                "display_name": rules.display_name,
            },
            resolution_hint=(
                "Confirm the shipment method is intended for this order; "
                "override legitimately if so."
                if not passed else None
            ),
        )


# ── Gate 3: freight expectation mismatch (WARN) ────────────────────────────

class WarehouseOrderFreightExpectationMismatchGate:
    id = "warehouse_order_freight_expectation_mismatch"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "warn"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _is_wh_doc(ctx):
            return _not_applicable(self.id, self.version, "not a Warehouse Sales Order")
        code = _shipment_method_code(ctx)
        if not code:
            return _not_applicable(self.id, self.version, "no shipment_method_code on document")

        rules = resolve_rules(code, archetype=ARCHETYPE)
        if not rules.known:
            return _not_applicable(self.id, self.version, "unknown code deferred")

        findings: list[str] = []

        if rules.has_freight_line_expected and not _has_freight_line(ctx):
            findings.append(
                f"method {code} expects a freight line on the SO, but none was found"
            )

        if (
            rules.has_freight_line_expected
            and rules.freight_has_sell_price
            and _has_freight_line(ctx)
            and not _freight_line_has_sell_price(ctx)
        ):
            findings.append(
                f"method {code} expects the freight line to carry a sell price, but none was found"
            )

        passed = len(findings) == 0
        return GateResult(
            gate_id=self.id, gate_version=self.version,
            passed=passed, severity="warn",
            detail=(
                "; ".join(findings) if findings
                else f"Freight expectations for {code} are satisfied."
            ),
            evidence={"code": code, "findings": findings},
            resolution_hint=(
                "Confirm the freight line is present and priced per the "
                "method's convention, or override if intentionally absent."
                if not passed else None
            ),
        )


# ── Opt-in registration ─────────────────────────────────────────────────────

_WH_GATE_CLASSES = (
    WarehouseOrderShipmentMethodUnknownGate,
    WarehouseOrderShipmentMethodArchetypeMismatchGate,
    WarehouseOrderFreightExpectationMismatchGate,
)


def register_warehouse_order_gates(registry: GateRegistry) -> tuple[Gate, ...]:
    """Register the three Warehouse Order gates on ``registry``. Idempotent.

    Not auto-registered at import time. Callers opt in explicitly.
    """
    existing_ids = {g.id for g in registry.list_gates()}
    registered: list[Gate] = []
    for cls in _WH_GATE_CLASSES:
        gate = cls()
        if gate.id in existing_ids:
            continue
        registry.register(gate)
        registered.append(gate)
    return tuple(registered)


__all__ = [
    "ARCHETYPE",
    "WarehouseOrderShipmentMethodUnknownGate",
    "WarehouseOrderShipmentMethodArchetypeMismatchGate",
    "WarehouseOrderFreightExpectationMismatchGate",
    "register_warehouse_order_gates",
]
