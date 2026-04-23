"""Pytest for Lane C Step 4 — inventory lineage primitives.

Covers:
  - receive/release event shape + storage
  - qty-must-be-positive rejection on both writers
  - missing-required-ref rejection
  - get_hold_balance math across receive + release events
  - balance scoping by (so_ref, item_no)
  - empty balance sentinel
  - unwired guardrail: no external imports of workflows.inventory.lineage
"""

from __future__ import annotations

import uuid
from pathlib import Path

import mongomock_motor
import pytest

from workflows.inventory import lineage


@pytest.fixture
def mongo_db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client[f"test_lineage_{uuid.uuid4().hex[:8]}"]


# ---------------------------------------------------------------------------
# 1. Write behaviors
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestWrites:
    async def test_record_receive_to_hold_persists_and_returns_event(self, mongo_db):
        ev = await lineage.record_receive_to_hold(
            mongo_db,
            so_ref="SO-1001", item_no="ITEM-A", qty=100,
            location="WH-HOLD", source_ref="PO-500",
            evidence={"receipt_no": "R-900"},
        )
        assert ev.event_type == "receive_to_hold"
        assert ev.so_ref == "SO-1001"
        assert ev.qty == 100.0
        assert ev.location == "WH-HOLD"
        assert ev.source_ref == "PO-500"
        assert ev.shipment_ref is None

        rows = await mongo_db[lineage.COLLECTION].find({}, {"_id": 0}).to_list(length=5)
        assert len(rows) == 1
        assert rows[0]["event_type"] == "receive_to_hold"

    async def test_record_release_from_hold_persists_and_returns_event(self, mongo_db):
        ev = await lineage.record_release_from_hold(
            mongo_db,
            so_ref="SO-1001", item_no="ITEM-A", qty=25,
            shipment_ref="SHP-77",
        )
        assert ev.event_type == "release_from_hold"
        assert ev.shipment_ref == "SHP-77"
        assert ev.location is None
        assert ev.source_ref is None

    async def test_zero_or_negative_qty_rejected_on_receive(self, mongo_db):
        for bad in (0, -1, -0.01):
            with pytest.raises(ValueError):
                await lineage.record_receive_to_hold(
                    mongo_db,
                    so_ref="SO", item_no="I", qty=bad,
                    location="L", source_ref="PO",
                )

    async def test_zero_or_negative_qty_rejected_on_release(self, mongo_db):
        for bad in (0, -1, -0.5):
            with pytest.raises(ValueError):
                await lineage.record_release_from_hold(
                    mongo_db,
                    so_ref="SO", item_no="I", qty=bad, shipment_ref="SHP",
                )

    async def test_missing_required_ref_rejected(self, mongo_db):
        with pytest.raises(ValueError):
            await lineage.record_receive_to_hold(
                mongo_db, so_ref="", item_no="I", qty=1, location="L", source_ref="PO",
            )
        with pytest.raises(ValueError):
            await lineage.record_release_from_hold(
                mongo_db, so_ref="SO", item_no="", qty=1, shipment_ref="SHP",
            )
        with pytest.raises(ValueError):
            await lineage.record_release_from_hold(
                mongo_db, so_ref="SO", item_no="I", qty=1, shipment_ref="",
            )


# ---------------------------------------------------------------------------
# 2. get_hold_balance
# ---------------------------------------------------------------------------

@pytest.mark.asyncio
class TestHoldBalance:
    async def test_empty_balance_returns_zero(self, mongo_db):
        bal = await lineage.get_hold_balance(
            mongo_db, so_ref="SO-X", item_no="ITEM-X",
        )
        assert bal.received_qty == 0
        assert bal.released_qty == 0
        assert bal.available_qty == 0
        assert bal.events == ()

    async def test_receive_then_release_math(self, mongo_db):
        await lineage.record_receive_to_hold(
            mongo_db, so_ref="SO-1", item_no="I-1", qty=100,
            location="WH-H", source_ref="PO-1",
        )
        await lineage.record_receive_to_hold(
            mongo_db, so_ref="SO-1", item_no="I-1", qty=50,
            location="WH-H", source_ref="PO-2",
        )
        await lineage.record_release_from_hold(
            mongo_db, so_ref="SO-1", item_no="I-1", qty=30, shipment_ref="SHP-1",
        )
        bal = await lineage.get_hold_balance(
            mongo_db, so_ref="SO-1", item_no="I-1",
        )
        assert bal.received_qty == 150
        assert bal.released_qty == 30
        assert bal.available_qty == 120
        assert len(bal.events) == 3

    async def test_balance_scoped_by_so_and_item(self, mongo_db):
        await lineage.record_receive_to_hold(
            mongo_db, so_ref="SO-A", item_no="I-1", qty=10,
            location="L", source_ref="PO",
        )
        await lineage.record_receive_to_hold(
            mongo_db, so_ref="SO-B", item_no="I-1", qty=20,
            location="L", source_ref="PO",
        )
        await lineage.record_receive_to_hold(
            mongo_db, so_ref="SO-A", item_no="I-2", qty=30,
            location="L", source_ref="PO",
        )
        bal_a1 = await lineage.get_hold_balance(
            mongo_db, so_ref="SO-A", item_no="I-1",
        )
        bal_a2 = await lineage.get_hold_balance(
            mongo_db, so_ref="SO-A", item_no="I-2",
        )
        bal_b1 = await lineage.get_hold_balance(
            mongo_db, so_ref="SO-B", item_no="I-1",
        )
        assert bal_a1.received_qty == 10
        assert bal_a2.received_qty == 30
        assert bal_b1.received_qty == 20


# ---------------------------------------------------------------------------
# 3. Unwired guardrail
# ---------------------------------------------------------------------------

class TestUnwiredGuardrail:
    """Only PH rules module + this test should reference lineage."""

    def test_no_unexpected_imports_of_lineage(self):
        backend_root = Path(__file__).resolve().parent.parent  # /app/backend
        allowed_prefixes = (
            backend_root / "workflows" / "inventory" / "lineage.py",
            backend_root / "workflows" / "inventory" / "__init__.py",
            backend_root / "workflows" / "sales" / "subtypes" / "produce_and_hold",
            backend_root / "workflows" / "sales" / "subtypes" / "assembly_order",
            backend_root / "tests" / "test_inventory_lineage.py",
            backend_root / "tests" / "test_produce_and_hold.py",
            backend_root / "tests" / "test_assembly_lineage.py",
            backend_root / "tests" / "test_assembly_order.py",
        )
        needles = (
            "workflows.inventory.lineage",
            "from workflows.inventory import lineage",
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
            "workflows.inventory.lineage must stay UNWIRED outside the PH "
            "package. Offending files:\n  " + "\n  ".join(offenders)
        )
