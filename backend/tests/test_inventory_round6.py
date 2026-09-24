"""
Regression: GET /api/inventory-ledger/customers.

2026-09-24: this file used to be "Inventory Round 6 Tests" (Iteration 209)
-- health-summary schema/sorting/per-customer rollup, XLS activity counts,
manual mapping promotion, filename customer suggestion, and iter-208
regression, almost all exercised via the removed /inventory-xls/* router
and/or the removed /inventory-ledger/health-summary endpoint (Inventory
Health + Inventory Imports nav-item removal). Only one method in the old
TestRegressionIter208 class tested something else still live -- kept below.
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


class TestRegressionIter208:
    """Regression tests for iter 208 endpoints."""

    def test_customers_endpoint_works(self, api_client):
        """GET /api/inventory-ledger/customers should return list."""
        resp = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert resp.status_code == 200, f"Customers list failed: {resp.status_code}"
        data = resp.json()
        assert isinstance(data, list), "Response should be a list"
        print(f"\u2713 Customers endpoint works: {len(data)} customers")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
