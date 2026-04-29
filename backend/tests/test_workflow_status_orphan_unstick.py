"""
Tests for the Workflow-Status Orphan Unstick script.

Class A — eligibility classification (pure)
Class B — dry-run mode
Class C — apply mode
Class D — revert mode

See: memory/WORKFLOW_STATUS_ORPHAN_UNSTICK_DECLARATION.md §9
"""
from __future__ import annotations

import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from scripts import workflow_status_orphan_unstick as mod
from scripts.workflow_status_orphan_unstick import (
    ALLOWED_DOC_IDS,
    BUCKET_CLEAN,
    BUCKET_MR_DUPLICATE,
    BUCKET_MR_POSTED,
    BUCKET_MR_UNEXPECTED,
    BUCKET_MR_VENDOR_DRIFT,
    BUCKET_PROMOTED,
    BUCKET_REJECTED,
    PROMOTION_MAP,
    _classify_doc,
)


C413 = "c413fe62-7f99-4584-b56f-4d30bf8b173d"
D10F = "d10f5242-0c8a-41fe-b713-e34223de0c52"
C10A = "c10a8b04-a49f-46ac-a78e-a5b448891307"
A48 = "48a153f8-41c0-46bd-bc93-52e2cc8238e5"
ALL_FOUR = [C413, D10F, C10A, A48]


def _doc(
    *,
    doc_id: str,
    status: str | None = None,
    workflow_status: str | None = None,
    vendor_canonical: str = "Mid America Logistics Group LLC",
    bc_vendor_number: str = "MIDAMER",
    vendor_match_method: str = "self_healed_bc_validation",
    bc_purchase_invoice: Any = None,
    is_duplicate: bool = False,
    duplicate_of_document_id: str | None = None,
    document_type: str = "AP_Invoice",
) -> Dict[str, Any]:
    if status is None:
        status = PROMOTION_MAP[doc_id]["from"]["status"]
    if workflow_status is None:
        workflow_status = PROMOTION_MAP[doc_id]["from"]["workflow_status"]
    return {
        "id": doc_id,
        "document_type": document_type,
        "status": status,
        "workflow_status": workflow_status,
        "vendor_canonical": vendor_canonical,
        "bc_vendor_number": bc_vendor_number,
        "vendor_match_method": vendor_match_method,
        "bc_purchase_invoice": bc_purchase_invoice,
        "is_duplicate": is_duplicate,
        "duplicate_of_document_id": duplicate_of_document_id,
    }


# ---------------------------------------------------------------------------
# Class A — Classification (pure)
# ---------------------------------------------------------------------------


class TestClassAClassify:
    @pytest.mark.parametrize("did", ALL_FOUR)
    def test_a1_each_id_at_expected_from_promotes(self, did):
        bucket, ctx = _classify_doc(_doc(doc_id=did))
        assert bucket == BUCKET_PROMOTED
        assert ctx["target"] == PROMOTION_MAP[did]["to"]

    def test_a2_already_at_target_is_clean(self):
        d = _doc(doc_id=C413, status="ReadyForPost", workflow_status="ready_for_post")
        bucket, _ = _classify_doc(d)
        assert bucket == BUCKET_CLEAN

    def test_a3_vendor_canonical_drift_blocks(self):
        d = _doc(doc_id=C413, vendor_canonical="Brown Warehouse Company")
        bucket, _ = _classify_doc(d)
        assert bucket == BUCKET_MR_VENDOR_DRIFT

    def test_a3b_bc_vendor_number_drift_blocks(self):
        d = _doc(doc_id=C413, bc_vendor_number="WROCKCP")
        bucket, _ = _classify_doc(d)
        assert bucket == BUCKET_MR_VENDOR_DRIFT

    def test_a3c_match_method_drift_blocks(self):
        d = _doc(doc_id=C413, vendor_match_method="sender_email")
        bucket, _ = _classify_doc(d)
        assert bucket == BUCKET_MR_VENDOR_DRIFT

    def test_a4_already_posted_blocks(self):
        d = _doc(doc_id=C413, bc_purchase_invoice={"id": "PI-001"})
        bucket, _ = _classify_doc(d)
        assert bucket == BUCKET_MR_POSTED

    def test_a5_duplicate_blocks(self):
        d = _doc(doc_id=C413, is_duplicate=True)
        bucket, _ = _classify_doc(d)
        assert bucket == BUCKET_MR_DUPLICATE

    def test_a5b_duplicate_of_blocks(self):
        d = _doc(doc_id=C413, duplicate_of_document_id="some-other-id")
        bucket, _ = _classify_doc(d)
        assert bucket == BUCKET_MR_DUPLICATE

    def test_a6_unexpected_state_blocks(self):
        # c413fe62 is supposed to be Completed/processed; here it's Validated/something_else
        d = _doc(doc_id=C413, status="Validated", workflow_status="something_else")
        bucket, _ = _classify_doc(d)
        assert bucket == BUCKET_MR_UNEXPECTED

    def test_a7_unknown_doc_id_rejected(self):
        d = _doc(
            doc_id="00000000-0000-0000-0000-000000000000",
            status="Completed", workflow_status="processed",
        )
        bucket, _ = _classify_doc(d)
        assert bucket == BUCKET_REJECTED


# ---------------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------------


class _FakeAsyncCursor:
    def __init__(self, rows):
        self._rows = list(rows)

    def __aiter__(self):
        self._iter = iter(self._rows)
        return self

    async def __anext__(self):
        try:
            return next(self._iter)
        except StopIteration:
            raise StopAsyncIteration


class _FakeCollection:
    def __init__(self, rows: List[Dict[str, Any]] | None = None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.update_calls: List[Dict[str, Any]] = []
        self.insert_calls: List[Dict[str, Any]] = []
        self.update_should_fail_for_doc_id: str | None = None

    def find(self, query: Dict[str, Any] | None = None, projection: Dict[str, Any] | None = None):
        rows = [r for r in self.rows if _matches(r, query or {})]
        rows = [{k: v for k, v in r.items() if k != "_id"} for r in rows]
        return _FakeAsyncCursor(rows)

    async def find_one(self, query, projection=None):
        for r in self.rows:
            if _matches(r, query):
                return {k: v for k, v in r.items() if k != "_id"}
        return None

    async def update_one(self, query, update):
        if self.update_should_fail_for_doc_id and query.get("id") == self.update_should_fail_for_doc_id:
            raise RuntimeError("simulated update failure")
        for r in self.rows:
            if _matches(r, query):
                self.update_calls.append({"query": query, "update": update})
                if "$set" in update:
                    r.update(update["$set"])
                if "$push" in update:
                    for k, v in update["$push"].items():
                        r.setdefault(k, []).append(v)
                if "$pop" in update:
                    for k, direction in update["$pop"].items():
                        arr = r.get(k) or []
                        if not arr:
                            continue
                        if direction == 1:
                            arr.pop()
                        else:
                            arr.pop(0)
                        r[k] = arr
                return

    async def insert_one(self, doc):
        self.insert_calls.append(doc)
        self.rows.append(dict(doc))


def _matches(row, query):
    for k, v in query.items():
        if "." in k:
            head, tail = k.split(".", 1)
            sub = row.get(head) or {}
            if sub.get(tail) != v:
                return False
            continue
        if row.get(k) != v:
            return False
    return True


class _FakeDB:
    def __init__(self, hub_rows=None):
        self.hub_documents = _FakeCollection(hub_rows)
        self.workflow_events = _FakeCollection()


@pytest.fixture
def fake_db(monkeypatch, tmp_path):
    db = _FakeDB()
    monkeypatch.setattr(mod, "_db", lambda: db)
    monkeypatch.setattr(mod, "REPORT_DIR", tmp_path)
    return db


# ---------------------------------------------------------------------------
# Class B — Dry-run
# ---------------------------------------------------------------------------


class TestClassBDryRun:
    @pytest.mark.asyncio
    async def test_b1_bucket_counts(self, fake_db):
        fake_db.hub_documents.rows = [
            _doc(doc_id=C413),  # promote
            _doc(doc_id=D10F, bc_purchase_invoice={"id":"x"}),  # already posted
            _doc(doc_id=C10A, status="ReadyForPost"),  # already promoted
            _doc(doc_id=A48, vendor_canonical="WRONG"),  # vendor drift
        ]
        report = await mod.sweep(apply=False, doc_id_filter=None, run_id="r-b1")
        assert report["bucket_counts"][BUCKET_PROMOTED] == 1
        assert report["bucket_counts"][BUCKET_MR_POSTED] == 1
        assert report["bucket_counts"][BUCKET_CLEAN] == 1
        assert report["bucket_counts"][BUCKET_MR_VENDOR_DRIFT] == 1

    @pytest.mark.asyncio
    async def test_b2_dry_run_no_writes(self, fake_db):
        fake_db.hub_documents.rows = [_doc(doc_id=did) for did in ALL_FOUR]
        await mod.sweep(apply=False, doc_id_filter=None, run_id="r-b2")
        assert fake_db.hub_documents.update_calls == []
        assert fake_db.workflow_events.insert_calls == []

    @pytest.mark.asyncio
    async def test_b3_writes_report_files(self, fake_db, tmp_path):
        fake_db.hub_documents.rows = [_doc(doc_id=C413)]
        report = await mod.sweep(apply=False, doc_id_filter=None, run_id="r-b3")
        md, js = mod._write_reports(report)
        assert md.exists() and md.read_text().startswith("# Workflow-Status Orphan Unstick")
        assert js.exists()


# ---------------------------------------------------------------------------
# Class C — Apply
# ---------------------------------------------------------------------------


class TestClassCApply:
    @pytest.mark.asyncio
    async def test_c1_promotes_target_fields(self, fake_db):
        fake_db.hub_documents.rows = [_doc(doc_id=C413)]
        await mod.sweep(apply=True, doc_id_filter=C413, run_id="r-c1")
        row = fake_db.hub_documents.rows[0]
        assert row["status"] == "ReadyForPost"
        assert row["workflow_status"] == "ready_for_post"
        assert row["promoted_for_batch2_source"] == mod.SCRIPT_VERSION
        assert row["promoted_for_batch2_at"]
        h = row["workflow_promotion_history"]
        assert len(h) == 1
        assert h[0]["previous_status"] == "Completed"
        assert h[0]["previous_workflow_status"] == "processed"
        assert h[0]["new_status"] == "ReadyForPost"
        assert h[0]["new_workflow_status"] == "ready_for_post"
        assert h[0]["run_id"] == "r-c1"

    @pytest.mark.asyncio
    async def test_c2_emits_event(self, fake_db):
        fake_db.hub_documents.rows = [_doc(doc_id=C413)]
        await mod.sweep(apply=True, doc_id_filter=C413, run_id="r-c2")
        events = [e for e in fake_db.workflow_events.insert_calls
                  if e["event_type"] == "workflow.status_promoted_for_batch2"]
        assert len(events) == 1
        e = events[0]
        assert e["document_id"] == C413
        assert e["payload"]["from"] == {"status": "Completed", "workflow_status": "processed"}
        assert e["payload"]["to"] == {"status": "ReadyForPost", "workflow_status": "ready_for_post"}
        assert e["payload"]["vendor_canonical"] == "Mid America Logistics Group LLC"
        assert e["payload"]["bc_vendor_number"] == "MIDAMER"
        assert e["payload"]["run_id"] == "r-c2"

    @pytest.mark.asyncio
    async def test_c3_idempotent(self, fake_db):
        fake_db.hub_documents.rows = [_doc(doc_id=C413)]
        await mod.sweep(apply=True, doc_id_filter=C413, run_id="r-c3-1")
        # second run — doc now at target
        report = await mod.sweep(apply=True, doc_id_filter=C413, run_id="r-c3-2")
        assert report["bucket_counts"].get(BUCKET_PROMOTED, 0) == 0
        assert report["bucket_counts"][BUCKET_CLEAN] == 1
        # only one history entry persists
        assert len(fake_db.hub_documents.rows[0]["workflow_promotion_history"]) == 1

    @pytest.mark.asyncio
    async def test_c4_unknown_doc_id_raises_before_db(self, fake_db):
        with pytest.raises(ValueError):
            await mod.sweep(apply=True, doc_id_filter="not-in-allowed", run_id="r-c4")

    @pytest.mark.asyncio
    async def test_c5_each_pair_maps_correctly(self, fake_db):
        fake_db.hub_documents.rows = [_doc(doc_id=did) for did in ALL_FOUR]
        await mod.sweep(apply=True, doc_id_filter=None, run_id="r-c5")
        for row in fake_db.hub_documents.rows:
            target = PROMOTION_MAP[row["id"]]["to"]
            assert row["status"] == target["status"]
            assert row["workflow_status"] == target["workflow_status"]


# ---------------------------------------------------------------------------
# Class D — Revert
# ---------------------------------------------------------------------------


class TestClassDRevert:
    @pytest.mark.asyncio
    async def test_d1_revert_restores_status(self, fake_db):
        fake_db.hub_documents.rows = [_doc(doc_id=C413)]
        await mod.sweep(apply=True, doc_id_filter=C413, run_id="r-d1")
        result = await mod.revert_doc(C413)
        assert result["reverted"] is True
        row = fake_db.hub_documents.rows[0]
        assert row["status"] == "Completed"
        assert row["workflow_status"] == "processed"

    @pytest.mark.asyncio
    async def test_d2_revert_pops_history(self, fake_db):
        fake_db.hub_documents.rows = [_doc(doc_id=C413)]
        await mod.sweep(apply=True, doc_id_filter=C413, run_id="r-d2")
        await mod.revert_doc(C413)
        assert fake_db.hub_documents.rows[0].get("workflow_promotion_history", []) == []

    @pytest.mark.asyncio
    async def test_d3_revert_emits_event(self, fake_db):
        fake_db.hub_documents.rows = [_doc(doc_id=C413)]
        await mod.sweep(apply=True, doc_id_filter=C413, run_id="r-d3")
        await mod.revert_doc(C413)
        rev = [e for e in fake_db.workflow_events.insert_calls
               if e["event_type"] == "workflow.status_promoted_for_batch2_reverted"]
        assert len(rev) == 1
        assert rev[0]["document_id"] == C413

    @pytest.mark.asyncio
    async def test_d4_revert_run_reverts_each(self, fake_db):
        fake_db.hub_documents.rows = [_doc(doc_id=did) for did in ALL_FOUR]
        await mod.sweep(apply=True, doc_id_filter=None, run_id="r-d4")
        result = await mod.revert_run("r-d4")
        assert result["reverted_count"] == 4

    @pytest.mark.asyncio
    async def test_d5_revert_unknown_doc_returns_failure(self, fake_db):
        result = await mod.revert_doc("nonexistent")
        assert result["reverted"] is False
        assert result["reason"] == "doc_not_found"

    @pytest.mark.asyncio
    async def test_d5b_revert_no_history(self, fake_db):
        fake_db.hub_documents.rows = [{"id": "x", "document_type": "AP_Invoice"}]
        result = await mod.revert_doc("x")
        assert result["reverted"] is False
        assert result["reason"] == "no_promotion_history"


# ---------------------------------------------------------------------------
# Sanity — declaration constants
# ---------------------------------------------------------------------------


class TestDeclarationConstants:
    def test_allowed_set_size(self):
        assert len(ALLOWED_DOC_IDS) == 4
        assert ALLOWED_DOC_IDS == set(PROMOTION_MAP.keys())

    def test_each_mapping_has_from_and_to(self):
        for did, m in PROMOTION_MAP.items():
            assert "from" in m and "to" in m
            for side in ("from", "to"):
                assert "status" in m[side]
                assert "workflow_status" in m[side]
