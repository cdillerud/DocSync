"""
Test BC Posting Pattern Analyzer - Phase 1 of 'Work backwards from BC'

Tests:
1. Module imports and function availability
2. GET /api/posting-patterns/status - Returns posting pattern analysis status
3. GET /api/posting-patterns/vendor/{vendor_no} - Returns vendor profile or 'not_analyzed'
4. GET /api/posting-patterns/learning-proof/{vendor_no} - Returns proof or 'NOT LEARNED'
5. Regression: GET /api/knowledge-seed/learning-proof/{vendor_id} still works
6. ap_auto_post_service loads posting_profile and attaches suggested_posting_template
"""
import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestPostingPatternModuleImports:
    """Test that posting_pattern_analyzer module loads and functions are importable."""

    def test_posting_pattern_analyzer_imports(self):
        """Verify posting_pattern_analyzer module imports correctly."""
        from services.posting_pattern_analyzer import (
            analyze_vendor_posting_patterns,
            build_all_vendor_posting_profiles,
            get_posting_profile_for_vendor,
            MIN_INVOICES_FOR_PROFILE,
            MAX_INVOICES_PER_VENDOR
        )
        assert callable(analyze_vendor_posting_patterns)
        assert callable(build_all_vendor_posting_profiles)
        assert callable(get_posting_profile_for_vendor)
        assert MIN_INVOICES_FOR_PROFILE == 3
        assert MAX_INVOICES_PER_VENDOR == 200

    def test_business_central_service_new_methods(self):
        """Verify BC service has new methods for posted invoice queries."""
        from services.business_central_service import BusinessCentralService, get_bc_service
        bc = get_bc_service()
        assert hasattr(bc, 'get_posted_purchase_invoices')
        assert hasattr(bc, 'get_purchase_invoice_lines')
        assert callable(bc.get_posted_purchase_invoices)
        assert callable(bc.get_purchase_invoice_lines)

    def test_posting_patterns_router_imports(self):
        """Verify posting_patterns router imports correctly."""
        from routers.posting_patterns import router
        assert router is not None
        assert router.prefix == "/posting-patterns"


class TestPostingPatternsStatusEndpoint:
    """Test GET /api/posting-patterns/status endpoint."""

    def test_status_returns_200(self):
        """Status endpoint should return 200."""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_status_has_required_fields(self):
        """Status response should have total_profiles and confidence_distribution."""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/status")
        data = response.json()
        
        assert "total_profiles" in data, f"Missing total_profiles: {data}"
        assert "confidence_distribution" in data, f"Missing confidence_distribution: {data}"
        assert "top_vendors" in data, f"Missing top_vendors: {data}"

    def test_status_confidence_distribution_structure(self):
        """Confidence distribution should have high/medium/low keys."""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/status")
        data = response.json()
        
        conf = data.get("confidence_distribution", {})
        assert "high" in conf, f"Missing 'high' in confidence_distribution: {conf}"
        assert "medium" in conf, f"Missing 'medium' in confidence_distribution: {conf}"
        assert "low" in conf, f"Missing 'low' in confidence_distribution: {conf}"


class TestPostingPatternsVendorEndpoint:
    """Test GET /api/posting-patterns/vendor/{vendor_no} endpoint."""

    def test_vendor_profile_returns_200(self):
        """Vendor profile endpoint should return 200."""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/vendor/TUMALOC")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_vendor_profile_not_analyzed_message(self):
        """Unanalyzed vendor should return 'not_analyzed' status."""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/vendor/TUMALOC")
        data = response.json()
        
        # Since BC API calls fail on preview, vendor should be not_analyzed
        assert data.get("vendor_no") == "TUMALOC", f"Wrong vendor_no: {data}"
        assert data.get("status") == "not_analyzed", f"Expected not_analyzed status: {data}"
        assert "message" in data, f"Missing message: {data}"

    def test_vendor_profile_nonexistent_vendor(self):
        """Nonexistent vendor should also return not_analyzed."""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/vendor/NONEXISTENT_VENDOR_XYZ")
        data = response.json()
        
        assert response.status_code == 200
        assert data.get("status") == "not_analyzed"


class TestPostingPatternsLearningProofEndpoint:
    """Test GET /api/posting-patterns/learning-proof/{vendor_no} endpoint."""

    def test_learning_proof_returns_200(self):
        """Learning proof endpoint should return 200."""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-proof/TUMALOC")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_learning_proof_not_learned_message(self):
        """Unanalyzed vendor should return 'NOT LEARNED' verdict."""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-proof/TUMALOC")
        data = response.json()
        
        assert data.get("vendor_no") == "TUMALOC", f"Wrong vendor_no: {data}"
        assert data.get("verdict") == "NOT LEARNED", f"Expected NOT LEARNED verdict: {data}"
        assert "message" in data, f"Missing message: {data}"

    def test_learning_proof_nonexistent_vendor(self):
        """Nonexistent vendor should also return NOT LEARNED."""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/learning-proof/NONEXISTENT_VENDOR_XYZ")
        data = response.json()
        
        assert response.status_code == 200
        assert data.get("verdict") == "NOT LEARNED"


class TestKnowledgeSeedLearningProofRegression:
    """Regression test: GET /api/knowledge-seed/learning-proof/{vendor_id} still works."""

    def test_knowledge_seed_learning_proof_returns_200(self):
        """Knowledge seed learning proof should still work."""
        response = requests.get(f"{BASE_URL}/api/knowledge-seed/learning-proof/TUMALOC")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"

    def test_knowledge_seed_learning_proof_has_learning_sources(self):
        """Knowledge seed learning proof should have learning_sources."""
        response = requests.get(f"{BASE_URL}/api/knowledge-seed/learning-proof/TUMALOC")
        data = response.json()
        
        assert "learning_sources" in data, f"Missing learning_sources: {data}"
        assert "summary" in data, f"Missing summary: {data}"
        assert data.get("vendor_id") == "TUMALOC", f"Wrong vendor_id: {data}"


class TestAPAutoPostServiceIntegration:
    """Test that ap_auto_post_service loads posting_profile correctly."""

    def test_ap_auto_post_service_imports_posting_profile(self):
        """Verify ap_auto_post_service can import get_posting_profile_for_vendor."""
        # This tests the import path used in ap_auto_post_service.py lines 133-137
        from services.posting_pattern_analyzer import get_posting_profile_for_vendor
        assert callable(get_posting_profile_for_vendor)

    def test_ap_auto_post_service_code_structure(self):
        """Verify ap_auto_post_service has the posting profile loading code."""
        import inspect
        from services import ap_auto_post_service
        
        source = inspect.getsource(ap_auto_post_service)
        
        # Check that posting_profile loading is present
        assert "posting_profile" in source, "posting_profile variable not found in ap_auto_post_service"
        assert "get_posting_profile_for_vendor" in source, "get_posting_profile_for_vendor import not found"
        assert "suggested_posting_template" in source, "suggested_posting_template not found"
        assert "posting_profile_confidence" in source, "posting_profile_confidence not found"


class TestHealthEndpoint:
    """Basic health check to ensure backend is running."""

    def test_health_returns_200(self):
        """Health endpoint should return 200."""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
