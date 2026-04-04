"""
Iteration 190: PO Format Learning Engine Tests

Tests the new PO Format Learning Engine that:
1. Tracks every PO match attempt per vendor
2. Learns which transformations succeed (strip suffixes, numeric extraction, prefix addition, etc.)
3. Applies learned transformations in priority order on future documents
4. Records outcomes for continuous learning

Also tests regression for existing endpoints.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

class TestPOFormatIntelligence:
    """Test the new /po-format-intelligence endpoint"""
    
    def test_po_format_intelligence_endpoint_exists(self):
        """GET /api/posting-patterns/po-format-intelligence should return 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/po-format-intelligence")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        print(f"✓ PO Format Intelligence endpoint returns 200")
        
    def test_po_format_intelligence_response_structure(self):
        """Response should have expected fields"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/po-format-intelligence")
        assert response.status_code == 200
        data = response.json()
        
        # Check expected fields
        assert "vendors_tracked" in data, "Missing vendors_tracked field"
        assert "total_match_attempts" in data, "Missing total_match_attempts field"
        assert "top_transformations" in data, "Missing top_transformations field"
        assert "worst_match_vendors" in data, "Missing worst_match_vendors field"
        assert "generated_at" in data, "Missing generated_at field"
        
        # Validate types
        assert isinstance(data["vendors_tracked"], int), "vendors_tracked should be int"
        assert isinstance(data["total_match_attempts"], int), "total_match_attempts should be int"
        assert isinstance(data["top_transformations"], list), "top_transformations should be list"
        assert isinstance(data["worst_match_vendors"], list), "worst_match_vendors should be list"
        
        print(f"✓ PO Format Intelligence response structure valid")
        print(f"  - Vendors tracked: {data['vendors_tracked']}")
        print(f"  - Total match attempts: {data['total_match_attempts']}")
        print(f"  - Top transformations: {len(data['top_transformations'])}")


class TestIntelligenceBackfillWithPORevalidation:
    """Test the enhanced /intelligence/backfill endpoint with PO revalidation"""
    
    def test_backfill_endpoint_exists(self):
        """POST /api/posting-patterns/intelligence/backfill should return 200"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/intelligence/backfill")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        print(f"✓ Intelligence Backfill endpoint returns 200")
        
    def test_backfill_response_includes_po_revalidation(self):
        """Response should include po_revalidation step"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/intelligence/backfill")
        assert response.status_code == 200
        data = response.json()
        
        # Check all expected backfill steps
        assert "escalation_backfill" in data, "Missing escalation_backfill"
        assert "duplicate_backfill" in data, "Missing duplicate_backfill"
        assert "vendor_maturity" in data, "Missing vendor_maturity"
        assert "duplicate_clear" in data, "Missing duplicate_clear"
        assert "po_revalidation" in data, "Missing po_revalidation (NEW in iteration 190)"
        
        # Validate po_revalidation structure
        po_reval = data["po_revalidation"]
        if "error" not in po_reval:
            assert "found" in po_reval or "resolved" in po_reval, "po_revalidation should have found/resolved"
        
        print(f"✓ Intelligence Backfill includes PO revalidation step")
        print(f"  - Escalation: {data.get('escalation_backfill', {})}")
        print(f"  - Duplicate: {data.get('duplicate_backfill', {})}")
        print(f"  - Vendor Maturity: {data.get('vendor_maturity', {})}")
        print(f"  - Duplicate Clear: {data.get('duplicate_clear', {})}")
        print(f"  - PO Revalidation: {data.get('po_revalidation', {})}")


class TestPOGapBreakdown:
    """Test the /po-gap-breakdown endpoint"""
    
    def test_po_gap_breakdown_endpoint(self):
        """GET /api/posting-patterns/po-gap-breakdown should return 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/po-gap-breakdown")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        data = response.json()
        
        assert "total_po_gaps" in data, "Missing total_po_gaps"
        assert "by_vendor" in data, "Missing by_vendor"
        
        print(f"✓ PO Gap Breakdown endpoint returns 200")
        print(f"  - Total PO gaps: {data.get('total_po_gaps', 0)}")
        print(f"  - Vendors with gaps: {len(data.get('by_vendor', []))}")


class TestGapCloserStatus:
    """Test the /gap-closer/status endpoint"""
    
    def test_gap_closer_status_endpoint(self):
        """GET /api/posting-patterns/gap-closer/status should return 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        print(f"✓ Gap Closer Status endpoint returns 200")
        
    def test_gap_closer_returns_7_gaps(self):
        """Response should include all 7 gap types"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/gap-closer/status")
        assert response.status_code == 200
        data = response.json()
        
        # Check for total_validation_gaps
        assert "total_validation_gaps" in data, "Missing total_validation_gaps"
        
        # The 7 gaps should be tracked - they are at the top level of the response
        expected_gaps = [
            "gap_1_confidence_calibration",
            "gap_2_po_matching",
            "gap_3_customer_matching",
            "gap_4_sales_order_matching",
            "gap_5_duplicate_intelligence",
            "gap_6_amount_anomaly",
            "gap_7_escalation_intelligence",
        ]
        
        # Check that all 7 gap closers are present as top-level keys
        for expected in expected_gaps:
            assert expected in data, f"Missing gap: {expected}"
            # Each gap should have a status field
            assert "status" in data[expected], f"Gap {expected} missing status field"
        
        print(f"✓ Gap Closer Status returns all 7 gaps")
        print(f"  - All 7 gaps present at top level")


class TestRegressionLearningPulse:
    """Regression test for /learning-pulse endpoint"""
    
    def test_learning_pulse_endpoint(self):
        """GET /api/posting-patterns/learning-pulse should return 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-pulse")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        data = response.json()
        
        # Check expected fields
        assert "total_documents_learned_from" in data or "total_documents" in data, "Missing document count"
        
        print(f"✓ Learning Pulse endpoint returns 200 (regression)")


class TestRegressionDeepLearningSummary:
    """Regression test for /deep-learning/summary endpoint"""
    
    def test_deep_learning_summary_endpoint(self):
        """GET /api/posting-patterns/deep-learning/summary should return 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/deep-learning/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        data = response.json()
        
        # Check for vendor_maturity
        assert "vendor_maturity" in data, "Missing vendor_maturity"
        
        # Check maturity levels use new labels
        maturity = data.get("vendor_maturity", {})
        levels = maturity.get("levels", {})
        
        # New labels: autonomous, stable, developing, learning, novice
        valid_labels = {"autonomous", "stable", "developing", "learning", "novice"}
        for label in levels.keys():
            assert label in valid_labels, f"Unexpected maturity label: {label}"
        
        print(f"✓ Deep Learning Summary endpoint returns 200 (regression)")
        print(f"  - Vendor maturity levels: {levels}")


class TestRegressionEscalationIntelligence:
    """Regression test for /escalation-intelligence endpoint"""
    
    def test_escalation_intelligence_endpoint(self):
        """GET /api/posting-patterns/escalation-intelligence should return 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/escalation-intelligence")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        data = response.json()
        
        # Check expected fields
        assert "total_combinations_tracked" in data or "summary" in data, "Missing escalation data"
        
        print(f"✓ Escalation Intelligence endpoint returns 200 (regression)")


class TestRegressionDuplicateIntelligence:
    """Regression test for /duplicate-intelligence endpoint"""
    
    def test_duplicate_intelligence_endpoint(self):
        """GET /api/posting-patterns/duplicate-intelligence should return 200"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/duplicate-intelligence")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        data = response.json()
        
        # Check expected fields
        assert "currently_blocked_by_duplicate" in data or "summary" in data, "Missing duplicate data"
        
        print(f"✓ Duplicate Intelligence endpoint returns 200 (regression)")


class TestHealthEndpoint:
    """Test basic health endpoint"""
    
    def test_health_endpoint(self):
        """GET /api/health should return 200"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        print(f"✓ Health endpoint returns 200")


class TestAuthLogin:
    """Test authentication"""
    
    def test_login_with_admin_credentials(self):
        """POST /api/auth/login with admin/admin should succeed"""
        response = requests.post(
            f"{BASE_URL}/api/auth/login",
            json={"username": "admin", "password": "admin"}
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text[:200]}"
        data = response.json()
        assert "token" in data or "access_token" in data or "success" in data, "Missing auth token"
        print(f"✓ Login with admin/admin succeeds")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
