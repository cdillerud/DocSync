"""
Tests for Saved Views & Personal Queue Presets feature (iteration_91)

Covers:
- CRUD endpoints for saved views (POST/GET/PATCH/DELETE /api/inventory-ledger/saved-views)
- view_type validation (422 for invalid)
- Default view uniqueness (only one default per view_type + created_by)
- Operations Queue integration (saved_views_count, default_view_name)
- Regression: Activity, Assignment, Escalation endpoints
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')


class TestSavedViewsCRUD:
    """Saved Views CRUD endpoint tests"""

    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup: store created view IDs for cleanup"""
        self.created_view_ids = []
        yield
        # Cleanup: delete all test-created views
        for view_id in self.created_view_ids:
            try:
                requests.delete(f"{BASE_URL}/api/inventory-ledger/saved-views/{view_id}", timeout=5)
            except:
                pass

    def test_create_saved_view_success(self):
        """POST /api/inventory-ledger/saved-views - creates saved view with filters and sort"""
        unique_name = f"TEST-View-{uuid.uuid4().hex[:6]}"
        payload = {
            "view_type": "operations_queue",
            "name": unique_name,
            "is_default": False,
            "created_by": "test_user",
            "filters": {"entity_type": "sales_order", "escalation": "overdue"},
            "sort": {"field": "priority_score", "direction": "desc"},
            "notes": "Test view for overdue sales orders"
        }
        response = requests.post(f"{BASE_URL}/api/inventory-ledger/saved-views", json=payload, timeout=10)
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Store for cleanup
        if "saved_view_id" in data:
            self.created_view_ids.append(data["saved_view_id"])
        
        # Validate response structure
        assert "saved_view_id" in data
        assert data["saved_view_id"].startswith("SV-")
        assert data["view_type"] == "operations_queue"
        assert data["name"] == unique_name
        assert data["is_default"] == False
        assert data["created_by"] == "test_user"
        assert data["filters"] == payload["filters"]
        assert data["sort"] == payload["sort"]
        assert data["notes"] == payload["notes"]
        assert "created_at" in data
        assert "updated_at" in data
        print(f"SUCCESS: Created saved view {data['saved_view_id']}")

    def test_create_saved_view_invalid_view_type(self):
        """POST /api/inventory-ledger/saved-views - returns 422 for invalid view_type"""
        payload = {
            "view_type": "invalid_type",
            "name": "Test Invalid View",
            "is_default": False
        }
        response = requests.post(f"{BASE_URL}/api/inventory-ledger/saved-views", json=payload, timeout=10)
        
        assert response.status_code == 422, f"Expected 422, got {response.status_code}"
        data = response.json()
        assert "view_type" in str(data.get("detail", "")).lower()
        print(f"SUCCESS: 422 returned for invalid view_type")

    def test_create_default_unsets_previous(self):
        """POST /api/inventory-ledger/saved-views - setting is_default=true unsets previous default"""
        # Create first default view
        name1 = f"TEST-Default1-{uuid.uuid4().hex[:6]}"
        payload1 = {
            "view_type": "operations_queue",
            "name": name1,
            "is_default": True,
            "created_by": "test_default_user"
        }
        r1 = requests.post(f"{BASE_URL}/api/inventory-ledger/saved-views", json=payload1, timeout=10)
        assert r1.status_code == 200
        view1 = r1.json()
        self.created_view_ids.append(view1["saved_view_id"])
        assert view1["is_default"] == True
        
        # Create second default view - should unset first
        name2 = f"TEST-Default2-{uuid.uuid4().hex[:6]}"
        payload2 = {
            "view_type": "operations_queue",
            "name": name2,
            "is_default": True,
            "created_by": "test_default_user"
        }
        r2 = requests.post(f"{BASE_URL}/api/inventory-ledger/saved-views", json=payload2, timeout=10)
        assert r2.status_code == 200
        view2 = r2.json()
        self.created_view_ids.append(view2["saved_view_id"])
        assert view2["is_default"] == True
        
        # Verify first view is no longer default
        r_list = requests.get(
            f"{BASE_URL}/api/inventory-ledger/saved-views?view_type=operations_queue&created_by=test_default_user",
            timeout=10
        )
        assert r_list.status_code == 200
        views = r_list.json()["entries"]
        
        # Find our views
        v1 = next((v for v in views if v["saved_view_id"] == view1["saved_view_id"]), None)
        v2 = next((v for v in views if v["saved_view_id"] == view2["saved_view_id"]), None)
        
        assert v1 is not None and v1["is_default"] == False, "First view should have is_default=False"
        assert v2 is not None and v2["is_default"] == True, "Second view should have is_default=True"
        print(f"SUCCESS: Default uniqueness enforced - only one default per view_type+created_by")

    def test_list_saved_views_all(self):
        """GET /api/inventory-ledger/saved-views - lists all saved views"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/saved-views", timeout=10)
        
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "entries" in data
        assert isinstance(data["entries"], list)
        print(f"SUCCESS: Listed {data['total']} saved views")

    def test_list_saved_views_filter_view_type(self):
        """GET /api/inventory-ledger/saved-views?view_type=operations_queue - filters by view_type"""
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/saved-views?view_type=operations_queue",
            timeout=10
        )
        
        assert response.status_code == 200
        data = response.json()
        
        # All entries should have view_type=operations_queue
        for entry in data["entries"]:
            assert entry["view_type"] == "operations_queue"
        print(f"SUCCESS: Filtered {data['total']} operations_queue views")

    def test_update_saved_view_success(self):
        """PATCH /api/inventory-ledger/saved-views/{id} - updates name, notes, filters, sort"""
        # First create a view
        unique_name = f"TEST-Update-{uuid.uuid4().hex[:6]}"
        create_payload = {
            "view_type": "operations_queue",
            "name": unique_name,
            "is_default": False,
            "created_by": "test_update_user",
            "filters": {"entity_type": "sales_order"},
            "sort": {"field": "priority_score", "direction": "desc"},
            "notes": "Original notes"
        }
        r_create = requests.post(f"{BASE_URL}/api/inventory-ledger/saved-views", json=create_payload, timeout=10)
        assert r_create.status_code == 200
        view = r_create.json()
        view_id = view["saved_view_id"]
        self.created_view_ids.append(view_id)
        
        # Update the view
        update_payload = {
            "name": f"{unique_name}-Updated",
            "notes": "Updated notes",
            "filters": {"entity_type": "po_draft", "escalation": "due_soon"},
            "sort": {"field": "latest_activity", "direction": "desc"}
        }
        r_update = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/saved-views/{view_id}",
            json=update_payload,
            timeout=10
        )
        
        assert r_update.status_code == 200
        updated = r_update.json()
        
        assert updated["name"] == f"{unique_name}-Updated"
        assert updated["notes"] == "Updated notes"
        assert updated["filters"]["entity_type"] == "po_draft"
        assert updated["sort"]["field"] == "latest_activity"
        print(f"SUCCESS: Updated saved view {view_id}")

    def test_update_saved_view_set_default(self):
        """PATCH /api/inventory-ledger/saved-views/{id} - setting is_default=true unsets other defaults"""
        # Create two views
        name1 = f"TEST-SetDefault1-{uuid.uuid4().hex[:6]}"
        r1 = requests.post(f"{BASE_URL}/api/inventory-ledger/saved-views", json={
            "view_type": "operations_queue",
            "name": name1,
            "is_default": True,
            "created_by": "test_set_default_user"
        }, timeout=10)
        view1 = r1.json()
        self.created_view_ids.append(view1["saved_view_id"])
        
        name2 = f"TEST-SetDefault2-{uuid.uuid4().hex[:6]}"
        r2 = requests.post(f"{BASE_URL}/api/inventory-ledger/saved-views", json={
            "view_type": "operations_queue",
            "name": name2,
            "is_default": False,
            "created_by": "test_set_default_user"
        }, timeout=10)
        view2 = r2.json()
        self.created_view_ids.append(view2["saved_view_id"])
        
        # Set view2 as default via PATCH
        r_patch = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/saved-views/{view2['saved_view_id']}",
            json={"is_default": True},
            timeout=10
        )
        assert r_patch.status_code == 200
        
        # Verify view2 is now default and view1 is not
        r_list = requests.get(
            f"{BASE_URL}/api/inventory-ledger/saved-views?view_type=operations_queue&created_by=test_set_default_user",
            timeout=10
        )
        views = r_list.json()["entries"]
        
        v1 = next((v for v in views if v["saved_view_id"] == view1["saved_view_id"]), None)
        v2 = next((v for v in views if v["saved_view_id"] == view2["saved_view_id"]), None)
        
        assert v1["is_default"] == False, "View1 should no longer be default"
        assert v2["is_default"] == True, "View2 should be default"
        print(f"SUCCESS: PATCH is_default=true unsets other defaults")

    def test_update_saved_view_not_found(self):
        """PATCH /api/inventory-ledger/saved-views/{id} - returns 404 for non-existent"""
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/saved-views/SV-NONEXISTENT123",
            json={"name": "Test"},
            timeout=10
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print(f"SUCCESS: 404 returned for non-existent view")

    def test_delete_saved_view_success(self):
        """DELETE /api/inventory-ledger/saved-views/{id} - deletes saved view"""
        # Create a view
        unique_name = f"TEST-Delete-{uuid.uuid4().hex[:6]}"
        r_create = requests.post(f"{BASE_URL}/api/inventory-ledger/saved-views", json={
            "view_type": "operations_queue",
            "name": unique_name,
            "is_default": False
        }, timeout=10)
        view = r_create.json()
        view_id = view["saved_view_id"]
        
        # Delete it
        r_delete = requests.delete(f"{BASE_URL}/api/inventory-ledger/saved-views/{view_id}", timeout=10)
        
        assert r_delete.status_code == 200
        data = r_delete.json()
        assert data["deleted"] == view_id
        
        # Verify it's gone
        r_get = requests.get(f"{BASE_URL}/api/inventory-ledger/saved-views?view_type=operations_queue", timeout=10)
        views = r_get.json()["entries"]
        assert not any(v["saved_view_id"] == view_id for v in views), "View should be deleted"
        print(f"SUCCESS: Deleted saved view {view_id}")

    def test_delete_saved_view_not_found(self):
        """DELETE /api/inventory-ledger/saved-views/{id} - returns 404 for non-existent"""
        response = requests.delete(
            f"{BASE_URL}/api/inventory-ledger/saved-views/SV-NONEXISTENT456",
            timeout=10
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print(f"SUCCESS: 404 returned for non-existent view deletion")


class TestOperationsQueueSavedViewsIntegration:
    """Tests for saved_views_count and default_view_name in Operations Queue response"""

    def test_operations_queue_includes_saved_views_count(self):
        """Operations Queue response includes saved_views_count"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=10", timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "saved_views_count" in data, "saved_views_count should be in response"
        assert isinstance(data["saved_views_count"], int)
        print(f"SUCCESS: Operations Queue returns saved_views_count={data['saved_views_count']}")

    def test_operations_queue_includes_default_view_name(self):
        """Operations Queue response includes default_view_name"""
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=10", timeout=30)
        
        assert response.status_code == 200
        data = response.json()
        
        assert "default_view_name" in data, "default_view_name should be in response"
        # It can be empty string if no default view exists
        assert isinstance(data["default_view_name"], str)
        print(f"SUCCESS: Operations Queue returns default_view_name='{data['default_view_name']}'")


class TestRegressionIteration88Escalation:
    """Regression tests for Escalation feature (iteration_88)"""

    def test_escalation_endpoint_working(self):
        """Escalation endpoints still work"""
        # List escalations
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/escalations?limit=5",
            timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data or "entries" in data
        print(f"SUCCESS: Escalation list endpoint working")


class TestRegressionIteration89Assignment:
    """Regression tests for Assignment feature (iteration_89)"""

    def test_assignment_endpoint_working(self):
        """Assignment endpoints still work"""
        # List assignments
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/assignments?limit=5",
            timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data or "entries" in data
        print(f"SUCCESS: Assignment list endpoint working")


class TestRegressionIteration90Activity:
    """Regression tests for Activity Timeline feature (iteration_90)"""

    def test_activity_endpoint_working(self):
        """Activity endpoints still work"""
        # List activities
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/activities?limit=5",
            timeout=10
        )
        assert response.status_code == 200
        data = response.json()
        assert "total" in data or "entries" in data
        print(f"SUCCESS: Activity list endpoint working")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
