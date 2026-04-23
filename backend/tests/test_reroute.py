"""Pytest for Lane C Step 7 (narrowed) — Reroute gates.

Proves:
  1. location_code=="001"-driven triggers, no classifier
  2. Warn on missing original-SO reference / missing DS PO linkage
  3. Non-duplication with live SO-008 (DS block via keyword detection)
  4. Freight-side authority (LOCATION_REROUTED, find_so_for_rerouted_po)
     is untouched
  5. Opt-in registration only
"""

from __future__ import annotations

import uuid
from pathlib import Path

import mongomock_motor
import pytest

from workflows.core.gate_framework import GateContext, GateRegistry
from workflows.sales.subtypes.reroute import (
    ARCHETYPE,
    RerouteLocationWithoutOriginalSoGate,
    RerouteRequiresDropShipLinkageGate,
    register_reroute_gates,
)
from workflows.sales.subtypes.reroute.rules import REROUTE_LOCATION_CODE


@pytest.fixture
def mongo_db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client[f"test_rr_{uuid.uuid4().hex[:8]}"]


def _rr_doc(
    *,
    location_code: str | None = "001",
    original_so: str | None = None,
    po_linkage: bool = False,
    line_level_location: bool = False,
):
    ef: dict = {"line_items": []}
    if location_code is not None:
        ef["location_code"] = location_code
    if original_so:
        ef["original_sales_order"] = original_so
    if po_linkage:
        ef["purchase_order_no"] = "PO-RR-42"
    if line_level_location:
        ef["line_items"].append({
            "item_no": "LINE-LOC-1",
            "quantity": 1,
            "location_code": "001",
        })
    return {"id": "doc-rr-1", "extracted_fields": ef}


def _non_reroute_doc():
    return {
        "id": "doc-rr-2",
        "extracted_fields": {
            "location_code": "MAIN",
            "line_items": [{"item_no": "X", "quantity": 1}],
        },
    }


# ===========================================================================
# 1. Gate 1 — reroute_location_without_original_so (WARN)
# ===========================================================================

@pytest.mark.asyncio
class TestOriginalSoGate:
    async def test_doc_level_loc_with_original_so_passes(self, mongo_db):
        gate = RerouteLocationWithoutOriginalSoGate()
        ctx = GateContext(db=mongo_db, doc=_rr_doc(original_so="WH-SO-777"))
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.severity == "warn"
        assert r.evidence["original_so"] == "WH-SO-777"

    async def test_doc_level_loc_without_original_so_warns(self, mongo_db):
        gate = RerouteLocationWithoutOriginalSoGate()
        ctx = GateContext(db=mongo_db, doc=_rr_doc())
        r = await gate.evaluate(ctx)
        assert r.passed is False
        assert r.severity == "warn"
        assert r.evidence["location_code"] == REROUTE_LOCATION_CODE
        assert "original_sales_order" in r.resolution_hint

    async def test_line_level_location_triggers(self, mongo_db):
        gate = RerouteLocationWithoutOriginalSoGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_rr_doc(location_code=None, line_level_location=True),
        )
        r = await gate.evaluate(ctx)
        assert r.passed is False
        assert r.severity == "warn"

    async def test_non_reroute_doc_not_applicable(self, mongo_db):
        gate = RerouteLocationWithoutOriginalSoGate()
        ctx = GateContext(db=mongo_db, doc=_non_reroute_doc())
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.severity == "info"
        assert "001" in r.detail

    async def test_alternative_ref_fields_recognized(self, mongo_db):
        gate = RerouteLocationWithoutOriginalSoGate()
        doc = _rr_doc()
        doc["extracted_fields"]["rerouted_from_so"] = "WH-SO-999"
        ctx = GateContext(db=mongo_db, doc=doc)
        r = await gate.evaluate(ctx)
        assert r.passed is True


# ===========================================================================
# 2. Gate 2 — reroute_requires_drop_ship_linkage (WARN)
# ===========================================================================

@pytest.mark.asyncio
class TestPoLinkageGate:
    async def test_reroute_with_po_linkage_passes(self, mongo_db):
        gate = RerouteRequiresDropShipLinkageGate()
        ctx = GateContext(db=mongo_db, doc=_rr_doc(po_linkage=True))
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.severity == "warn"
        assert r.evidence["has_po_linkage"] is True

    async def test_reroute_without_po_linkage_warns(self, mongo_db):
        gate = RerouteRequiresDropShipLinkageGate()
        ctx = GateContext(db=mongo_db, doc=_rr_doc(po_linkage=False))
        r = await gate.evaluate(ctx)
        assert r.passed is False
        assert r.severity == "warn"
        assert r.evidence["has_po_linkage"] is False
        assert "drop-ship" in r.resolution_hint.lower() or "purchase order" in r.resolution_hint.lower()

    async def test_non_reroute_doc_not_applicable(self, mongo_db):
        gate = RerouteRequiresDropShipLinkageGate()
        ctx = GateContext(db=mongo_db, doc=_non_reroute_doc())
        r = await gate.evaluate(ctx)
        assert r.severity == "info"

    async def test_po_linkage_via_linked_po(self, mongo_db):
        gate = RerouteRequiresDropShipLinkageGate()
        doc = _rr_doc(po_linkage=False)
        doc["linked_po"] = "PO-LINKED-501"
        ctx = GateContext(db=mongo_db, doc=doc)
        r = await gate.evaluate(ctx)
        assert r.passed is True


# ===========================================================================
# 3. Non-duplication with live SO-008 (keyword-detected drop ship)
# ===========================================================================

class TestNonDuplicationWithLiveSo008:
    """The reroute gates and SO-008 operate on orthogonal trigger axes
    and may both apply to the same document without semantic conflict.
    """

    def test_live_so008_uses_keyword_detection(self):
        """Sanity: SO-008 still owns the keyword-detected DS case and
        lives in services.so_rules_engine (untouched by Step 7)."""
        from services import so_rules_engine

        assert hasattr(so_rules_engine, "_check_drop_ship_rules")
        # The live DS detection uses a text-keyword predicate, not
        # location_code. Check the source of _build_order_context
        # contains the expected DS keywords.
        import inspect
        src = inspect.getsource(so_rules_engine._build_order_context)
        assert "is_drop_ship" in src
        assert "drop ship" in src.lower()

    def test_reroute_gates_use_location_code_not_keywords(self):
        """Reroute gates must trigger on location_code, not keywords."""
        import inspect
        from workflows.sales.subtypes.reroute import rules as rr_rules

        src = inspect.getsource(rr_rules._is_reroute_doc)
        assert "001" in src or "REROUTE_LOCATION_CODE" in src
        # Must NOT use DS keyword detection.
        assert "drop ship" not in src.lower() and "dropship" not in src.lower()

    @pytest.mark.asyncio
    async def test_same_doc_both_gates_can_fire(self):
        """A rerouted doc that ALSO contains DS keywords represents the
        live production reality (rerouted warehouse→drop ship). Both
        the reroute gate and SO-008 can flag different gaps without
        overlap or contradiction."""
        import mongomock_motor
        client = mongomock_motor.AsyncMongoMockClient()
        db = client["ndup_test"]
        # Reroute doc with drop-ship keyword in notes AND no PO linkage.
        doc = {
            "id": "doc-both-1",
            "extracted_fields": {
                "location_code": "001",
                "notes": "DROP SHIP from warehouse",
                "line_items": [{"item_no": "X", "quantity": 1}],
            },
        }
        gate = RerouteRequiresDropShipLinkageGate()
        r = await gate.evaluate(GateContext(db=db, doc=doc))
        assert r.passed is False
        assert r.evidence["location_code"] == "001"
        # SO-008 would separately flag the same doc via its keyword
        # path; that assertion belongs to the SO-rules-engine tests, not
        # this package. What matters here is: the two axes are
        # independent and neither short-circuits the other.


# ===========================================================================
# 4. Opt-in registration
# ===========================================================================

class TestRegistration:
    def test_register_is_opt_in_and_idempotent(self):
        reg = GateRegistry()
        assert reg.list_gates() == []
        first = register_reroute_gates(reg)
        assert len(first) == 2
        ids = {g.id for g in reg.list_gates()}
        assert ids == {
            "reroute_location_without_original_so",
            "reroute_requires_drop_ship_linkage",
        }
        second = register_reroute_gates(reg)
        assert second == ()

    def test_all_gates_scoped_to_archetype(self):
        reg = GateRegistry()
        register_reroute_gates(reg)
        for g in reg.list_gates():
            assert g.archetype == ARCHETYPE == "reroute"

    def test_severities_match_signed_ledger(self):
        reg = GateRegistry()
        register_reroute_gates(reg)
        by_id = {g.id: g for g in reg.list_gates()}
        assert by_id["reroute_location_without_original_so"].severity == "warn"
        assert by_id["reroute_requires_drop_ship_linkage"].severity == "warn"


# ===========================================================================
# 5. Unwired guardrail + freight-side untouched
# ===========================================================================

class TestUnwiredGuardrail:
    def test_module_import_does_not_touch_any_registry(self):
        reg = GateRegistry()
        import importlib
        import workflows.sales.subtypes.reroute as rr_pkg  # noqa: F401
        import workflows.sales.subtypes.reroute.rules as rr_rules  # noqa: F401
        importlib.reload(rr_pkg)
        assert reg.list_gates() == []

    def test_no_external_imports_of_reroute_package(self):
        backend_root = Path(__file__).resolve().parent.parent
        allowed_prefixes = (
            backend_root / "workflows" / "sales" / "subtypes" / "reroute",
            backend_root / "tests" / "test_reroute.py",
        )
        needles = (
            "workflows.sales.subtypes.reroute",
            "from workflows.sales.subtypes import reroute",
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
            "workflows.sales.subtypes.reroute must stay UNWIRED in Step 7. "
            "Offending files:\n  " + "\n  ".join(offenders)
        )

    def test_freight_side_authority_untouched(self):
        """Freight-side reroute authority remains the authoritative
        source for freight behavior. Step 7 must not touch it."""
        from workflows.freight import item_charges
        from services import bc_reference_cache_service

        # Core constant and helper must remain.
        assert hasattr(item_charges, "LOCATION_REROUTED")
        assert item_charges.LOCATION_REROUTED == "001"
        assert hasattr(bc_reference_cache_service, "BCReferenceCacheService")
        svc_cls = bc_reference_cache_service.BCReferenceCacheService
        assert hasattr(svc_cls, "find_so_for_rerouted_po")

    def test_reroute_constant_matches_freight_side(self):
        """The reroute package must stay aligned with the freight-side
        constant, without importing it (decoupled authority)."""
        from workflows.freight.item_charges import LOCATION_REROUTED
        assert REROUTE_LOCATION_CODE == LOCATION_REROUTED
