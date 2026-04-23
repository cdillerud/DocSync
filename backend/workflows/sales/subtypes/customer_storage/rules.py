"""
GPI Hub — Customer Storage gates (Lane C Step 7, narrowed)

Two signal-driven gates for the Customer Storage archetype. No
classifier, no registry, no writes. Gates short-circuit to ``info``
when no customer-storage signal is present on the document — zero
false positives on non-CS docs.

Severity ledger (signed):
  - customer_storage_without_storage_agreement .... warn
  - customer_storage_ship_out_missing_release ..... block

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


ARCHETYPE = "customer_storage"


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


def _is_customer_storage_doc(ctx: GateContext) -> bool:
    """Document-level storage signal OR any line marks stored ware."""
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    if ef.get("is_customer_storage") is True:
        return True
    for line in _line_items(ctx):
        if line.get("from_customer_storage") is True:
            return True
    return False


def _storage_agreement_id(ctx: GateContext) -> str:
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    v = ef.get("storage_agreement_id") or doc.get("storage_agreement_id")
    return str(v).strip() if v else ""


def _storage_release_id(ctx: GateContext) -> str:
    doc = ctx.doc or {}
    ef = doc.get("extracted_fields") or {}
    v = ef.get("storage_release_id") or doc.get("storage_release_id")
    return str(v).strip() if v else ""


def _ship_out_lines(ctx: GateContext) -> list[Mapping[str, Any]]:
    """Lines flagged as from_customer_storage with positive quantity —
    these are the ship-out releases that require a release authorization."""
    out: list[Mapping[str, Any]] = []
    for line in _line_items(ctx):
        if line.get("from_customer_storage") is not True:
            continue
        qty = line.get("quantity")
        if qty is None:
            qty = line.get("qty")
        try:
            qty_f = float(qty) if qty is not None else 0.0
        except (TypeError, ValueError):
            qty_f = 0.0
        if qty_f > 0:
            out.append(line)
    return out


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


# ── Gate 1: storage-agreement missing (WARN) ───────────────────────────────

class CustomerStorageWithoutStorageAgreementGate:
    """Warn when a customer-storage sales doc lacks ``storage_agreement_id``."""

    id = "customer_storage_without_storage_agreement"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "warn"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _is_customer_storage_doc(ctx):
            return _not_applicable(
                self.id, self.version,
                "no customer-storage signal on document",
            )

        agreement = _storage_agreement_id(ctx)
        if agreement:
            return GateResult(
                gate_id=self.id, gate_version=self.version,
                passed=True, severity="warn",
                detail="Customer-storage agreement reference is present.",
                evidence={"storage_agreement_id": agreement},
                resolution_hint=None,
            )

        return GateResult(
            gate_id=self.id, gate_version=self.version,
            passed=False, severity="warn",
            detail=(
                "Document references customer-stored ware but carries no "
                "storage_agreement_id."
            ),
            evidence={"storage_agreement_id": None},
            resolution_hint=(
                "Attach the applicable customer-storage agreement ID to "
                "the document (extracted_fields.storage_agreement_id)."
            ),
        )


# ── Gate 2: ship-out without release authorization (BLOCK) ─────────────────

class CustomerStorageShipOutMissingReleaseGate:
    """Block when stored ware is being shipped out without a release ID.

    A "ship-out" is any line with ``from_customer_storage=true`` and a
    positive quantity. Presence of such lines requires a
    ``storage_release_id`` on the document.
    """

    id = "customer_storage_ship_out_missing_release"
    archetype: Optional[str] = ARCHETYPE
    applies_to_states: Set[str] = {"*"}
    severity = "block"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        if not _is_customer_storage_doc(ctx):
            return _not_applicable(
                self.id, self.version,
                "no customer-storage signal on document",
            )

        ship_out = _ship_out_lines(ctx)
        if not ship_out:
            return _not_applicable(
                self.id, self.version,
                "no ship-out lines (from_customer_storage lines have qty<=0)",
            )

        release = _storage_release_id(ctx)
        if release:
            return GateResult(
                gate_id=self.id, gate_version=self.version,
                passed=True, severity="block",
                detail=(
                    f"Storage release authorization is present for "
                    f"{len(ship_out)} ship-out line(s)."
                ),
                evidence={
                    "storage_release_id": release,
                    "ship_out_line_count": len(ship_out),
                },
                resolution_hint=None,
            )

        return GateResult(
            gate_id=self.id, gate_version=self.version,
            passed=False, severity="block",
            detail=(
                f"Stored ware ship-out detected on {len(ship_out)} line(s) "
                "but no storage_release_id is present on the document."
            ),
            evidence={
                "storage_release_id": None,
                "ship_out_line_count": len(ship_out),
            },
            resolution_hint=(
                "Obtain a customer-storage release authorization and attach "
                "it to the document (extracted_fields.storage_release_id) "
                "before the sales document can proceed."
            ),
        )


# ── Opt-in registration ─────────────────────────────────────────────────────

_CS_GATE_CLASSES = (
    CustomerStorageWithoutStorageAgreementGate,
    CustomerStorageShipOutMissingReleaseGate,
)


def register_customer_storage_gates(registry: GateRegistry) -> tuple[Gate, ...]:
    """Register Customer Storage gates on ``registry``. Idempotent.

    Not auto-registered at import time. Callers opt in explicitly.
    """
    existing_ids = {g.id for g in registry.list_gates()}
    registered: list[Gate] = []
    for cls in _CS_GATE_CLASSES:
        gate = cls()
        if gate.id in existing_ids:
            continue
        registry.register(gate)
        registered.append(gate)
    return tuple(registered)


__all__ = [
    "ARCHETYPE",
    "CustomerStorageWithoutStorageAgreementGate",
    "CustomerStorageShipOutMissingReleaseGate",
    "register_customer_storage_gates",
]
