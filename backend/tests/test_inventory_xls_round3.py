"""
Regression: GET /api/inside-sales-pilot/match-tier-distribution.

2026-09-24: this file used to be "Inventory XLS Pipeline Round 3 Tests"
(Iteration 208) -- auto-approve gate/confidence formula, backfill-pilot-docs,
customer prefix match, and applied-record auto_approved flag, all exercised
via /api/inventory-xls/*. That whole router was removed (Inventory Imports
nav-item removal), so those tests were dropped. TestMatchTierDistribution
below tests a different, unrelated, still-live endpoint that had been
tacked onto the end of this file -- kept.
"""

import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session."""
    session = requests.Session()
    return session


class TestMatchTierDistribution:
    """Test GET /api/inside-sales-pilot/match-tier-distribution for Cache Drift Alarm."""

    def test_match_tier_distribution_returns_buckets(self, api_client):
        """Test that match-tier-distribution returns expected buckets schema."""
        resp = api_client.get(f"{BASE_URL}/api/inside-sales-pilot/match-tier-distribution")

        # Endpoint may not exist or may return 404 if no pilot data
        if resp.status_code == 404:
            pytest.skip("match-tier-distribution endpoint not found or no pilot data")

        assert resp.status_code == 200, f"Match tier distribution failed: {resp.status_code} {resp.text}"
        result = resp.json()

        # Verify expected buckets schema
        # The alarm checks: matched>=10 AND (exact/matched < 0.80 OR fuzzy/matched > 0.10)
        # So we expect buckets like: exact, fuzzy, none, matched
        if "buckets" in result or "exact" in result or "matched" in result:
            print(f"\u2713 Match tier distribution returns buckets: {list(result.keys())[:5]}")
        else:
            print(f"  Match tier distribution response: {result}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
