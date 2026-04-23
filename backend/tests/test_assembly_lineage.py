"""Pytest for Lane C Step 4b — Assembly lineage primitives (extensions
on top of workflows.inventory.lineage)."""

from __future__ import annotations

import uuid

import mongomock_motor
import pytest

from workflows.inventory import lineage


@pytest.fixture
def mongo_db():
    client = mongomock_motor.AsyncMongoMockClient()
    return client[f"test_assembly_lineage_{uuid.uuid4().hex[:8]}"]


# ── Additive-extension sanity ──────────────────────────────────────────────

class TestLiteralExtension:
    def test_all_four_event_types_preserved(self):
        # Step 4a's two types must still be present; Step 4b appends two.
        assert "receive_to_hold" in lineage.LINEAGE_EVENT_TYPES
        assert "release_from_hold" in lineage.LINEAGE_EVENT_TYPES
        assert "component_consumed" in lineage.LINEAGE_EVENT_TYPES
        assert "assembly_produced" in lineage.LINEAGE_EVENT_TYPES

    def test_event_types_tuple_is_unique(self):
        assert len(lineage.LINEAGE_EVENT_TYPES) == len(set(lineage.LINEAGE_EVENT_TYPES))


# ── Write behaviors ────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestAssemblyWrites:
    async def test_record_component_consumed_shape(self, mongo_db):
        ev = await lineage.record_component_consumed(
            mongo_db,
            work_order_ref="WO-900",
            component_item_no="COMP-A",
            qty=25,
            source_location="WH-MAIN",
            evidence={"pick_list": "PL-1"},
        )
        assert ev.event_type == "component_consumed"
        assert ev.work_order_ref == "WO-900"
        assert ev.item_no == "COMP-A"
        assert ev.qty == 25.0
        assert ev.location == "WH-MAIN"
        assert ev.components == ()

        rows = await mongo_db[lineage.COLLECTION].find({}, {"_id": 0}).to_list(length=5)
        assert len(rows) == 1
        assert rows[0]["event_type"] == "component_consumed"

    async def test_record_assembly_produced_shape(self, mongo_db):
        ev = await lineage.record_assembly_produced(
            mongo_db,
            work_order_ref="WO-900",
            parent_item_no="PARENT-X",
            qty=10,
            location="WH-HOLD",
            components=[
                {"item_no": "COMP-A", "qty": 2.5},
                {"item_no": "COMP-B", "qty": 1.0},
            ],
        )
        assert ev.event_type == "assembly_produced"
        assert ev.item_no == "PARENT-X"
        assert ev.qty == 10.0
        assert len(ev.components) == 2
        assert ev.components[0]["item_no"] == "COMP-A"

    async def test_component_normalization_drops_malformed_entries(self, mongo_db):
        ev = await lineage.record_assembly_produced(
            mongo_db,
            work_order_ref="WO-901",
            parent_item_no="PARENT-Y",
            qty=1,
            location="WH-HOLD",
            components=[
                {"item_no": "OK", "qty": 1},
                {"item_no": "BAD", "qty": 0},        # zero qty → dropped
                {"item_no": "NO_QTY"},               # missing qty → dropped
                {"qty": 5},                          # missing item_no → dropped
                "not a mapping",                     # wrong type → dropped
            ],
        )
        assert len(ev.components) == 1
        assert ev.components[0]["item_no"] == "OK"

    async def test_qty_must_be_positive(self, mongo_db):
        for bad in (0, -1, -0.01):
            with pytest.raises(ValueError):
                await lineage.record_component_consumed(
                    mongo_db, work_order_ref="W", component_item_no="C",
                    qty=bad, source_location="L",
                )
            with pytest.raises(ValueError):
                await lineage.record_assembly_produced(
                    mongo_db, work_order_ref="W", parent_item_no="P",
                    qty=bad, location="L",
                )

    async def test_missing_required_refs_rejected(self, mongo_db):
        with pytest.raises(ValueError):
            await lineage.record_component_consumed(
                mongo_db, work_order_ref="", component_item_no="C",
                qty=1, source_location="L",
            )
        with pytest.raises(ValueError):
            await lineage.record_assembly_produced(
                mongo_db, work_order_ref="W", parent_item_no="",
                qty=1, location="L",
            )
        with pytest.raises(ValueError):
            await lineage.record_assembly_produced(
                mongo_db, work_order_ref="W", parent_item_no="P",
                qty=1, location="",
            )


# ── Ledger math ────────────────────────────────────────────────────────────

@pytest.mark.asyncio
class TestAssemblyLedger:
    async def test_empty_ledger_returns_zero(self, mongo_db):
        lg = await lineage.get_assembly_ledger(
            mongo_db, work_order_ref="WO-EMPTY",
        )
        assert lg.produced_parents == {}
        assert lg.consumed_components == {}
        assert lg.events == ()

    async def test_produced_and_consumed_sum_independently(self, mongo_db):
        await lineage.record_component_consumed(
            mongo_db, work_order_ref="WO-1", component_item_no="COMP-A",
            qty=20, source_location="WH",
        )
        await lineage.record_component_consumed(
            mongo_db, work_order_ref="WO-1", component_item_no="COMP-A",
            qty=5, source_location="WH",
        )
        await lineage.record_component_consumed(
            mongo_db, work_order_ref="WO-1", component_item_no="COMP-B",
            qty=10, source_location="WH",
        )
        await lineage.record_assembly_produced(
            mongo_db, work_order_ref="WO-1", parent_item_no="PARENT-X",
            qty=8, location="WH-HOLD",
        )
        await lineage.record_assembly_produced(
            mongo_db, work_order_ref="WO-1", parent_item_no="PARENT-X",
            qty=2, location="WH-HOLD",
        )

        lg = await lineage.get_assembly_ledger(mongo_db, work_order_ref="WO-1")
        assert lg.consumed_components == {"COMP-A": 25.0, "COMP-B": 10.0}
        assert lg.produced_parents == {"PARENT-X": 10.0}
        assert len(lg.events) == 5

    async def test_ledger_scoped_by_work_order(self, mongo_db):
        await lineage.record_assembly_produced(
            mongo_db, work_order_ref="WO-A", parent_item_no="P",
            qty=5, location="WH",
        )
        await lineage.record_assembly_produced(
            mongo_db, work_order_ref="WO-B", parent_item_no="P",
            qty=7, location="WH",
        )
        lg_a = await lineage.get_assembly_ledger(mongo_db, work_order_ref="WO-A")
        lg_b = await lineage.get_assembly_ledger(mongo_db, work_order_ref="WO-B")
        assert lg_a.produced_parents == {"P": 5.0}
        assert lg_b.produced_parents == {"P": 7.0}

    async def test_ph_events_do_not_leak_into_assembly_ledger(self, mongo_db):
        # Interleave a PH receive event on the same collection; assembly
        # reader must filter by event_type and ignore it.
        await lineage.record_receive_to_hold(
            mongo_db, so_ref="SO-1", item_no="I", qty=100,
            location="WH-H", source_ref="PO-1",
        )
        await lineage.record_assembly_produced(
            mongo_db, work_order_ref="WO-1", parent_item_no="P",
            qty=3, location="WH-H",
        )
        lg = await lineage.get_assembly_ledger(mongo_db, work_order_ref="WO-1")
        assert lg.produced_parents == {"P": 3.0}
        # Only 1 event should show in the ledger (the produced one).
        assert len(lg.events) == 1
        assert lg.events[0].event_type == "assembly_produced"
