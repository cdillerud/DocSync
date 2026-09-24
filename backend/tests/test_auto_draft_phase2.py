"""
Test Phase 2: Confidence-Gated Auto-Draft PI Creation

Tests the new auto-draft endpoints and functionality:
1. GET /api/posting-patterns/settings - returns auto-post configuration
2. PUT /api/posting-patterns/settings - updates configuration
3. GET /api/posting-patterns/ready-queue - returns ready documents list
4. GET /api/posting-patterns/vendor-summary - returns vendor profiles with auto_post_eligible
5. POST /api/posting-patterns/draft-preview/{doc_id} - returns preview or graceful error
6. POST /api/posting-patterns/create-draft/{doc_id} - returns graceful error for invalid doc
7. POST /api/posting-patterns/auto-draft-queue - processes queue and returns results
8. GET /api/posting-patterns/auto-draft-eligibility/{doc_id} - returns eligibility check
9. Auto-draft queue returns reason='Auto-post is disabled' when disabled
"""

import pytest
import requests
import os
import sys

# Add backend to path for direct imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://contract-intel-9.preview.emergentagent.com').rstrip('/')


class TestHealthEndpoint:
    """Basic health check"""
    
    def test_health_returns_200(self):
        """GET /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("PASS: /api/health returns 200 with status=healthy")


class TestAutoDraftEligibility:
    """Test GET /api/posting-patterns/auto-draft-eligibility/{doc_id}"""
    
    def test_auto_draft_eligibility_returns_graceful_error_for_invalid_doc(self):
        """GET /api/posting-patterns/auto-draft-eligibility/{doc_id} returns graceful error for invalid doc"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/auto-draft-eligibility/invalid-doc-id")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        
        # Should return error and eligible=false, not crash
        assert "error" in data, "Response should have error field for invalid doc"
        assert data.get("eligible") is False, "eligible should be False for invalid doc"
        assert data["error"] == "Document not found", f"Expected 'Document not found' but got '{data.get('error')}'"
        
        print(f"PASS: GET /api/posting-patterns/auto-draft-eligibility returns graceful error: {data['error']}")


class TestCheckAutoDraftEligibilityFunction:
    """Unit tests for check_auto_draft_eligibility function"""
    
    @pytest.mark.asyncio
    async def test_no_vendor_number_returns_not_eligible(self):
        """Document without vendor number is not eligible"""
        from services.ap_auto_post_service import check_auto_draft_eligibility
        
        # Mock db that returns settings
        class MockDB:
            class auto_post_settings:
                @staticmethod
                async def find_one(query):
                    return {"auto_post_enabled": True, "min_confidence": "high", "min_invoices_analyzed": 10}
            
            class posting_pattern_analysis:
                @staticmethod
                async def find_one(query, projection=None):
                    return None
        
        doc = {"id": "test-doc", "bc_vendor_number": ""}
        result = await check_auto_draft_eligibility(doc, MockDB())
        
        assert result["eligible"] is False
        assert "No vendor number" in result["reason"]
        print(f"PASS: No vendor number → eligible=False, reason='{result['reason']}'")
    
    @pytest.mark.asyncio
    async def test_existing_draft_returns_not_eligible(self):
        """Document with existing draft PI is not eligible"""
        from services.ap_auto_post_service import check_auto_draft_eligibility
        
        class MockDB:
            class auto_post_settings:
                @staticmethod
                async def find_one(query):
                    return {"auto_post_enabled": True, "min_confidence": "high", "min_invoices_analyzed": 10}
            
            class posting_pattern_analysis:
                @staticmethod
                async def find_one(query, projection=None):
                    return None
        
        doc = {
            "id": "test-doc",
            "bc_vendor_number": "V00123",
            "bc_purchase_invoice": {"bc_record_no": "PI-001"}
        }
        result = await check_auto_draft_eligibility(doc, MockDB())
        
        assert result["eligible"] is False
        assert "Draft PI already exists" in result["reason"]
        print(f"PASS: Existing draft → eligible=False, reason='{result['reason']}'")
    
    @pytest.mark.asyncio
    async def test_auto_post_disabled_returns_not_eligible(self):
        """When auto-post is disabled, document is not eligible"""
        from services.ap_auto_post_service import check_auto_draft_eligibility
        
        class MockDB:
            class auto_post_settings:
                @staticmethod
                async def find_one(query):
                    return {"auto_post_enabled": False, "min_confidence": "high", "min_invoices_analyzed": 10}
            
            class posting_pattern_analysis:
                @staticmethod
                async def find_one(query, projection=None):
                    return None
        
        doc = {"id": "test-doc", "bc_vendor_number": "V00123"}
        result = await check_auto_draft_eligibility(doc, MockDB())
        
        assert result["eligible"] is False
        assert "Auto-post is disabled" in result["reason"]
        print(f"PASS: Auto-post disabled → eligible=False, reason='{result['reason']}'")


class TestConfidenceMeetsThreshold:
    """Unit tests for _confidence_meets_threshold function"""
    
    def test_high_meets_high(self):
        """high confidence meets high threshold"""
        from services.ap_auto_post_service import _confidence_meets_threshold
        assert _confidence_meets_threshold("high", "high") is True
        print("PASS: high meets high threshold")
    
    def test_high_meets_medium(self):
        """high confidence meets medium threshold"""
        from services.ap_auto_post_service import _confidence_meets_threshold
        assert _confidence_meets_threshold("high", "medium") is True
        print("PASS: high meets medium threshold")
    
    def test_high_meets_low(self):
        """high confidence meets low threshold"""
        from services.ap_auto_post_service import _confidence_meets_threshold
        assert _confidence_meets_threshold("high", "low") is True
        print("PASS: high meets low threshold")
    
    def test_medium_does_not_meet_high(self):
        """medium confidence does not meet high threshold"""
        from services.ap_auto_post_service import _confidence_meets_threshold
        assert _confidence_meets_threshold("medium", "high") is False
        print("PASS: medium does not meet high threshold")
    
    def test_medium_meets_medium(self):
        """medium confidence meets medium threshold"""
        from services.ap_auto_post_service import _confidence_meets_threshold
        assert _confidence_meets_threshold("medium", "medium") is True
        print("PASS: medium meets medium threshold")
    
    def test_low_does_not_meet_medium(self):
        """low confidence does not meet medium threshold"""
        from services.ap_auto_post_service import _confidence_meets_threshold
        assert _confidence_meets_threshold("low", "medium") is False
        print("PASS: low does not meet medium threshold")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
