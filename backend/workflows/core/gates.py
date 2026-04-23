"""
Concrete gates registered at import time — Lane C Step 2.75.

Three lifted adapters over existing ownership/consignment checks (block) plus
one new master-data-completeness gate (warn). All four are global
(archetype=None) per signed §3 row 2.75.

The lifted gates delegate to the functions in workflows.inventory.ownership
verbatim — no business-rule re-implementation — so the 55 existing
Step 1 + Step 2 tests continue to cover the underlying logic unchanged.
"""
from __future__ import annotations

from typing import Dict, Optional, Set

from workflows.core.gate_framework import (
    Gate,
    GateContext,
    GateResult,
    hash_evaluate_source,
    registry,
)
from workflows.inventory import ownership


# ── Lifted gate #1: Customer-Owned Ware on PO / Adj-journal ─────────────────

class COWItemOnPOGate:
    id = "cow_item_on_po"
    archetype: Optional[str] = None
    applies_to_states: Set[str] = {"*"}
    severity = "block"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        evidence_rows = await ownership.check_cow_item_on_po(ctx.db, ctx.doc)
        passed = len(evidence_rows) == 0
        return GateResult(
            gate_id=self.id,
            gate_version=self.version,
            passed=passed,
            severity="block",
            detail=(
                f"{len(evidence_rows)} CP line(s) flagged on PO/adjustment doc."
                if not passed else "No CP items flagged."
            ),
            evidence={"rows": evidence_rows},
            resolution_hint=(
                "Route CP items through an inventory adjustment journal into the "
                "canonical_location, or update the CP item registry."
                if not passed else None
            ),
        )


# ── Lifted gate #2: Customer-Owned Ware on Sales doc ────────────────────────

class COWSalesOrderGate:
    id = "cow_sales_order"
    archetype: Optional[str] = None
    applies_to_states: Set[str] = {"*"}
    severity = "block"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        evidence_rows = await ownership.check_cow_so_uses_base_item(ctx.db, ctx.doc)
        passed = len(evidence_rows) == 0
        codes = sorted({e["blocker_code"] for e in evidence_rows})
        return GateResult(
            gate_id=self.id,
            gate_version=self.version,
            passed=passed,
            severity="block",
            detail=(
                f"{len(evidence_rows)} CP line(s) flagged on sales doc; codes={codes}"
                if not passed else "No CP items flagged on sales doc."
            ),
            evidence={"rows": evidence_rows, "codes": codes},
            resolution_hint=(
                "Correct sales lines to the recommended_base_item_no or update the "
                "CP item registry to reflect the true customer."
                if not passed else None
            ),
        )


# ── Lifted gate #3: Vendor Consignment rules (all 5) ────────────────────────

class ConsignmentGate:
    id = "consignment_rules"
    archetype: Optional[str] = None
    applies_to_states: Set[str] = {"*"}
    severity = "block"

    def __init__(self) -> None:
        self.version = hash_evaluate_source(self.evaluate)

    async def evaluate(self, ctx: GateContext) -> GateResult:
        evidence_rows = await ownership.check_consignment_rules(ctx.db, ctx.doc)
        passed = len(evidence_rows) == 0
        codes = sorted({e["blocker_code"] for e in evidence_rows})
        return GateResult(
            gate_id=self.id,
            gate_version=self.version,
            passed=passed,
            severity="block",
            detail=(
                f"{len(evidence_rows)} consignment violation(s); codes={codes}"
                if not passed else "No consignment rule violations."
            ),
            evidence={"rows": evidence_rows, "codes": codes},
            resolution_hint=(
                "Move the consigned item through its legal state transition "
                "(consumed or returned) before posting this document."
                if not passed else None
            ),
        )


# ── New gate: Master-Data Completeness (warn-only) ──────────────────────────

_AP_DOC_TYPES = frozenset({"ap_invoice", "purchase_invoice", "apinvoice", "po", "purchase_order"})
_SALES_DOC_TYPES = frozenset({
    "sales_invoice", "sales_order", "so_confirmation",
    "ds_sales_order", "wh_sales_order",
})


def _normalize_doctype(doc: Dict) -> str:
    return str(
        doc.get("document_type")
        or doc.get("doc_type")
        or doc.get("suggested_job_type")
        or ""
    ).strip().lower().replace(" ", "_")


def _has_field(doc: Dict, *names: str) -> bool:
    extracted = doc.get("extracted_fields") or {}
    for name in names:
        for src in (doc, extracted):
            v = src.get(name)
            if v not in (None, "", []):
                return True
    return False


class MasterDataCompletenessGate:
    """Global, warn-severity master-data completeness check.

    Step 2.75 ships this at warn severity per signed §3. Step 9 upgrades to
    block once every archetype's required master-data set is final.

    Manual semver version so that the step-9 tightening (and any interim rule
    adjustments) produce a human-readable audit trail via GateResult.gate_version.
    """

    id = "master_data_completeness"
    version = "1.0.0"
    archetype: Optional[str] = None
    applies_to_states: Set[str] = {"*"}
    severity = "warn"

    async def evaluate(self, ctx: GateContext) -> GateResult:
        doc = ctx.doc
        doctype = _normalize_doctype(doc)
        missing = []

        if doctype in _AP_DOC_TYPES:
            if not _has_field(doc, "bc_vendor_number", "vendor_no"):
                missing.append("vendor_master")

        if doctype in _SALES_DOC_TYPES:
            if not _has_field(doc, "bc_customer_number", "customer_no"):
                missing.append("customer_master")

        lines = (doc.get("extracted_fields") or {}).get("line_items") or []
        lines_missing_item_no = sum(
            1 for ln in lines
            if isinstance(ln, dict) and not (ln.get("item_no") or "").strip()
        )
        if lines_missing_item_no > 0:
            missing.append("item_master")

        passed = len(missing) == 0
        return GateResult(
            gate_id=self.id,
            gate_version=self.version,
            passed=passed,
            severity="warn",
            detail=(
                f"Master-data gaps: {', '.join(missing)}"
                if not passed else "Master data complete."
            ),
            evidence={
                "missing": missing,
                "lines_missing_item_no": lines_missing_item_no,
            },
            resolution_hint=(
                "Resolve the vendor/customer in Business Central or update the "
                "item master mappings before submitting this document."
                if not passed else None
            ),
        )


# ── Self-registration at import time ────────────────────────────────────────

def register_step_275_gates() -> None:
    """Idempotent registration — safe to call multiple times (e.g., in tests)."""
    for cls in (
        COWItemOnPOGate,
        COWSalesOrderGate,
        ConsignmentGate,
        MasterDataCompletenessGate,
    ):
        gate = cls()
        if gate.id in {g.id for g in registry.list_gates()}:
            continue
        registry.register(gate)


# Import-time side effect (signed §5 pattern: archetype modules self-register)
register_step_275_gates()
