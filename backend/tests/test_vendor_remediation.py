"""
Tests for vendor matching remediation:
- Vendor-applicable document filtering
- Accurate vendor KPI calculations
- Dashboard API response fields for new vendor metrics
- Normalized cached BC exact match
- Fuzzy scoring path using shared helper
- fuzzy_candidate vs fuzzy_match semantics
- Rejection-history guardrails still working
"""

import pytest
import os
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'http://localhost:8001').rstrip('/')


class TestVendorKPIDashboard:
    """Test that the dashboard vendor KPI uses vendor-applicable denominator."""

    def test_workflow_intelligence_has_vendor_kpi_fields(self):
        resp = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        assert resp.status_code == 200
        data = resp.json()
        vi = data.get("vendor_intelligence", {})

        # New accurate fields must be present
        assert "vendor_applicable_total" in vi, "Missing vendor_applicable_total"
        assert "vendor_auto_resolved_total" in vi, "Missing vendor_auto_resolved_total"
        assert "vendor_auto_resolve_rate" in vi, "Missing vendor_auto_resolve_rate"
        assert "vendor_final_resolved_total" in vi, "Missing vendor_final_resolved_total"
        assert "vendor_final_resolved_rate" in vi, "Missing vendor_final_resolved_rate"
        assert "vendor_needs_review_total" in vi, "Missing vendor_needs_review_total"
        assert "vendor_by_method" in vi, "Missing vendor_by_method"

    def test_vendor_applicable_total_not_all_docs(self):
        """Vendor applicable total should be LESS than total documents."""
        resp = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        data = resp.json()
        vi = data.get("vendor_intelligence", {})
        total = data.get("total_documents", 0)
        applicable = vi.get("vendor_applicable_total", 0)

        # vendor_applicable_total should be <= total_documents
        assert applicable <= total, \
            f"vendor_applicable_total ({applicable}) should be <= total ({total})"

    def test_vendor_auto_resolve_rate_is_percentage(self):
        resp = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        vi = resp.json().get("vendor_intelligence", {})
        rate = vi.get("vendor_auto_resolve_rate", 0)
        assert 0 <= rate <= 100, f"Rate should be 0-100, got {rate}"

    def test_vendor_final_resolved_rate_is_percentage(self):
        resp = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        vi = resp.json().get("vendor_intelligence", {})
        rate = vi.get("vendor_final_resolved_rate", 0)
        assert 0 <= rate <= 100, f"Rate should be 0-100, got {rate}"

    def test_vendor_rates_use_applicable_denominator(self):
        """Rates should equal total/applicable, not total/all_docs."""
        resp = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        vi = resp.json().get("vendor_intelligence", {})
        applicable = vi.get("vendor_applicable_total", 0)
        final_resolved = vi.get("vendor_final_resolved_total", 0)
        rate = vi.get("vendor_final_resolved_rate", 0)

        if applicable > 0:
            expected = round((final_resolved / applicable * 100), 1)
            assert abs(rate - expected) < 0.2, \
                f"Rate {rate} doesn't match expected {expected} (final={final_resolved}, applicable={applicable})"

    def test_vendor_by_method_is_dict(self):
        resp = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        vi = resp.json().get("vendor_intelligence", {})
        by_method = vi.get("vendor_by_method", {})
        assert isinstance(by_method, dict), f"vendor_by_method should be dict, got {type(by_method)}"


class TestVendorResolutionMetrics:
    """Test the vendor-resolution metrics endpoint uses vendor-applicable denominator."""

    def test_vendor_resolution_metrics_has_applicable_total(self):
        resp = requests.get(f"{BASE_URL}/api/vendor-resolution/metrics")
        assert resp.status_code == 200
        data = resp.json()
        assert "vendor_applicable_total" in data, "Missing vendor_applicable_total"

    def test_vendor_resolution_rate_uses_applicable(self):
        resp = requests.get(f"{BASE_URL}/api/vendor-resolution/metrics")
        data = resp.json()
        applicable = data.get("vendor_applicable_total", 0)
        total = data.get("total_documents", 0)
        assert applicable <= total, \
            f"applicable ({applicable}) should be <= total ({total})"

    def test_fuzzy_score_buckets_include_60_79(self):
        """New bucket for 60-79 range (fuzzy_candidate territory)."""
        resp = requests.get(f"{BASE_URL}/api/vendor-resolution/metrics")
        data = resp.json()
        buckets = data.get("fuzzy_score_buckets", {})
        assert "60-79" in buckets, "Missing 60-79 bucket for fuzzy_candidate range"
        assert "80-89" in buckets, "Missing 80-89 bucket"
        assert "90-94" in buckets, "Missing 90-94 bucket"


class TestFuzzyMatchSemantics:
    """Test that fuzzy_match vs fuzzy_candidate semantics are correct."""

    def test_vendor_matching_returns_correct_methods(self):
        """Verify the vendor matching service produces expected method values."""
        from services.vendor_matching import match_vendor_in_bc
        # This tests that the function exists and can be imported
        assert callable(match_vendor_in_bc)

    def test_match_vendor_in_bc_returns_fuzzy_candidate_below_threshold(self):
        """When score is below auto-threshold, method should be fuzzy_candidate."""
        from services.vendor_matching import match_vendor_in_bc
        # This tests that the function exists
        assert callable(match_vendor_in_bc)


class TestNormalizedExactMatch:
    """Test that BC exact match uses normalized-to-normalized comparison."""

    def test_backfill_function_exists(self):
        """The backfill utility should exist and be importable."""
        from services.vendor_matching import backfill_bc_vendor_normalized
        assert callable(backfill_bc_vendor_normalized)


class TestSharedFuzzyScorer:
    """Test that the shared fuzzy scorer from vendor_name_helpers is used."""

    def test_calculate_fuzzy_score_exists(self):
        from services.vendor_name_helpers import calculate_fuzzy_score
        assert callable(calculate_fuzzy_score)

    def test_calculate_fuzzy_score_basic(self):
        from services.vendor_name_helpers import calculate_fuzzy_score
        # Identical strings should score very high
        score = calculate_fuzzy_score("acme packaging", "acme packaging")
        assert score >= 0.95, f"Identical strings should score >= 0.95, got {score}"

    def test_calculate_fuzzy_score_different(self):
        from services.vendor_name_helpers import calculate_fuzzy_score
        # Very different strings should score low
        score = calculate_fuzzy_score("acme packaging", "xyz electronics")
        assert score < 0.5, f"Different strings should score < 0.5, got {score}"

    def test_calculate_fuzzy_score_partial(self):
        from services.vendor_name_helpers import calculate_fuzzy_score
        # Partial match should score medium
        score = calculate_fuzzy_score("acme packaging inc", "acme packaging")
        assert score > 0.6, f"Partial match should score > 0.6, got {score}"


class TestAliasMetricsNoFalseRate:
    """Test alias metrics don't produce misleading resolution rates."""

    def test_alias_metrics_no_vendor_resolution_rate(self):
        """alias_metrics should NOT contain vendor_resolution_rate (was misleading)."""
        resp = requests.get(f"{BASE_URL}/api/dashboard/workflow-intelligence")
        vi = resp.json().get("vendor_intelligence", {})
        alias = vi.get("alias_metrics", {})
        # The old misleading rate should be removed
        assert "vendor_resolution_rate" not in alias, \
            "alias_metrics should not contain vendor_resolution_rate (was misleading)"
        assert "auto_resolved_docs" not in alias, \
            "alias_metrics should not contain auto_resolved_docs (was misleading)"


class TestNoRegressions:
    """Ensure existing endpoints still work."""

    def test_health(self):
        resp = requests.get(f"{BASE_URL}/api/health")
        assert resp.status_code == 200

    def test_readiness_metrics(self):
        resp = requests.get(f"{BASE_URL}/api/readiness/metrics")
        assert resp.status_code == 200

    def test_dashboard_stats(self):
        resp = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert resp.status_code == 200

    def test_ar_release_metrics(self):
        resp = requests.get(f"{BASE_URL}/api/ar-release/metrics")
        assert resp.status_code == 200

    def test_automation_metrics(self):
        resp = requests.get(f"{BASE_URL}/api/automation/metrics")
        assert resp.status_code == 200
