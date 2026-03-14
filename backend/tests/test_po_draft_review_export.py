"""
PO Draft Review and Export API Tests (Iteration 74)

Tests for:
- GET /api/inventory-ledger/po-drafts/{id} - Returns full PO draft with all fields
- GET /api/inventory-ledger/po-drafts/{id}/export - Returns downloadable JSON
- PATCH /api/inventory-ledger/po-drafts/{id}/status - Updates draft status
- 404 handling for nonexistent drafts
"""
import pytest
import requests
import os
import json

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestPODraftDetail:
    """Tests for GET /api/inventory-ledger/po-drafts/{id} endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get a valid draft ID from existing drafts for Hormel customer"""
        self.customer_id = None
        self.draft_id = None
        
        # Get Hormel customer
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert res.status_code == 200
        customers = res.json()
        hormel = next((c for c in customers if c.get('code') == 'HORMEL'), None)
        if hormel:
            self.customer_id = hormel['id']
            # Get existing drafts for Hormel
            drafts_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={self.customer_id}")
            if drafts_res.status_code == 200:
                drafts = drafts_res.json().get('drafts', [])
                if drafts:
                    self.draft_id = drafts[0].get('po_draft_id')
    
    def test_get_draft_detail_success(self):
        """GET /api/inventory-ledger/po-drafts/{id} returns full draft with all fields"""
        if not self.draft_id:
            pytest.skip("No existing draft found for testing")
        
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{self.draft_id}")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        
        data = res.json()
        # Verify all expected fields are present
        assert "po_draft_id" in data, "Missing po_draft_id"
        assert "created_at" in data, "Missing created_at"
        assert "customer_id" in data, "Missing customer_id"
        assert "customer_name" in data, "Missing customer_name"
        assert "lines" in data, "Missing lines"
        assert "source" in data, "Missing source"
        assert "status" in data, "Missing status"
        assert "total_qty" in data, "Missing total_qty"
        assert "total_lines" in data, "Missing total_lines"
        
        # Verify draft_id matches
        assert data["po_draft_id"] == self.draft_id
        
        # Verify lines structure
        assert isinstance(data["lines"], list), "lines should be a list"
        if data["lines"]:
            first_line = data["lines"][0]
            assert "item" in first_line, "Line missing item"
            assert "qty" in first_line, "Line missing qty"
            assert "source" in first_line, "Line missing source"
        
        print(f"SUCCESS: Draft detail returned with all fields for {self.draft_id}")
    
    def test_get_draft_detail_404_nonexistent(self):
        """GET /api/inventory-ledger/po-drafts/{id} returns 404 for nonexistent draft"""
        fake_draft_id = "PO-DRAFT-NONEXISTENT-999999"
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{fake_draft_id}")
        
        assert res.status_code == 404, f"Expected 404, got {res.status_code}"
        data = res.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()
        
        print(f"SUCCESS: 404 returned for nonexistent draft {fake_draft_id}")


class TestPODraftExport:
    """Tests for GET /api/inventory-ledger/po-drafts/{id}/export endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get a valid draft ID from existing drafts"""
        self.customer_id = None
        self.draft_id = None
        self.draft_data = None
        
        # Get Hormel customer
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert res.status_code == 200
        customers = res.json()
        hormel = next((c for c in customers if c.get('code') == 'HORMEL'), None)
        if hormel:
            self.customer_id = hormel['id']
            # Get existing drafts for Hormel
            drafts_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={self.customer_id}")
            if drafts_res.status_code == 200:
                drafts = drafts_res.json().get('drafts', [])
                if drafts:
                    self.draft_id = drafts[0].get('po_draft_id')
                    # Get full draft detail
                    detail_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{self.draft_id}")
                    if detail_res.status_code == 200:
                        self.draft_data = detail_res.json()
    
    def test_export_draft_json_success(self):
        """GET /api/inventory-ledger/po-drafts/{id}/export returns downloadable JSON with Content-Disposition"""
        if not self.draft_id:
            pytest.skip("No existing draft found for testing")
        
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{self.draft_id}/export")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        
        # Verify Content-Disposition header for download
        content_disposition = res.headers.get('Content-Disposition', '')
        assert 'attachment' in content_disposition, "Missing attachment in Content-Disposition"
        assert self.draft_id in content_disposition, f"Draft ID {self.draft_id} not in Content-Disposition header"
        assert '.json' in content_disposition, "Missing .json extension in Content-Disposition"
        
        # Verify content type
        content_type = res.headers.get('Content-Type', '')
        assert 'application/json' in content_type, f"Expected application/json, got {content_type}"
        
        # Verify JSON is parseable
        export_data = res.json()
        assert "po_draft_id" in export_data
        assert export_data["po_draft_id"] == self.draft_id
        
        print(f"SUCCESS: Export returned with Content-Disposition: {content_disposition}")
    
    def test_export_matches_stored_draft(self):
        """GET /api/inventory-ledger/po-drafts/{id}/export payload matches stored draft exactly"""
        if not self.draft_id or not self.draft_data:
            pytest.skip("No existing draft found for testing")
        
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{self.draft_id}/export")
        assert res.status_code == 200
        
        export_data = res.json()
        
        # Verify all stored fields match export
        assert export_data["po_draft_id"] == self.draft_data["po_draft_id"]
        assert export_data["customer_id"] == self.draft_data["customer_id"]
        assert export_data["customer_name"] == self.draft_data["customer_name"]
        assert export_data["status"] == self.draft_data["status"]
        assert export_data["total_qty"] == self.draft_data["total_qty"]
        assert export_data["total_lines"] == self.draft_data["total_lines"]
        assert export_data["source"] == self.draft_data["source"]
        
        # Verify lines match
        assert len(export_data["lines"]) == len(self.draft_data["lines"])
        for i, line in enumerate(export_data["lines"]):
            assert line["item"] == self.draft_data["lines"][i]["item"]
            assert line["qty"] == self.draft_data["lines"][i]["qty"]
        
        print(f"SUCCESS: Export data matches stored draft exactly")
    
    def test_export_draft_404_nonexistent(self):
        """GET /api/inventory-ledger/po-drafts/{id}/export returns 404 for nonexistent draft"""
        fake_draft_id = "PO-DRAFT-NONEXISTENT-888888"
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{fake_draft_id}/export")
        
        assert res.status_code == 404, f"Expected 404, got {res.status_code}"
        data = res.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()
        
        print(f"SUCCESS: Export returns 404 for nonexistent draft")


class TestPODraftStatusUpdate:
    """Tests for PATCH /api/inventory-ledger/po-drafts/{id}/status endpoint"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get a valid draft ID from existing drafts"""
        self.customer_id = None
        self.draft_id = None
        self.original_status = None
        
        # Get Hormel customer
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert res.status_code == 200
        customers = res.json()
        hormel = next((c for c in customers if c.get('code') == 'HORMEL'), None)
        if hormel:
            self.customer_id = hormel['id']
            # Get existing drafts for Hormel
            drafts_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={self.customer_id}")
            if drafts_res.status_code == 200:
                drafts = drafts_res.json().get('drafts', [])
                if drafts:
                    # Find a draft that's not archived for testing
                    for d in drafts:
                        if d.get('status') != 'archived':
                            self.draft_id = d.get('po_draft_id')
                            self.original_status = d.get('status')
                            break
                    if not self.draft_id and drafts:
                        self.draft_id = drafts[0].get('po_draft_id')
                        self.original_status = drafts[0].get('status')
    
    def test_update_status_to_sent(self):
        """PATCH /api/inventory-ledger/po-drafts/{id}/status?status=sent updates status"""
        if not self.draft_id:
            pytest.skip("No existing draft found for testing")
        
        res = requests.patch(f"{BASE_URL}/api/inventory-ledger/po-drafts/{self.draft_id}/status?status=sent")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        
        data = res.json()
        assert data["po_draft_id"] == self.draft_id
        assert data["status"] == "sent"
        
        # Verify the update persisted
        verify_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{self.draft_id}")
        assert verify_res.status_code == 200
        verify_data = verify_res.json()
        assert verify_data["status"] == "sent"
        
        print(f"SUCCESS: Draft status updated to 'sent'")
    
    def test_update_status_to_archived(self):
        """PATCH /api/inventory-ledger/po-drafts/{id}/status?status=archived updates status"""
        if not self.draft_id:
            pytest.skip("No existing draft found for testing")
        
        res = requests.patch(f"{BASE_URL}/api/inventory-ledger/po-drafts/{self.draft_id}/status?status=archived")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}"
        
        data = res.json()
        assert data["po_draft_id"] == self.draft_id
        assert data["status"] == "archived"
        
        # Verify the update persisted
        verify_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{self.draft_id}")
        assert verify_res.status_code == 200
        verify_data = verify_res.json()
        assert verify_data["status"] == "archived"
        
        print(f"SUCCESS: Draft status updated to 'archived'")
    
    def test_update_status_invalid_returns_422(self):
        """PATCH /api/inventory-ledger/po-drafts/{id}/status?status=invalid returns 422"""
        if not self.draft_id:
            pytest.skip("No existing draft found for testing")
        
        res = requests.patch(f"{BASE_URL}/api/inventory-ledger/po-drafts/{self.draft_id}/status?status=invalid_status")
        assert res.status_code == 422, f"Expected 422, got {res.status_code}"
        
        data = res.json()
        assert "detail" in data
        
        print(f"SUCCESS: 422 returned for invalid status")
    
    def test_update_status_nonexistent_draft_returns_404(self):
        """PATCH /api/inventory-ledger/po-drafts/{id}/status returns 404 for nonexistent draft"""
        fake_draft_id = "PO-DRAFT-NONEXISTENT-777777"
        res = requests.patch(f"{BASE_URL}/api/inventory-ledger/po-drafts/{fake_draft_id}/status?status=sent")
        
        assert res.status_code == 404, f"Expected 404, got {res.status_code}"
        data = res.json()
        assert "detail" in data
        assert "not found" in data["detail"].lower()
        
        print(f"SUCCESS: 404 returned for nonexistent draft status update")


class TestRegressionEndpoints:
    """Regression tests to ensure other endpoints still work"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Get Hormel customer ID"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers")
        assert res.status_code == 200
        customers = res.json()
        hormel = next((c for c in customers if c.get('code') == 'HORMEL'), None)
        self.customer_id = hormel['id'] if hormel else None
    
    def test_action_center_still_works(self):
        """Action Center endpoint still returns data"""
        if not self.customer_id:
            pytest.skip("No Hormel customer found")
        
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/action-center?customer_id={self.customer_id}")
        assert res.status_code == 200
        data = res.json()
        assert "action_summary" in data
        assert "actions" in data
        print(f"SUCCESS: Action Center working (total: {data.get('total', 0)} items)")
    
    def test_supply_coverage_still_works(self):
        """Supply Coverage endpoint still returns data"""
        if not self.customer_id:
            pytest.skip("No Hormel customer found")
        
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/supply-coverage?customer_id={self.customer_id}")
        assert res.status_code == 200
        data = res.json()
        assert "coverage" in data
        assert "total" in data
        print(f"SUCCESS: Supply Coverage working (total: {data.get('total', 0)} items)")
    
    def test_demand_signals_still_works(self):
        """Demand Signals endpoint still returns data"""
        if not self.customer_id:
            pytest.skip("No Hormel customer found")
        
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/demand-signals?customer_id={self.customer_id}")
        assert res.status_code == 200
        data = res.json()
        assert "demand_signals" in data
        assert "total" in data
        print(f"SUCCESS: Demand Signals working (total: {data.get('total', 0)} items)")
    
    def test_exceptions_still_works(self):
        """Exceptions endpoint still returns data"""
        if not self.customer_id:
            pytest.skip("No Hormel customer found")
        
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/exceptions?customer_id={self.customer_id}")
        assert res.status_code == 200
        data = res.json()
        assert "exception_summary" in data
        assert "exceptions" in data
        print(f"SUCCESS: Exceptions working (total: {data.get('total', 0)} items)")
    
    def test_dashboard_summary_still_works(self):
        """Dashboard Summary endpoint still returns data"""
        if not self.customer_id:
            pytest.skip("No Hormel customer found")
        
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary?customer_id={self.customer_id}")
        assert res.status_code == 200
        data = res.json()
        assert "total_items" in data
        assert "items_ok" in data
        assert "items_low" in data
        assert "items_short" in data
        print(f"SUCCESS: Dashboard Summary working (total items: {data.get('total_items', 0)})")
    
    def test_po_drafts_list_still_works(self):
        """PO Drafts list endpoint still returns data"""
        if not self.customer_id:
            pytest.skip("No Hormel customer found")
        
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={self.customer_id}")
        assert res.status_code == 200
        data = res.json()
        assert "drafts" in data
        assert "total" in data
        print(f"SUCCESS: PO Drafts list working (total: {data.get('total', 0)} drafts)")
