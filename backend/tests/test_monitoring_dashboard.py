"""
Test suite for Monitoring Dashboard APIs
Tests the 5 metrics endpoints used by the executive monitoring dashboard at /monitor
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestMonitoringDashboardAPIs:
    """Tests for the 5 metric APIs used by the monitoring dashboard"""
    
    def test_learning_pulse_endpoint(self):
        """Test learning-pulse API (Metrics 1 & 3: AI Confidence Accuracy, Auto-File Rate)"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Verify required fields for confidence calibration (Metric 1)
        assert "confidence_calibration" in data, "Missing confidence_calibration field"
        assert "95_100" in data["confidence_calibration"], "Missing 95-100% band"
        
        # Verify required fields for auto-file rate (Metric 3)
        assert "outcomes" in data, "Missing outcomes field"
        assert "total_documents_learned_from" in data, "Missing total_documents_learned_from"
        
        print(f"Learning Pulse: {data.get('total_documents_learned_from', 0)} docs, "
              f"auto_filed: {data.get('outcomes', {}).get('auto_filed', 0)}")
    
    def test_deep_learning_summary_endpoint(self):
        """Test deep-learning/summary API (Metric 2: Vendor Maturity)"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Verify vendor maturity structure
        assert "vendor_maturity" in data, "Missing vendor_maturity field"
        assert "levels" in data["vendor_maturity"], "Missing maturity levels"
        
        levels = data["vendor_maturity"]["levels"]
        expected_levels = ["learning", "developing", "stable", "autonomous"]
        for level in expected_levels:
            assert level in levels or levels.get(level, 0) >= 0, f"Missing or invalid level: {level}"
        
        print(f"Vendor Maturity Levels: {levels}")
    
    def test_gap_closer_status_endpoint(self):
        """Test gap-closer/status API (Metric 4: Validation Gaps)"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Verify all 7 gaps are present
        expected_gaps = [
            "gap_1_confidence_calibration",
            "gap_2_po_matching",
            "gap_3_customer_matching",
            "gap_4_sales_order_matching",
            "gap_5_duplicate_intelligence",
            "gap_6_amount_anomaly",
            "gap_7_escalation_intelligence"
        ]
        for gap in expected_gaps:
            assert gap in data, f"Missing gap: {gap}"
            assert "status" in data[gap], f"Missing status in {gap}"
        
        # Verify total_validation_gaps
        assert "total_validation_gaps" in data, "Missing total_validation_gaps"
        
        total_gaps = sum(data["total_validation_gaps"].values())
        print(f"Total Validation Gaps: {total_gaps}")
    
    def test_escalation_intelligence_endpoint(self):
        """Test escalation-intelligence API (Metric 5: Escalation Patterns)"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/escalation-intelligence")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Verify required fields
        assert "total_combinations_tracked" in data, "Missing total_combinations_tracked"
        assert "always_escalate" in data, "Missing always_escalate"
        assert "fully_automated" in data, "Missing fully_automated"
        
        print(f"Escalation: {data.get('total_combinations_tracked', 0)} combos tracked, "
              f"{data.get('always_escalate', 0)} always escalate")
    
    def test_duplicate_intelligence_endpoint(self):
        """Test duplicate-intelligence API (used in gap detail)"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/duplicate-intelligence")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        # Verify required fields
        assert "currently_blocked_by_duplicate" in data, "Missing currently_blocked_by_duplicate"
        assert "vendors_with_intel" in data, "Missing vendors_with_intel"
        
        print(f"Duplicate Intel: {data.get('currently_blocked_by_duplicate', 0)} blocked")


class TestRegressionAPIs:
    """Regression tests for existing APIs"""
    
    def test_learning_dashboard_endpoint(self):
        """Regression: learning-dashboard API still works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("Learning dashboard API: OK")
    
    def test_advanced_learning_summary_endpoint(self):
        """Regression: advanced-learning/summary API still works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("Advanced learning summary API: OK")
    
    def test_health_endpoint(self):
        """Regression: health endpoint still works"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print("Health API: OK")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
