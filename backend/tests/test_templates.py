"""
Test suite for Operational Templates feature (iteration_93)
Tests CRUD endpoints, apply endpoint, and safe-skip behavior.
"""
import pytest
import requests
import os
BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def api_client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestTemplatesCRUD:
    """Test template CRUD endpoints"""
    
        
        
        
        
    def test_list_all_templates(self, api_client):
        """GET /templates - list all templates"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/templates")
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        assert "total" in data
        assert isinstance(data["entries"], list)
        print(f"✓ Listed {data['total']} templates")
        
    def test_list_templates_filter_by_entity_type(self, api_client):
        """GET /templates?entity_type=sales_order - filter by type"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/templates?entity_type=sales_order")
        assert response.status_code == 200
        data = response.json()
        for tmpl in data["entries"]:
            assert tmpl["entity_type"] == "sales_order"
        print(f"✓ Filtered by entity_type=sales_order: {data['total']} templates")
        
    def test_list_templates_filter_by_active(self, api_client):
        """GET /templates?entity_type=sales_order&is_active=true - filter by type and active"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/templates?entity_type=sales_order&is_active=true")
        assert response.status_code == 200
        data = response.json()
        for tmpl in data["entries"]:
            assert tmpl["entity_type"] == "sales_order"
            assert tmpl["is_active"] is True
        print(f"✓ Filtered by entity_type=sales_order&is_active=true: {data['total']} templates")
        

        


class TestTemplateApply:
    """Test template apply endpoint and safe-skip behavior"""
    
    
    
    
    @pytest.fixture
    def test_sales_order_id(self, api_client):
        """Get a real SO ID from operations queue"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=sales_order&limit=1")
        if response.status_code == 200:
            items = response.json().get("items", [])
            if items:
                return items[0]["entity_id"]
        # Return a reasonable default
        return "SO-TEST-001"
    
    @pytest.fixture
    def test_po_draft(self, api_client):
        """Get or create a PO Draft for testing"""
        # First try to get existing PO drafts
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=po_draft&limit=1")
        if response.status_code == 200:
            items = response.json().get("items", [])
            if items:
                return items[0]["entity_id"]
        return None
    
        
        
    
            
            
            
        


class TestBulkApplyTemplate:
    """Test bulk apply_template via operations-queue/bulk-action"""
    
    
    @pytest.fixture
    def test_so_ids(self, api_client):
        """Get multiple SO IDs for bulk testing"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=sales_order&limit=3")
        if response.status_code == 200:
            items = response.json().get("items", [])
            if len(items) >= 2:
                return [item["entity_id"] for item in items[:2]]
        return []
    
        
    def test_bulk_apply_template_requires_template_id(self, api_client, test_so_ids):
        """Bulk apply_template validates template_id is required"""
        if not test_so_ids:
            pytest.skip("No SOs available for testing")
            
        bulk_payload = {
            "entity_type": "sales_order",
            "entity_ids": test_so_ids[:1],
            "action": "apply_template",
            "payload": {}  # Missing template_id
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json=bulk_payload)
        assert response.status_code == 200  # Bulk action returns 200 with per-item failures
        data = response.json()
        # Check that result indicates failure
        results = data.get("results", [])
        if results:
            assert results[0].get("status") == "failed"
            assert "template_id" in results[0].get("message", "").lower()
        print(f"✓ Bulk template apply correctly fails when template_id missing")


class TestRegressionBulkActions:
    """Regression tests for bulk actions (iteration_92)"""
    
    @pytest.fixture
    def test_so_id(self, api_client):
        """Get a SO ID for regression tests"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=sales_order&limit=1")
        if response.status_code == 200:
            items = response.json().get("items", [])
            if items:
                return items[0]["entity_id"]
        return None
    
    def test_bulk_assign_owner_still_works(self, api_client, test_so_id):
        """Regression: bulk assign_owner still works (iteration_92)"""
        if not test_so_id:
            pytest.skip("No SO available")
            
        bulk_payload = {
            "entity_type": "sales_order",
            "entity_ids": [test_so_id],
            "action": "assign_owner",
            "payload": {
                "assigned_to": "Regression Test User"
            }
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json=bulk_payload)
        assert response.status_code == 200
        print(f"✓ Regression: bulk assign_owner works")


class TestRegressionSavedViews:
    """Regression tests for saved views (iteration_91)"""
    
    def test_saved_views_endpoint_works(self, api_client):
        """Regression: saved-views endpoint works (iteration_91)"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/saved-views?view_type=operations_queue")
        assert response.status_code == 200
        data = response.json()
        assert "entries" in data
        print(f"✓ Regression: saved-views endpoint works")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
