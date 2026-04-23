"""Pytest for Lane C Step 7 (narrowed) — Customer Storage gates.

Proves:
  1. Signal-driven, no-classifier behavior
  2. Warn on missing agreement / block on ship-out missing release
  3. Opt-in registration only, no runtime drift
  4. No touches to AP S&H classification paths
"""

from __future__ import annotations

import uuid
from pathlib import Path

import mongomock_motor
import pytest

from workflows.core.gate_framework import GateContext, GateRegistry
from workflows.sales.subtypes.customer_storage import (
    ARCHETYPE,
    CustomerStorageShipOutMissingReleaseGate,
    CustomerStorageWithoutStorageAgreementGate,
    register_customer_storage_gates,
)


@pytest.fixture
def mongo_db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client[f"test_cs_{uuid.uuid4().hex[:8]}"]


def _cs_doc(
    *,
    agreement_id: str | None = None,
    release_id: str | None = None,
    ship_out_qty: float | None = 5.0,
    extra_signal: str = "flag",  # "flag" | "line" | "both" | "none"
    extra_lines=None,
):
    ef: dict = {"line_items": []}
    if agreement_id:
        ef["storage_agreement_id"] = agreement_id
    if release_id:
        ef["storage_release_id"] = release_id
    if extra_signal in ("flag", "both"):
        ef["is_customer_storage"] = True
    if extra_signal in ("line", "both") and ship_out_qty is not None:
        ef["line_items"].append({
            "item_no": "STORED-ITEM-1",
            "from_customer_storage": True,
            "quantity": ship_out_qty,
        })
    if extra_lines:
        ef["line_items"].extend(extra_lines)
    return {"id": "doc-cs-1", "extracted_fields": ef}


def _non_cs_doc():
    return {
        "id": "doc-non-cs-1",
        "extracted_fields": {
            "line_items": [{"item_no": "REGULAR-1", "quantity": 10}],
        },
    }


# ===========================================================================
# 1. Gate 1 — customer_storage_without_storage_agreement (WARN)
# ===========================================================================

@pytest.mark.asyncio
class TestAgreementGate:
    async def test_applicable_with_agreement_passes(self, mongo_db):
        gate = CustomerStorageWithoutStorageAgreementGate()
        ctx = GateContext(db=mongo_db, doc=_cs_doc(agreement_id="AGR-001"))
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.severity == "warn"
        assert r.evidence["storage_agreement_id"] == "AGR-001"

    async def test_applicable_without_agreement_warns(self, mongo_db):
        gate = CustomerStorageWithoutStorageAgreementGate()
        ctx = GateContext(db=mongo_db, doc=_cs_doc(agreement_id=None))
        r = await gate.evaluate(ctx)
        assert r.passed is False
        assert r.severity == "warn"
        assert r.evidence["storage_agreement_id"] is None
        assert "storage_agreement_id" in r.resolution_hint

    async def test_line_level_signal_triggers(self, mongo_db):
        gate = CustomerStorageWithoutStorageAgreementGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_cs_doc(agreement_id=None, extra_signal="line"),
        )
        r = await gate.evaluate(ctx)
        assert r.passed is False

    async def test_non_cs_doc_not_applicable(self, mongo_db):
        gate = CustomerStorageWithoutStorageAgreementGate()
        ctx = GateContext(db=mongo_db, doc=_non_cs_doc())
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.severity == "info"
        assert "no customer-storage signal" in r.detail


# ===========================================================================
# 2. Gate 2 — customer_storage_ship_out_missing_release (BLOCK)
# ===========================================================================

@pytest.mark.asyncio
class TestShipOutGate:
    async def test_ship_out_with_release_passes(self, mongo_db):
        gate = CustomerStorageShipOutMissingReleaseGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_cs_doc(release_id="REL-777", extra_signal="line"),
        )
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.severity == "block"
        assert r.evidence["storage_release_id"] == "REL-777"
        assert r.evidence["ship_out_line_count"] == 1

    async def test_ship_out_without_release_blocks(self, mongo_db):
        gate = CustomerStorageShipOutMissingReleaseGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_cs_doc(release_id=None, extra_signal="line"),
        )
        r = await gate.evaluate(ctx)
        assert r.passed is False
        assert r.severity == "block"
        assert r.evidence["ship_out_line_count"] == 1
        assert "storage_release_id" in r.resolution_hint

    async def test_doc_flag_only_no_ship_out_lines_not_applicable(self, mongo_db):
        # Doc-level is_customer_storage flag but no line qty → no ship-out
        gate = CustomerStorageShipOutMissingReleaseGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_cs_doc(release_id=None, extra_signal="flag"),
        )
        r = await gate.evaluate(ctx)
        assert r.passed is True
        assert r.severity == "info"
        assert "no ship-out" in r.detail.lower()

    async def test_zero_qty_line_not_ship_out(self, mongo_db):
        gate = CustomerStorageShipOutMissingReleaseGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_cs_doc(release_id=None, extra_signal="line", ship_out_qty=0.0),
        )
        r = await gate.evaluate(ctx)
        # Signal present via flag but line qty is 0 → not a ship-out.
        # (The line's flag still triggers the CS detector, but
        # _ship_out_lines filters by qty > 0.)
        assert r.passed is True
        assert r.severity == "info"

    async def test_non_cs_doc_not_applicable(self, mongo_db):
        gate = CustomerStorageShipOutMissingReleaseGate()
        ctx = GateContext(db=mongo_db, doc=_non_cs_doc())
        r = await gate.evaluate(ctx)
        assert r.severity == "info"


# ===========================================================================
# 3. Opt-in registration
# ===========================================================================

class TestRegistration:
    def test_register_is_opt_in_and_idempotent(self):
        reg = GateRegistry()
        assert reg.list_gates() == []
        first = register_customer_storage_gates(reg)
        assert len(first) == 2
        ids = {g.id for g in reg.list_gates()}
        assert ids == {
            "customer_storage_without_storage_agreement",
            "customer_storage_ship_out_missing_release",
        }
        second = register_customer_storage_gates(reg)
        assert second == ()

    def test_all_gates_scoped_to_archetype(self):
        reg = GateRegistry()
        register_customer_storage_gates(reg)
        for g in reg.list_gates():
            assert g.archetype == ARCHETYPE == "customer_storage"

    def test_severities_match_signed_ledger(self):
        reg = GateRegistry()
        register_customer_storage_gates(reg)
        by_id = {g.id: g for g in reg.list_gates()}
        assert by_id["customer_storage_without_storage_agreement"].severity == "warn"
        assert by_id["customer_storage_ship_out_missing_release"].severity == "block"


# ===========================================================================
# 4. Unwired guardrail — prove no runtime change
# ===========================================================================

class TestUnwiredGuardrail:
    def test_module_import_does_not_touch_any_registry(self):
        reg = GateRegistry()
        import importlib
        import workflows.sales.subtypes.customer_storage as cs_pkg  # noqa: F401
        import workflows.sales.subtypes.customer_storage.rules as cs_rules  # noqa: F401
        importlib.reload(cs_pkg)
        assert reg.list_gates() == []

    def test_no_external_imports_of_customer_storage_package(self):
        backend_root = Path(__file__).resolve().parent.parent
        allowed_prefixes = (
            backend_root / "workflows" / "sales" / "subtypes" / "customer_storage",
            backend_root / "tests" / "test_customer_storage.py",
        )
        needles = (
            "workflows.sales.subtypes.customer_storage",
            "from workflows.sales.subtypes import customer_storage",
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
            "workflows.sales.subtypes.customer_storage must stay UNWIRED. "
            "Offending files:\n  " + "\n  ".join(offenders)
        )

    def test_ap_storage_handling_paths_untouched(self):
        """Sanity: the AP S&H invoice-classification lane (a DIFFERENT
        concern from customer_storage the sales archetype) still owns
        ``STORAGE_HANDLING_KEYWORDS`` and ``_is_storage_handling``.
        """
        from services import freight_gl_routing_service, folder_routing_service

        assert hasattr(freight_gl_routing_service, "STORAGE_HANDLING_KEYWORDS")
        assert hasattr(folder_routing_service, "_is_storage_handling")
