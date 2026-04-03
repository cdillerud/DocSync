"""
Test BC Posting Pattern Analyzer - Expanded BC Data Fetch

Tests the expanded BC data ingestion that includes:
1. ALL invoice statuses (not just Paid/Open)
2. Historical posted purchase invoices from postedPurchaseInvoices endpoint
3. Graceful error handling when BC credentials are invalid

Key endpoints tested:
- GET /api/posting-patterns/status - totals including total_historical and total_current
- POST /api/posting-patterns/analyze/{vendor_no} - graceful error handling
- GET /api/posting-patterns/learning-proof/{vendor_no} - data_sources and status_distribution
- GET /api/posting-patterns/settings - auto-post configuration
- GET /api/posting-patterns/vendor-summary - vendor list with auto_post_eligible
- GET /api/posting-patterns/ready-queue - document queue
- POST /api/posting-patterns/analyze-top - background analysis
- GET /api/posting-patterns/analyze-top/status - analysis status
- GET /api/posting-patterns/learning-activity - learning events
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestPostingPatternsExpandedBC:
    """Test expanded BC data fetch for posting patterns"""

    def test_health_check(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Health check failed: {response.text}"
        print("PASS: Health check returns 200")

    def test_status_endpoint_returns_totals(self):
        """GET /api/posting-patterns/status returns totals including total_historical and total_current"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/status")
        assert response.status_code == 200, f"Status endpoint failed: {response.text}"
        
        data = response.json()
        # Verify required fields
        assert "total_profiles" in data, "Missing total_profiles field"
        assert "totals" in data, "Missing totals field"
        assert "confidence_distribution" in data, "Missing confidence_distribution field"
        
        # Verify totals structure includes new fields
        totals = data.get("totals", {})
        assert "total_invoices" in totals, "Missing total_invoices in totals"
        assert "total_lines" in totals, "Missing total_lines in totals"
        assert "total_historical" in totals, "Missing total_historical in totals (new field)"
        assert "total_current" in totals, "Missing total_current in totals (new field)"
        
        print(f"PASS: Status endpoint returns totals with total_historical={totals.get('total_historical')} and total_current={totals.get('total_current')}")

    def test_analyze_vendor_graceful_error_handling(self):
        """POST /api/posting-patterns/analyze/{vendor_no} returns proper JSON even when BC credentials are invalid"""
        # Use a test vendor number
        vendor_no = "TEST_VENDOR_123"
        response = requests.post(f"{BASE_URL}/api/posting-patterns/analyze/{vendor_no}")
        
        # Should return 200 with proper JSON, not 500
        assert response.status_code == 200, f"Analyze endpoint should return 200 even with BC errors, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Should have vendor_no and status fields
        assert "vendor_no" in data, "Missing vendor_no field"
        assert data["vendor_no"] == vendor_no, f"vendor_no mismatch: expected {vendor_no}, got {data.get('vendor_no')}"
        
        # When BC fails, should return no_invoices status with error message
        # (since BC credentials are placeholder in preview)
        status = data.get("status", "")
        if status == "no_invoices":
            # This is expected when BC credentials are invalid
            print(f"PASS: Analyze endpoint returns no_invoices status (expected with invalid BC credentials)")
            # Should have error field explaining the issue
            if "error" in data:
                print(f"  Error message: {data.get('error')}")
        elif status == "analyzed":
            # If somehow BC worked, verify the response structure
            assert "invoices_analyzed" in data, "Missing invoices_analyzed field"
            print(f"PASS: Analyze endpoint returns analyzed status with {data.get('invoices_analyzed')} invoices")
        else:
            print(f"PASS: Analyze endpoint returns status={status}")

    def test_learning_proof_returns_data_sources(self):
        """GET /api/posting-patterns/learning-proof/{vendor_no} returns data_sources and status_distribution"""
        # First try with a non-existent vendor to verify structure
        vendor_no = "NONEXISTENT_VENDOR"
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-proof/{vendor_no}")
        
        assert response.status_code == 200, f"Learning proof endpoint failed: {response.text}"
        
        data = response.json()
        assert "vendor_no" in data, "Missing vendor_no field"
        
        # For non-existent vendor, should return NOT LEARNED verdict
        if data.get("verdict") == "NOT LEARNED":
            print("PASS: Learning proof returns NOT LEARNED for non-existent vendor")
        else:
            # If vendor exists, verify new fields
            assert "data_sources" in data, "Missing data_sources field (new field)"
            assert "status_distribution" in data, "Missing status_distribution field (new field)"
            
            data_sources = data.get("data_sources", {})
            print(f"PASS: Learning proof returns data_sources: {data_sources}")
            print(f"  status_distribution: {data.get('status_distribution', {})}")

    def test_settings_endpoint(self):
        """GET /api/posting-patterns/settings returns current auto-post configuration"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/settings")
        
        assert response.status_code == 200, f"Settings endpoint failed: {response.text}"
        
        data = response.json()
        # Verify required fields
        assert "auto_post_enabled" in data, "Missing auto_post_enabled field"
        assert "min_confidence" in data, "Missing min_confidence field"
        assert "min_invoices_analyzed" in data, "Missing min_invoices_analyzed field"
        
        print(f"PASS: Settings endpoint returns auto_post_enabled={data.get('auto_post_enabled')}, min_confidence={data.get('min_confidence')}")

    def test_vendor_summary_returns_auto_post_eligible(self):
        """GET /api/posting-patterns/vendor-summary returns vendor list with auto_post_eligible field"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/vendor-summary")
        
        assert response.status_code == 200, f"Vendor summary endpoint failed: {response.text}"
        
        data = response.json()
        assert "count" in data, "Missing count field"
        assert "vendors" in data, "Missing vendors field"
        assert "settings" in data, "Missing settings field"
        
        # If there are vendors, verify auto_post_eligible field
        vendors = data.get("vendors", [])
        if vendors:
            first_vendor = vendors[0]
            assert "auto_post_eligible" in first_vendor, "Missing auto_post_eligible field in vendor"
            print(f"PASS: Vendor summary returns {len(vendors)} vendors with auto_post_eligible field")
        else:
            print("PASS: Vendor summary returns empty vendor list (expected with no BC data)")

    def test_ready_queue_endpoint(self):
        """GET /api/posting-patterns/ready-queue returns document queue"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/ready-queue")
        
        assert response.status_code == 200, f"Ready queue endpoint failed: {response.text}"
        
        data = response.json()
        assert "count" in data, "Missing count field"
        assert "documents" in data, "Missing documents field"
        
        print(f"PASS: Ready queue returns count={data.get('count')} documents")

    def test_analyze_top_starts_background_analysis(self):
        """POST /api/posting-patterns/analyze-top starts background analysis without crashing"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/analyze-top?top_n=5")
        
        assert response.status_code == 200, f"Analyze top endpoint failed: {response.text}"
        
        data = response.json()
        # Should return started or already_running status
        status = data.get("status", "")
        assert status in ["started", "already_running"], f"Unexpected status: {status}"
        
        print(f"PASS: Analyze top returns status={status}")

    def test_analyze_top_status_endpoint(self):
        """GET /api/posting-patterns/analyze-top/status returns analysis status"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/analyze-top/status")
        
        assert response.status_code == 200, f"Analyze top status endpoint failed: {response.text}"
        
        data = response.json()
        # Should have running and progress fields
        assert "running" in data, "Missing running field"
        assert "progress" in data, "Missing progress field"
        
        print(f"PASS: Analyze top status returns running={data.get('running')}, progress={data.get('progress')}")

    def test_learning_activity_endpoint(self):
        """GET /api/posting-patterns/learning-activity returns learning events"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-activity")
        
        assert response.status_code == 200, f"Learning activity endpoint failed: {response.text}"
        
        data = response.json()
        assert "total_learning_events" in data, "Missing total_learning_events field"
        assert "recent_events" in data, "Missing recent_events field"
        assert "vendors_learning" in data, "Missing vendors_learning field"
        
        print(f"PASS: Learning activity returns total_learning_events={data.get('total_learning_events')}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
