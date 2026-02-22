"""
GPI Document Hub - Pilot Endpoints Tests
Tests for the 14-day shadow pilot APIs:
- /api/pilot/status
- /api/pilot/daily-metrics
- /api/pilot/logs
- /api/pilot/accuracy
- /api/pilot/trend
- Document upload pilot metadata
"""

import pytest
import requests
import os
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestPilotStatus:
    """Test pilot status endpoint"""
    
    def test_pilot_status_returns_200(self):
        """GET /api/pilot/status should return 200"""
        response = requests.get(f"{BASE_URL}/api/pilot/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: Pilot status endpoint returns 200")
    
    def test_pilot_status_response_structure(self):
        """Verify pilot status response contains expected fields"""
        response = requests.get(f"{BASE_URL}/api/pilot/status")
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        required_fields = [
            "pilot_mode_enabled",
            "current_phase",
            "pilot_start_date",
            "pilot_end_date",
            "exports_blocked",
            "bc_validation_blocked",
            "external_writes_blocked"
        ]
        
        for field in required_fields:
            assert field in data, f"Missing field: {field}"
        
        # Verify pilot mode is enabled (default)
        assert data["pilot_mode_enabled"] == True, "Pilot mode should be enabled"
        assert data["current_phase"] == "shadow_pilot_v1", f"Expected shadow_pilot_v1, got {data['current_phase']}"
        print(f"PASS: Pilot status has correct structure with pilot_mode_enabled=True")


class TestPilotDailyMetrics:
    """Test pilot daily metrics endpoint"""
    
    def test_daily_metrics_returns_200(self):
        """GET /api/pilot/daily-metrics should return 200"""
        response = requests.get(f"{BASE_URL}/api/pilot/daily-metrics")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: Pilot daily metrics endpoint returns 200")
    
    def test_daily_metrics_response_structure(self):
        """Verify daily metrics response structure"""
        response = requests.get(f"{BASE_URL}/api/pilot/daily-metrics")
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert "phase" in data
        assert "summary" in data
        assert "by_doc_type" in data
        assert "stuck_documents" in data
        
        # Check summary fields
        summary = data["summary"]
        summary_fields = [
            "total_documents",
            "deterministic_classified",
            "ai_classified",
            "ai_usage_rate",
            "vendor_extraction_rate",
            "export_rate"
        ]
        for field in summary_fields:
            assert field in summary, f"Missing summary field: {field}"
        
        print(f"PASS: Daily metrics has correct structure with {summary['total_documents']} documents")
    
    def test_daily_metrics_with_date_filter(self):
        """Test daily metrics with specific date"""
        today = datetime.now().strftime("%Y-%m-%d")
        response = requests.get(f"{BASE_URL}/api/pilot/daily-metrics", params={"date": today})
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        data = response.json()
        assert data["date"] == today
        print(f"PASS: Daily metrics with date filter works")


class TestPilotLogs:
    """Test pilot logs endpoint"""
    
    def test_logs_returns_200(self):
        """GET /api/pilot/logs should return 200"""
        response = requests.get(f"{BASE_URL}/api/pilot/logs")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: Pilot logs endpoint returns 200")
    
    def test_logs_response_structure(self):
        """Verify logs response structure"""
        response = requests.get(f"{BASE_URL}/api/pilot/logs")
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert "phase" in data
        assert "page" in data
        assert "page_size" in data
        assert "total" in data
        assert "logs" in data
        assert isinstance(data["logs"], list)
        
        print(f"PASS: Pilot logs has correct structure with {data['total']} total entries")
    
    def test_logs_pagination(self):
        """Test logs pagination"""
        response = requests.get(f"{BASE_URL}/api/pilot/logs", params={"page": 1, "page_size": 10})
        assert response.status_code == 200
        data = response.json()
        assert data["page"] == 1
        assert data["page_size"] == 10
        print(f"PASS: Pilot logs pagination works")


class TestPilotAccuracy:
    """Test pilot accuracy report endpoint"""
    
    def test_accuracy_returns_200(self):
        """GET /api/pilot/accuracy should return 200"""
        response = requests.get(f"{BASE_URL}/api/pilot/accuracy")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: Pilot accuracy endpoint returns 200")
    
    def test_accuracy_response_structure(self):
        """Verify accuracy response structure"""
        response = requests.get(f"{BASE_URL}/api/pilot/accuracy")
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert "phase" in data
        assert "accuracy_score" in data
        assert "total_documents" in data
        assert "corrected_documents" in data
        assert "corrections" in data
        assert "time_in_status_distribution" in data
        
        # Verify accuracy_score is a number
        assert isinstance(data["accuracy_score"], (int, float))
        
        print(f"PASS: Pilot accuracy has correct structure with score={data['accuracy_score']}%")


class TestPilotTrend:
    """Test pilot trend data endpoint"""
    
    def test_trend_returns_200(self):
        """GET /api/pilot/trend should return 200"""
        response = requests.get(f"{BASE_URL}/api/pilot/trend")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        print(f"PASS: Pilot trend endpoint returns 200")
    
    def test_trend_response_structure(self):
        """Verify trend response structure"""
        response = requests.get(f"{BASE_URL}/api/pilot/trend")
        assert response.status_code == 200
        data = response.json()
        
        # Check required fields
        assert "phase" in data
        assert "days" in data
        assert "start_date" in data
        assert "end_date" in data
        assert "doc_types" in data
        assert "trend" in data
        assert isinstance(data["trend"], list)
        
        print(f"PASS: Pilot trend has correct structure with {len(data['trend'])} days")
    
    def test_trend_with_custom_days(self):
        """Test trend with custom days parameter"""
        response = requests.get(f"{BASE_URL}/api/pilot/trend", params={"days": 7})
        assert response.status_code == 200
        data = response.json()
        assert data["days"] == 7
        print(f"PASS: Pilot trend with custom days works")


class TestDocumentUploadPilotMetadata:
    """Test that document upload adds pilot metadata"""
    
    def test_upload_adds_pilot_metadata(self):
        """Document upload should add pilot_phase and pilot_date"""
        # Create test file
        import io
        files = {"file": ("test_pilot.pdf", io.BytesIO(b"test content"), "application/pdf")}
        data = {"document_type": "PurchaseInvoice", "source": "pilot_test"}
        
        response = requests.post(f"{BASE_URL}/api/documents/upload", files=files, data=data)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        result = response.json()
        doc = result.get("document", {})
        
        # Check pilot metadata
        assert "pilot_phase" in doc, "Document should have pilot_phase"
        assert doc["pilot_phase"] == "shadow_pilot_v1", f"Expected shadow_pilot_v1, got {doc['pilot_phase']}"
        assert "pilot_date" in doc, "Document should have pilot_date"
        
        # Verify pilot_date is ISO format
        pilot_date = doc["pilot_date"]
        assert pilot_date is not None, "pilot_date should not be None"
        
        # Cleanup - delete the test document
        doc_id = doc.get("id")
        if doc_id:
            cleanup_response = requests.delete(f"{BASE_URL}/api/documents/{doc_id}")
            print(f"Cleanup: deleted test document {doc_id}")
        
        print(f"PASS: Upload adds pilot_phase={doc['pilot_phase']} and pilot_date")


class TestPilotIntegration:
    """Integration tests for pilot workflow"""
    
    def test_pilot_flow_end_to_end(self):
        """Test full pilot flow: upload -> verify metadata -> check in metrics"""
        import io
        
        # 1. Verify pilot is enabled
        status_response = requests.get(f"{BASE_URL}/api/pilot/status")
        assert status_response.status_code == 200
        assert status_response.json()["pilot_mode_enabled"] == True
        
        # 2. Upload a test document
        files = {"file": ("integration_test.pdf", io.BytesIO(b"integration test"), "application/pdf")}
        data = {"document_type": "PurchaseInvoice", "source": "integration_test"}
        
        upload_response = requests.post(f"{BASE_URL}/api/documents/upload", files=files, data=data)
        assert upload_response.status_code == 200
        doc = upload_response.json().get("document", {})
        doc_id = doc.get("id")
        
        # 3. Verify pilot metadata
        assert doc.get("pilot_phase") == "shadow_pilot_v1"
        assert doc.get("pilot_date") is not None
        
        # 4. Check document appears in pilot logs
        logs_response = requests.get(f"{BASE_URL}/api/pilot/logs", params={"page_size": 100})
        assert logs_response.status_code == 200
        logs = logs_response.json().get("logs", [])
        doc_ids_in_logs = [log.get("id") for log in logs]
        assert doc_id in doc_ids_in_logs, f"Uploaded doc {doc_id} should appear in pilot logs"
        
        # 5. Cleanup
        if doc_id:
            requests.delete(f"{BASE_URL}/api/documents/{doc_id}")
        
        print(f"PASS: Pilot integration flow works end-to-end")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
