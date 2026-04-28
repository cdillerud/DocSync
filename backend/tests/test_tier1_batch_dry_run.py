"""
Tier 1 dry-run unit tests — deterministic, offline.

Verifies:
  - candidate selection query shape
  - vendor re-resolution falls back across alias / profile / unresolved
  - duplicate-check correctly identifies HIT / clean
  - line completeness flag fires for zero-line docs
  - bucket classifier maps known HTTP shapes to expected buckets
  - repeatable-malformed-shape signature is stable for identical bodies

No live BC calls. No live Mongo. Uses an in-process fake DB.
"""
from __future__ import annotations

import sys
from pathlib import Path

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(BACKEND_DIR))
sys.path.insert(0, str(BACKEND_DIR / "scripts"))

import tier1_batch_runner as runner  # noqa: E402


# ---------- fake async cursor + collection ----------


class _FakeCursor:
    def __init__(self, rows):
        self._rows = list(rows)
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._rows):
            raise StopAsyncIteration
        row = self._rows[self._i]
        self._i += 1
        return row


class _FakeColl:
    def __init__(self, rows=None, find_one_result=None):
        self._rows = rows or []
        self._find_one_result = find_one_result

    def aggregate(self, pipe):
        return _FakeCursor(self._rows)

    async def find_one(self, q, projection=None):
        return self._find_one_result


class _FakeDB:
    def __init__(self, hub_docs=None, alias=None, profile=None, ref_cache=None):
        self.hub_documents = _FakeColl(rows=hub_docs)
        self.vendor_aliases = _FakeColl(find_one_result=alias)
        self.vendor_invoice_profiles = _FakeColl(find_one_result=profile)
        self.bc_reference_cache = _FakeColl(find_one_result=ref_cache)


# ---------- selection ----------


@pytest.mark.asyncio
async def test_select_candidates_returns_empty_when_no_docs():
    db = _FakeDB(hub_docs=[])
    cands = await runner._select_candidates(db, limit=10)
    assert cands == []


@pytest.mark.asyncio
async def test_select_candidates_maps_extracted_fields():
    doc = {
        "id": "doc-1",
        "document_type": "AP_Invoice",
        "status": "Completed",
        "extracted_fields": {
            "vendor": "Acme Co",
            "invoice_number": "INV-001",
            "invoice_date": "2026-04-20",
            "total": 123.45,
            "line_items": [{"qty": 1}, {"qty": 2}],
        },
        "vendor_canonical": "V123",
    }
    db = _FakeDB(hub_docs=[doc])
    cands = await runner._select_candidates(db)
    assert len(cands) == 1
    c = cands[0]
    assert c.doc_id == "doc-1"
    assert c.vendor_no == "V123"
    assert c.vendor_name == "Acme Co"
    assert c.invoice_number == "INV-001"
    assert c.line_count == 2
    assert c.total_amount == 123.45


# ---------- vendor resolution ----------


@pytest.mark.asyncio
async def test_vendor_resolve_returns_alias_when_present():
    db = _FakeDB(alias={"vendor_no": "V-ALIAS", "alias": "Acme"})
    c = runner.Candidate(
        doc_id="d", vendor_name="Acme", vendor_no=None, invoice_number="i",
        invoice_date="", total_amount=10, line_count=1,
        status="Completed", workflow_status="processed", document_type="AP_Invoice",
    )
    v_no, method = await runner._vendor_resolve(db, c)
    assert v_no == "V-ALIAS"
    assert "alias" in method


@pytest.mark.asyncio
async def test_vendor_resolve_falls_back_to_profile():
    db = _FakeDB(alias=None, profile={"vendor_no": "V-PROF", "vendor_name": "Acme"})
    c = runner.Candidate(
        doc_id="d", vendor_name="Acme", vendor_no=None, invoice_number="i",
        invoice_date="", total_amount=10, line_count=1,
        status="Completed", workflow_status="processed", document_type="AP_Invoice",
    )
    v_no, method = await runner._vendor_resolve(db, c)
    assert v_no == "V-PROF"
    assert "profile" in method


@pytest.mark.asyncio
async def test_vendor_resolve_unresolved_returns_empty():
    db = _FakeDB(alias=None, profile=None)
    c = runner.Candidate(
        doc_id="d", vendor_name="Nobody", vendor_no=None, invoice_number="i",
        invoice_date="", total_amount=10, line_count=1,
        status="Completed", workflow_status="processed", document_type="AP_Invoice",
    )
    v_no, method = await runner._vendor_resolve(db, c)
    assert v_no == ""
    assert "no alias or profile" in method


# ---------- duplicate check ----------


@pytest.mark.asyncio
async def test_dup_check_clean_when_no_match():
    db = _FakeDB(ref_cache=None)
    c = runner.Candidate(
        doc_id="d", vendor_name="Acme", vendor_no="V1", invoice_number="INV-001",
        invoice_date="", total_amount=10, line_count=1,
        status="Completed", workflow_status="processed", document_type="AP_Invoice",
    )
    status, _ = await runner._dup_check(db, c)
    assert status == "clean"


@pytest.mark.asyncio
async def test_dup_check_hit_when_cache_returns_pi():
    db = _FakeDB(ref_cache={"data": {"number": "PI-9", "vendorNumber": "V1"}})
    c = runner.Candidate(
        doc_id="d", vendor_name="Acme", vendor_no="V1", invoice_number="INV-001",
        invoice_date="", total_amount=10, line_count=1,
        status="Completed", workflow_status="processed", document_type="AP_Invoice",
    )
    status, detail = await runner._dup_check(db, c)
    assert status == "HIT"
    assert "PI-9" in detail


@pytest.mark.asyncio
async def test_dup_check_skip_when_no_invoice_number():
    db = _FakeDB(ref_cache={"data": {"number": "PI-9"}})
    c = runner.Candidate(
        doc_id="d", vendor_name="Acme", vendor_no="V1", invoice_number="",
        invoice_date="", total_amount=10, line_count=1,
        status="Completed", workflow_status="processed", document_type="AP_Invoice",
    )
    status, _ = await runner._dup_check(db, c)
    assert status == "skip"


# ---------- bucket classifier ----------


@pytest.mark.parametrize("status,body,expected", [
    (200, {"success": True, "bc_record_no": "PI-1"}, "P1"),
    (200, {"success": True, "already_exists": True, "bc_record_no": "PI-1"}, "F-DUP"),
    (401, {"detail": "unauthorized"}, "F-AUTH"),
    (403, {"detail": "forbidden"}, "F-AUTH"),
    (422, {"detail": {"error": "missing_vendor", "message": "no vendor"}}, "F-REF"),
    (422, {"detail": "Duplicate detected"}, "F-DUP"),
    (422, {"detail": "Invalid invoice_number"}, "F-DATA"),
    (404, {"detail": "Document not found"}, "F-DATA"),
    (503, {"detail": "BC credentials not configured"}, "F-CONFIG"),
    (500, {"detail": "Posting period closed"}, "F-RULE"),
    (500, {"detail": "Vendor on hold"}, "F-RULE"),
    (500, {"detail": "Unhandled exception in writer"}, "F-BUG"),
])
def test_classify_buckets(status, body, expected):
    assert runner._classify(status, body, None) == expected


def test_classify_network_when_exception():
    assert runner._classify(None, None, RuntimeError("connection refused")) == "F-NETWORK"
    assert runner._classify(None, None, RuntimeError("timeout")) == "F-NETWORK"


def test_classify_bug_on_unknown_exception():
    assert runner._classify(None, None, RuntimeError("kaboom")) == "F-BUG"


# ---------- shape signature stability ----------


def test_shape_signature_stable_for_identical_bodies():
    a = runner._shape_signature(422, {"detail": "missing field x"})
    b = runner._shape_signature(422, {"detail": "missing field x"})
    assert a == b


def test_shape_signature_differs_when_status_differs():
    a = runner._shape_signature(422, {"detail": "x"})
    b = runner._shape_signature(500, {"detail": "x"})
    assert a != b


# ---------- credential plausibility guard (Phase 1 check #6) ----------


import re  # noqa: E402

GUID_RE = re.compile(
    r"^[0-9a-f]{8}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{4}-[0-9a-f]{12}$",
    re.IGNORECASE,
)


@pytest.mark.parametrize("value,looks_real", [
    ("c7b2de14-71d9-4c49-a0b9-2bec103a6fdc", True),     # real GUID
    ("6ac62e44-8968-4ad9-b781-434507a5c83a", True),     # real GUID
    ("doc-workflow-test", False),                       # placeholder string
    ("order-ledger-1", False),                          # placeholder string
    ("test", False),                                    # placeholder
    ("", False),                                        # empty
    ("not-a-guid-at-all", False),                       # garbage
])
def test_guid_pattern_recognizes_real_vs_placeholder(value, looks_real):
    assert bool(GUID_RE.match(value)) is looks_real


# ---------- vendor-mismatch heuristic (Phase 3 risk detection) ----------


@pytest.mark.parametrize("extracted,canonical,expect_match", [
    # exact case-insensitive equality
    ("Mexus Inc.", "MEXUS, INC", True),
    # substring containment (BC vendor code vs full name)
    ("TUMALO CREEK Transportation", "TUMALOC", True),
    ("Massilly North America", "MASSILL", True),
    # token overlap
    ("LSI Distribution", "Lone Star Integrated Distribution, LLC", True),
    ("Progressive Logistics", "Progressive Logistics", True),
    # real mismatches that should flag
    ("Mid America Logistics Group, LLC", "Brown Warehouse Company", False),
    ("SC Warehouses, LLC", "YANDELL", False),
    # empty inputs return True (insufficient signal — don't flag)
    ("", "Brown Warehouse", True),
    ("Mid America", "", True),
])
def test_vendor_match_likely_heuristic(extracted, canonical, expect_match):
    assert runner._vendor_match_likely(extracted, canonical) is expect_match
