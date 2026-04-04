"""
Test Intelligence Backfill and Related Features - Iteration 189

Tests for:
1. POST /api/posting-patterns/intelligence/backfill - new on-demand backfill endpoint
2. GET /api/posting-patterns/gap-closer/status - should return all 7 gaps
3. GET /api/posting-patterns/duplicate-intelligence - valid summary
4. GET /api/posting-patterns/escalation-intelligence - valid summary
5. GET /api/posting-patterns/deep-learning/summary - vendor_maturity with new labels
6. GET /api/posting-patterns/learning-pulse - regression test
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestIntelligenceBackfill:
    """Test the new intelligence backfill endpoint"""

    def test_backfill_endpoint_returns_valid_structure(self):
        """POST /api/posting-patterns/intelligence/backfill should return proper structure"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/intelligence/backfill")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        # Should have escalation_backfill, duplicate_backfill, vendor_maturity, duplicate_clear
        assert "escalation_backfill" in data, "Missing escalation_backfill in response"
        assert "duplicate_backfill" in data, "Missing duplicate_backfill in response"
        assert "vendor_maturity" in data, "Missing vendor_maturity in response"
        assert "duplicate_clear" in data, "Missing duplicate_clear in response"
        
        print(f"Backfill response: {data}")

    def test_backfill_escalation_structure(self):
        """Escalation backfill should have tracked count"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/intelligence/backfill")
        assert response.status_code == 200
        
        data = response.json()
        esc = data.get("escalation_backfill", {})
        # Should have 'tracked' or 'error' key
        assert "tracked" in esc or "error" in esc, f"Unexpected escalation_backfill structure: {esc}"
        if "tracked" in esc:
            assert isinstance(esc["tracked"], int), "tracked should be an integer"
            print(f"Escalation tracked: {esc['tracked']} docs")

    def test_backfill_vendor_maturity_structure(self):
        """Vendor maturity should have computed count and levels"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/intelligence/backfill")
        assert response.status_code == 200
        
        data = response.json()
        vm = data.get("vendor_maturity", {})
        # Should have 'computed' or 'error' key
        assert "computed" in vm or "error" in vm, f"Unexpected vendor_maturity structure: {vm}"
        if "computed" in vm:
            assert isinstance(vm["computed"], int), "computed should be an integer"
            print(f"Vendor maturity computed: {vm['computed']} vendors")
            if "levels" in vm:
                print(f"Maturity levels: {vm['levels']}")


class TestGapCloserStatus:
    """Test gap-closer/status endpoint returns all 7 gaps"""

    def test_gap_closer_status_returns_200(self):
        """GET /api/posting-patterns/gap-closer/status should return 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_gap_closer_has_all_7_gaps(self):
        """Should return all 7 gap types"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200
        
        data = response.json()
        
        # Expected 7 gap keys (gap_1 through gap_7)
        expected_gaps = [
            "gap_1_confidence_calibration",
            "gap_2_po_matching",
            "gap_3_customer_matching",
            "gap_4_sales_order_matching",
            "gap_5_duplicate_intelligence",
            "gap_6_amount_anomaly",
            "gap_7_escalation_intelligence"
        ]
        
        for gap_name in expected_gaps:
            assert gap_name in data, f"Missing gap: {gap_name}"
            print(f"Gap '{gap_name}': present with status={data[gap_name].get('status', 'N/A')}")
        
        # Also check total_validation_gaps
        assert "total_validation_gaps" in data, "Missing total_validation_gaps"
        print(f"Total validation gaps: {data['total_validation_gaps']}")


class TestDuplicateIntelligence:
    """Test duplicate-intelligence endpoint"""

    def test_duplicate_intelligence_returns_200(self):
        """GET /api/posting-patterns/duplicate-intelligence should return 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/duplicate-intelligence")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_duplicate_intelligence_valid_summary(self):
        """Should return valid summary structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/duplicate-intelligence")
        assert response.status_code == 200
        
        data = response.json()
        # Expected fields
        expected_fields = [
            "total_outcomes_tracked",
            "vendors_with_intel",
            "currently_blocked_by_duplicate"
        ]
        
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
            print(f"{field}: {data[field]}")


class TestEscalationIntelligence:
    """Test escalation-intelligence endpoint"""

    def test_escalation_intelligence_returns_200(self):
        """GET /api/posting-patterns/escalation-intelligence should return 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/escalation-intelligence")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_escalation_intelligence_valid_summary(self):
        """Should return valid summary structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/escalation-intelligence")
        assert response.status_code == 200
        
        data = response.json()
        # Expected fields
        expected_fields = [
            "total_combinations_tracked",
            "always_escalate",
            "fully_automated"
        ]
        
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
            print(f"{field}: {data[field]}")


class TestDeepLearningSummary:
    """Test deep-learning/summary endpoint with new maturity labels"""

    def test_deep_learning_summary_returns_200(self):
        """GET /api/posting-patterns/deep-learning/summary should return 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_vendor_maturity_has_new_labels(self):
        """Vendor maturity should use new labels: autonomous/stable/developing/learning/novice"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/summary")
        assert response.status_code == 200
        
        data = response.json()
        assert "vendor_maturity" in data, "Missing vendor_maturity in response"
        
        vm = data["vendor_maturity"]
        assert "levels" in vm, "Missing levels in vendor_maturity"
        
        levels = vm["levels"]
        print(f"Vendor maturity levels: {levels}")
        
        # Valid labels are: autonomous, stable, developing, learning, novice, unknown
        valid_labels = {"autonomous", "stable", "developing", "learning", "novice", "unknown"}
        for label in levels.keys():
            assert label in valid_labels, f"Unexpected maturity label: {label}. Expected one of {valid_labels}"
        
        # OLD labels should NOT be present
        old_labels = {"mastered", "proficient"}
        for old_label in old_labels:
            assert old_label not in levels, f"Old maturity label '{old_label}' should not be present"

    def test_deep_learning_has_all_sections(self):
        """Should have all expected sections"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/summary")
        assert response.status_code == 200
        
        data = response.json()
        expected_sections = [
            "extraction_patterns",
            "document_similarity",
            "self_correction",
            "vendor_maturity",
            "predictive_readiness"
        ]
        
        for section in expected_sections:
            assert section in data, f"Missing section: {section}"
            print(f"Section '{section}' present")


class TestLearningPulseRegression:
    """Regression test for learning-pulse endpoint"""

    def test_learning_pulse_returns_200(self):
        """GET /api/posting-patterns/learning-pulse should return 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_learning_pulse_has_expected_fields(self):
        """Should have confidence_calibration, outcomes, total_documents_learned_from"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert response.status_code == 200
        
        data = response.json()
        expected_fields = ["confidence_calibration", "outcomes", "total_documents_learned_from"]
        
        for field in expected_fields:
            assert field in data, f"Missing field: {field}"
            print(f"{field}: {data.get(field)}")


class TestHealthEndpoint:
    """Basic health check"""

    def test_health_returns_200(self):
        """GET /api/health should return 200"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
