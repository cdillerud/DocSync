"""
Invoice Trace API Tests - Iteration 174
Tests the new trace endpoints for comparing human vs AI posting behavior.
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestInvoiceTraceEndpoints:
    """Tests for GET /api/posting-patterns/trace/{vendor_no} and /list endpoints"""
    
    def test_health_check(self):
        """Verify API is accessible"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        print("PASS: Health check returns 200")
    
    def test_trace_endpoint_returns_json_not_500(self):
        """
        GET /api/posting-patterns/trace/TUMALOC should return proper JSON with error message
        when BC credentials are missing (not a 500 error)
        """
        response = requests.get(f"{BASE_URL}/api/posting-patterns/trace/TUMALOC")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Should have error field with message about BC token failure
        assert "error" in data, "Response should contain 'error' field"
        assert "vendor_no" in data, "Response should contain 'vendor_no' field"
        assert data["vendor_no"] == "TUMALOC"
        # Error should mention BC token failure, not be a 500 error
        assert "Failed to" in data["error"] or "BC" in data["error"], f"Error should mention BC failure: {data['error']}"
        print(f"PASS: Trace endpoint returns proper JSON with error: {data['error']}")
    
    def test_trace_list_endpoint_returns_json_not_500(self):
        """
        GET /api/posting-patterns/trace/TUMALOC/list should return proper JSON with
        vendor_no, count, and invoices array (even if empty due to BC creds)
        """
        response = requests.get(f"{BASE_URL}/api/posting-patterns/trace/TUMALOC/list")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Should have vendor_no field
        assert "vendor_no" in data, "Response should contain 'vendor_no' field"
        assert data["vendor_no"] == "TUMALOC"
        
        # Should have invoices array (may be empty due to BC creds)
        assert "invoices" in data, "Response should contain 'invoices' field"
        assert isinstance(data["invoices"], list), "invoices should be a list"
        
        # If error, should be graceful (not 500)
        if "error" in data:
            assert "Failed to" in data["error"] or "BC" in data["error"], f"Error should mention BC failure: {data['error']}"
        
        print(f"PASS: Trace list endpoint returns proper JSON with {len(data.get('invoices', []))} invoices")
    
    def test_trace_endpoint_with_invoice_index(self):
        """
        GET /api/posting-patterns/trace/TUMALOC?invoice_index=0 should work
        """
        response = requests.get(f"{BASE_URL}/api/posting-patterns/trace/TUMALOC?invoice_index=0")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "vendor_no" in data
        print(f"PASS: Trace endpoint with invoice_index=0 returns proper JSON")
    
    def test_trace_list_endpoint_with_limit(self):
        """
        GET /api/posting-patterns/trace/TUMALOC/list?limit=5 should work
        """
        response = requests.get(f"{BASE_URL}/api/posting-patterns/trace/TUMALOC/list?limit=5")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "vendor_no" in data
        assert "invoices" in data
        print(f"PASS: Trace list endpoint with limit=5 returns proper JSON")
    
    def test_trace_endpoint_unknown_vendor(self):
        """
        GET /api/posting-patterns/trace/UNKNOWN_VENDOR should return proper JSON
        (not 500) even for unknown vendors
        """
        response = requests.get(f"{BASE_URL}/api/posting-patterns/trace/UNKNOWN_VENDOR_XYZ")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert "vendor_no" in data or "error" in data
        print(f"PASS: Trace endpoint for unknown vendor returns proper JSON")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
