"""
Test New Intelligence Services (Iteration 187)
Tests for:
- Gap 5: Duplicate Intelligence
- Gap 6: Amount Anomaly Integration
- Gap 7: Auto-Escalation Intelligence
- Gap Closer Status API (7 gaps)
- Regression tests for learning-pulse, deep-learning, advanced-learning
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestGapCloserStatus:
    """Test GET /api/posting-patterns/gap-closer/status returns all 7 gaps"""
    
    def test_gap_closer_status_returns_7_gaps(self):
        """Verify gap-closer/status returns all 7 gap closers"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify all 7 gaps are present
        assert "gap_1_confidence_calibration" in data, "Missing gap_1_confidence_calibration"
        assert "gap_2_po_matching" in data, "Missing gap_2_po_matching"
        assert "gap_3_customer_matching" in data, "Missing gap_3_customer_matching"
        assert "gap_4_sales_order_matching" in data, "Missing gap_4_sales_order_matching"
        assert "gap_5_duplicate_intelligence" in data, "Missing gap_5_duplicate_intelligence"
        assert "gap_6_amount_anomaly" in data, "Missing gap_6_amount_anomaly"
        assert "gap_7_escalation_intelligence" in data, "Missing gap_7_escalation_intelligence"
        
        print(f"SUCCESS: All 7 gaps present in response")
    
    def test_gap_5_duplicate_intelligence_structure(self):
        """Verify gap_5_duplicate_intelligence has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200
        
        data = response.json()
        gap5 = data.get("gap_5_duplicate_intelligence", {})
        
        assert "status" in gap5, "Missing status in gap_5"
        assert gap5["status"] in ["active", "initializing"], f"Unexpected status: {gap5['status']}"
        
        if gap5["status"] == "active":
            assert "vendors_with_intel" in gap5, "Missing vendors_with_intel"
            assert "global_false_positive_rate" in gap5, "Missing global_false_positive_rate"
            assert "safe_to_clear_vendors" in gap5, "Missing safe_to_clear_vendors"
            assert "currently_blocked" in gap5, "Missing currently_blocked"
        
        print(f"SUCCESS: gap_5_duplicate_intelligence structure valid: {gap5}")
    
    def test_gap_6_amount_anomaly_structure(self):
        """Verify gap_6_amount_anomaly has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200
        
        data = response.json()
        gap6 = data.get("gap_6_amount_anomaly", {})
        
        assert "status" in gap6, "Missing status in gap_6"
        assert gap6["status"] in ["active", "initializing"], f"Unexpected status: {gap6['status']}"
        
        if gap6["status"] == "active":
            assert "vendors_with_patterns" in gap6, "Missing vendors_with_patterns"
            assert "active_anomalies" in gap6, "Missing active_anomalies"
        
        print(f"SUCCESS: gap_6_amount_anomaly structure valid: {gap6}")
    
    def test_gap_7_escalation_intelligence_structure(self):
        """Verify gap_7_escalation_intelligence has correct structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200
        
        data = response.json()
        gap7 = data.get("gap_7_escalation_intelligence", {})
        
        assert "status" in gap7, "Missing status in gap_7"
        assert gap7["status"] in ["active", "initializing"], f"Unexpected status: {gap7['status']}"
        
        if gap7["status"] == "active":
            assert "combinations_tracked" in gap7, "Missing combinations_tracked"
            assert "always_escalate" in gap7, "Missing always_escalate"
            assert "fully_automated" in gap7, "Missing fully_automated"
        
        print(f"SUCCESS: gap_7_escalation_intelligence structure valid: {gap7}")


class TestDuplicateIntelligenceAPI:
    """Test GET /api/posting-patterns/duplicate-intelligence"""
    
    def test_duplicate_intelligence_endpoint(self):
        """Verify duplicate-intelligence endpoint returns summary"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/duplicate-intelligence")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify expected fields
        assert "total_outcomes_tracked" in data, "Missing total_outcomes_tracked"
        assert "vendors_with_intel" in data, "Missing vendors_with_intel"
        assert "trust_distribution" in data, "Missing trust_distribution"
        assert "global_false_positive_rate" in data, "Missing global_false_positive_rate"
        assert "generated_at" in data, "Missing generated_at"
        
        print(f"SUCCESS: duplicate-intelligence returns valid summary")
        print(f"  - Total outcomes tracked: {data['total_outcomes_tracked']}")
        print(f"  - Vendors with intel: {data['vendors_with_intel']}")
        print(f"  - Global FP rate: {data['global_false_positive_rate']}")


class TestDuplicateIntelligenceBatchClear:
    """Test POST /api/posting-patterns/duplicate-intelligence/batch-clear"""
    
    def test_batch_clear_endpoint(self):
        """Verify batch-clear endpoint works"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/duplicate-intelligence/batch-clear?limit=10")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify expected fields
        assert "cleared" in data, "Missing cleared count"
        
        print(f"SUCCESS: batch-clear endpoint works")
        print(f"  - Cleared: {data.get('cleared', 0)}")
        print(f"  - Safe vendors: {data.get('safe_vendors', 0)}")
        print(f"  - Candidates found: {data.get('candidates_found', 0)}")


class TestEscalationIntelligenceAPI:
    """Test GET /api/posting-patterns/escalation-intelligence"""
    
    def test_escalation_intelligence_endpoint(self):
        """Verify escalation-intelligence endpoint returns summary"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/escalation-intelligence")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify expected fields
        assert "total_combinations_tracked" in data, "Missing total_combinations_tracked"
        assert "always_escalate" in data, "Missing always_escalate"
        assert "fully_automated" in data, "Missing fully_automated"
        assert "monitoring" in data, "Missing monitoring"
        assert "generated_at" in data, "Missing generated_at"
        
        print(f"SUCCESS: escalation-intelligence returns valid summary")
        print(f"  - Combinations tracked: {data['total_combinations_tracked']}")
        print(f"  - Always escalate: {data['always_escalate']}")
        print(f"  - Fully automated: {data['fully_automated']}")


class TestRegressionLearningPulse:
    """Regression test for GET /api/posting-patterns/learning-pulse"""
    
    def test_learning_pulse_endpoint(self):
        """Verify learning-pulse still works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify expected fields
        assert "total_documents_learned_from" in data, "Missing total_documents_learned_from"
        
        print(f"SUCCESS: learning-pulse regression passed")
        print(f"  - Total docs learned from: {data.get('total_documents_learned_from', 0)}")


class TestRegressionDeepLearning:
    """Regression test for GET /api/posting-patterns/deep-learning"""
    
    def test_deep_learning_summary_endpoint(self):
        """Verify deep-learning/summary still works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify expected sections
        assert "extraction_patterns" in data or "self_correction" in data or "vendor_maturity" in data, \
            "Missing expected deep learning sections"
        
        print(f"SUCCESS: deep-learning/summary regression passed")


class TestRegressionAdvancedLearning:
    """Regression test for GET /api/posting-patterns/advanced-learning"""
    
    def test_advanced_learning_summary_endpoint(self):
        """Verify advanced-learning/summary still works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/advanced-learning/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify expected sections
        assert "line_item_intelligence" in data or "document_flow" in data or "amount_patterns" in data, \
            "Missing expected advanced learning sections"
        
        print(f"SUCCESS: advanced-learning/summary regression passed")


class TestLearningDashboard:
    """Test GET /api/posting-patterns/learning-dashboard"""
    
    def test_learning_dashboard_endpoint(self):
        """Verify learning-dashboard still works"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-dashboard")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        
        # Verify expected fields
        assert "summary" in data, "Missing summary"
        
        print(f"SUCCESS: learning-dashboard regression passed")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
