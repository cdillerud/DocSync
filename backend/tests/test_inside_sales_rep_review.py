"""
Inside Sales Rep Review API Tests
Tests for the new Inside Sales Rep Review feature endpoints:
  - GET /api/sales-dashboard/reps - list available sales reps
  - GET /api/sales-dashboard/my-queue - docs assigned to a specific rep
  - GET /api/sales-dashboard/triage-queue - unassigned docs
  - POST /api/sales-dashboard/queue/{id}/approve - approve a document
  - POST /api/sales-dashboard/queue/{id}/flag - flag a document with notes
  - POST /api/sales-dashboard/queue/{id}/assign - assign rep to a document
  - POST /api/sales-dashboard/seed-review-data - seed test data
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestSeedReviewData:
    """Tests for POST /api/sales-dashboard/seed-review-data endpoint"""
    
    def test_seed_review_data(self):
        """Test seeding review data creates expected documents and reps"""
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/seed-review-data")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("status") == "success", f"Expected success status, got {data.get('status')}"
        assert "seeded_count" in data, "Response should contain seeded_count"
        assert data["seeded_count"] == 18, f"Expected 18 seeded docs (15 assigned + 3 triage), got {data['seeded_count']}"
        
        # Verify reps list
        assert "reps" in data, "Response should contain reps list"
        expected_reps = ["jsmith@gamerpackaging.com", "mgarcia@gamerpackaging.com", "bwilson@gamerpackaging.com"]
        for rep in expected_reps:
            assert rep in data["reps"], f"Expected rep {rep} in seeded reps"
        
        # Verify status breakdown
        assert "statuses" in data, "Response should contain statuses breakdown"
        statuses = data["statuses"]
        assert statuses.get("pending_rep_review") == 9, f"Expected 9 pending_rep_review, got {statuses.get('pending_rep_review')}"
        assert statuses.get("flagged") == 3, f"Expected 3 flagged, got {statuses.get('flagged')}"
        assert statuses.get("approved") == 3, f"Expected 3 approved, got {statuses.get('approved')}"
        assert statuses.get("triage") == 3, f"Expected 3 triage, got {statuses.get('triage')}"
        
        print(f"Seeded {data['seeded_count']} documents with reps: {data['reps']}")
        print(f"Status breakdown: {statuses}")


class TestListReps:
    """Tests for GET /api/sales-dashboard/reps endpoint"""
    
    def test_reps_returns_list(self):
        """Test reps endpoint returns list of available sales reps"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/reps")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "reps" in data, "Response should contain 'reps' array"
        assert "count" in data, "Response should contain 'count'"
        assert isinstance(data["reps"], list), "reps should be a list"
        
        print(f"Found {data['count']} reps")
    
    def test_reps_structure(self):
        """Test each rep has required fields"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/reps")
        assert response.status_code == 200
        
        data = response.json()
        if len(data["reps"]) > 0:
            rep = data["reps"][0]
            required_fields = ["rep_email", "rep_name", "source"]
            for field in required_fields:
                assert field in rep, f"Rep missing required field: {field}"
            
            print(f"Verified rep structure: {rep['rep_name']} <{rep['rep_email']}> (source: {rep['source']})")
        else:
            print("No reps found to verify structure")
    
    def test_reps_contains_seeded_reps(self):
        """Test reps list contains the seeded test reps"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/reps")
        assert response.status_code == 200
        
        data = response.json()
        rep_emails = [r["rep_email"] for r in data["reps"]]
        
        expected_reps = ["jsmith@gamerpackaging.com", "mgarcia@gamerpackaging.com", "bwilson@gamerpackaging.com"]
        for expected in expected_reps:
            assert expected in rep_emails, f"Expected rep {expected} not found in reps list"
        
        print(f"All expected reps found: {expected_reps}")


class TestMyQueue:
    """Tests for GET /api/sales-dashboard/my-queue endpoint"""
    
    def test_my_queue_requires_rep_email(self):
        """Test my-queue endpoint requires rep_email parameter"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue")
        # Should return 422 for missing required parameter
        assert response.status_code == 422, f"Expected 422 for missing rep_email, got {response.status_code}"
    
    def test_my_queue_returns_items_for_rep(self):
        """Test my-queue returns documents assigned to specific rep"""
        rep_email = "jsmith@gamerpackaging.com"
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email={rep_email}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "items" in data, "Response should contain 'items' array"
        assert "total" in data, "Response should contain 'total' count"
        assert "rep_email" in data, "Response should contain 'rep_email'"
        assert "summary" in data, "Response should contain 'summary'"
        
        assert data["rep_email"] == rep_email, f"rep_email should match request"
        
        # Verify all items are assigned to this rep
        for item in data["items"]:
            assert item.get("assigned_rep_email") == rep_email, \
                f"Item {item['id']} assigned to {item.get('assigned_rep_email')}, expected {rep_email}"
        
        print(f"My queue for {rep_email}: {len(data['items'])} items, total: {data['total']}")
        print(f"Summary: {data['summary']}")
    
    def test_my_queue_item_structure(self):
        """Test my-queue items have all required fields"""
        rep_email = "jsmith@gamerpackaging.com"
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email={rep_email}")
        assert response.status_code == 200
        
        data = response.json()
        if len(data["items"]) > 0:
            item = data["items"][0]
            required_fields = [
                "id", "file_name", "document_type", "assigned_rep_email", 
                "assigned_rep_name", "sales_review_status", "customer_name"
            ]
            for field in required_fields:
                assert field in item, f"Item missing required field: {field}"
            
            # Verify sales_review_status is valid
            valid_statuses = ["pending_rep_review", "approved", "flagged"]
            assert item["sales_review_status"] in valid_statuses, \
                f"Invalid sales_review_status: {item['sales_review_status']}"
            
            print(f"Verified item structure - id: {item['id'][:8]}..., status: {item['sales_review_status']}")
    
    def test_my_queue_filter_by_status(self):
        """Test filtering my-queue by status"""
        rep_email = "jsmith@gamerpackaging.com"
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email={rep_email}&status=pending_rep_review")
        assert response.status_code == 200
        
        data = response.json()
        for item in data["items"]:
            assert item["sales_review_status"] == "pending_rep_review", \
                f"Expected pending_rep_review, got {item['sales_review_status']}"
        
        print(f"Filtered by pending_rep_review: {len(data['items'])} items")
    
    def test_my_queue_summary_counts(self):
        """Test my-queue summary has correct structure"""
        rep_email = "jsmith@gamerpackaging.com"
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email={rep_email}")
        assert response.status_code == 200
        
        data = response.json()
        summary = data["summary"]
        
        required_fields = ["pending_rep_review", "approved", "flagged", "total"]
        for field in required_fields:
            assert field in summary, f"Summary missing field: {field}"
            assert isinstance(summary[field], int), f"Summary field {field} should be int"
        
        print(f"Summary for {rep_email}: pending={summary['pending_rep_review']}, approved={summary['approved']}, flagged={summary['flagged']}, total={summary['total']}")


class TestTriageQueue:
    """Tests for GET /api/sales-dashboard/triage-queue endpoint"""
    
    def test_triage_queue_returns_unassigned_docs(self):
        """Test triage-queue returns unassigned documents"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/triage-queue")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "items" in data, "Response should contain 'items' array"
        assert "total" in data, "Response should contain 'total' count"
        
        # Verify all items are unassigned (no rep email or triage status)
        for item in data["items"]:
            is_unassigned = not item.get("assigned_rep_email") or item.get("assigned_rep_email") == ""
            is_triage = item.get("sales_review_status") == "triage"
            assert is_unassigned or is_triage, \
                f"Triage item {item['id']} should be unassigned or have triage status"
        
        print(f"Triage queue: {len(data['items'])} unassigned items, total: {data['total']}")
    
    def test_triage_queue_item_structure(self):
        """Test triage-queue items have required fields"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/triage-queue")
        assert response.status_code == 200
        
        data = response.json()
        if len(data["items"]) > 0:
            item = data["items"][0]
            required_fields = ["id", "file_name", "document_type", "sales_review_status", "customer_name"]
            for field in required_fields:
                assert field in item, f"Triage item missing required field: {field}"
            
            print(f"Verified triage item: {item['file_name']}, customer: {item.get('customer_name')}")
    
    def test_triage_queue_search(self):
        """Test triage-queue search functionality"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/triage-queue?search=UNKNOWN")
        assert response.status_code == 200
        
        data = response.json()
        print(f"Triage search 'UNKNOWN': {len(data['items'])} items found")


class TestApproveDocument:
    """Tests for POST /api/sales-dashboard/queue/{id}/approve endpoint"""
    
    def test_approve_document_success(self):
        """Test approving a pending document"""
        # First get a pending document from my-queue
        rep_email = "jsmith@gamerpackaging.com"
        queue_response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email={rep_email}&status=pending_rep_review")
        assert queue_response.status_code == 200
        
        queue_data = queue_response.json()
        if len(queue_data["items"]) == 0:
            pytest.skip("No pending documents to approve")
        
        doc_id = queue_data["items"][0]["id"]
        
        # Approve the document
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/queue/{doc_id}/approve")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("status") == "approved", f"Expected status 'approved', got {data.get('status')}"
        assert data.get("doc_id") == doc_id, f"doc_id should match"
        assert "approved_at" in data, "Response should contain approved_at timestamp"
        
        print(f"Approved document {doc_id[:8]}... at {data['approved_at']}")
        
        # Verify the document status changed
        verify_response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email={rep_email}")
        verify_data = verify_response.json()
        approved_doc = next((d for d in verify_data["items"] if d["id"] == doc_id), None)
        if approved_doc:
            assert approved_doc["sales_review_status"] == "approved", \
                f"Document status should be 'approved', got {approved_doc['sales_review_status']}"
    
    def test_approve_nonexistent_document(self):
        """Test approving a non-existent document returns 404"""
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/queue/nonexistent-id-12345/approve")
        assert response.status_code == 404, f"Expected 404 for non-existent doc, got {response.status_code}"


class TestFlagDocument:
    """Tests for POST /api/sales-dashboard/queue/{id}/flag endpoint"""
    
    def test_flag_document_success(self):
        """Test flagging a pending document with notes"""
        # First get a pending document
        rep_email = "mgarcia@gamerpackaging.com"
        queue_response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email={rep_email}&status=pending_rep_review")
        assert queue_response.status_code == 200
        
        queue_data = queue_response.json()
        if len(queue_data["items"]) == 0:
            pytest.skip("No pending documents to flag")
        
        doc_id = queue_data["items"][0]["id"]
        flag_notes = "TEST: Customer requested different ship date"
        
        # Flag the document
        response = requests.post(
            f"{BASE_URL}/api/sales-dashboard/queue/{doc_id}/flag",
            json={"notes": flag_notes}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("status") == "flagged", f"Expected status 'flagged', got {data.get('status')}"
        assert data.get("doc_id") == doc_id, f"doc_id should match"
        assert data.get("notes") == flag_notes, f"notes should match"
        assert "flagged_at" in data, "Response should contain flagged_at timestamp"
        
        print(f"Flagged document {doc_id[:8]}... with notes: {flag_notes}")
        
        # Verify the document status and notes changed
        verify_response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email={rep_email}")
        verify_data = verify_response.json()
        flagged_doc = next((d for d in verify_data["items"] if d["id"] == doc_id), None)
        if flagged_doc:
            assert flagged_doc["sales_review_status"] == "flagged", \
                f"Document status should be 'flagged', got {flagged_doc['sales_review_status']}"
            assert flagged_doc.get("flag_notes") == flag_notes, \
                f"flag_notes should match"
    
    def test_flag_document_empty_notes(self):
        """Test flagging a document with empty notes"""
        rep_email = "bwilson@gamerpackaging.com"
        queue_response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email={rep_email}&status=pending_rep_review")
        assert queue_response.status_code == 200
        
        queue_data = queue_response.json()
        if len(queue_data["items"]) == 0:
            pytest.skip("No pending documents to flag")
        
        doc_id = queue_data["items"][0]["id"]
        
        # Flag with empty notes
        response = requests.post(
            f"{BASE_URL}/api/sales-dashboard/queue/{doc_id}/flag",
            json={"notes": ""}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("status") == "flagged"
        print(f"Flagged document {doc_id[:8]}... with empty notes")
    
    def test_flag_nonexistent_document(self):
        """Test flagging a non-existent document returns 404"""
        response = requests.post(
            f"{BASE_URL}/api/sales-dashboard/queue/nonexistent-id-12345/flag",
            json={"notes": "test"}
        )
        assert response.status_code == 404, f"Expected 404 for non-existent doc, got {response.status_code}"


class TestAssignDocument:
    """Tests for POST /api/sales-dashboard/queue/{id}/assign endpoint"""
    
    def test_assign_document_success(self):
        """Test assigning a triage document to a rep"""
        # First get a triage document
        triage_response = requests.get(f"{BASE_URL}/api/sales-dashboard/triage-queue")
        assert triage_response.status_code == 200
        
        triage_data = triage_response.json()
        if len(triage_data["items"]) == 0:
            pytest.skip("No triage documents to assign")
        
        doc_id = triage_data["items"][0]["id"]
        assign_email = "jsmith@gamerpackaging.com"
        assign_name = "John Smith"
        
        # Assign the document
        response = requests.post(
            f"{BASE_URL}/api/sales-dashboard/queue/{doc_id}/assign",
            json={"rep_email": assign_email, "rep_name": assign_name}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert data.get("status") == "assigned", f"Expected status 'assigned', got {data.get('status')}"
        assert data.get("doc_id") == doc_id, f"doc_id should match"
        assert data.get("rep_email") == assign_email, f"rep_email should match"
        assert data.get("rep_name") == assign_name, f"rep_name should match"
        
        print(f"Assigned document {doc_id[:8]}... to {assign_name} <{assign_email}>")
        
        # Verify the document is now in the rep's queue
        verify_response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email={assign_email}")
        verify_data = verify_response.json()
        assigned_doc = next((d for d in verify_data["items"] if d["id"] == doc_id), None)
        assert assigned_doc is not None, f"Document should appear in rep's queue after assignment"
        assert assigned_doc["assigned_rep_email"] == assign_email
        assert assigned_doc["sales_review_status"] == "pending_rep_review"
        
        # Verify document is no longer in triage queue
        triage_verify = requests.get(f"{BASE_URL}/api/sales-dashboard/triage-queue")
        triage_verify_data = triage_verify.json()
        still_in_triage = any(d["id"] == doc_id for d in triage_verify_data["items"])
        assert not still_in_triage, "Document should no longer be in triage queue after assignment"
    
    def test_assign_nonexistent_document(self):
        """Test assigning a non-existent document returns 404"""
        response = requests.post(
            f"{BASE_URL}/api/sales-dashboard/queue/nonexistent-id-12345/assign",
            json={"rep_email": "test@example.com", "rep_name": "Test User"}
        )
        assert response.status_code == 404, f"Expected 404 for non-existent doc, got {response.status_code}"


class TestEndToEndWorkflow:
    """End-to-end workflow tests for the Inside Sales Rep Review feature"""
    
    def test_full_workflow_approve(self):
        """Test full workflow: seed -> view queue -> approve"""
        # 1. Seed data
        seed_response = requests.post(f"{BASE_URL}/api/sales-dashboard/seed-review-data")
        assert seed_response.status_code == 200
        
        # 2. Get reps
        reps_response = requests.get(f"{BASE_URL}/api/sales-dashboard/reps")
        assert reps_response.status_code == 200
        reps_data = reps_response.json()
        assert len(reps_data["reps"]) >= 3
        
        # 3. View my-queue for first rep
        rep_email = "jsmith@gamerpackaging.com"
        queue_response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email={rep_email}")
        assert queue_response.status_code == 200
        queue_data = queue_response.json()
        
        # 4. Approve a pending document
        pending_docs = [d for d in queue_data["items"] if d["sales_review_status"] == "pending_rep_review"]
        if len(pending_docs) > 0:
            doc_id = pending_docs[0]["id"]
            approve_response = requests.post(f"{BASE_URL}/api/sales-dashboard/queue/{doc_id}/approve")
            assert approve_response.status_code == 200
            print(f"Full workflow test: Approved document {doc_id[:8]}...")
        else:
            print("No pending documents to approve in workflow test")
    
    def test_full_workflow_triage_assign(self):
        """Test full workflow: view triage -> assign -> verify in my-queue"""
        # 1. View triage queue
        triage_response = requests.get(f"{BASE_URL}/api/sales-dashboard/triage-queue")
        assert triage_response.status_code == 200
        triage_data = triage_response.json()
        
        if len(triage_data["items"]) == 0:
            pytest.skip("No triage documents for workflow test")
        
        doc_id = triage_data["items"][0]["id"]
        assign_email = "mgarcia@gamerpackaging.com"
        
        # 2. Assign to rep
        assign_response = requests.post(
            f"{BASE_URL}/api/sales-dashboard/queue/{doc_id}/assign",
            json={"rep_email": assign_email, "rep_name": "Maria Garcia"}
        )
        assert assign_response.status_code == 200
        
        # 3. Verify in rep's queue
        queue_response = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email={assign_email}")
        assert queue_response.status_code == 200
        queue_data = queue_response.json()
        
        assigned_doc = next((d for d in queue_data["items"] if d["id"] == doc_id), None)
        assert assigned_doc is not None, "Assigned document should appear in rep's queue"
        
        print(f"Full workflow test: Assigned {doc_id[:8]}... to Maria Garcia and verified in queue")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
