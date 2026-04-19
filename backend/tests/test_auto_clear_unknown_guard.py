"""
Regression tests for the auto-clear Unknown/split-child guardrail.

Bug reproduced:
    Auto-split child documents (e.g., `..._p11.pdf` from Ball Metal) were
    classified as `doc_type = "Unknown"` with 0.00 confidence and zero
    extracted fields, yet passed `evaluate_auto_clear()` ("All 1 checks
    passed") because the `Unknown` threshold config was 0.0 and had no
    minimum-extraction requirement. They were then exported/completed,
    bypassing human review.

Fixed by adding a hard guardrail at the top of `evaluate_auto_clear` that
refuses to auto-clear documents with:
    - doc_type in {None, "", "Unknown", "Other", "Unknown_Document", ...}
    AND (confidence < 0.70 OR fewer than 2 meaningful extracted fields)
"""

from services.auto_clear_service import evaluate_auto_clear, AutoClearDecision


def test_unknown_zero_confidence_blocked():
    """The exact real-world case: Unknown + 0 conf + 0 fields."""
    doc = {
        "id": "d1",
        "doc_type": "Unknown",
        "ai_classification": {"confidence": 0.0, "method": "ai_classifier"},
        "extracted_fields": {},
    }
    decision, reason, details = evaluate_auto_clear(doc)
    assert decision == AutoClearDecision.NEEDS_REVIEW
    assert details.get("unclassified_guard_triggered") is True
    assert "Unclassified" in reason or "doc_type=Unknown" in reason


def test_empty_doc_type_blocked():
    """None / empty doc_type should also fail the guardrail."""
    doc = {
        "id": "d2",
        "doc_type": None,
        "ai_classification": {"confidence": 0.95},
        "extracted_fields": {},
    }
    decision, reason, details = evaluate_auto_clear(doc)
    assert decision == AutoClearDecision.NEEDS_REVIEW
    assert details.get("unclassified_guard_triggered") is True


def test_other_low_confidence_blocked():
    doc = {
        "id": "d3",
        "document_type": "Other",
        "ai_confidence": 0.40,
        "extracted_fields": {"vendor": "Ball Metal"},
    }
    decision, _, details = evaluate_auto_clear(doc)
    assert decision == AutoClearDecision.NEEDS_REVIEW
    assert details.get("unclassified_guard_triggered") is True


def test_unknown_high_confidence_with_fields_allowed_past_guard():
    """An Unknown doc with good confidence AND real extracted content is
    allowed to proceed past the guard (downstream checks still apply)."""
    doc = {
        "id": "d4",
        "doc_type": "Unknown",
        "ai_classification": {"confidence": 0.85},
        "extracted_fields": {
            "vendor": "Ball Metal",
            "po_number": "P0024333",
            "amount": "1234.56",
        },
    }
    decision, _, details = evaluate_auto_clear(doc)
    # Should NOT be blocked by the early guard — may still be CLEARED
    # since Unknown config has no further required checks.
    assert not details.get("unclassified_guard_triggered", False)


def test_known_doctype_with_low_confidence_unaffected():
    """Guard only fires for Unknown-family types — existing flows untouched."""
    doc = {
        "id": "d5",
        "doc_type": "AP_Invoice",
        "ai_classification": {"confidence": 0.10},
        "extracted_fields": {"vendor": "Acme"},
    }
    decision, _, details = evaluate_auto_clear(doc)
    # Fails downstream (low AP confidence) but not via our new guard
    assert not details.get("unclassified_guard_triggered", False)
    assert decision == AutoClearDecision.NEEDS_REVIEW


def test_unknown_percentage_string_confidence_blocked():
    """Handle string percentages like '0%'."""
    doc = {
        "id": "d6",
        "doc_type": "Unknown",
        "confidence": "0%",
        "extracted_fields": {},
    }
    decision, _, details = evaluate_auto_clear(doc)
    assert decision == AutoClearDecision.NEEDS_REVIEW
    assert details.get("unclassified_guard_triggered") is True


def test_unknown_document_variant_blocked():
    """Check the 'Unknown_Document' / 'Unknown_Sales' variants."""
    for t in ("Unknown_Document", "Unknown_Sales", "UNKNOWN", "DEFAULT"):
        doc = {
            "id": f"d7-{t}",
            "doc_type": t,
            "ai_classification": {"confidence": 0.0},
            "extracted_fields": {},
        }
        decision, _, details = evaluate_auto_clear(doc)
        assert decision == AutoClearDecision.NEEDS_REVIEW, f"{t} should be blocked"
        assert details.get("unclassified_guard_triggered") is True, f"{t} guard flag missing"


def test_unknown_with_one_field_still_blocked():
    """One meaningful field is NOT enough — we require >= 2."""
    doc = {
        "id": "d8",
        "doc_type": "Unknown",
        "ai_classification": {"confidence": 0.85},
        "extracted_fields": {"vendor": "Ball Metal"},
    }
    decision, _, details = evaluate_auto_clear(doc)
    assert decision == AutoClearDecision.NEEDS_REVIEW
    assert details.get("unclassified_guard_triggered") is True
