"""
Unit tests for the Document Readiness Engine.

Tests cover:
  1. Signal computation from document fields
  2. Readiness evaluation — all status paths
  3. Confidence computation
  4. Edge cases (empty docs, missing fields)
  5. Async evaluate_and_persist (mocked DB)
"""

import pytest
from unittest.mock import AsyncMock, MagicMock, patch

from services.document_readiness_service import (
    compute_signals,
    evaluate_readiness,
    STATUS_READY_AUTO_DRAFT,
    STATUS_READY_AUTO_LINK,
    STATUS_NEEDS_REVIEW,
    STATUS_BLOCKED,
    STATUS_AMBIGUOUS,
    ACTION_AUTO_DRAFT,
    ACTION_AUTO_LINK,
    ACTION_REVIEW,
    ACTION_HOLD,
)


# ---------------------------------------------------------------------------
# Helpers
# ---------------------------------------------------------------------------

def _make_doc(**overrides):
    """Build a minimal document dict for testing."""
    doc = {
        "id": "DOC-TEST-001",
        "ai_confidence": 0.95,
        "suggested_job_type": "AP_Invoice",
        "extracted_fields": {
            "vendor": "Acme Corp",
            "invoice_number": "INV-1234",
            "amount": "1500.00",
            "po_number": "PO-5678",
            "line_items": [{"description": "Widget", "amount": "750.00"}],
        },
        "vendor_canonical": "V100",
        "vendor_match_method": "alias_match",
        "vendor_resolution": {"status": "resolved", "method": "alias_match"},
        "possible_duplicate": False,
        "automation_decision": "auto",
        "validation_results": {"all_passed": True},
        "draft_candidate": True,
    }
    doc.update(overrides)
    return doc


# ---------------------------------------------------------------------------
# 1. Signal computation tests
# ---------------------------------------------------------------------------

class TestComputeSignals:
    def test_fully_resolved(self):
        doc = _make_doc()
        signals = compute_signals(doc)
        assert signals["vendor_resolved"] is True
        assert signals["required_fields_complete"] is True
        assert signals["duplicate_risk"] is False
        assert signals["policy_blocked"] is False
        assert signals["policy_held"] is False

    def test_vendor_unresolved(self):
        doc = _make_doc(vendor_canonical=None, vendor_match_method=None, vendor_resolution={})
        signals = compute_signals(doc)
        assert signals["vendor_resolved"] is False

    def test_duplicate_risk(self):
        doc = _make_doc(possible_duplicate=True)
        signals = compute_signals(doc)
        assert signals["duplicate_risk"] is True

    def test_policy_blocked(self):
        doc = _make_doc(automation_decision="blocked")
        signals = compute_signals(doc)
        assert signals["policy_blocked"] is True

    def test_policy_held(self):
        doc = _make_doc(automation_decision="hold")
        signals = compute_signals(doc)
        assert signals["policy_held"] is True

    def test_graph_linked(self):
        doc = _make_doc(bc_document_id="BC-123")
        signals = compute_signals(doc)
        assert signals["graph_linked"] is True

    def test_line_items(self):
        doc = _make_doc(extracted_fields={
            "vendor": "X", "invoice_number": "1", "amount": "100",
            "line_items": [{"description": "Widget", "amount": "50"}],
        })
        signals = compute_signals(doc)
        assert signals["line_items_present"] is True
        assert signals["line_items_confident"] is True

    def test_no_line_items(self):
        doc = _make_doc(extracted_fields={
            "vendor": "X", "invoice_number": "1", "amount": "100",
        })
        signals = compute_signals(doc)
        assert signals["line_items_present"] is False
        assert signals["line_items_confident"] is False

    def test_po_resolved(self):
        doc = _make_doc(extracted_fields={
            "vendor": "X", "invoice_number": "1", "amount": "100",
            "po_number": "PO-5678",
        })
        signals = compute_signals(doc)
        assert signals["po_resolved"] is True

    def test_missing_required_fields(self):
        doc = _make_doc(extracted_fields={"vendor": "X"})
        signals = compute_signals(doc)
        assert signals["required_fields_complete"] is False

    def test_manually_overridden(self):
        doc = _make_doc(
            vendor_resolution={"status": "resolved", "reviewed_override": True},
            approved_by="admin",
        )
        signals = compute_signals(doc)
        assert signals["manually_overridden"] is True


# ---------------------------------------------------------------------------
# 2. Readiness evaluation tests
# ---------------------------------------------------------------------------

class TestEvaluateReadiness:
    def test_ready_auto_draft(self):
        """Fully resolved doc → ready_auto_draft."""
        doc = _make_doc()
        r = evaluate_readiness(doc)
        assert r["status"] == STATUS_READY_AUTO_DRAFT
        assert r["recommended_action"] == ACTION_AUTO_DRAFT
        assert r["confidence"] > 0.7
        assert len(r["blocking_reasons"]) == 0
        assert "last_evaluated_at" in r

    def test_blocked_duplicate(self):
        """Duplicate risk → blocked."""
        doc = _make_doc(possible_duplicate=True)
        r = evaluate_readiness(doc)
        assert r["status"] == STATUS_BLOCKED
        assert r["recommended_action"] == ACTION_HOLD
        assert "duplicate_risk" in r["blocking_reasons"]

    def test_blocked_policy(self):
        """Policy blocked → blocked."""
        doc = _make_doc(automation_decision="blocked")
        r = evaluate_readiness(doc)
        assert r["status"] == STATUS_BLOCKED
        assert "policy_engine_blocked" in r["blocking_reasons"]

    def test_blocked_missing_fields(self):
        """Missing required fields → blocked."""
        doc = _make_doc(extracted_fields={}, vendor_canonical=None, vendor_match_method=None, vendor_resolution={})
        r = evaluate_readiness(doc)
        assert r["status"] == STATUS_BLOCKED
        assert "missing_required_fields" in r["blocking_reasons"]
        assert "vendor_unresolved" in r["blocking_reasons"]

    def test_needs_review_low_vendor_confidence(self):
        """Vendor needs review → needs_review."""
        doc = _make_doc(
            vendor_resolution={"status": "needs_review", "method": "fuzzy_match"},
            ai_confidence=0.70,
        )
        r = evaluate_readiness(doc)
        assert r["status"] in (STATUS_NEEDS_REVIEW, STATUS_AMBIGUOUS)
        assert "vendor_needs_review" in r["warning_reasons"]

    def test_ready_auto_link(self):
        """Graph-linked doc → ready_auto_link."""
        doc = _make_doc(bc_document_id="BC-XYZ")
        r = evaluate_readiness(doc)
        assert r["status"] == STATUS_READY_AUTO_LINK
        assert r["recommended_action"] == ACTION_AUTO_LINK

    def test_ambiguous_many_warnings(self):
        """Multiple warnings → ambiguous."""
        doc = _make_doc(
            vendor_resolution={"status": "needs_review"},
            automation_decision="hold",
            extracted_fields={"vendor": "X", "invoice_number": "1", "amount": "5"},
        )
        r = evaluate_readiness(doc)
        # With policy_hold + vendor_needs_review + po_missing + no_line_items = 4 warnings
        assert r["status"] in (STATUS_AMBIGUOUS, STATUS_NEEDS_REVIEW)

    def test_confidence_bounds(self):
        """Confidence always 0.0-1.0."""
        doc = _make_doc(ai_confidence=0.99)
        r = evaluate_readiness(doc)
        assert 0.0 <= r["confidence"] <= 1.0

        doc2 = _make_doc(
            ai_confidence=0.1,
            possible_duplicate=True,
            automation_decision="blocked",
            vendor_canonical=None,
            vendor_resolution={},
        )
        r2 = evaluate_readiness(doc2)
        assert 0.0 <= r2["confidence"] <= 1.0

    def test_signals_included(self):
        """Signals dict is always present."""
        doc = _make_doc()
        r = evaluate_readiness(doc)
        assert "signals" in r
        assert "vendor_resolved" in r["signals"]
        assert len(r["signals"]) == 11

    def test_empty_doc(self):
        """Empty doc doesn't crash."""
        r = evaluate_readiness({})
        assert r["status"] in (STATUS_BLOCKED, STATUS_NEEDS_REVIEW)
        assert r["confidence"] >= 0.0

    def test_reviewed_override(self):
        """Manually overridden doc."""
        doc = _make_doc(
            vendor_resolution={"status": "resolved", "reviewed_override": True},
            approved_by="admin",
        )
        r = evaluate_readiness(doc)
        assert r["reviewed_override"] is True


# ---------------------------------------------------------------------------
# 3. Async evaluate_and_persist (mocked DB)
# ---------------------------------------------------------------------------

class TestEvaluateAndPersist:
    @pytest.mark.asyncio
    async def test_persist(self):
        mock_doc = _make_doc()
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=mock_doc)
        mock_col.update_one = AsyncMock()

        mock_db = MagicMock()
        mock_db.hub_documents = mock_col

        with patch("deps.get_db", return_value=mock_db):
            from services.document_readiness_service import evaluate_and_persist
            result = await evaluate_and_persist("DOC-TEST-001")

        assert result["status"] in (STATUS_READY_AUTO_DRAFT, STATUS_READY_AUTO_LINK, STATUS_NEEDS_REVIEW, STATUS_BLOCKED, STATUS_AMBIGUOUS)
        mock_col.update_one.assert_called_once()
        call_args = mock_col.update_one.call_args
        set_data = call_args[0][1]["$set"]
        assert "readiness" in set_data

    @pytest.mark.asyncio
    async def test_not_found(self):
        mock_col = MagicMock()
        mock_col.find_one = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.hub_documents = mock_col

        with patch("deps.get_db", return_value=mock_db):
            from services.document_readiness_service import evaluate_and_persist
            with pytest.raises(ValueError, match="Document not found"):
                await evaluate_and_persist("NONEXISTENT")
