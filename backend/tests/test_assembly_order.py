"""Pytest for Lane C Step 4b — Assembly Order classifier + gates."""

from __future__ import annotations

import uuid
from pathlib import Path

import mongomock_motor
import pytest

from workflows.core.gate_framework import GateContext, GateRegistry
from workflows.inventory import lineage
from workflows.sales.subtypes.assembly_order import (
    ASSEMBLY_BOM_COMPLETENESS_STRICT,
    ASSEMBLY_CONFIDENCE_THRESHOLD,
    AssemblyClassification,
    AssemblyOrderBomCompletenessGate,
    AssemblyOrderProducedOverdrawGate,
    KNOWN_ASSEMBLY_CUSTOMERS,
    classify_assembly_order,
    register_assembly_order_gates,
)


@pytest.fixture
def mongo_db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client[f"test_assembly_{uuid.uuid4().hex[:8]}"]


# ===========================================================================
# 1. Classifier
# ===========================================================================

class TestClassifier:
    def test_no_signals_returns_sentinel(self):
        r = classify_assembly_order({}, {})
        assert r.is_assembly_order is False
        assert r.confidence == 0.0
        assert r.signals == ()
        assert r.reasons == ("no signals found",)

    def test_order_type_assembly_triggers_true(self):
        r = classify_assembly_order({}, {"order_type": "Assembly"})
        assert r.is_assembly_order is True
        assert "order_type_assembly" in r.signals

    def test_order_type_kit_triggers_true(self):
        r = classify_assembly_order({}, {"order_type": "kit"})
        assert r.is_assembly_order is True

    def test_order_type_work_order_triggers_signal(self):
        r = classify_assembly_order({}, {"order_type": "work_order"})
        assert "order_type_assembly" in r.signals

    def test_bom_field_with_entries_triggers_signal(self):
        r = classify_assembly_order(
            {},
            {"bom": [{"item_no": "COMP-A", "qty": 1}]},
        )
        assert "bom_field_present" in r.signals

    def test_empty_bom_list_does_not_trigger(self):
        r = classify_assembly_order({}, {"bom": []})
        assert "bom_field_present" not in r.signals

    def test_assembly_keyword_in_text_triggers_signal(self):
        r = classify_assembly_order(
            {"raw_text": "Please fulfill this assembly order"}, {},
        )
        assert "assembly_keyword" in r.signals

    def test_kit_keyword_in_text_triggers_signal(self):
        r = classify_assembly_order(
            {"raw_text": "kit assembly required"}, {},
        )
        assert "kit_keyword" in r.signals

    def test_drop_ship_keyword_drives_negative(self):
        r = classify_assembly_order(
            {"raw_text": "drop ship directly; assembly order"}, {},
        )
        # Positive (assembly_keyword) + negative (drop_ship_keyword):
        # DS weight (-0.8) dominates the assembly weight (+0.5) so net is
        # under threshold.
        assert r.is_assembly_order is False
        assert "drop_ship_keyword" in r.signals

    def test_drop_ship_location_drives_negative(self):
        r = classify_assembly_order(
            {"raw_text": "assembly order"},
            {"ship_to_location_code": "00"},
        )
        assert "drop_ship_location" in r.signals

    def test_known_customers_seed_is_empty_per_sign_off(self):
        # User sign-off rule from Step 4a: no hardcoded customer-specific
        # knowledge. The seed hook exists but ships empty.
        assert KNOWN_ASSEMBLY_CUSTOMERS == ()

    def test_customer_no_never_alone_triggers_true_when_seed_empty(self):
        r = classify_assembly_order({}, {"customer_no": "C-99999"})
        assert "known_assembly_customer" not in r.signals

    def test_confidence_clamped_to_unit_interval(self):
        r = classify_assembly_order(
            {"raw_text": "assembly order; kit assembly"},
            {"order_type": "assembly", "bom": [{"item_no": "X", "qty": 1}]},
        )
        assert 0.0 <= r.confidence <= 1.0

    def test_returns_frozen_dataclass(self):
        r = classify_assembly_order({}, {"order_type": "assembly"})
        assert isinstance(r, AssemblyClassification)
        with pytest.raises(Exception):
            r.confidence = 0.0  # type: ignore[misc]

    def test_strict_flag_ships_as_false(self):
        # Hook preserved for later tightening; not consumed this pass.
        assert ASSEMBLY_BOM_COMPLETENESS_STRICT is False

    def test_threshold_constant_is_half(self):
        assert ASSEMBLY_CONFIDENCE_THRESHOLD == 0.5


# ===========================================================================
# 2. Gates — produced_overdraw (block)
# ===========================================================================

def _assembly_doc(work_ref="WO-1", lines=None, extra_ef=None):
    ef = {
        "work_order_ref": work_ref,
        "order_type": "assembly",
        "line_items": lines or [],
    }
    if extra_ef:
        ef.update(extra_ef)
    return {"id": "doc-1", "raw_text": "assembly order", "extracted_fields": ef}


def _non_assembly_doc():
    return {
        "id": "doc-2",
        "raw_text": "standard warehouse shipment",
        "extracted_fields": {"line_items": [{"item_no": "X", "quantity": 1}]},
    }


@pytest.mark.asyncio
class TestProducedOverdrawGate:
    async def test_ship_within_produced_passes(self, mongo_db):
        await lineage.record_assembly_produced(
            mongo_db, work_order_ref="WO-1", parent_item_no="P",
            qty=10, location="WH",
        )
        gate = AssemblyOrderProducedOverdrawGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_assembly_doc(lines=[{"item_no": "P", "ship_qty": 6}]),
        )
        result = await gate.evaluate(ctx)
        assert result.passed is True
        assert result.severity == "block"

    async def test_ship_exceeding_produced_blocks(self, mongo_db):
        await lineage.record_assembly_produced(
            mongo_db, work_order_ref="WO-1", parent_item_no="P",
            qty=4, location="WH",
        )
        gate = AssemblyOrderProducedOverdrawGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_assembly_doc(lines=[{"item_no": "P", "ship_qty": 10}]),
        )
        result = await gate.evaluate(ctx)
        assert result.passed is False
        assert result.severity == "block"
        ov = result.evidence["overdraw_lines"][0]
        assert ov["parent_item_no"] == "P"
        assert ov["ship_qty"] == 10
        assert ov["produced_qty"] == 4.0

    async def test_no_work_order_ref_is_not_applicable(self, mongo_db):
        gate = AssemblyOrderProducedOverdrawGate()
        # Doc looks like assembly but lacks work_order_ref.
        ctx = GateContext(
            db=mongo_db,
            doc={
                "id": "d", "raw_text": "assembly order",
                "extracted_fields": {"order_type": "assembly", "line_items": []},
            },
        )
        result = await gate.evaluate(ctx)
        assert result.passed is True
        assert result.severity == "info"

    async def test_non_assembly_doc_gets_defensive_info_passthrough(self, mongo_db):
        gate = AssemblyOrderProducedOverdrawGate()
        ctx = GateContext(db=mongo_db, doc=_non_assembly_doc())
        result = await gate.evaluate(ctx)
        assert result.passed is True
        assert result.severity == "info"
        assert "not applicable" in result.detail.lower()


# ===========================================================================
# 3. Gates — bom_completeness (warn)
# ===========================================================================

@pytest.mark.asyncio
class TestBomCompletenessGate:
    async def test_all_components_consumed_passes(self, mongo_db):
        for comp in ("COMP-A", "COMP-B"):
            await lineage.record_component_consumed(
                mongo_db, work_order_ref="WO-1", component_item_no=comp,
                qty=1, source_location="WH",
            )
        gate = AssemblyOrderBomCompletenessGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_assembly_doc(extra_ef={
                "bom": [
                    {"item_no": "COMP-A", "qty": 1},
                    {"item_no": "COMP-B", "qty": 1},
                ],
            }),
        )
        result = await gate.evaluate(ctx)
        assert result.passed is True

    async def test_missing_component_consumption_warns(self, mongo_db):
        await lineage.record_component_consumed(
            mongo_db, work_order_ref="WO-1", component_item_no="COMP-A",
            qty=1, source_location="WH",
        )
        gate = AssemblyOrderBomCompletenessGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_assembly_doc(extra_ef={
                "bom": [
                    {"item_no": "COMP-A", "qty": 1},
                    {"item_no": "COMP-B", "qty": 1},   # never consumed
                ],
            }),
        )
        result = await gate.evaluate(ctx)
        assert result.passed is False
        assert result.severity == "warn"
        missing = result.evidence["missing_components"]
        assert len(missing) == 1
        assert missing[0]["component_item_no"] == "COMP-B"

    async def test_no_declared_bom_passes_silently(self, mongo_db):
        gate = AssemblyOrderBomCompletenessGate()
        ctx = GateContext(db=mongo_db, doc=_assembly_doc())
        result = await gate.evaluate(ctx)
        assert result.passed is True

    async def test_non_assembly_doc_gets_defensive_info_passthrough(self, mongo_db):
        gate = AssemblyOrderBomCompletenessGate()
        ctx = GateContext(db=mongo_db, doc=_non_assembly_doc())
        result = await gate.evaluate(ctx)
        assert result.passed is True
        assert result.severity == "info"


# ===========================================================================
# 4. Opt-in registration
# ===========================================================================

class TestRegistration:
    def test_register_is_opt_in_and_idempotent(self):
        reg = GateRegistry()
        assert reg.list_gates() == []

        first = register_assembly_order_gates(reg)
        assert len(first) == 2
        ids = {g.id for g in reg.list_gates()}
        assert ids == {
            "assembly_order_produced_overdraw",
            "assembly_order_bom_completeness",
        }

        # Second call is a no-op — idempotent.
        second = register_assembly_order_gates(reg)
        assert second == ()
        assert {g.id for g in reg.list_gates()} == ids

    def test_all_gates_scoped_to_archetype(self):
        reg = GateRegistry()
        register_assembly_order_gates(reg)
        for g in reg.list_gates():
            assert g.archetype == "assembly_order"


# NOTE: a cross-package cohabitation test importing PH's registrar
# alongside Assembly's was considered but intentionally omitted, to
# preserve the sibling package's unwired guardrail — each archetype
# test file remains self-contained.


# ===========================================================================
# 5. Unwired guardrail
# ===========================================================================

class TestUnwiredGuardrail:
    def test_no_external_imports_of_assembly_package(self):
        backend_root = Path(__file__).resolve().parent.parent
        allowed_prefixes = (
            backend_root / "workflows" / "sales" / "subtypes" / "assembly_order",
            backend_root / "tests" / "test_assembly_order.py",
        )
        needles = (
            "workflows.sales.subtypes.assembly_order",
            "from workflows.sales.subtypes import assembly_order",
        )
        offenders: list[str] = []
        for py in backend_root.rglob("*.py"):
            if "__pycache__" in py.parts:
                continue
            if any(str(py).startswith(str(p)) for p in allowed_prefixes):
                continue
            try:
                text = py.read_text(encoding="utf-8", errors="ignore")
            except OSError:
                continue
            for needle in needles:
                if needle in text:
                    offenders.append(f"{py} -> {needle!r}")
                    break
        assert offenders == [], (
            "workflows.sales.subtypes.assembly_order must stay UNWIRED. "
            "Offending files:\n  " + "\n  ".join(offenders)
        )
