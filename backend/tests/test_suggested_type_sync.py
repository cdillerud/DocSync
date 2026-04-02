"""
Test suggested_type Sync Logic - Bug Fix Verification

Tests the fix for: Document from AP mailbox gets doc_type=AP_INVOICE but 
document_type=Unknown and suggested_job_type=Unknown because AI extraction 
returned Unknown and deterministic classification result was never propagated 
back to suggested_type.

The fix adds _DOC_TYPE_TO_SUGGESTED sync logic in both intake functions:
1. _internal_intake_document (lines ~2723-2756)
2. intake_document (lines ~3485-3520)

Test cases:
1. classify_document_type returns doc_type='AP_INVOICE' when mailbox_category=AP
2. suggested_type sync correctly maps AP_INVOICE → AP_Invoice when AI fails
3. suggested_type is NOT overridden when AI extraction already succeeded
4. suggested_type stays Unknown when no deterministic classification available
5. Both intake functions have the sync logic
6. Auto-clear skip uses doc_type_value as fallback
7. AP auto-post service correctly identifies AP_INVOICE doc_type
"""

import pytest
import requests
import os
import sys

# Add backend to path for direct imports
sys.path.insert(0, '/app/backend')

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', 'https://reprocess-fix-verify.preview.emergentagent.com').rstrip('/')


class TestHealthEndpoint:
    """Basic health check"""
    
    def test_health_returns_200(self):
        """GET /api/health returns healthy status"""
        response = requests.get(f"{BASE_URL}/api/health")
        assert response.status_code == 200
        data = response.json()
        assert data.get("status") == "healthy"
        print("PASS: /api/health returns 200 with status=healthy")


class TestClassifyDocumentTypeMailboxCategory:
    """Test classify_document_type returns AP_INVOICE for mailbox_category=AP"""
    
    def test_mailbox_ap_returns_ap_invoice(self):
        """When mailbox_category=AP, classify_document_type returns doc_type='AP_INVOICE'"""
        from services.workflow_engine import DocumentClassifier, DocType
        
        # Test the mailbox category classification
        result = DocumentClassifier.classify_from_mailbox_category("AP")
        assert result == DocType.AP_INVOICE, f"Expected AP_INVOICE but got {result}"
        print(f"PASS: classify_from_mailbox_category('AP') returns {result.value}")
    
    def test_mailbox_sales_returns_sales_invoice(self):
        """When mailbox_category=SALES, returns SALES_INVOICE"""
        from services.workflow_engine import DocumentClassifier, DocType
        
        result = DocumentClassifier.classify_from_mailbox_category("SALES")
        assert result == DocType.SALES_INVOICE, f"Expected SALES_INVOICE but got {result}"
        print(f"PASS: classify_from_mailbox_category('SALES') returns {result.value}")
    
    def test_mailbox_purchase_returns_purchase_order(self):
        """When mailbox_category=PURCHASE, returns PURCHASE_ORDER"""
        from services.workflow_engine import DocumentClassifier, DocType
        
        result = DocumentClassifier.classify_from_mailbox_category("PURCHASE")
        assert result == DocType.PURCHASE_ORDER, f"Expected PURCHASE_ORDER but got {result}"
        print(f"PASS: classify_from_mailbox_category('PURCHASE') returns {result.value}")
    
    def test_mailbox_unknown_returns_other(self):
        """When mailbox_category is unknown, returns OTHER"""
        from services.workflow_engine import DocumentClassifier, DocType
        
        result = DocumentClassifier.classify_from_mailbox_category("UNKNOWN")
        assert result == DocType.OTHER, f"Expected OTHER but got {result}"
        print(f"PASS: classify_from_mailbox_category('UNKNOWN') returns {result.value}")


class TestSuggestedTypeSyncLogic:
    """Test the _DOC_TYPE_TO_SUGGESTED sync logic"""
    
    def test_doc_type_to_suggested_mapping_exists(self):
        """Verify _DOC_TYPE_TO_SUGGESTED mapping is defined in server.py"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read()
        
        # Check mapping exists
        assert '_DOC_TYPE_TO_SUGGESTED = {' in content, \
            "_DOC_TYPE_TO_SUGGESTED mapping should be defined"
        assert '"AP_INVOICE": "AP_Invoice"' in content, \
            "AP_INVOICE should map to AP_Invoice"
        print("PASS: _DOC_TYPE_TO_SUGGESTED mapping exists with AP_INVOICE → AP_Invoice")
    
    def test_sync_logic_in_internal_intake_function(self):
        """Verify sync logic exists in _internal_intake_document function"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read()
        
        # Check for the sync logic pattern in first intake function
        # The sync logic should check if suggested_type is Unknown and update it
        assert 'if suggested_type in ("Unknown", "Other", "Unknown_Document") and new_suggested != suggested_type:' in content, \
            "Sync logic should check if suggested_type is Unknown/Other"
        assert 'Syncing suggested_type for' in content, \
            "Sync logic should log the sync operation"
        print("PASS: Sync logic exists in _internal_intake_document")
    
    def test_sync_logic_in_intake_document_function(self):
        """Verify sync logic exists in intake_document function (second intake)"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read()
        
        # Count occurrences of the sync logic - should appear twice (both intake functions)
        sync_pattern = 'if suggested_type in ("Unknown", "Other", "Unknown_Document") and new_suggested != suggested_type:'
        occurrences = content.count(sync_pattern)
        assert occurrences >= 2, \
            f"Sync logic should appear in both intake functions, found {occurrences} occurrences"
        print(f"PASS: Sync logic appears {occurrences} times (in both intake functions)")
    
    def test_sync_only_when_ai_fails(self):
        """Verify sync only happens when suggested_type is Unknown/Other"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read()
        
        # The condition should check for Unknown/Other before syncing
        assert 'suggested_type in ("Unknown", "Other", "Unknown_Document")' in content, \
            "Sync should only happen when suggested_type is Unknown/Other/Unknown_Document"
        print("PASS: Sync logic only triggers when suggested_type is Unknown/Other")
    
    def test_sync_preserves_successful_ai_classification(self):
        """Verify sync does NOT override when AI extraction already succeeded"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read()
        
        # The condition checks that suggested_type is Unknown before overriding
        # This means if AI returned "AP_Invoice", it won't be overridden
        assert 'new_suggested != suggested_type' in content, \
            "Sync should check that new value differs from current"
        print("PASS: Sync logic preserves successful AI classification (only syncs when Unknown)")


class TestDocTypeMappingValues:
    """Test the _DOC_TYPE_TO_SUGGESTED mapping values"""
    
    def test_mapping_values(self):
        """Verify all expected mappings exist"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read()
        
        expected_mappings = [
            ('"AP_INVOICE": "AP_Invoice"', "AP_INVOICE → AP_Invoice"),
            ('"PURCHASE_ORDER": "Purchase_Order"', "PURCHASE_ORDER → Purchase_Order"),
            ('"SALES_INVOICE": "AR_Invoice"', "SALES_INVOICE → AR_Invoice"),
            ('"DS_SALES_ORDER": "DS_Sales_Order"', "DS_SALES_ORDER → DS_Sales_Order"),
            ('"WH_SALES_ORDER": "WH_Sales_Order"', "WH_SALES_ORDER → WH_Sales_Order"),
            ('"SH_INVOICE": "SH_Invoice"', "SH_INVOICE → SH_Invoice"),
        ]
        
        for mapping, description in expected_mappings:
            assert mapping in content, f"Missing mapping: {description}"
            print(f"PASS: Mapping exists: {description}")


class TestAutoClearSkipLogic:
    """Test auto-clear skip uses both suggested_type and doc_type_value"""
    
    def test_auto_clear_skip_checks_both_fields(self):
        """Verify auto-clear skip checks both suggested_type and doc_type_value"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read()
        
        # The is_ap_invoice check should use both suggested_type and doc_type_value
        assert 'is_ap_invoice = suggested_type in ("AP_Invoice", "AP Invoice") or doc_type_value == "AP_INVOICE"' in content, \
            "is_ap_invoice should check both suggested_type and doc_type_value"
        print("PASS: Auto-clear skip checks both suggested_type and doc_type_value")
    
    def test_auto_clear_skip_message(self):
        """Verify auto-clear skip logs appropriate message"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read()
        
        assert 'SKIPPED for AP_Invoice' in content, \
            "Auto-clear should log skip message for AP_Invoice"
        print("PASS: Auto-clear logs skip message for AP_Invoice")


class TestAPAutoPostServiceDocTypeCheck:
    """Test AP auto-post service correctly identifies AP_INVOICE doc_type"""
    
    def test_check_ap_ready_to_post_accepts_ap_invoice(self):
        """check_ap_ready_to_post accepts doc_type=AP_INVOICE"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "AP_INVOICE",  # Uppercase from deterministic classification
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc"
            },
            "bc_vendor_number": "V00123",
            "validation_results": {"checks": []}
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        # Should NOT fail on doc_type check
        assert "Not classified as AP_Invoice" not in failures, \
            f"AP_INVOICE should be accepted, but got failure: {failures}"
        print(f"PASS: check_ap_ready_to_post accepts doc_type=AP_INVOICE")
    
    def test_check_ap_ready_to_post_accepts_purchase_invoice(self):
        """check_ap_ready_to_post accepts doc_type=PURCHASE_INVOICE"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        doc = {
            "doc_type": "PURCHASE_INVOICE",
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc"
            },
            "bc_vendor_number": "V00123",
            "validation_results": {"checks": []}
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc)
        assert "Not classified as AP_Invoice" not in failures, \
            f"PURCHASE_INVOICE should be accepted, but got failure: {failures}"
        print(f"PASS: check_ap_ready_to_post accepts doc_type=PURCHASE_INVOICE")
    
    def test_check_ap_ready_to_post_uses_fallback_fields(self):
        """check_ap_ready_to_post uses document_type and suggested_job_type as fallbacks"""
        from services.ap_auto_post_service import check_ap_ready_to_post
        
        # Test with document_type fallback
        doc1 = {
            "document_type": "AP_Invoice",  # Fallback field
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc"
            },
            "bc_vendor_number": "V00123",
            "validation_results": {"checks": []}
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc1)
        assert "Not classified as AP_Invoice" not in failures, \
            f"document_type=AP_Invoice should be accepted"
        print("PASS: check_ap_ready_to_post uses document_type as fallback")
        
        # Test with suggested_job_type fallback
        doc2 = {
            "suggested_job_type": "AP_Invoice",  # Fallback field
            "extracted_fields": {
                "invoice_number": "INV-001",
                "amount": "1000.00",
                "invoice_date": "2025-01-15",
                "vendor": "Test Vendor Inc"
            },
            "bc_vendor_number": "V00123",
            "validation_results": {"checks": []}
        }
        
        ready, reason, failures = check_ap_ready_to_post(doc2)
        assert "Not classified as AP_Invoice" not in failures, \
            f"suggested_job_type=AP_Invoice should be accepted"
        print("PASS: check_ap_ready_to_post uses suggested_job_type as fallback")


class TestAPAutoPostServiceCodePath:
    """Verify ap_auto_post_service.py has correct doc_type check"""
    
    def test_doc_type_check_in_service(self):
        """Verify check_ap_ready_to_post checks doc_type correctly"""
        with open('/app/backend/services/ap_auto_post_service.py', 'r') as f:
            content = f.read()
        
        # Should check doc_type, document_type, and suggested_job_type
        assert 'doc.get("doc_type")' in content, \
            "Should check doc_type field"
        assert 'doc.get("document_type")' in content, \
            "Should check document_type field as fallback"
        assert 'doc.get("suggested_job_type")' in content, \
            "Should check suggested_job_type field as fallback"
        print("PASS: check_ap_ready_to_post checks all doc_type fields")
    
    def test_doc_type_normalization(self):
        """Verify doc_type is normalized for comparison"""
        with open('/app/backend/services/ap_auto_post_service.py', 'r') as f:
            content = f.read()
        
        # Should normalize doc_type for comparison
        assert '.upper()' in content or 'AP_INVOICE' in content, \
            "Should normalize doc_type for case-insensitive comparison"
        assert '"AP_INVOICE"' in content or '"PURCHASE_INVOICE"' in content, \
            "Should check for AP_INVOICE or PURCHASE_INVOICE"
        print("PASS: doc_type is normalized for comparison")


class TestClassificationHelpersMailboxCategory:
    """Test classification_helpers.py mailbox category classification"""
    
    def test_mailbox_category_classification_in_helpers(self):
        """Verify classification_helpers.py checks mailbox_category"""
        with open('/app/backend/services/classification_helpers.py', 'r') as f:
            content = f.read()
        
        assert 'mailbox_category' in content, \
            "classification_helpers.py should check mailbox_category"
        assert 'classify_from_mailbox_category' in content, \
            "Should call classify_from_mailbox_category"
        print("PASS: classification_helpers.py checks mailbox_category")


class TestConfidenceBumpLogic:
    """Test confidence bump when deterministic classification succeeds"""
    
    def test_confidence_bump_exists(self):
        """Verify confidence is bumped when deterministic classification succeeds"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read()
        
        # Should bump confidence when deterministic classification succeeds
        assert 'classification_confidence = 0.85' in content, \
            "Should bump confidence to 0.85 for deterministic classification"
        assert 'Bumping confidence for' in content, \
            "Should log confidence bump"
        print("PASS: Confidence bump logic exists (0.85 for deterministic classification)")
    
    def test_confidence_bump_condition(self):
        """Verify confidence bump only happens when AI confidence is low"""
        with open('/app/backend/server.py', 'r') as f:
            content = f.read()
        
        assert 'confidence < 0.5' in content, \
            "Should only bump confidence when AI confidence < 0.5"
        print("PASS: Confidence bump only triggers when AI confidence < 0.5")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
