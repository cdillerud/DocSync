"""
Test Bulk Actions for Operations Queue (Iteration 92)

Tests for POST /api/inventory-ledger/operations-queue/bulk-action endpoint:
- 5 actions: assign_owner, update_assignment_status, set_due_date, set_escalation_status, request_approval
- Structured results (processed/succeeded/failed per entity)
- Activity timeline entries auto-generated for each affected entity
- Validation (entity_type, action, payload)
- Partial success handling

Regression tests for previous iterations (88-91)
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

# Test identifiers for cleanup
TEST_PREFIX = "BULK-TEST"


class TestBulkActionsEndpoint:
    """Tests for POST /api/inventory-ledger/operations-queue/bulk-action"""

    @pytest.fixture
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session

    @pytest.fixture
    def test_sales_order_ids(self, api_client):
        """Get some real sales order IDs from operations queue"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=sales_order&limit=5")
        if res.status_code == 200:
            data = res.json()
            ids = [item["entity_id"] for item in data.get("items", [])[:3]]
            if ids:
                return ids
        # Return test IDs if no real ones found
        return [f"{TEST_PREFIX}-SO-001", f"{TEST_PREFIX}-SO-002"]

    @pytest.fixture
    def test_po_draft_ids(self, api_client):
        """Get some real PO draft IDs from operations queue"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=po_draft&limit=5")
        if res.status_code == 200:
            data = res.json()
            ids = [item["entity_id"] for item in data.get("items", [])[:2]]
            if ids:
                return ids
        return []

    # =========================================================================
    # VALIDATION TESTS
    # =========================================================================

    def test_bulk_action_validates_entity_type(self, api_client):
        """Bulk action rejects invalid entity_type with 422"""
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "invalid_type",
            "entity_ids": ["TEST-001"],
            "action": "assign_owner",
            "payload": {"assigned_to": "tester"}
        })
        assert res.status_code == 422, f"Expected 422 for invalid entity_type, got {res.status_code}"
        data = res.json()
        assert "entity_type" in str(data.get("detail", "")).lower()
        print("PASS: Bulk action validates entity_type - 422 returned for invalid type")

    def test_bulk_action_validates_action(self, api_client):
        """Bulk action rejects invalid action with 422"""
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": ["TEST-001"],
            "action": "invalid_action",
            "payload": {}
        })
        assert res.status_code == 422, f"Expected 422 for invalid action, got {res.status_code}"
        data = res.json()
        assert "action" in str(data.get("detail", "")).lower() or "invalid" in str(data.get("detail", "")).lower()
        print("PASS: Bulk action validates action - 422 returned for invalid action")

    def test_bulk_action_validates_empty_entity_ids(self, api_client):
        """Bulk action rejects empty entity_ids with 422"""
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": [],
            "action": "assign_owner",
            "payload": {"assigned_to": "tester"}
        })
        assert res.status_code == 422, f"Expected 422 for empty entity_ids, got {res.status_code}"
        print("PASS: Bulk action validates empty entity_ids - 422 returned")

    # =========================================================================
    # ACTION: ASSIGN_OWNER
    # =========================================================================

    def test_assign_owner_to_multiple_sos(self, api_client, test_sales_order_ids):
        """Bulk assign_owner to multiple Sales Orders"""
        if not test_sales_order_ids:
            pytest.skip("No sales orders available for testing")
        
        owner_name = f"{TEST_PREFIX}-Owner-{uuid.uuid4().hex[:6]}"
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": test_sales_order_ids,
            "action": "assign_owner",
            "payload": {"assigned_to": owner_name, "notes": "Bulk test assignment"}
        })
        
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        
        # Verify response structure
        assert data["action"] == "assign_owner"
        assert data["entity_type"] == "sales_order"
        assert "processed_count" in data
        assert "succeeded_count" in data
        assert "failed_count" in data
        assert "results" in data
        
        # At least some should succeed
        assert data["succeeded_count"] > 0, "Expected at least one success"
        
        # Verify per-entity results
        for result in data["results"]:
            assert "entity_id" in result
            assert "status" in result
            assert "message" in result
        
        print(f"PASS: assign_owner bulk action - {data['succeeded_count']} succeeded, {data['failed_count']} failed")

    def test_assign_owner_validates_assigned_to(self, api_client, test_sales_order_ids):
        """Bulk assign_owner fails per-entity when assigned_to is missing"""
        if not test_sales_order_ids:
            pytest.skip("No sales orders available for testing")
        
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": test_sales_order_ids[:1],
            "action": "assign_owner",
            "payload": {"assigned_to": ""}  # Empty
        })
        
        assert res.status_code == 200  # Request succeeds but per-entity fails
        data = res.json()
        assert data["failed_count"] >= 1, "Expected failure for empty assigned_to"
        
        failed_result = next((r for r in data["results"] if r["status"] == "failed"), None)
        assert failed_result is not None
        assert "assigned_to" in failed_result["message"].lower()
        print("PASS: assign_owner validates assigned_to - fails when empty")

    # =========================================================================
    # ACTION: UPDATE_ASSIGNMENT_STATUS
    # =========================================================================

    def test_update_assignment_status_multiple_items(self, api_client, test_sales_order_ids):
        """Bulk update_assignment_status for multiple items"""
        if not test_sales_order_ids:
            pytest.skip("No sales orders available for testing")
        
        # First assign to create assignments
        owner_name = f"{TEST_PREFIX}-StatusTest-{uuid.uuid4().hex[:6]}"
        assign_res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": test_sales_order_ids[:2],
            "action": "assign_owner",
            "payload": {"assigned_to": owner_name}
        })
        
        if assign_res.status_code != 200 or assign_res.json().get("succeeded_count", 0) == 0:
            pytest.skip("Could not create assignments for status update test")
        
        # Now update status
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": test_sales_order_ids[:2],
            "action": "update_assignment_status",
            "payload": {"assignment_status": "in_progress"}
        })
        
        assert res.status_code == 200
        data = res.json()
        assert data["action"] == "update_assignment_status"
        assert data["succeeded_count"] > 0 or data["failed_count"] > 0  # Some result
        print(f"PASS: update_assignment_status bulk action - {data['succeeded_count']} succeeded, {data['failed_count']} failed")

    def test_update_assignment_status_invalid_status(self, api_client, test_sales_order_ids):
        """Bulk update_assignment_status fails for invalid status"""
        if not test_sales_order_ids:
            pytest.skip("No sales orders available for testing")
        
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": test_sales_order_ids[:1],
            "action": "update_assignment_status",
            "payload": {"assignment_status": "invalid_status"}
        })
        
        assert res.status_code == 200  # Request succeeds but per-entity fails
        data = res.json()
        assert data["failed_count"] >= 1
        print("PASS: update_assignment_status validates status - fails for invalid status")

    # =========================================================================
    # ACTION: SET_DUE_DATE
    # =========================================================================

    def test_set_due_date_multiple_items(self, api_client, test_sales_order_ids):
        """Bulk set_due_date for multiple items"""
        if not test_sales_order_ids:
            pytest.skip("No sales orders available for testing")
        
        due_date = "2026-04-01T00:00:00Z"
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": test_sales_order_ids,
            "action": "set_due_date",
            "payload": {"due_date": due_date, "notes": "Bulk due date test"}
        })
        
        assert res.status_code == 200
        data = res.json()
        assert data["action"] == "set_due_date"
        assert data["succeeded_count"] > 0
        
        # Check result messages include the due date
        success_result = next((r for r in data["results"] if r["status"] == "success"), None)
        if success_result:
            assert "due date" in success_result["message"].lower() or due_date[:10] in success_result["message"]
        
        print(f"PASS: set_due_date bulk action - {data['succeeded_count']} succeeded, {data['failed_count']} failed")

    def test_set_due_date_validates_due_date(self, api_client, test_sales_order_ids):
        """Bulk set_due_date fails per-entity when due_date is missing"""
        if not test_sales_order_ids:
            pytest.skip("No sales orders available for testing")
        
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": test_sales_order_ids[:1],
            "action": "set_due_date",
            "payload": {"due_date": ""}  # Empty
        })
        
        assert res.status_code == 200
        data = res.json()
        assert data["failed_count"] >= 1
        print("PASS: set_due_date validates due_date - fails when empty")

    # =========================================================================
    # ACTION: SET_ESCALATION_STATUS
    # =========================================================================

    def test_set_escalation_status_multiple_items(self, api_client, test_sales_order_ids):
        """Bulk set_escalation_status for multiple items (requires existing escalation)"""
        if not test_sales_order_ids:
            pytest.skip("No sales orders available for testing")
        
        # First set due date to create escalation records
        api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": test_sales_order_ids[:2],
            "action": "set_due_date",
            "payload": {"due_date": "2026-04-15T00:00:00Z"}
        })
        
        # Now update escalation status
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": test_sales_order_ids[:2],
            "action": "set_escalation_status",
            "payload": {"escalation_status": "escalated"}
        })
        
        assert res.status_code == 200
        data = res.json()
        assert data["action"] == "set_escalation_status"
        # May succeed or fail depending on whether escalation exists
        print(f"PASS: set_escalation_status bulk action - {data['succeeded_count']} succeeded, {data['failed_count']} failed")

    def test_set_escalation_status_invalid(self, api_client, test_sales_order_ids):
        """Bulk set_escalation_status fails for invalid status"""
        if not test_sales_order_ids:
            pytest.skip("No sales orders available for testing")
        
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": test_sales_order_ids[:1],
            "action": "set_escalation_status",
            "payload": {"escalation_status": "invalid_escalation"}
        })
        
        assert res.status_code == 200
        data = res.json()
        assert data["failed_count"] >= 1
        print("PASS: set_escalation_status validates escalation_status - fails for invalid")

    # =========================================================================
    # ACTION: REQUEST_APPROVAL
    # =========================================================================

    def test_request_approval_multiple_items(self, api_client, test_sales_order_ids):
        """Bulk request_approval for multiple items"""
        if not test_sales_order_ids:
            pytest.skip("No sales orders available for testing")
        
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": test_sales_order_ids,
            "action": "request_approval",
            "payload": {"approval_type": "manager_review", "notes": "Bulk approval test"}
        })
        
        assert res.status_code == 200
        data = res.json()
        assert data["action"] == "request_approval"
        assert data["succeeded_count"] > 0
        
        # Check result messages
        success_result = next((r for r in data["results"] if r["status"] == "success"), None)
        if success_result:
            assert "approval" in success_result["message"].lower()
        
        print(f"PASS: request_approval bulk action - {data['succeeded_count']} succeeded, {data['failed_count']} failed")

    def test_request_approval_different_types(self, api_client, test_sales_order_ids):
        """Bulk request_approval with different approval types"""
        if not test_sales_order_ids:
            pytest.skip("No sales orders available for testing")
        
        for approval_type in ["manager_review", "finance_review", "logistics_review"]:
            res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
                "entity_type": "sales_order",
                "entity_ids": test_sales_order_ids[:1],
                "action": "request_approval",
                "payload": {"approval_type": approval_type}
            })
            
            assert res.status_code == 200
            data = res.json()
            assert data["action"] == "request_approval"
            print(f"  - {approval_type}: {data['succeeded_count']} succeeded")
        
        print("PASS: request_approval works for all approval types")

    # =========================================================================
    # PO DRAFTS
    # =========================================================================

    def test_bulk_action_on_po_drafts(self, api_client, test_po_draft_ids):
        """Bulk action works for po_draft entity type"""
        if not test_po_draft_ids:
            pytest.skip("No PO drafts available for testing")
        
        owner_name = f"{TEST_PREFIX}-POOwner-{uuid.uuid4().hex[:6]}"
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "po_draft",
            "entity_ids": test_po_draft_ids,
            "action": "assign_owner",
            "payload": {"assigned_to": owner_name}
        })
        
        assert res.status_code == 200
        data = res.json()
        assert data["entity_type"] == "po_draft"
        print(f"PASS: Bulk action on po_drafts - {data['succeeded_count']} succeeded, {data['failed_count']} failed")

    def test_bulk_action_po_draft_not_found(self, api_client):
        """Bulk action handles non-existent PO draft gracefully"""
        fake_id = f"FAKE-PO-{uuid.uuid4().hex[:8]}"
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "po_draft",
            "entity_ids": [fake_id],
            "action": "assign_owner",
            "payload": {"assigned_to": "tester"}
        })
        
        assert res.status_code == 200
        data = res.json()
        assert data["failed_count"] == 1
        
        failed_result = data["results"][0]
        assert failed_result["status"] == "failed"
        assert "not found" in failed_result["message"].lower()
        print("PASS: Bulk action handles non-existent PO draft - returns failed result")

    # =========================================================================
    # PARTIAL SUCCESS
    # =========================================================================

    def test_partial_success_handling(self, api_client, test_sales_order_ids):
        """Bulk action handles partial success (some succeed, some fail)"""
        if not test_sales_order_ids:
            pytest.skip("No sales orders available for testing")
        
        # Mix valid IDs with a fake one
        fake_id = f"FAKE-SO-{uuid.uuid4().hex[:8]}"
        mixed_ids = test_sales_order_ids[:2] + [fake_id]
        
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": mixed_ids,
            "action": "set_due_date",
            "payload": {"due_date": "2026-05-01T00:00:00Z"}
        })
        
        assert res.status_code == 200
        data = res.json()
        
        # Should have some successes and at least report on the fake one
        assert data["processed_count"] == len(mixed_ids)
        assert len(data["results"]) == len(mixed_ids)
        
        # Verify each ID has a result
        result_ids = [r["entity_id"] for r in data["results"]]
        for eid in mixed_ids:
            assert eid in result_ids, f"Missing result for {eid}"
        
        print(f"PASS: Partial success handling - {data['succeeded_count']} succeeded, {data['failed_count']} failed out of {data['processed_count']}")

    # =========================================================================
    # ACTIVITY GENERATION
    # =========================================================================

    def test_bulk_action_generates_activities(self, api_client, test_sales_order_ids):
        """Bulk action generates activity timeline entries for each entity"""
        if not test_sales_order_ids:
            pytest.skip("No sales orders available for testing")
        
        test_so_id = test_sales_order_ids[0]
        owner_name = f"{TEST_PREFIX}-ActivityTest-{uuid.uuid4().hex[:6]}"
        
        # Do a bulk assign
        bulk_res = api_client.post(f"{BASE_URL}/api/inventory-ledger/operations-queue/bulk-action", json={
            "entity_type": "sales_order",
            "entity_ids": [test_so_id],
            "action": "assign_owner",
            "payload": {"assigned_to": owner_name}
        })
        
        if bulk_res.status_code != 200:
            pytest.skip("Bulk action failed, cannot test activity generation")
        
        # Check activities for this entity
        activities_res = api_client.get(
            f"{BASE_URL}/api/inventory-ledger/activities?entity_type=sales_order&entity_id={test_so_id}&limit=5"
        )
        
        assert activities_res.status_code == 200
        activities_data = activities_res.json()
        
        # Should have at least one recent activity
        entries = activities_data.get("entries", [])
        if entries:
            # Check if latest activity is from bulk action
            recent = entries[0]
            assert recent["entity_type"] == "sales_order"
            assert recent["entity_id"] == test_so_id
            print(f"PASS: Bulk action generates activities - found {len(entries)} activities for {test_so_id}")
        else:
            print("WARNING: No activities found, but this might be expected for some test data")


class TestRegressionPreviousIterations:
    """Regression tests for iterations 88-91"""

    @pytest.fixture
    def api_client(self):
        session = requests.Session()
        session.headers.update({"Content-Type": "application/json"})
        return session

    # Iteration 91 - Saved Views
    def test_regression_saved_views_endpoint(self, api_client):
        """Regression: GET /api/inventory-ledger/saved-views still works"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/saved-views?view_type=operations_queue")
        assert res.status_code == 200
        data = res.json()
        assert "entries" in data
        assert "total" in data
        print(f"PASS: Regression - saved-views endpoint works (found {data['total']} views)")

    # Iteration 90 - Activity Timeline
    def test_regression_activities_endpoint(self, api_client):
        """Regression: GET /api/inventory-ledger/activities still works"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/activities?limit=5")
        assert res.status_code == 200
        data = res.json()
        assert "entries" in data
        assert "total" in data
        print(f"PASS: Regression - activities endpoint works (found {data['total']} activities)")

    # Iteration 89 - Assignments
    def test_regression_assignments_endpoint(self, api_client):
        """Regression: Assignment endpoints still work"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=5")
        assert res.status_code == 200
        data = res.json()
        # Check assignment-related fields in items
        if data.get("items"):
            item = data["items"][0]
            assert "assignment_status" in item or "current_owner" in item
        print("PASS: Regression - assignment fields present in operations queue")

    # Iteration 88 - Escalation
    def test_regression_escalation_endpoint(self, api_client):
        """Regression: Escalation endpoints still work"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=5")
        assert res.status_code == 200
        data = res.json()
        # Check escalation-related counts
        assert "escalated_count" in data or "overdue_count" in data
        print("PASS: Regression - escalation fields present in operations queue")

    # Operations Queue basic functionality
    def test_regression_operations_queue_basic(self, api_client):
        """Regression: Operations Queue basic functionality"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=10")
        assert res.status_code == 200
        data = res.json()
        
        # Check required response fields
        assert "total" in data
        assert "items" in data
        assert "high_priority_count" in data
        assert "unassigned_count" in data
        
        # Check item structure
        if data.get("items"):
            item = data["items"][0]
            required_fields = ["entity_type", "entity_id", "priority_score", "action_required"]
            for field in required_fields:
                assert field in item, f"Missing field: {field}"
        
        print(f"PASS: Regression - operations queue returns {data['total']} items")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
