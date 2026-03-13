"""
BC Integration Dashboard Tests

Tests the new BC Integration Dashboard endpoint at GET /api/gpi-integration/dashboard
which aggregates integration transactions (Sales Orders and Purchase Invoices) from
local document graph data.

Features tested:
- Dashboard endpoint returns valid JSON with counts and transactions
- Filtering by record_type (sales_order, purchase_invoice)
- Filtering by status (created, already_exists, failed)
- Pagination (limit, skip)
- Regression: status and preflight endpoints still work
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestBCIntegrationDashboard:
    """BC Integration Dashboard endpoint tests"""

    def test_dashboard_returns_valid_json_structure(self):
        """Dashboard returns proper JSON with counts and transactions arrays"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Validate structure
        assert "counts" in data, "Response missing 'counts' field"
        assert "transactions" in data, "Response missing 'transactions' field"
        assert "total" in data, "Response missing 'total' field"
        assert "limit" in data, "Response missing 'limit' field"
        assert "skip" in data, "Response missing 'skip' field"
        
        # Validate counts structure
        counts = data["counts"]
        assert "sales_order_created" in counts, "Counts missing 'sales_order_created'"
        assert "purchase_invoice_created" in counts, "Counts missing 'purchase_invoice_created'"
        assert "already_exists" in counts, "Counts missing 'already_exists'"
        assert "failed" in counts, "Counts missing 'failed'"
        assert "total" in counts, "Counts missing 'total'"
        
        # All counts should be integers >= 0
        for key, val in counts.items():
            assert isinstance(val, int) and val >= 0, f"Count '{key}' should be non-negative int"
        
        # Transactions should be a list
        assert isinstance(data["transactions"], list), "transactions should be a list"
        print(f"✓ Dashboard returns valid structure: counts={counts}, transactions_count={len(data['transactions'])}")

    def test_dashboard_filter_by_record_type_sales_order(self):
        """Dashboard filters by record_type=sales_order"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard?record_type=sales_order")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # All transactions should be Sales Order type
        for txn in data["transactions"]:
            assert txn["record_type"] == "Sales Order", f"Expected 'Sales Order', got '{txn['record_type']}'"
        
        print(f"✓ Sales order filter: {len(data['transactions'])} transactions")

    def test_dashboard_filter_by_record_type_purchase_invoice(self):
        """Dashboard filters by record_type=purchase_invoice"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard?record_type=purchase_invoice")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # All transactions should be Purchase Invoice type
        for txn in data["transactions"]:
            assert txn["record_type"] == "Purchase Invoice", f"Expected 'Purchase Invoice', got '{txn['record_type']}'"
        
        print(f"✓ Purchase invoice filter: {len(data['transactions'])} transactions")

    def test_dashboard_filter_by_status_created(self):
        """Dashboard filters by status=created"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard?status=created")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # All transactions should be created (success=True, status != already_exists)
        for txn in data["transactions"]:
            assert txn["success"] == True, f"Expected success=True for 'created' status"
            assert txn["status"] != "already_exists", f"Expected status != 'already_exists'"
        
        print(f"✓ Created filter: {len(data['transactions'])} transactions")

    def test_dashboard_filter_by_status_already_exists(self):
        """Dashboard filters by status=already_exists"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard?status=already_exists")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # All transactions should have status=already_exists
        for txn in data["transactions"]:
            assert txn["status"] == "already_exists", f"Expected status='already_exists', got '{txn['status']}'"
        
        print(f"✓ Already exists filter: {len(data['transactions'])} transactions")

    def test_dashboard_filter_by_status_failed(self):
        """Dashboard filters by status=failed"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard?status=failed")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # All transactions should be failed (success=False, status != already_exists)
        for txn in data["transactions"]:
            assert txn["success"] == False, f"Expected success=False for 'failed' status"
            assert txn["status"] != "already_exists", f"Status should not be 'already_exists'"
        
        print(f"✓ Failed filter: {len(data['transactions'])} transactions")

    def test_dashboard_pagination_limit(self):
        """Dashboard respects limit parameter"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard?limit=10")
        assert response.status_code == 200
        
        data = response.json()
        assert len(data["transactions"]) <= 10, f"Expected max 10 transactions, got {len(data['transactions'])}"
        assert data["limit"] == 10, f"Expected limit=10, got {data['limit']}"
        
        print(f"✓ Limit=10 pagination: {len(data['transactions'])} transactions returned")

    def test_dashboard_pagination_skip(self):
        """Dashboard respects skip parameter"""
        # First get all transactions
        response_all = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard?limit=100")
        assert response_all.status_code == 200
        all_data = response_all.json()
        
        # Skip first 5
        response_skip = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard?limit=100&skip=5")
        assert response_skip.status_code == 200
        skip_data = response_skip.json()
        
        assert skip_data["skip"] == 5, f"Expected skip=5, got {skip_data['skip']}"
        
        # If there were more than 5 transactions, skipped result should have fewer
        if all_data["total"] > 5:
            expected_count = min(100, all_data["total"] - 5)
            assert len(skip_data["transactions"]) == expected_count, f"Expected {expected_count} after skip, got {len(skip_data['transactions'])}"
        
        print(f"✓ Skip=5 pagination: total={all_data['total']}, after skip={len(skip_data['transactions'])}")

    def test_dashboard_transaction_structure(self):
        """Dashboard transaction records have correct fields"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard?limit=10")
        assert response.status_code == 200
        
        data = response.json()
        
        # If there are transactions, validate structure
        if data["transactions"]:
            txn = data["transactions"][0]
            required_fields = [
                "record_type", "source_document_id", "source_document_name",
                "bc_record_no", "bc_system_id", "idempotency_key", "transaction_id",
                "status", "success", "customer_no", "customer_name", "vendor_no",
                "vendor_name", "external_ref", "error_message", "created_at", "created_by"
            ]
            for field in required_fields:
                assert field in txn, f"Transaction missing field: {field}"
            
            print(f"✓ Transaction structure validated with all {len(required_fields)} required fields")
        else:
            print("✓ No transactions found (this is expected if no BC records created yet)")


class TestBCIntegrationRegressionEndpoints:
    """Regression tests for existing GPI Integration endpoints"""

    def test_status_endpoint_still_works(self):
        """GET /api/gpi-integration/status returns valid response"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Should have credential status info
        assert "has_credentials" in data or "credentials_configured" in data or "environment" in data, \
            "Status response should have credential/config info"
        
        print(f"✓ Status endpoint working: {data}")

    def test_preflight_endpoint_still_works(self):
        """POST /api/gpi-integration/sales-orders/preflight/{doc_id} returns expected response"""
        doc_id = "44b2e236-c1ab-4e0e-9c23-23f542d68a71"  # Known Sales_Order doc
        response = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        
        # Should return 200 (success) or 404 (doc not found)
        assert response.status_code in [200, 404], f"Expected 200 or 404, got {response.status_code}"
        
        if response.status_code == 200:
            data = response.json()
            assert "eligible" in data, "Preflight should have 'eligible' field"
            assert "ready" in data, "Preflight should have 'ready' field"
            assert "mapped_values" in data, "Preflight should have 'mapped_values' field"
            print(f"✓ Preflight endpoint working: eligible={data['eligible']}, ready={data['ready']}")
        else:
            print("✓ Preflight endpoint working (doc not found - expected if test doc doesn't exist)")


class TestBCIntegrationDashboardEdgeCases:
    """Edge case tests for dashboard"""

    def test_dashboard_combined_filters(self):
        """Dashboard handles combined record_type and status filters"""
        response = requests.get(
            f"{BASE_URL}/api/gpi-integration/dashboard?record_type=sales_order&status=created"
        )
        assert response.status_code == 200
        
        data = response.json()
        for txn in data["transactions"]:
            assert txn["record_type"] == "Sales Order"
            assert txn["success"] == True
            assert txn["status"] != "already_exists"
        
        print(f"✓ Combined filters (sales_order + created): {len(data['transactions'])} transactions")

    def test_dashboard_empty_filters(self):
        """Dashboard handles empty/no filters"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard")
        assert response.status_code == 200
        
        data = response.json()
        assert "counts" in data
        assert "transactions" in data
        
        print(f"✓ No filters: total={data['total']}")

    def test_dashboard_invalid_record_type_ignored(self):
        """Dashboard handles invalid record_type gracefully"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard?record_type=invalid_type")
        # Should still return 200 with empty or full results (not 400 error)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # With invalid filter, might return empty or all results
        assert "transactions" in data
        
        print(f"✓ Invalid record_type handled gracefully: {len(data['transactions'])} transactions")

    def test_dashboard_large_limit(self):
        """Dashboard handles large limit parameter"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard?limit=500")
        assert response.status_code == 200
        
        data = response.json()
        # Limit should be capped at 500 (per endpoint definition)
        assert data["limit"] <= 500
        
        print(f"✓ Large limit handled: limit={data['limit']}")

    def test_dashboard_zero_skip(self):
        """Dashboard handles skip=0 correctly"""
        response = requests.get(f"{BASE_URL}/api/gpi-integration/dashboard?skip=0")
        assert response.status_code == 200
        
        data = response.json()
        assert data["skip"] == 0
        
        print(f"✓ Skip=0 handled correctly")


# Run tests
if __name__ == "__main__":
    pytest.main([__file__, "-v"])
