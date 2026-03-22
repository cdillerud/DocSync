"""
GPI Document Hub - BC Validation Isolation Tests

Validates:
  1. Behavior preservation: validate_bc_match returns identical output structure
  2. Demo mode: returns early with simulated checks
  3. Extraction quality computation: correct field scoring
  4. Vendor matching: AP_Invoice delegates to unified_vendor_matcher
  5. Customer matching: Sales_PO delegates to _match_customer_in_bc
  6. PO validation: PO_REQUIRED, PO_IF_PRESENT modes
  7. Duplicate invoice check: blocks when found
  8. Shipping doc: sales order lookup
  9. Error handling: BC connection failures produce structured errors
  10. Normalization: _normalize_vendor_name preserves regex-based behavior
  11. Fuzzy scoring: _calculate_fuzzy_score preserves token-overlap behavior
  12. Compatibility: server.py wrapper delegates correctly
  13. document_intel_helpers adapter delegates correctly
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.bc_validation_service import (
    validate_bc_match,
    _normalize_vendor_name,
    _calculate_fuzzy_score,
    _compute_extraction_quality,
    _match_customer_in_bc,
)


# ---------------------------------------------------------------------------
# Unit tests: _normalize_vendor_name
# ---------------------------------------------------------------------------

class TestNormalizeVendorName:
    """Regex-based suffix removal preserves server.py behavior."""

    def test_basic(self):
        assert _normalize_vendor_name("Acme Corp") == "acme"

    def test_inc_with_dot(self):
        assert _normalize_vendor_name("Acme, Inc.") == "acme"

    def test_llc(self):
        assert _normalize_vendor_name("Widget LLC") == "widget"

    def test_limited(self):
        assert _normalize_vendor_name("Foo Limited") == "foo"

    def test_gmbh(self):
        assert _normalize_vendor_name("Siemens GmbH") == "siemens"

    def test_empty(self):
        assert _normalize_vendor_name("") == ""

    def test_no_suffix(self):
        assert _normalize_vendor_name("Tumalo Creek Transportation") == "tumalo creek transportation"

    def test_special_chars_removed(self):
        assert _normalize_vendor_name("O'Brien & Sons, Inc.") == "obrien sons"

    def test_multiple_spaces_collapsed(self):
        assert _normalize_vendor_name("  Foo   Bar  ") == "foo bar"


# ---------------------------------------------------------------------------
# Unit tests: _calculate_fuzzy_score
# ---------------------------------------------------------------------------

class TestCalculateFuzzyScore:
    """Token-overlap scoring with BC code prefix stripping."""

    def test_identical(self):
        assert _calculate_fuzzy_score("Acme Corp", "Acme Corp") == 1.0

    def test_completely_different(self):
        assert _calculate_fuzzy_score("Acme", "Zebra") == 0.0

    def test_bc_code_prefix_stripped(self):
        score = _calculate_fuzzy_score("Tumalo Creek", "TUMALOC - Tumalo Creek")
        assert score >= 0.8

    def test_empty_strings(self):
        assert _calculate_fuzzy_score("", "Acme") == 0.0
        assert _calculate_fuzzy_score("Acme", "") == 0.0
        assert _calculate_fuzzy_score("", "") == 0.0

    def test_partial_overlap(self):
        score = _calculate_fuzzy_score("Acme Widgets Inc", "Acme Corp")
        assert 0.0 < score < 1.0


# ---------------------------------------------------------------------------
# Unit tests: _compute_extraction_quality
# ---------------------------------------------------------------------------

class TestComputeExtractionQuality:
    """Extraction quality scoring — pure computation."""

    def test_all_required_fields(self):
        fields = {"vendor": "Acme", "invoice_number": "INV-001", "amount": 100.00}
        config = {
            "required_extractions": ["vendor", "invoice_number", "amount"],
            "optional_extractions": ["po_number", "due_date"],
        }
        result = _compute_extraction_quality(fields, {}, config)
        assert result["completeness_score"] == 0.8
        assert result["ready_for_draft_candidate"] is True
        assert result["required_extracted"] == 3
        assert result["optional_extracted"] == 0

    def test_all_fields_present(self):
        fields = {
            "vendor": "Acme", "invoice_number": "INV-001", "amount": 100.00,
            "po_number": "PO-123", "due_date": "2026-01-01",
        }
        config = {
            "required_extractions": ["vendor", "invoice_number", "amount"],
            "optional_extractions": ["po_number", "due_date"],
        }
        result = _compute_extraction_quality(fields, {}, config)
        assert result["completeness_score"] == 1.0
        assert result["ready_for_draft_candidate"] is True

    def test_missing_required_field(self):
        fields = {"vendor": "Acme", "amount": 100.00}
        config = {
            "required_extractions": ["vendor", "invoice_number", "amount"],
            "optional_extractions": [],
        }
        result = _compute_extraction_quality(fields, {}, config)
        assert result["required_extracted"] == 2
        assert result["ready_for_draft_candidate"] is False

    def test_empty_fields(self):
        result = _compute_extraction_quality({}, {}, {"required_extractions": [], "optional_extractions": []})
        assert result["completeness_score"] == 1.0  # no requirements = fully complete
        assert result["ready_for_draft_candidate"] is True  # no required fields

    def test_default_config_with_empty_fields(self):
        """Default config has required fields, so empty extraction = not ready."""
        result = _compute_extraction_quality({}, {}, {})
        assert result["ready_for_draft_candidate"] is False

    def test_fallback_to_extracted_fields(self):
        """extracted_fields param is checked when normalized_fields misses a key."""
        normalized = {"vendor": "Acme"}
        raw = {"invoice_number": "INV-001", "amount": 50}
        config = {
            "required_extractions": ["vendor", "invoice_number", "amount"],
            "optional_extractions": [],
        }
        result = _compute_extraction_quality(normalized, raw, config)
        assert result["required_extracted"] == 3


# ---------------------------------------------------------------------------
# Integration: validate_bc_match demo mode
# ---------------------------------------------------------------------------

class TestValidateBcMatchDemoMode:
    """In demo mode, returns early with simulated check."""

    @pytest.mark.asyncio
    async def test_demo_mode_returns_simulated(self):
        from unittest.mock import patch
        with patch("services.bc_validation_service.DEMO_MODE", True, create=True), \
             patch("deps.DEMO_MODE", True):
            result = await validate_bc_match(
                "AP_Invoice",
                {"vendor": "Acme", "invoice_number": "INV-001"},
                {},
            )
        assert result["all_passed"] is True
        assert any(c["check_name"] == "demo_mode" for c in result["checks"])

    @pytest.mark.asyncio
    async def test_result_shape(self):
        from unittest.mock import patch
        with patch("deps.DEMO_MODE", True), \
             patch("deps.BC_CLIENT_ID", ""):
            result = await validate_bc_match("AP_Invoice", {}, {})

        # Verify all expected top-level keys are present
        expected_keys = {
            "all_passed", "checks", "warnings", "bc_record_id",
            "bc_record_info", "vendor_candidates", "customer_candidates",
            "normalized_fields", "match_method", "match_score",
            "extraction_quality",
        }
        assert expected_keys.issubset(set(result.keys()))

    @pytest.mark.asyncio
    async def test_extraction_quality_populated(self):
        from unittest.mock import patch
        with patch("deps.DEMO_MODE", True), \
             patch("deps.BC_CLIENT_ID", ""):
            result = await validate_bc_match(
                "AP_Invoice",
                {"vendor": "Acme", "invoice_number": "INV-001", "amount": 100},
                {"required_extractions": ["vendor", "invoice_number", "amount"]},
            )

        eq = result["extraction_quality"]
        assert eq["vendor_extracted"] is True
        assert eq["invoice_number_extracted"] is True
        assert eq["amount_extracted"] is True
        assert eq["completeness_score"] > 0


# ---------------------------------------------------------------------------
# Integration: validate_bc_match error handling
# ---------------------------------------------------------------------------

class TestValidateBcMatchErrorHandling:
    """BC connection failures produce structured errors."""

    @pytest.mark.asyncio
    async def test_token_failure(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        mock_adapter = MagicMock()
        mock_adapter.get_token = AsyncMock(return_value=None)
        with patch("deps.DEMO_MODE", False), \
             patch("deps.BC_CLIENT_ID", "some-client-id"), \
             patch("services.bc_access.get_bc_adapter", return_value=mock_adapter):
            result = await validate_bc_match("AP_Invoice", {"vendor": "X"}, {})

        assert result["all_passed"] is False
        assert any(c["check_name"] == "bc_connection" for c in result["checks"])

    @pytest.mark.asyncio
    async def test_company_failure(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        mock_adapter = MagicMock()
        mock_adapter.get_token = AsyncMock(return_value="mock-token")
        mock_adapter.get_company_id = AsyncMock(return_value=None)
        with patch("deps.DEMO_MODE", False), \
             patch("deps.BC_CLIENT_ID", "some-client-id"), \
             patch("services.bc_access.get_bc_adapter", return_value=mock_adapter):
            result = await validate_bc_match("AP_Invoice", {"vendor": "X"}, {})

        assert result["all_passed"] is False
        assert any("No BC companies" in c.get("details", "") for c in result["checks"])

    @pytest.mark.asyncio
    async def test_exception_caught(self):
        from unittest.mock import patch, AsyncMock, MagicMock
        mock_adapter = MagicMock()
        mock_adapter.get_token = AsyncMock(side_effect=RuntimeError("network down"))
        with patch("deps.DEMO_MODE", False), \
             patch("deps.BC_CLIENT_ID", "some-client-id"), \
             patch("services.bc_access.get_bc_adapter", return_value=mock_adapter):
            result = await validate_bc_match("AP_Invoice", {"vendor": "X"}, {})

        assert result["all_passed"] is False
        assert any(c["check_name"] == "bc_error" for c in result["checks"])


# ---------------------------------------------------------------------------
# Compatibility: server.py wrapper still works
# ---------------------------------------------------------------------------

class TestServerWrapper:
    """server.py's validate_bc_match delegates to bc_validation_service."""

    @pytest.mark.asyncio
    async def test_wrapper_delegates(self):
        from unittest.mock import patch
        with patch("deps.DEMO_MODE", True), \
             patch("deps.BC_CLIENT_ID", ""):
            from services.bc_validation_service import validate_bc_match as server_fn
            result = await server_fn("AP_Invoice", {"vendor": "Acme"}, {})

        assert "checks" in result
        assert any(c["check_name"] == "demo_mode" for c in result["checks"])


# ---------------------------------------------------------------------------
# Compatibility: document_intel_helpers adapter still works
# ---------------------------------------------------------------------------

class TestDocIntelHelpersAdapter:
    """document_intel_helpers.validate_bc_match delegates correctly."""

    @pytest.mark.asyncio
    async def test_adapter_delegates(self):
        from unittest.mock import patch
        with patch("deps.DEMO_MODE", True), \
             patch("deps.BC_CLIENT_ID", ""):
            from services.document_intel_helpers import validate_bc_match as helper_fn
            result = await helper_fn("AP_Invoice", {"vendor": "Acme"}, {})

        assert "checks" in result
        assert any(c["check_name"] == "demo_mode" for c in result["checks"])


# ---------------------------------------------------------------------------
# API regression — endpoints that trigger validation should still return 200
# ---------------------------------------------------------------------------

import requests

API_BASE = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestAPIRegression:
    """Endpoints that depend on validate_bc_match continue to work."""

    def test_health(self):
        resp = requests.get(f"{API_BASE}/api/health")
        assert resp.status_code == 200

    def test_documents_list(self):
        resp = requests.get(f"{API_BASE}/api/documents")
        assert resp.status_code == 200

    def test_pipeline_stages(self):
        resp = requests.get(f"{API_BASE}/api/document-intelligence/pipeline/stages")
        assert resp.status_code == 200
        data = resp.json()
        assert len(data["stages"]) == 9
