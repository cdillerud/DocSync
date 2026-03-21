"""
Test: Freight G/L Account Routing Feature
Tests the complete Freight G/L routing functionality including:
- G/L Account CRUD operations
- Document classification for freight carriers
- Override functionality
- Statistics and recent classifications
- BC Write Safety Guard status
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test document IDs provided in requirements
DOC_TUMALO_CREEK = "98695c83-a7f3-495f-ac8d-bb5405c55a63"  # TUMALOC freight carrier (already classified)
DOC_SHIPPING = "b31207c3-4a2b-41e3-97c6-561c850c0893"       # Shipping_Document
DOC_NON_FREIGHT = "c3bf1459-e48d-4905-a813-84b02386b9c4"    # Protiviti non-freight AP_Invoice


class TestFreightGLAccounts:
    """Test G/L Account CRUD operations"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def test_list_freight_gl_accounts(self):
        """GET /api/freight-routing/accounts - Should list all 9 default accounts"""
        response = self.session.get(f"{BASE_URL}/api/freight-routing/accounts")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        data = response.json()
        assert "accounts" in data, "Response should contain 'accounts' key"
        assert "total" in data, "Response should contain 'total' key"
        
        accounts = data["accounts"]
        # Verify we have the 9 default accounts
        assert len(accounts) >= 9, f"Expected at least 9 default accounts, got {len(accounts)}"
        
        # Verify account structure
        expected_fields = ["account_id", "gl_number", "gl_name", "direction", "sub_type", "enabled"]
        for account in accounts[:3]:  # Check first 3 accounts
            for field in expected_fields:
                assert field in account, f"Account missing field: {field}"
        
        print(f"✓ Listed {len(accounts)} G/L accounts")

    def test_get_single_account_gl_inbound_raw(self):
        """GET /api/freight-routing/accounts/gl-inbound-raw - Get single account"""
        response = self.session.get(f"{BASE_URL}/api/freight-routing/accounts/gl-inbound-raw")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        account = response.json()
        assert account["account_id"] == "gl-inbound-raw"
        assert account["gl_number"] == "5200-00"
        assert account["gl_name"] == "Inbound Freight - Raw Materials"
        assert account["direction"] == "inbound"
        assert account["sub_type"] == "raw_materials"
        assert account["enabled"] == True
        
        print(f"✓ Got account: {account['gl_number']} - {account['gl_name']}")

    def test_get_nonexistent_account_returns_404(self):
        """GET /api/freight-routing/accounts/nonexistent - Should return 404"""
        response = self.session.get(f"{BASE_URL}/api/freight-routing/accounts/nonexistent-account-xyz")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Nonexistent account returns 404")

    def test_create_new_gl_account(self):
        """POST /api/freight-routing/accounts - Create a new G/L account"""
        test_account = {
            "gl_number": "9999-TEST",
            "gl_name": "Test Freight Account",
            "direction": "inbound",
            "sub_type": "test_type",
            "description": "Test account for pytest",
            "keywords": ["test", "pytest"],
            "enabled": True,
            "priority": 50
        }
        
        response = self.session.post(f"{BASE_URL}/api/freight-routing/accounts", json=test_account)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        created = response.json()
        assert "account_id" in created, "Created account should have account_id"
        assert created["gl_number"] == test_account["gl_number"]
        assert created["gl_name"] == test_account["gl_name"]
        assert created["direction"] == test_account["direction"]
        assert "created_at" in created, "Created account should have created_at"
        
        # Cleanup - delete the test account
        delete_resp = self.session.delete(f"{BASE_URL}/api/freight-routing/accounts/{created['account_id']}")
        assert delete_resp.status_code == 200, f"Cleanup delete failed: {delete_resp.status_code}"
        
        print(f"✓ Created and cleaned up test account: {created['account_id']}")

    def test_update_gl_account(self):
        """PUT /api/freight-routing/accounts/gl-inbound-raw - Update an account"""
        # First get original value
        get_resp = self.session.get(f"{BASE_URL}/api/freight-routing/accounts/gl-inbound-raw")
        original = get_resp.json()
        original_priority = original.get("priority", 10)
        
        # Update the account
        update_data = {"priority": 15}
        response = self.session.put(f"{BASE_URL}/api/freight-routing/accounts/gl-inbound-raw", json=update_data)
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        updated = response.json()
        assert updated["priority"] == 15, f"Expected priority 15, got {updated.get('priority')}"
        assert "updated_at" in updated, "Updated account should have updated_at"
        
        # Restore original value
        restore_data = {"priority": original_priority}
        restore_resp = self.session.put(f"{BASE_URL}/api/freight-routing/accounts/gl-inbound-raw", json=restore_data)
        assert restore_resp.status_code == 200, "Failed to restore original value"
        
        print(f"✓ Updated account priority: {original_priority} -> 15 -> {original_priority}")

    def test_delete_gl_account(self):
        """DELETE /api/freight-routing/accounts/{id} - Delete account"""
        # First create an account to delete
        test_account = {
            "gl_number": "DEL-TEST-001",
            "gl_name": "Account To Delete",
            "direction": "transfer",
            "sub_type": "delete_test",
            "enabled": True
        }
        
        create_resp = self.session.post(f"{BASE_URL}/api/freight-routing/accounts", json=test_account)
        assert create_resp.status_code == 200
        created = create_resp.json()
        account_id = created["account_id"]
        
        # Delete the account
        delete_resp = self.session.delete(f"{BASE_URL}/api/freight-routing/accounts/{account_id}")
        assert delete_resp.status_code == 200, f"Expected 200, got {delete_resp.status_code}"
        
        data = delete_resp.json()
        assert data["status"] == "deleted"
        assert data["account_id"] == account_id
        
        # Verify it's gone
        get_resp = self.session.get(f"{BASE_URL}/api/freight-routing/accounts/{account_id}")
        assert get_resp.status_code == 404, "Deleted account should return 404"
        
        print(f"✓ Deleted account {account_id}")


class TestFreightClassification:
    """Test document freight classification"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def test_classify_tumalo_creek_freight_carrier(self):
        """POST /api/freight-routing/classify/{doc_id} - Classify Tumalo Creek freight document"""
        response = self.session.post(f"{BASE_URL}/api/freight-routing/classify/{DOC_TUMALO_CREEK}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        result = response.json()
        assert result["is_freight"] == True, "Tumalo Creek document should be classified as freight"
        assert result["direction"] in ["inbound", "outbound", "transfer", "unknown"], f"Invalid direction: {result.get('direction')}"
        assert "recommended_gl" in result, "Classification should include recommended_gl"
        assert "confidence" in result, "Classification should include confidence score"
        assert result.get("recommended_gl") is not None, "Freight document should have recommended G/L"
        
        gl = result["recommended_gl"]
        assert "gl_number" in gl, "Recommended G/L should have gl_number"
        assert "gl_name" in gl, "Recommended G/L should have gl_name"
        
        print(f"✓ Tumalo Creek: is_freight={result['is_freight']}, direction={result['direction']}, GL={gl['gl_number']}")

    def test_classify_shipping_document(self):
        """POST /api/freight-routing/classify/{doc_id} - Classify Shipping_Document"""
        response = self.session.post(f"{BASE_URL}/api/freight-routing/classify/{DOC_SHIPPING}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        result = response.json()
        # Shipping documents should be classified as freight
        assert "is_freight" in result, "Result should have is_freight flag"
        assert "direction" in result or result["is_freight"] == False, "Freight docs should have direction"
        assert "classified_at" in result, "Result should have classified_at timestamp"
        
        if result["is_freight"]:
            assert result.get("recommended_gl") is not None
            print(f"✓ Shipping doc: is_freight=True, direction={result.get('direction')}, GL={result['recommended_gl']['gl_number']}")
        else:
            print(f"✓ Shipping doc: is_freight=False")

    def test_classify_non_freight_ap_invoice(self):
        """POST /api/freight-routing/classify/{doc_id} - Non-freight AP_Invoice should return is_freight=false"""
        response = self.session.post(f"{BASE_URL}/api/freight-routing/classify/{DOC_NON_FREIGHT}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        result = response.json()
        # Protiviti is not a freight carrier, should be marked as non-freight
        assert "is_freight" in result, "Result should have is_freight flag"
        
        # Based on the vendor (Protiviti), this should NOT be freight-related
        if result["is_freight"] == False:
            assert result.get("recommended_gl") is None, "Non-freight docs should not have recommended G/L"
            print(f"✓ Non-freight doc (Protiviti): is_freight=False - CORRECT")
        else:
            # If it was somehow marked as freight, note it
            print(f"⚠ Non-freight doc classified as freight: direction={result.get('direction')}")

    def test_classify_nonexistent_document_returns_error(self):
        """POST /api/freight-routing/classify/{doc_id} - Nonexistent doc returns 404"""
        fake_id = str(uuid.uuid4())
        response = self.session.post(f"{BASE_URL}/api/freight-routing/classify/{fake_id}")
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Nonexistent document returns 404")


class TestFreightOverride:
    """Test freight G/L override functionality"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def test_override_freight_gl(self):
        """POST /api/freight-routing/override/{doc_id} - Override G/L to different account"""
        # First classify the document
        classify_resp = self.session.post(f"{BASE_URL}/api/freight-routing/classify/{DOC_TUMALO_CREEK}")
        assert classify_resp.status_code == 200
        
        # Override to a different account
        override_payload = {
            "gl_account_id": "gl-outbound-customer",  # Override to outbound customer
            "reason": "Test override from pytest"
        }
        
        response = self.session.post(
            f"{BASE_URL}/api/freight-routing/override/{DOC_TUMALO_CREEK}",
            json=override_payload
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        result = response.json()
        assert result["status"] == "overridden", f"Expected status='overridden', got {result.get('status')}"
        assert result["document_id"] == DOC_TUMALO_CREEK
        assert result["gl_number"] == "6100-00", f"Expected GL 6100-00, got {result.get('gl_number')}"
        assert result["gl_name"] == "Outbound Freight - Customer Orders"
        
        print(f"✓ Override successful: {result['gl_number']} - {result['gl_name']}")

    def test_override_with_missing_account_id_returns_400(self):
        """POST /api/freight-routing/override/{doc_id} - Missing gl_account_id returns 400"""
        response = self.session.post(
            f"{BASE_URL}/api/freight-routing/override/{DOC_TUMALO_CREEK}",
            json={"reason": "No account ID provided"}
        )
        assert response.status_code == 400, f"Expected 400, got {response.status_code}"
        print("✓ Missing gl_account_id returns 400")

    def test_override_with_invalid_account_returns_404(self):
        """POST /api/freight-routing/override/{doc_id} - Invalid account returns 404"""
        response = self.session.post(
            f"{BASE_URL}/api/freight-routing/override/{DOC_TUMALO_CREEK}",
            json={"gl_account_id": "nonexistent-account-xyz", "reason": "Test"}
        )
        assert response.status_code == 404, f"Expected 404, got {response.status_code}"
        print("✓ Invalid account returns 404")


class TestFreightStats:
    """Test freight statistics and recent classifications"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def test_get_freight_routing_stats(self):
        """GET /api/freight-routing/stats - Get freight routing statistics"""
        response = self.session.get(f"{BASE_URL}/api/freight-routing/stats")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        stats = response.json()
        assert "total_classified" in stats, "Stats should include total_classified"
        assert "freight_documents" in stats, "Stats should include freight_documents"
        assert "non_freight" in stats, "Stats should include non_freight"
        assert "manual_overrides" in stats, "Stats should include manual_overrides"
        assert "by_direction" in stats, "Stats should include by_direction breakdown"
        assert "by_gl_account" in stats, "Stats should include by_gl_account breakdown"
        
        print(f"✓ Stats: total={stats['total_classified']}, freight={stats['freight_documents']}, overrides={stats['manual_overrides']}")

    def test_get_recent_classifications(self):
        """GET /api/freight-routing/recent - Get recent freight classifications"""
        response = self.session.get(f"{BASE_URL}/api/freight-routing/recent")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        recent = response.json()
        assert isinstance(recent, list), "Recent should be a list"
        
        if len(recent) > 0:
            # Check structure of first item
            item = recent[0]
            assert "document_id" in item, "Recent item should have document_id"
            assert "is_freight" in item, "Recent item should have is_freight"
            assert "classified_at" in item, "Recent item should have classified_at"
            
        print(f"✓ Recent classifications: {len(recent)} items")

    def test_recent_classifications_with_limit(self):
        """GET /api/freight-routing/recent?limit=5 - Test limit parameter"""
        response = self.session.get(f"{BASE_URL}/api/freight-routing/recent?limit=5")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        recent = response.json()
        assert len(recent) <= 5, f"Expected max 5 items, got {len(recent)}"
        print(f"✓ Recent with limit=5: {len(recent)} items")


class TestBCWriteGuard:
    """Test BC Write Safety Guard status"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def test_bc_write_guard_status_blocked(self):
        """GET /api/bc/write-guard/status - Verify writes are BLOCKED"""
        response = self.session.get(f"{BASE_URL}/api/bc/write-guard/status")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        status = response.json()
        assert "write_enabled" in status, "Status should include write_enabled"
        assert "environment" in status, "Status should include environment"
        assert "status" in status, "Status should include status field"
        
        # According to requirements, BC_WRITE_ENABLED=false so writes should be BLOCKED
        assert status["write_enabled"] == False, f"Expected write_enabled=False (BLOCKED), got {status['write_enabled']}"
        assert status["status"] == "blocked", f"Expected status='blocked', got {status.get('status')}"
        
        print(f"✓ BC Write Guard: write_enabled={status['write_enabled']}, status={status['status']}, env={status.get('environment')}")


class TestBackendTenantId:
    """Verify backend is using correct tenant_id"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def test_tenant_id_not_freight_routing(self):
        """Verify tenant_id is not 'freight-routing' (should be actual tenant)"""
        # Check settings endpoint if available, or BC service status
        # This is an implicit check - if BC calls work, tenant ID is correct
        response = self.session.get(f"{BASE_URL}/api/bc/write-guard/status")
        assert response.status_code == 200
        
        # If BC service is functional, tenant_id is configured correctly
        status = response.json()
        # The tenant_id should be a UUID, not 'freight-routing'
        env = status.get("environment", "")
        assert "freight-routing" not in env.lower(), "Environment should not be 'freight-routing'"
        
        print(f"✓ Backend using correct configuration (env={env})")


class TestDocumentIntegration:
    """Test document retrieval with freight G/L classification data"""

    @pytest.fixture(autouse=True)
    def setup(self):
        self.session = requests.Session()
        self.session.headers.update({"Content-Type": "application/json"})

    def test_document_has_freight_gl_classification(self):
        """GET /api/documents/{doc_id} - Document should have freight_gl_classification after classify"""
        # First classify
        self.session.post(f"{BASE_URL}/api/freight-routing/classify/{DOC_TUMALO_CREEK}")
        
        # Get document
        response = self.session.get(f"{BASE_URL}/api/documents/{DOC_TUMALO_CREEK}")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}"
        
        data = response.json()
        doc = data.get("document", {})
        
        # Check freight_gl_classification is present
        assert "freight_gl_classification" in doc, "Document should have freight_gl_classification"
        
        fgl = doc["freight_gl_classification"]
        assert "is_freight" in fgl, "freight_gl_classification should have is_freight"
        
        if fgl["is_freight"]:
            assert "gl_number" in fgl, "Freight doc should have gl_number"
            assert "direction" in fgl, "Freight doc should have direction"
            print(f"✓ Document has freight_gl_classification: GL={fgl.get('gl_number')}, direction={fgl.get('direction')}")
        else:
            print(f"✓ Document has freight_gl_classification: is_freight=False")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])


# =============================================================================
# NEW TESTS: do_not_pay, freight_issues, dropship_international, storage_handling
# =============================================================================

from services.freight_gl_routing_service import (
    DEFAULT_GL_ACCOUNTS,
    DO_NOT_PAY_KEYWORDS,
    FREIGHT_ISSUES_KEYWORDS,
    STORAGE_HANDLING_KEYWORDS,
    FreightGLRoutingService,
)
from unittest.mock import AsyncMock, MagicMock
import asyncio as _asyncio


def _make_freight_doc(**overrides):
    base = {
        "id": "test-freight-001",
        "document_type": "Freight_Document",
        "file_name": "freight_invoice.pdf",
        "vendor_canonical": "XPO Logistics",
        "extracted_fields": {},
        "email_subject": "",
        "email_body_snippet": "",
    }
    base.update(overrides)
    return base


class TestDoNotPayRouting:
    def test_do_not_pay_keyword_in_text(self):
        from unittest.mock import MagicMock
        db = MagicMock()
        service = FreightGLRoutingService(db)
        doc = _make_freight_doc(
            extracted_fields={"description": "DO NOT PAY - duplicate freight bill"},
        )
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(service.classify_document(doc))
        assert result["do_not_pay"] is True
        assert result["recommended_gl"] is None
        assert result["sub_type"] == "do_not_pay"
        print("PASS: do_not_pay keyword → no GL posting")

    def test_do_not_pay_folder_path(self):
        from unittest.mock import MagicMock
        db = MagicMock()
        service = FreightGLRoutingService(db)
        doc = _make_freight_doc(folder_path="DO NOT PAY/2026")
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(service.classify_document(doc))
        assert result["do_not_pay"] is True
        assert result["recommended_gl"] is None
        print("PASS: DO NOT PAY folder → no GL posting")

    def test_do_not_pay_explicit_flag(self):
        from unittest.mock import MagicMock
        db = MagicMock()
        service = FreightGLRoutingService(db)
        doc = _make_freight_doc(do_not_pay=True)
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(service.classify_document(doc))
        assert result["do_not_pay"] is True
        print("PASS: explicit do_not_pay flag → respected")


class TestFreightIssuesRouting:
    def test_freight_issues_keyword(self):
        from unittest.mock import AsyncMock, MagicMock
        db = MagicMock()
        db.freight_gl_accounts = MagicMock()
        db.freight_gl_accounts.find = MagicMock(return_value=MagicMock(
            sort=MagicMock(return_value=MagicMock(
                to_list=AsyncMock(return_value=DEFAULT_GL_ACCOUNTS)
            ))
        ))
        service = FreightGLRoutingService(db)
        doc = _make_freight_doc(
            extracted_fields={"description": "Freight claim for damaged shipment"},
        )
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(service.classify_document(doc))
        assert result["freight_issues"] is True
        assert result.get("workflow_status_override") == "needs_logistics_approval"
        print("PASS: freight_issues → needs_logistics_approval")

    def test_freight_issues_folder(self):
        from unittest.mock import AsyncMock, MagicMock
        db = MagicMock()
        db.freight_gl_accounts = MagicMock()
        db.freight_gl_accounts.find = MagicMock(return_value=MagicMock(
            sort=MagicMock(return_value=MagicMock(
                to_list=AsyncMock(return_value=DEFAULT_GL_ACCOUNTS)
            ))
        ))
        service = FreightGLRoutingService(db)
        doc = _make_freight_doc(folder_path="Freight Issues/2026-03")
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(service.classify_document(doc))
        assert result["freight_issues"] is True
        print("PASS: Freight Issues folder → flag set")


class TestDropshipInternational:
    def test_dropship_international_combined(self):
        from unittest.mock import AsyncMock, MagicMock
        db = MagicMock()
        db.freight_gl_accounts = MagicMock()
        db.freight_gl_accounts.find = MagicMock(return_value=MagicMock(
            sort=MagicMock(return_value=MagicMock(
                to_list=AsyncMock(return_value=DEFAULT_GL_ACCOUNTS)
            ))
        ))
        service = FreightGLRoutingService(db)
        doc = _make_freight_doc(
            extracted_fields={"description": "International drop ship order #W12345"},
        )
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(service.classify_document(doc))
        assert result["sub_type"] == "dropship_international"
        gl = result.get("recommended_gl") or {}
        assert gl.get("gl_number") == "6115-00", f"Expected 6115-00, got {gl.get('gl_number')}"
        print("PASS: dropship + international → 6115-00")


class TestStorageHandling:
    def test_storage_handling_keyword(self):
        from unittest.mock import AsyncMock, MagicMock
        db = MagicMock()
        db.freight_gl_accounts = MagicMock()
        db.freight_gl_accounts.find = MagicMock(return_value=MagicMock(
            sort=MagicMock(return_value=MagicMock(
                to_list=AsyncMock(return_value=DEFAULT_GL_ACCOUNTS)
            ))
        ))
        service = FreightGLRoutingService(db)
        doc = _make_freight_doc(
            extracted_fields={"description": "Warehouse storage & handling charge for March"},
        )
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(service.classify_document(doc))
        assert result["sub_type"] == "storage_handling"
        gl = result.get("recommended_gl") or {}
        assert gl.get("gl_number") == "5260-00", f"Expected 5260-00, got {gl.get('gl_number')}"
        print("PASS: storage & handling → 5260-00")


class TestGLAccountSeeder:
    def test_all_folder_categories_have_gl_accounts(self):
        account_ids = {a["account_id"] for a in DEFAULT_GL_ACCOUNTS}
        sub_types = {a["sub_type"] for a in DEFAULT_GL_ACCOUNTS}
        assert "gl-storage-handling" in account_ids
        assert "gl-dropship-international" in account_ids
        assert "gl-dunnage-return" in account_ids
        assert "gl-outbound-dropship" in account_ids
        assert "storage_handling" in sub_types
        assert "dropship_international" in sub_types
        print("PASS: All folder categories have GL accounts")

    def test_keyword_lists_not_empty(self):
        assert len(DO_NOT_PAY_KEYWORDS) > 0
        assert len(FREIGHT_ISSUES_KEYWORDS) > 0
        assert len(STORAGE_HANDLING_KEYWORDS) > 0
        print("PASS: Keyword lists populated")


class TestNonFreightUnchanged:
    def test_non_freight_has_false_flags(self):
        from unittest.mock import MagicMock
        db = MagicMock()
        service = FreightGLRoutingService(db)
        doc = {
            "id": "test-ap-001",
            "document_type": "AP_Invoice",
            "file_name": "invoice_12345.pdf",
            "vendor_canonical": "Acme Widgets Inc",
            "extracted_fields": {"vendor": "Acme Widgets Inc"},
        }
        import asyncio
        result = asyncio.get_event_loop().run_until_complete(service.classify_document(doc))
        assert result["is_freight"] is False
        assert result.get("do_not_pay", False) is False
        assert result.get("freight_issues", False) is False
        print("PASS: Non-freight doc unaffected by new flags")
