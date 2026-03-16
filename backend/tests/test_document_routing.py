"""
Unit tests for the Autonomous Document Routing Service (Auto-Clear Gate).

Tests cover:
  - Score computation for each rule category
  - Status determination thresholds (auto_process / review / blocked)
  - Edge cases: empty docs, missing intelligence, zero confidence
  - The route_document async integration (mocked DB)
"""

import pytest
from unittest.mock import AsyncMock, patch, MagicMock
from datetime import datetime, timezone

from services.document_routing_service import (
    evaluate_routing,
    ROUTE_AUTO_PROCESS,
    ROUTE_REVIEW,
    ROUTE_BLOCKED,
    THRESHOLD_AUTO_PROCESS,
    THRESHOLD_REVIEW,
    _score_confidence,
    _score_required_fields,
    _score_validation,
    _score_duplicates,
    _score_entity_resolution,
    _score_optional_fields,
)


# ---------------------------------------------------------------------------
# Helpers to build test documents
# ---------------------------------------------------------------------------

def _make_doc(
    *,
    confidence=0.95,
    doc_type="AP_Invoice",
    vendor_canonical="Acme Corp",
    extracted_fields=None,
    validation_all_passed=True,
    is_duplicate=False,
    **extra,
):
    """Build a minimal hub_documents-style dict for testing."""
    doc = {
        "id": "DOC-TEST-001",
        "ai_confidence": confidence,
        "suggested_job_type": doc_type,
        "vendor_canonical": vendor_canonical,
        "extracted_fields": extracted_fields or {
            "vendor": "Acme Corp",
            "invoice_number": "INV-1234",
            "amount": "1500.00",
        },
        "validation_results": {
            "all_passed": validation_all_passed,
            "checks": [],
        },
        "possible_duplicate": is_duplicate,
    }
    doc.update(extra)
    return doc


def _make_intel(*, confidence=0.95, doc_type="AP_Invoice", extracted_fields=None):
    doc = {
        "document_id": "DOC-TEST-001",
        "classification_confidence": confidence,
        "document_type": doc_type,
        "extracted_fields": extracted_fields or {
            "vendor": "Acme Corp",
            "invoice_number": "INV-1234",
            "amount": "1500.00",
        },
    }
    return doc


# ===========================================================================
# 1. Individual scorer tests
# ===========================================================================

class TestScoreConfidence:
    def test_high_confidence(self):
        reasons = []
        assert _score_confidence(0.95, reasons) == 35
        assert reasons == []

    def test_moderate_confidence(self):
        reasons = []
        assert _score_confidence(0.85, reasons) == 25
        assert len(reasons) == 1
        assert "moderate_confidence" in reasons[0]

    def test_low_confidence(self):
        reasons = []
        assert _score_confidence(0.70, reasons) == 15
        assert "low_confidence" in reasons[0]

    def test_very_low_confidence(self):
        reasons = []
        assert _score_confidence(0.30, reasons) == 5
        assert "very_low_confidence" in reasons[0]


class TestScoreRequiredFields:
    def test_all_present(self):
        reasons = []
        extracted = {"vendor": "X", "invoice_number": "123", "amount": "99"}
        score = _score_required_fields("AP_Invoice", extracted, reasons)
        assert score == 30
        assert reasons == []

    def test_some_missing(self):
        reasons = []
        extracted = {"vendor": "X"}  # missing invoice_number, amount
        score = _score_required_fields("AP_Invoice", extracted, reasons)
        assert score == 10  # 1/3 * 30
        assert any("missing_required_invoice_number" in r for r in reasons)

    def test_all_missing(self):
        reasons = []
        score = _score_required_fields("AP_Invoice", {}, reasons)
        assert score == 0
        assert len(reasons) == 3

    def test_unknown_type_defaults(self):
        reasons = []
        score = _score_required_fields("Unknown", {"vendor": "X", "invoice_number": "1", "amount": "5"}, reasons)
        assert score == 30  # Falls back to AP_Invoice schema


class TestScoreValidation:
    def test_all_passed(self):
        reasons = []
        val = {"all_passed": True, "checks": []}
        assert _score_validation(val, reasons) == 15

    def test_failed_required(self):
        reasons = []
        val = {
            "all_passed": False,
            "checks": [{"check_name": "vendor_exists", "passed": False, "required": True}],
        }
        assert _score_validation(val, reasons) == 0
        assert "validation_failed_vendor_exists" in reasons[0]

    def test_no_validation(self):
        reasons = []
        assert _score_validation(None, reasons) == 5
        assert "no_validation_results" in reasons[0]


class TestScoreDuplicates:
    def test_no_duplicate(self):
        reasons = []
        assert _score_duplicates({"possible_duplicate": False}, reasons) == 0
        assert reasons == []

    def test_is_duplicate(self):
        reasons = []
        assert _score_duplicates({"possible_duplicate": True}, reasons) == -15
        assert "possible_duplicate" in reasons[0]


class TestScoreEntityResolution:
    def test_vendor_resolved(self):
        reasons = []
        assert _score_entity_resolution({"vendor_canonical": "X"}, None, reasons) == 5

    def test_both_resolved(self):
        reasons = []
        assert _score_entity_resolution({"vendor_canonical": "X", "customer_canonical": "Y"}, None, reasons) == 10

    def test_none_resolved(self):
        reasons = []
        assert _score_entity_resolution({}, None, reasons) == 0
        assert "no_entity_resolved" in reasons[0]


class TestScoreOptionalFields:
    def test_all_optional_present(self):
        reasons = []
        extracted = {"po_number": "PO-1", "due_date": "2026-01-01", "line_items": [{"item": "x"}]}
        score = _score_optional_fields("AP_Invoice", extracted, reasons)
        assert score == 10  # 3/3 optional filled

    def test_some_optional(self):
        reasons = []
        extracted = {"po_number": "PO-1"}
        score = _score_optional_fields("AP_Invoice", extracted, reasons)
        # 1/3 * 10 = 3 (int)
        assert score == 3


# ===========================================================================
# 2. Full evaluate_routing tests
# ===========================================================================

class TestEvaluateRouting:
    def test_high_quality_doc_auto_process(self):
        doc = _make_doc(confidence=0.95)
        result = evaluate_routing(doc)
        assert result["routing_status"] == ROUTE_AUTO_PROCESS
        assert result["routing_score"] >= THRESHOLD_AUTO_PROCESS
        assert "routing_timestamp" in result

    def test_moderate_quality_review(self):
        doc = _make_doc(confidence=0.75, extracted_fields={"vendor": "X"})
        result = evaluate_routing(doc)
        assert result["routing_status"] == ROUTE_REVIEW
        assert THRESHOLD_REVIEW <= result["routing_score"] < THRESHOLD_AUTO_PROCESS

    def test_low_quality_blocked(self):
        doc = _make_doc(
            confidence=0.30,
            extracted_fields={},
            validation_all_passed=False,
            vendor_canonical=None,
        )
        doc["validation_results"]["checks"] = [
            {"check_name": "vendor_exists", "passed": False, "required": True}
        ]
        result = evaluate_routing(doc)
        assert result["routing_status"] == ROUTE_BLOCKED
        assert result["routing_score"] < THRESHOLD_REVIEW

    def test_duplicate_penalty(self):
        doc = _make_doc(confidence=0.95, is_duplicate=True)
        result = evaluate_routing(doc)
        # Duplicate penalty of -15 should lower the score
        assert result["routing_score"] < 90  # Max without penalty would be ~90
        assert "possible_duplicate" in result["routing_reasons"]

    def test_intelligence_overrides_doc(self):
        doc = _make_doc(confidence=0.50)
        intel = _make_intel(confidence=0.98)
        result = evaluate_routing(doc, intelligence=intel)
        # Intelligence confidence should be used instead of doc's
        assert result["routing_score"] >= THRESHOLD_AUTO_PROCESS

    def test_reasons_list_populated(self):
        doc = _make_doc(confidence=0.70, extracted_fields={"vendor": "X"})
        result = evaluate_routing(doc)
        assert isinstance(result["routing_reasons"], list)
        assert len(result["routing_reasons"]) > 0

    def test_score_clamped_to_100(self):
        doc = _make_doc(confidence=0.99)
        doc["customer_canonical"] = "Big Customer"
        doc["extracted_fields"] = {
            "vendor": "X", "invoice_number": "1", "amount": "5",
            "po_number": "PO-1", "due_date": "2026-01-01", "line_items": [],
        }
        result = evaluate_routing(doc)
        assert result["routing_score"] <= 100

    def test_score_clamped_to_0(self):
        doc = _make_doc(
            confidence=0.10,
            extracted_fields={},
            validation_all_passed=False,
            vendor_canonical=None,
            is_duplicate=True,
        )
        doc["validation_results"]["checks"] = [
            {"check_name": "x", "passed": False, "required": True}
        ]
        result = evaluate_routing(doc)
        assert result["routing_score"] >= 0


# ===========================================================================
# 3. Async route_document integration test (mocked DB)
# ===========================================================================

class TestRouteDocument:
    @pytest.mark.asyncio
    async def test_route_document_persists(self):
        mock_doc = _make_doc(confidence=0.95)
        mock_intel = _make_intel(confidence=0.95)

        mock_hub = MagicMock()
        mock_hub.find_one = AsyncMock(return_value=mock_doc)
        mock_hub.update_one = AsyncMock()

        mock_intel_col = MagicMock()
        mock_intel_col.find_one = AsyncMock(return_value=mock_intel)

        mock_db = MagicMock()
        mock_db.hub_documents = mock_hub
        mock_db.document_intelligence_results = mock_intel_col

        with patch("deps.get_db", return_value=mock_db):
            from services.document_routing_service import route_document
            result = await route_document("DOC-TEST-001")

        assert result["routing_status"] in (ROUTE_AUTO_PROCESS, ROUTE_REVIEW, ROUTE_BLOCKED)
        mock_hub.update_one.assert_called_once()
        call_args = mock_hub.update_one.call_args
        assert call_args[0][0] == {"id": "DOC-TEST-001"}
        set_data = call_args[0][1]["$set"]
        assert "routing_status" in set_data
        assert "routing_score" in set_data
        assert "routing_reasons" in set_data
        assert "routing_timestamp" in set_data

    @pytest.mark.asyncio
    async def test_route_document_not_found(self):
        mock_hub = MagicMock()
        mock_hub.find_one = AsyncMock(return_value=None)

        mock_db = MagicMock()
        mock_db.hub_documents = mock_hub

        with patch("deps.get_db", return_value=mock_db):
            from services.document_routing_service import route_document
            with pytest.raises(ValueError, match="Document not found"):
                await route_document("NONEXISTENT")
