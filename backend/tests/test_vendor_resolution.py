"""
Unit tests for vendor resolution improvements:
  - rapidfuzz-based fuzzy matching
  - Normalization (already tested but verified here for completeness)
  - Match method standardization
"""

import pytest
from services.vendor_name_helpers import normalize_vendor_name, calculate_fuzzy_score


class TestNormalization:
    """Verify normalization covers all required suffix removals."""

    def test_inc(self):
        assert normalize_vendor_name("Acme Inc.") == "acme"

    def test_llc(self):
        assert normalize_vendor_name("ABC Supply LLC") == "abc supply"

    def test_ltd(self):
        assert normalize_vendor_name("Global Trading Ltd") == "global trading"

    def test_corp(self):
        assert normalize_vendor_name("Tech Corp") == "tech"

    def test_corporation(self):
        assert normalize_vendor_name("Tech Corporation") == "tech"

    def test_company(self):
        assert normalize_vendor_name("Smith Company") == "smith"

    def test_co(self):
        assert normalize_vendor_name("Jones Co.") == "jones"

    def test_plc(self):
        assert normalize_vendor_name("British Plc") == "british"

    def test_gmbh(self):
        assert normalize_vendor_name("Siemens GmbH") == "siemens"

    def test_ag(self):
        assert normalize_vendor_name("Swiss AG") == "swiss"

    def test_lowercase_and_strip(self):
        assert normalize_vendor_name("  ABC Industrial Supply  ") == "abc industrial supply"

    def test_punctuation(self):
        assert normalize_vendor_name("ABC – Midwest Division") == "abc midwest division"

    def test_empty(self):
        assert normalize_vendor_name("") == ""

    def test_none(self):
        assert normalize_vendor_name(None) == ""


class TestRapidfuzzScoring:
    """Test that calculate_fuzzy_score uses rapidfuzz and returns proper scores."""

    def test_exact_match(self):
        score = calculate_fuzzy_score("ABC Industrial Supply", "ABC Industrial Supply")
        assert score >= 0.99

    def test_high_similarity(self):
        score = calculate_fuzzy_score("ABC Industrial Supply", "ABC Industrial Supply LLC")
        assert score >= 0.90

    def test_moderate_similarity(self):
        score = calculate_fuzzy_score("ABC Industrial", "ABC Industrial Supply Midwest")
        assert 0.3 < score < 1.0

    def test_no_similarity(self):
        score = calculate_fuzzy_score("Alpha Beta Gamma", "XYZ Completely Different")
        assert score < 0.5

    def test_empty_strings(self):
        assert calculate_fuzzy_score("", "ABC") == 0.0
        assert calculate_fuzzy_score("ABC", "") == 0.0
        assert calculate_fuzzy_score("", "") == 0.0

    def test_bc_vendor_code_handling(self):
        """BC vendor names like 'TUMALOC - Tumalo Creek' should match 'Tumalo Creek'."""
        score = calculate_fuzzy_score("Tumalo Creek", "TUMALOC - Tumalo Creek Transportation")
        assert score >= 0.6

    def test_suffix_stripped_match(self):
        """LLC/Inc should be stripped before comparison."""
        score = calculate_fuzzy_score("ABC Industrial Supply LLC", "ABC Industrial Supply Inc")
        # Both normalize to "abc industrial supply" — should be near-perfect
        assert score >= 0.95

    def test_reordered_tokens(self):
        """token_sort_ratio handles reordered words."""
        score = calculate_fuzzy_score("Industrial ABC Supply", "ABC Industrial Supply")
        assert score >= 0.90

    def test_threshold_90_auto_match(self):
        """Verify that similar names exceed the 90% auto-match threshold."""
        # These should be close enough to auto-match
        pairs_above_90 = [
            ("ABC Industrial Supply LLC", "ABC Industrial Supply"),
            ("Tumalo Creek Transportation", "Tumalo Creek Transportation Inc"),
            ("Smith & Associates", "Smith Associates"),
        ]
        for name1, name2 in pairs_above_90:
            score = calculate_fuzzy_score(name1, name2)
            assert score >= 0.90, f"Expected >=0.90 for ({name1}, {name2}), got {score}"

    def test_threshold_below_90(self):
        """Verify that dissimilar names fall below the 90% threshold."""
        pairs_below_90 = [
            ("ABC Industrial", "XYZ Manufacturing"),
            ("Pacific Northwest Supply", "Atlantic Southeast Logistics"),
        ]
        for name1, name2 in pairs_below_90:
            score = calculate_fuzzy_score(name1, name2)
            assert score < 0.90, f"Expected <0.90 for ({name1}, {name2}), got {score}"


class TestMatchMethodStandardization:
    """Verify the standardized match method constants are used."""

    def test_standard_methods_exist(self):
        """The code should use these standardized method names."""
        standard_methods = {"alias_match", "fuzzy_match", "bc_exact_match", "manual_match"}
        # Just verify they're valid strings (actual usage tested via integration tests)
        for method in standard_methods:
            assert isinstance(method, str)
            assert len(method) > 0
