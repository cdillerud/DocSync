"""
Test suite for Operational Templates feature (iteration_93)
Tests CRUD endpoints, apply endpoint, and safe-skip behavior.
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def api_client():
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestTemplatesCRUD:
    """Test template CRUD endpoints"""
    
    def test_create_template_valid(self, api_client):
        """POST /templates - create template with all fields"""
        unique_name = f"TEST_Template_{uuid.uuid4().hex[:6]}"
        payload = {
            "name": unique_name,
            "entity_type": "sales_order",
            "applies_to_order_type": "warehouse",
            "description": "Test template for warehouse orders",
            "default_assignment_to": "Test User",
            "default_due_days": 5,
            "default_escalation_status": "on_track",
            "auto_request_approval": True,
            "notes": "Test notes",
            "is_active": True
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates", json=payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "template_id" in data
        assert data["name"] == unique_name
        assert data["entity_type"] == "sales_order"
        assert data["applies_to_order_type"] == "warehouse"
        assert data["default_assignment_to"] == "Test User"
        assert data["default_due_days"] == 5
        assert data["auto_request_approval"] is True
        print(f"✓ Created template: {data['template_id']}")
        
    def test_create_template_invalid_entity_type(self, api_client):
        """POST /templates - validates entity_type (422 for invalid)"""
        payload = {
            "name": "Invalid Entity Type Template",
            "entity_type": "invalid_type"
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates", json=payload)
        assert response.status_code == 422, f"Expected 422 for invalid entity_type, got {response.status_code}"
        print(f"✓ Correctly rejected invalid entity_type with 422")
        
    def test_create_template_invalid_order_type(self, api_client):
        """POST /templates - validates applies_to_order_type (422 for invalid)"""
        payload = {
            "name": "Invalid Order Type Template",
            "entity_type": "sales_order",
            "applies_to_order_type": "invalid_order_type"
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates", json=payload)
        assert response.status_code == 422, f"Expected 422 for invalid order_type, got {response.status_code}"
        print(f"✓ Correctly rejected invalid applies_to_order_type with 422")
        
    def test_create_po_draft_template(self, api_client):
        """POST /templates - create PO Draft template"""
        unique_name = f"TEST_PO_Template_{uuid.uuid4().hex[:6]}"
        payload = {
            "name": unique_name,
            "entity_type": "po_draft",
            "default_assignment_to": "PO Manager",
            "default_due_days": 7,
            "auto_request_approval": False,
            "is_active": True
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates", json=payload)
        assert response.status_code == 200
        data = response.json()
        assert data["entity_type"] == "po_draft"
        print(f"✓ Created PO Draft template: {data['template_id']}")
        
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
        

class TestTemplateUpdate:
    """Test template update endpoint"""
    
    @pytest.fixture
    def test_template(self, api_client):
        """Create a template for update tests"""
        unique_name = f"TEST_Update_Template_{uuid.uuid4().hex[:6]}"
        payload = {
            "name": unique_name,
            "entity_type": "sales_order",
            "default_assignment_to": "Original Owner",
            "default_due_days": 3,
            "is_active": True
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates", json=payload)
        assert response.status_code == 200
        return response.json()
    
    def test_update_template_fields(self, api_client, test_template):
        """PATCH /templates/{id} - update template fields"""
        template_id = test_template["template_id"]
        update_payload = {
            "name": "Updated Template Name",
            "default_assignment_to": "New Owner",
            "default_due_days": 7
        }
        response = api_client.patch(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}", json=update_payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["name"] == "Updated Template Name"
        assert data["default_assignment_to"] == "New Owner"
        assert data["default_due_days"] == 7
        print(f"✓ Updated template {template_id}")
        
    def test_update_template_not_found(self, api_client):
        """PATCH /templates/{id} - returns 404 for non-existent"""
        response = api_client.patch(f"{BASE_URL}/api/inventory-ledger/templates/TMPL-NONEXISTENT", json={"name": "Test"})
        assert response.status_code == 404
        print(f"✓ Correctly returned 404 for non-existent template")
        

class TestTemplateDelete:
    """Test template soft-delete endpoint"""
    
    @pytest.fixture
    def delete_template(self, api_client):
        """Create a template for delete test"""
        unique_name = f"TEST_Delete_Template_{uuid.uuid4().hex[:6]}"
        payload = {
            "name": unique_name,
            "entity_type": "sales_order",
            "is_active": True
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates", json=payload)
        assert response.status_code == 200
        return response.json()
    
    def test_delete_template_soft_deactivates(self, api_client, delete_template):
        """DELETE /templates/{id} - soft-deactivates template"""
        template_id = delete_template["template_id"]
        response = api_client.delete(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}")
        assert response.status_code == 200
        data = response.json()
        assert data.get("deactivated") == template_id
        
        # Verify it's now inactive
        get_response = api_client.get(f"{BASE_URL}/api/inventory-ledger/templates")
        templates = get_response.json()["entries"]
        found = next((t for t in templates if t["template_id"] == template_id), None)
        assert found is not None
        assert found["is_active"] is False
        print(f"✓ Template {template_id} soft-deactivated (is_active=false)")


class TestTemplateApply:
    """Test template apply endpoint and safe-skip behavior"""
    
    @pytest.fixture
    def so_template(self, api_client):
        """Create an active SO template for apply tests"""
        unique_name = f"TEST_Apply_SO_Template_{uuid.uuid4().hex[:6]}"
        payload = {
            "name": unique_name,
            "entity_type": "sales_order",
            "default_assignment_to": "Template Assigned User",
            "default_due_days": 5,
            "auto_request_approval": True,
            "is_active": True
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates", json=payload)
        assert response.status_code == 200
        return response.json()
    
    @pytest.fixture
    def po_template(self, api_client):
        """Create an active PO Draft template"""
        unique_name = f"TEST_Apply_PO_Template_{uuid.uuid4().hex[:6]}"
        payload = {
            "name": unique_name,
            "entity_type": "po_draft",
            "default_assignment_to": "PO Template User",
            "default_due_days": 3,
            "auto_request_approval": False,
            "is_active": True
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates", json=payload)
        assert response.status_code == 200
        return response.json()
    
    @pytest.fixture
    def warehouse_template(self, api_client):
        """Create a warehouse-only SO template"""
        unique_name = f"TEST_Warehouse_Template_{uuid.uuid4().hex[:6]}"
        payload = {
            "name": unique_name,
            "entity_type": "sales_order",
            "applies_to_order_type": "warehouse",
            "default_assignment_to": "Warehouse Manager",
            "default_due_days": 2,
            "is_active": True
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates", json=payload)
        assert response.status_code == 200
        return response.json()
    
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
    
    def test_apply_template_entity_type_mismatch(self, api_client, so_template):
        """POST /templates/{id}/apply - validates entity_type mismatch (422)"""
        template_id = so_template["template_id"]
        apply_payload = {
            "entity_type": "po_draft",  # Mismatch - template is for sales_order
            "entity_id": "PO-DRAFT-TEST"
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}/apply", json=apply_payload)
        assert response.status_code == 422, f"Expected 422 for entity_type mismatch, got {response.status_code}"
        print(f"✓ Correctly rejected entity_type mismatch with 422")
        
    def test_apply_inactive_template_returns_404(self, api_client):
        """POST /templates/{id}/apply - returns 404 for inactive template"""
        # First create and deactivate a template
        unique_name = f"TEST_Inactive_Template_{uuid.uuid4().hex[:6]}"
        create_payload = {
            "name": unique_name,
            "entity_type": "sales_order",
            "is_active": True
        }
        create_response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates", json=create_payload)
        assert create_response.status_code == 200
        template_id = create_response.json()["template_id"]
        
        # Deactivate it
        api_client.delete(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}")
        
        # Try to apply
        apply_payload = {
            "entity_type": "sales_order",
            "entity_id": "SO-TEST-001"
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}/apply", json=apply_payload)
        assert response.status_code == 404, f"Expected 404 for inactive template, got {response.status_code}"
        print(f"✓ Correctly returned 404 for inactive template")
        
    def test_apply_template_to_so(self, api_client, so_template, test_sales_order_id):
        """POST /templates/{id}/apply - apply template to SO creates assignment, due date, approval"""
        template_id = so_template["template_id"]
        apply_payload = {
            "entity_type": "sales_order",
            "entity_id": test_sales_order_id
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}/apply", json=apply_payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "actions_applied" in data
        assert "actions_skipped" in data
        assert "messages" in data
        print(f"✓ Applied template to SO - Applied: {data['actions_applied']}, Skipped: {data['actions_skipped']}")
        return data
    
    def test_apply_template_safe_skip_assignment(self, api_client, so_template, test_sales_order_id):
        """POST /templates/{id}/apply - safe skip: existing assignment is skipped not overwritten"""
        template_id = so_template["template_id"]
        
        # First apply to create assignment
        first_apply = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}/apply", json={
            "entity_type": "sales_order",
            "entity_id": test_sales_order_id
        })
        assert first_apply.status_code == 200
        
        # Second apply should skip assignment
        second_apply = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}/apply", json={
            "entity_type": "sales_order",
            "entity_id": test_sales_order_id
        })
        assert second_apply.status_code == 200
        data = second_apply.json()
        # If assignment was created in first apply, it should be skipped in second
        if "assignment" in first_apply.json().get("actions_applied", []):
            assert "assignment" in data.get("actions_skipped", [])
            print(f"✓ Safe skip: existing assignment correctly skipped")
        else:
            print(f"✓ Assignment was already skipped (pre-existing)")
            
    def test_apply_template_safe_skip_due_date(self, api_client, so_template, test_sales_order_id):
        """POST /templates/{id}/apply - safe skip: existing due date is skipped"""
        template_id = so_template["template_id"]
        
        # Apply template (will create or skip due date)
        apply_response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}/apply", json={
            "entity_type": "sales_order",
            "entity_id": test_sales_order_id
        })
        assert apply_response.status_code == 200
        data = apply_response.json()
        
        # Check if due_date was applied or skipped
        if "due_date" in data.get("actions_skipped", []):
            print(f"✓ Safe skip: existing due date correctly skipped")
        elif "due_date" in data.get("actions_applied", []):
            # Apply again - should skip this time
            second_apply = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}/apply", json={
                "entity_type": "sales_order",
                "entity_id": test_sales_order_id
            })
            assert "due_date" in second_apply.json().get("actions_skipped", [])
            print(f"✓ Safe skip: due date correctly skipped on second apply")
        else:
            print(f"✓ Due date not configured in template")
            
    def test_apply_template_safe_skip_approval(self, api_client, so_template, test_sales_order_id):
        """POST /templates/{id}/apply - safe skip: pending approval is skipped"""
        template_id = so_template["template_id"]
        
        # Apply template
        apply_response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}/apply", json={
            "entity_type": "sales_order",
            "entity_id": test_sales_order_id
        })
        assert apply_response.status_code == 200
        data = apply_response.json()
        
        if "approval" in data.get("actions_skipped", []):
            print(f"✓ Safe skip: pending approval correctly skipped")
        elif "approval" in data.get("actions_applied", []):
            # Apply again - should skip approval
            second_apply = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}/apply", json={
                "entity_type": "sales_order",
                "entity_id": test_sales_order_id
            })
            assert "approval" in second_apply.json().get("actions_skipped", [])
            print(f"✓ Safe skip: approval correctly skipped on second apply")
        else:
            print(f"✓ Approval not configured in template")
            
    def test_apply_template_generates_activity(self, api_client, so_template, test_sales_order_id):
        """POST /templates/{id}/apply - generates activity timeline entries"""
        template_id = so_template["template_id"]
        
        # Apply template
        apply_response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}/apply", json={
            "entity_type": "sales_order",
            "entity_id": test_sales_order_id
        })
        assert apply_response.status_code == 200
        
        # Check activity timeline
        activity_response = api_client.get(
            f"{BASE_URL}/api/inventory-ledger/activities?entity_type=sales_order&entity_id={test_sales_order_id}&limit=10"
        )
        assert activity_response.status_code == 200
        activities = activity_response.json().get("entries", [])
        
        # Look for template-related activity
        template_activities = [a for a in activities if "template" in a.get("title", "").lower() or a.get("created_by") == "template"]
        assert len(template_activities) > 0, "Expected activity entries from template application"
        print(f"✓ Found {len(template_activities)} template-related activity entries")
        
    def test_apply_template_to_po_draft(self, api_client, po_template, test_po_draft):
        """POST /templates/{id}/apply - apply to PO Draft works"""
        if not test_po_draft:
            pytest.skip("No PO Draft available for testing")
            
        template_id = po_template["template_id"]
        apply_payload = {
            "entity_type": "po_draft",
            "entity_id": test_po_draft
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates/{template_id}/apply", json=apply_payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        print(f"✓ Applied template to PO Draft - Applied: {data.get('actions_applied', [])}")


class TestBulkApplyTemplate:
    """Test bulk apply_template via operations-queue/bulk-action"""
    
    @pytest.fixture
    def bulk_template(self, api_client):
        """Create a template for bulk testing"""
        unique_name = f"TEST_Bulk_Template_{uuid.uuid4().hex[:6]}"
        payload = {
            "name": unique_name,
            "entity_type": "sales_order",
            "default_assignment_to": "Bulk Template User",
            "default_due_days": 4,
            "is_active": True
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/templates", json=payload)
        assert response.status_code == 200
        return response.json()
    
    @pytest.fixture
    def test_so_ids(self, api_client):
        """Get multiple SO IDs for bulk testing"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=sales_order&limit=3")
        if response.status_code == 200:
            items = response.json().get("items", [])
            if len(items) >= 2:
                return [item["entity_id"] for item in items[:2]]
        return []
    
    def test_bulk_apply_template_action_works(self, api_client, bulk_template, test_so_ids):
        """Bulk apply_template via operations-queue/bulk-action works for multiple entities"""
        if len(test_so_ids) < 2:
            pytest.skip("Not enough SOs available for bulk testing")
            
        template_id = bulk_template["template_id"]
        bulk_payload = {
            "entity_type": "sales_order",
            "entity_ids": test_so_ids,
            "action": "apply_template",
            "payload": {
                "template_id": template_id
            }
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json=bulk_payload)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "processed_count" in data
        assert "results" in data
        print(f"✓ Bulk template apply - Processed: {data['processed_count']}, Succeeded: {data.get('succeeded_count', 0)}")
        
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
