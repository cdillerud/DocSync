"""
API tests for Vendor Resolution Observability + Negative Feedback Loop.

Tests:
  1. GET /api/vendor-resolution/metrics endpoint structure and response
  2. GET /api/vendor-resolution/rejections endpoint structure and response
  3. Verification that existing endpoints still work (non-regression)
"""

import os
import pytest
import requests

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestVendorResolutionMetricsEndpoint:
    """Test GET /api/vendor-resolution/metrics."""

    def test_metrics_returns_200(self):
        """Endpoint should return 200 OK."""
        response = requests.get(f"{BASE_URL}/api/vendor-resolution/metrics")
        assert response.status_code == 200

    def test_metrics_response_structure(self):
        """Response should have all required fields."""
        response = requests.get(f"{BASE_URL}/api/vendor-resolution/metrics")
        data = response.json()

        # Core counts
        assert "total_documents" in data
        assert "resolved_count" in data
        assert "unresolved_count" in data
        assert "ambiguous_count" in data
        assert "needs_review_count" in data
        assert "resolution_rate" in data

        # Method breakdown
        assert "by_method" in data
        assert isinstance(data["by_method"], dict)

        # Fuzzy score buckets
        assert "fuzzy_score_buckets" in data
        assert isinstance(data["fuzzy_score_buckets"], dict)
        # Expected buckets
        buckets = data["fuzzy_score_buckets"]
        assert "90-94" in buckets
        assert "95-97" in buckets
        assert "98-100" in buckets

        # Top unresolved/corrected
        assert "top_unresolved" in data
        assert isinstance(data["top_unresolved"], list)
        assert "top_corrected" in data
        assert isinstance(data["top_corrected"], list)

        # Rejection stats
        assert "total_rejections" in data
        assert isinstance(data["total_rejections"], int)

    def test_metrics_values_are_numeric(self):
        """Count fields should be integers, rate should be numeric."""
        response = requests.get(f"{BASE_URL}/api/vendor-resolution/metrics")
        data = response.json()

        assert isinstance(data["total_documents"], int)
        assert isinstance(data["resolved_count"], int)
        assert isinstance(data["unresolved_count"], int)
        assert isinstance(data["ambiguous_count"], int)
        assert isinstance(data["needs_review_count"], int)
        assert isinstance(data["resolution_rate"], (int, float))
        assert isinstance(data["total_rejections"], int)


class TestVendorResolutionRejectionsEndpoint:
    """Test GET /api/vendor-resolution/rejections."""

    def test_rejections_returns_200(self):
        """Endpoint should return 200 OK."""
        response = requests.get(f"{BASE_URL}/api/vendor-resolution/rejections")
        assert response.status_code == 200

    def test_rejections_response_structure(self):
        """Response should have rejections array and count."""
        response = requests.get(f"{BASE_URL}/api/vendor-resolution/rejections")
        data = response.json()

        assert "rejections" in data
        assert isinstance(data["rejections"], list)
        assert "count" in data
        assert isinstance(data["count"], int)

    def test_rejections_limit_parameter(self):
        """Should accept limit parameter."""
        response = requests.get(f"{BASE_URL}/api/vendor-resolution/rejections?limit=5")
        assert response.status_code == 200
        data = response.json()
        assert data["count"] <= 5

    def test_rejections_skip_parameter(self):
        """Should accept skip parameter."""
        response = requests.get(f"{BASE_URL}/api/vendor-resolution/rejections?skip=0")
        assert response.status_code == 200


class TestExistingEndpointsStillWork:
    """Verify no breaking changes to existing endpoints."""

    def test_dashboard_stats_still_works(self):
        """GET /api/dashboard/stats should still work."""
        response = requests.get(f"{BASE_URL}/api/dashboard/stats")
        assert response.status_code == 200
        data = response.json()
        assert "total_documents" in data

    def test_aliases_metrics_still_works(self):
        """GET /api/aliases/metrics should still work."""
        response = requests.get(f"{BASE_URL}/api/aliases/metrics")
        assert response.status_code == 200
        data = response.json()
        assert "total_aliases" in data

    def test_health_endpoint_works(self):
        """GET /api/health should return healthy."""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data["status"] == "healthy"


class TestVendorResolutionStatusLogic:
    """Verify the resolution status constants/logic are exposed correctly."""

    def test_no_resolution_data_count(self):
        """no_resolution_data should count docs without vendor_resolution field."""
        response = requests.get(f"{BASE_URL}/api/vendor-resolution/metrics")
        data = response.json()

        # no_resolution_data = total - resolved - unresolved - ambiguous - needs_review
        expected_no_data = (
            data["total_documents"]
            - data["resolved_count"]
            - data["unresolved_count"]
            - data["ambiguous_count"]
            - data["needs_review_count"]
        )
        assert data.get("no_resolution_data", expected_no_data) >= 0
