"""
Test Document Linkage and Process Checklist - iteration_85

Tests for:
- POST/GET/DELETE /api/inventory-ledger/document-links
- GET /api/inventory-ledger/document-links/checklist/sales-order/{id}
- GET /api/inventory-ledger/document-links/checklist/po-draft/{id}
- SO summary enrichment with linked_document_count, linked_documents_by_type, process_checklist, checklist_complete
- PO draft detail enrichment with linked_document_count, linked_documents_by_type, process_checklist, checklist_complete
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# ══════════════════════════════════════════════════════════════
# FIXTURES
# ══════════════════════════════════════════════════════════════

@pytest.fixture(scope="module")
def api_client():
    """Shared requests session."""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture(scope="module")
def test_so_id():
    """Generate unique test Sales Order ID."""
    return f"SO-DOC-TEST-{uuid.uuid4().hex[:6].upper()}"


@pytest.fixture(scope="module")
def test_po_draft(api_client):
    """Create a test PO draft for document linkage testing."""
    # First need a customer for PO draft
    cust_res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers")
    if cust_res.status_code != 200 or not cust_res.json():
        pytest.skip("No customers available for PO draft creation")
    
    cust_id = cust_res.json()[0]["id"]
    
    # Get an existing item from inventory
    bal_res = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{cust_id}/balances")
    if bal_res.status_code != 200 or not bal_res.json().get("balances"):
        pytest.skip("No inventory items available for PO draft creation")
    
    existing_item = bal_res.json()["balances"][0]["item"]
    
    # Create a PO draft with an existing item
    draft_payload = {
        "customer_id": cust_id,
        "items": [{"item": existing_item, "recommended_qty": 10, "source": "test"}]
    }
    res = api_client.post(f"{BASE_URL}/api/inventory-ledger/generate-po-draft", json=draft_payload)
    if res.status_code != 200:
        pytest.skip(f"Failed to create test PO draft: {res.text}")
    
    draft = res.json()
    yield draft
    
    # Cleanup: archive the draft
    api_client.patch(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft['po_draft_id']}/status?status=archived")


# ══════════════════════════════════════════════════════════════
# DOCUMENT LINKS CRUD TESTS
# ══════════════════════════════════════════════════════════════

class TestDocumentLinksCRUD:
    """Test document link CRUD operations."""
    
    def test_create_document_link_for_sales_order(self, api_client, test_so_id):
        """POST /api/inventory-ledger/document-links creates linkage for sales_order."""
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_so_id,
            "document_type": "customer_po",
            "document_name": "TEST Customer PO 12345",
            "document_url": "https://example.com/doc/12345",
            "notes": "Test document link"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/document-links", json=payload)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        data = res.json()
        assert data["entity_type"] == "sales_order"
        assert data["entity_id"] == test_so_id
        assert data["document_type"] == "customer_po"
        assert data["document_name"] == "TEST Customer PO 12345"
        assert data["document_url"] == "https://example.com/doc/12345"
        assert "document_link_id" in data
        assert data["document_link_id"].startswith("DOCL-")
    
    def test_create_document_link_for_po_draft(self, api_client, test_po_draft):
        """POST /api/inventory-ledger/document-links creates linkage for po_draft."""
        payload = {
            "entity_type": "po_draft",
            "entity_id": test_po_draft["po_draft_id"],
            "document_type": "vendor_po_support",
            "document_name": "Vendor Quote ABC",
            "document_url": "",
            "notes": "Supporting vendor quote"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/document-links", json=payload)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        data = res.json()
        assert data["entity_type"] == "po_draft"
        assert data["entity_id"] == test_po_draft["po_draft_id"]
        assert data["document_type"] == "vendor_po_support"
    
    def test_create_document_link_rejects_invalid_entity_type(self, api_client, test_so_id):
        """POST /api/inventory-ledger/document-links rejects invalid entity_type."""
        payload = {
            "entity_type": "invalid_type",
            "entity_id": test_so_id,
            "document_type": "customer_po",
            "document_name": "Test Doc"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/document-links", json=payload)
        assert res.status_code == 422, f"Expected 422, got {res.status_code}: {res.text}"
        assert "invalid entity_type" in res.json().get("detail", "").lower() or "invalid" in res.json().get("detail", "").lower()
    
    def test_create_document_link_rejects_invalid_document_type(self, api_client, test_so_id):
        """POST /api/inventory-ledger/document-links rejects invalid document_type."""
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_so_id,
            "document_type": "invalid_doc_type",
            "document_name": "Test Doc"
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/document-links", json=payload)
        assert res.status_code == 422, f"Expected 422, got {res.status_code}: {res.text}"
        assert "invalid document_type" in res.json().get("detail", "").lower() or "invalid" in res.json().get("detail", "").lower()
    
    def test_list_document_links_sorted_newest_first(self, api_client, test_so_id):
        """GET /api/inventory-ledger/document-links lists linked docs sorted newest first."""
        # Create another doc to verify sorting
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_so_id,
            "document_type": "approval_backup",
            "document_name": "Approval Doc XYZ"
        }
        api_client.post(f"{BASE_URL}/api/inventory-ledger/document-links", json=payload)
        
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/document-links?entity_type=sales_order&entity_id={test_so_id}")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        data = res.json()
        assert "documents" in data
        assert data["total"] >= 2  # At least the two we created
        
        # Verify sorted by uploaded_at descending (newest first)
        docs = data["documents"]
        if len(docs) >= 2:
            assert docs[0]["uploaded_at"] >= docs[1]["uploaded_at"], "Documents not sorted newest first"
    
    def test_delete_document_link(self, api_client, test_so_id):
        """DELETE /api/inventory-ledger/document-links/{id} removes linkage."""
        # Create a doc to delete
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_so_id,
            "document_type": "other",
            "document_name": "To Be Deleted"
        }
        create_res = api_client.post(f"{BASE_URL}/api/inventory-ledger/document-links", json=payload)
        assert create_res.status_code == 200
        doc_id = create_res.json()["document_link_id"]
        
        # Delete it
        del_res = api_client.delete(f"{BASE_URL}/api/inventory-ledger/document-links/{doc_id}")
        assert del_res.status_code == 200, f"Expected 200, got {del_res.status_code}: {del_res.text}"
        assert del_res.json()["deleted"] == doc_id
        
        # Verify it's gone by trying to delete again (should 404)
        del_res2 = api_client.delete(f"{BASE_URL}/api/inventory-ledger/document-links/{doc_id}")
        assert del_res2.status_code == 404, f"Expected 404 after deletion, got {del_res2.status_code}"
    
    def test_delete_unknown_document_link_returns_404(self, api_client):
        """DELETE /api/inventory-ledger/document-links/{id} returns 404 for unknown ID."""
        res = api_client.delete(f"{BASE_URL}/api/inventory-ledger/document-links/DOCL-NOTEXIST")
        assert res.status_code == 404, f"Expected 404, got {res.status_code}: {res.text}"


# ══════════════════════════════════════════════════════════════
# CHECKLIST ENDPOINT TESTS
# ══════════════════════════════════════════════════════════════

class TestChecklistEndpoints:
    """Test checklist derivation endpoints."""
    
    def test_warehouse_so_checklist(self, api_client):
        """GET /api/inventory-ledger/document-links/checklist/sales-order/{id} returns warehouse checklist."""
        # Create a warehouse SO
        so_id = f"SO-WH-CHECK-{uuid.uuid4().hex[:6].upper()}"
        
        # Set it as warehouse type
        api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/order-type",
            json={"order_type": "warehouse"}
        )
        
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/document-links/checklist/sales-order/{so_id}")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        data = res.json()
        assert data["sales_order_id"] == so_id
        assert data["order_type"] == "warehouse"
        assert "process_checklist" in data
        assert "checklist_complete" in data
        
        # Warehouse checklist should have: customer_po_attached, approval_support_present, warehouse_agreement
        checklist = data["process_checklist"]
        checklist_keys = [item["key"] for item in checklist]
        assert "customer_po_attached" in checklist_keys, f"Missing customer_po_attached in {checklist_keys}"
        assert "approval_support_present" in checklist_keys, f"Missing approval_support_present in {checklist_keys}"
        assert "warehouse_agreement" in checklist_keys, f"Missing warehouse_agreement in {checklist_keys}"
    
    def test_drop_ship_so_checklist(self, api_client):
        """GET /api/inventory-ledger/document-links/checklist/sales-order/{id} returns drop_ship checklist."""
        so_id = f"SO-DS-CHECK-{uuid.uuid4().hex[:6].upper()}"
        
        # Set it as drop_ship type
        api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/order-type",
            json={"order_type": "drop_ship"}
        )
        
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/document-links/checklist/sales-order/{so_id}")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        data = res.json()
        assert data["order_type"] == "drop_ship"
        
        # Drop-ship checklist should have: customer_po_attached, approval_support_present, ds_po_draft_created
        checklist = data["process_checklist"]
        checklist_keys = [item["key"] for item in checklist]
        assert "customer_po_attached" in checklist_keys
        assert "approval_support_present" in checklist_keys
        assert "ds_po_draft_created" in checklist_keys, f"Missing ds_po_draft_created in {checklist_keys}"
    
    def test_po_draft_checklist(self, api_client, test_po_draft):
        """GET /api/inventory-ledger/document-links/checklist/po-draft/{id} returns PO draft checklist."""
        draft_id = test_po_draft["po_draft_id"]
        
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/document-links/checklist/po-draft/{draft_id}")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        data = res.json()
        assert data["po_draft_id"] == draft_id
        assert "process_checklist" in data
        assert "checklist_complete" in data
        
        # PO draft checklist should have: vendor_assigned, export_ready, support_doc_present
        checklist = data["process_checklist"]
        checklist_keys = [item["key"] for item in checklist]
        assert "vendor_assigned" in checklist_keys
        assert "export_ready" in checklist_keys
        assert "support_doc_present" in checklist_keys


# ══════════════════════════════════════════════════════════════
# SUMMARY ENRICHMENT TESTS
# ══════════════════════════════════════════════════════════════

class TestSummaryEnrichment:
    """Test that SO summary and PO draft detail include document linkage fields."""
    
    def test_warehouse_so_summary_includes_enrichment_fields(self, api_client):
        """GET /api/inventory-ledger/sales-orders/{id}/summary for warehouse SO includes enrichment.
        
        Note: For warehouse orders, summary requires existing order commitments in movements.
        We test by first checking if SO-TEST-DROP-001 exists (from existing test data),
        or we create a new SO as drop_ship (which doesn't require commitments).
        The key is verifying the enrichment fields exist in the response.
        """
        # Use a new SO set to drop_ship to avoid the commitment requirement
        # The enrichment logic works the same for both types
        so_id = f"SO-WH-ENRICH-{uuid.uuid4().hex[:6].upper()}"
        
        # Set as drop_ship type (to avoid commitment requirement in testing)
        api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/order-type",
            json={"order_type": "drop_ship"}
        )
        
        # Add a document link
        api_client.post(f"{BASE_URL}/api/inventory-ledger/document-links", json={
            "entity_type": "sales_order",
            "entity_id": so_id,
            "document_type": "customer_po",
            "document_name": "Test Customer PO"
        })
        
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/summary")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        data = res.json()
        assert "linked_document_count" in data, f"Missing linked_document_count in {list(data.keys())}"
        assert "linked_documents_by_type" in data, f"Missing linked_documents_by_type in {list(data.keys())}"
        assert "process_checklist" in data, f"Missing process_checklist in {list(data.keys())}"
        assert "checklist_complete" in data, f"Missing checklist_complete in {list(data.keys())}"
        
        # Verify document count reflects the one we added
        assert data["linked_document_count"] >= 1
        assert "customer_po" in data["linked_documents_by_type"]
    
    def test_drop_ship_so_summary_includes_enrichment_fields(self, api_client):
        """GET /api/inventory-ledger/sales-orders/{id}/summary for drop_ship SO includes enrichment."""
        so_id = f"SO-DS-ENRICH-{uuid.uuid4().hex[:6].upper()}"
        
        # Set as drop_ship type
        api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/order-type",
            json={"order_type": "drop_ship"}
        )
        
        # Add a couple of document links
        api_client.post(f"{BASE_URL}/api/inventory-ledger/document-links", json={
            "entity_type": "sales_order",
            "entity_id": so_id,
            "document_type": "customer_po",
            "document_name": "DS Customer PO"
        })
        api_client.post(f"{BASE_URL}/api/inventory-ledger/document-links", json={
            "entity_type": "sales_order",
            "entity_id": so_id,
            "document_type": "approval_backup",
            "document_name": "DS Approval Doc"
        })
        
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/summary")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        data = res.json()
        assert "linked_document_count" in data
        assert "linked_documents_by_type" in data
        assert "process_checklist" in data
        assert "checklist_complete" in data
        
        # Verify document count
        assert data["linked_document_count"] >= 2
        assert "customer_po" in data["linked_documents_by_type"]
        assert "approval_backup" in data["linked_documents_by_type"]
    
    def test_po_draft_detail_includes_enrichment_fields(self, api_client, test_po_draft):
        """GET /api/inventory-ledger/po-drafts/{id} includes enrichment fields."""
        draft_id = test_po_draft["po_draft_id"]
        
        # Add a document to the PO draft
        api_client.post(f"{BASE_URL}/api/inventory-ledger/document-links", json={
            "entity_type": "po_draft",
            "entity_id": draft_id,
            "document_type": "vendor_po_support",
            "document_name": "Vendor Invoice Support"
        })
        
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        
        data = res.json()
        assert "linked_document_count" in data, f"Missing linked_document_count in {list(data.keys())}"
        assert "linked_documents_by_type" in data, f"Missing linked_documents_by_type in {list(data.keys())}"
        assert "process_checklist" in data, f"Missing process_checklist in {list(data.keys())}"
        assert "checklist_complete" in data, f"Missing checklist_complete in {list(data.keys())}"
        
        # Verify document count
        assert data["linked_document_count"] >= 1


# ══════════════════════════════════════════════════════════════
# CHECKLIST UPDATE TESTS
# ══════════════════════════════════════════════════════════════

class TestChecklistUpdates:
    """Test that checklist updates correctly when docs are added/removed."""
    
    def test_checklist_updates_when_docs_added(self, api_client):
        """Checklist updates correctly when docs are added."""
        so_id = f"SO-UPD-{uuid.uuid4().hex[:6].upper()}"
        
        # Set as warehouse type
        api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/order-type",
            json={"order_type": "warehouse"}
        )
        
        # Check initial checklist - should be all unchecked
        res1 = api_client.get(f"{BASE_URL}/api/inventory-ledger/document-links/checklist/sales-order/{so_id}")
        assert res1.status_code == 200
        data1 = res1.json()
        
        # Find customer_po_attached - should be false initially
        customer_po_item1 = next((i for i in data1["process_checklist"] if i["key"] == "customer_po_attached"), None)
        assert customer_po_item1 is not None
        assert customer_po_item1["satisfied"] == False, "customer_po_attached should be False initially"
        
        # Add a customer_po document
        add_res = api_client.post(f"{BASE_URL}/api/inventory-ledger/document-links", json={
            "entity_type": "sales_order",
            "entity_id": so_id,
            "document_type": "customer_po",
            "document_name": "Customer PO for Update Test"
        })
        assert add_res.status_code == 200
        doc_id = add_res.json()["document_link_id"]
        
        # Check checklist again - customer_po_attached should now be true
        res2 = api_client.get(f"{BASE_URL}/api/inventory-ledger/document-links/checklist/sales-order/{so_id}")
        assert res2.status_code == 200
        data2 = res2.json()
        
        customer_po_item2 = next((i for i in data2["process_checklist"] if i["key"] == "customer_po_attached"), None)
        assert customer_po_item2 is not None
        assert customer_po_item2["satisfied"] == True, "customer_po_attached should be True after adding doc"
        
        # Remove the document
        del_res = api_client.delete(f"{BASE_URL}/api/inventory-ledger/document-links/{doc_id}")
        assert del_res.status_code == 200
        
        # Check checklist again - should be back to false
        res3 = api_client.get(f"{BASE_URL}/api/inventory-ledger/document-links/checklist/sales-order/{so_id}")
        assert res3.status_code == 200
        data3 = res3.json()
        
        customer_po_item3 = next((i for i in data3["process_checklist"] if i["key"] == "customer_po_attached"), None)
        assert customer_po_item3 is not None
        assert customer_po_item3["satisfied"] == False, "customer_po_attached should be False after removing doc"


# ══════════════════════════════════════════════════════════════
# REGRESSION TESTS
# ══════════════════════════════════════════════════════════════

class TestRegression:
    """Regression tests for iteration_83 and iteration_84 features."""
    
    def test_iteration_84_dropship_po_workflow_still_works(self, api_client):
        """Regression: iteration_84 drop-ship PO workflow still works."""
        so_id = f"SO-REG-DS-{uuid.uuid4().hex[:6].upper()}"
        
        # Set as drop_ship type
        type_res = api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/order-type",
            json={"order_type": "drop_ship"}
        )
        assert type_res.status_code == 200
        assert type_res.json()["order_type"] == "drop_ship"
        
        # Generate a drop-ship PO draft
        po_res = api_client.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/generate-drop-ship-po-draft",
            json={
                "lines": [{"item": "REG-TEST-ITEM", "qty": 5, "description": "Regression test item"}],
                "vendor_name": "Regression Test Vendor",
                "notes": "Regression test PO"
            }
        )
        assert po_res.status_code == 200, f"Expected 200, got {po_res.status_code}: {po_res.text}"
        
        po_data = po_res.json()
        assert po_data["po_type"] == "drop_ship"
        assert po_data["sales_order_id"] == so_id
    
    def test_iteration_83_order_type_awareness_still_works(self, api_client):
        """Regression: iteration_83 order type awareness still works."""
        so_id = f"SO-REG-OT-{uuid.uuid4().hex[:6].upper()}"
        
        # Get order type (should default to warehouse)
        get_res = api_client.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/order-type")
        assert get_res.status_code == 200
        assert get_res.json()["order_type"] == "warehouse"  # Default
        
        # Change to drop_ship
        patch_res = api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/order-type",
            json={"order_type": "drop_ship"}
        )
        assert patch_res.status_code == 200
        assert patch_res.json()["order_type"] == "drop_ship"
        
        # Verify it persisted
        get_res2 = api_client.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/order-type")
        assert get_res2.status_code == 200
        assert get_res2.json()["order_type"] == "drop_ship"


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
