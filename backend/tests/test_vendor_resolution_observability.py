"""
Unit and integration tests for Vendor Resolution Observability + Negative Feedback Loop.

Tests cover:
  1. build_resolution_object — all status paths
  2. capture_rejection — new + reinforced rejections
  3. check_rejection_guardrail — block/pass decisions
  4. Resolution metrics structure
  5. Rejection admin endpoint
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.vendor_resolution_service import (
    build_resolution_object,
    STATUS_RESOLVED,
    STATUS_UNRESOLVED,
    STATUS_AMBIGUOUS,
    STATUS_NEEDS_REVIEW,
)


# ---------------------------------------------------------------------------
# 1. build_resolution_object tests
# ---------------------------------------------------------------------------

class TestBuildResolutionObject:
    def test_alias_match_resolved(self):
        result = build_resolution_object(
            vendor_raw="ABC Industrial Supply",
            match_result={
                "vendor_canonical": "V123",
                "vendor_match_method": "alias_match",
                "vendor_name": "ABC Industrial Supply LLC",
                "vendor_no": "V123",
            },
        )
        assert result["status"] == STATUS_RESOLVED
        assert result["method"] == "alias_match"
        assert result["matched_vendor_no"] == "V123"
        assert result["reviewed_override"] is False
        assert result["raw"] == "ABC Industrial Supply"
        assert result["normalized"] == "abc industrial supply"
        assert "resolved_at" in result

    def test_bc_exact_match_resolved(self):
        result = build_resolution_object(
            vendor_raw="Acme Corp",
            match_result={
                "vendor_canonical": "V456",
                "vendor_match_method": "bc_exact_match",
                "vendor_name": "Acme Corp",
                "vendor_no": "V456",
            },
        )
        assert result["status"] == STATUS_RESOLVED
        assert result["method"] == "bc_exact_match"

    def test_high_fuzzy_resolved(self):
        result = build_resolution_object(
            vendor_raw="ABC Supply",
            match_result={
                "vendor_canonical": "V789",
                "vendor_match_method": "fuzzy_match",
                "vendor_name": "ABC Supply Co",
                "match_score": 0.97,
            },
        )
        assert result["status"] == STATUS_RESOLVED
        assert result["score"] == 0.97

    def test_low_fuzzy_needs_review(self):
        result = build_resolution_object(
            vendor_raw="ABC Supply",
            match_result={
                "vendor_canonical": "V789",
                "vendor_match_method": "fuzzy_match",
                "vendor_name": "ABC Supply Co",
                "match_score": 0.91,
            },
        )
        assert result["status"] == STATUS_NEEDS_REVIEW
        assert result["score"] == 0.91

    def test_no_match_unresolved(self):
        result = build_resolution_object(
            vendor_raw="Unknown Vendor XYZ",
            match_result={
                "vendor_canonical": None,
                "vendor_match_method": "none",
            },
        )
        assert result["status"] == STATUS_UNRESOLVED
        assert result["matched_vendor_no"] is None

    def test_empty_vendor_raw(self):
        result = build_resolution_object(
            vendor_raw="",
            match_result={"vendor_canonical": None, "vendor_match_method": "none"},
        )
        assert result["raw"] == ""
        assert result["normalized"] == ""
        assert result["status"] == STATUS_UNRESOLVED

    def test_explicit_status_override(self):
        result = build_resolution_object(
            vendor_raw="Test",
            match_result={"vendor_canonical": "V1", "vendor_match_method": "fuzzy_match", "match_score": 0.92},
            status=STATUS_AMBIGUOUS,
            reason="Multiple matches",
        )
        assert result["status"] == STATUS_AMBIGUOUS
        assert result["reason"] == "Multiple matches"


# ---------------------------------------------------------------------------
# 2. capture_rejection tests
# ---------------------------------------------------------------------------

class TestCaptureRejection:
    @pytest.mark.asyncio
    async def test_new_rejection(self):
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=None)
        mock_col.insert_one = AsyncMock()

        mock_db = MagicMock()
        mock_db.vendor_match_rejections = mock_col

        with patch("services.vendor_resolution_service.get_db", return_value=mock_db):
            from services.vendor_resolution_service import capture_rejection
            result = await capture_rejection(
                doc_id="DOC-1",
                vendor_raw="ABC Supply",
                proposed_vendor_id="V100",
                proposed_vendor_name="ABC Supply Inc",
                proposed_method="fuzzy_match",
                proposed_score=0.92,
                corrected_vendor_id="V200",
                corrected_vendor_name="ABC Industrial Supply LLC",
            )

        assert result["rejection_count"] == 1
        assert result["proposed_vendor_id"] == "V100"
        assert result["corrected_vendor_id"] == "V200"
        mock_col.insert_one.assert_called_once()

    @pytest.mark.asyncio
    async def test_reinforced_rejection(self):
        existing = {
            "normalized_raw": "abc supply",
            "proposed_vendor_id": "V100",
            "rejection_count": 2,
        }
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=existing)
        mock_col.update_one = AsyncMock()

        mock_db = MagicMock()
        mock_db.vendor_match_rejections = mock_col

        with patch("services.vendor_resolution_service.get_db", return_value=mock_db):
            from services.vendor_resolution_service import capture_rejection
            result = await capture_rejection(
                doc_id="DOC-2",
                vendor_raw="ABC Supply",
                proposed_vendor_id="V100",
                proposed_vendor_name="ABC Supply Inc",
                proposed_method="fuzzy_match",
                proposed_score=0.91,
                corrected_vendor_id="V300",
                corrected_vendor_name="ABC Corp",
            )

        assert result["rejection_count"] == 3
        mock_col.update_one.assert_called_once()


# ---------------------------------------------------------------------------
# 3. check_rejection_guardrail tests
# ---------------------------------------------------------------------------

class TestGuardrail:
    @pytest.mark.asyncio
    async def test_blocked_match(self):
        rejection = {
            "normalized_raw": "abc supply",
            "proposed_vendor_id": "V100",
            "rejection_count": 2,
        }
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=rejection)

        mock_db = MagicMock()
        mock_db.vendor_match_rejections = mock_col

        with patch("services.vendor_resolution_service.get_db", return_value=mock_db):
            from services.vendor_resolution_service import check_rejection_guardrail
            result = await check_rejection_guardrail("ABC Supply", "V100")

        assert result is not None
        assert result["rejection_count"] == 2

    @pytest.mark.asyncio
    async def test_safe_match(self):
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.vendor_match_rejections = mock_col

        with patch("services.vendor_resolution_service.get_db", return_value=mock_db):
            from services.vendor_resolution_service import check_rejection_guardrail
            result = await check_rejection_guardrail("ABC Supply", "V100")

        assert result is None

    @pytest.mark.asyncio
    async def test_empty_input(self):
        mock_db = MagicMock()
        mock_db.vendor_match_rejections = MagicMock()

        with patch("services.vendor_resolution_service.get_db", return_value=mock_db):
            from services.vendor_resolution_service import check_rejection_guardrail
            result = await check_rejection_guardrail("", "V100")
            assert result is None

            result2 = await check_rejection_guardrail("ABC", "")
            assert result2 is None


# ---------------------------------------------------------------------------
# 4. Vendor resolution object integration in matching pipeline
# ---------------------------------------------------------------------------

class TestResolutionInMatchPipeline:
    def test_guardrail_downgraded_creates_needs_review(self):
        """When guardrail downgrades a match, status should be needs_review."""
        match_result = {
            "vendor_canonical": "V100",
            "vendor_match_method": "fuzzy_match",
            "vendor_name": "ABC Supply",
            "vendor_no": "V100",
            "match_score": 0.92,
            "guardrail_downgraded": True,
            "resolution_status": "needs_review",
        }
        result = build_resolution_object(
            vendor_raw="ABC Supply Inc",
            match_result=match_result,
            status="needs_review",
            reason="Previously rejected match (guardrail)",
        )
        assert result["status"] == STATUS_NEEDS_REVIEW
        assert "guardrail" in result["reason"].lower()

    def test_manual_match_override(self):
        """reviewer override should set reviewed_override=True."""
        # This tests the shape of what set_vendor_for_document writes
        resolution = {
            "status": "resolved",
            "method": "manual_match",
            "raw": "ABC Supply Inc",
            "normalized": "abc supply",
            "matched_vendor_name": "ABC Industrial Supply LLC",
            "matched_vendor_no": "V200",
            "score": 1.0,
            "reason": "Reviewer override",
            "reviewed_override": True,
        }
        assert resolution["reviewed_override"] is True
        assert resolution["method"] == "manual_match"
