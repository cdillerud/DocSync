"""
Tests for the §6.2 Vendor-Canonical Self-Heal Sweep.

Covers:
  - Class A: pure-function `_classify_doc`
  - Class B: dry-run mode (no `--apply`)
  - Class C: apply mode
  - Class D: revert mode
  - Class E: real-world fixtures (Mid America / SC Warehouses shapes)

See: memory/VENDOR_CANONICAL_SELF_HEAL_SWEEP_DECLARATION.md §9
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

from scripts import vendor_canonical_self_heal_sweep as sweep_mod
from scripts.vendor_canonical_self_heal_sweep import (
    BUCKET_AUTO_HEAL,
    BUCKET_CLEAN,
    BUCKET_MR_DUPLICATE,
    BUCKET_MR_EXTRACTION_VS_BC,
    BUCKET_MR_OVERRIDE,
    BUCKET_MR_POSTED,
    BUCKET_NA_NO_BC,
    BUCKET_NA_NO_EXTRACTED,
    _classify_doc,
)


# ---------------------------------------------------------------------------
# Doc fixture builders
# ---------------------------------------------------------------------------


def _doc(
    *,
    extracted: str = "Mid America Logistics Group, LLC",
    bc_number: str | None = "MIDAMER",
    bc_display: str | None = "Mid America Logistics Group LLC",
    canonical: str = "Brown Warehouse Company",
    posted: bool = False,
    is_dup: bool = False,
    manual_override: bool = False,
    match_method: str | None = None,
    doc_id: str | None = None,
) -> Dict[str, Any]:
    bc_info: Dict[str, Any] = {}
    if bc_number is not None:
        bc_info["number"] = bc_number
    if bc_display is not None:
        bc_info["displayName"] = bc_display
    return {
        "id": doc_id or str(uuid.uuid4()),
        "document_type": "AP_Invoice",
        "extracted_fields": {"vendor": extracted},
        "vendor_canonical": canonical,
        "vendor_match_method": match_method,
        "bc_vendor_number": "BWC" if canonical == "Brown Warehouse Company" else None,
        "validation_results": {"bc_record_info": bc_info},
        "bc_purchase_invoice": {"id": "abc"} if posted else None,
        "is_duplicate": is_dup,
        "vendor_canonical_manual_override": manual_override,
    }


# ---------------------------------------------------------------------------
# Class A — Eligibility classification (pure)
# ---------------------------------------------------------------------------


class TestClassAClassify:
    def test_a1_clean_no_change_needed(self):
        # Canonical already matches BC display (token-substring) → CLEAN
        d = _doc(canonical="Mid America Logistics Group LLC")
        bucket, _ = _classify_doc(d)
        assert bucket == BUCKET_CLEAN

    def test_a2_auto_heal(self):
        bucket, ctx = _classify_doc(_doc())
        assert bucket == BUCKET_AUTO_HEAL
        assert ctx["bc_number"] == "MIDAMER"
        assert ctx["bc_display"] == "Mid America Logistics Group LLC"

    def test_a3_no_bc_resolution(self):
        bucket, _ = _classify_doc(_doc(bc_number=None, bc_display=None))
        assert bucket == BUCKET_NA_NO_BC

    def test_a3b_partial_bc_resolution_missing_display(self):
        bucket, _ = _classify_doc(_doc(bc_display=None))
        assert bucket == BUCKET_NA_NO_BC

    def test_a4_no_extracted_vendor(self):
        bucket, _ = _classify_doc(_doc(extracted=""))
        assert bucket == BUCKET_NA_NO_EXTRACTED

    def test_a5_already_posted_protected(self):
        bucket, _ = _classify_doc(_doc(posted=True))
        assert bucket == BUCKET_MR_POSTED

    def test_a6_duplicate_protected(self):
        bucket, _ = _classify_doc(_doc(is_dup=True))
        assert bucket == BUCKET_MR_DUPLICATE

    def test_a7_manual_override_protected(self):
        bucket, _ = _classify_doc(_doc(manual_override=True))
        assert bucket == BUCKET_MR_OVERRIDE

    def test_a7b_manual_match_method_protected(self):
        bucket, _ = _classify_doc(_doc(match_method="manual_override"))
        assert bucket == BUCKET_MR_OVERRIDE

    def test_a8_extraction_disagrees_with_bc(self):
        # Extracted "ACME ROOFING" vs BC display "GLOBEX SHIPPING" — disjoint.
        d = _doc(
            extracted="ACME Roofing Supplies",
            bc_number="GLOBEX",
            bc_display="Globex Shipping International",
            canonical="Brown Warehouse Company",
        )
        bucket, _ = _classify_doc(d)
        assert bucket == BUCKET_MR_EXTRACTION_VS_BC


# ---------------------------------------------------------------------------
# Fake DB
# ---------------------------------------------------------------------------


class _FakeAsyncCursor:
    def __init__(self, rows: List[Dict[str, Any]]):
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
        self.insert_should_fail_for_event_type: str | None = None
        self.update_should_fail_for_doc_id: str | None = None

    def find(self, query: Dict[str, Any] | None = None, projection: Dict[str, Any] | None = None):
        rows = [r for r in self.rows if _matches(r, query or {})]
        # strip _id like real projection
        rows = [{k: v for k, v in r.items() if k != "_id"} for r in rows]
        return _FakeAsyncCursor(rows)

    async def find_one(self, query: Dict[str, Any], projection: Dict[str, Any] | None = None):
        for r in self.rows:
            if _matches(r, query):
                return {k: v for k, v in r.items() if k != "_id"}
        return None

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any]):
        # Optionally simulate failure
        target_id = query.get("id")
        if self.update_should_fail_for_doc_id and target_id == self.update_should_fail_for_doc_id:
            raise RuntimeError("simulated update failure")
        # apply $set / $push / $pop in place on matching row
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

    async def insert_one(self, doc: Dict[str, Any]):
        if self.insert_should_fail_for_event_type and doc.get("event_type") == self.insert_should_fail_for_event_type:
            raise RuntimeError("simulated mongo write failure")
        self.insert_calls.append(doc)
        # also persist so subsequent find()s see the row
        self.rows.append(dict(doc))


def _matches(row: Dict[str, Any], query: Dict[str, Any]) -> bool:
    for k, v in query.items():
        if "." in k:
            # only used for "payload.sweep_run_id"
            head, tail = k.split(".", 1)
            sub = row.get(head) or {}
            if sub.get(tail) != v:
                return False
            continue
        if isinstance(v, dict) and "$nin" in v:
            if row.get(k) in v["$nin"]:
                return False
        elif row.get(k) != v:
            return False
    return True


class _FakeDB:
    def __init__(self, hub_rows: List[Dict[str, Any]] | None = None):
        self.hub_documents = _FakeCollection(hub_rows)
        self.workflow_events = _FakeCollection()


@pytest.fixture
def fake_db(monkeypatch):
    db = _FakeDB()
    monkeypatch.setattr(sweep_mod, "_db", lambda: db)
    return db


# ---------------------------------------------------------------------------
# Class B — Dry-run
# ---------------------------------------------------------------------------


class TestClassBDryRun:
    @pytest.mark.asyncio
    async def test_b1_bucket_counts(self, fake_db, tmp_path, monkeypatch):
        fake_db.hub_documents.rows = [
            _doc(),  # auto_heal
            _doc(canonical="Mid America Logistics Group LLC"),  # clean
            _doc(extracted=""),  # no_extracted
            _doc(bc_number=None, bc_display=None),  # no_bc
            _doc(posted=True),  # posted
            _doc(is_dup=True),  # duplicate
            _doc(manual_override=True),  # override
            _doc(  # extraction vs bc disagreement
                extracted="ACME Roofing Supplies",
                bc_number="GLOBEX",
                bc_display="Globex Shipping International",
            ),
        ]
        monkeypatch.setattr(sweep_mod, "REPORT_DIR", tmp_path)

        report = await sweep_mod.sweep(
            apply=False, max_heals=None, doc_id_filter=None, sweep_run_id="run-b1",
        )
        assert report["bucket_counts"][BUCKET_AUTO_HEAL] == 1
        assert report["bucket_counts"][BUCKET_CLEAN] == 1
        assert report["bucket_counts"][BUCKET_NA_NO_EXTRACTED] == 1
        assert report["bucket_counts"][BUCKET_NA_NO_BC] == 1
        assert report["bucket_counts"][BUCKET_MR_POSTED] == 1
        assert report["bucket_counts"][BUCKET_MR_DUPLICATE] == 1
        assert report["bucket_counts"][BUCKET_MR_OVERRIDE] == 1
        assert report["bucket_counts"][BUCKET_MR_EXTRACTION_VS_BC] == 1

    @pytest.mark.asyncio
    async def test_b2_dry_run_no_writes(self, fake_db):
        fake_db.hub_documents.rows = [_doc(), _doc(), _doc()]
        await sweep_mod.sweep(
            apply=False, max_heals=None, doc_id_filter=None, sweep_run_id="run-b2",
        )
        assert fake_db.hub_documents.update_calls == []
        assert fake_db.workflow_events.insert_calls == []

    @pytest.mark.asyncio
    async def test_b3_writes_report_files(self, fake_db, tmp_path, monkeypatch):
        fake_db.hub_documents.rows = [_doc()]
        monkeypatch.setattr(sweep_mod, "REPORT_DIR", tmp_path)
        report = await sweep_mod.sweep(
            apply=False, max_heals=None, doc_id_filter=None, sweep_run_id="run-b3",
        )
        md, js, mr = sweep_mod._write_reports(report)
        assert md.exists() and md.read_text().startswith("# Vendor-Canonical Self-Heal Sweep")
        assert js.exists()
        assert mr is None  # no manual review buckets


# ---------------------------------------------------------------------------
# Class C — Apply mode
# ---------------------------------------------------------------------------


class TestClassCApply:
    @pytest.mark.asyncio
    async def test_c1_heal_writes_expected_fields(self, fake_db):
        d = _doc(doc_id="DOC-C1")
        fake_db.hub_documents.rows = [d]
        report = await sweep_mod.sweep(
            apply=True, max_heals=None, doc_id_filter=None, sweep_run_id="run-c1",
        )
        assert len(report["heal_results"]) == 1
        assert report["heal_results"][0]["healed"] is True
        # find the post-update row
        row = fake_db.hub_documents.rows[0]
        assert row["vendor_canonical"] == "Mid America Logistics Group LLC"
        assert row["bc_vendor_number"] == "MIDAMER"
        assert row["vendor_match_method"] == "self_healed_bc_validation"
        assert row["self_heal_source"] == sweep_mod.SWEEP_VERSION
        assert row["self_healed_at"]
        history = row["self_heal_history"]
        assert len(history) == 1
        h0 = history[0]
        assert h0["previous_vendor_canonical"] == "Brown Warehouse Company"
        assert h0["new_vendor_canonical"] == "Mid America Logistics Group LLC"
        assert h0["new_bc_vendor_number"] == "MIDAMER"
        assert h0["sweep_run_id"] == "run-c1"

    @pytest.mark.asyncio
    async def test_c2_emits_one_workflow_event(self, fake_db):
        d = _doc(doc_id="DOC-C2")
        fake_db.hub_documents.rows = [d]
        await sweep_mod.sweep(
            apply=True, max_heals=None, doc_id_filter=None, sweep_run_id="run-c2",
        )
        events = [e for e in fake_db.workflow_events.insert_calls
                  if e["event_type"] == "vendor.canonical_self_healed"]
        assert len(events) == 1
        e = events[0]
        assert e["status"] == "completed"
        assert e["source_service"] == "vendor_canonical_self_heal_sweep"
        assert e["document_id"] == "DOC-C2"
        p = e["payload"]
        assert p["from"]["vendor_canonical"] == "Brown Warehouse Company"
        assert p["to"]["vendor_canonical"] == "Mid America Logistics Group LLC"
        assert p["to"]["bc_vendor_number"] == "MIDAMER"
        assert p["sweep_run_id"] == "run-c2"
        assert p["extracted_vendor"] == "Mid America Logistics Group, LLC"

    @pytest.mark.asyncio
    async def test_c3_idempotent(self, fake_db):
        d = _doc(doc_id="DOC-C3")
        fake_db.hub_documents.rows = [d]
        # first run
        r1 = await sweep_mod.sweep(
            apply=True, max_heals=None, doc_id_filter=None, sweep_run_id="run-c3-1",
        )
        assert len(r1["heal_results"]) == 1
        # second run — doc now has canonical = bc_display, so classify=CLEAN
        r2 = await sweep_mod.sweep(
            apply=True, max_heals=None, doc_id_filter=None, sweep_run_id="run-c3-2",
        )
        assert r2["heal_results"] == []
        assert r2["bucket_counts"].get(BUCKET_AUTO_HEAL, 0) == 0
        assert r2["bucket_counts"][BUCKET_CLEAN] == 1
        # only one history entry persists
        assert len(fake_db.hub_documents.rows[0]["self_heal_history"]) == 1

    @pytest.mark.asyncio
    async def test_c4_per_doc_failure_does_not_abort(self, fake_db):
        d1 = _doc(doc_id="DOC-C4-FAIL")
        d2 = _doc(doc_id="DOC-C4-OK")
        fake_db.hub_documents.rows = [d1, d2]
        fake_db.hub_documents.update_should_fail_for_doc_id = "DOC-C4-FAIL"
        report = await sweep_mod.sweep(
            apply=True, max_heals=None, doc_id_filter=None, sweep_run_id="run-c4",
        )
        # one heal succeeded, one failure recorded
        ok_ids = [r["doc_id"] for r in report["heal_results"] if r.get("healed")]
        fail_ids = [r["doc_id"] for r in report["heal_failures"]]
        assert "DOC-C4-OK" in ok_ids
        assert "DOC-C4-FAIL" in fail_ids

    @pytest.mark.asyncio
    async def test_c5_max_heals_caps_apply(self, fake_db):
        fake_db.hub_documents.rows = [
            _doc(doc_id=f"DOC-C5-{i}") for i in range(5)
        ]
        report = await sweep_mod.sweep(
            apply=True, max_heals=2, doc_id_filter=None, sweep_run_id="run-c5",
        )
        assert len(report["heal_results"]) == 2
        # the auto_heal_doc_ids list still reflects the full population
        assert len(report["auto_heal_doc_ids"]) == 5


# ---------------------------------------------------------------------------
# Class D — Revert mode
# ---------------------------------------------------------------------------


class TestClassDRevert:
    @pytest.mark.asyncio
    async def test_d1_revert_restores_prior_values(self, fake_db):
        d = _doc(doc_id="DOC-D1")
        fake_db.hub_documents.rows = [d]
        await sweep_mod.sweep(
            apply=True, max_heals=None, doc_id_filter=None, sweep_run_id="run-d1",
        )
        result = await sweep_mod.revert_doc("DOC-D1")
        assert result["reverted"] is True
        row = fake_db.hub_documents.rows[0]
        assert row["vendor_canonical"] == "Brown Warehouse Company"
        assert row["bc_vendor_number"] == "BWC"

    @pytest.mark.asyncio
    async def test_d2_revert_pops_history_entry(self, fake_db):
        d = _doc(doc_id="DOC-D2")
        fake_db.hub_documents.rows = [d]
        await sweep_mod.sweep(
            apply=True, max_heals=None, doc_id_filter=None, sweep_run_id="run-d2",
        )
        await sweep_mod.revert_doc("DOC-D2")
        row = fake_db.hub_documents.rows[0]
        assert row.get("self_heal_history", []) == []

    @pytest.mark.asyncio
    async def test_d3_revert_emits_event(self, fake_db):
        d = _doc(doc_id="DOC-D3")
        fake_db.hub_documents.rows = [d]
        await sweep_mod.sweep(
            apply=True, max_heals=None, doc_id_filter=None, sweep_run_id="run-d3",
        )
        await sweep_mod.revert_doc("DOC-D3")
        revert_events = [e for e in fake_db.workflow_events.insert_calls
                         if e["event_type"] == "vendor.canonical_self_heal_reverted"]
        assert len(revert_events) == 1
        assert revert_events[0]["document_id"] == "DOC-D3"

    @pytest.mark.asyncio
    async def test_d4_revert_sweep_run_reverts_each(self, fake_db):
        fake_db.hub_documents.rows = [
            _doc(doc_id="DOC-D4-1"),
            _doc(doc_id="DOC-D4-2"),
        ]
        await sweep_mod.sweep(
            apply=True, max_heals=None, doc_id_filter=None, sweep_run_id="run-d4",
        )
        result = await sweep_mod.revert_sweep_run("run-d4")
        assert result["reverted_count"] == 2

    @pytest.mark.asyncio
    async def test_d5_revert_unknown_doc_returns_failure(self, fake_db):
        result = await sweep_mod.revert_doc("DOES-NOT-EXIST")
        assert result["reverted"] is False
        assert result["reason"] == "doc_not_found"

    @pytest.mark.asyncio
    async def test_d6_revert_doc_with_no_history(self, fake_db):
        fake_db.hub_documents.rows = [{"id": "NO-HIST", "document_type": "AP_Invoice"}]
        result = await sweep_mod.revert_doc("NO-HIST")
        assert result["reverted"] is False
        assert result["reason"] == "no_self_heal_history"


# ---------------------------------------------------------------------------
# Class E — Real-world fixtures
# ---------------------------------------------------------------------------


class TestClassEFixtures:
    def test_e1_mid_america_doc_classifies_auto_heal(self):
        d = _doc(
            extracted="Mid America Logistics Group, LLC",
            bc_number="MIDAMER",
            bc_display="Mid America Logistics Group LLC",
            canonical="Brown Warehouse Company",
        )
        bucket, ctx = _classify_doc(d)
        assert bucket == BUCKET_AUTO_HEAL
        assert ctx["bc_number"] == "MIDAMER"
        assert ctx["bc_display"] == "Mid America Logistics Group LLC"

    def test_e2_sc_warehouses_doc_classifies_no_bc(self):
        # SC Warehouses → YANDELL: alias_driven, BC never resolved this
        d = _doc(
            extracted="SC Warehouses, LLC",
            bc_number=None,
            bc_display=None,
            canonical="YANDELL",
        )
        bucket, _ = _classify_doc(d)
        assert bucket == BUCKET_NA_NO_BC
