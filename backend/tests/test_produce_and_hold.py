"""Pytest for Lane C Step 4 — Produce & Hold classifier + gates.

Covers:
  - Classifier: positive signals, negative signals, sentinel empty return,
    confidence monotonicity, empty KNOWN_PH_CUSTOMERS seed (per user amend).
  - Gates: release-overdraw blocks; blanket-match warns; aging warns;
    non-PH docs see a defensive info pass-through.
  - register_produce_and_hold_gates is idempotent and only adds 3 gates.
  - Unwired guardrail: no external imports of the PH package outside its
    own tree + its test file.
"""

from __future__ import annotations

import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path

import mongomock_motor
import pytest

from workflows.core.gate_framework import GateContext, GateRegistry
from workflows.inventory import lineage
from workflows.sales.subtypes.produce_and_hold import (
    KNOWN_PH_CUSTOMERS,
    PH_AGING_THRESHOLD_DAYS,
    PH_BLANKET_DIVERGENCE_FRACTION,
    PHClassification,
    ProduceAndHoldAgingGate,
    ProduceAndHoldBlanketMatchGate,
    ProduceAndHoldReleaseOverdrawGate,
    classify_produce_and_hold,
    register_produce_and_hold_gates,
)


@pytest.fixture
def mongo_db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client[f"test_ph_{uuid.uuid4().hex[:8]}"]


# ===========================================================================
# 1. Classifier
# ===========================================================================

class TestClassifier:
    def test_no_signals_returns_sentinel(self):
        r = classify_produce_and_hold({}, {})
        assert r.is_produce_and_hold is False
        assert r.confidence == 0.0
        assert r.signals == ()
        assert r.reasons == ("no signals found",)

    def test_ph_keyword_in_text_triggers_true(self):
        r = classify_produce_and_hold(
            {"raw_text": "please produce and hold for release"},
            {},
        )
        assert r.is_produce_and_hold is True
        assert "produce_and_hold_keyword" in r.signals

    def test_order_type_blanket_plus_hold_field_is_high_confidence(self):
        r = classify_produce_and_hold(
            {},
            {"order_type": "Blanket", "call_off_date": "2026-06-01"},
        )
        assert r.is_produce_and_hold is True
        assert "order_type_blanket" in r.signals
        assert "hold_field_present" in r.signals
        assert r.confidence >= 0.8

    def test_drop_ship_keyword_drives_negative(self):
        r = classify_produce_and_hold(
            {"raw_text": "drop ship directly to customer"},
            {},
        )
        assert r.is_produce_and_hold is False
        assert "drop_ship_keyword" in r.signals

    def test_drop_ship_location_code_drives_negative(self):
        r = classify_produce_and_hold(
            {},
            {"ship_to_location_code": "00"},
        )
        assert r.is_produce_and_hold is False
        assert "drop_ship_location" in r.signals

    def test_known_customers_seed_is_empty_per_sign_off(self):
        # User sign-off amendment (c): NO seeded customers.
        # Hook is preserved for later expansion; seed must ship empty.
        assert KNOWN_PH_CUSTOMERS == ()

    def test_customer_no_never_alone_triggers_true_when_seed_empty(self):
        # With the seed empty, the "known_ph_customer" signal can never fire.
        r = classify_produce_and_hold(
            {}, {"customer_no": "C-10250"},
        )
        assert "known_ph_customer" not in r.signals

    def test_confidence_is_clamped_to_unit_interval(self):
        # Stack multiple positives; result must not exceed 1.0.
        r = classify_produce_and_hold(
            {"raw_text": "blanket order; produce and hold for release"},
            {"order_type": "blanket", "hold_until": "2026-12-31"},
        )
        assert 0.0 <= r.confidence <= 1.0

    def test_returns_frozen_dataclass(self):
        r = classify_produce_and_hold({"raw_text": "blanket order"}, {})
        assert isinstance(r, PHClassification)
        with pytest.raises(Exception):
            r.confidence = 0.0  # type: ignore[misc]


# ===========================================================================
# 2. Gates
# ===========================================================================

def _ph_doc(so_ref="SO-1", lines=None) -> dict:
    return {
        "id": "doc-1",
        "raw_text": "please produce and hold for release",
        "extracted_fields": {
            "so_number": so_ref,
            "line_items": lines or [],
        },
    }


def _non_ph_doc() -> dict:
    return {
        "id": "doc-2",
        "raw_text": "standard warehouse shipment",
        "extracted_fields": {
            "so_number": "SO-X",
            "line_items": [{"item_no": "I-1", "quantity": 1}],
        },
    }


@pytest.mark.asyncio
class TestReleaseOverdrawGate:
    async def test_release_within_balance_passes(self, mongo_db):
        await lineage.record_receive_to_hold(
            mongo_db, so_ref="SO-1", item_no="I-1", qty=100,
            location="WH-H", source_ref="PO-1",
        )
        gate = ProduceAndHoldReleaseOverdrawGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_ph_doc(lines=[{"item_no": "I-1", "release_qty": 40}]),
        )
        result = await gate.evaluate(ctx)
        assert result.passed is True
        assert result.severity == "block"

    async def test_release_exceeding_balance_blocks(self, mongo_db):
        await lineage.record_receive_to_hold(
            mongo_db, so_ref="SO-1", item_no="I-1", qty=50,
            location="WH-H", source_ref="PO-1",
        )
        gate = ProduceAndHoldReleaseOverdrawGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_ph_doc(lines=[{"item_no": "I-1", "release_qty": 75}]),
        )
        result = await gate.evaluate(ctx)
        assert result.passed is False
        assert result.severity == "block"
        assert result.evidence["overdraw_lines"][0]["release_qty"] == 75
        assert result.evidence["overdraw_lines"][0]["available_qty"] == 50

    async def test_non_ph_doc_gets_defensive_info_passthrough(self, mongo_db):
        gate = ProduceAndHoldReleaseOverdrawGate()
        ctx = GateContext(db=mongo_db, doc=_non_ph_doc())
        result = await gate.evaluate(ctx)
        assert result.passed is True
        assert result.severity == "info"
        assert "not applicable" in result.detail.lower()


@pytest.mark.asyncio
class TestBlanketMatchGate:
    async def test_received_matches_blanket_within_tolerance_passes(self, mongo_db):
        # 1000 blanket, 1000 received → 0% divergence.
        await lineage.record_receive_to_hold(
            mongo_db, so_ref="SO-1", item_no="I-1", qty=1000,
            location="WH-H", source_ref="PO-1",
        )
        gate = ProduceAndHoldBlanketMatchGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_ph_doc(lines=[{"item_no": "I-1", "blanket_qty": 1000}]),
        )
        result = await gate.evaluate(ctx)
        assert result.passed is True

    async def test_divergence_beyond_5pct_warns(self, mongo_db):
        # 1000 blanket, 800 received → 20% divergence > 5%.
        await lineage.record_receive_to_hold(
            mongo_db, so_ref="SO-1", item_no="I-1", qty=800,
            location="WH-H", source_ref="PO-1",
        )
        gate = ProduceAndHoldBlanketMatchGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_ph_doc(lines=[{"item_no": "I-1", "blanket_qty": 1000}]),
        )
        result = await gate.evaluate(ctx)
        assert result.passed is False
        assert result.severity == "warn"
        assert result.evidence["threshold"] == PH_BLANKET_DIVERGENCE_FRACTION
        assert result.evidence["diverging_lines"][0]["divergence_fraction"] >= 0.20

    async def test_divergence_exactly_5pct_does_not_warn(self, mongo_db):
        # At-threshold is within tolerance (strict greater-than semantics).
        await lineage.record_receive_to_hold(
            mongo_db, so_ref="SO-1", item_no="I-1", qty=950,
            location="WH-H", source_ref="PO-1",
        )
        gate = ProduceAndHoldBlanketMatchGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_ph_doc(lines=[{"item_no": "I-1", "blanket_qty": 1000}]),
        )
        result = await gate.evaluate(ctx)
        assert result.passed is True


@pytest.mark.asyncio
class TestAgingGate:
    async def test_recent_hold_does_not_warn(self, mongo_db):
        await lineage.record_receive_to_hold(
            mongo_db, so_ref="SO-1", item_no="I-1", qty=10,
            location="WH-H", source_ref="PO-1",
        )
        gate = ProduceAndHoldAgingGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_ph_doc(lines=[{"item_no": "I-1"}]),
        )
        result = await gate.evaluate(ctx)
        assert result.passed is True

    async def test_aged_hold_warns(self, mongo_db):
        # Stamp a receive event older than the threshold by writing the
        # collection document directly (bypassing the writer's now() stamp).
        old_ts = (
            datetime.now(timezone.utc) - timedelta(days=PH_AGING_THRESHOLD_DAYS + 10)
        ).isoformat()
        await mongo_db[lineage.COLLECTION].insert_one({
            "event_id": str(uuid.uuid4()),
            "event_type": "receive_to_hold",
            "so_ref": "SO-1", "item_no": "I-1", "qty": 10.0,
            "location": "WH-H", "source_ref": "PO-1", "shipment_ref": None,
            "created_utc": old_ts, "evidence": {},
        })
        gate = ProduceAndHoldAgingGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_ph_doc(lines=[{"item_no": "I-1"}]),
        )
        result = await gate.evaluate(ctx)
        assert result.passed is False
        assert result.severity == "warn"
        assert result.evidence["threshold_days"] == PH_AGING_THRESHOLD_DAYS
        assert result.evidence["aged_items"][0]["item_no"] == "I-1"

    async def test_fully_released_aged_hold_does_not_warn(self, mongo_db):
        """available_qty=0 means nothing is aging in hold."""
        old_ts = (
            datetime.now(timezone.utc) - timedelta(days=PH_AGING_THRESHOLD_DAYS + 10)
        ).isoformat()
        await mongo_db[lineage.COLLECTION].insert_one({
            "event_id": str(uuid.uuid4()),
            "event_type": "receive_to_hold",
            "so_ref": "SO-1", "item_no": "I-1", "qty": 10.0,
            "location": "WH-H", "source_ref": "PO-1", "shipment_ref": None,
            "created_utc": old_ts, "evidence": {},
        })
        # Release everything that was received.
        await lineage.record_release_from_hold(
            mongo_db, so_ref="SO-1", item_no="I-1", qty=10, shipment_ref="SHP-1",
        )
        gate = ProduceAndHoldAgingGate()
        ctx = GateContext(
            db=mongo_db,
            doc=_ph_doc(lines=[{"item_no": "I-1"}]),
        )
        result = await gate.evaluate(ctx)
        assert result.passed is True


# ===========================================================================
# 3. Opt-in registration
# ===========================================================================

class TestRegistration:
    def test_register_is_opt_in_and_idempotent(self):
        reg = GateRegistry()
        assert reg.list_gates() == []

        first = register_produce_and_hold_gates(reg)
        assert len(first) == 3
        ids = {g.id for g in reg.list_gates()}
        assert ids == {
            "produce_and_hold_release_overdraw",
            "produce_and_hold_blanket_match",
            "produce_and_hold_aging",
        }

        # Second call is a no-op – does not raise, registers nothing new.
        second = register_produce_and_hold_gates(reg)
        assert second == ()
        assert {g.id for g in reg.list_gates()} == ids

    def test_all_gates_scoped_to_archetype(self):
        reg = GateRegistry()
        register_produce_and_hold_gates(reg)
        for g in reg.list_gates():
            assert g.archetype == "produce_and_hold"


# ===========================================================================
# 4. Unwired guardrail
# ===========================================================================

class TestUnwiredGuardrail:
    def test_no_external_imports_of_produce_and_hold_package(self):
        backend_root = Path(__file__).resolve().parent.parent
        allowed_prefixes = (
            backend_root / "workflows" / "sales" / "subtypes" / "produce_and_hold",
            backend_root / "tests" / "test_produce_and_hold.py",
        )
        needles = (
            "workflows.sales.subtypes.produce_and_hold",
            "from workflows.sales.subtypes import produce_and_hold",
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
            "workflows.sales.subtypes.produce_and_hold must stay UNWIRED. "
            "Offending files:\n  " + "\n  ".join(offenders)
        )
