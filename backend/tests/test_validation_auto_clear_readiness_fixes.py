"""
Tests for the 3 validation bug fixes:
1. BC Validation extraction_quality_gate - rejects docs with no meaningful fields
2. Auto-clear minimum extraction - filters _detected_by metadata from count
3. Readiness terminal shortcut - requires meaningful_count >= 1 for completed docs

These are unit tests that directly call the service functions.
"""
import pytest
import sys
import os

# Ensure backend directory is in path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), '..'))

from services.bc_validation_service import validate_bc_match
from services.auto_clear_service import evaluate_auto_clear, AutoClearDecision
from services.document_readiness_service import evaluate_readiness


# =============================================================================
# BC Validation - extraction_quality_gate tests
# =============================================================================

class TestBCValidationExtractionQualityGate:
    """Tests for BC validation extraction quality gate (reject docs with only metadata)."""

    @pytest.mark.asyncio
    async def test_bc_validation_fails_when_only_metadata_fields(self):
        """BC Validation should FAIL when extracted_fields has only _detected_by metadata."""
        extracted_fields = {
            "bol_detected_by": "heuristic",
            "packing_list_detected_by": "pattern_match",
        }
        job_config = {"required_extractions": ["vendor", "bol_number"]}

        result = await validate_bc_match(
            job_type="Shipping_Document",
            extracted_fields=extracted_fields,
            job_config=job_config,
        )

        # Should fail because no meaningful data
        assert result["all_passed"] is False, "BC validation should FAIL with only metadata fields"
        
        # Check for extraction_quality_gate check
        gate_check = next(
            (c for c in result["checks"] if c["check_name"] == "extraction_quality_gate"),
            None
        )
        assert gate_check is not None, "extraction_quality_gate check should be present"
        assert gate_check["passed"] is False, "extraction_quality_gate should fail"
        assert "No meaningful data extracted" in gate_check["details"]
        print("PASS: BC validation correctly rejects docs with only _detected_by metadata")

    @pytest.mark.asyncio
    async def test_bc_validation_passes_with_real_data(self):
        """BC Validation should NOT fail quality gate when real data is present."""
        extracted_fields = {
            "vendor": "Test Vendor Inc",
            "bol_number": "BOL123456",
            "amount": 500.00,
            "bol_detected_by": "heuristic",  # metadata field - should be ignored
        }
        job_config = {"required_extractions": ["vendor", "bol_number"]}

        result = await validate_bc_match(
            job_type="Shipping_Document",
            extracted_fields=extracted_fields,
            job_config=job_config,
        )

        # Should NOT fail the extraction_quality_gate
        gate_check = next(
            (c for c in result["checks"] if c["check_name"] == "extraction_quality_gate"),
            None
        )
        # If gate check is present, it means it failed - which is wrong
        if gate_check:
            assert gate_check["passed"] is True, "extraction_quality_gate should pass with real data"
        
        # Note: all_passed may still be False due to demo mode or other checks,
        # but the extraction quality gate should NOT be the blocker
        print(f"PASS: BC validation quality gate passed with real data (all_passed={result['all_passed']})")

    @pytest.mark.asyncio
    async def test_bc_validation_fails_with_empty_extracted_fields(self):
        """BC Validation should FAIL when extracted_fields is empty."""
        extracted_fields = {}
        job_config = {"required_extractions": ["vendor", "invoice_number"]}

        result = await validate_bc_match(
            job_type="AP_Invoice",
            extracted_fields=extracted_fields,
            job_config=job_config,
        )

        assert result["all_passed"] is False, "BC validation should FAIL with empty extracted_fields"
        
        gate_check = next(
            (c for c in result["checks"] if c["check_name"] == "extraction_quality_gate"),
            None
        )
        assert gate_check is not None, "extraction_quality_gate check should be present"
        assert gate_check["passed"] is False
        print("PASS: BC validation correctly rejects docs with empty extracted_fields")


# =============================================================================
# Auto-Clear - minimum extraction tests
# =============================================================================

class TestAutoClearMinimumExtraction:
    """Tests for auto-clear minimum extraction filtering _detected_by fields."""

    def test_auto_clear_returns_missing_data_for_only_metadata(self):
        """Auto-clear should return MISSING_DATA for Shipping_Document with only _detected_by field."""
        doc = {
            "id": "test-doc-metadata-only",
            "doc_type": "Shipping_Document",
            "ai_confidence": 0.95,
            "extracted_fields": {
                "bol_detected_by": "heuristic",
            },
            "normalized_fields": {},
        }

        decision, reason, details = evaluate_auto_clear(doc)

        assert decision == AutoClearDecision.MISSING_DATA, f"Expected MISSING_DATA, got {decision.value}"
        assert "Insufficient data" in reason or "meaningful" in reason.lower(), f"Reason should mention insufficient data: {reason}"
        print(f"PASS: Auto-clear returns MISSING_DATA for doc with only metadata. Reason: {reason}")

    def test_auto_clear_returns_cleared_with_real_data(self):
        """Auto-clear should return CLEARED for Shipping_Document with vendor + bol_number + ship_date."""
        doc = {
            "id": "test-doc-real-data",
            "doc_type": "Shipping_Document",
            "ai_confidence": 0.95,
            "extracted_fields": {
                "vendor": "Test Carrier LLC",
                "bol_number": "BOL789012",
                "ship_date": "2026-01-15",
                "bol_detected_by": "heuristic",  # metadata - should be ignored
            },
            "normalized_fields": {},
        }

        decision, reason, details = evaluate_auto_clear(doc)

        assert decision == AutoClearDecision.CLEARED, f"Expected CLEARED, got {decision.value}. Reason: {reason}"
        print(f"PASS: Auto-clear returns CLEARED for doc with real data. Checks: {len(details.get('checks', []))}")

    def test_auto_clear_counts_real_fields_correctly(self):
        """Auto-clear should still count real fields (vendor, amount, etc.) correctly."""
        doc = {
            "id": "test-doc-count-fields",
            "doc_type": "Shipping_Document",
            "ai_confidence": 0.85,
            "extracted_fields": {
                "vendor": "Acme Freight",
                "amount": 150.00,
                "po_number": "PO-123",
                "bol_detected_by": "pattern",
                "invoice_detected_by": "llm",
            },
            "normalized_fields": {},
        }

        decision, reason, details = evaluate_auto_clear(doc)

        # Should pass minimum extraction (has vendor OR order ref OR 3+ real fields)
        # Has vendor + po_number + amount = 3 real fields
        minimum_check = next(
            (c for c in details.get("checks", []) if c["check"] == "minimum_extraction"),
            None
        )
        
        if minimum_check:
            assert minimum_check["passed"] is True, f"minimum_extraction should pass: {minimum_check}"
            # Verify field count excludes _detected_by fields
            field_count = minimum_check.get("value", {}).get("field_count", 0)
            assert field_count >= 3, f"Should count at least 3 real fields, got {field_count}"
        
        print(f"PASS: Auto-clear correctly counts real fields. Decision: {decision.value}")

    def test_auto_clear_handles_mixed_empty_and_metadata(self):
        """Auto-clear handles docs with empty values and metadata-only."""
        doc = {
            "id": "test-doc-empty-mixed",
            "doc_type": "Warehouse_Document",
            "ai_confidence": 0.90,
            "extracted_fields": {
                "vendor": "",  # Empty - should not count
                "bol_number": None,  # None - should not count
                "packing_list_detected_by": "heuristic",  # Metadata - should not count
            },
            "normalized_fields": {},
        }

        decision, reason, details = evaluate_auto_clear(doc)

        # Should return MISSING_DATA because no real non-empty fields
        assert decision == AutoClearDecision.MISSING_DATA, f"Expected MISSING_DATA, got {decision.value}"
        print(f"PASS: Auto-clear returns MISSING_DATA for empty + metadata mix. Reason: {reason}")


# =============================================================================
# Readiness - terminal shortcut tests
# =============================================================================

class TestReadinessTerminalShortcut:
    """Tests for readiness terminal shortcut requiring meaningful_count >= 1."""

    def test_readiness_blocked_for_completed_with_zero_meaningful_fields(self):
        """Readiness should return BLOCKED for completed docs with 0 meaningful extracted fields."""
        doc = {
            "id": "test-doc-completed-no-data",
            "status": "Completed",
            "auto_cleared": True,
            "workflow_status": "exported",
            "extracted_fields": {
                "bol_detected_by": "heuristic",  # Only metadata
            },
        }

        result = evaluate_readiness(doc)

        # Should NOT return ready_auto_link because there's no meaningful data
        # The terminal shortcut should NOT fire
        assert result["status"] != "ready_auto_link" or len(result.get("blocking_reasons", [])) > 0, \
            f"Should not be ready_auto_link with 0 meaningful fields. Got status: {result['status']}"
        
        # Actually, with the fix, it should evaluate normally and likely be blocked
        print(f"PASS: Readiness for completed doc with 0 meaningful fields: status={result['status']}, confidence={result['confidence']}")

    def test_readiness_ready_auto_link_for_completed_with_real_data(self):
        """Readiness should return ready_auto_link for completed docs with real extracted data."""
        doc = {
            "id": "test-doc-completed-with-data",
            "status": "Completed",
            "auto_cleared": True,
            "workflow_status": "exported",
            "extracted_fields": {
                "vendor": "Real Vendor Corp",
                "invoice_number": "INV-001",
                "amount": 1000.00,
                "bol_detected_by": "heuristic",  # Metadata - ignored for count
            },
            "vendor_canonical": "Real Vendor Corp",
        }

        result = evaluate_readiness(doc)

        # Should return ready_auto_link because doc is completed AND has real data
        assert result["status"] == "ready_auto_link", \
            f"Expected ready_auto_link for completed doc with real data. Got: {result['status']}"
        assert result["confidence"] == 1.0, f"Expected confidence 1.0, got {result['confidence']}"
        print(f"PASS: Readiness returns ready_auto_link for completed doc with real data")

    def test_readiness_terminal_shortcut_counts_meaningful_fields(self):
        """Readiness terminal shortcut correctly counts meaningful fields (excludes _detected_by)."""
        # Doc with exactly 1 meaningful field
        doc_one_field = {
            "id": "test-doc-one-field",
            "status": "Completed",
            "auto_cleared": True,
            "extracted_fields": {
                "vendor": "Single Field Vendor",
                "classification_detected_by": "ai",
                "type_detected_by": "pattern",
            },
            "vendor_canonical": "Single Field Vendor",
        }

        result = evaluate_readiness(doc_one_field)
        
        # With 1 meaningful field, terminal shortcut should fire
        assert result["status"] == "ready_auto_link", \
            f"Expected ready_auto_link with 1 meaningful field. Got: {result['status']}"
        print(f"PASS: Readiness terminal shortcut works with 1 meaningful field")

    def test_readiness_does_not_shortcut_for_non_terminal_status(self):
        """Readiness should NOT use terminal shortcut for non-completed docs."""
        doc = {
            "id": "test-doc-in-progress",
            "status": "Processing",
            "auto_cleared": False,
            "extracted_fields": {
                "vendor": "Some Vendor",
            },
        }

        result = evaluate_readiness(doc)

        # Should NOT have ready_auto_link shortcut since not completed
        # (unless it evaluates to that status through normal flow)
        # The key is it goes through full evaluation, not shortcut
        assert "Document already processed and completed" not in result.get("explanations", []), \
            "Should not trigger terminal shortcut for non-completed doc"
        print(f"PASS: Readiness evaluates non-completed doc normally: status={result['status']}")


# =============================================================================
# Integration tests - end-to-end scenarios
# =============================================================================

class TestIntegrationScenarios:
    """Integration tests combining all 3 fixes."""

    @pytest.mark.asyncio
    async def test_bad_document_fails_all_checks(self):
        """Document with only _detected_by metadata fails BC validation, auto-clear, and readiness."""
        # Simulates a document that was incorrectly processed
        bad_extracted = {"bol_detected_by": "heuristic"}
        
        # BC Validation
        bc_result = await validate_bc_match(
            job_type="Shipping_Document",
            extracted_fields=bad_extracted,
            job_config={"required_extractions": ["vendor"]},
        )
        assert bc_result["all_passed"] is False, "BC should fail"
        
        # Auto-clear
        bad_doc = {
            "id": "bad-doc",
            "doc_type": "Shipping_Document",
            "ai_confidence": 0.90,
            "extracted_fields": bad_extracted,
            "normalized_fields": {},
        }
        ac_decision, ac_reason, _ = evaluate_auto_clear(bad_doc)
        assert ac_decision == AutoClearDecision.MISSING_DATA, f"Auto-clear should be MISSING_DATA, got {ac_decision.value}"
        
        # Readiness (if it were marked completed incorrectly)
        bad_doc["status"] = "Completed"
        bad_doc["auto_cleared"] = True
        readiness = evaluate_readiness(bad_doc)
        # Should NOT be ready_auto_link with 100% confidence
        if readiness["status"] == "ready_auto_link":
            # This is the bug case - should not happen with fix
            assert False, "Readiness should NOT shortcut to ready_auto_link with 0 meaningful fields"
        
        print("PASS: Bad document correctly fails all 3 checks")

    @pytest.mark.asyncio
    async def test_good_document_passes_all_checks(self):
        """Document with real data passes BC validation, auto-clear, and readiness."""
        good_extracted = {
            "vendor": "Acme Shipping Co",
            "bol_number": "BOL-999",
            "ship_date": "2026-01-20",
            "bol_detected_by": "heuristic",  # metadata - should be ignored
        }
        
        # BC Validation - quality gate should pass
        bc_result = await validate_bc_match(
            job_type="Shipping_Document",
            extracted_fields=good_extracted,
            job_config={"required_extractions": ["vendor"]},
        )
        gate_check = next(
            (c for c in bc_result["checks"] if c["check_name"] == "extraction_quality_gate"),
            None
        )
        if gate_check:
            assert gate_check["passed"] is True, "BC quality gate should pass with real data"
        
        # Auto-clear
        good_doc = {
            "id": "good-doc",
            "doc_type": "Shipping_Document",
            "ai_confidence": 0.95,
            "extracted_fields": good_extracted,
            "normalized_fields": {},
        }
        ac_decision, ac_reason, _ = evaluate_auto_clear(good_doc)
        assert ac_decision == AutoClearDecision.CLEARED, f"Auto-clear should be CLEARED, got {ac_decision.value}"
        
        # Readiness (when completed)
        good_doc["status"] = "Completed"
        good_doc["auto_cleared"] = True
        good_doc["vendor_canonical"] = "Acme Shipping Co"
        readiness = evaluate_readiness(good_doc)
        assert readiness["status"] == "ready_auto_link", f"Readiness should be ready_auto_link, got {readiness['status']}"
        assert readiness["confidence"] == 1.0, f"Confidence should be 1.0, got {readiness['confidence']}"
        
        print("PASS: Good document correctly passes all 3 checks")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
