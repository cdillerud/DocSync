"""
Tests for Reference Intelligence shared helpers and consolidated services.

Covers:
  - Normalization consistency across all 3 normalizers
  - Fuzzy matching (ratio + vendor match)
  - Freight carrier detection
  - Reference number normalization edge cases
  - BC access adapter initialization
"""

import pytest
import sys
import os

# Add backend to path
sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.reference_helpers import (
    normalize_text,
    normalize_reference,
    normalize_company_name,
    fuzzy_ratio,
    fuzzy_vendor_match,
    is_freight_carrier,
)


# ============================================================================
# normalize_text  (generic string matching)
# ============================================================================

class TestNormalizeText:
    def test_basic(self):
        assert normalize_text("Hello World") == "hello world"

    def test_strips_punctuation(self):
        assert normalize_text("PO#12-345") == "po 12 345"

    def test_collapses_whitespace(self):
        assert normalize_text("  foo   bar  ") == "foo bar"

    def test_empty_and_none(self):
        assert normalize_text("") == ""
        assert normalize_text(None) == ""

    def test_numeric(self):
        assert normalize_text("12345") == "12345"


# ============================================================================
# normalize_reference  (reference number → BC lookup key)
# ============================================================================

class TestNormalizeReference:
    def test_basic(self):
        assert normalize_reference("PO-12345") == "12345"

    def test_uppercase(self):
        assert normalize_reference("po-12345") == "12345"

    def test_bol_prefix(self):
        assert normalize_reference("BOL 98765") == "98765"

    def test_bl_prefix(self):
        assert normalize_reference("B/L 55-44-33") == "554433"

    def test_strip_leading_zeros(self):
        assert normalize_reference("00012345") == "12345"

    def test_single_zero(self):
        assert normalize_reference("000") == "0"

    def test_hash_prefix(self):
        assert normalize_reference("#99887") == "99887"

    def test_with_trace(self):
        result, trace = normalize_reference("PO#00123", return_trace=True)
        assert result == "123"
        assert any(s["step"] == "strip_po_prefix" for s in trace)
        assert any(s["step"] == "strip_leading_zeros" for s in trace)

    def test_empty(self):
        assert normalize_reference("") == ""
        result, trace = normalize_reference("", return_trace=True)
        assert result == ""
        assert trace == []

    def test_inv_prefix(self):
        assert normalize_reference("INV-2024-001") == "2024001"

    def test_already_clean(self):
        assert normalize_reference("12345") == "12345"


# ============================================================================
# normalize_company_name  (vendor/customer name matching)
# ============================================================================

class TestNormalizeCompanyName:
    def test_basic(self):
        assert normalize_company_name("Acme Inc.") == "acme"

    def test_llc(self):
        assert normalize_company_name("TechCorp LLC") == "techcorp"

    def test_corporation(self):
        # "corporation" and then "company" suffix both stripped
        assert normalize_company_name("Big Company Corporation") == "big"

    def test_ltd(self):
        assert normalize_company_name("Smith Ltd.") == "smith"

    def test_preserves_words(self):
        assert normalize_company_name("Bob's Freight Co.") == "bobs freight"

    def test_empty(self):
        assert normalize_company_name("") == ""
        assert normalize_company_name(None) == ""

    def test_whitespace_collapse(self):
        assert normalize_company_name("  Gamer   Packaging  ") == "gamer packaging"


# ============================================================================
# fuzzy_ratio  (SequenceMatcher wrapper)
# ============================================================================

class TestFuzzyRatio:
    def test_exact_match(self):
        assert fuzzy_ratio("hello", "hello") == 1.0

    def test_no_match(self):
        assert fuzzy_ratio("abc", "xyz") < 0.5

    def test_with_normalizer(self):
        score = fuzzy_ratio("HELLO WORLD", "hello world", normalizer=normalize_text)
        assert score == 1.0

    def test_empty_strings(self):
        assert fuzzy_ratio("", "hello") == 0.0
        assert fuzzy_ratio("hello", "") == 0.0
        assert fuzzy_ratio("", "") == 0.0

    def test_partial_match(self):
        score = fuzzy_ratio("Gamer Packaging", "Gamer Pack")
        assert 0.5 < score < 1.0

    def test_company_name_normalizer(self):
        score = fuzzy_ratio("Acme Inc.", "ACME Corporation", normalizer=normalize_company_name)
        assert score == 1.0  # both normalize to "acme"


# ============================================================================
# fuzzy_vendor_match  (quick prefix/token check)
# ============================================================================

class TestFuzzyVendorMatch:
    def test_prefix_match(self):
        assert fuzzy_vendor_match("GAMER PACKAGING", "GAMER PACK") is True

    def test_short_prefix_no_match(self):
        assert fuzzy_vendor_match("AB", "ABC") is False  # too short for prefix

    def test_token_overlap(self):
        assert fuzzy_vendor_match("Cargo Modules LLC", "Cargo Modules Inc") is True

    def test_single_token_overlap_small_set(self):
        assert fuzzy_vendor_match("FedEx", "FedEx Ground") is True

    def test_no_match(self):
        assert fuzzy_vendor_match("ABC Corp", "XYZ Industries") is False

    def test_empty(self):
        assert fuzzy_vendor_match("", "hello") is False
        assert fuzzy_vendor_match("hello", "") is False


# ============================================================================
# is_freight_carrier
# ============================================================================

class TestIsFreightCarrier:
    def test_obvious_freight(self):
        assert is_freight_carrier("XYZ Freight") is True
        assert is_freight_carrier("ABC Trucking LLC") is True
        assert is_freight_carrier("Fast Logistics Inc") is True

    def test_not_freight(self):
        assert is_freight_carrier("Gamer Packaging") is False
        assert is_freight_carrier("Office Supplies Co") is False

    def test_case_insensitive(self):
        assert is_freight_carrier("TUMALO CREEK TRANSPORT") is True

    def test_empty(self):
        assert is_freight_carrier("") is False
        assert is_freight_carrier(None) is False

    def test_drayage(self):
        assert is_freight_carrier("Port Drayage Services") is True

    def test_ltl(self):
        assert is_freight_carrier("LTL Express") is True


# ============================================================================
# Cross-service consistency checks
# ============================================================================

class TestCrossServiceConsistency:
    """Verify that the shared helpers produce identical results to what
    the old per-service implementations would have produced."""

    def test_entity_resolution_normalize_matches_shared(self):
        """entity_resolution_service._normalize delegates to normalize_text."""
        from services.entity_resolution_service import _normalize
        for val in ["Hello World", "PO#12345", "  foo   bar  ", "", "12345"]:
            assert _normalize(val) == normalize_text(val), f"Mismatch for {val!r}"

    def test_entity_resolution_fuzzy_matches_shared(self):
        """entity_resolution_service._fuzzy_score delegates to fuzzy_ratio."""
        from services.entity_resolution_service import _fuzzy_score
        for a, b in [("hello", "hello"), ("abc", "xyz"), ("", "x"), ("Gamer", "Gamer Pack")]:
            expected = fuzzy_ratio(a, b, normalizer=normalize_text)
            actual = _fuzzy_score(a, b)
            assert abs(actual - expected) < 0.001, f"Mismatch for ({a!r}, {b!r})"

    def test_reference_normalize_matches_shared(self):
        """reference_intelligence_service.normalize_reference delegates to shared."""
        from services.reference_intelligence_service import normalize_reference as svc_normalize
        for val in ["PO-12345", "BOL 98765", "#99887", "00012345", ""]:
            assert svc_normalize(val) == normalize_reference(val), f"Mismatch for {val!r}"

    def test_reference_normalize_trace_matches(self):
        from services.reference_intelligence_service import normalize_reference as svc_normalize
        r1, t1 = svc_normalize("PO#00123", return_trace=True)
        r2, t2 = normalize_reference("PO#00123", return_trace=True)
        assert r1 == r2
        assert len(t1) == len(t2)


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
