"""
Tests for GET /api/inventory-ledger/export endpoint (CSV export feature).
Tests CSV format, headers, status values, filtering, and regression checks.
"""
import pytest
import requests
import os
import uuid
import csv
import io

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test customer workspace - Hormel Foods has data
TEST_CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"


class TestInventoryBalanceExport:
    """Tests for GET /api/inventory-ledger/export endpoint"""
    
    def test_export_returns_200_status(self):
        """Export endpoint returns 200 for valid customer_id"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/export", 
                               params={"customer_id": TEST_CUSTOMER_ID})
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("✓ Export returns 200 status")
    
    def test_export_content_type_is_csv(self):
        """Content-Type header is text/csv"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/export",
                               params={"customer_id": TEST_CUSTOMER_ID})
        content_type = response.headers.get('Content-Type', '')
        assert 'text/csv' in content_type, f"Expected text/csv, got {content_type}"
        print(f"✓ Content-Type is {content_type}")
    
    def test_export_content_disposition_attachment(self):
        """Content-Disposition header has attachment and filename"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/export",
                               params={"customer_id": TEST_CUSTOMER_ID})
        disposition = response.headers.get('Content-Disposition', '')
        assert 'attachment' in disposition, f"Expected 'attachment' in Content-Disposition, got {disposition}"
        assert 'filename=' in disposition, f"Expected 'filename=' in Content-Disposition, got {disposition}"
        print(f"✓ Content-Disposition: {disposition}")
    
    def test_export_csv_has_correct_headers(self):
        """CSV has required 10 columns in correct order"""
        expected_headers = [
            "item", "item_description", "warehouse", "ownership_type",
            "on_hand", "incoming", "committed", "available",
            "unit_of_measure", "status"
        ]
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/export",
                               params={"customer_id": TEST_CUSTOMER_ID})
        reader = csv.reader(io.StringIO(response.text))
        header_row = next(reader)
        assert header_row == expected_headers, f"Headers mismatch.\nExpected: {expected_headers}\nGot: {header_row}"
        print(f"✓ CSV headers correct: {header_row}")
    
    def test_export_has_data_rows(self):
        """Export includes data rows (Hormel Foods has 9+ balances)"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/export",
                               params={"customer_id": TEST_CUSTOMER_ID})
        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        assert len(rows) >= 1, f"Expected at least 1 data row, got {len(rows)}"
        print(f"✓ Export has {len(rows)} data rows")
    
    def test_export_status_values_valid(self):
        """Status column contains only OK, LOW, or SHORT"""
        valid_statuses = {"OK", "LOW", "SHORT"}
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/export",
                               params={"customer_id": TEST_CUSTOMER_ID})
        reader = csv.DictReader(io.StringIO(response.text))
        for row in reader:
            status = row.get('status', '')
            assert status in valid_statuses, f"Invalid status '{status}' found. Valid: {valid_statuses}"
        print("✓ All status values are valid (OK/LOW/SHORT)")
    
    def test_export_status_short_for_negative_available(self):
        """Items with is_short=True have status=SHORT"""
        # Get balances to find a SHORT item
        bal_response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{TEST_CUSTOMER_ID}/balances")
        balances = bal_response.json().get('balances', [])
        short_items = [b['item'] for b in balances if b.get('is_short')]
        
        if not short_items:
            pytest.skip("No SHORT items in test data to verify")
        
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/export",
                               params={"customer_id": TEST_CUSTOMER_ID})
        reader = csv.DictReader(io.StringIO(response.text))
        rows = {row['item']: row for row in reader}
        
        for item in short_items[:2]:  # Check first 2
            if item in rows:
                assert rows[item]['status'] == 'SHORT', f"Item {item} should have status=SHORT"
        print(f"✓ SHORT items correctly marked: {short_items[:2]}")
    
    def test_export_item_filter_works(self):
        """Item filter returns only matching items"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/export",
                               params={"customer_id": TEST_CUSTOMER_ID, "item": "SPAM-12OZ"})
        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        
        # Should return SPAM-12OZ rows only (2 warehouses)
        assert len(rows) >= 1, "Item filter should return matching rows"
        for row in rows:
            assert row['item'] == "SPAM-12OZ", f"Filter failed: got item={row['item']}"
        print(f"✓ Item filter works: {len(rows)} rows for SPAM-12OZ")
    
    def test_export_empty_result_returns_headers_only(self):
        """Non-existent item filter returns CSV with headers only"""
        nonexistent_item = f"NONEXISTENT_{uuid.uuid4().hex[:8]}"
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/export",
                               params={"customer_id": TEST_CUSTOMER_ID, "item": nonexistent_item})
        
        # Should still be 200
        assert response.status_code == 200
        
        reader = csv.DictReader(io.StringIO(response.text))
        rows = list(reader)
        assert len(rows) == 0, f"Expected 0 data rows for non-existent item, got {len(rows)}"
        print("✓ Empty result returns headers only (0 data rows)")
    
    def test_export_values_match_balances_api(self):
        """Exported values match GET /customers/{id}/balances API"""
        # Get from balances API
        bal_response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{TEST_CUSTOMER_ID}/balances")
        api_balances = bal_response.json().get('balances', [])
        
        # Get from export
        exp_response = requests.get(f"{BASE_URL}/api/inventory-ledger/export",
                                   params={"customer_id": TEST_CUSTOMER_ID})
        reader = csv.DictReader(io.StringIO(exp_response.text))
        export_rows = list(reader)
        
        # Count should match
        assert len(export_rows) == len(api_balances), f"Row count mismatch: API={len(api_balances)}, Export={len(export_rows)}"
        
        # Spot check first item
        if api_balances:
            api_item = api_balances[0]
            export_item = next((r for r in export_rows if r['item'] == api_item['item'] and r['warehouse'] == api_item['warehouse']), None)
            if export_item:
                assert float(export_item['on_hand']) == api_item['on_hand'], "on_hand mismatch"
                assert float(export_item['available']) == api_item['available'], "available mismatch"
        print(f"✓ Export values match balances API ({len(api_balances)} items)")
    
    def test_export_missing_customer_id_returns_422(self):
        """Missing customer_id returns 422 validation error"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/export")
        assert response.status_code == 422, f"Expected 422 for missing customer_id, got {response.status_code}"
        print("✓ Missing customer_id returns 422")


class TestExportRegression:
    """Regression tests for related endpoints"""
    
    def test_manual_movement_still_works(self):
        """POST /api/inventory-ledger/movements still creates movements"""
        unique_item = f"TEST_EXPORT_REGRESS_{uuid.uuid4().hex[:8]}"
        payload = {
            "customer_id": TEST_CUSTOMER_ID,
            "movement_type": "manual_adjustment",
            "item": unique_item,
            "qty": 10
        }
        response = requests.post(f"{BASE_URL}/api/inventory-ledger/movements", json=payload)
        assert response.status_code == 200, f"Manual movement failed: {response.status_code}"
        data = response.json()
        assert data.get('success') == True, f"Movement not successful: {data}"
        print(f"✓ Manual movement still works: {unique_item}")
    
    def test_history_endpoint_still_works(self):
        """GET /api/inventory-ledger/history returns movements"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/history",
                               params={"customer_id": TEST_CUSTOMER_ID, "limit": 5})
        assert response.status_code == 200, f"History failed: {response.status_code}"
        data = response.json()
        assert 'movements' in data, "Missing 'movements' in response"
        assert 'total' in data, "Missing 'total' in response"
        print(f"✓ History endpoint works: {data['total']} total movements")
    
    def test_reconcile_sales_order_endpoint_exists(self):
        """POST /api/inventory-ledger/reconcile-sales-order endpoint available"""
        # Test with empty/cancelled order - just verify endpoint responds
        payload = {
            "sales_order_id": f"TEST-SO-{uuid.uuid4().hex[:8]}",
            "lines": [],
            "cancelled": True
        }
        response = requests.post(f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order", json=payload)
        # Expect 200 (no-op for empty cancelled) or 422 (validation)
        assert response.status_code in [200, 422], f"Unexpected status: {response.status_code}"
        print(f"✓ reconcile-sales-order endpoint responds: {response.status_code}")
    
    def test_incoming_from_shortage_endpoint_exists(self):
        """POST /api/incoming-supply/from-shortage endpoint available"""
        payload = {
            "sales_order_id": f"TEST-SO-{uuid.uuid4().hex[:8]}",
            "lines": []
        }
        response = requests.post(f"{BASE_URL}/api/incoming-supply/from-shortage", json=payload)
        # Expect 200 (empty lines = no-op) or 422 (validation)
        assert response.status_code in [200, 422], f"Unexpected status: {response.status_code}"
        print(f"✓ incoming-supply/from-shortage endpoint responds: {response.status_code}")
    
    def test_balances_endpoint_still_works(self):
        """GET /api/inventory-ledger/customers/{id}/balances returns data"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{TEST_CUSTOMER_ID}/balances")
        assert response.status_code == 200, f"Balances failed: {response.status_code}"
        data = response.json()
        assert 'balances' in data, "Missing 'balances' in response"
        assert 'count' in data, "Missing 'count' in response"
        print(f"✓ Balances endpoint works: {data['count']} items")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
