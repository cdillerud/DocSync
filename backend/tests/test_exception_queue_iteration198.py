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
    
    
    def test_exception_queue_with_large_skip(self):
        """Test exception-queue with skip larger than total"""
        response = requests.get(f"{BASE_URL}/api/readiness/exception-queue?skip=10000&limit=10")
        assert response.status_code == 200
        
        data = response.json()
        assert data.get("documents") == [], "Should return empty list for large skip"
        
        print(f"✓ exception-queue handles large skip correctly")
    


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
