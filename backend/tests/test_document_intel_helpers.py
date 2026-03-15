"""
Tests for Document Intelligence helpers and pipeline alignment.

Covers:
  - Field normalization (normalize_extracted_fields)
  - AP field computation (compute_ap_normalized_fields)
  - Automation decision matrix (make_automation_decision)
  - Pipeline stage ordering and naming
  - Legacy decoupling verification
"""

import pytest
import sys
import os

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.document_intel_helpers import (
    normalize_extracted_fields,
    compute_ap_normalized_fields,
    make_automation_decision,
)


# ============================================================================
# normalize_extracted_fields
# ============================================================================

class TestNormalizeExtractedFields:
    def test_amount_normalization(self):
        fields = {"amount": "$1,234.56"}
        result = normalize_extracted_fields(fields)
        assert result["amount"] == 1234.56
        assert result["amount_raw"] == "$1,234.56"

    def test_amount_bad_value(self):
        result = normalize_extracted_fields({"amount": "N/A"})
        assert result["amount"] is None
        assert result["amount_raw"] == "N/A"

    def test_date_normalization(self):
        result = normalize_extracted_fields({"invoice_date": "March 15, 2026"})
        assert result["invoice_date"] == "2026-03-15"
        assert result["invoice_date_raw"] == "March 15, 2026"

    def test_date_bad_value(self):
        result = normalize_extracted_fields({"invoice_date": "not-a-date"})
        # dateutil.parser can parse almost anything, but if it truly fails:
        assert "invoice_date" in result

    def test_string_trimming(self):
        result = normalize_extracted_fields({"vendor": "  Acme Corp  "})
        assert result["vendor"] == "Acme Corp"

    def test_none_values_skipped(self):
        result = normalize_extracted_fields({"amount": None, "vendor": "Acme"})
        assert "amount" not in result
        assert result["vendor"] == "Acme"

    def test_empty_fields(self):
        assert normalize_extracted_fields({}) == {}

    def test_numeric_passthrough(self):
        result = normalize_extracted_fields({"quantity": 42})
        assert result["quantity"] == 42

    def test_multiple_date_fields(self):
        result = normalize_extracted_fields({
            "due_date": "2026-04-01",
            "ship_date": "2026-03-20",
        })
        assert result["due_date"] == "2026-04-01"
        assert result["ship_date"] == "2026-03-20"


# ============================================================================
# compute_ap_normalized_fields
# ============================================================================

class TestComputeApNormalizedFields:
    def test_vendor_normalization(self):
        result = compute_ap_normalized_fields({"vendor": "  ACME Corp  "})
        assert result["vendor_raw"] == "ACME Corp"
        assert result["vendor_normalized"] == "acme corp"

    def test_invoice_number_clean(self):
        result = compute_ap_normalized_fields({"invoice_number": "inv 123,456"})
        assert result["invoice_number_raw"] == "inv 123,456"
        assert result["invoice_number_clean"] == "INV123456"

    def test_amount_parsing(self):
        result = compute_ap_normalized_fields({"amount": "$9,876.54"})
        assert result["amount_raw"] == "$9,876.54"
        assert result["amount_float"] == 9876.54

    def test_amount_bad(self):
        result = compute_ap_normalized_fields({"amount": "TBD"})
        assert result["amount_float"] is None

    def test_due_date_iso(self):
        result = compute_ap_normalized_fields({"due_date": "April 1, 2026"})
        assert result["due_date_iso"] == "2026-04-01"

    def test_po_number_clean(self):
        result = compute_ap_normalized_fields({"po_number": "po 789"})
        assert result["po_number_clean"] == "PO789"

    def test_invoice_date_iso(self):
        result = compute_ap_normalized_fields({"invoice_date": "03/15/2026"})
        assert result["invoice_date"] == "2026-03-15"

    def test_line_items_normalization(self):
        items = [{"description": "Widget", "quantity": "2", "unit_price": "10.50", "total": "21.00"}]
        result = compute_ap_normalized_fields({"line_items": items})
        assert len(result["line_items"]) == 1
        assert result["line_items"][0]["quantity"] == 2.0
        assert result["line_items"][0]["unit_price"] == 10.50

    def test_empty_input(self):
        assert compute_ap_normalized_fields({}) == {}
        assert compute_ap_normalized_fields(None) == {}

    def test_missing_fields_get_none(self):
        result = compute_ap_normalized_fields({"vendor": "Acme"})
        assert result["invoice_number_raw"] is None
        assert result["amount_raw"] is None
        assert result["line_items"] == []


# ============================================================================
# make_automation_decision
# ============================================================================

class TestMakeAutomationDecision:
    def _config(self, level=1, link=0.85, create=0.95, review=True):
        return {
            "automation_level": level,
            "min_confidence_to_auto_link": link,
            "min_confidence_to_auto_create_draft": create,
            "requires_human_review_if_exception": review,
        }

    def _validation_ok(self):
        return {"all_passed": True, "checks": [], "warnings": []}

    def _validation_fail(self, checks=None):
        return {
            "all_passed": False,
            "checks": checks or [{"check_name": "vendor_match", "passed": False, "required": True}],
            "warnings": [],
        }

    def test_level_0_always_manual(self):
        dec, reason, meta = make_automation_decision(self._config(level=0), 0.99, self._validation_ok())
        assert dec == "manual"

    def test_level_1_high_confidence_auto_link(self):
        dec, reason, meta = make_automation_decision(self._config(level=1), 0.90, self._validation_ok())
        assert dec == "auto_link"

    def test_level_1_low_confidence_needs_review(self):
        dec, reason, meta = make_automation_decision(self._config(level=1), 0.50, self._validation_ok())
        assert dec == "needs_review"

    def test_level_2_high_confidence_auto_create(self):
        dec, reason, meta = make_automation_decision(self._config(level=2), 0.97, self._validation_ok())
        assert dec == "auto_create"

    def test_level_2_medium_confidence_auto_link(self):
        dec, reason, meta = make_automation_decision(self._config(level=2), 0.90, self._validation_ok())
        assert dec == "auto_link"

    def test_validation_fail_needs_review(self):
        dec, reason, meta = make_automation_decision(self._config(level=1), 0.95, self._validation_fail())
        assert dec == "needs_review"
        assert "vendor_match" in reason

    def test_validation_fail_no_review_required(self):
        dec, reason, meta = make_automation_decision(
            self._config(level=1, review=False), 0.95, self._validation_fail()
        )
        assert dec == "manual"

    def test_metadata_has_candidates(self):
        val = self._validation_ok()
        val["vendor_candidates"] = [{"name": "Acme"}]
        _, _, meta = make_automation_decision(self._config(level=1), 0.90, val)
        assert len(meta["vendor_candidates"]) == 1

    def test_warnings_in_reason(self):
        val = self._validation_ok()
        val["warnings"] = ["minor issue"]
        dec, reason, _ = make_automation_decision(self._config(level=1), 0.90, val)
        assert dec == "auto_link"
        assert "warning" in reason.lower()


# ============================================================================
# Pipeline stage ordering
# ============================================================================

class TestPipelineStages:
    def test_9_stages(self):
        from services.pipeline.document_pipeline import STAGE_ORDER
        assert len(STAGE_ORDER) == 9

    def test_stage_names(self):
        from services.pipeline.document_pipeline import STAGE_ORDER
        assert STAGE_ORDER[0] == "classification"
        assert STAGE_ORDER[1] == "extraction"
        assert STAGE_ORDER[2] == "layout"
        assert STAGE_ORDER[3] == "entity_resolution"
        assert STAGE_ORDER[8] == "learning_capture"

    def test_backward_compat_v1(self):
        from services.pipeline.document_pipeline import STAGE_ORDER_V1
        assert len(STAGE_ORDER_V1) == 7
        assert "extraction" not in STAGE_ORDER_V1
        assert "layout" not in STAGE_ORDER_V1

    def test_all_stages_have_runners(self):
        from services.pipeline.document_pipeline import STAGE_ORDER, _STAGE_RUNNERS
        for stage in STAGE_ORDER:
            assert stage in _STAGE_RUNNERS, f"Missing runner for stage: {stage}"


# ============================================================================
# Legacy decoupling verification
# ============================================================================

class TestLegacyDecoupling:
    """Verify document_intelligence_service no longer imports from server.py."""

    def test_no_server_import_in_doc_intel_service(self):
        with open("services/document_intelligence_service.py") as f:
            content = f.read()
        # Should NOT have direct 'from server import' anymore
        assert "from server import" not in content, \
            "document_intelligence_service still imports from server.py"

    def test_imports_from_helpers(self):
        with open("services/document_intelligence_service.py") as f:
            content = f.read()
        assert "from services.document_intel_helpers import" in content

    def test_uses_shared_utcnow(self):
        with open("services/document_intelligence_service.py") as f:
            content = f.read()
        assert "from services.automation_helpers import" in content
        # Should NOT have raw datetime calls
        raw_count = content.count("datetime.now(timezone.utc).isoformat()")
        assert raw_count == 0, f"Found {raw_count} raw datetime calls"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
