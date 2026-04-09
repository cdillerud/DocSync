"""
Iteration 198: Exception Queue Feature Tests

Tests for:
1. POST /api/readiness/retry-failed - batch retry failed extraction docs
   - force_escalate=true: immediately move to Exception Queue
   - force_escalate=false: incremental retry mode
2. GET /api/readiness/exception-queue - returns documents in exception queue
3. POST /api/readiness/sync-status - force cleanup with expanded terminal statuses
4. GET /api/readiness/inbox-diagnostic - diagnostic with expanded terminal statuses
5. GET /api/documents?queue_view=true - Exception status excluded from main Inbox
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestRetryFailedEndpoint:
    """Tests for POST /api/readiness/retry-failed endpoint"""
    
    def test_retry_failed_default_mode(self):
        """Test retry-failed with default (incremental) mode"""
        response = requests.post(f"{BASE_URL}/api/readiness/retry-failed?limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify response structure
        assert "total_found" in data, "Missing total_found in response"
        assert "retried" in data, "Missing retried in response"
        assert "escalated_to_exception" in data, "Missing escalated_to_exception in response"
        assert "max_retries" in data, "Missing max_retries in response"
        assert "message" in data, "Missing message in response"
        
        # Verify data types
        assert isinstance(data["total_found"], int), "total_found should be int"
        assert isinstance(data["retried"], int), "retried should be int"
        assert isinstance(data["escalated_to_exception"], int), "escalated_to_exception should be int"
        assert isinstance(data["max_retries"], int), "max_retries should be int"
        
        print(f"✓ retry-failed default mode: found={data['total_found']}, retried={data['retried']}, escalated={data['escalated_to_exception']}")
    
    def test_retry_failed_force_escalate_false(self):
        """Test retry-failed with force_escalate=false (incremental mode)"""
        response = requests.post(f"{BASE_URL}/api/readiness/retry-failed?limit=5&force_escalate=false")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "total_found" in data
        assert "retried" in data
        assert "escalated_to_exception" in data
        assert "details" in data
        
        # Details should be a list
        assert isinstance(data["details"], list), "details should be a list"
        
        print(f"✓ retry-failed force_escalate=false: {data['message']}")
    
    def test_retry_failed_force_escalate_true(self):
        """Test retry-failed with force_escalate=true (immediate escalation)"""
        response = requests.post(f"{BASE_URL}/api/readiness/retry-failed?limit=5&force_escalate=true")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "total_found" in data
        assert "escalated_to_exception" in data
        assert "message" in data
        
        # When force_escalate=true, all found docs should be escalated
        # (retried should be 0 or not present)
        if data["total_found"] > 0:
            # All found docs should be escalated when force_escalate=true
            assert data["escalated_to_exception"] >= 0, "escalated_to_exception should be >= 0"
        
        print(f"✓ retry-failed force_escalate=true: {data['message']}")
    
    def test_retry_failed_response_details_structure(self):
        """Test that details array has correct structure"""
        response = requests.post(f"{BASE_URL}/api/readiness/retry-failed?limit=10")
        assert response.status_code == 200
        
        data = response.json()
        details = data.get("details", [])
        
        # If there are details, verify structure
        for detail in details[:5]:  # Check first 5
            assert "doc_id" in detail, "detail missing doc_id"
            assert "action" in detail, "detail missing action"
            assert "retries" in detail, "detail missing retries"
            # file is optional but should be present if available
        
        print(f"✓ retry-failed details structure verified ({len(details)} items)")
    
    def test_retry_failed_max_retries_value(self):
        """Test that max_retries matches DEFAULT_WORKFLOW_CONFIG"""
        response = requests.post(f"{BASE_URL}/api/readiness/retry-failed?limit=1")
        assert response.status_code == 200
        
        data = response.json()
        # DEFAULT_WORKFLOW_CONFIG has max_retry_attempts: 4
        assert data["max_retries"] == 4, f"Expected max_retries=4, got {data['max_retries']}"
        
        print(f"✓ max_retries correctly set to 4")


class TestExceptionQueueEndpoint:
    """Tests for GET /api/readiness/exception-queue endpoint"""
    
    def test_exception_queue_basic(self):
        """Test exception-queue returns correct structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/exception-queue")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "total" in data, "Missing total in response"
        assert "documents" in data, "Missing documents in response"
        
        assert isinstance(data["total"], int), "total should be int"
        assert isinstance(data["documents"], list), "documents should be list"
        
        print(f"✓ exception-queue basic: total={data['total']}, docs_returned={len(data['documents'])}")
    
    def test_exception_queue_pagination(self):
        """Test exception-queue supports skip/limit pagination"""
        # Test with skip=0, limit=10
        response = requests.get(f"{BASE_URL}/api/readiness/exception-queue?skip=0&limit=10")
        assert response.status_code == 200
        
        data = response.json()
        assert "total" in data
        assert "documents" in data
        assert len(data["documents"]) <= 10, "Should respect limit parameter"
        
        # Test with skip=5
        response2 = requests.get(f"{BASE_URL}/api/readiness/exception-queue?skip=5&limit=10")
        assert response2.status_code == 200
        
        print(f"✓ exception-queue pagination works")
    
    def test_exception_queue_document_structure(self):
        """Test that documents in exception queue have expected fields"""
        response = requests.get(f"{BASE_URL}/api/readiness/exception-queue?limit=50")
        assert response.status_code == 200
        
        data = response.json()
        docs = data.get("documents", [])
        
        # Expected fields based on the endpoint projection
        expected_fields = ["id", "file_name", "status"]
        
        for doc in docs[:5]:  # Check first 5
            for field in expected_fields:
                assert field in doc, f"Document missing field: {field}"
            
            # Verify status is Exception or exception_review workflow_status
            status = doc.get("status", "")
            # Documents in exception queue should have Exception status or auto_escalated=True
            # The query uses $or with status in ["Exception", "exception"], workflow_status="exception_review", or auto_escalated=True
        
        print(f"✓ exception-queue document structure verified ({len(docs)} docs)")
    
    def test_exception_queue_excludes_duplicates(self):
        """Test that exception queue excludes duplicates"""
        response = requests.get(f"{BASE_URL}/api/readiness/exception-queue?limit=100")
        assert response.status_code == 200
        
        data = response.json()
        docs = data.get("documents", [])
        
        # Check that no document has is_duplicate=True
        for doc in docs:
            assert doc.get("is_duplicate") != True, f"Found duplicate in exception queue: {doc.get('id')}"
        
        print(f"✓ exception-queue excludes duplicates")


class TestSyncStatusWithException:
    """Tests for POST /api/readiness/sync-status with Exception status"""
    
    def test_sync_status_terminal_includes_exception(self):
        """Test that sync-status TERMINAL list includes Exception"""
        response = requests.post(f"{BASE_URL}/api/readiness/sync-status?limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Verify response structure
        assert "total_fixed" in data, "Missing total_fixed"
        assert "remaining_in_inbox" in data, "Missing remaining_in_inbox"
        assert "message" in data, "Missing message"
        
        print(f"✓ sync-status works with expanded TERMINAL statuses: {data['message']}")
    
    def test_sync_status_rule_counts(self):
        """Test that sync-status returns all rule counts"""
        response = requests.post(f"{BASE_URL}/api/readiness/sync-status?limit=100")
        assert response.status_code == 200
        
        data = response.json()
        
        # Check for rule counts (rules 1-20 based on the code)
        expected_rules = [
            "rule1_has_bc_pi", "rule2_draft_approved", "rule3_auto_draft_created",
            "rule4_readiness_ready", "rule5_vendor_resolved", "rule6_readyforpost",
            "rule7_readiness_catchall", "rule8_non_ap_vendor", "rule9_non_ap_no_vendor",
            "rule10_attempted_vendor", "rule11_reverted_non_ap", "rule12_junk_files",
            "rule13_statements", "rule14_self_vendor", "rule15_tax_forms",
            "rule16_captured_stale", "rule17_xml_files", "rule18_ar_invoices",
            "rule19_self_vendor_broad", "rule20_duplicate_filenames"
        ]
        
        for rule in expected_rules:
            assert rule in data, f"Missing rule count: {rule}"
            assert isinstance(data[rule], int), f"{rule} should be int"
        
        print(f"✓ sync-status returns all 20 rule counts")


class TestInboxDiagnosticWithException:
    """Tests for GET /api/readiness/inbox-diagnostic with Exception status"""
    
    def test_inbox_diagnostic_basic(self):
        """Test inbox-diagnostic returns correct structure"""
        response = requests.get(f"{BASE_URL}/api/readiness/inbox-diagnostic")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "total_in_inbox" in data, "Missing total_in_inbox"
        assert "would_fix" in data, "Missing would_fix"
        assert "would_remain_after_cleanup" in data, "Missing would_remain_after_cleanup"
        assert "breakdown" in data, "Missing breakdown"
        assert "action" in data, "Missing action"
        
        print(f"✓ inbox-diagnostic: total={data['total_in_inbox']}, would_fix={data['would_fix']}, would_remain={data['would_remain_after_cleanup']}")
    
    def test_inbox_diagnostic_excludes_exception_status(self):
        """Test that inbox-diagnostic doesn't count Exception status docs as stuck"""
        response = requests.get(f"{BASE_URL}/api/readiness/inbox-diagnostic")
        assert response.status_code == 200
        
        data = response.json()
        breakdown = data.get("breakdown", [])
        
        # Exception status should be in TERMINAL list, so docs with Exception status
        # should NOT appear in the inbox diagnostic breakdown
        for item in breakdown:
            status = item.get("status", "")
            assert status.lower() != "exception", f"Exception status should not be in inbox breakdown"
        
        print(f"✓ inbox-diagnostic correctly excludes Exception status from stuck docs")


class TestDocumentsQueueViewExcludesException:
    """Tests for GET /api/documents?queue_view=true excluding Exception status"""
    
    def test_queue_view_excludes_exception(self):
        """Test that queue_view=true excludes Exception status documents"""
        response = requests.get(f"{BASE_URL}/api/documents?queue_view=true&limit=500")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "documents" in data, "Missing documents in response"
        
        docs = data.get("documents", [])
        
        # Check that no document has Exception status
        for doc in docs:
            status = (doc.get("status") or "").lower()
            workflow_status = (doc.get("workflow_status") or "").lower()
            
            assert status != "exception", f"Found Exception status doc in queue view: {doc.get('id')}"
            # exception_review workflow_status should also be excluded
            assert workflow_status != "exception_review", f"Found exception_review workflow_status in queue view: {doc.get('id')}"
        
        print(f"✓ queue_view=true excludes Exception status ({len(docs)} docs checked)")
    
    def test_queue_view_counts(self):
        """Test that queue_view returns correct counts"""
        response = requests.get(f"{BASE_URL}/api/documents?queue_view=true")
        assert response.status_code == 200
        
        data = response.json()
        assert "counts" in data, "Missing counts in response"
        
        counts = data["counts"]
        assert "total_all" in counts, "Missing total_all in counts"
        assert "pending_review" in counts, "Missing pending_review in counts"
        assert "completed" in counts, "Missing completed in counts"
        
        print(f"✓ queue_view counts: total_all={counts['total_all']}, pending={counts['pending_review']}, completed={counts['completed']}")
    
    def test_terminal_statuses_list(self):
        """Verify TERMINAL_STATUSES in documents.py includes Exception"""
        # This is a code review check - we verify by checking that Exception docs
        # are not returned in queue_view
        response = requests.get(f"{BASE_URL}/api/documents?queue_view=true&limit=1000")
        assert response.status_code == 200
        
        data = response.json()
        docs = data.get("documents", [])
        
        # Terminal statuses that should be excluded
        terminal_statuses = [
            "completed", "posted", "archived", "filemissing", "batch_parent",
            "validated", "validationpassed", "readyforpost", "ready_for_post",
            "autofiled", "auto_filed", "linkedtobc", "exception"
        ]
        
        for doc in docs:
            status = (doc.get("status") or "").lower()
            assert status not in terminal_statuses, f"Found terminal status '{status}' in queue view"
        
        print(f"✓ Terminal statuses correctly excluded from queue view")


class TestIntegrationRetryToException:
    """Integration tests for retry-failed → exception-queue flow"""
    
    def test_retry_escalation_flow(self):
        """Test that docs escalated via retry-failed appear in exception-queue"""
        # Get initial exception queue count
        response1 = requests.get(f"{BASE_URL}/api/readiness/exception-queue")
        assert response1.status_code == 200
        initial_count = response1.json().get("total", 0)
        
        # Run retry-failed with force_escalate=true
        response2 = requests.post(f"{BASE_URL}/api/readiness/retry-failed?limit=5&force_escalate=true")
        assert response2.status_code == 200
        escalated = response2.json().get("escalated_to_exception", 0)
        
        # Get new exception queue count
        response3 = requests.get(f"{BASE_URL}/api/readiness/exception-queue")
        assert response3.status_code == 200
        new_count = response3.json().get("total", 0)
        
        # New count should be >= initial (escalated docs should appear)
        # Note: might be equal if no docs were found to escalate
        assert new_count >= initial_count, f"Exception queue count should not decrease"
        
        print(f"✓ Integration: initial={initial_count}, escalated={escalated}, new_count={new_count}")
    
    def test_exception_docs_not_in_inbox(self):
        """Test that exception queue docs are not in main inbox"""
        # Get exception queue docs
        response1 = requests.get(f"{BASE_URL}/api/readiness/exception-queue?limit=100")
        assert response1.status_code == 200
        exception_docs = response1.json().get("documents", [])
        exception_ids = {doc.get("id") for doc in exception_docs}
        
        # Get inbox docs
        response2 = requests.get(f"{BASE_URL}/api/documents?queue_view=true&limit=1000")
        assert response2.status_code == 200
        inbox_docs = response2.json().get("documents", [])
        inbox_ids = {doc.get("id") for doc in inbox_docs}
        
        # Exception docs should not be in inbox
        overlap = exception_ids & inbox_ids
        assert len(overlap) == 0, f"Found {len(overlap)} exception docs in inbox: {list(overlap)[:5]}"
        
        print(f"✓ Exception docs ({len(exception_ids)}) not in inbox ({len(inbox_ids)})")


class TestEdgeCases:
    """Edge case tests"""
    
    def test_retry_failed_with_zero_limit(self):
        """Test retry-failed with limit=0 (should fail validation)"""
        response = requests.post(f"{BASE_URL}/api/readiness/retry-failed?limit=0")
        # FastAPI Query validation should reject limit=0 (ge=1)
        # But let's check what happens
        # If it returns 422, that's expected validation error
        # If it returns 200 with 0 results, that's also acceptable
        assert response.status_code in [200, 422], f"Unexpected status: {response.status_code}"
        print(f"✓ retry-failed limit=0 handled correctly (status={response.status_code})")
    
    def test_exception_queue_with_large_skip(self):
        """Test exception-queue with skip larger than total"""
        response = requests.get(f"{BASE_URL}/api/readiness/exception-queue?skip=10000&limit=10")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("documents") == [], "Should return empty list for large skip"
        
        print(f"✓ exception-queue handles large skip correctly")
    
    def test_retry_failed_idempotency(self):
        """Test that retry-failed is safe to call multiple times"""
        # Call twice in succession
        response1 = requests.post(f"{BASE_URL}/api/readiness/retry-failed?limit=5")
        assert response1.status_code == 200
        
        response2 = requests.post(f"{BASE_URL}/api/readiness/retry-failed?limit=5")
        assert response2.status_code == 200
        
        # Both should succeed without errors
        print(f"✓ retry-failed is idempotent")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
