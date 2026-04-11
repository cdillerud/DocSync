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

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://po-vendor-resolver.preview.emergentagent.com').rstrip('/')


class TestHealthEndpoint:
    """Basic health check"""
    
    def test_health_returns_200(self):
        """GET /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("PASS: /api/health returns 200 with status=healthy")


class TestAutoPostSettings:
    """Test GET/PUT /api/posting-patterns/settings"""
    
    def test_get_settings_returns_200(self):
        """GET /api/posting-patterns/settings returns 200 with expected fields"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/settings")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        
        # Verify required fields exist
        assert "auto_post_enabled" in data, "Response should have auto_post_enabled field"
        assert "min_confidence" in data, "Response should have min_confidence field"
        assert "min_invoices_analyzed" in data, "Response should have min_invoices_analyzed field"
        assert "require_po_match" in data, "Response should have require_po_match field"
        assert "allowed_vendors" in data, "Response should have allowed_vendors field"
        assert "blocked_vendors" in data, "Response should have blocked_vendors field"
        
        print(f"PASS: GET /api/posting-patterns/settings returns 200 with fields: {list(data.keys())}")
    
    def test_put_settings_updates_and_returns_updated_fields(self):
        """PUT /api/posting-patterns/settings updates configuration"""
        # First get current settings
        get_response = requests.get(f"{BASE_URL}/api/posting-patterns/settings")
        original_settings = get_response.json()
        
        # Update with new value
        new_min_invoices = 25
        response = requests.put(
            f"{BASE_URL}/api/posting-patterns/settings",
            json={"min_invoices_analyzed": new_min_invoices},
            headers={"Content-Type": "application/json"}
        )
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        
        # Verify update was applied
        assert data.get("status") == "updated", "Response should have status=updated"
        assert data.get("min_invoices_analyzed") == new_min_invoices, f"Expected min_invoices_analyzed={new_min_invoices}"
        assert "updated_at" in data, "Response should have updated_at field"
        
        # Restore original value
        requests.put(
            f"{BASE_URL}/api/posting-patterns/settings",
            json={"min_invoices_analyzed": original_settings.get("min_invoices_analyzed", 10)},
            headers={"Content-Type": "application/json"}
        )
        
        print(f"PASS: PUT /api/posting-patterns/settings updates and returns updated fields")


class TestReadyQueue:
    """Test GET /api/posting-patterns/ready-queue"""
    
    def test_ready_queue_returns_200(self):
        """GET /api/posting-patterns/ready-queue returns 200 with expected structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/ready-queue?limit=10")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        
        # Verify structure
        assert "count" in data, "Response should have count field"
        assert "documents" in data, "Response should have documents field"
        assert isinstance(data["documents"], list), "documents should be a list"
        
        print(f"PASS: GET /api/posting-patterns/ready-queue returns 200 with count={data['count']}")


class TestVendorSummary:
    """Test GET /api/posting-patterns/vendor-summary"""
    
    def test_vendor_summary_returns_200(self):
        """GET /api/posting-patterns/vendor-summary returns 200 with expected structure"""
        response = requests.get(f"{BASE_URL}/api/posting-patterns/vendor-summary?limit=10")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        
        # Verify structure
        assert "count" in data, "Response should have count field"
        assert "vendors" in data, "Response should have vendors field"
        assert "settings" in data, "Response should have settings field"
        assert "ready_total" in data, "Response should have ready_total field"
        assert isinstance(data["vendors"], list), "vendors should be a list"
        
        # Verify settings sub-structure
        settings = data["settings"]
        assert "auto_post_enabled" in settings, "settings should have auto_post_enabled"
        assert "min_confidence" in settings, "settings should have min_confidence"
        assert "min_invoices_analyzed" in settings, "settings should have min_invoices_analyzed"
        
        # If there are vendors, verify auto_post_eligible field exists
        if data["vendors"]:
            vendor = data["vendors"][0]
            assert "auto_post_eligible" in vendor, "vendor should have auto_post_eligible field"
        
        print(f"PASS: GET /api/posting-patterns/vendor-summary returns 200 with count={data['count']}")


class TestDraftPreview:
    """Test POST /api/posting-patterns/draft-preview/{doc_id}"""
    
    def test_draft_preview_returns_graceful_error_for_invalid_doc(self):
        """POST /api/posting-patterns/draft-preview/{doc_id} returns graceful error for invalid doc"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/draft-preview/invalid-doc-id")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        
        # Should return error field, not crash
        assert "error" in data, "Response should have error field for invalid doc"
        assert data["error"] == "Document not found", f"Expected 'Document not found' but got '{data.get('error')}'"
        
        print(f"PASS: POST /api/posting-patterns/draft-preview returns graceful error: {data['error']}")


class TestCreateDraft:
    """Test POST /api/posting-patterns/create-draft/{doc_id}"""
    
    def test_create_draft_returns_graceful_error_for_invalid_doc(self):
        """POST /api/posting-patterns/create-draft/{doc_id} returns graceful error for invalid doc"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/create-draft/invalid-doc-id")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        
        # Should return error field and success=false, not crash
        assert "error" in data, "Response should have error field for invalid doc"
        assert data.get("success") is False, "success should be False for invalid doc"
        assert data["error"] == "Document not found", f"Expected 'Document not found' but got '{data.get('error')}'"
        
        print(f"PASS: POST /api/posting-patterns/create-draft returns graceful error: {data['error']}")


class TestAutoDraftQueue:
    """Test POST /api/posting-patterns/auto-draft-queue"""
    
    def test_auto_draft_queue_returns_200_with_results(self):
        """POST /api/posting-patterns/auto-draft-queue returns 200 with results structure"""
        response = requests.post(f"{BASE_URL}/api/posting-patterns/auto-draft-queue?limit=10")
        assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
        data = response.json()
        
        # Verify structure - should have counts
        assert "processed" in data, "Response should have processed field"
        assert "drafted" in data, "Response should have drafted field"
        assert "skipped" in data, "Response should have skipped field"
        assert "errors" in data, "Response should have errors field"
        assert "details" in data, "Response should have details field"
        
        print(f"PASS: POST /api/posting-patterns/auto-draft-queue returns 200 with processed={data['processed']}, drafted={data['drafted']}, skipped={data['skipped']}, errors={data['errors']}")
    
    def test_auto_draft_queue_returns_disabled_reason_when_disabled(self):
        """POST /api/posting-patterns/auto-draft-queue returns reason='Auto-post is disabled' when disabled"""
        # First disable auto-post
        requests.put(
            f"{BASE_URL}/api/posting-patterns/settings",
            json={"auto_post_enabled": False},
            headers={"Content-Type": "application/json"}
        )
        
        try:
            # Run the queue
            response = requests.post(f"{BASE_URL}/api/posting-patterns/auto-draft-queue?limit=10")
            assert response.status_code == 200, f"Expected 200 but got {response.status_code}"
            data = response.json()
            
            # Should have reason field indicating disabled
            assert "reason" in data, "Response should have reason field when disabled"
            assert data["reason"] == "Auto-post is disabled", f"Expected 'Auto-post is disabled' but got '{data.get('reason')}'"
            assert data["processed"] == 0, "processed should be 0 when disabled"
            
            print(f"PASS: POST /api/posting-patterns/auto-draft-queue returns reason='{data['reason']}' when disabled")
        finally:
            # Re-enable auto-post
            requests.put(
                f"{BASE_URL}/api/posting-patterns/settings",
                json={"auto_post_enabled": True},
                headers={"Content-Type": "application/json"}
            )


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
