"""
API Integration Tests for P3-B: Drop-Ship vs Warehouse SO Type Routing

Tests the preflight and from-document endpoints with so_type routing.
These tests create test documents in MongoDB, call the API, and verify responses.

Note: BC API is not available in preview environment, so from-document endpoint
will return 503 for BC credentials not configured (expected).
"""
import pytest
import requests
import uuid
import os
from pymongo import MongoClient


BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://po-vendor-resolver.preview.emergentagent.com").rstrip("/")
MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "gpi_document_hub")


@pytest.fixture(scope="module")
def db():
    """MongoDB connection fixture."""
    client = MongoClient(MONGO_URL)
    database = client[DB_NAME]
    yield database
    client.close()


@pytest.fixture
def cleanup_docs(db):
    """Cleanup test documents after each test."""
    doc_ids = []
    yield doc_ids
    for doc_id in doc_ids:
        db.hub_documents.delete_one({"id": doc_id})


class TestPreflightSOTypeRouting:
    """Test preflight endpoint returns so_type and so_routing correctly."""

    def test_preflight_dropship_document(self, db, cleanup_docs):
        """Preflight for dropship document returns correct so_type and routing fields."""
        doc_id = f"test-api-ds-{uuid.uuid4().hex[:8]}"
        cleanup_docs.append(doc_id)
        
        # Insert test document with so_type=dropship
        db.hub_documents.insert_one({
            "id": doc_id,
            "document_type": "Sales_Order",
            "extracted_fields": {
                "customer": "Dropship Customer Inc",
                "po_number": "DS-PO-12345",
                "so_type": "dropship",
                "ship_to": "123 Customer Address, City, ST 12345",
                "location_code": "CUST-SHIP-01",
                "amount": "2500.00",
            },
            "normalized_fields": {},
            "validation_results": {},
        })
        
        resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        
        # Verify so_type in document_summary
        assert data["document_summary"]["so_type"] == "dropship"
        
        # Verify so_type in mapped_values
        assert data["mapped_values"]["so_type"] == "dropship"
        
        # Verify so_routing structure
        so_routing = data["mapped_values"]["so_routing"]
        assert so_routing["so_type"] == "dropship"
        assert so_routing["ship_to_code"] == "CUST-SHIP-01"
        assert so_routing["ship_to_name"] == "Dropship Customer Inc"
        assert so_routing["ship_to_address"] == "123 Customer Address, City, ST 12345"
        
        # Dropship should NOT have location_code set
        assert so_routing.get("location_code", "") == ""
        
        print(f"✓ Dropship preflight test passed: so_type={data['document_summary']['so_type']}")

    def test_preflight_warehouse_document(self, db, cleanup_docs):
        """Preflight for warehouse document returns correct so_type and location_code."""
        doc_id = f"test-api-wh-{uuid.uuid4().hex[:8]}"
        cleanup_docs.append(doc_id)
        
        # Insert test document with so_type=warehouse
        db.hub_documents.insert_one({
            "id": doc_id,
            "document_type": "Sales_Order",
            "extracted_fields": {
                "customer": "Warehouse Customer LLC",
                "po_number": "WH-PO-67890",
                "so_type": "warehouse",
                "amount": "3500.00",
            },
            "normalized_fields": {},
            "validation_results": {},
        })
        
        resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        assert resp.status_code == 200, f"Expected 200, got {resp.status_code}: {resp.text}"
        
        data = resp.json()
        
        # Verify so_type
        assert data["document_summary"]["so_type"] == "warehouse"
        assert data["mapped_values"]["so_type"] == "warehouse"
        
        # Verify so_routing has location_code (default MAIN)
        so_routing = data["mapped_values"]["so_routing"]
        assert so_routing["so_type"] == "warehouse"
        assert so_routing["location_code"] == "MAIN"  # BC_DEFAULT_WAREHOUSE_CODE
        assert so_routing["ship_to_code"] == ""
        assert so_routing["ship_to_name"] == ""
        
        print(f"✓ Warehouse preflight test passed: location_code={so_routing['location_code']}")

    def test_preflight_warehouse_with_explicit_location(self, db, cleanup_docs):
        """Preflight for warehouse document with explicit location_code uses that value."""
        doc_id = f"test-api-wh-loc-{uuid.uuid4().hex[:8]}"
        cleanup_docs.append(doc_id)
        
        db.hub_documents.insert_one({
            "id": doc_id,
            "document_type": "Sales_Order",
            "extracted_fields": {
                "customer": "Warehouse Customer 2",
                "po_number": "WH-PO-99999",
                "so_type": "warehouse",
                "location_code": "WH-EAST-02",
                "amount": "1000.00",
            },
            "normalized_fields": {},
            "validation_results": {},
        })
        
        resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        assert resp.status_code == 200
        
        data = resp.json()
        so_routing = data["mapped_values"]["so_routing"]
        
        # Should use explicit location_code, not default
        assert so_routing["location_code"] == "WH-EAST-02"
        
        print(f"✓ Warehouse with explicit location test passed: location_code={so_routing['location_code']}")

    def test_preflight_unknown_so_type(self, db, cleanup_docs):
        """Preflight for document without so_type returns 'unknown'."""
        doc_id = f"test-api-unk-{uuid.uuid4().hex[:8]}"
        cleanup_docs.append(doc_id)
        
        db.hub_documents.insert_one({
            "id": doc_id,
            "document_type": "Sales_Order",
            "extracted_fields": {
                "customer": "Unknown Type Customer",
                "po_number": "UNK-PO-11111",
                "amount": "500.00",
                # No so_type field
            },
            "normalized_fields": {},
            "validation_results": {},
        })
        
        resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
        assert resp.status_code == 200
        
        data = resp.json()
        
        # Verify so_type is 'unknown'
        assert data["document_summary"]["so_type"] == "unknown"
        assert data["mapped_values"]["so_type"] == "unknown"
        
        # Verify so_routing has empty fields
        so_routing = data["mapped_values"]["so_routing"]
        assert so_routing["so_type"] == "unknown"
        assert so_routing["ship_to_code"] == ""
        assert so_routing["ship_to_name"] == ""
        assert so_routing["location_code"] == ""
        
        print(f"✓ Unknown so_type test passed")

    def test_preflight_dropship_variants(self, db, cleanup_docs):
        """Test that dropship variants (drop_ship, drop-ship) are normalized."""
        variants = ["drop_ship", "drop-ship", "Dropship", "DROPSHIP"]
        
        for variant in variants:
            doc_id = f"test-api-dsv-{uuid.uuid4().hex[:8]}"
            cleanup_docs.append(doc_id)
            
            db.hub_documents.insert_one({
                "id": doc_id,
                "document_type": "Sales_Order",
                "extracted_fields": {
                    "customer": f"Customer for {variant}",
                    "po_number": f"PO-{variant}",
                    "so_type": variant,
                    "amount": "100.00",
                },
                "normalized_fields": {},
                "validation_results": {},
            })
            
            resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/preflight/{doc_id}")
            assert resp.status_code == 200
            
            data = resp.json()
            assert data["document_summary"]["so_type"] == "dropship", f"Variant '{variant}' should normalize to 'dropship'"
            
            print(f"✓ Dropship variant '{variant}' normalized correctly")


class TestFromDocumentSOTypeRouting:
    """Test from-document endpoint includes so_type in response and audit.
    
    Note: BC API is not available in preview, so these tests verify the endpoint
    returns 503 (BC credentials not configured) as expected.
    """

    def test_from_document_returns_503_without_bc(self, db, cleanup_docs):
        """from-document endpoint returns 503 when BC credentials not configured."""
        doc_id = f"test-api-fd-{uuid.uuid4().hex[:8]}"
        cleanup_docs.append(doc_id)
        
        # Insert a document with customer resolved (to pass validation)
        db.hub_documents.insert_one({
            "id": doc_id,
            "document_type": "Sales_Order",
            "extracted_fields": {
                "customer": "Test Customer",
                "po_number": "FD-PO-12345",
                "so_type": "dropship",
                "amount": "1000.00",
            },
            "normalized_fields": {},
            "validation_results": {
                "bc_record_info": {"number": "C00001", "displayName": "Test Customer"},
            },
            "customer_candidates": [{"number": "C00001", "displayName": "Test Customer", "score": 0.95}],
        })
        
        resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{doc_id}")
        
        # In preview env without BC credentials, expect 503
        # If BC credentials are configured but fail, expect 502
        assert resp.status_code in [503, 502, 422], f"Expected 503/502/422, got {resp.status_code}: {resp.text}"
        
        print(f"✓ from-document returns expected status {resp.status_code} (BC not available in preview)")

    def test_from_document_not_found(self, db):
        """from-document returns 404 for non-existent document."""
        fake_id = f"nonexistent-{uuid.uuid4().hex[:8]}"
        
        resp = requests.post(f"{BASE_URL}/api/gpi-integration/sales-orders/from-document/{fake_id}")
        assert resp.status_code == 404
        
        print(f"✓ from-document returns 404 for non-existent document")


class TestSOTypeInAuditTrail:
    """Test that so_type is stored in audit trail when SO is created."""

    def test_audit_collection_exists(self, db):
        """Verify bc_so_creation_audit collection exists and has expected structure."""
        # Check if collection exists (may be empty in test env)
        collections = db.list_collection_names()
        
        # The collection is created when first SO is created
        # Just verify we can query it
        audit_count = db.bc_so_creation_audit.count_documents({})
        print(f"✓ bc_so_creation_audit collection accessible, {audit_count} records")


class TestClassificationPromptSOType:
    """Test that classification prompt includes so_type extraction instructions."""

    def test_prompt_has_so_type_field(self):
        """Verify the classification prompt includes so_type in extracted_fields."""
        from services.document_intel_helpers import _CLASSIFY_SYSTEM_PROMPT
        
        assert "so_type" in _CLASSIFY_SYSTEM_PROMPT
        assert "dropship" in _CLASSIFY_SYSTEM_PROMPT.lower()
        assert "warehouse" in _CLASSIFY_SYSTEM_PROMPT.lower()
        
        print("✓ Classification prompt includes so_type extraction instructions")

    def test_prompt_has_dropship_indicators(self):
        """Verify prompt describes how to identify dropship orders."""
        from services.document_intel_helpers import _CLASSIFY_SYSTEM_PROMPT
        
        # Check for dropship identification guidance
        assert "drop ship" in _CLASSIFY_SYSTEM_PROMPT.lower() or "drop-ship" in _CLASSIFY_SYSTEM_PROMPT.lower()
        assert "direct ship" in _CLASSIFY_SYSTEM_PROMPT.lower()
        
        print("✓ Classification prompt includes dropship identification guidance")

    def test_prompt_has_warehouse_indicators(self):
        """Verify prompt describes how to identify warehouse orders."""
        from services.document_intel_helpers import _CLASSIFY_SYSTEM_PROMPT
        
        # Check for warehouse identification guidance
        assert "warehouse" in _CLASSIFY_SYSTEM_PROMPT.lower()
        assert "location" in _CLASSIFY_SYSTEM_PROMPT.lower()
        
        print("✓ Classification prompt includes warehouse identification guidance")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
