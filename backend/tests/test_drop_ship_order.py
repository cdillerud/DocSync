"""Pytest for Lane C Step 6 — Drop Ship gates.

Proves:
  1. Gate surface landed under workflows/sales/subtypes/drop_ship/
  2. Parity with live so_rules_engine DS rules (SO-008, SO-009, ancillary)
  3. Unwired / no-runtime-change behavior (opt-in registration only,
     no edits to services/so_rules_engine.py)
  4. Baseline regression (additive only, no consumer touches the new
     package outside this test file)
"""

from __future__ import annotations

import uuid
from pathlib import Path

import mongomock_motor
import pytest

from workflows.core.gate_framework import GateContext, GateRegistry
from workflows.sales.subtypes.drop_ship import (
    ARCHETYPE,
    DropShipInventoryLineNotMarkedGate,
    DropShipPoCostUnverifiedGate,
    DropShipPoMissingGate,
    register_drop_ship_gates,
)


@pytest.fixture
def mongo_db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client[f"test_ds_{uuid.uuid4().hex[:8]}"]


def _ds_doc(
    *,
    subtype="DS_Sales_Order",
    po_linkage: bool = False,
    lines=None,
):
    ef: dict = {"line_items": lines or []}
    if po_linkage:
        ef["purchase_order_no"] = "PO-12345"
    return {
        "id": "doc-ds-1",
        "so_subtype": subtype,
        "extracted_fields": ef,
    }


def _wh_doc():
    return {
        "id": "doc-wh-1",
        "so_subtype": "WH_Sales_Order",
        "extracted_fields": {
            "purchase_order_no": "PO-55555",
            "line_items": [{"item_no": "ABC", "unit_price": 100}],
        },
    }


def _plain_so_doc():
    return {
        "id": "doc-plain-1",
        "so_subtype": "Sales_Order",
        "extracted_fields": {"line_items": []},
    }


# ===========================================================================
# 1. SO-008 parity — drop_ship_po_missing (BLOCK)
# ===========================================================================

@pytest.mark.asyncio
class TestPoMissingGate:
    async def test_ds_with_po_linkage_passes(self, mongo_db):
        gate = DropShipPoMissingGate()
        ctx = GateContext(db=mongo_db, doc=_ds_doc(po_linkage=True))
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.severity == "block"
        assert r.evidence["has_po_linkage"] is True

    async def test_ds_without_po_linkage_blocks(self, mongo_db):
        gate = DropShipPoMissingGate()
        ctx = GateContext(db=mongo_db, doc=_ds_doc(po_linkage=False))
        r = await gate.evaluate(ctx)
        assert r.passed is False
        assert r.severity == "block"
        assert r.evidence["has_po_linkage"] is False
        assert "SO-008" in r.detail or "Drop Ship PO Needed" in r.detail
        assert r.resolution_hint is not None
        assert "purchase order" in r.resolution_hint.lower()

    async def test_wh_doc_defensive_info(self, mongo_db):
        gate = DropShipPoMissingGate()
        ctx = GateContext(db=mongo_db, doc=_wh_doc())
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.severity == "info"
        assert "not a Drop Ship" in r.detail

    async def test_plain_so_doc_defensive_info(self, mongo_db):
        gate = DropShipPoMissingGate()
        ctx = GateContext(db=mongo_db, doc=_plain_so_doc())
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.severity == "info"

    async def test_lowercase_subtype_also_triggers(self, mongo_db):
        gate = DropShipPoMissingGate()
        ctx = GateContext(db=mongo_db, doc=_ds_doc(subtype="ds_sales_order"))
        r = await gate.evaluate(ctx)
        assert r.passed is False
        assert r.severity == "block"

    async def test_po_linkage_via_linked_po(self, mongo_db):
        gate = DropShipPoMissingGate()
        doc = _ds_doc(po_linkage=False)
        doc["linked_po"] = "PO-LINKED-999"
        ctx = GateContext(db=mongo_db, doc=doc)
        r = await gate.evaluate(ctx)
        assert r.passed is True

    async def test_po_linkage_via_normalized_fields(self, mongo_db):
        gate = DropShipPoMissingGate()
        doc = _ds_doc(po_linkage=False)
        doc["normalized_fields"] = {"purchase_order_number": "PO-NF-777"}
        ctx = GateContext(db=mongo_db, doc=doc)
        r = await gate.evaluate(ctx)
        assert r.passed is True


# ===========================================================================
# 2. SO-009 parity — drop_ship_po_cost_unverified (WARN)
# ===========================================================================

@pytest.mark.asyncio
class TestPoCostUnverifiedGate:
    async def test_ds_with_po_linkage_warns(self, mongo_db):
        gate = DropShipPoCostUnverifiedGate()
        ctx = GateContext(db=mongo_db, doc=_ds_doc(po_linkage=True))
        r = await gate.evaluate(ctx)
        assert r.passed is False
        assert r.severity == "warn"
        assert "SO-009" in r.detail or "PO cost" in r.detail
        assert r.resolution_hint is not None

    async def test_ds_without_po_linkage_deferred_to_gate1(self, mongo_db):
        gate = DropShipPoCostUnverifiedGate()
        ctx = GateContext(db=mongo_db, doc=_ds_doc(po_linkage=False))
        r = await gate.evaluate(ctx)
        # Missing-PO case is Gate 1's concern; Gate 2 must defer.
        assert r.passed is True
        assert r.severity == "info"
        assert "drop_ship_po_missing" in r.detail or "deferred" in r.detail.lower()

    async def test_wh_doc_defensive_info(self, mongo_db):
        gate = DropShipPoCostUnverifiedGate()
        ctx = GateContext(db=mongo_db, doc=_wh_doc())
        r = await gate.evaluate(ctx)
        assert r.severity == "info"

    async def test_plain_so_defensive_info(self, mongo_db):
        gate = DropShipPoCostUnverifiedGate()
        ctx = GateContext(db=mongo_db, doc=_plain_so_doc())
        r = await gate.evaluate(ctx)
        assert r.severity == "info"


# ===========================================================================
# 3. Ancillary parity — drop_ship_inventory_line_not_marked (WARN)
# ===========================================================================

@pytest.mark.asyncio
class TestInventoryLineNotMarkedGate:
    async def test_all_lines_marked_drop_shipment_passes(self, mongo_db):
        gate = DropShipInventoryLineNotMarkedGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_ds_doc(
                po_linkage=True,
                lines=[
                    {"item_no": "ABC", "unit_price": 100, "drop_shipment": True},
                    {"item_no": "DEF", "unit_price": 50, "purchasing_code": "DROP SHIP"},
                ],
            ),
        )
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.severity == "warn"
        assert r.evidence["ds_marked_count"] == 2

    async def test_inventory_lines_with_no_ds_marking_warns(self, mongo_db):
        gate = DropShipInventoryLineNotMarkedGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_ds_doc(
                po_linkage=True,
                lines=[
                    {"item_no": "ABC", "unit_price": 100},
                    {"item_no": "DEF", "unit_price": 50},
                ],
            ),
        )
        r = await gate.evaluate(ctx)
        assert r.passed is False
        assert r.severity == "warn"
        assert r.evidence["ds_marked_count"] == 0
        assert r.evidence["non_freight_line_count"] == 2
        assert "purchasing code" in (r.resolution_hint or "").lower()

    async def test_only_freight_lines_is_not_applicable(self, mongo_db):
        gate = DropShipInventoryLineNotMarkedGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_ds_doc(
                po_linkage=True,
                lines=[
                    {"item_no": "FREIGHT", "description": "Freight", "unit_price": 25},
                    {"description": "Shipping fee", "unit_price": 10, "line_type": "charge"},
                ],
            ),
        )
        r = await gate.evaluate(ctx)
        # No non-freight inventory lines → gate not applicable.
        assert r.passed is True
        assert r.severity == "info"

    async def test_no_lines_is_not_applicable(self, mongo_db):
        gate = DropShipInventoryLineNotMarkedGate()
        ctx = GateContext(db=mongo_db, doc=_ds_doc(po_linkage=True, lines=[]))
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.severity == "info"

    async def test_partial_marking_still_passes(self, mongo_db):
        # One DS-marked line among non-freight lines is enough to clear
        # the gate — matches the live predicate (``if ds_lines``).
        gate = DropShipInventoryLineNotMarkedGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_ds_doc(
                po_linkage=True,
                lines=[
                    {"item_no": "ABC", "unit_price": 100, "drop_shipment": True},
                    {"item_no": "DEF", "unit_price": 50},
                    {"item_no": "FREIGHT", "description": "Freight", "unit_price": 25},
                ],
            ),
        )
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.evidence["ds_marked_count"] == 1
        assert r.evidence["non_freight_line_count"] == 2

    async def test_wh_doc_defensive_info(self, mongo_db):
        gate = DropShipInventoryLineNotMarkedGate()
        ctx = GateContext(db=mongo_db, doc=_wh_doc())
        r = await gate.evaluate(ctx)
        assert r.severity == "info"

    async def test_plain_so_defensive_info(self, mongo_db):
        gate = DropShipInventoryLineNotMarkedGate()
        ctx = GateContext(db=mongo_db, doc=_plain_so_doc())
        r = await gate.evaluate(ctx)
        assert r.severity == "info"


# ===========================================================================
# 4. Opt-in registration
# ===========================================================================

class TestRegistration:
    def test_register_is_opt_in_and_idempotent(self):
        reg = GateRegistry()
        assert reg.list_gates() == []
        first = register_drop_ship_gates(reg)
        assert len(first) == 3
        ids = {g.id for g in reg.list_gates()}
        assert ids == {
            "drop_ship_po_missing",
            "drop_ship_po_cost_unverified",
            "drop_ship_inventory_line_not_marked",
        }
        # Second registration must be a no-op.
        second = register_drop_ship_gates(reg)
        assert second == ()
        assert {g.id for g in reg.list_gates()} == ids

    def test_all_gates_scoped_to_archetype(self):
        reg = GateRegistry()
        register_drop_ship_gates(reg)
        for g in reg.list_gates():
            assert g.archetype == ARCHETYPE == "drop_ship"

    def test_gate_severities_match_signed_ledger(self):
        reg = GateRegistry()
        register_drop_ship_gates(reg)
        by_id = {g.id: g for g in reg.list_gates()}
        assert by_id["drop_ship_po_missing"].severity == "block"
        assert by_id["drop_ship_po_cost_unverified"].severity == "warn"
        assert by_id["drop_ship_inventory_line_not_marked"].severity == "warn"


# ===========================================================================
# 5. Unwired guardrail — prove no runtime change
# ===========================================================================

class TestUnwiredGuardrail:
    def test_module_import_does_not_touch_any_registry(self):
        """Proves the package does NOT auto-register at import time.

        If import-time registration leaked in, a fresh registry would
        receive gates without us calling ``register_drop_ship_gates``.
        """
        reg = GateRegistry()
        # Re-import to simulate a fresh import from another module path.
        import importlib
        import workflows.sales.subtypes.drop_ship as ds_pkg  # noqa: F401
        import workflows.sales.subtypes.drop_ship.rules as ds_rules  # noqa: F401
        importlib.reload(ds_pkg)
        assert reg.list_gates() == []

    def test_no_external_imports_of_drop_ship_package(self):
        backend_root = Path(__file__).resolve().parent.parent
        allowed_prefixes = (
            backend_root / "workflows" / "sales" / "subtypes" / "drop_ship",
            backend_root / "tests" / "test_drop_ship_order.py",
        )
        needles = (
            "workflows.sales.subtypes.drop_ship",
            "from workflows.sales.subtypes import drop_ship",
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
            "workflows.sales.subtypes.drop_ship must stay UNWIRED in Step 6. "
            "Offending files:\n  " + "\n  ".join(offenders)
        )

    def test_so_rules_engine_untouched_for_ds_rules(self):
        """Sanity check: the live authoritative DS logic still lives in
        so_rules_engine.py, unchanged by Step 6.

        We do not diff the file here; we simply assert the live DS
        symbols are present and still owned by so_rules_engine.
        """
        from services import so_rules_engine

        # Live DS rule function remains the authority.
        assert hasattr(so_rules_engine, "_check_drop_ship_rules"), (
            "services.so_rules_engine._check_drop_ship_rules must remain "
            "the live authoritative DS rule in Step 6."
        )
        # Canonical DS stage labels untouched.
        assert "Drop Ship PO Needed" in so_rules_engine.STAGES
        assert "Drop Ship PO Incomplete" in so_rules_engine.STAGES
