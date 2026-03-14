"""
Test suite for GET /api/inventory-ledger/reorder-recommendations endpoint.
Tests reorder recommendation generation based on derived balances.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Hormel Foods workspace (has SHORT items for testing)
HORMEL_CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"
# Healthy Corp workspace (all healthy inventory)
HEALTHY_CUSTOMER_ID = "0be8d686-c173-4f8e-afb6-32a0676cd68d"


class TestReorderRecommendations:
    """Test GET /api/inventory-ledger/reorder-recommendations endpoint"""

    def test_recommendations_returns_200(self):
        """Basic endpoint availability test"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "recommendations" in data
        assert "total" in data
        print(f"✓ Endpoint returns 200 with {data['total']} recommendations")

    def test_recommendations_for_short_items(self):
        """Verify recommendations returned for SHORT items (available <= 0)"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Hormel Foods should have SHORT items
        assert data["total"] > 0, "Expected at least 1 recommendation for Hormel workspace"
        
        # Verify all recommendations are SHORT or have available <= 0
        for rec in data["recommendations"]:
            assert rec["status"] == "SHORT" or rec["available"] <= 0, \
                f"Expected SHORT status or available <= 0, got status={rec['status']}, available={rec['available']}"
        
        print(f"✓ All {data['total']} recommendations are for SHORT items")

    def test_recommended_qty_formula(self):
        """Verify recommended_qty = abs(available) + 10 (safety buffer)"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        for rec in data["recommendations"]:
            available = rec["available"]
            expected_qty = abs(available) + 10 if available <= 0 else 10
            # Round for floating point comparison
            assert round(rec["recommended_qty"], 2) == round(expected_qty, 2), \
                f"Item {rec['item']}: expected recommended_qty={expected_qty}, got {rec['recommended_qty']}"
        
        print(f"✓ Recommended qty formula verified for all {len(data['recommendations'])} items")

    def test_sorted_by_available_ascending(self):
        """Verify recommendations sorted by available ascending (most critical first)"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        recs = data["recommendations"]
        
        if len(recs) > 1:
            for i in range(len(recs) - 1):
                assert recs[i]["available"] <= recs[i+1]["available"], \
                    f"Not sorted: item {recs[i]['item']} available={recs[i]['available']} " \
                    f"should be <= item {recs[i+1]['item']} available={recs[i+1]['available']}"
        
        print(f"✓ Recommendations sorted by available ascending (most critical first)")

    def test_no_recommendations_for_healthy_inventory(self):
        """Verify no recommendations when all inventory is healthy (available > 0)"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
            params={"customer_id": HEALTHY_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        # Healthy Corp has no SHORT items (all healthy)
        assert data["total"] == 0, f"Expected 0 recommendations for healthy inventory, got {data['total']}"
        assert len(data["recommendations"]) == 0
        
        print("✓ No recommendations for workspace with healthy inventory")

    def test_item_filter_works(self):
        """Verify item filter narrows down recommendations"""
        # First get all recommendations
        all_response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert all_response.status_code == 200
        all_data = all_response.json()
        
        if all_data["total"] > 0:
            # Filter by first item
            test_item = all_data["recommendations"][0]["item"]
            filtered_response = requests.get(
                f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
                params={"customer_id": HORMEL_CUSTOMER_ID, "item": test_item}
            )
            assert filtered_response.status_code == 200
            filtered_data = filtered_response.json()
            
            # Should return only the filtered item or subset
            assert filtered_data["total"] <= all_data["total"]
            for rec in filtered_data["recommendations"]:
                assert rec["item"] == test_item, f"Expected item={test_item}, got {rec['item']}"
            
            print(f"✓ Item filter works: '{test_item}' returned {filtered_data['total']} recommendations")
        else:
            pytest.skip("No recommendations to filter")

    def test_recommendation_response_structure(self):
        """Verify response structure includes all required fields"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/reorder-recommendations",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200
        data = response.json()
        
        required_fields = [
            "item", "item_description", "warehouse", "ownership_type",
            "on_hand", "incoming", "committed", "available",
            "unit_of_measure", "status", "recommended_qty"
        ]
        
        for rec in data["recommendations"]:
            for field in required_fields:
                assert field in rec, f"Missing required field: {field}"
        
        print(f"✓ All {len(required_fields)} required fields present in response")

    def test_missing_customer_id_returns_422(self):
        """Verify missing customer_id returns validation error"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/reorder-recommendations")
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        print("✓ Missing customer_id returns 422 validation error")


class TestRegressionEndpoints:
    """Regression tests for existing inventory ledger endpoints"""

    def test_csv_export_still_works(self):
        """REGRESSION: GET /api/inventory-ledger/export still works"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/export",
            params={"customer_id": HORMEL_CUSTOMER_ID}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        assert "text/csv" in response.headers.get("content-type", "")
        print("✓ REGRESSION: CSV export endpoint works")

    def test_manual_movement_entry_still_works(self):
        """REGRESSION: POST /api/inventory-ledger/movements still works"""
        import uuid
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/movements",
            json={
                "customer_id": HORMEL_CUSTOMER_ID,
                "movement_type": "correction",
                "item": f"TEST-REORDER-REG-{uuid.uuid4().hex[:6]}",
                "qty": 1,
                "idempotency_key": f"test-reorder-reg-{uuid.uuid4().hex}"
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data.get("success") is True
        print("✓ REGRESSION: Manual movement entry works")

    def test_history_endpoint_still_works(self):
        """REGRESSION: GET /api/inventory-ledger/history still works"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/history",
            params={"customer_id": HORMEL_CUSTOMER_ID, "limit": 10}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert "movements" in data
        print(f"✓ REGRESSION: History endpoint works ({data.get('total', 0)} total movements)")

    def test_reconcile_sales_order_still_works(self):
        """REGRESSION: POST /api/inventory-ledger/reconcile-sales-order responds correctly"""
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order",
            json={
                "sales_order_id": "SO-TEST-NONEXISTENT",
                "lines": [],
                "cancelled": False
            }
        )
        # Returns 422 when no existing order_commitment found (expected validation behavior)
        assert response.status_code == 422, f"Expected 422 for non-existent SO, got {response.status_code}: {response.text}"
        assert "No order_commitment found" in response.text
        print("✓ REGRESSION: Reconcile sales order endpoint responds correctly (422 for no commitments)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
