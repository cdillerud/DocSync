"""
Dashboard Summary Endpoint Tests - Iteration 65

Tests the new GET /api/inventory-ledger/dashboard-summary endpoint that returns
inventory health metrics: total_items, items_ok, items_low, items_short,
total_on_hand, total_incoming, total_committed, total_available, total_reorder_recommendations.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL').rstrip('/')
HORMEL_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"  # Hormel Foods customer


class TestDashboardSummary:
    """Tests for GET /api/inventory-ledger/dashboard-summary endpoint"""

    def test_dashboard_summary_returns_all_9_fields(self):
        """Test that dashboard-summary returns all required fields"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary", 
                               params={"customer_id": HORMEL_ID})
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        required_fields = [
            "total_items", "items_ok", "items_low", "items_short",
            "total_on_hand", "total_incoming", "total_committed", 
            "total_available", "total_reorder_recommendations"
        ]
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
            assert isinstance(data[field], (int, float)), f"Field {field} should be numeric"

    def test_dashboard_summary_status_counts_sum(self):
        """Test that items_ok + items_low + items_short equals total balance buckets"""
        # Get dashboard summary
        summary_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary", 
                                   params={"customer_id": HORMEL_ID})
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        
        # Get balances to verify count
        balances_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_ID}/balances")
        assert balances_resp.status_code == 200
        balance_count = balances_resp.json()["count"]
        
        # Status counts should sum to total balance rows (not unique items)
        status_sum = summary["items_ok"] + summary["items_low"] + summary["items_short"]
        assert status_sum == balance_count, f"Status sum {status_sum} != balance count {balance_count}"

    def test_dashboard_summary_reorder_count_matches_endpoint(self):
        """Test that total_reorder_recommendations matches /reorder-recommendations total"""
        # Get dashboard summary
        summary_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary", 
                                   params={"customer_id": HORMEL_ID})
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        
        # Get reorder recommendations
        reorder_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
                                   params={"customer_id": HORMEL_ID})
        assert reorder_resp.status_code == 200
        reorder = reorder_resp.json()
        
        assert summary["total_reorder_recommendations"] == reorder["total"], \
            f"Dashboard reorder count {summary['total_reorder_recommendations']} != reorder endpoint total {reorder['total']}"

    def test_dashboard_summary_empty_customer_returns_zeros(self):
        """Test that nonexistent/empty customer returns all zeros"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary", 
                               params={"customer_id": "nonexistent-customer-id-12345"})
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data["total_items"] == 0
        assert data["items_ok"] == 0
        assert data["items_low"] == 0
        assert data["items_short"] == 0
        assert data["total_on_hand"] == 0
        assert data["total_incoming"] == 0
        assert data["total_committed"] == 0
        assert data["total_available"] == 0
        assert data["total_reorder_recommendations"] == 0

    def test_dashboard_summary_item_filter_works(self):
        """Test that item filter parameter works"""
        # Get summary without filter
        full_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary", 
                                params={"customer_id": HORMEL_ID})
        assert full_resp.status_code == 200
        full_data = full_resp.json()
        
        # Get summary with filter for nonexistent item
        filtered_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary", 
                                    params={"customer_id": HORMEL_ID, "item": "NONEXISTENT-ITEM-XYZ"})
        assert filtered_resp.status_code == 200
        filtered_data = filtered_resp.json()
        
        # Filtered with no matches should return zeros
        assert filtered_data["total_items"] == 0
        assert filtered_data["items_ok"] == 0

    def test_dashboard_summary_missing_customer_id_returns_422(self):
        """Test that missing customer_id returns 422 validation error"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary")
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"

    def test_dashboard_summary_status_logic_matches_balances(self):
        """Test that is_short and is_low flags in balances match dashboard counts"""
        # Get balances
        balances_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_ID}/balances")
        assert balances_resp.status_code == 200
        balances = balances_resp.json()["balances"]
        
        # Count statuses from balances
        ok_count = sum(1 for b in balances if not b.get("is_short") and not b.get("is_low"))
        low_count = sum(1 for b in balances if b.get("is_low") and not b.get("is_short"))
        short_count = sum(1 for b in balances if b.get("is_short"))
        
        # Get dashboard summary
        summary_resp = requests.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary", 
                                   params={"customer_id": HORMEL_ID})
        assert summary_resp.status_code == 200
        summary = summary_resp.json()
        
        assert summary["items_ok"] == ok_count, f"Dashboard OK {summary['items_ok']} != counted {ok_count}"
        assert summary["items_low"] == low_count, f"Dashboard LOW {summary['items_low']} != counted {low_count}"
        assert summary["items_short"] == short_count, f"Dashboard SHORT {summary['items_short']} != counted {short_count}"


class TestDashboardSummaryRegression:
    """Regression tests to ensure existing endpoints still work"""

    def test_balances_endpoint_still_works(self):
        """Regression: Balances endpoint should still work"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_ID}/balances")
        assert response.status_code == 200
        data = response.json()
        assert "balances" in data
        assert "count" in data

    def test_movements_endpoint_still_works(self):
        """Regression: Movements endpoint should still work"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_ID}/movements")
        assert response.status_code == 200
        data = response.json()
        assert "movements" in data

    def test_incoming_endpoint_still_works(self):
        """Regression: Incoming supply endpoint should still work"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_ID}/incoming")
        assert response.status_code == 200
        # Returns a list

    def test_reorder_recommendations_still_works(self):
        """Regression: Reorder recommendations endpoint should still work"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
                               params={"customer_id": HORMEL_ID})
        assert response.status_code == 200
        data = response.json()
        assert "recommendations" in data
        assert "total" in data

    def test_item_settings_still_works(self):
        """Regression: Item settings endpoint should still work"""
        response = requests.get(f"{BASE_URL}/api/inventory-items/settings",
                               params={"customer_id": HORMEL_ID})
        assert response.status_code == 200
        data = response.json()
        assert "settings" in data

    def test_csv_export_still_works(self):
        """Regression: CSV export endpoint should still work"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/export",
                               params={"customer_id": HORMEL_ID})
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("content-type", "")
