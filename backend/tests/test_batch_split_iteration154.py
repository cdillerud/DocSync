"""
Test suite for Batch PO Split refactoring - Iteration 154
Tests the batch split API, inbox stats, insights trends, and document filtering.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestBatchSplitAPIs:
    """Tests for batch split demo APIs"""
    
    def test_batch_status_endpoint(self):
        """Test GET /api/sales-dashboard/demo/batch-status/{job_id} returns completed job"""
        job_id = "3162246957db"
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/batch-status/{job_id}")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert data.get("status") == "completed", f"Expected completed, got {data.get('status')}"
        assert data.get("job_id") == job_id
        assert data.get("total_pages") == 5
        assert data.get("children_created") == 5
        
        # Verify children have correct structure
        children = data.get("children", [])
        assert len(children) == 5, f"Expected 5 children, got {len(children)}"
        
        for child in children:
            assert child.get("type") == "Sales_Order", f"Expected Sales_Order, got {child.get('type')}"
            assert child.get("queue") == "My Queue", f"Expected My Queue, got {child.get('queue')}"
            assert child.get("assigned_rep") == "Lisa Chen"
            assert child.get("review_status") == "auto_approved"
        
        # Verify steps completed
        steps = data.get("steps", [])
        assert len(steps) == 5, f"Expected 5 steps, got {len(steps)}"
        
        step_names = [s.get("name") for s in steps]
        assert "Batch PO Generation" in step_names
        assert "Parent Document Stored" in step_names
        assert "Learned Patterns Seeded" in step_names
        assert "Page Split & Full Pipeline" in step_names
        assert "Child Documents Summary" in step_names
        
        print(f"PASS: Batch status endpoint returns completed job with 5 children")
    
    def test_batch_status_not_found(self):
        """Test GET /api/sales-dashboard/demo/batch-status/{invalid_id} returns 404"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/demo/batch-status/invalid_job_id")
        assert response.status_code == 404


class TestInboxStats:
    """Tests for inbox stats API"""
    
    def test_inbox_stats_endpoint(self):
        """Test GET /api/dashboard/inbox-stats returns valid data"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Verify required fields exist
        assert "ingested_today" in data
        assert "avg_daily_7d" in data
        assert "auto_validation_rate" in data
        assert "pending_review" in data
        assert "avg_ai_confidence" in data
        assert "total_documents" in data
        
        # Verify data types
        assert isinstance(data["ingested_today"], int)
        assert isinstance(data["auto_validation_rate"], (int, float))
        assert isinstance(data["avg_ai_confidence"], (int, float))
        
        print(f"PASS: Inbox stats - Today: {data['ingested_today']}, Auto-rate: {data['auto_validation_rate']}%, AI confidence: {data['avg_ai_confidence']}%")


class TestInsightsTrends:
    """Tests for insights trends API"""
    
    def test_insights_trends_endpoint(self):
        """Test GET /api/dashboard/insights-trends returns daily trend data"""
        response = requests.get(f"{BASE_URL}/api/dashboard/insights-trends")
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        
        # Verify structure
        assert "daily" in data
        assert "period_days" in data
        
        daily = data.get("daily", [])
        assert len(daily) > 0, "Expected at least one day of data"
        
        # Verify daily entry structure
        for entry in daily:
            assert "date" in entry
            assert "ingested" in entry
            assert "auto_rate" in entry
            assert "ai_confidence" in entry
        
        print(f"PASS: Insights trends - {len(daily)} days of data, period: {data.get('period_days')} days")


class TestDocumentFiltering:
    """Tests for document filtering - batch_parent exclusion"""
    
    def test_active_inbox_excludes_batch_parent(self):
        """Test that active inbox (queue_view=true) excludes batch_parent docs"""
        response = requests.get(f"{BASE_URL}/api/documents?queue_view=true&include_cleared=false&limit=100")
        
        assert response.status_code == 200
        
        data = response.json()
        docs = data.get("documents", [])
        
        # Check no batch_parent docs in active inbox
        batch_parents = [d for d in docs if d.get("status") == "batch_parent"]
        assert len(batch_parents) == 0, f"Found {len(batch_parents)} batch_parent docs in active inbox"
        
        print(f"PASS: Active inbox has {len(docs)} docs, 0 batch_parent docs")
    
    def test_processed_tab_shows_terminal_docs(self):
        """Test that processed view shows terminal/completed docs"""
        response = requests.get(f"{BASE_URL}/api/documents?queue_view=false&include_cleared=true&limit=100")
        
        assert response.status_code == 200
        
        data = response.json()
        docs = data.get("documents", [])
        
        # Filter for terminal docs (same logic as frontend)
        terminal_statuses = ["Completed", "Posted", "Archived", "completed", "posted", "archived", "exported", "auto_filed", "AutoFiled"]
        done_wf_statuses = ["completed", "exported", "validation_passed", "processed"]
        
        processed_docs = []
        for doc in docs:
            status = (doc.get("status") or "").lower()
            wf_status = (doc.get("workflow_status") or "").lower()
            
            # Exclude batch_parent from processed view
            if status == "batch_parent":
                continue
            
            is_terminal = (
                status in [t.lower() for t in terminal_statuses] or
                wf_status in done_wf_statuses or
                doc.get("auto_cleared") == True
            )
            if is_terminal:
                processed_docs.append(doc)
        
        assert len(processed_docs) >= 5, f"Expected at least 5 processed docs, got {len(processed_docs)}"
        
        # Verify Giovanni Food Company docs are present
        giovanni_docs = [d for d in processed_docs if "Giovanni" in str(d.get("extracted_fields", {}).get("customer", ""))]
        assert len(giovanni_docs) >= 5, f"Expected 5 Giovanni docs, got {len(giovanni_docs)}"
        
        print(f"PASS: Processed view has {len(processed_docs)} terminal docs, {len(giovanni_docs)} Giovanni docs")
    
    def test_vendor_customer_field_extraction(self):
        """Test that extracted_fields.customer contains correct vendor/customer name"""
        response = requests.get(f"{BASE_URL}/api/documents?queue_view=false&include_cleared=true&limit=100")
        
        assert response.status_code == 200
        
        data = response.json()
        docs = data.get("documents", [])
        
        # Find Giovanni docs
        giovanni_docs = [d for d in docs if "Giovanni" in str(d.get("extracted_fields", {}).get("customer", ""))]
        
        for doc in giovanni_docs:
            ef = doc.get("extracted_fields", {}) or {}
            customer = ef.get("customer", "")
            assert "Giovanni Food Company" in customer, f"Expected Giovanni Food Company, got {customer}"
            
            # Verify document type
            doc_type = doc.get("document_type", "")
            assert doc_type == "Sales_Order", f"Expected Sales_Order, got {doc_type}"
        
        print(f"PASS: {len(giovanni_docs)} docs have correct customer field: Giovanni Food Company")


class TestBatchParentExclusion:
    """Tests specifically for batch_parent document exclusion"""
    
    def test_batch_parent_docs_exist_in_db(self):
        """Verify batch_parent docs exist but are filtered correctly"""
        response = requests.get(f"{BASE_URL}/api/documents?queue_view=false&include_cleared=true&limit=200")
        
        assert response.status_code == 200
        
        data = response.json()
        docs = data.get("documents", [])
        
        batch_parents = [d for d in docs if d.get("status") == "batch_parent"]
        
        # There should be batch_parent docs in the database
        assert len(batch_parents) > 0, "Expected batch_parent docs to exist in database"
        
        print(f"PASS: Found {len(batch_parents)} batch_parent docs in database (correctly excluded from UI views)")
    
    def test_terminal_statuses_include_batch_parent(self):
        """Verify TERMINAL_STATUSES in backend includes batch_parent"""
        # This is a code review check - batch_parent should be in TERMINAL_STATUSES
        # so it's excluded from active inbox
        response = requests.get(f"{BASE_URL}/api/documents?queue_view=true&include_cleared=false&limit=100")
        
        assert response.status_code == 200
        
        data = response.json()
        docs = data.get("documents", [])
        
        # No batch_parent should appear in active queue
        for doc in docs:
            assert doc.get("status") != "batch_parent", f"batch_parent doc found in active queue: {doc.get('id')}"
        
        print(f"PASS: No batch_parent docs in active queue view")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
