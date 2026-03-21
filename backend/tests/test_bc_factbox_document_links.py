"""
BC Factbox Document Links API Tests (Zetadocs Replacement)

Tests the 5 new endpoints in gpi_integration.py:
1. GET /api/gpi-integration/document-links/{bc_entity}/{bc_document_no}
2. POST /api/gpi-integration/document-links/{bc_entity}/{bc_document_no}/upload
3. DELETE /api/gpi-integration/document-links/{bc_entity}/{bc_document_no}/{doc_id}
4. POST /api/gpi-integration/document-links/migrate-from-zetadocs
5. bc_entity_to_doc_type mapping validation

DEMO_MODE must be true for upload tests to work (mocked SharePoint).
"""

import pytest
import requests
import os
import io
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Test document numbers - use unique prefixes to avoid collisions
TEST_PI_DOC_NO = f"TEST-PI-{uuid.uuid4().hex[:8]}"
TEST_PO_DOC_NO = f"TEST-PO-{uuid.uuid4().hex[:8]}"
TEST_SO_DOC_NO = f"TEST-SO-{uuid.uuid4().hex[:8]}"


class TestDocumentLinksGetEndpoint:
    """Test GET /api/gpi-integration/document-links/{bc_entity}/{bc_document_no}"""

    def test_get_document_links_unknown_doc_returns_empty(self):
        """GET document-links for unknown doc returns empty list"""
        response = requests.get(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/UNKNOWN-DOC-12345"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert "documents" in data
        assert "total" in data
        assert data["total"] == 0
        assert data["documents"] == []
        assert data["bc_entity"] == "purchaseInvoices"
        assert data["bc_document_no"] == "UNKNOWN-DOC-12345"
        print("PASS: GET document-links for unknown doc returns empty list")

    def test_get_document_links_purchase_invoices(self):
        """GET document-links for purchaseInvoices entity works"""
        response = requests.get(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{TEST_PI_DOC_NO}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["bc_entity"] == "purchaseInvoices"
        assert data["bc_document_no"] == TEST_PI_DOC_NO
        print("PASS: GET document-links for purchaseInvoices works")

    def test_get_document_links_sales_orders(self):
        """GET document-links for salesOrders entity works"""
        response = requests.get(
            f"{BASE_URL}/api/gpi-integration/document-links/salesOrders/{TEST_SO_DOC_NO}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["bc_entity"] == "salesOrders"
        assert data["bc_document_no"] == TEST_SO_DOC_NO
        print("PASS: GET document-links for salesOrders works")

    def test_get_document_links_purchase_orders(self):
        """GET document-links for purchaseOrders entity works"""
        response = requests.get(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseOrders/{TEST_PO_DOC_NO}"
        )
        assert response.status_code == 200
        data = response.json()
        assert data["bc_entity"] == "purchaseOrders"
        assert data["bc_document_no"] == TEST_PO_DOC_NO
        print("PASS: GET document-links for purchaseOrders works")


class TestDocumentLinksUploadEndpoint:
    """Test POST /api/gpi-integration/document-links/{bc_entity}/{bc_document_no}/upload"""

    def test_upload_small_file_succeeds(self):
        """POST upload with small file succeeds (DEMO_MODE mocked)"""
        # Create a small test file
        file_content = b"Test PDF content for BC factbox upload test"
        files = {"file": ("test_invoice.pdf", io.BytesIO(file_content), "application/pdf")}
        data = {"uploaded_by": "Test User", "vendor_context": "Test Vendor"}

        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{TEST_PI_DOC_NO}/upload",
            files=files,
            data=data
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        result = response.json()
        
        # Verify response structure
        assert result.get("success") is True, f"Expected success=true, got {result}"
        assert "file_name" in result
        assert result["file_name"] == "test_invoice.pdf"
        assert "sharepoint_url" in result
        assert "folder_path" in result
        assert "folder_source" in result
        assert result["folder_source"] in ["routing_rules", "matched"]
        assert "doc_id" in result
        
        print(f"PASS: Upload succeeded - doc_id={result['doc_id']}, folder_source={result['folder_source']}")
        return result["doc_id"]

    def test_upload_response_contains_required_fields(self):
        """Upload response contains success, file_name, sharepoint_url, folder_path, folder_source"""
        file_content = b"Another test file content"
        files = {"file": ("receipt.pdf", io.BytesIO(file_content), "application/pdf")}

        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{TEST_PI_DOC_NO}/upload",
            files=files
        )
        assert response.status_code == 200
        result = response.json()
        
        required_fields = ["success", "file_name", "sharepoint_url", "folder_path", "folder_source"]
        for field in required_fields:
            assert field in result, f"Missing required field: {field}"
        
        print(f"PASS: Upload response contains all required fields: {required_fields}")

    def test_second_upload_returns_folder_source_matched(self):
        """Second upload to same bc_document_no returns folder_source=matched"""
        # First upload
        file_content1 = b"First file content"
        files1 = {"file": ("first.pdf", io.BytesIO(file_content1), "application/pdf")}
        
        unique_doc_no = f"TEST-MATCH-{uuid.uuid4().hex[:8]}"
        
        response1 = requests.post(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}/upload",
            files=files1
        )
        assert response1.status_code == 200
        result1 = response1.json()
        first_folder_source = result1.get("folder_source")
        print(f"First upload folder_source: {first_folder_source}")

        # Second upload to same document
        file_content2 = b"Second file content"
        files2 = {"file": ("second.pdf", io.BytesIO(file_content2), "application/pdf")}
        
        response2 = requests.post(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}/upload",
            files=files2
        )
        assert response2.status_code == 200
        result2 = response2.json()
        
        # Second upload should find existing folder and return "matched"
        assert result2.get("folder_source") == "matched", \
            f"Expected folder_source=matched for second upload, got {result2.get('folder_source')}"
        
        print("PASS: Second upload returns folder_source=matched")

    def test_upload_large_file_returns_413(self):
        """Upload with 26MB+ file returns HTTP 413"""
        # Create a file larger than 25MB
        large_content = b"X" * (26 * 1024 * 1024)  # 26 MB
        files = {"file": ("large_file.pdf", io.BytesIO(large_content), "application/pdf")}

        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{TEST_PI_DOC_NO}/upload",
            files=files
        )
        assert response.status_code == 413, f"Expected 413, got {response.status_code}: {response.text}"
        print("PASS: Upload with 26MB+ file returns HTTP 413")

    def test_upload_creates_hub_document_with_correct_fields(self):
        """Hub documents record created has correct fields"""
        unique_doc_no = f"TEST-FIELDS-{uuid.uuid4().hex[:8]}"
        file_content = b"Test content for field validation"
        files = {"file": ("field_test.pdf", io.BytesIO(file_content), "application/pdf")}
        data = {"uploaded_by": "Field Test User", "vendor_context": "Field Test Vendor"}

        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}/upload",
            files=files,
            data=data
        )
        assert response.status_code == 200
        result = response.json()
        doc_id = result["doc_id"]

        # Verify by fetching the document links
        get_response = requests.get(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}"
        )
        assert get_response.status_code == 200
        get_data = get_response.json()
        
        assert get_data["total"] >= 1, "Expected at least 1 document"
        
        # Find our uploaded document
        uploaded_doc = None
        for doc in get_data["documents"]:
            if doc["doc_id"] == doc_id:
                uploaded_doc = doc
                break
        
        assert uploaded_doc is not None, f"Could not find uploaded doc {doc_id}"
        assert uploaded_doc["source"] == "bc_drop", f"Expected source=bc_drop, got {uploaded_doc['source']}"
        assert uploaded_doc["file_name"] == "field_test.pdf"
        
        print("PASS: Hub document created with correct fields (source=bc_drop)")


class TestDocumentLinksDeleteEndpoint:
    """Test DELETE /api/gpi-integration/document-links/{bc_entity}/{bc_document_no}/{doc_id}"""

    def test_delete_soft_deletes_record(self):
        """DELETE soft-deletes the record"""
        # First upload a document
        unique_doc_no = f"TEST-DEL-{uuid.uuid4().hex[:8]}"
        file_content = b"File to be deleted"
        files = {"file": ("to_delete.pdf", io.BytesIO(file_content), "application/pdf")}

        upload_response = requests.post(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}/upload",
            files=files
        )
        assert upload_response.status_code == 200
        doc_id = upload_response.json()["doc_id"]

        # Verify it exists
        get_response1 = requests.get(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}"
        )
        assert get_response1.status_code == 200
        initial_count = get_response1.json()["total"]
        assert initial_count >= 1

        # Delete the document
        delete_response = requests.delete(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}/{doc_id}"
        )
        assert delete_response.status_code == 200, f"Expected 200, got {delete_response.status_code}: {delete_response.text}"
        delete_data = delete_response.json()
        assert delete_data.get("success") is True
        assert "SharePoint file preserved" in delete_data.get("message", "")
        
        print("PASS: DELETE soft-deletes the record")

    def test_get_after_delete_shows_fewer_documents(self):
        """GET after delete shows fewer documents (soft-deleted docs filtered out)"""
        unique_doc_no = f"TEST-FILTER-{uuid.uuid4().hex[:8]}"
        
        # Upload two documents
        for i in range(2):
            file_content = f"File {i} content".encode()
            files = {"file": (f"file_{i}.pdf", io.BytesIO(file_content), "application/pdf")}
            response = requests.post(
                f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}/upload",
                files=files
            )
            assert response.status_code == 200

        # Get initial count
        get_response1 = requests.get(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}"
        )
        initial_count = get_response1.json()["total"]
        assert initial_count == 2, f"Expected 2 documents, got {initial_count}"

        # Delete one document
        doc_id = get_response1.json()["documents"][0]["doc_id"]
        delete_response = requests.delete(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}/{doc_id}"
        )
        assert delete_response.status_code == 200

        # Verify count decreased
        get_response2 = requests.get(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}"
        )
        final_count = get_response2.json()["total"]
        assert final_count == initial_count - 1, f"Expected {initial_count - 1} documents after delete, got {final_count}"
        
        print("PASS: GET after delete shows fewer documents")

    def test_delete_nonexistent_returns_404(self):
        """DELETE nonexistent document returns 404"""
        response = requests.delete(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/NONEXISTENT-DOC/nonexistent-id"
        )
        assert response.status_code == 404
        print("PASS: DELETE nonexistent document returns 404")


class TestMigrateFromZetadocsEndpoint:
    """Test POST /api/gpi-integration/document-links/migrate-from-zetadocs"""

    def test_migrate_returns_expected_fields(self):
        """POST migrate-from-zetadocs returns response with migrated/skipped/errors fields"""
        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/document-links/migrate-from-zetadocs"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # In DEMO_MODE, it should return 0 migrated with a message
        assert "migrated" in data
        assert "skipped" in data
        assert "errors" in data
        
        # DEMO_MODE returns 0 migrated
        assert data["migrated"] == 0
        assert data["skipped"] == 0
        assert isinstance(data["errors"], list)
        
        print(f"PASS: migrate-from-zetadocs returns expected fields: migrated={data['migrated']}, skipped={data['skipped']}")


class TestBcEntityToDocTypeMapping:
    """Test bc_entity_to_doc_type mapping"""

    def test_purchase_invoices_maps_to_ap_invoice(self):
        """purchaseInvoices maps to AP_Invoice"""
        # We verify this by checking the document_type in uploaded documents
        unique_doc_no = f"TEST-MAP-PI-{uuid.uuid4().hex[:8]}"
        file_content = b"Test content"
        files = {"file": ("test.pdf", io.BytesIO(file_content), "application/pdf")}

        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}/upload",
            files=files
        )
        assert response.status_code == 200

        get_response = requests.get(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseInvoices/{unique_doc_no}"
        )
        docs = get_response.json()["documents"]
        assert len(docs) >= 1
        assert docs[0]["document_type"] == "AP_Invoice", f"Expected AP_Invoice, got {docs[0]['document_type']}"
        print("PASS: purchaseInvoices maps to AP_Invoice")

    def test_purchase_orders_maps_to_purchase_order(self):
        """purchaseOrders maps to Purchase_Order"""
        unique_doc_no = f"TEST-MAP-PO-{uuid.uuid4().hex[:8]}"
        file_content = b"Test content"
        files = {"file": ("test.pdf", io.BytesIO(file_content), "application/pdf")}

        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseOrders/{unique_doc_no}/upload",
            files=files
        )
        assert response.status_code == 200

        get_response = requests.get(
            f"{BASE_URL}/api/gpi-integration/document-links/purchaseOrders/{unique_doc_no}"
        )
        docs = get_response.json()["documents"]
        assert len(docs) >= 1
        assert docs[0]["document_type"] == "Purchase_Order", f"Expected Purchase_Order, got {docs[0]['document_type']}"
        print("PASS: purchaseOrders maps to Purchase_Order")

    def test_sales_orders_maps_to_sales_order(self):
        """salesOrders maps to Sales_Order"""
        unique_doc_no = f"TEST-MAP-SO-{uuid.uuid4().hex[:8]}"
        file_content = b"Test content"
        files = {"file": ("test.pdf", io.BytesIO(file_content), "application/pdf")}

        response = requests.post(
            f"{BASE_URL}/api/gpi-integration/document-links/salesOrders/{unique_doc_no}/upload",
            files=files
        )
        assert response.status_code == 200

        get_response = requests.get(
            f"{BASE_URL}/api/gpi-integration/document-links/salesOrders/{unique_doc_no}"
        )
        docs = get_response.json()["documents"]
        assert len(docs) >= 1
        assert docs[0]["document_type"] == "Sales_Order", f"Expected Sales_Order, got {docs[0]['document_type']}"
        print("PASS: salesOrders maps to Sales_Order")


class TestDocSpecFileExists:
    """Test that the spec documentation exists"""

    def test_bc_extension_factbox_spec_exists(self):
        """docs/bc_extension_factbox_spec.md exists and contains endpoint documentation"""
        spec_path = "/app/docs/bc_extension_factbox_spec.md"
        assert os.path.exists(spec_path), f"Spec file not found at {spec_path}"
        
        with open(spec_path, 'r') as f:
            content = f.read()
        
        # Verify it contains key endpoint documentation
        assert "document-links" in content, "Spec should document document-links endpoints"
        assert "GET" in content, "Spec should document GET endpoint"
        assert "POST" in content, "Spec should document POST endpoint"
        assert "DELETE" in content, "Spec should document DELETE endpoint"
        assert "migrate-from-zetadocs" in content, "Spec should document migration endpoint"
        assert "purchaseInvoices" in content, "Spec should mention purchaseInvoices entity"
        assert "purchaseOrders" in content, "Spec should mention purchaseOrders entity"
        assert "salesOrders" in content, "Spec should mention salesOrders entity"
        
        print("PASS: bc_extension_factbox_spec.md exists and contains endpoint documentation")


@pytest.fixture(scope="session", autouse=True)
def setup_environment():
    """Verify environment is set up correctly"""
    assert BASE_URL, "REACT_APP_BACKEND_URL environment variable not set"
    print(f"Testing against: {BASE_URL}")
    
    # Verify backend is accessible
    try:
        response = requests.get(f"{BASE_URL}/api/health", timeout=5)
        print(f"Backend health check: {response.status_code}")
    except Exception as e:
        print(f"Warning: Could not reach backend health endpoint: {e}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
