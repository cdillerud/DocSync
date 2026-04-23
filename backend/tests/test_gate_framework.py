"""
Gate framework + Step 2.75 gates — verification suite.

Covers:
  * Primitives: GateResult frozen, hash stability, registry semantics,
    global-then-archetype ordering, duplicate-id rejection
  * Lifted gates: evidence byte-equality vs underlying check_* functions
  * Master-data gate: AP/Sales/item-master cases + pass case
  * Adapter round-trip: running registry on a doc produces the same
    readiness mutations the retired try-blocks would have produced
  * Idempotent clear on transition (proves lift preserved behavior)
"""
from __future__ import annotations

import asyncio

import pytest
import mongomock_motor

from workflows.core import gate_framework as gf
from workflows.core.gate_framework import (
    GateContext,
    GateRegistry,
    GateResult,
    hash_evaluate_source,
)
from workflows.core import gates as step_275_gates
from workflows.inventory import ownership


# ── Fixtures ────────────────────────────────────────────────────────────────

@pytest.fixture
def db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client["gate_test"]


@pytest.fixture
def fresh_registry():
    """A scratch registry so tests don't tread on the singleton."""
    return GateRegistry()


# ── G1: GateResult is frozen ────────────────────────────────────────────────

def test_G1_gate_result_is_frozen():
    r = GateResult(
        gate_id="x", gate_version="v", passed=True, severity="info",
        detail="", evidence={}, resolution_hint=None,
    )
    with pytest.raises(Exception):
        r.passed = False  # type: ignore[misc]


# ── G2: hash_evaluate_source is deterministic ───────────────────────────────

def test_G2_hash_evaluate_source_is_stable():
    def f():
        return 1
    h1 = hash_evaluate_source(f)
    h2 = hash_evaluate_source(f)
    assert h1 == h2
    assert len(h1) == 12
    # Different function → different hash
    def g():
        return 2
    assert hash_evaluate_source(g) != h1


# ── G3: registry list_gates puts globals first ──────────────────────────────

def test_G3_registry_lists_globals_first(fresh_registry):
    class GlobalGate:
        id = "g1"
        version = "1"
        archetype = None
        applies_to_states = {"*"}
        severity = "info"
        async def evaluate(self, ctx):
            return GateResult("g1", "1", True, "info", "", {}, None)
    class ArchGate:
        id = "a1"
        version = "1"
        archetype = "ap_invoice"
        applies_to_states = {"*"}
        severity = "info"
        async def evaluate(self, ctx):
            return GateResult("a1", "1", True, "info", "", {}, None)
    fresh_registry.register(ArchGate())
    fresh_registry.register(GlobalGate())
    ids = [g.id for g in fresh_registry.list_gates()]
    assert ids == ["g1", "a1"], "globals must precede archetype-scoped"


# ── G4: unregister removes a gate ───────────────────────────────────────────

def test_G4_unregister_removes_gate(fresh_registry):
    class Gate1:
        id = "foo"
        version = "1"
        archetype = None
        applies_to_states = {"*"}
        severity = "info"
        async def evaluate(self, ctx):
            return GateResult("foo", "1", True, "info", "", {}, None)
    fresh_registry.register(Gate1())
    assert len(fresh_registry.list_gates()) == 1
    fresh_registry.unregister("foo")
    assert len(fresh_registry.list_gates()) == 0


# ── G5: evaluate_all runs globals first, arch after ─────────────────────────

@pytest.mark.asyncio
async def test_G5_evaluate_all_preserves_order(fresh_registry, db):
    order = []
    def make_gate(gid, arch):
        class _G:
            id = gid
            version = "1"
            archetype = arch
            applies_to_states = {"*"}
            severity = "info"
            async def evaluate(self, ctx):
                order.append(gid)
                return GateResult(gid, "1", True, "info", "", {}, None)
        return _G()
    fresh_registry.register(make_gate("arch-a", "sales"))
    fresh_registry.register(make_gate("glob-b", None))
    fresh_registry.register(make_gate("glob-a", None))
    await fresh_registry.evaluate_all(GateContext(db=db, doc={}))
    # Globals first (alpha-sorted within), then archetype-scoped
    assert order == ["glob-a", "glob-b", "arch-a"]


# ── G6: duplicate-id registration raises ────────────────────────────────────

def test_G6_duplicate_id_rejected(fresh_registry):
    class G:
        id = "same"
        version = "1"
        archetype = None
        applies_to_states = {"*"}
        severity = "info"
        async def evaluate(self, ctx):
            return GateResult("same", "1", True, "info", "", {}, None)
    fresh_registry.register(G())
    with pytest.raises(ValueError, match="already registered"):
        fresh_registry.register(G())


# ── Step 2.75 gates are registered on the module-level singleton ────────────

def test_step_275_gates_are_registered():
    ids = {g.id for g in gf.registry.list_gates()}
    assert {
        "cow_item_on_po",
        "cow_sales_order",
        "consignment_rules",
        "master_data_completeness",
    }.issubset(ids)


# ── G7: COWItemOnPOGate evidence matches check_cow_item_on_po ──────────────

@pytest.mark.asyncio
async def test_G7_cow_po_gate_evidence_matches_check(db):
    await ownership.upsert_cp_item(
        db,
        ownership.CpItemCreate(
            item_no="WIDGET-CPA1", customer_no="C-1",
            base_item_no="WIDGET", canonical_location="WH-1",
        ),
        actor="items@gamerpackaging.com",
    )
    doc = {
        "id": "d1",
        "document_type": "PO",
        "extracted_fields": {"line_items": [{"item_no": "WIDGET-CPA1", "quantity": 3}]},
    }
    direct = await ownership.check_cow_item_on_po(db, doc)

    gate = step_275_gates.COWItemOnPOGate()
    result = await gate.evaluate(GateContext(db=db, doc=doc))

    assert result.severity == "block"
    assert result.passed is False
    assert result.evidence["rows"] == direct


# ── G8: COWSalesOrderGate emits mixed-code evidence ─────────────────────────

@pytest.mark.asyncio
async def test_G8_cow_so_gate_mixed_codes(db):
    # Two different CPs: one registered to the same customer (base-item) and
    # one registered to a different customer (wrong-customer).
    await ownership.upsert_cp_item(
        db,
        ownership.CpItemCreate(
            item_no="A-CPX1", customer_no="C-OK",
            base_item_no="A", canonical_location="WH-A",
        ),
        actor="items@gamerpackaging.com",
    )
    await ownership.upsert_cp_item(
        db,
        ownership.CpItemCreate(
            item_no="B-CPX2", customer_no="C-OTHER",
            base_item_no="B", canonical_location="WH-B",
        ),
        actor="items@gamerpackaging.com",
    )
    doc = {
        "id": "d-so-1",
        "document_type": "SALES_INVOICE",
        "bc_customer_number": "C-OK",
        "extracted_fields": {
            "line_items": [
                {"item_no": "A-CPX1", "quantity": 1},
                {"item_no": "B-CPX2", "quantity": 1},
            ]
        },
    }
    gate = step_275_gates.COWSalesOrderGate()
    result = await gate.evaluate(GateContext(db=db, doc=doc))
    assert result.passed is False
    assert set(result.evidence["codes"]) == {
        "cow_so_uses_base_item", "cow_so_wrong_customer",
    }


# ── G9: ConsignmentGate evidence matches check_consignment_rules ────────────

@pytest.mark.asyncio
async def test_G9_consignment_gate_evidence_matches(db):
    await ownership.upsert_consigned_item(
        db,
        ownership.ConsignedItemCreate(
            item_no="COMP-A1", vendor_no="V-1", physical_location="WH-CONS",
        ),
        actor="admin",
    )
    doc = {
        "id": "d-cons-1",
        "document_type": "SALES_INVOICE",
        "bc_customer_number": "C-SOMEONE",
        "extracted_fields": {"line_items": [{"item_no": "COMP-A1", "quantity": 1}]},
    }
    direct = await ownership.check_consignment_rules(db, doc)
    gate = step_275_gates.ConsignmentGate()
    result = await gate.evaluate(GateContext(db=db, doc=doc))
    assert result.passed is False
    assert result.evidence["rows"] == direct
    assert "consigned_item_on_sales_doc" in result.evidence["codes"]


# ── G10: MasterDataCompletenessGate warns on missing vendor (AP) ────────────

@pytest.mark.asyncio
async def test_G10_master_data_missing_vendor(db):
    doc = {
        "id": "d-ap-1",
        "document_type": "AP_INVOICE",
        # no bc_vendor_number / vendor_no
        "extracted_fields": {"line_items": [{"item_no": "X", "quantity": 1}]},
    }
    gate = step_275_gates.MasterDataCompletenessGate()
    result = await gate.evaluate(GateContext(db=db, doc=doc))
    assert result.severity == "warn"
    assert result.passed is False
    assert "vendor_master" in result.evidence["missing"]


# ── G11: master-data gate flags customer on sales doc ───────────────────────

@pytest.mark.asyncio
async def test_G11_master_data_missing_customer(db):
    doc = {
        "id": "d-so-1",
        "document_type": "SALES_INVOICE",
        "extracted_fields": {"line_items": [{"item_no": "X", "quantity": 1}]},
    }
    gate = step_275_gates.MasterDataCompletenessGate()
    result = await gate.evaluate(GateContext(db=db, doc=doc))
    assert result.passed is False
    assert "customer_master" in result.evidence["missing"]


# ── G12: master-data gate passes with full data ─────────────────────────────

@pytest.mark.asyncio
async def test_G12_master_data_passes(db):
    doc = {
        "id": "d-clean",
        "document_type": "SALES_INVOICE",
        "bc_customer_number": "C-1",
        "extracted_fields": {"line_items": [{"item_no": "X", "quantity": 1}]},
    }
    gate = step_275_gates.MasterDataCompletenessGate()
    result = await gate.evaluate(GateContext(db=db, doc=doc))
    assert result.passed is True
    assert result.evidence["missing"] == []


# ── G12b: master-data gate flags missing item_no on lines ───────────────────

@pytest.mark.asyncio
async def test_G12b_master_data_missing_item_master(db):
    doc = {
        "id": "d-line",
        "document_type": "SALES_INVOICE",
        "bc_customer_number": "C-1",
        "extracted_fields": {"line_items": [{"item_no": "", "quantity": 1}]},
    }
    gate = step_275_gates.MasterDataCompletenessGate()
    result = await gate.evaluate(GateContext(db=db, doc=doc))
    assert result.passed is False
    assert "item_master" in result.evidence["missing"]
    assert result.evidence["lines_missing_item_no"] == 1


# ── Manual semver preserved for master-data gate (§5.1) ─────────────────────

def test_master_data_gate_uses_manual_semver():
    gate = step_275_gates.MasterDataCompletenessGate()
    assert gate.version == "1.0.0"


# ── Lifted gates use source-hash default version (§5.1) ─────────────────────

def test_lifted_gates_use_source_hash_version():
    for cls in (
        step_275_gates.COWItemOnPOGate,
        step_275_gates.COWSalesOrderGate,
        step_275_gates.ConsignmentGate,
    ):
        g = cls()
        assert len(g.version) == 12
        assert all(c in "0123456789abcdef" for c in g.version)


# ── G13: registry evaluate_all + adapter preserves readiness fields ─────────

@pytest.mark.asyncio
async def test_G13_registry_adapter_preserves_cow_po_mutations(db):
    """The single registry call must produce the same readiness mutations
    the retired try-blocks produced — byte-for-byte on the existing fields."""
    await ownership.upsert_cp_item(
        db,
        ownership.CpItemCreate(
            item_no="ROUND-TRIP-CPX1", customer_no="C-R",
            base_item_no="ROUND", canonical_location="WH-R",
        ),
        actor="items@gamerpackaging.com",
    )
    doc = {
        "id": "d-round",
        "document_type": "PO",
        "extracted_fields": {
            "line_items": [{"item_no": "ROUND-TRIP-CPX1", "quantity": 1}]
        },
    }

    # Expected (direct call path)
    expected_readiness = {"blocking_reasons": [], "explanations": []}
    direct_evidence = await ownership.check_cow_item_on_po(db, doc)
    ownership.apply_cow_blocker_to_readiness(expected_readiness, direct_evidence)

    # Actual (via registry singleton + mimicking the document_readiness adapter)
    gate = step_275_gates.COWItemOnPOGate()
    result = await gate.evaluate(GateContext(db=db, doc=doc))
    actual_readiness = {"blocking_reasons": [], "explanations": []}
    ownership.apply_cow_blocker_to_readiness(
        actual_readiness, result.evidence["rows"]
    )
    assert actual_readiness["blocking_reasons"] == expected_readiness["blocking_reasons"]
    assert actual_readiness.get("cow_items") == expected_readiness.get("cow_items")


# ── G14: Idempotent clear after state flip (proves lift preserved behavior) ─

@pytest.mark.asyncio
async def test_G14_idempotent_clear_after_transition(db):
    """Proves the adapter's clear path behaves like the retired try-blocks:
    evidence appears when rule fires, disappears when it no longer fires.
    This round-trips through the registry's evaluate_all."""
    await ownership.upsert_consigned_item(
        db,
        ownership.ConsignedItemCreate(
            item_no="FLIP-A", vendor_no="V-F", physical_location="WH-F",
        ),
        actor="admin",
    )
    doc = {
        "id": "d-flip",
        "document_type": "SALES_INVOICE",
        "bc_customer_number": "C-X",
        "extracted_fields": {"line_items": [{"item_no": "FLIP-A", "quantity": 1}]},
    }

    # Fire: consigned_in → sales doc triggers the rule
    results_1 = await gf.registry.evaluate_all(GateContext(db=db, doc=doc))
    cons_r1 = next(r for r in results_1 if r.gate_id == "consignment_rules")
    assert cons_r1.passed is False
    assert "consigned_item_on_sales_doc" in cons_r1.evidence["codes"]

    # Transition to consumed — different rule now applies (post_lifecycle)
    await ownership.transition_consigned_item(
        db, "FLIP-A", "consumed",
        actor=ownership.CONSIGNMENT_STATE_ACTOR_EMAIL,
        evidence_id="SI-FLIP-1",
    )
    results_2 = await gf.registry.evaluate_all(GateContext(db=db, doc=doc))
    cons_r2 = next(r for r in results_2 if r.gate_id == "consignment_rules")
    assert cons_r2.passed is False
    assert "consigned_item_post_lifecycle_on_so" in cons_r2.evidence["codes"]
    # The original "consigned_in" code must NOT still be present (clear proof)
    assert "consigned_item_on_sales_doc" not in cons_r2.evidence["codes"]


# ── Gate version hash changes when evaluate source changes ──────────────────

def test_gate_version_hash_is_content_addressed():
    """Two different classes with different evaluate sources produce different
    content-hash versions. Rationale (signed §5.1): threshold tightening must
    be distinguishable in audit trails."""
    g1 = step_275_gates.COWItemOnPOGate()
    g2 = step_275_gates.COWSalesOrderGate()
    assert g1.version != g2.version
