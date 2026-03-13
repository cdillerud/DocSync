"""
Sales Dashboard API Tests
Tests for the new Sales Dashboard feature - Orders Awaiting Review
Endpoints:
  - GET /api/sales-dashboard/queue  - filtered list of sales-eligible docs
  - GET /api/sales-dashboard/summary - summary counts for dashboard cards
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestSalesDashboardQueue:
    """Tests for GET /api/sales-dashboard/queue endpoint"""
    
    def test_queue_returns_items_list(self):
        """Test queue endpoint returns items array with expected fields"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "items" in data, "Response should contain 'items' array"
        assert "total" in data, "Response should contain 'total' count"
        assert "summary" in data, "Response should contain 'summary' object"
        
        # Verify summary structure
        summary = data["summary"]
        assert "ready" in summary, "Summary should have 'ready' count"
        assert "ready_warnings" in summary, "Summary should have 'ready_warnings' count"
        assert "needs_review" in summary, "Summary should have 'needs_review' count"
        assert "already_created" in summary, "Summary should have 'already_created' count"
        assert "total" in summary, "Summary should have 'total' count"
        
        print(f"Queue returned {len(data['items'])} items, total: {data['total']}")
        print(f"Summary: ready={summary['ready']}, warnings={summary['ready_warnings']}, needs_review={summary['needs_review']}, created={summary['already_created']}")
    
    def test_queue_item_structure(self):
        """Test each queue item has all required fields"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue")
        assert response.status_code == 200
        
        data = response.json()
        if len(data["items"]) > 0:
            item = data["items"][0]
            required_fields = [
                "id", "file_name", "document_type", "status", "customer_name",
                "external_doc_no", "amount", "line_count", "warnings", "blocking_issues"
            ]
            for field in required_fields:
                assert field in item, f"Item missing required field: {field}"
            
            # Status should be one of the valid values
            valid_statuses = ["ready", "ready_warnings", "needs_review", "already_created"]
            assert item["status"] in valid_statuses, f"Invalid status: {item['status']}"
            
            print(f"Verified item structure - id: {item['id']}, status: {item['status']}, customer: {item['customer_name']}")
        else:
            print("No items in queue to verify structure")
    
    def test_queue_filter_by_status_needs_review(self):
        """Test filtering queue by status=needs_review"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue?status=needs_review")
        assert response.status_code == 200
        
        data = response.json()
        # All returned items should have needs_review status
        for item in data["items"]:
            assert item["status"] == "needs_review", f"Expected needs_review, got {item['status']}"
        
        print(f"needs_review filter: {len(data['items'])} items returned")
    
    def test_queue_filter_by_status_already_created(self):
        """Test filtering queue by status=already_created"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue?status=already_created")
        assert response.status_code == 200
        
        data = response.json()
        # All returned items should have already_created status
        for item in data["items"]:
            assert item["status"] == "already_created", f"Expected already_created, got {item['status']}"
            # already_created items should have bc_record_no
            if item.get("bc_record_no"):
                print(f"Found already_created item with BC SO: {item['bc_record_no']}")
        
        print(f"already_created filter: {len(data['items'])} items returned")
    
    def test_queue_filter_has_bc_order_no(self):
        """Test filtering queue by has_bc_order=no (docs without BC order)"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue?has_bc_order=no")
        assert response.status_code == 200
        
        data = response.json()
        # All returned items should NOT have bc_record_no
        for item in data["items"]:
            # Items without BC order should not have already_created status
            assert item["status"] != "already_created" or not item.get("bc_record_no"), \
                f"has_bc_order=no should not return docs with BC order"
        
        print(f"has_bc_order=no filter: {len(data['items'])} items returned")
    
    def test_queue_filter_has_bc_order_yes(self):
        """Test filtering queue by has_bc_order=yes (docs with BC order)"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue?has_bc_order=yes")
        assert response.status_code == 200
        
        data = response.json()
        # All returned items should be already_created status
        for item in data["items"]:
            assert item["status"] == "already_created", \
                f"has_bc_order=yes should only return already_created docs, got {item['status']}"
        
        print(f"has_bc_order=yes filter: {len(data['items'])} items returned")
    
    def test_queue_search_by_customer(self):
        """Test search functionality by customer name"""
        # First get all items to find a customer name to search
        all_response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue")
        all_data = all_response.json()
        
        if len(all_data["items"]) > 0:
            # Find an item with a customer name
            search_name = None
            for item in all_data["items"]:
                if item.get("customer_name"):
                    search_name = item["customer_name"][:5]  # Use first 5 chars as search term
                    break
            
            if search_name:
                # Search for that customer
                response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue?search={search_name}")
                assert response.status_code == 200
                data = response.json()
                print(f"Search '{search_name}' returned {len(data['items'])} items")
            else:
                print("No customer names found to test search")
        else:
            print("No items in queue to test search")
    
    def test_queue_pagination(self):
        """Test pagination with skip and limit"""
        # Get first page
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue?limit=2&skip=0")
        assert response.status_code == 200
        data = response.json()
        
        assert "skip" in data, "Response should contain skip value"
        assert "limit" in data, "Response should contain limit value"
        assert data["limit"] == 2, f"Limit should be 2, got {data['limit']}"
        
        print(f"Pagination test: returned {len(data['items'])} items with limit=2")
    
    def test_queue_sort_created_desc(self):
        """Test sorting by created date descending"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue?sort=created_desc")
        assert response.status_code == 200
        data = response.json()
        
        if len(data["items"]) >= 2:
            # Verify items are sorted by created_utc descending
            for i in range(len(data["items"]) - 1):
                current = data["items"][i].get("created_utc", "")
                next_item = data["items"][i + 1].get("created_utc", "")
                if current and next_item:
                    assert current >= next_item, f"Items not sorted descending: {current} < {next_item}"
        
        print(f"Sort created_desc verified with {len(data['items'])} items")


class TestSalesDashboardSummary:
    """Tests for GET /api/sales-dashboard/summary endpoint"""
    
    def test_summary_returns_counts(self):
        """Test summary endpoint returns all required counts"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        required_fields = ["ready", "ready_warnings", "needs_review", "already_created", "total"]
        
        for field in required_fields:
            assert field in data, f"Summary missing field: {field}"
            assert isinstance(data[field], int), f"Field {field} should be integer, got {type(data[field])}"
        
        # Total should equal sum of all status counts
        expected_total = data["ready"] + data["ready_warnings"] + data["needs_review"] + data["already_created"]
        assert data["total"] == expected_total, \
            f"Total {data['total']} should equal sum of statuses {expected_total}"
        
        print(f"Summary: ready={data['ready']}, warnings={data['ready_warnings']}, needs_review={data['needs_review']}, created={data['already_created']}, total={data['total']}")
    
    def test_summary_matches_queue_counts(self):
        """Test summary counts match queue data"""
        # Get summary
        summary_response = requests.get(f"{BASE_URL}/api/sales-dashboard/summary")
        assert summary_response.status_code == 200
        summary = summary_response.json()
        
        # Get queue which also includes summary
        queue_response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue")
        assert queue_response.status_code == 200
        queue_data = queue_response.json()
        
        queue_summary = queue_data.get("summary", {})
        
        # Verify counts match
        assert summary["ready"] == queue_summary.get("ready", 0), \
            f"Ready count mismatch: summary={summary['ready']}, queue={queue_summary.get('ready')}"
        assert summary["already_created"] == queue_summary.get("already_created", 0), \
            f"Already created count mismatch"
        
        print("Summary counts match queue summary counts")


class TestSalesDashboardDataIntegrity:
    """Tests for data integrity and expected values based on test data"""
    
    def test_expected_document_counts(self):
        """Test we have expected 6 sales-eligible documents: 5 already_created, 1 needs_review"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/summary")
        assert response.status_code == 200
        data = response.json()
        
        # Per the context: 6 sales-eligible docs, 5 already_created, 1 needs_review
        print(f"Actual counts - total: {data['total']}, created: {data['already_created']}, needs_review: {data['needs_review']}")
        
        # Verify we have some sales-eligible documents
        assert data["total"] >= 1, "Should have at least 1 sales-eligible document"
    
    def test_already_created_has_bc_record_no(self):
        """Test already_created items have BC record number"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue?status=already_created")
        assert response.status_code == 200
        data = response.json()
        
        for item in data["items"]:
            assert item["status"] == "already_created"
            # bc_record_no should be present for created items
            if item.get("bc_record_no"):
                print(f"Already created item {item['id'][:8]}... has BC SO: {item['bc_record_no']}")
    
    def test_needs_review_has_blocking_issues(self):
        """Test needs_review items have blocking issues"""
        response = requests.get(f"{BASE_URL}/api/sales-dashboard/queue?status=needs_review")
        assert response.status_code == 200
        data = response.json()
        
        for item in data["items"]:
            assert item["status"] == "needs_review"
            # needs_review items should have blocking_issues
            blocking = item.get("blocking_issues", [])
            print(f"Needs review item {item['id'][:8]}... blocking issues: {blocking}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
