"""
Test Activity Timeline Feature (Iteration 90)
- POST /api/inventory-ledger/activities - manual notes
- GET /api/inventory-ledger/activities - list with filters
- System auto-generated activities (assignments, approvals, documents, escalations)
- Activity enrichment in Operations Queue and SO/PO detail
- stale_days filter, sort_by=latest_activity, dashboard counts
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestManualNoteEndpoints:
    """Test POST/GET /api/inventory-ledger/activities for manual notes"""

    def test_create_manual_note_success(self, api_client):
        """POST creates manual note with activity_type='note'"""
        # Use existing test SO from iteration_89
        payload = {
            "entity_type": "sales_order",
            "entity_id": "TEST-ACTIVITY-001",
            "activity_type": "note",
            "title": "Test manual note",
            "body": "This is a test note body",
            "created_by": "test_user"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/activities", json=payload)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert "activity_id" in data
        assert data["activity_id"].startswith("ACT-")
        assert data["entity_type"] == "sales_order"
        assert data["entity_id"] == "TEST-ACTIVITY-001"
        assert data["activity_type"] == "note"
        assert data["title"] == "Test manual note"
        assert data["body"] == "This is a test note body"
        assert data["created_by"] == "test_user"
        assert "created_at" in data
        print(f"Created activity: {data['activity_id']}")

    def test_create_note_invalid_entity_type(self, api_client):
        """POST returns 422 for invalid entity_type"""
        payload = {
            "entity_type": "invalid_type",
            "entity_id": "TEST-001",
            "title": "Test note"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/activities", json=payload)
        assert res.status_code == 422, f"Expected 422, got {res.status_code}"
        data = res.json()
        assert "entity_type must be sales_order or po_draft" in data.get("detail", "")

    def test_create_note_invalid_activity_type(self, api_client):
        """POST returns 422 for invalid activity_type"""
        payload = {
            "entity_type": "sales_order",
            "entity_id": "TEST-001",
            "activity_type": "invalid_activity",
            "title": "Test note"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/activities", json=payload)
        assert res.status_code == 422, f"Expected 422, got {res.status_code}"
        data = res.json()
        assert "Invalid activity_type" in data.get("detail", "")

    def test_create_note_po_draft_not_found(self, api_client):
        """POST returns 404 for non-existent PO Draft"""
        payload = {
            "entity_type": "po_draft",
            "entity_id": "NONEXISTENT-PO-DRAFT-999",
            "title": "Test note"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/activities", json=payload)
        assert res.status_code == 404, f"Expected 404, got {res.status_code}"
        data = res.json()
        assert "PO Draft" in data.get("detail", "") and "not found" in data.get("detail", "")


class TestListActivitiesEndpoint:
    """Test GET /api/inventory-ledger/activities listing and filters"""

    def test_list_activities_newest_first(self, api_client):
        """GET lists activities in newest-first order"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/activities", params={"limit": 20})
        assert res.status_code == 200
        data = res.json()
        assert "total" in data
        assert "entries" in data
        assert isinstance(data["entries"], list)
        # Check descending order
        if len(data["entries"]) >= 2:
            dates = [e.get("created_at", "") for e in data["entries"]]
            assert dates == sorted(dates, reverse=True), "Activities should be sorted newest first"
        print(f"Total activities: {data['total']}, returned: {len(data['entries'])}")

    def test_filter_by_entity_type_and_id(self, api_client):
        """GET filters by entity_type and entity_id"""
        # First create a note with known entity
        payload = {
            "entity_type": "sales_order",
            "entity_id": "TEST-FILTER-SO-001",
            "title": "Filter test note"
        }
        api_client.post(f"{BASE_URL}/api/inventory-ledger/activities", json=payload)

        # Now filter
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/activities", params={
            "entity_type": "sales_order",
            "entity_id": "TEST-FILTER-SO-001"
        })
        assert res.status_code == 200
        data = res.json()
        for entry in data["entries"]:
            assert entry["entity_type"] == "sales_order"
            assert entry["entity_id"] == "TEST-FILTER-SO-001"
        print(f"Filtered activities for TEST-FILTER-SO-001: {data['total']}")

    def test_filter_by_activity_type(self, api_client):
        """GET filters by activity_type"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/activities", params={
            "activity_type": "note"
        })
        assert res.status_code == 200
        data = res.json()
        for entry in data["entries"]:
            assert entry["activity_type"] == "note"
        print(f"Activities of type 'note': {data['total']}")


class TestSystemActivityAutoGeneration:
    """Test that system activities are auto-generated for workflow events"""

    def test_assignment_generates_activity(self, api_client):
        """Creating an assignment should auto-generate an 'assignment' activity"""
        entity_id = f"TEST-ASGN-ACT-{datetime.now().strftime('%H%M%S')}"
        
        # Create assignment
        assign_payload = {
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "assigned_to": "test_owner",
            "assigned_by": "system_test"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/assignments", json=assign_payload)
        assert res.status_code == 200, f"Assignment creation failed: {res.text}"

        # Check for auto-generated activity
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/activities", params={
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "activity_type": "assignment"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 1, "Assignment should create an activity"
        assert any("Assigned to test_owner" in e.get("title", "") for e in data["entries"])
        print(f"Assignment activity auto-generated for {entity_id}")

    def test_approval_request_generates_activity(self, api_client):
        """Requesting approval should auto-generate an 'approval' activity"""
        entity_id = f"TEST-APPR-ACT-{datetime.now().strftime('%H%M%S')}"
        
        # Request approval (approval_type must be 'sales_order' or 'purchase_order')
        approval_payload = {
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "approval_type": "sales_order",
            "requested_by": "test_requester"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/approvals/request", json=approval_payload)
        assert res.status_code == 200, f"Approval request failed: {res.text}"
        approval_id = res.json().get("approval_id")

        # Check for auto-generated activity
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/activities", params={
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "activity_type": "approval"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 1, "Approval request should create an activity"
        assert any("Approval requested" in e.get("title", "") for e in data["entries"])
        print(f"Approval activity auto-generated for {entity_id}")
        return approval_id, entity_id

    def test_approval_decision_generates_activity(self, api_client):
        """Approving/rejecting should auto-generate an 'approval' activity"""
        # Create new approval request first (approval_type must be 'sales_order' or 'purchase_order')
        entity_id = f"TEST-DEC-ACT-{datetime.now().strftime('%H%M%S')}"
        approval_payload = {
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "approval_type": "sales_order",
            "requested_by": "test_requester"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/approvals/request", json=approval_payload)
        assert res.status_code == 200
        approval_id = res.json().get("approval_id")

        # Approve it
        decide_payload = {
            "approval_status": "approved",
            "approved_by": "test_approver"
        }
        res = api_client.patch(f"{BASE_URL}/api/inventory-ledger/approvals/{approval_id}", json=decide_payload)
        assert res.status_code == 200

        # Check for decision activity
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/activities", params={
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "activity_type": "approval"
        })
        data = res.json()
        assert any("Approval approved" in e.get("title", "") for e in data["entries"])
        print(f"Approval decision activity auto-generated for {entity_id}")

    def test_document_link_generates_activity(self, api_client):
        """Linking a document should auto-generate a 'document' activity"""
        entity_id = f"TEST-DOC-ACT-{datetime.now().strftime('%H%M%S')}"
        
        # Create document link
        doc_payload = {
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "document_type": "customer_po",
            "document_name": "Test Customer PO.pdf"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/document-links", json=doc_payload)
        assert res.status_code == 200, f"Document link creation failed: {res.text}"

        # Check for auto-generated activity
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/activities", params={
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "activity_type": "document"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 1, "Document link should create an activity"
        assert any("Document linked" in e.get("title", "") for e in data["entries"])
        print(f"Document activity auto-generated for {entity_id}")

    def test_escalation_generates_activity(self, api_client):
        """Creating an escalation should auto-generate an 'escalation' activity"""
        entity_id = f"TEST-ESC-ACT-{datetime.now().strftime('%H%M%S')}"
        future_date = (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d")
        
        # Create escalation
        esc_payload = {
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "due_date": future_date,
            "notes": "Test escalation"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=esc_payload)
        assert res.status_code == 200, f"Escalation creation failed: {res.text}"

        # Check for auto-generated activity
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/activities", params={
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "activity_type": "escalation"
        })
        assert res.status_code == 200
        data = res.json()
        assert data["total"] >= 1, "Escalation should create an activity"
        print(f"Escalation activity auto-generated for {entity_id}")


class TestOperationsQueueActivityEnrichment:
    """Test activity enrichment in Operations Queue"""

    def test_operations_queue_returns_activity_fields(self, api_client):
        """Operations Queue items include latest_activity_at, latest_activity_type, activity_count"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue", params={"limit": 10})
        assert res.status_code == 200
        data = res.json()
        
        # Check response-level activity counts
        assert "recent_activity_today" in data, "Missing recent_activity_today in response"
        assert "no_recent_activity_7d" in data, "Missing no_recent_activity_7d in response"
        print(f"Activity counts - Today: {data['recent_activity_today']}, Stale 7d: {data['no_recent_activity_7d']}")
        
        # Check item-level enrichment (check first item if exists)
        if data["items"]:
            item = data["items"][0]
            assert "latest_activity_at" in item, "Item missing latest_activity_at"
            assert "latest_activity_type" in item, "Item missing latest_activity_type"
            assert "activity_count" in item, "Item missing activity_count"
            print(f"Sample item activity: type={item.get('latest_activity_type')}, count={item.get('activity_count')}")

    def test_sort_by_latest_activity(self, api_client):
        """sort_by=latest_activity sorts by most recent activity first"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue", params={
            "sort_by": "latest_activity",
            "limit": 20
        })
        assert res.status_code == 200
        data = res.json()
        
        if len(data["items"]) >= 2:
            # Items with activity should be sorted by latest_activity_at descending
            items_with_activity = [i for i in data["items"] if i.get("latest_activity_at")]
            if len(items_with_activity) >= 2:
                dates = [i["latest_activity_at"] for i in items_with_activity]
                assert dates == sorted(dates, reverse=True), "Items should be sorted by latest_activity_at descending"
        print("sort_by=latest_activity verified")

    def test_stale_days_filter(self, api_client):
        """stale_days=7 filters for items with no recent activity"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue", params={
            "stale_days": 7,
            "limit": 50
        })
        assert res.status_code == 200
        data = res.json()
        
        # All items should have no activity or activity older than 7 days
        cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
        for item in data["items"]:
            act_at = item.get("latest_activity_at", "")
            if act_at:
                assert act_at < cutoff, f"Item {item['entity_id']} has recent activity but passed stale filter"
        print(f"stale_days=7 filter returned {data['total']} items")


class TestRegressionEscalationFeature:
    """Regression tests for Escalation endpoints (iteration_88)"""

    def test_create_escalation_success(self, api_client):
        """POST /escalations creates escalation with derived status"""
        entity_id = f"TEST-ESC-REG-{datetime.now().strftime('%H%M%S')}"
        future_date = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        
        payload = {
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "due_date": future_date,
            "notes": "Regression test"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["escalation_status"] == "on_track"  # Future date > 3 days
        print(f"Escalation regression test passed: {data['escalation_id']}")

    def test_list_escalations(self, api_client):
        """GET /escalations lists escalations"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/escalations", params={
            "entity_type": "sales_order"
        })
        assert res.status_code == 200
        data = res.json()
        assert "total" in data
        assert "entries" in data
        print(f"Escalation list regression: {data['total']} entries")


class TestRegressionAssignmentFeature:
    """Regression tests for Assignment endpoints (iteration_89)"""

    def test_create_assignment_success(self, api_client):
        """POST /assignments creates assignment with default status"""
        entity_id = f"TEST-ASGN-REG-{datetime.now().strftime('%H%M%S')}"
        
        payload = {
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "assigned_to": "regression_owner",
            "assigned_by": "regression_test"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/assignments", json=payload)
        assert res.status_code == 200
        data = res.json()
        assert data["assignment_status"] == "assigned"
        print(f"Assignment regression test passed: {data['assignment_id']}")

    def test_list_assignments(self, api_client):
        """GET /assignments lists assignments"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/assignments")
        assert res.status_code == 200
        data = res.json()
        assert "total" in data
        assert "entries" in data
        print(f"Assignment list regression: {data['total']} entries")

    def test_patch_assignment(self, api_client):
        """PATCH /assignments/{id} updates assignment"""
        # Create assignment first
        entity_id = f"TEST-PATCH-{datetime.now().strftime('%H%M%S')}"
        create_res = api_client.post(f"{BASE_URL}/api/inventory-ledger/assignments", json={
            "entity_type": "sales_order",
            "entity_id": entity_id,
            "assigned_to": "initial_owner",
            "assigned_by": "test"
        })
        assert create_res.status_code == 200
        assignment_id = create_res.json()["assignment_id"]

        # Update it
        patch_res = api_client.patch(f"{BASE_URL}/api/inventory-ledger/assignments/{assignment_id}", json={
            "assignment_status": "in_progress"
        })
        assert patch_res.status_code == 200
        assert patch_res.json()["assignment_status"] == "in_progress"
        print(f"Assignment PATCH regression passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
