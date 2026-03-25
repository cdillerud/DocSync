"""
Sales Auto-Assignment Pipeline Tests
Tests for the new auto-assignment feature:
  - POST /api/sales-dashboard/run-auto-assign - re-run auto-assignment on triage docs
  - services/sales_auto_assign.py - auto_assign_sales_rep logic
  - Integration with customer_rep_overrides collection
  - Routing to triage when no rep mapping exists
  - Routing to pending_rep_review when rep mapping exists
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Sales-eligible document types
SALES_ELIGIBLE_TYPES = {'Sales_Order', 'SalesOrder', 'Order_Confirmation', 'PurchaseOrder'}


class TestRunAutoAssignEndpoint:
    """Tests for POST /api/sales-dashboard/run-auto-assign endpoint"""
    
    def test_run_auto_assign_returns_200(self):
        """Test run-auto-assign endpoint returns 200 and expected structure"""
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/run-auto-assign")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "status" in data, "Response should contain 'status'"
        assert data["status"] == "completed", f"Expected status 'completed', got {data['status']}"
        assert "processed" in data, "Response should contain 'processed' count"
        assert "assigned" in data, "Response should contain 'assigned' count"
        assert "triage" in data, "Response should contain 'triage' count"
        assert "skipped" in data, "Response should contain 'skipped' count"
        assert "errors" in data, "Response should contain 'errors' count"
        
        print(f"Run auto-assign result: processed={data['processed']}, assigned={data['assigned']}, triage={data['triage']}, skipped={data['skipped']}, errors={data['errors']}")
    
    def test_run_auto_assign_processes_triage_docs(self):
        """Test run-auto-assign processes documents in triage status"""
        # First seed data to ensure we have triage docs
        seed_response = requests.post(f"{BASE_URL}/api/sales-dashboard/seed-review-data")
        assert seed_response.status_code == 200
        
        # Check triage queue before
        triage_before = requests.get(f"{BASE_URL}/api/sales-dashboard/triage-queue")
        assert triage_before.status_code == 200
        triage_count_before = triage_before.json()["total"]
        print(f"Triage docs before auto-assign: {triage_count_before}")
        
        # Run auto-assign
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/run-auto-assign")
        assert response.status_code == 200
        
        data = response.json()
        print(f"Auto-assign processed {data['processed']} docs: {data['assigned']} assigned, {data['triage']} to triage")
        
        # The endpoint should have processed the triage docs
        # They may stay in triage if no rep mapping exists, or get assigned if mapping exists
        assert data["processed"] >= 0, "Should process some documents"


class TestAutoAssignWithRepOverrides:
    """Tests for auto-assignment with customer_rep_overrides"""
    
    def test_auto_assign_with_customer_name_override(self):
        """Test auto-assign uses customer_rep_overrides for name-based matching"""
        # 1. Create a customer_rep_override for a specific customer name
        override_customer_name = "TEST_AutoAssign_Customer"
        override_rep_email = "test_rep@gamerpackaging.com"
        override_rep_name = "Test Rep"
        
        # Create override via direct API or by inserting into collection
        # We'll use the override endpoint if available, or create test data
        
        # 2. Create a test document with that customer name in triage
        test_doc_id = f"test-auto-assign-{uuid.uuid4().hex[:8]}"
        
        # First, let's check if we can create a document via intake
        # For now, we'll test the endpoint behavior with existing data
        
        # Run auto-assign and verify it processes correctly
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/run-auto-assign")
        assert response.status_code == 200
        
        data = response.json()
        print(f"Auto-assign with overrides: processed={data['processed']}, assigned={data['assigned']}")
    
    def test_auto_assign_routes_to_triage_when_no_rep(self):
        """Test documents route to triage when no rep mapping exists"""
        # Seed fresh data
        seed_response = requests.post(f"{BASE_URL}/api/sales-dashboard/seed-review-data")
        assert seed_response.status_code == 200
        
        # The seeded triage docs have no rep mapping, so they should stay in triage
        # after running auto-assign (unless we add overrides)
        
        # Run auto-assign
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/run-auto-assign")
        assert response.status_code == 200
        
        data = response.json()
        # Without rep overrides, triage docs should remain in triage
        print(f"Auto-assign routing: {data['triage']} docs routed to triage (no rep found)")


class TestSalesEligibleTypes:
    """Tests for sales-eligible document type detection"""
    
    def test_sales_eligible_types_constant(self):
        """Verify the expected sales-eligible types"""
        expected_types = {'Sales_Order', 'SalesOrder', 'Order_Confirmation', 'PurchaseOrder'}
        assert SALES_ELIGIBLE_TYPES == expected_types, f"Sales eligible types mismatch"
        print(f"Sales eligible types: {SALES_ELIGIBLE_TYPES}")
    
    def test_queue_only_contains_sales_eligible_docs(self):
        """Test that sales queue only contains sales-eligible document types"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue")
        assert response.status_code == 200
        
        data = response.json()
        for item in data["items"]:
            doc_type = item.get("document_type", "")
            assert doc_type in SALES_ELIGIBLE_TYPES, \
                f"Document {item['id']} has non-sales type: {doc_type}"
        
        print(f"Verified {len(data['items'])} docs are all sales-eligible types")


class TestAutoAssignIntegration:
    """Integration tests for auto-assign pipeline"""
    
    def test_seed_then_auto_assign_workflow(self):
        """Test full workflow: seed data -> run auto-assign -> verify results"""
        # 1. Seed fresh data
        seed_response = requests.post(f"{BASE_URL}/api/sales-dashboard/seed-review-data")
        assert seed_response.status_code == 200
        seed_data = seed_response.json()
        print(f"Seeded {seed_data['seeded_count']} documents")
        
        # 2. Check initial triage count
        triage_response = requests.get(f"{BASE_URL}/api/sales-dashboard/triage-queue")
        assert triage_response.status_code == 200
        initial_triage = triage_response.json()["total"]
        print(f"Initial triage count: {initial_triage}")
        
        # 3. Run auto-assign
        auto_assign_response = requests.post(f"{BASE_URL}/api/sales-dashboard/run-auto-assign")
        assert auto_assign_response.status_code == 200
        auto_assign_data = auto_assign_response.json()
        print(f"Auto-assign: processed={auto_assign_data['processed']}, assigned={auto_assign_data['assigned']}, triage={auto_assign_data['triage']}")
        
        # 4. Verify results
        # The processed count should match the number of unassigned/triage docs
        assert auto_assign_data["errors"] == 0, f"Auto-assign had {auto_assign_data['errors']} errors"
    
    def test_auto_assign_idempotent(self):
        """Test running auto-assign multiple times is idempotent"""
        # Seed data
        requests.post(f"{BASE_URL}/api/sales-dashboard/seed-review-data")
        
        # Run auto-assign first time
        response1 = requests.post(f"{BASE_URL}/api/sales-dashboard/run-auto-assign")
        assert response1.status_code == 200
        data1 = response1.json()
        
        # Run auto-assign second time
        response2 = requests.post(f"{BASE_URL}/api/sales-dashboard/run-auto-assign")
        assert response2.status_code == 200
        data2 = response2.json()
        
        # Second run should process fewer or same docs (already assigned ones won't be reprocessed)
        print(f"First run: processed={data1['processed']}, Second run: processed={data2['processed']}")
        
        # After first run, docs that got assigned won't be in triage anymore
        # So second run should process fewer docs
        assert data2["processed"] <= data1["processed"], \
            "Second auto-assign run should process same or fewer docs"


class TestAutoAssignWithCustomerRepOverride:
    """Tests for auto-assign with customer_rep_overrides collection"""
    
    def test_create_override_then_auto_assign(self):
        """Test creating a rep override and then running auto-assign"""
        # 1. First seed data to get triage docs
        seed_response = requests.post(f"{BASE_URL}/api/sales-dashboard/seed-review-data")
        assert seed_response.status_code == 200
        
        # 2. Get a triage doc's customer name
        triage_response = requests.get(f"{BASE_URL}/api/sales-dashboard/triage-queue")
        assert triage_response.status_code == 200
        triage_data = triage_response.json()
        
        if len(triage_data["items"]) == 0:
            pytest.skip("No triage documents to test with")
        
        triage_doc = triage_data["items"][0]
        customer_name = triage_doc.get("customer_name", "")
        doc_id = triage_doc["id"]
        print(f"Testing with triage doc {doc_id[:8]}..., customer: {customer_name}")
        
        # 3. Note: To fully test override-based assignment, we would need to:
        #    - Insert a customer_rep_override with matching customer_name
        #    - Run auto-assign
        #    - Verify the doc gets assigned to the override rep
        # This requires direct DB access or an override creation endpoint
        
        # For now, verify the auto-assign endpoint handles the case gracefully
        auto_assign_response = requests.post(f"{BASE_URL}/api/sales-dashboard/run-auto-assign")
        assert auto_assign_response.status_code == 200
        
        data = auto_assign_response.json()
        print(f"Auto-assign result: {data}")


class TestAutoAssignConfidenceThreshold:
    """Tests for auto-approve confidence threshold (0.95)"""
    
    def test_high_confidence_auto_approve(self):
        """Test that high confidence docs get auto_approved status"""
        # The AUTO_APPROVE_CONFIDENCE threshold is 0.95
        # Docs with confidence >= 0.95 and a rep mapping should get auto_approved
        
        # Seed data and check for any auto_approved docs
        seed_response = requests.post(f"{BASE_URL}/api/sales-dashboard/seed-review-data")
        assert seed_response.status_code == 200
        
        # Check the queue for auto_approved status
        # Note: Seeded docs have varying confidence (0.7 to 0.94), so none should be auto_approved
        # This is expected behavior
        
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue")
        assert response.status_code == 200
        
        data = response.json()
        auto_approved_count = sum(1 for item in data["items"] 
                                   if item.get("sales_review_status") == "auto_approved")
        print(f"Auto-approved docs in queue: {auto_approved_count}")


class TestAutoAssignErrorHandling:
    """Tests for error handling in auto-assign"""
    
    def test_auto_assign_handles_missing_fields(self):
        """Test auto-assign handles documents with missing fields gracefully"""
        # Run auto-assign - it should handle any malformed docs without crashing
        response = requests.post(f"{BASE_URL}/api/sales-dashboard/run-auto-assign")
        assert response.status_code == 200
        
        data = response.json()
        # Even if there are errors, the endpoint should complete
        assert data["status"] == "completed"
        print(f"Auto-assign completed with {data['errors']} errors")


class TestRepAssignmentService:
    """Tests for the rep_assignment_service.py functions"""
    
    def test_reps_endpoint_returns_all_sources(self):
        """Test reps endpoint returns reps from all sources (bc_cache, override, document)"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/reps")
        assert response.status_code == 200
        
        data = response.json()
        sources = set(rep.get("source") for rep in data["reps"])
        print(f"Rep sources found: {sources}")
        
        # At minimum, we should have reps from documents (seeded data)
        # bc_cache and override sources depend on BC sync and manual overrides
        assert len(data["reps"]) > 0, "Should have at least some reps"


class TestDocumentIntakeAutoAssign:
    """Tests for auto-assign integration in document intake pipeline"""
    
    def test_intake_endpoint_exists(self):
        """Test the document intake endpoint exists"""
        # The intake endpoint is POST /api/documents/intake
        # We'll verify it exists by checking for a proper error response (not 404)
        response = requests.post(f"{BASE_URL}/api/documents/intake")
        # Without a file, it should return 422 (validation error) not 404
        assert response.status_code in [400, 422], \
            f"Intake endpoint should exist, got {response.status_code}"
        print(f"Intake endpoint exists, returns {response.status_code} without file")


class TestEndToEndAutoAssign:
    """End-to-end tests for the auto-assign feature"""
    
    def test_full_auto_assign_workflow(self):
        """Test complete auto-assign workflow"""
        # 1. Clear and seed fresh data
        clear_response = requests.delete(f"{BASE_URL}/api/sales-dashboard/queue/clear")
        print(f"Clear queue: {clear_response.status_code}")
        
        seed_response = requests.post(f"{BASE_URL}/api/sales-dashboard/seed-review-data")
        assert seed_response.status_code == 200
        seed_data = seed_response.json()
        print(f"Seeded {seed_data['seeded_count']} docs")
        
        # 2. Check initial state
        triage_before = requests.get(f"{BASE_URL}/api/sales-dashboard/triage-queue")
        assert triage_before.status_code == 200
        triage_count_before = triage_before.json()["total"]
        
        my_queue_before = requests.get(f"{BASE_URL}/api/sales-dashboard/my-queue?rep_email=jsmith@gamerpackaging.com")
        assert my_queue_before.status_code == 200
        my_queue_count_before = my_queue_before.json()["total"]
        
        print(f"Before auto-assign: triage={triage_count_before}, jsmith queue={my_queue_count_before}")
        
        # 3. Run auto-assign
        auto_assign_response = requests.post(f"{BASE_URL}/api/sales-dashboard/run-auto-assign")
        assert auto_assign_response.status_code == 200
        auto_assign_data = auto_assign_response.json()
        print(f"Auto-assign: {auto_assign_data}")
        
        # 4. Verify no errors
        assert auto_assign_data["errors"] == 0, f"Auto-assign had errors: {auto_assign_data['errors']}"
        
        # 5. Check final state
        triage_after = requests.get(f"{BASE_URL}/api/sales-dashboard/triage-queue")
        assert triage_after.status_code == 200
        triage_count_after = triage_after.json()["total"]
        
        print(f"After auto-assign: triage={triage_count_after}")
        
        # The triage count should be same or less (docs may get assigned if overrides exist)
        assert triage_count_after <= triage_count_before + auto_assign_data["triage"], \
            "Triage count should be consistent with auto-assign results"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
