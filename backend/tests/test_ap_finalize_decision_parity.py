"""Phase 3 Step 3 — AP auto-post branch extraction parity tests.

Proves that replacing the two inline AP-decision branches in ``server.py``
(``_internal_intake_document`` and ``_reprocess_document_inner``) with calls to
``services.ap_auto_post_service.finalize_ap_decision`` is BEHAVIOR-PRESERVING.

Four classes:

* Class A — Pure-result parity: assert ``finalize_ap_decision`` returns exactly
  the status flip the inline branch would have computed across 6 canonical
  fixtures of ``attempt_ap_auto_post`` output + 2 exception paths.
* Class B — DB-mutation parity: capture the exact sequence of Motor ``update_one``
  and ``insert_one`` calls the helper makes; assert against a golden fixture.
* Class C — Source-inspection guardrail: assert ``server.py`` no longer imports
  ``attempt_ap_auto_post`` from the two finalized branches and uses
  ``finalize_ap_decision`` exactly twice.
* Class D — Live-surface smoke: lightweight shape assertion against
  ``localhost:8001`` — SKIPS gracefully if no backend is reachable.

Deterministic. No Mongo required for Classes A/B/C. Class D skips on no backend.
"""

from __future__ import annotations

import asyncio
import inspect
import json
import os
from pathlib import Path
from typing import Any, Dict, List, Optional

import pytest


# ---------------------------------------------------------------------------
# In-memory DB double — captures every mutation for golden-file parity
# ---------------------------------------------------------------------------
class _CollectionDouble:
    """Records update_one / insert_one calls without persistence."""

    def __init__(self, name: str, events: List[Dict[str, Any]]) -> None:
        self._name = name
        self._events = events

    async def update_one(self, filt: Dict, update: Dict) -> Any:
        self._events.append({
            "op": "update_one",
            "collection": self._name,
            "filter": filt,
            "update": update,
        })
        return type("UpdRes", (), {"modified_count": 1, "matched_count": 1})()

    async def insert_one(self, doc: Dict) -> Any:
        # Strip non-deterministic keys for golden parity.
        stable_doc = {k: v for k, v in doc.items() if k not in ("event_id", "timestamp")}
        self._events.append({
            "op": "insert_one",
            "collection": self._name,
            "doc": stable_doc,
            "keys_present": sorted(doc.keys()),
        })
        return type("InsRes", (), {"inserted_id": "stub"})()

    async def find_one(self, *a, **kw) -> None:
        return None


class _DbDouble:
    def __init__(self) -> None:
        self.events: List[Dict[str, Any]] = []
        self.hub_documents = _CollectionDouble("hub_documents", self.events)
        self.workflow_events = _CollectionDouble("workflow_events", self.events)


# ---------------------------------------------------------------------------
# Fixtures of ``attempt_ap_auto_post`` return values
# ---------------------------------------------------------------------------
AP_RESULT_POSTED = {"success": True, "posted": True, "bc_record_no": "PI-2026-00042", "status": "Posted"}
AP_RESULT_READY = {"success": True, "posted": False, "status": "ReadyForPost", "reason": "BC writes disabled"}
AP_RESULT_NEEDS_REVIEW = {"success": False, "posted": False, "status": "NeedsReview", "reason": "PO not matched"}
AP_RESULT_UNKNOWN = {"success": False, "posted": False}  # Neither posted nor ReadyForPost → NeedsReview
AP_RESULT_MALFORMED = {}  # Empty dict → falls through to NeedsReview
AP_RESULT_EMPTY_NONE = None  # Defensive — caller returned None


# ---------------------------------------------------------------------------
# Class A — Pure-result parity
# ---------------------------------------------------------------------------
class TestPureResultParity:
    """finalize_ap_decision return-value matches inline-branch behavior."""

    @staticmethod
    def _inline_intake_compute(ap_result: Dict[str, Any] | None) -> Dict[str, Any]:
        """Recreates the exact intake inline-branch decision tree."""
        r = ap_result or {}
        if r.get("posted"):
            return {"status": "Posted", "posted": True, "bc_record_no": r.get("bc_record_no"), "reason": None}
        if r.get("status") == "ReadyForPost":
            return {"status": "ReadyForPost", "posted": False, "bc_record_no": None, "reason": None}
        return {"status": "NeedsReview", "posted": False, "bc_record_no": None, "reason": r.get("reason")}

    @pytest.mark.parametrize("ap_result,expected_status,expected_posted", [
        (AP_RESULT_POSTED, "Posted", True),
        (AP_RESULT_READY, "ReadyForPost", False),
        (AP_RESULT_NEEDS_REVIEW, "NeedsReview", False),
        (AP_RESULT_UNKNOWN, "NeedsReview", False),
        (AP_RESULT_MALFORMED, "NeedsReview", False),
    ])
    def test_finalize_matches_inline_intake(self, monkeypatch, ap_result, expected_status, expected_posted):
        from services import ap_auto_post_service

        async def _stub_attempt(_doc_id, _db, source):
            return ap_result

        monkeypatch.setattr(ap_auto_post_service, "attempt_ap_auto_post", _stub_attempt)

        db = _DbDouble()
        result = asyncio.run(ap_auto_post_service.finalize_ap_decision(
            "doc-A", db, source="auto",
        ))

        inline = self._inline_intake_compute(ap_result)
        assert result["status"] == expected_status == inline["status"]
        assert result["posted"] == expected_posted == inline["posted"]
        assert result["bc_record_no"] == inline["bc_record_no"]
        assert result["reason"] == inline["reason"]
        assert result["events_emitted"] == 0  # intake-branch → no reprocess events

    def test_intake_exception_is_swallowed(self, monkeypatch):
        from services import ap_auto_post_service

        async def _raise(_doc_id, _db, source):
            raise RuntimeError("boom")

        monkeypatch.setattr(ap_auto_post_service, "attempt_ap_auto_post", _raise)

        db = _DbDouble()
        result = asyncio.run(ap_auto_post_service.finalize_ap_decision(
            "doc-X", db, source="auto", on_exception_fallback_status=None,
        ))
        # Intake-branch parity: swallow → no hub_documents update, status stays default.
        assert result["status"] == "NeedsReview"
        assert result["posted"] is False
        hub_updates = [e for e in db.events if e["collection"] == "hub_documents"]
        assert hub_updates == [], "Intake-branch parity: exception must not write status"

    def test_reprocess_exception_writes_needs_review(self, monkeypatch):
        from services import ap_auto_post_service

        async def _raise(_doc_id, _db, source):
            raise RuntimeError("boom")

        monkeypatch.setattr(ap_auto_post_service, "attempt_ap_auto_post", _raise)

        db = _DbDouble()
        result = asyncio.run(ap_auto_post_service.finalize_ap_decision(
            "doc-X", db, source="reprocess", on_exception_fallback_status="NeedsReview",
        ))
        # Reprocess-branch parity: on exception, must write status=NeedsReview.
        assert result["status"] == "NeedsReview"
        hub_updates = [e for e in db.events if e["collection"] == "hub_documents"]
        assert len(hub_updates) == 1
        assert hub_updates[0]["update"] == {"$set": {"status": "NeedsReview"}}


# ---------------------------------------------------------------------------
# Class B — DB-mutation parity (golden-file snapshot)
# ---------------------------------------------------------------------------
GOLDEN_DIR = Path(__file__).parent / "fixtures"
GOLDEN_FILE = GOLDEN_DIR / "ap_finalize_golden.json"


def _run_and_capture(source: str, ap_result: Dict[str, Any], **kwargs) -> List[Dict[str, Any]]:
    """Helper: run finalize_ap_decision with stubbed attempt, return event list
    FILTERED to only the mutations finalize_ap_decision is directly responsible
    for — the hub_documents.status flip and the 2 workflow_events inserts.

    Side-effects from ``DerivedStateService.update_document_derived_state``
    (extra hub_documents updates carrying wall-clock timestamps) are out of
    scope for the Step 3 parity contract and are filtered out here.
    """
    from services import ap_auto_post_service

    async def _stub(_doc_id, _db, source):
        return ap_result

    original = ap_auto_post_service.attempt_ap_auto_post
    ap_auto_post_service.attempt_ap_auto_post = _stub  # type: ignore[assignment]
    try:
        db = _DbDouble()
        asyncio.run(ap_auto_post_service.finalize_ap_decision(
            "doc-golden", db, source=source, **kwargs,
        ))
        events = db.events
    finally:
        ap_auto_post_service.attempt_ap_auto_post = original  # type: ignore[assignment]

    # Scope filter: keep only the status flip + workflow_events inserts.
    filtered: List[Dict[str, Any]] = []
    for ev in events:
        if ev["collection"] == "hub_documents" and ev["op"] == "update_one":
            # Only the direct status flip (single key: "status") is in-scope.
            set_payload = ev.get("update", {}).get("$set", {})
            if set(set_payload.keys()) == {"status"}:
                filtered.append(ev)
            # Else: derived-state side-effect, drop.
        elif ev["collection"] == "workflow_events" and ev["op"] == "insert_one":
            filtered.append(ev)
    return filtered


def _build_golden_snapshot() -> Dict[str, List[Dict[str, Any]]]:
    """Produces the full golden snapshot across all scenarios."""
    scenarios: Dict[str, List[Dict[str, Any]]] = {}
    # Intake path (no reprocess events)
    scenarios["intake_posted"] = _run_and_capture("auto", AP_RESULT_POSTED)
    scenarios["intake_ready"] = _run_and_capture("auto", AP_RESULT_READY)
    scenarios["intake_needs_review"] = _run_and_capture("auto", AP_RESULT_NEEDS_REVIEW)
    # Reprocess path (emit_reprocess_events=True, fallback="NeedsReview")
    scenarios["reprocess_posted"] = _run_and_capture(
        "reprocess", AP_RESULT_POSTED, emit_reprocess_events=True, on_exception_fallback_status="NeedsReview",
    )
    scenarios["reprocess_ready"] = _run_and_capture(
        "reprocess", AP_RESULT_READY, emit_reprocess_events=True, on_exception_fallback_status="NeedsReview",
    )
    scenarios["reprocess_needs_review"] = _run_and_capture(
        "reprocess", AP_RESULT_NEEDS_REVIEW, emit_reprocess_events=True, on_exception_fallback_status="NeedsReview",
    )
    return scenarios


class TestDbMutationGoldenParity:
    """Captured DB mutation sequence is stable — golden-file snapshot."""

    def test_golden_file_exists_or_regenerate(self):
        if not GOLDEN_FILE.exists():
            GOLDEN_DIR.mkdir(parents=True, exist_ok=True)
            snapshot = _build_golden_snapshot()
            GOLDEN_FILE.write_text(json.dumps(snapshot, indent=2, sort_keys=True) + "\n")
        assert GOLDEN_FILE.exists()

    def test_all_scenarios_match_golden(self):
        golden = json.loads(GOLDEN_FILE.read_text())
        actual = _build_golden_snapshot()
        for scenario, expected_events in golden.items():
            assert scenario in actual, f"Missing scenario: {scenario}"
            assert actual[scenario] == expected_events, (
                f"Golden mismatch for scenario {scenario!r}:\n"
                f"expected={expected_events}\n"
                f"actual={actual[scenario]}"
            )

    def test_intake_scenarios_emit_no_workflow_events(self):
        actual = _build_golden_snapshot()
        for scenario_key in ("intake_posted", "intake_ready", "intake_needs_review"):
            we = [e for e in actual[scenario_key] if e["collection"] == "workflow_events"]
            assert we == [], (
                f"Intake-branch parity violation: {scenario_key} emitted "
                f"{len(we)} workflow_events (expected 0)"
            )

    def test_reprocess_scenarios_emit_exactly_two_workflow_events(self):
        actual = _build_golden_snapshot()
        for scenario_key in ("reprocess_posted", "reprocess_ready", "reprocess_needs_review"):
            we = [e for e in actual[scenario_key] if e["collection"] == "workflow_events"]
            assert len(we) == 2, (
                f"Reprocess-branch parity violation: {scenario_key} emitted "
                f"{len(we)} workflow_events (expected 2)"
            )
            event_types = [e["doc"]["event_type"] for e in we]
            assert event_types == ["system.reprocessed", "automation.decision.completed"]
            assert all(e["doc"]["source_service"] == "ap_auto_post_service" for e in we)

    def test_reprocess_decision_payload_matches_final_status(self):
        """The automation.decision.completed payload.decision must match final status."""
        actual = _build_golden_snapshot()
        for scenario_key, expected_status in (
            ("reprocess_posted", "Posted"),
            ("reprocess_ready", "ReadyForPost"),
            ("reprocess_needs_review", "NeedsReview"),
        ):
            decision_events = [
                e for e in actual[scenario_key]
                if e["collection"] == "workflow_events"
                and e["doc"]["event_type"] == "automation.decision.completed"
            ]
            assert len(decision_events) == 1
            assert decision_events[0]["doc"]["payload"]["decision"] == expected_status


# ---------------------------------------------------------------------------
# Class C — Source-inspection guardrail
# ---------------------------------------------------------------------------
class TestSourceInspectionGuardrail:
    """server.py uses finalize_ap_decision exactly where Step 3 declared."""

    @pytest.fixture(scope="class")
    def server_source(self) -> str:
        import server as server_module
        return inspect.getsource(server_module)

    def test_finalize_ap_decision_called_exactly_twice(self, server_source: str):
        # Step 3 landed 2 call sites in server.py: intake + reprocess.
        # Step 4b (2026-04-23) moved the intake body to
        # services/document_handlers.py, so 1 site is now in server.py
        # (the reprocess branch) and 1 site is in document_handlers.py
        # (the moved intake body). Total across both files must stay 2.
        server_count = server_source.count("await finalize_ap_decision(")
        from services import document_handlers
        dh_src = inspect.getsource(document_handlers)
        dh_count = dh_src.count("await finalize_ap_decision(")
        total = server_count + dh_count
        assert total == 2, (
            f"Expected exactly 2 finalize_ap_decision call sites total across "
            f"server.py + document_handlers.py (server={server_count}, "
            f"document_handlers={dh_count}, total={total}). Step 3/4b scope drifted."
        )
        assert server_count == 1, (
            f"Expected 1 call in server.py (reprocess branch), got {server_count}"
        )
        assert dh_count == 1, (
            f"Expected 1 call in document_handlers.py (moved intake body), got {dh_count}"
        )

    def test_server_no_longer_calls_attempt_ap_auto_post_in_branches(self, server_source: str):
        # Step 3 removed the 2 direct attempt_ap_auto_post call sites from
        # server.py's intake + reprocess branches. Step 4b moved the intake
        # body to document_handlers.py, so server.py now contains zero
        # attempt_ap_auto_post call sites. The moved intake body in
        # document_handlers.py routes through finalize_ap_decision, which
        # dispatches to attempt_ap_auto_post internally — that's preserved.
        call_count = server_source.count("attempt_ap_auto_post(")
        assert call_count == 0, (
            f"server.py still references attempt_ap_auto_post ({call_count}x) "
            "— Step 3/4b should have removed all such references."
        )

    def test_finalize_ap_decision_defined_once_in_service(self):
        from services import ap_auto_post_service
        src = inspect.getsource(ap_auto_post_service)
        assert src.count("async def finalize_ap_decision(") == 1

    def test_helper_still_calls_attempt_ap_auto_post(self):
        from services import ap_auto_post_service
        src = inspect.getsource(ap_auto_post_service.finalize_ap_decision)
        assert "attempt_ap_auto_post(" in src, (
            "finalize_ap_decision must still invoke attempt_ap_auto_post"
        )

    def test_helper_signature_matches_declaration(self):
        from services.ap_auto_post_service import finalize_ap_decision
        sig = inspect.signature(finalize_ap_decision)
        params = sig.parameters
        assert list(params.keys()) == [
            "doc_id", "db", "source", "emit_reprocess_events",
            "on_exception_fallback_status",
        ]
        assert params["source"].kind == inspect.Parameter.KEYWORD_ONLY
        assert params["emit_reprocess_events"].default is False
        assert params["on_exception_fallback_status"].default is None


# ---------------------------------------------------------------------------
# Class D — Live-surface smoke (skips gracefully if no backend)
# ---------------------------------------------------------------------------
class TestLiveSurfaceSmoke:
    """Minimal live-surface checks — skip cleanly if no backend."""

    BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "http://localhost:8001").rstrip("/")

    def _is_backend_reachable(self) -> bool:
        try:
            import requests
            resp = requests.get(f"{self.BASE_URL}/openapi.json", timeout=2)
            return resp.status_code == 200
        except Exception:
            return False

    def test_intake_route_registered(self):
        if not self._is_backend_reachable():
            pytest.skip("No backend reachable on localhost:8001")
        import requests
        resp = requests.get(f"{self.BASE_URL}/openapi.json")
        paths = resp.json().get("paths", {})
        assert "/api/documents/intake" in paths

    def test_reprocess_route_registered(self):
        if not self._is_backend_reachable():
            pytest.skip("No backend reachable on localhost:8001")
        import requests
        resp = requests.get(f"{self.BASE_URL}/openapi.json")
        paths = resp.json().get("paths", {})
        assert "/api/documents/{doc_id}/reprocess" in paths

    def test_openapi_path_count_unchanged(self):
        """Step 3 must not add or remove any HTTP routes."""
        if not self._is_backend_reachable():
            pytest.skip("No backend reachable on localhost:8001")
        import requests
        resp = requests.get(f"{self.BASE_URL}/openapi.json")
        total_paths = len(resp.json().get("paths", {}))
        # Baseline after Step 2B: 858 paths.
        assert total_paths == 858, (
            f"OpenAPI path count changed: {total_paths} (expected 858). "
            "Step 3 must not add or remove any HTTP routes."
        )
