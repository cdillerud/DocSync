"""
GPI Document Hub - Pipeline Hardening & Observability Tests

Validates:
  1. Timing: started_at / finished_at / duration_ms populated on every stage
  2. Status semantics: ok / skipped / error used correctly
  3. Failure propagation: stage exceptions → status "error" + error message
  4. Skip behaviour: explicit skip_stages and dependency-based skips
  5. Trace persistence: pipeline runs stored in pipeline_runs collection
  6. Output safety: to_dict() returns bounded, sanitized payloads
  7. API endpoint: GET /api/document-intelligence/pipeline/runs/{doc_id}
"""

import pytest
import asyncio
import time
from unittest.mock import AsyncMock, patch, MagicMock

import sys
import os
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.pipeline.document_pipeline import (
    StageResult,
    PipelineResult,
    run_pipeline,
    get_pipeline_runs,
    _sanitize_output,
    STAGE_ORDER,
    PIPELINE_VERSION,
    PIPELINE_RUNS_COLLECTION,
)


# ---------------------------------------------------------------------------
# Unit tests: _sanitize_output
# ---------------------------------------------------------------------------

class TestSanitizeOutput:
    """Output safety — bounded serialisation."""

    def test_normal_dict_unchanged(self):
        raw = {"a": 1, "b": "hello", "c": [1, 2]}
        result = _sanitize_output(raw)
        assert result == raw

    def test_long_string_truncated(self):
        raw = {"big": "x" * 1000}
        result = _sanitize_output(raw)
        assert len(result["big"]) <= 501  # 500 + ellipsis char

    def test_long_list_capped(self):
        raw = {"items": list(range(100))}
        result = _sanitize_output(raw)
        assert len(result["items"]) == 25
        assert result["_items_truncated"] == 75

    def test_too_many_keys_truncated(self):
        raw = {f"k{i}": i for i in range(50)}
        result = _sanitize_output(raw)
        assert "_truncated_keys" in result
        assert len([k for k in result if not k.startswith("_truncated")]) <= 25

    def test_empty_dict(self):
        assert _sanitize_output({}) == {}


# ---------------------------------------------------------------------------
# Unit tests: StageResult.to_dict()
# ---------------------------------------------------------------------------

class TestStageResultToDict:
    """StageResult serialisation contract."""

    def test_ok_stage_fields(self):
        sr = StageResult(
            stage="classification", status="ok",
            started_at="2026-03-15T10:00:00Z",
            finished_at="2026-03-15T10:00:01Z",
            duration_ms=1042.3,
            output={"document_type": "AP_INVOICE", "confidence": 0.95},
        )
        d = sr.to_dict()
        assert d["stage"] == "classification"
        assert d["status"] == "ok"
        assert d["started_at"] == "2026-03-15T10:00:00Z"
        assert d["finished_at"] == "2026-03-15T10:00:01Z"
        assert d["duration_ms"] == 1042.3
        assert d["output"]["document_type"] == "AP_INVOICE"
        assert "error" not in d

    def test_error_stage_includes_error(self):
        sr = StageResult(
            stage="layout", status="error",
            started_at="t0", finished_at="t1", duration_ms=5.0,
            error="document not found",
        )
        d = sr.to_dict()
        assert d["status"] == "error"
        assert d["error"] == "document not found"

    def test_skipped_stage_no_error(self):
        sr = StageResult(
            stage="extraction", status="skipped",
            output={"reason": "no extracted fields from classification"},
        )
        d = sr.to_dict()
        assert d["status"] == "skipped"
        assert "error" not in d

    def test_long_error_truncated(self):
        sr = StageResult(stage="x", status="error", error="E" * 2000)
        d = sr.to_dict()
        assert len(d["error"]) <= 500

    def test_output_sanitized(self):
        sr = StageResult(stage="x", status="ok", output={"big": "z" * 1000})
        d = sr.to_dict()
        assert len(d["output"]["big"]) <= 501


# ---------------------------------------------------------------------------
# Unit tests: PipelineResult.to_dict()
# ---------------------------------------------------------------------------

class TestPipelineResultToDict:
    """PipelineResult serialisation contract."""

    def test_empty_pipeline(self):
        pr = PipelineResult(
            run_id="RUN-ABC", document_id="DOC-1",
            started_at="t0", finished_at="t1",
            total_duration_ms=100.0, status="ok",
        )
        d = pr.to_dict()
        assert d["run_id"] == "RUN-ABC"
        assert d["document_id"] == "DOC-1"
        assert d["pipeline_version"] == PIPELINE_VERSION
        assert d["total_duration_ms"] == 100.0
        assert d["stages"] == []
        assert d["stages_run"] == 0
        assert d["stages_skipped"] == 0
        assert d["stages_errored"] == 0

    def test_stages_serialised(self):
        pr = PipelineResult(run_id="R1", document_id="D1", status="ok")
        pr.stages.append(StageResult(stage="classification", status="ok"))
        pr.stages.append(StageResult(stage="extraction", status="skipped"))
        d = pr.to_dict()
        assert len(d["stages"]) == 2
        assert d["stages"][0]["stage"] == "classification"
        assert d["stages"][1]["status"] == "skipped"


# ---------------------------------------------------------------------------
# Integration tests: run_pipeline (mocked service calls)
# ---------------------------------------------------------------------------

def _make_mock_db(doc=None):
    """Create a mock DB that returns `doc` from hub_documents.find_one."""
    mock_db = MagicMock()
    find_one_coro = AsyncMock(return_value=doc)
    mock_db.hub_documents.find_one = find_one_coro

    # pipeline_runs collection
    mock_db.__getitem__ = MagicMock(return_value=MagicMock())
    mock_db[PIPELINE_RUNS_COLLECTION].insert_one = AsyncMock()

    return mock_db


@pytest.fixture
def mock_all_services():
    """Patch every stage's service call so run_pipeline can execute end-to-end."""
    doc = {"id": "DOC-TEST", "doc_type": "AP_INVOICE", "extracted_fields": {"vendor_name": "Acme"}}

    patches = [
        patch("services.document_intelligence_service.process_document",
              new=AsyncMock(return_value={"document_type": "AP_INVOICE", "confidence": 0.9,
                                          "extracted_fields": {"vendor_name": "Acme"},
                                          "automation_readiness": {"status": "ready"}})),
        patch("services.entity_resolution_service.resolve_entities",
              new=AsyncMock(return_value={"summary": {"total": 2, "resolved": 1, "confidence_avg": 0.8},
                                          "resolutions": [{"status": "resolved", "confidence": 0.85,
                                                           "entity_kind": "vendor", "resolved_id": "V001"}]})),
        patch("services.transaction_matching_service.match_transactions",
              new=AsyncMock(return_value={"overall_status": "matched", "candidates_count": 1,
                                          "best_match": {"confidence": 0.92}})),
        patch("services.document_bundle_service.detect_bundles",
              new=AsyncMock(return_value={"bundles_created": 0, "bundles_updated": 1, "documents_grouped": 1})),
        patch("services.document_lifecycle_service.validate_lifecycle",
              new=AsyncMock(return_value={"completeness_pct": 75, "issues_count": 1})),
        patch("services.decision_policy_service.evaluate_decision",
              new=AsyncMock(return_value={"action": "hold_for_review",
                                          "matched_policy": {"name": "default"},
                                          "confidence": 0.7})),
        patch("services.learning_loop_service.update_automation_metrics",
              new=AsyncMock(return_value={"updated": True})),
        patch("deps.get_db", return_value=_make_mock_db(doc)),
    ]

    for p in patches:
        p.start()
    yield
    for p in patches:
        p.stop()


class TestPipelineTimingInstrumentation:
    """Every executed stage must have started_at, finished_at, and duration_ms > 0."""

    @pytest.mark.asyncio
    async def test_all_stages_have_timestamps(self, mock_all_services):
        result = await run_pipeline("DOC-TEST", persist=False)

        for sr in result.stages:
            d = sr.to_dict()
            assert d["started_at"], f"stage {d['stage']} missing started_at"
            assert d["finished_at"], f"stage {d['stage']} missing finished_at"
            assert d["duration_ms"] >= 0, f"stage {d['stage']} negative duration"

    @pytest.mark.asyncio
    async def test_pipeline_total_duration(self, mock_all_services):
        result = await run_pipeline("DOC-TEST", persist=False)
        assert result.total_duration_ms > 0
        assert result.started_at
        assert result.finished_at

    @pytest.mark.asyncio
    async def test_run_id_generated(self, mock_all_services):
        result = await run_pipeline("DOC-TEST", persist=False)
        assert result.run_id.startswith("RUN-")
        assert len(result.run_id) == 16  # "RUN-" + 12 hex chars


class TestPipelineStatusSemantics:
    """Status must be ok / skipped / error — nothing else."""

    VALID_STAGE_STATUSES = {"ok", "skipped", "error"}
    VALID_PIPELINE_STATUSES = {"ok", "partial", "error", "pending"}

    @pytest.mark.asyncio
    async def test_all_stage_statuses_valid(self, mock_all_services):
        result = await run_pipeline("DOC-TEST", persist=False)
        for sr in result.stages:
            assert sr.status in self.VALID_STAGE_STATUSES, \
                f"stage {sr.stage} has invalid status '{sr.status}'"

    @pytest.mark.asyncio
    async def test_pipeline_status_ok_when_all_ok_or_skipped(self, mock_all_services):
        result = await run_pipeline("DOC-TEST", persist=False)
        assert result.status in ("ok", "partial")

    @pytest.mark.asyncio
    async def test_stage_counts_sum(self, mock_all_services):
        result = await run_pipeline("DOC-TEST", persist=False)
        total = result.stages_run + result.stages_skipped + result.stages_errored
        assert total == len(result.stages)


class TestPipelineFailurePropagation:
    """Stage exceptions → status 'error' + error message preserved."""

    @pytest.mark.asyncio
    async def test_exception_in_stage_becomes_error(self):
        with patch("services.document_intelligence_service.process_document",
                   new=AsyncMock(side_effect=RuntimeError("AI service down"))), \
             patch("deps.get_db", return_value=_make_mock_db({"id": "X", "extracted_fields": {}})):
            result = await run_pipeline("X", stop_after="classification", persist=False)

        assert result.stages_errored >= 1
        err_stage = result.stages[0]
        assert err_stage.status == "error"
        assert "AI service down" in err_stage.error
        assert result.status == "partial"

    @pytest.mark.asyncio
    async def test_error_does_not_abort_later_stages(self, mock_all_services):
        """An error in classification should not prevent entity_resolution from running."""
        with patch("services.document_intelligence_service.process_document",
                   new=AsyncMock(side_effect=RuntimeError("boom"))):
            result = await run_pipeline("DOC-TEST", persist=False)

        stage_names = [s.stage for s in result.stages]
        assert "entity_resolution" in stage_names
        assert result.stages_errored >= 1
        assert result.stages_run >= 1


class TestPipelineSkipBehaviour:
    """Explicit skip_stages and dependency-based skips."""

    @pytest.mark.asyncio
    async def test_explicit_skip(self, mock_all_services):
        result = await run_pipeline(
            "DOC-TEST", skip_stages=["bundle_detection", "learning_capture"], persist=False,
        )
        skipped_names = [s.stage for s in result.stages if s.status == "skipped"]
        assert "bundle_detection" in skipped_names
        assert "learning_capture" in skipped_names
        # Explicitly skipped stages have reason
        for s in result.stages:
            if s.stage in ("bundle_detection", "learning_capture"):
                assert s.output.get("reason") == "explicitly skipped"

    @pytest.mark.asyncio
    async def test_stop_after(self, mock_all_services):
        result = await run_pipeline("DOC-TEST", stop_after="extraction", persist=False)
        stage_names = [s.stage for s in result.stages]
        assert "classification" in stage_names
        assert "extraction" in stage_names
        assert "entity_resolution" not in stage_names

    @pytest.mark.asyncio
    async def test_dependency_skip_extraction_no_fields(self):
        """Extraction skips when classification returns no extracted_fields."""
        with patch("services.document_intelligence_service.process_document",
                   new=AsyncMock(return_value={"document_type": "OTHER", "confidence": 0.5,
                                                "extracted_fields": {},
                                                "automation_readiness": {"status": "not_ready"}})), \
             patch("deps.get_db", return_value=_make_mock_db({"id": "X", "extracted_fields": {}})):
            result = await run_pipeline("X", stop_after="extraction", persist=False)

        extraction = [s for s in result.stages if s.stage == "extraction"][0]
        assert extraction.status == "skipped"
        assert "no extracted fields" in extraction.output.get("reason", "")


class TestPipelineTracePersistence:
    """Verify that run traces are written to the pipeline_runs collection."""

    @pytest.mark.asyncio
    async def test_persist_called_by_default(self, mock_all_services):
        mock_db = _make_mock_db({"id": "DOC-TEST", "extracted_fields": {"vendor_name": "Acme"}})
        with patch("deps.get_db", return_value=mock_db):
            result = await run_pipeline("DOC-TEST", persist=True)

        # insert_one should have been called on the pipeline_runs collection
        mock_db[PIPELINE_RUNS_COLLECTION].insert_one.assert_called_once()
        inserted = mock_db[PIPELINE_RUNS_COLLECTION].insert_one.call_args[0][0]
        assert inserted["run_id"] == result.run_id
        assert inserted["document_id"] == "DOC-TEST"
        assert "_persisted_at" in inserted

    @pytest.mark.asyncio
    async def test_persist_false_skips_write(self, mock_all_services):
        mock_db = _make_mock_db({"id": "DOC-TEST", "extracted_fields": {"vendor_name": "Acme"}})
        with patch("deps.get_db", return_value=mock_db):
            await run_pipeline("DOC-TEST", persist=False)

        mock_db[PIPELINE_RUNS_COLLECTION].insert_one.assert_not_called()

    @pytest.mark.asyncio
    async def test_persisted_payload_bounded(self, mock_all_services):
        """Persisted trace must not contain unbounded data."""
        mock_db = _make_mock_db({"id": "DOC-TEST", "extracted_fields": {"vendor_name": "Acme"}})
        with patch("deps.get_db", return_value=mock_db):
            await run_pipeline("DOC-TEST", persist=True)

        inserted = mock_db[PIPELINE_RUNS_COLLECTION].insert_one.call_args[0][0]
        import json
        payload_str = json.dumps(inserted, default=str)
        # Persisted payload should be well under 100KB for a normal run
        assert len(payload_str) < 100_000, f"Payload too large: {len(payload_str)} bytes"


# ---------------------------------------------------------------------------
# API endpoint tests (requires running server)
# ---------------------------------------------------------------------------

import requests

API_BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestPipelineRunsEndpoint:
    """GET /api/document-intelligence/pipeline/runs/{doc_id}"""

    def test_returns_200_for_any_doc(self):
        """Endpoint returns 200 even for a doc with no runs."""
        resp = requests.get(f"{API_BASE}/api/document-intelligence/pipeline/runs/NONEXISTENT")
        assert resp.status_code == 200
        data = resp.json()
        assert data["document_id"] == "NONEXISTENT"
        assert data["runs"] == []
        assert data["count"] == 0

    def test_limit_parameter(self):
        resp = requests.get(
            f"{API_BASE}/api/document-intelligence/pipeline/runs/NONEXISTENT",
            params={"limit": 5},
        )
        assert resp.status_code == 200

    def test_limit_validation_rejects_zero(self):
        resp = requests.get(
            f"{API_BASE}/api/document-intelligence/pipeline/runs/NONEXISTENT",
            params={"limit": 0},
        )
        assert resp.status_code == 422

    def test_limit_validation_rejects_over_100(self):
        resp = requests.get(
            f"{API_BASE}/api/document-intelligence/pipeline/runs/NONEXISTENT",
            params={"limit": 200},
        )
        assert resp.status_code == 422


class TestPipelineStagesEndpoint:
    """GET /api/document-intelligence/pipeline/stages — regression."""

    def test_returns_stage_list(self):
        resp = requests.get(f"{API_BASE}/api/document-intelligence/pipeline/stages")
        assert resp.status_code == 200
        data = resp.json()
        assert "stages" in data
        assert data["stages"] == [
            "classification", "extraction", "layout",
            "entity_resolution", "transaction_match",
            "bundle_detection", "lifecycle_check",
            "policy_decision", "learning_capture",
        ]
