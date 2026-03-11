"""
GPI Document Hub — Document Processor Plugin Architecture Tests

Tests for:
- Part 1-2: GET /api/processors/registry - 3 processors sorted by priority
- Part 3-4: POST /api/processors/test-detect with freight, customs, BOL texts
- Part 4: Generic text returns matched=false
- Part 5: suggested_references have label, value, source='processor'
- Part 6: suggested_vendor returns carrier/broker
- Part 7: GET /api/processors/document/{doc_id}/processor-result
- Part 9: Existing APIs still work (auth, documents, workflow, settings)
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test data provided by main agent
FREIGHT_INVOICE_TEXT = """FREIGHT INVOICE

Carrier: Tumalo Creek Transport
BOL: 89268460
Shipment No: 111428
Freight Charges: $1,250.00
Weight: 12,500 lbs
PO Number: PO-55432

Invoice #: INV-0303853"""

CUSTOMS_ENTRY_TEXT = """CBP FORM 7501 - ENTRY SUMMARY
U.S. Customs and Border Protection

Entry Number: E12345678
Broker File Number: SI-02-26-31449
Customer Reference: 0493335
Invoice Reference: INV-2026-1234"""

BOL_TEXT = """STRAIGHT BILL OF LADING

BOL Number: BOL-98765432
Shipper: Pacific Coast Paper Co
Consignee: RB Dwyer LLC
Carrier: XPO Logistics
Shipment Ref: SHIP-2026-001
PO Number: PO-44221"""

GENERIC_TEXT = """INVOICE
From: ABC Corp
Amount: $500"""


@pytest.fixture(scope="module")
def api_session():
    """Create a session for API calls."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def auth_token(api_session):
    """Get authentication token."""
    response = api_session.post(f"{BASE_URL}/api/auth/login", json={
        "username": "admin",
        "password": "admin"
    })
    assert response.status_code == 200, f"Auth failed: {response.text}"
    data = response.json()
    return data.get("token")


@pytest.fixture(scope="module")
def authenticated_session(api_session, auth_token):
    """Session with auth header."""
    api_session.headers.update({"Authorization": f"Bearer {auth_token}"})
    return api_session


class TestProcessorRegistry:
    """Part 1-2: GET /api/processors/registry tests"""
    
    def test_registry_returns_3_processors(self, api_session):
        """Registry should return exactly 3 processors."""
        response = api_session.get(f"{BASE_URL}/api/processors/registry")
        assert response.status_code == 200, f"Registry failed: {response.text}"
        
        data = response.json()
        assert "processors" in data
        assert "count" in data
        assert data["count"] == 3, f"Expected 3 processors, got {data['count']}"
    
    def test_registry_has_correct_processors(self, api_session):
        """Registry should have FreightInvoice, BillOfLading, CustomsEntry processors."""
        response = api_session.get(f"{BASE_URL}/api/processors/registry")
        data = response.json()
        
        processor_names = [p["name"] for p in data["processors"]]
        assert "FreightInvoiceProcessor" in processor_names
        assert "BillOfLadingProcessor" in processor_names
        assert "CustomsEntryProcessor" in processor_names
    
    def test_registry_sorted_by_priority(self, api_session):
        """Processors should be sorted by priority."""
        response = api_session.get(f"{BASE_URL}/api/processors/registry")
        data = response.json()
        
        priorities = [p["priority"] for p in data["processors"]]
        assert priorities == sorted(priorities), f"Processors not sorted by priority: {priorities}"
        
        # FreightInvoiceProcessor (100), BillOfLadingProcessor (105), CustomsEntryProcessor (110)
        print(f"Processor order: {[p['name'] for p in data['processors']]}")
        print(f"Priorities: {priorities}")


class TestFreightInvoiceDetection:
    """Part 3-4: Freight invoice detection tests"""
    
    def test_freight_invoice_detection(self, api_session):
        """Freight invoice text should match FreightInvoiceProcessor."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": FREIGHT_INVOICE_TEXT}
        )
        assert response.status_code == 200, f"Detection failed: {response.text}"
        
        data = response.json()
        assert data["matched"] == True
        assert data["processor_name"] == "FreightInvoiceProcessor"
    
    def test_freight_extracted_fields(self, api_session):
        """Freight invoice should extract BOL, shipment, carrier, invoice, freight_amount, PO."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": FREIGHT_INVOICE_TEXT}
        )
        data = response.json()
        
        extracted = data["result"]["extracted_fields"]
        
        # Check bol_number - should be 89268460
        assert "bol_number" in extracted, f"Missing bol_number. Got: {extracted.keys()}"
        assert extracted["bol_number"] == "89268460", f"Wrong BOL: {extracted.get('bol_number')}"
        
        # Check shipment_number - should be 111428
        assert "shipment_number" in extracted, f"Missing shipment_number. Got: {extracted.keys()}"
        assert extracted["shipment_number"] == "111428", f"Wrong shipment: {extracted.get('shipment_number')}"
        
        # Check carrier - should be Tumalo Creek Transport
        assert "carrier" in extracted, f"Missing carrier. Got: {extracted.keys()}"
        assert "Tumalo Creek Transport" in extracted["carrier"], f"Wrong carrier: {extracted.get('carrier')}"
        
        # Check invoice_number - should be INV-0303853
        assert "invoice_number" in extracted, f"Missing invoice_number. Got: {extracted.keys()}"
        assert extracted["invoice_number"] == "INV-0303853", f"Wrong invoice: {extracted.get('invoice_number')}"
        
        # Check freight_amount - should be 1,250.00 or 1250.00
        assert "freight_amount" in extracted, f"Missing freight_amount. Got: {extracted.keys()}"
        assert "1250" in extracted["freight_amount"], f"Wrong amount: {extracted.get('freight_amount')}"
        
        # Check po_number - should be PO-55432
        assert "po_number" in extracted, f"Missing po_number. Got: {extracted.keys()}"
        assert extracted["po_number"] == "PO-55432", f"Wrong PO: {extracted.get('po_number')}"
    
    def test_freight_suggested_vendor(self, api_session):
        """Freight invoice should suggest carrier as vendor."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": FREIGHT_INVOICE_TEXT}
        )
        data = response.json()
        
        suggested_vendor = data["result"]["suggested_vendor"]
        assert suggested_vendor is not None
        assert "Tumalo Creek Transport" in suggested_vendor


class TestCustomsEntryDetection:
    """Part 3-4: Customs entry detection tests"""
    
    def test_customs_entry_detection(self, api_session):
        """Customs entry text should match CustomsEntryProcessor."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": CUSTOMS_ENTRY_TEXT}
        )
        assert response.status_code == 200, f"Detection failed: {response.text}"
        
        data = response.json()
        assert data["matched"] == True
        assert data["processor_name"] == "CustomsEntryProcessor"
    
    def test_customs_extracted_fields(self, api_session):
        """Customs entry should extract entry_number, broker_file_number correctly."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": CUSTOMS_ENTRY_TEXT}
        )
        data = response.json()
        
        extracted = data["result"]["extracted_fields"]
        
        # Check entry_number - should be E12345678
        assert "entry_number" in extracted, f"Missing entry_number. Got: {extracted.keys()}"
        assert extracted["entry_number"] == "E12345678", f"Wrong entry_number: {extracted.get('entry_number')}"
        
        # Check broker_file_number - should be SI-02-26-31449
        assert "broker_file_number" in extracted, f"Missing broker_file_number. Got: {extracted.keys()}"
        assert extracted["broker_file_number"] == "SI-02-26-31449", f"Wrong broker_file_number: {extracted.get('broker_file_number')}"


class TestBillOfLadingDetection:
    """Part 3-4: Bill of Lading detection tests"""
    
    def test_bol_detection(self, api_session):
        """BOL text should match BillOfLadingProcessor."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": BOL_TEXT}
        )
        assert response.status_code == 200, f"Detection failed: {response.text}"
        
        data = response.json()
        assert data["matched"] == True
        assert data["processor_name"] == "BillOfLadingProcessor"
    
    def test_bol_extracted_fields(self, api_session):
        """BOL should extract bol_number, carrier, shipper."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": BOL_TEXT}
        )
        data = response.json()
        
        extracted = data["result"]["extracted_fields"]
        
        # Check bol_number - should be BOL-98765432
        assert "bol_number" in extracted, f"Missing bol_number. Got: {extracted.keys()}"
        assert extracted["bol_number"] == "BOL-98765432", f"Wrong BOL: {extracted.get('bol_number')}"
        
        # Check carrier - should be XPO Logistics
        assert "carrier" in extracted, f"Missing carrier. Got: {extracted.keys()}"
        assert "XPO Logistics" in extracted["carrier"], f"Wrong carrier: {extracted.get('carrier')}"
        
        # Check shipper - should be Pacific Coast Paper Co
        assert "shipper" in extracted, f"Missing shipper. Got: {extracted.keys()}"
        assert "Pacific Coast Paper" in extracted["shipper"], f"Wrong shipper: {extracted.get('shipper')}"


class TestGenericTextNoMatch:
    """Part 4: Generic text should not match any processor"""
    
    def test_generic_text_no_match(self, api_session):
        """Generic invoice text should return matched=false."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": GENERIC_TEXT}
        )
        assert response.status_code == 200, f"Detection failed: {response.text}"
        
        data = response.json()
        assert data["matched"] == False, f"Expected no match, but matched: {data.get('processor_name')}"
        assert data["processor_name"] is None


class TestSuggestedReferences:
    """Part 5: suggested_references have label, value, source='processor'"""
    
    def test_freight_suggested_references_format(self, api_session):
        """Freight references should have label, value, source='processor'."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": FREIGHT_INVOICE_TEXT}
        )
        data = response.json()
        
        refs = data["result"]["suggested_references"]
        assert len(refs) > 0, "No references returned"
        
        for ref in refs:
            assert "label" in ref, f"Missing label in reference: {ref}"
            assert "value" in ref, f"Missing value in reference: {ref}"
            assert "source" in ref, f"Missing source in reference: {ref}"
            assert ref["source"] == "processor", f"Wrong source: {ref['source']}"
    
    def test_customs_suggested_references_format(self, api_session):
        """Customs references should have label, value, source='processor'."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": CUSTOMS_ENTRY_TEXT}
        )
        data = response.json()
        
        refs = data["result"]["suggested_references"]
        assert len(refs) > 0, "No references returned"
        
        for ref in refs:
            assert "label" in ref, f"Missing label in reference: {ref}"
            assert "value" in ref, f"Missing value in reference: {ref}"
            assert "source" in ref, f"Missing source in reference: {ref}"
            assert ref["source"] == "processor", f"Wrong source: {ref['source']}"
    
    def test_bol_suggested_references_format(self, api_session):
        """BOL references should have label, value, source='processor'."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": BOL_TEXT}
        )
        data = response.json()
        
        refs = data["result"]["suggested_references"]
        assert len(refs) > 0, "No references returned"
        
        for ref in refs:
            assert "label" in ref, f"Missing label in reference: {ref}"
            assert "value" in ref, f"Missing value in reference: {ref}"
            assert "source" in ref, f"Missing source in reference: {ref}"
            assert ref["source"] == "processor", f"Wrong source: {ref['source']}"


class TestSuggestedVendor:
    """Part 6: suggested_vendor returns carrier/broker name"""
    
    def test_freight_vendor_is_carrier(self, api_session):
        """Freight invoice vendor should be carrier name."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": FREIGHT_INVOICE_TEXT}
        )
        data = response.json()
        
        vendor = data["result"]["suggested_vendor"]
        assert vendor is not None
        assert "Tumalo Creek Transport" in vendor
    
    def test_bol_vendor_is_carrier(self, api_session):
        """BOL vendor should be carrier name."""
        response = api_session.post(
            f"{BASE_URL}/api/processors/test-detect",
            json={"document_text": BOL_TEXT}
        )
        data = response.json()
        
        vendor = data["result"]["suggested_vendor"]
        assert vendor is not None
        # BOL suggest_vendor returns carrier or shipper
        assert "XPO Logistics" in vendor or "Pacific Coast Paper" in vendor


class TestDocumentProcessorResult:
    """Part 7: GET /api/processors/document/{doc_id}/processor-result"""
    
    def test_get_processor_result_with_real_doc(self, authenticated_session):
        """Get processor result for a real document."""
        # First, get a real document ID
        response = authenticated_session.get(f"{BASE_URL}/api/documents?limit=1")
        assert response.status_code == 200, f"Documents fetch failed: {response.text}"
        
        data = response.json()
        if not data.get("documents") or len(data["documents"]) == 0:
            pytest.skip("No documents available for testing")
        
        doc_id = data["documents"][0]["id"]
        
        # Get processor result
        response = authenticated_session.get(f"{BASE_URL}/api/processors/document/{doc_id}/processor-result")
        assert response.status_code == 200, f"Processor result failed: {response.text}"
        
        result = response.json()
        assert "document_id" in result
        assert "has_processor_result" in result
        assert result["document_id"] == doc_id
    
    def test_get_processor_result_invalid_doc(self, authenticated_session):
        """Get processor result for non-existent document should return error."""
        response = authenticated_session.get(f"{BASE_URL}/api/processors/document/nonexistent_doc_id/processor-result")
        assert response.status_code == 200  # Returns 200 with error message
        
        result = response.json()
        assert "error" in result or result.get("has_processor_result") == False


class TestExistingAPIs:
    """Part 9: Existing APIs still work"""
    
    def test_auth_login(self, api_session):
        """Auth login should still work."""
        response = api_session.post(f"{BASE_URL}/api/auth/login", json={
            "username": "admin",
            "password": "admin"
        })
        assert response.status_code == 200
        assert "token" in response.json()
    
    def test_documents_list(self, authenticated_session):
        """Documents list should still work."""
        response = authenticated_session.get(f"{BASE_URL}/api/documents?limit=5")
        assert response.status_code == 200
        assert "documents" in response.json()
    
    def test_workflow_status_counts(self, authenticated_session):
        """Workflow status-counts should still work."""
        response = authenticated_session.get(f"{BASE_URL}/api/workflows/ap_invoice/status-counts")
        assert response.status_code == 200
    
    def test_settings_status(self, authenticated_session):
        """Settings status should still work."""
        response = authenticated_session.get(f"{BASE_URL}/api/settings/status")
        assert response.status_code == 200


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
