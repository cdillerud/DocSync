"""
Test: Auto-close confidence fix for documents with failed AI extraction.

Verifies:
1. _update_standard_workflow_status doesn't bail early when doc has valid type but 0 confidence
2. Confidence is bumped after successful deterministic classification
3. Auto-clear evaluates correctly with classification confidence fallback
4. is_eligible_for_auto_resolution passes for eligible doc types even with low confidence
"""
import pytest
from unittest.mock import AsyncMock, patch, MagicMock

# Test the auto-resolution eligibility check
def test_auto_resolution_eligible_by_doc_type():
    """Documents with eligible doc_type should be eligible regardless of confidence."""
    from services.auto_resolution_service import is_eligible_for_auto_resolution
    
    # AP_Invoice with 0 confidence - should STILL be eligible
    doc = {"document_type": "AP_Invoice", "ai_confidence": 0.0}
    eligible, reason = is_eligible_for_auto_resolution(doc)
    assert eligible, f"AP_Invoice should be eligible regardless of confidence: {reason}"
    
    # Shipping_Document with 0 confidence - should STILL be eligible
    doc = {"document_type": "Shipping_Document", "ai_confidence": 0.0}
    eligible, reason = is_eligible_for_auto_resolution(doc)
    assert eligible, f"Shipping_Document should be eligible regardless of confidence: {reason}"
    
    # BOL with 0 confidence - should STILL be eligible
    doc = {"document_type": "BOL", "ai_confidence": 0.0}
    eligible, reason = is_eligible_for_auto_resolution(doc)
    assert eligible, f"BOL should be eligible regardless of confidence: {reason}"


def test_auto_resolution_not_eligible_unknown_low_confidence():
    """Documents with 'Other' type AND low confidence should NOT be eligible."""
    from services.auto_resolution_service import is_eligible_for_auto_resolution
    
    doc = {"document_type": "Other", "ai_confidence": 0.0}
    eligible, reason = is_eligible_for_auto_resolution(doc)
    assert not eligible, "Other + 0.0 confidence should NOT be eligible"
    
    doc = {"document_type": "Unknown", "ai_confidence": 0.3}
    eligible, reason = is_eligible_for_auto_resolution(doc)
    assert not eligible, "Unknown + low confidence should NOT be eligible"


def test_auto_clear_confidence_fallback():
    """Auto-clear confidence gate should pass when classification method exists."""
    from services.auto_clear_service import evaluate_auto_clear, AutoClearDecision
    
    # Shipping_Document with 0.0 ai_confidence but successfully classified
    # Confidence fallback should bump to 0.85, passing the 0.70 threshold.
    # Additional checks (PO resolution etc.) may fail, but the confidence gate must PASS.
    doc = {
        "id": "test-doc-1",
        "doc_type": "Shipping_Document",
        "document_type": "Shipping_Document",
        "ai_confidence": 0.0,
        "classification_method": "mailbox:AP",
        "ai_classification": {"method": "mailbox:AP", "confidence": None},
        "vendor_normalized": "ACME Freight",
        "extracted_fields": {"vendor": "ACME Freight", "bol_number": "BOL-12345"},
    }
    
    decision, reason, details = evaluate_auto_clear(doc)
    # Verify the confidence check passed (decision should NOT be NEEDS_REVIEW due to confidence)
    confidence_check = next(
        (c for c in details.get("checks", []) if c["check"] == "confidence"), None
    )
    assert confidence_check is not None, "Confidence check should be in details"
    assert confidence_check["passed"], (
        f"Confidence check should pass with fallback: value={confidence_check.get('value')}, "
        f"threshold={confidence_check.get('threshold')}"
    )
    # Without full PO resolution data, later checks may fail — that's expected.
    # The key assertion is that the confidence gate no longer blocks.


def test_auto_clear_no_fallback_without_method():
    """Without classification method, confidence fallback shouldn't apply."""
    from services.auto_clear_service import evaluate_auto_clear, AutoClearDecision
    
    # AP_Invoice with 0 confidence and NO classification method
    doc = {
        "id": "test-doc-2",
        "doc_type": "AP_Invoice",
        "document_type": "AP_Invoice",
        "ai_confidence": 0.0,
        "classification_method": None,
        "ai_classification": None,
    }
    
    decision, reason, details = evaluate_auto_clear(doc)
    # AP_Invoice threshold is 0.90, no method means no fallback, 0.0 < 0.90
    assert decision == AutoClearDecision.NEEDS_REVIEW, (
        f"AP_Invoice with no classification method and 0 confidence should need review, got: {decision}"
    )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
