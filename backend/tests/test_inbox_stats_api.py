"""
Test suite for Inbox Stats API endpoint
Tests the GET /api/dashboard/inbox-stats endpoint for the simplified inbox UI
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestInboxStatsAPI:
    """Tests for the inbox stats endpoint used by the simplified inbox UI"""
    
    def test_inbox_stats_endpoint_returns_200(self):
        """Test that inbox-stats endpoint returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ GET /api/dashboard/inbox-stats returns 200")
    
    def test_inbox_stats_returns_required_fields(self):
        """Test that inbox-stats returns all required fields for the stats strip"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200
        
        data = response.json()
        
        # Required fields for the stats strip
        required_fields = [
            'ingested_today',
            'avg_daily_7d',
            'auto_validation_rate',
            'pending_review',
            'bounds_alerts',
            'avg_ai_confidence',
            'total_documents'
        ]
        
        for field in required_fields:
            assert field in data, f"Missing required field: {field}"
            print(f"✓ Field '{field}' present with value: {data[field]}")
    
    def test_inbox_stats_field_types(self):
        """Test that inbox-stats fields have correct types"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200
        
        data = response.json()
        
        # Check numeric types
        assert isinstance(data['ingested_today'], (int, float)), "ingested_today should be numeric"
        assert isinstance(data['avg_daily_7d'], (int, float)), "avg_daily_7d should be numeric"
        assert isinstance(data['auto_validation_rate'], (int, float)), "auto_validation_rate should be numeric"
        assert isinstance(data['pending_review'], (int, float)), "pending_review should be numeric"
        assert isinstance(data['bounds_alerts'], (int, float)), "bounds_alerts should be numeric"
        assert isinstance(data['avg_ai_confidence'], (int, float)), "avg_ai_confidence should be numeric"
        assert isinstance(data['total_documents'], (int, float)), "total_documents should be numeric"
        
        print("✓ All field types are correct (numeric)")
    
    def test_inbox_stats_values_are_non_negative(self):
        """Test that inbox-stats values are non-negative"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200
        
        data = response.json()
        
        assert data['ingested_today'] >= 0, "ingested_today should be non-negative"
        assert data['avg_daily_7d'] >= 0, "avg_daily_7d should be non-negative"
        assert data['auto_validation_rate'] >= 0, "auto_validation_rate should be non-negative"
        assert data['pending_review'] >= 0, "pending_review should be non-negative"
        assert data['bounds_alerts'] >= 0, "bounds_alerts should be non-negative"
        assert data['avg_ai_confidence'] >= 0, "avg_ai_confidence should be non-negative"
        assert data['total_documents'] >= 0, "total_documents should be non-negative"
        
        print("✓ All values are non-negative")
    
    def test_inbox_stats_auto_validation_rate_is_percentage(self):
        """Test that auto_validation_rate is a valid percentage (0-100)"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200
        
        data = response.json()
        
        assert 0 <= data['auto_validation_rate'] <= 100, \
            f"auto_validation_rate should be 0-100, got {data['auto_validation_rate']}"
        
        print(f"✓ auto_validation_rate is valid percentage: {data['auto_validation_rate']}%")
    
    def test_inbox_stats_ai_confidence_is_percentage(self):
        """Test that avg_ai_confidence is a valid percentage (0-100)"""
        response = requests.get(f"{BASE_URL}/api/dashboard/inbox-stats")
        assert response.status_code == 200
        
        data = response.json()
        
        assert 0 <= data['avg_ai_confidence'] <= 100, \
            f"avg_ai_confidence should be 0-100, got {data['avg_ai_confidence']}"
        
        print(f"✓ avg_ai_confidence is valid percentage: {data['avg_ai_confidence']}%")


class TestDocumentsAPI:
    """Tests for the documents list endpoint used by the inbox"""
    
    def test_documents_endpoint_returns_200(self):
        """Test that documents endpoint returns 200 OK"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ GET /api/documents returns 200")
    
    def test_documents_returns_list(self):
        """Test that documents endpoint returns a list of documents"""
        response = requests.get(f"{BASE_URL}/api/documents?limit=10")
        assert response.status_code == 200
        
        data = response.json()
        assert 'documents' in data, "Response should contain 'documents' key"
        assert isinstance(data['documents'], list), "documents should be a list"
        
        print(f"✓ Documents endpoint returns list with {len(data['documents'])} items")
    
    def test_documents_with_accounting_filter(self):
        """Test documents endpoint with accounting document types filter"""
        ap_types = "AP_Invoice,AP_INVOICE,Purchase_Order,PURCHASE_ORDER,Remittance,REMITTANCE"
        response = requests.get(f"{BASE_URL}/api/documents?document_types={ap_types}&limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        print(f"✓ Documents endpoint with accounting filter returns 200")
    
    def test_documents_with_sales_filter(self):
        """Test documents endpoint with sales document types filter"""
        sales_types = "Sales_Order,SALES_ORDER,Sales_PO,Sales_Quote,Order_Confirmation,SALES_INVOICE"
        response = requests.get(f"{BASE_URL}/api/documents?document_types={sales_types}&limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        print(f"✓ Documents endpoint with sales filter returns 200")
    
    def test_documents_with_search(self):
        """Test documents endpoint with search query"""
        response = requests.get(f"{BASE_URL}/api/documents?search=Purchase&limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        print(f"✓ Documents endpoint with search returns 200")


class TestAuthAPI:
    """Tests for authentication endpoint"""
    
    def test_login_with_valid_credentials(self):
        """Test login with admin/admin credentials"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "admin", "password": "admin"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        assert 'token' in data or 'access_token' in data or 'user' in data, \
            "Response should contain authentication data"
        
        print(f"✓ Login with admin/admin returns 200")
    
    def test_login_with_invalid_credentials(self):
        """Test login with invalid credentials"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "invalid", "password": "invalid"}
        )
        assert response.status_code in [401, 403], \
            f"Expected 401 or 403, got {response.status_code}"
        
        print(f"✓ Login with invalid credentials returns {response.status_code}")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
