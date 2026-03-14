"""
Snapshot Export Feature Tests

Tests for GET /api/inventory-ledger/snapshot and /snapshot/export endpoints.
Snapshot returns structured JSON with generated_at, context, summary metrics, balance rows, and optional reorder rows.
Export returns the same as a downloadable JSON file with Content-Disposition header.
"""
import pytest
import requests
import os
import json
import re

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Known test customer with data
HORMEL_CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"


class TestSnapshotEndpoint:
    """Tests for GET /api/inventory-ledger/snapshot"""
    
    def test_snapshot_basic_structure(self):
        """Verify snapshot returns all required top-level fields"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}")
        assert response.status_code == 200
        
        data = response.json()
        # Required top-level fields
        assert "generated_at" in data
        assert "context" in data
        assert "summary" in data
        assert "balances" in data
        # Default include_reorders=true
        assert "reorders" in data
        
    def test_snapshot_generated_at_format(self):
        """Verify generated_at is ISO timestamp"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}")
        data = response.json()
        
        # Should be ISO format datetime string
        generated_at = data.get("generated_at", "")
        assert "T" in generated_at  # ISO format has T separator
        assert ":" in generated_at  # Has time component
        
    def test_snapshot_context_fields(self):
        """Verify context object has expected fields"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}")
        data = response.json()
        
        context = data.get("context", {})
        assert context.get("customer_id") == HORMEL_CUSTOMER_ID
        assert "item_filter" in context
        assert "include_reorders" in context
        assert context["include_reorders"] is True  # Default
        
    def test_snapshot_summary_fields(self):
        """Verify summary has all expected metrics fields"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}")
        data = response.json()
        
        summary = data.get("summary", {})
        expected_fields = [
            "total_items", "items_ok", "items_low", "items_short",
            "total_on_hand", "total_incoming", "total_committed", 
            "total_available", "total_reorder_recommendations"
        ]
        for field in expected_fields:
            assert field in summary, f"Missing summary field: {field}"
            
    def test_snapshot_summary_matches_dashboard(self):
        """Verify snapshot summary matches /dashboard-summary exactly"""
        snapshot_res = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}")
        dashboard_res = requests.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary?customer_id={HORMEL_CUSTOMER_ID}")
        
        assert snapshot_res.status_code == 200
        assert dashboard_res.status_code == 200
        
        snap_summary = snapshot_res.json().get("summary", {})
        dashboard = dashboard_res.json()
        
        # All fields should match
        for field in dashboard.keys():
            assert snap_summary.get(field) == dashboard[field], f"Mismatch in {field}"
            
    def test_snapshot_balance_rows_have_status(self):
        """Verify balance rows have status field (OK/LOW/SHORT)"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}")
        data = response.json()
        
        balances = data.get("balances", [])
        assert len(balances) > 0, "Expected at least one balance row"
        
        for b in balances:
            assert "status" in b, f"Balance row missing status field: {b.get('item')}"
            assert b["status"] in ["OK", "LOW", "SHORT"], f"Invalid status: {b['status']}"
            
    def test_snapshot_balance_rows_structure(self):
        """Verify balance rows have all expected fields"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}")
        data = response.json()
        
        balances = data.get("balances", [])
        expected_fields = [
            "item", "item_description", "warehouse", "ownership_type",
            "on_hand", "incoming", "committed", "available",
            "unit_of_measure", "status"
        ]
        
        if balances:
            b = balances[0]
            for field in expected_fields:
                assert field in b, f"Missing balance field: {field}"
            # Should NOT have internal flags
            assert "is_short" not in b, "is_short internal flag should be stripped"
            assert "is_low" not in b, "is_low internal flag should be stripped"
            
    def test_snapshot_balance_rows_match_api(self):
        """Verify balance rows match /customers/{cid}/balances count"""
        snapshot_res = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}")
        balances_res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/balances")
        
        snap_balances = snapshot_res.json().get("balances", [])
        api_balances = balances_res.json().get("balances", [])
        
        assert len(snap_balances) == len(api_balances), "Balance counts should match"
        
    def test_snapshot_include_reorders_true(self):
        """Verify include_reorders=true includes reorders array"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}&include_reorders=true")
        data = response.json()
        
        assert "reorders" in data, "reorders key should exist when include_reorders=true"
        assert data["context"]["include_reorders"] is True
        
    def test_snapshot_include_reorders_false(self):
        """Verify include_reorders=false excludes reorders key"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}&include_reorders=false")
        data = response.json()
        
        assert "reorders" not in data, "reorders key should NOT exist when include_reorders=false"
        assert data["context"]["include_reorders"] is False
        
    def test_snapshot_reorder_rows_structure(self):
        """Verify reorder rows have expected fields"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}&include_reorders=true")
        data = response.json()
        
        reorders = data.get("reorders", [])
        if reorders:
            r = reorders[0]
            expected_fields = [
                "item", "warehouse", "available", "status",
                "recommended_qty", "reorder_threshold", "safety_buffer"
            ]
            for field in expected_fields:
                assert field in r, f"Missing reorder field: {field}"
                
    def test_snapshot_item_filter(self):
        """Verify item filter works"""
        # Get an item we know exists
        all_snap = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}")
        balances = all_snap.json().get("balances", [])
        
        if balances:
            test_item = balances[0]["item"]
            filtered = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id={HORMEL_CUSTOMER_ID}&item={test_item}")
            data = filtered.json()
            
            assert data["context"]["item_filter"] == test_item
            # Should have fewer or equal balances
            assert len(data.get("balances", [])) <= len(balances)
            
    def test_snapshot_missing_customer_id_returns_422(self):
        """Verify missing customer_id returns 422"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot")
        assert response.status_code == 422
        
    def test_snapshot_empty_customer_returns_zeros(self):
        """Verify nonexistent/empty customer returns valid snapshot with zeros"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot?customer_id=nonexistent-customer-xyz")
        assert response.status_code == 200
        
        data = response.json()
        summary = data.get("summary", {})
        
        # All counts should be zero
        assert summary.get("total_items") == 0
        assert summary.get("items_ok") == 0
        assert summary.get("items_low") == 0
        assert summary.get("items_short") == 0
        assert len(data.get("balances", [])) == 0


class TestSnapshotExportEndpoint:
    """Tests for GET /api/inventory-ledger/snapshot/export"""
    
    def test_export_returns_json(self):
        """Verify export returns valid JSON body"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot/export?customer_id={HORMEL_CUSTOMER_ID}")
        assert response.status_code == 200
        
        # Should be valid JSON
        data = response.json()
        assert isinstance(data, dict)
        
    def test_export_content_disposition_header(self):
        """Verify Content-Disposition header for download"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot/export?customer_id={HORMEL_CUSTOMER_ID}")
        assert response.status_code == 200
        
        cd_header = response.headers.get("Content-Disposition", "")
        assert "attachment" in cd_header
        assert "filename=" in cd_header
        
    def test_export_filename_format(self):
        """Verify filename format: snapshot_{name}_{timestamp}.json"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot/export?customer_id={HORMEL_CUSTOMER_ID}")
        
        cd_header = response.headers.get("Content-Disposition", "")
        # Extract filename
        match = re.search(r'filename=["\']?([^"\';\s]+)', cd_header)
        assert match, "Filename not found in Content-Disposition"
        
        filename = match.group(1)
        assert filename.startswith("snapshot_"), f"Filename should start with snapshot_: {filename}"
        assert filename.endswith(".json"), f"Filename should end with .json: {filename}"
        
        # Should have timestamp pattern YYYYMMDD_HHMMSS
        assert re.search(r'\d{8}_\d{6}\.json$', filename), f"Filename missing timestamp: {filename}"
        
    def test_export_body_matches_snapshot(self):
        """Verify export body structure matches /snapshot response"""
        export_res = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot/export?customer_id={HORMEL_CUSTOMER_ID}")
        
        data = export_res.json()
        
        # Should have same structure
        assert "generated_at" in data
        assert "context" in data
        assert "summary" in data
        assert "balances" in data
        # Default include_reorders=true
        assert "reorders" in data
        
    def test_export_content_type(self):
        """Verify Content-Type is application/json"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot/export?customer_id={HORMEL_CUSTOMER_ID}")
        
        content_type = response.headers.get("Content-Type", "")
        assert "application/json" in content_type
        
    def test_export_with_include_reorders_false(self):
        """Verify export respects include_reorders parameter"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/snapshot/export?customer_id={HORMEL_CUSTOMER_ID}&include_reorders=false")
        assert response.status_code == 200
        
        data = response.json()
        assert "reorders" not in data


class TestSnapshotRegression:
    """Regression tests to ensure existing features still work"""
    
    def test_dashboard_summary_still_works(self):
        """Verify dashboard-summary endpoint still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary?customer_id={HORMEL_CUSTOMER_ID}")
        assert response.status_code == 200
        assert "total_items" in response.json()
        
    def test_balances_tab_still_works(self):
        """Verify balances endpoint still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/balances")
        assert response.status_code == 200
        assert "balances" in response.json()
        
    def test_reorder_recommendations_still_works(self):
        """Verify reorder-recommendations endpoint still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/reorder-recommendations?customer_id={HORMEL_CUSTOMER_ID}")
        assert response.status_code == 200
        assert "recommendations" in response.json()
        
    def test_item_settings_still_works(self):
        """Verify item-settings endpoint still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-items/settings?customer_id={HORMEL_CUSTOMER_ID}")
        assert response.status_code == 200
        assert "settings" in response.json()
        
    def test_csv_export_still_works(self):
        """Verify CSV export endpoint still works"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/export?customer_id={HORMEL_CUSTOMER_ID}")
        assert response.status_code == 200
        assert "text/csv" in response.headers.get("Content-Type", "")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
