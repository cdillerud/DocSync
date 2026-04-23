"""
GPI Hub — Reroute gates (Lane C Step 7, narrowed)

Two gates triggered by ``location_code == "001"`` (the canonical
"rerouted warehouse → drop ship" signal, already authoritative in the
freight-side code paths under ``workflows/freight/item_charges.py``
and ``services/freight_gl_routing_service.py``).

This package is the sales-archetype companion: it surfaces the same
condition at the SO layer and warns on two specific gaps. It does NOT
duplicate any freight-side routing logic.

Severity ledger (signed):
  - reroute_location_without_original_so .......... warn
  - reroute_requires_drop_ship_linkage ............ warn

Non-duplication with live SO-008 (Drop Ship PO Needed):
  - SO-008 trigger axis: ``is_drop_ship`` keyword/line-flag detection
    in ``services/so_rules_engine.py``.
  - Reroute trigger axis: ``location_code == "001"``.
  The two axes are orthogonal. On a rerouted doc that ALSO carries
  a drop-ship keyword, both predicates may fire — they read different
  facts and report different gaps. A pytest case asserts this.

Opt-in registration only.
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


ARCHETYPE = "reroute"

# Canonical reroute location code. Sourced from the live freight-side
# constant (``workflows.freight.item_charges.LOCATION_REROUTED``) — we
# do NOT import that symbol to keep the packages decoupled, but the
# value must match.
REROUTE_LOCATION_CODE = "001"


# ── Signal readers ─────────────────────────────────────────────────────────

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


def _doc_location_code(ctx: GateContext) -> str:
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    for key in ("location_code", "ship_to_location_code", "ship_to_code"):
        v = ef.get(key) or doc.get(key)
        if v:
            return str(v).strip()
    return ""


def _is_reroute_doc(ctx: GateContext) -> bool:
    """Trigger axis: ``location_code == "001"`` at doc or line level."""
    if _doc_location_code(ctx) == REROUTE_LOCATION_CODE:
        return True
    for line in _line_items(ctx):
        loc = line.get("location_code") or line.get("location")
        if loc and str(loc).strip() == REROUTE_LOCATION_CODE:
            return True
    return False


def _original_so_reference(ctx: GateContext) -> str:
    """Fact: did the document carry a reference back to the original
    warehouse SO that was rerouted? The live freight-side resolver
    (``bc_reference_cache_service.find_so_for_rerouted_po``) looks up
    the original SO from BC when absent — we read only what is already
    on the document.
    """
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    for key in (
        "original_sales_order",
        "original_so_no",
        "rerouted_from_so",
        "original_wh_so",
    ):
        v = ef.get(key) or doc.get(key)
        if v:
            return str(v).strip()
    return ""


def _has_drop_ship_po_linkage(ctx: GateContext) -> bool:
    """Same PO-linkage predicate as the DS package — intentional, so
    that a rerouted doc with a linked PO clears both gates cleanly.
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


# ── Gate 1: reroute location without original SO reference (WARN) ──────────

class RerouteLocationWithoutOriginalSoGate:
    """Warn when a rerouted SO carries no reference back to the
    original warehouse SO it was rerouted from.

    Mirrors the existing freight-side ``rerouted_missing_so`` warning
    at the sales-archetype layer. Does NOT invoke any SO-resolution
    logic — reads only what is already on the document.
    """

    id = "reroute_location_without_original_so"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "warn"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _is_reroute_doc(ctx):
            return _not_applicable(
                self.id, self.version,
                f"no location_code=={REROUTE_LOCATION_CODE!r} signal on document",
            )

        original_so = _original_so_reference(ctx)
        if original_so:
            return GateResult(
                gate_id=self.id, gate_version=self.version,
                passed=True, severity="warn",
                detail="Reroute doc references original warehouse SO.",
                evidence={
                    "location_code": REROUTE_LOCATION_CODE,
                    "original_so": original_so,
                },
                resolution_hint=None,
            )

        return GateResult(
            gate_id=self.id, gate_version=self.version,
            passed=False, severity="warn",
            detail=(
                f"Rerouted SO (location_code=={REROUTE_LOCATION_CODE}) "
                "carries no original warehouse SO reference on the document."
            ),
            evidence={
                "location_code": REROUTE_LOCATION_CODE,
                "original_so": None,
            },
            resolution_hint=(
                "Capture the original warehouse SO number on the document "
                "(extracted_fields.original_sales_order / original_so_no / "
                "rerouted_from_so). Freight-side resolvers may fill this in "
                "downstream, but capturing it here keeps the sales record "
                "auditable at intake."
            ),
        )


# ── Gate 2: reroute requires drop-ship PO linkage (WARN) ───────────────────

class RerouteRequiresDropShipLinkageGate:
    """Warn when a rerouted SO has no drop-ship PO linkage.

    NON-DUPLICATION with live SO-008 (Drop Ship PO Needed):
      - SO-008 fires on keyword-detected ``is_drop_ship``.
      - This gate fires on location_code=="001" regardless of keywords.
    A rerouted doc without drop-ship keywords would miss SO-008
    entirely; this gate catches that gap at the sales-archetype layer.
    Severity is WARN (not block) because SO-008 remains the authoritative
    blocker for the keyword-detected drop-ship case.
    """

    id = "reroute_requires_drop_ship_linkage"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "warn"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _is_reroute_doc(ctx):
            return _not_applicable(
                self.id, self.version,
                f"no location_code=={REROUTE_LOCATION_CODE!r} signal on document",
            )

        if _has_drop_ship_po_linkage(ctx):
            return GateResult(
                gate_id=self.id, gate_version=self.version,
                passed=True, severity="warn",
                detail="Drop-ship PO linkage is present on the rerouted SO.",
                evidence={
                    "location_code": REROUTE_LOCATION_CODE,
                    "has_po_linkage": True,
                },
                resolution_hint=None,
            )

        return GateResult(
            gate_id=self.id, gate_version=self.version,
            passed=False, severity="warn",
            detail=(
                f"Rerouted SO (location_code=={REROUTE_LOCATION_CODE}) has "
                "no linked drop-ship PO. This is the reroute-archetype "
                "companion to SO-008; the live SO-008 block only fires on "
                "keyword-detected drop-ship docs."
            ),
            evidence={
                "location_code": REROUTE_LOCATION_CODE,
                "has_po_linkage": False,
            },
            resolution_hint=(
                "Create or link the drop-ship purchase order for this "
                "rerouted SO and attach the PO number to the document."
            ),
        )


# ── Opt-in registration ─────────────────────────────────────────────────────

_RR_GATE_CLASSES = (
    RerouteLocationWithoutOriginalSoGate,
    RerouteRequiresDropShipLinkageGate,
)


def register_reroute_gates(registry: GateRegistry) -> tuple[Gate, ...]:
    """Register Reroute gates on ``registry``. Idempotent.

    Not auto-registered at import time. Callers opt in explicitly.
    """
    existing_ids = {g.id for g in registry.list_gates()}
    registered: list[Gate] = []
    for cls in _RR_GATE_CLASSES:
        gate = cls()
        if gate.id in existing_ids:
            continue
        registry.register(gate)
        registered.append(gate)
    return tuple(registered)


__all__ = [
    "ARCHETYPE",
    "REROUTE_LOCATION_CODE",
    "RerouteLocationWithoutOriginalSoGate",
    "RerouteRequiresDropShipLinkageGate",
    "register_reroute_gates",
]
