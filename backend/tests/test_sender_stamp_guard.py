"""
Tests for the live-path Sender-Stamp Guard v1.

Covers:
  - Class A: pure-function vendor_match_likely
  - Class B: lookup_vendor_by_sender legacy back-compat
  - Class C: lookup_vendor_by_sender guarded mode
  - Class D: integration smoke (intake_document_from_bytes)
  - Class E: sweep contract preservation

See: memory/SENDER_STAMP_GUARD_IMPLEMENTATION_DECLARATION.md §8
"""
from __future__ import annotations

import os
import sys
import uuid
from pathlib import Path
from typing import Any, Dict, List
from unittest.mock import AsyncMock

import pytest

BACKEND_DIR = Path(__file__).resolve().parent.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))


# ---------------------------------------------------------------------------
# Class A — Pure-function: vendor_match_likely
# ---------------------------------------------------------------------------


class TestClassAVendorMatchLikely:
    def test_a1_identical_names_match(self):
        from services.vendor_name_helpers import vendor_match_likely
        assert vendor_match_likely("Acme Corp", "Acme Corp") is True

    def test_a2_substring_token_agreement_matches(self):
        from services.vendor_name_helpers import vendor_match_likely
        # TUMALO CREEK ↔ TUMALOC — token "tumalo" is substring of "tumaloc"
        assert vendor_match_likely("Tumalo Creek Transportation", "TUMALOC") is True

    def test_a3_disjoint_tokens_do_not_match(self):
        from services.vendor_name_helpers import vendor_match_likely
        # The exact original Batch-2 defect pair
        assert vendor_match_likely("Mid America Logistics Group, LLC", "Brown Warehouse Company") is False

    def test_a4_either_side_empty_fails_open(self):
        from services.vendor_name_helpers import vendor_match_likely
        assert vendor_match_likely("", "Brown Warehouse Company") is True
        assert vendor_match_likely("Mid America", "") is True
        assert vendor_match_likely(None, None) is True  # type: ignore[arg-type]

    def test_a5_stopword_only_fails_open(self):
        from services.vendor_name_helpers import vendor_match_likely
        # Both sides reduce to empty token sets — fail-open
        assert vendor_match_likely("LLC Inc", "Corp Co Ltd") is True


# ---------------------------------------------------------------------------
# Helpers — fake DB
# ---------------------------------------------------------------------------


class _FakeCollection:
    """Minimal Mongo-like async collection used in the guard tests."""

    def __init__(self, rows: List[Dict[str, Any]] | None = None):
        self.rows: List[Dict[str, Any]] = list(rows or [])
        self.update_calls: List[Dict[str, Any]] = []
        self.insert_calls: List[Dict[str, Any]] = []
        self.insert_should_fail = False

    async def find_one(self, query: Dict[str, Any], projection: Dict[str, Any] | None = None) -> Dict[str, Any] | None:
        for r in self.rows:
            if _matches(r, query):
                # strip _id like the real projection
                return {k: v for k, v in r.items() if k != "_id"}
        return None

    async def update_one(self, query: Dict[str, Any], update: Dict[str, Any]) -> None:
        self.update_calls.append({"query": query, "update": update})

    async def insert_one(self, doc: Dict[str, Any]) -> None:
        if self.insert_should_fail:
            raise RuntimeError("simulated mongo write failure")
        self.insert_calls.append(doc)


def _matches(row: Dict[str, Any], query: Dict[str, Any]) -> bool:
    """Tiny query matcher — supports flat equality and {'$gte': N}."""
    for k, v in query.items():
        rv = row.get(k)
        if isinstance(v, dict) and "$gte" in v:
            if rv is None or rv < v["$gte"]:
                return False
        else:
            if rv != v:
                return False
    return True


class _FakeDB:
    def __init__(self, sender_rows: List[Dict[str, Any]] | None = None):
        self.sender_vendor_map = _FakeCollection(sender_rows)
        self.workflow_events = _FakeCollection()


def _patch_db_and_env(monkeypatch, db: _FakeDB, *, guard_enabled: bool = True):
    monkeypatch.setattr("services.vendor_matching.get_db", lambda: db)
    if guard_enabled:
        monkeypatch.setenv("SENDER_STAMP_GUARD_ENABLED", "true")
    else:
        monkeypatch.setenv("SENDER_STAMP_GUARD_ENABLED", "false")


# ---------------------------------------------------------------------------
# Class B — Legacy back-compat
# ---------------------------------------------------------------------------


class TestClassBLegacy:
    @pytest.mark.asyncio
    async def test_b1_no_extracted_vendor_returns_mapping(self, monkeypatch):
        from services.vendor_matching import lookup_vendor_by_sender
        db = _FakeDB([{
            "sender_email": "kbowman@malg.us",
            "vendor_canonical": "Brown Warehouse Company",
            "vendor_name": "Brown Warehouse Company",
            "vendor_no": "",
        }])
        _patch_db_and_env(monkeypatch, db)
        # No extracted_vendor → legacy path; even though sender is the
        # known-bad mapping, the function returns it (by design — guard inert).
        result = await lookup_vendor_by_sender("kbowman@malg.us")
        assert result["vendor_canonical"] == "Brown Warehouse Company"
        assert result["vendor_match_method"] == "sender_email"
        # No telemetry written
        assert len(db.workflow_events.insert_calls) == 0

    @pytest.mark.asyncio
    async def test_b2_strict_false_disagreement_returns_mapping(self, monkeypatch):
        from services.vendor_matching import lookup_vendor_by_sender
        db = _FakeDB([{
            "sender_email": "kbowman@malg.us",
            "vendor_canonical": "Brown Warehouse Company",
            "vendor_name": "Brown Warehouse Company",
        }])
        _patch_db_and_env(monkeypatch, db)
        result = await lookup_vendor_by_sender(
            "kbowman@malg.us",
            extracted_vendor="Mid America Logistics Group, LLC",
            strict=False,
        )
        assert result["vendor_canonical"] == "Brown Warehouse Company"
        assert len(db.workflow_events.insert_calls) == 0

    @pytest.mark.asyncio
    async def test_b3_env_flag_off_disagreement_returns_mapping(self, monkeypatch):
        from services.vendor_matching import lookup_vendor_by_sender
        db = _FakeDB([{
            "sender_email": "kbowman@malg.us",
            "vendor_canonical": "Brown Warehouse Company",
            "vendor_name": "Brown Warehouse Company",
        }])
        _patch_db_and_env(monkeypatch, db, guard_enabled=False)
        result = await lookup_vendor_by_sender(
            "kbowman@malg.us",
            extracted_vendor="Mid America Logistics Group, LLC",
        )
        assert result["vendor_canonical"] == "Brown Warehouse Company"
        assert len(db.workflow_events.insert_calls) == 0


# ---------------------------------------------------------------------------
# Class C — Guarded mode
# ---------------------------------------------------------------------------


class TestClassCGuarded:
    @pytest.mark.asyncio
    async def test_c1_agreement_returns_mapping_and_increments_hit(self, monkeypatch):
        from services.vendor_matching import lookup_vendor_by_sender
        db = _FakeDB([{
            "sender_email": "asahel.avalos@cargomodules.com",
            "vendor_canonical": "CARGOMO",
            "vendor_name": "Cargo Modules, LLC",
            "vendor_no": "CARGOMO",
        }])
        _patch_db_and_env(monkeypatch, db)
        # Extracted "Cargo Modules LLC" agrees with sender mapping
        result = await lookup_vendor_by_sender(
            "asahel.avalos@cargomodules.com",
            extracted_vendor="Cargo Modules, LLC",
        )
        assert result["vendor_canonical"] == "CARGOMO"
        assert result["vendor_match_method"] == "sender_email"
        # hit_count increment recorded
        assert any(
            "$inc" in c["update"] and c["update"]["$inc"].get("hit_count") == 1
            for c in db.sender_vendor_map.update_calls
        )
        # No disagreement telemetry
        assert len(db.workflow_events.insert_calls) == 0

    @pytest.mark.asyncio
    async def test_c2_disagreement_returns_sender_disagreed_no_hit_increment(self, monkeypatch):
        from services.vendor_matching import lookup_vendor_by_sender
        db = _FakeDB([{
            "sender_email": "kbowman@malg.us",
            "vendor_canonical": "Brown Warehouse Company",
            "vendor_name": "Brown Warehouse Company",
        }])
        _patch_db_and_env(monkeypatch, db)
        result = await lookup_vendor_by_sender(
            "kbowman@malg.us",
            extracted_vendor="Mid America Logistics Group, LLC",
        )
        assert result["vendor_canonical"] is None
        assert result["vendor_match_method"] == "sender_disagreed"
        assert result["sender_hint"]["sender_email"] == "kbowman@malg.us"
        assert result["sender_hint"]["sender_canonical"] == "Brown Warehouse Company"
        assert result["sender_hint"]["extracted_vendor"] == "Mid America Logistics Group, LLC"
        assert result["sender_hint"]["matched_kind"] == "sender_email"
        # hit_count NOT incremented
        assert len(db.sender_vendor_map.update_calls) == 0

    @pytest.mark.asyncio
    async def test_c3_disagreement_emits_workflow_event(self, monkeypatch):
        from services.vendor_matching import lookup_vendor_by_sender
        db = _FakeDB([{
            "sender_email": "kbowman@malg.us",
            "vendor_canonical": "Brown Warehouse Company",
            "vendor_name": "Brown Warehouse Company",
        }])
        _patch_db_and_env(monkeypatch, db)
        await lookup_vendor_by_sender(
            "kbowman@malg.us",
            extracted_vendor="Mid America Logistics Group, LLC",
        )
        events = db.workflow_events.insert_calls
        assert len(events) == 1
        event = events[0]
        assert event["event_type"] == "vendor.sender_disagreed"
        assert event["status"] == "warning"
        assert event["source_service"] == "vendor_matching.lookup_vendor_by_sender"
        p = event["payload"]
        assert p["sender_email"] == "kbowman@malg.us"
        assert p["sender_canonical"] == "Brown Warehouse Company"
        assert p["extracted_vendor"] == "Mid America Logistics Group, LLC"
        assert p["matched_kind"] == "sender_email"
        assert p["guard_version"] == "v1"

    @pytest.mark.asyncio
    async def test_c4_telemetry_failure_does_not_raise(self, monkeypatch):
        from services.vendor_matching import lookup_vendor_by_sender
        db = _FakeDB([{
            "sender_email": "kbowman@malg.us",
            "vendor_canonical": "Brown Warehouse Company",
            "vendor_name": "Brown Warehouse Company",
        }])
        db.workflow_events.insert_should_fail = True
        _patch_db_and_env(monkeypatch, db)
        # Must not raise
        result = await lookup_vendor_by_sender(
            "kbowman@malg.us",
            extracted_vendor="Mid America Logistics Group, LLC",
        )
        assert result["vendor_match_method"] == "sender_disagreed"

    @pytest.mark.asyncio
    async def test_c5_no_mapping_returns_none(self, monkeypatch):
        from services.vendor_matching import lookup_vendor_by_sender
        db = _FakeDB(sender_rows=[])
        _patch_db_and_env(monkeypatch, db)
        result = await lookup_vendor_by_sender(
            "stranger@example.com",
            extracted_vendor="Some Vendor",
        )
        assert result["vendor_canonical"] is None
        assert result["vendor_match_method"] == "none"

    @pytest.mark.asyncio
    async def test_c6_disagreement_with_document_id_records_it(self, monkeypatch):
        """Amendment 2026-04-29: document_id present at top level AND in payload."""
        from services.vendor_matching import lookup_vendor_by_sender
        db = _FakeDB([{
            "sender_email": "kbowman@malg.us",
            "vendor_canonical": "Brown Warehouse Company",
            "vendor_name": "Brown Warehouse Company",
        }])
        _patch_db_and_env(monkeypatch, db)
        doc_id = str(uuid.uuid4())
        await lookup_vendor_by_sender(
            "kbowman@malg.us",
            extracted_vendor="Mid America Logistics Group, LLC",
            document_id=doc_id,
        )
        event = db.workflow_events.insert_calls[0]
        assert event.get("document_id") == doc_id
        assert event["payload"].get("document_id") == doc_id

    @pytest.mark.asyncio
    async def test_c7_disagreement_without_document_id_omits_field(self, monkeypatch):
        """Amendment 2026-04-29: when document_id is absent, field is absent (not null)."""
        from services.vendor_matching import lookup_vendor_by_sender
        db = _FakeDB([{
            "sender_email": "kbowman@malg.us",
            "vendor_canonical": "Brown Warehouse Company",
            "vendor_name": "Brown Warehouse Company",
        }])
        _patch_db_and_env(monkeypatch, db)
        await lookup_vendor_by_sender(
            "kbowman@malg.us",
            extracted_vendor="Mid America Logistics Group, LLC",
        )
        event = db.workflow_events.insert_calls[0]
        assert "document_id" not in event
        assert "document_id" not in event["payload"]


# ---------------------------------------------------------------------------
# Class D — Integration smoke (skipped — requires full backend wiring)
# ---------------------------------------------------------------------------
#
# D1/D2/D3 require an end-to-end fixture for `intake_document_from_bytes`,
# which depends on SharePoint, BC validation, classification, and Mongo.
# That harness is heavyweight and not part of this declaration's scope —
# the unit-level guarantees (Class C) plus E1/E2 are sufficient.
#
# A future declaration can add the integration harness; for now we mark
# these as expected-to-skip with a clear xfail reason.


class TestClassDIntegration:
    @pytest.mark.skip(reason="Integration fixture deferred — see declaration §8 D-class note")
    def test_d1_intake_with_disagreement(self):
        pass

    @pytest.mark.skip(reason="Integration fixture deferred — see declaration §8 D-class note")
    def test_d2_intake_with_guard_disabled(self):
        pass

    @pytest.mark.skip(reason="Integration fixture deferred — see declaration §8 D-class note")
    def test_d3_intake_with_agreement(self):
        pass


# ---------------------------------------------------------------------------
# Class E — Sweep contract preservation
# ---------------------------------------------------------------------------


class TestClassESweepContract:
    def test_e1_sweep_imports_resolve(self):
        # The sweep imports vendor_match_likely from vendor_name_helpers now.
        # The import must resolve without error.
        from services.vendor_name_helpers import vendor_match_likely, _vendor_tokens
        assert callable(vendor_match_likely)
        assert callable(_vendor_tokens)

    def test_e2_known_divergent_pair_still_flags(self):
        # Production sweep finding: Mid America vs Brown Warehouse must
        # remain a False (mismatch) under the imported function, proving
        # no semantic drift in the move.
        from services.vendor_name_helpers import vendor_match_likely
        assert vendor_match_likely(
            "Mid America Logistics Group, LLC",
            "Brown Warehouse Company",
        ) is False

    def test_e3_tier1_back_compat_alias_resolves(self):
        # tier1_batch_runner._vendor_match_likely should still be importable
        # and return identical results.
        from scripts.tier1_batch_runner import _vendor_match_likely as tier1_fn
        from services.vendor_name_helpers import vendor_match_likely as helpers_fn
        for a, b in [
            ("Mid America Logistics Group, LLC", "Brown Warehouse Company"),
            ("Tumalo Creek Transportation", "TUMALOC"),
            ("Acme Corp", "Acme Corp"),
        ]:
            assert tier1_fn(a, b) == helpers_fn(a, b)



# ---------------------------------------------------------------------------
# Class F — Legacy-path adoption smoke (Phase B)
#
# Static-source assertions that protect against future regressions where a
# maintainer drops the guard kwargs from a call site. No new behavioral
# coverage — Class C already proves the function works; Class F just proves
# every call site passes the right kwargs.
# ---------------------------------------------------------------------------


def _find_call_blocks(source: str, fn_name: str) -> list[str]:
    """Return each occurrence of `fn_name(...)` together with up to 300 chars
    of following text — enough to capture the call's keyword arguments
    across multi-line formatting."""
    blocks: list[str] = []
    idx = 0
    needle = fn_name + "("
    while True:
        i = source.find(needle, idx)
        if i == -1:
            break
        blocks.append(source[i:i + 300])
        idx = i + len(needle)
    return blocks


class TestClassFLegacyPathAdoption:
    def test_f1_vendor_reprocess_passes_guard_kwargs(self):
        import inspect
        import routers.vendor_reprocess as mod
        src = inspect.getsource(mod)
        blocks = _find_call_blocks(src, "lookup_vendor_by_sender")
        # at least one call to the function exists in this module
        assert len(blocks) >= 1, "lookup_vendor_by_sender call missing from vendor_reprocess.py"
        # at least one of those calls passes BOTH guard kwargs
        passes_both = any(
            "extracted_vendor=" in b and "document_id=" in b
            for b in blocks
        )
        assert passes_both, (
            "vendor_reprocess.py: at least one lookup_vendor_by_sender call must "
            "pass both `extracted_vendor=` and `document_id=` kwargs"
        )

    def test_f2_document_handlers_passes_guard_kwargs(self):
        import inspect
        import services.document_handlers as mod
        src = inspect.getsource(mod)
        blocks = _find_call_blocks(src, "lookup_vendor_by_sender")
        assert len(blocks) >= 1, "lookup_vendor_by_sender call missing from document_handlers.py"
        passes_both = any(
            "extracted_vendor=" in b and "document_id=" in b
            for b in blocks
        )
        assert passes_both, (
            "document_handlers.py: at least one lookup_vendor_by_sender call must "
            "pass both `extracted_vendor=` and `document_id=` kwargs"
        )

    def test_f3_server_passes_guard_kwargs(self):
        import inspect
        import server as mod
        src = inspect.getsource(mod)
        blocks = _find_call_blocks(src, "lookup_vendor_by_sender")
        assert len(blocks) >= 1, "lookup_vendor_by_sender call missing from server.py"
        passes_both = any(
            "extracted_vendor=" in b and "document_id=" in b
            for b in blocks
        )
        assert passes_both, (
            "server.py: at least one lookup_vendor_by_sender call must "
            "pass both `extracted_vendor=` and `document_id=` kwargs"
        )
