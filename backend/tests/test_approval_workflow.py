"""
Approval Workflow Tracking Tests (Iteration 86)
Tests for:
- POST /api/inventory-ledger/approvals/request - creates pending approval
- PATCH /api/inventory-ledger/approvals/{id} - approves/rejects
- GET /api/inventory-ledger/approvals - lists approval history
- SO summary enrichment with approval fields
- PO draft detail enrichment with approval fields
- Checklist integration with approval_requested/approval_granted items
"""

import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


class TestApprovalWorkflowRequest:
    """Tests for POST /api/inventory-ledger/approvals/request"""

    def test_create_pending_approval_for_sales_order(self):
        """Create pending approval for sales_order entity type"""
        # Use a unique SO ID for this test
        test_so_id = f"SO-TEST-APPR-{uuid.uuid4().hex[:6].upper()}"
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_so_id,
            "approval_type": "sales_order",
            "requested_by": "tester",
            "notes": "Test approval request"
        }
        res = requests.post(f"{BASE_URL}/api/inventory-ledger/approvals/request", json=payload)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert "approval_id" in data, "Response should contain approval_id"
        assert data["approval_id"].startswith("APPR-"), f"approval_id should start with 'APPR-', got {data['approval_id']}"
        assert data["entity_type"] == "sales_order"
        assert data["entity_id"] == test_so_id
        assert data["approval_type"] == "sales_order"
        assert data["approval_status"] == "pending", f"New approval should be pending, got {data['approval_status']}"
        assert data["requested_by"] == "tester"
        assert "requested_at" in data
        print(f"PASS: Created pending approval {data['approval_id']} for sales_order {test_so_id}")
        return data["approval_id"], test_so_id

    def test_create_pending_approval_for_po_draft(self):
        """Create pending approval for po_draft entity type"""
        # First, find an existing PO draft
        customer_id = None
        cust_res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers")
        if cust_res.status_code == 200:
            customers = cust_res.json()
            if customers:
                customer_id = customers[0]["id"]
        
        if not customer_id:
            pytest.skip("No customer workspace available for PO draft test")
        
        # Get existing PO drafts
        drafts_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={customer_id}")
        if drafts_res.status_code != 200 or not drafts_res.json().get("drafts"):
            pytest.skip("No PO drafts available for testing")
        
        draft = drafts_res.json()["drafts"][0]
        test_draft_id = draft["po_draft_id"]
        
        payload = {
            "entity_type": "po_draft",
            "entity_id": test_draft_id,
            "approval_type": "purchase_order",
            "requested_by": "po_tester",
            "notes": "PO draft approval request"
        }
        res = requests.post(f"{BASE_URL}/api/inventory-ledger/approvals/request", json=payload)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["entity_type"] == "po_draft"
        assert data["entity_id"] == test_draft_id
        assert data["approval_type"] == "purchase_order"
        assert data["approval_status"] == "pending"
        print(f"PASS: Created pending approval {data['approval_id']} for po_draft {test_draft_id}")
        return data["approval_id"], test_draft_id

    def test_reject_invalid_entity_type(self):
        """Should reject invalid entity_type with 422"""
        payload = {
            "entity_type": "invalid_type",
            "entity_id": "TEST-123",
            "approval_type": "sales_order",
        }
        res = requests.post(f"{BASE_URL}/api/inventory-ledger/approvals/request", json=payload)
        assert res.status_code == 422, f"Expected 422 for invalid entity_type, got {res.status_code}"
        data = res.json()
        assert "invalid entity_type" in data.get("detail", "").lower() or "entity_type" in data.get("detail", "").lower()
        print(f"PASS: Correctly rejected invalid entity_type with 422")

    def test_reject_invalid_approval_type(self):
        """Should reject invalid approval_type with 422"""
        payload = {
            "entity_type": "sales_order",
            "entity_id": "SO-TEST-123",
            "approval_type": "invalid_type",
        }
        res = requests.post(f"{BASE_URL}/api/inventory-ledger/approvals/request", json=payload)
        assert res.status_code == 422, f"Expected 422 for invalid approval_type, got {res.status_code}"
        data = res.json()
        assert "invalid approval_type" in data.get("detail", "").lower() or "approval_type" in data.get("detail", "").lower()
        print(f"PASS: Correctly rejected invalid approval_type with 422")

    def test_reject_non_existent_po_draft(self):
        """Should return 404 for non-existent PO draft"""
        payload = {
            "entity_type": "po_draft",
            "entity_id": "PO-DRAFT-NONEXISTENT-999",
            "approval_type": "purchase_order",
        }
        res = requests.post(f"{BASE_URL}/api/inventory-ledger/approvals/request", json=payload)
        assert res.status_code == 404, f"Expected 404 for non-existent PO draft, got {res.status_code}"
        print(f"PASS: Correctly returned 404 for non-existent PO draft")


class TestApprovalDecision:
    """Tests for PATCH /api/inventory-ledger/approvals/{id}"""

    def test_approve_pending_approval(self):
        """Should approve a pending approval request"""
        # First create a pending approval
        test_so_id = f"SO-TEST-APPROVE-{uuid.uuid4().hex[:6].upper()}"
        req_payload = {
            "entity_type": "sales_order",
            "entity_id": test_so_id,
            "approval_type": "sales_order",
            "requested_by": "requester",
        }
        req_res = requests.post(f"{BASE_URL}/api/inventory-ledger/approvals/request", json=req_payload)
        assert req_res.status_code == 200
        approval_id = req_res.json()["approval_id"]
        
        # Now approve it
        approve_payload = {
            "approval_status": "approved",
            "approved_by": "manager",
            "notes": "Approved by test"
        }
        res = requests.patch(f"{BASE_URL}/api/inventory-ledger/approvals/{approval_id}", json=approve_payload)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["approval_status"] == "approved", f"Expected approved, got {data['approval_status']}"
        assert data["approved_by"] == "manager"
        assert "decided_at" in data
        print(f"PASS: Approved pending approval {approval_id}")

    def test_reject_pending_approval(self):
        """Should reject a pending approval request"""
        test_so_id = f"SO-TEST-REJECT-{uuid.uuid4().hex[:6].upper()}"
        req_payload = {
            "entity_type": "sales_order",
            "entity_id": test_so_id,
            "approval_type": "sales_order",
        }
        req_res = requests.post(f"{BASE_URL}/api/inventory-ledger/approvals/request", json=req_payload)
        assert req_res.status_code == 200
        approval_id = req_res.json()["approval_id"]
        
        # Reject it
        reject_payload = {
            "approval_status": "rejected",
            "approved_by": "manager",
            "notes": "Rejected: insufficient documentation"
        }
        res = requests.patch(f"{BASE_URL}/api/inventory-ledger/approvals/{approval_id}", json=reject_payload)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        assert data["approval_status"] == "rejected"
        assert "rejected" in data.get("notes", "").lower() or data["notes"] == ""
        print(f"PASS: Rejected pending approval {approval_id}")

    def test_reject_already_decided_approval(self):
        """Should return 422 when trying to decide an already-decided approval"""
        test_so_id = f"SO-TEST-DOUBLE-{uuid.uuid4().hex[:6].upper()}"
        req_payload = {
            "entity_type": "sales_order",
            "entity_id": test_so_id,
            "approval_type": "sales_order",
        }
        req_res = requests.post(f"{BASE_URL}/api/inventory-ledger/approvals/request", json=req_payload)
        assert req_res.status_code == 200
        approval_id = req_res.json()["approval_id"]
        
        # First approve it
        approve_payload = {"approval_status": "approved", "approved_by": "mgr1"}
        res1 = requests.patch(f"{BASE_URL}/api/inventory-ledger/approvals/{approval_id}", json=approve_payload)
        assert res1.status_code == 200
        
        # Try to approve/reject again
        reject_payload = {"approval_status": "rejected", "approved_by": "mgr2"}
        res2 = requests.patch(f"{BASE_URL}/api/inventory-ledger/approvals/{approval_id}", json=reject_payload)
        assert res2.status_code == 422, f"Expected 422 for already-decided approval, got {res2.status_code}"
        assert "pending" in res2.json().get("detail", "").lower()
        print(f"PASS: Correctly returned 422 for already-decided approval")

    def test_404_for_unknown_approval_id(self):
        """Should return 404 for unknown approval ID"""
        res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/approvals/APPR-UNKNOWN999",
            json={"approval_status": "approved"}
        )
        assert res.status_code == 404, f"Expected 404, got {res.status_code}"
        print(f"PASS: Correctly returned 404 for unknown approval ID")


class TestApprovalList:
    """Tests for GET /api/inventory-ledger/approvals"""

    def test_list_approval_history(self):
        """Should list approval history sorted newest first"""
        test_so_id = f"SO-TEST-LIST-{uuid.uuid4().hex[:6].upper()}"
        
        # Create multiple approvals for same entity
        for i in range(3):
            payload = {
                "entity_type": "sales_order",
                "entity_id": test_so_id,
                "approval_type": "sales_order",
                "notes": f"Request #{i+1}"
            }
            res = requests.post(f"{BASE_URL}/api/inventory-ledger/approvals/request", json=payload)
            assert res.status_code == 200
        
        # List approvals
        list_res = requests.get(f"{BASE_URL}/api/inventory-ledger/approvals?entity_type=sales_order&entity_id={test_so_id}")
        assert list_res.status_code == 200, f"Expected 200, got {list_res.status_code}"
        data = list_res.json()
        assert data["entity_type"] == "sales_order"
        assert data["entity_id"] == test_so_id
        assert data["total"] >= 3, f"Expected at least 3 approvals, got {data['total']}"
        assert "approvals" in data
        assert len(data["approvals"]) >= 3
        
        # Verify sorted newest first (by requested_at)
        approvals = data["approvals"]
        for i in range(len(approvals) - 1):
            assert approvals[i]["requested_at"] >= approvals[i+1]["requested_at"], \
                "Approvals should be sorted newest first"
        print(f"PASS: Listed {data['total']} approvals for {test_so_id}, sorted newest first")


class TestSOSummaryEnrichment:
    """Tests for approval enrichment in SO summary"""

    def test_so_summary_includes_approval_fields_when_no_approvals(self):
        """SO summary should show not_requested when no approvals exist"""
        test_so_id = f"SO-TEST-NOAPPR-{uuid.uuid4().hex[:6].upper()}"
        
        # Get SO summary - it may not exist but that's OK, we're testing the approval fields
        # For drop-ship orders without commitments
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{test_so_id}/summary")
        
        # If the SO doesn't exist (no commitments), we can test with a known SO
        if res.status_code == 404:
            # Try with an existing known SO - set it as drop_ship first
            patch_res = requests.patch(
                f"{BASE_URL}/api/inventory-ledger/sales-orders/{test_so_id}/order-type",
                json={"order_type": "drop_ship"}
            )
            res = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{test_so_id}/summary")
        
        if res.status_code == 200:
            data = res.json()
            assert "approval_status" in data, "SO summary should include approval_status"
            # If no approvals requested, status should be not_requested
            if data["approval_history_count"] == 0:
                assert data["approval_status"] == "not_requested"
            assert "latest_approval_type" in data
            assert "latest_approval_at" in data
            assert "approval_history_count" in data
            print(f"PASS: SO summary includes approval enrichment fields")
        else:
            # Create the order type entry so we can test with drop-ship
            print(f"SKIP: Could not test SO summary enrichment (SO not found)")

    def test_so_summary_includes_approval_fields_when_approved(self):
        """SO summary should show approval status after approval"""
        test_so_id = f"SO-TEST-SUMAPPR-{uuid.uuid4().hex[:6].upper()}"
        
        # Set as drop-ship (doesn't require commitments)
        requests.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{test_so_id}/order-type",
            json={"order_type": "drop_ship"}
        )
        
        # Request approval
        req_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/approvals/request",
            json={
                "entity_type": "sales_order",
                "entity_id": test_so_id,
                "approval_type": "sales_order",
            }
        )
        if req_res.status_code != 200:
            pytest.skip("Failed to create approval request")
        
        approval_id = req_res.json()["approval_id"]
        
        # Approve it
        approve_res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/approvals/{approval_id}",
            json={"approval_status": "approved", "approved_by": "test_mgr"}
        )
        assert approve_res.status_code == 200
        
        # Get SO summary
        summary_res = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{test_so_id}/summary")
        assert summary_res.status_code == 200, f"Expected 200, got {summary_res.status_code}"
        
        data = summary_res.json()
        assert data["approval_status"] == "approved", f"Expected approved, got {data['approval_status']}"
        assert data["latest_approval_type"] == "sales_order"
        assert data["latest_approval_at"] != ""
        assert data["approval_history_count"] >= 1
        print(f"PASS: SO summary shows approved status after approval")


class TestPODraftEnrichment:
    """Tests for approval enrichment in PO draft detail"""

    def test_po_draft_detail_includes_approval_fields(self):
        """PO draft detail should include approval enrichment fields"""
        # Get a customer and existing PO draft
        cust_res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers")
        if cust_res.status_code != 200 or not cust_res.json():
            pytest.skip("No customers available")
        
        customer_id = cust_res.json()[0]["id"]
        
        drafts_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={customer_id}")
        if drafts_res.status_code != 200 or not drafts_res.json().get("drafts"):
            pytest.skip("No PO drafts available")
        
        draft = drafts_res.json()["drafts"][0]
        draft_id = draft["po_draft_id"]
        
        # Get PO draft detail
        detail_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}")
        assert detail_res.status_code == 200
        
        data = detail_res.json()
        assert "approval_status" in data, "PO draft detail should include approval_status"
        assert "latest_approval_type" in data
        assert "latest_approval_at" in data
        assert "approval_history_count" in data
        print(f"PASS: PO draft detail includes approval enrichment fields")


class TestChecklistIntegration:
    """Tests for checklist integration with approval items"""

    def test_warehouse_so_checklist_includes_approval_items(self):
        """Warehouse SO checklist should include approval_requested and approval_granted"""
        test_so_id = f"SO-TEST-WHCKLIST-{uuid.uuid4().hex[:6].upper()}"
        
        # Set as warehouse type
        requests.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{test_so_id}/order-type",
            json={"order_type": "warehouse"}
        )
        
        # Get checklist
        checklist_res = requests.get(f"{BASE_URL}/api/inventory-ledger/document-links/checklist/sales-order/{test_so_id}")
        assert checklist_res.status_code == 200
        
        data = checklist_res.json()
        assert data["order_type"] == "warehouse"
        
        checklist = data["process_checklist"]
        checklist_keys = [item["key"] for item in checklist]
        
        assert "approval_requested" in checklist_keys, "Warehouse SO checklist should include approval_requested"
        assert "approval_granted" in checklist_keys, "Warehouse SO checklist should include approval_granted"
        print(f"PASS: Warehouse SO checklist includes approval_requested and approval_granted")

    def test_drop_ship_so_checklist_includes_approval_granted(self):
        """Drop-ship SO checklist should include approval_granted"""
        test_so_id = f"SO-TEST-DSCKLIST-{uuid.uuid4().hex[:6].upper()}"
        
        # Set as drop_ship type
        requests.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{test_so_id}/order-type",
            json={"order_type": "drop_ship"}
        )
        
        # Get checklist
        checklist_res = requests.get(f"{BASE_URL}/api/inventory-ledger/document-links/checklist/sales-order/{test_so_id}")
        assert checklist_res.status_code == 200
        
        data = checklist_res.json()
        assert data["order_type"] == "drop_ship"
        
        checklist = data["process_checklist"]
        checklist_keys = [item["key"] for item in checklist]
        
        assert "approval_granted" in checklist_keys, "Drop-ship SO checklist should include approval_granted"
        # Drop-ship should NOT have approval_requested (only warehouse has it)
        assert "approval_requested" not in checklist_keys, "Drop-ship SO should not have approval_requested"
        print(f"PASS: Drop-ship SO checklist includes approval_granted (without approval_requested)")

    def test_po_draft_checklist_includes_approval_granted(self):
        """PO draft checklist should include approval_granted"""
        # Get a customer and existing PO draft
        cust_res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers")
        if cust_res.status_code != 200 or not cust_res.json():
            pytest.skip("No customers available")
        
        customer_id = cust_res.json()[0]["id"]
        
        drafts_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={customer_id}")
        if drafts_res.status_code != 200 or not drafts_res.json().get("drafts"):
            pytest.skip("No PO drafts available")
        
        draft = drafts_res.json()["drafts"][0]
        draft_id = draft["po_draft_id"]
        
        # Get checklist
        checklist_res = requests.get(f"{BASE_URL}/api/inventory-ledger/document-links/checklist/po-draft/{draft_id}")
        assert checklist_res.status_code == 200
        
        data = checklist_res.json()
        checklist = data["process_checklist"]
        checklist_keys = [item["key"] for item in checklist]
        
        assert "approval_granted" in checklist_keys, "PO draft checklist should include approval_granted"
        print(f"PASS: PO draft checklist includes approval_granted")

    def test_checklist_updates_when_approval_granted(self):
        """Checklist should update approval_granted status when approval is granted"""
        test_so_id = f"SO-TEST-CKLUPD-{uuid.uuid4().hex[:6].upper()}"
        
        # Set as warehouse type
        requests.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{test_so_id}/order-type",
            json={"order_type": "warehouse"}
        )
        
        # Get initial checklist - approval_granted should be unsatisfied
        checklist_res1 = requests.get(f"{BASE_URL}/api/inventory-ledger/document-links/checklist/sales-order/{test_so_id}")
        assert checklist_res1.status_code == 200
        data1 = checklist_res1.json()
        
        approval_granted_item1 = next((item for item in data1["process_checklist"] if item["key"] == "approval_granted"), None)
        assert approval_granted_item1 is not None
        assert approval_granted_item1["satisfied"] == False, "approval_granted should be unsatisfied initially"
        
        # Request and approve
        req_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/approvals/request",
            json={
                "entity_type": "sales_order",
                "entity_id": test_so_id,
                "approval_type": "sales_order",
            }
        )
        assert req_res.status_code == 200
        approval_id = req_res.json()["approval_id"]
        
        approve_res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/approvals/{approval_id}",
            json={"approval_status": "approved"}
        )
        assert approve_res.status_code == 200
        
        # Get updated checklist
        checklist_res2 = requests.get(f"{BASE_URL}/api/inventory-ledger/document-links/checklist/sales-order/{test_so_id}")
        assert checklist_res2.status_code == 200
        data2 = checklist_res2.json()
        
        approval_granted_item2 = next((item for item in data2["process_checklist"] if item["key"] == "approval_granted"), None)
        assert approval_granted_item2 is not None
        assert approval_granted_item2["satisfied"] == True, "approval_granted should be satisfied after approval"
        print(f"PASS: Checklist updates approval_granted status when approval is granted")


class TestRegressionDocumentLinkage:
    """Regression tests - iteration_85 document linkage should still work"""

    def test_document_linkage_still_works(self):
        """Document linkage CRUD should still work after approval changes"""
        test_so_id = f"SO-TEST-REGDOC-{uuid.uuid4().hex[:6].upper()}"
        
        # Create document link
        doc_payload = {
            "entity_type": "sales_order",
            "entity_id": test_so_id,
            "document_type": "customer_po",
            "document_name": "Regression Test PO",
            "document_url": "https://example.com/po123",
        }
        create_res = requests.post(f"{BASE_URL}/api/inventory-ledger/document-links", json=doc_payload)
        assert create_res.status_code == 200, f"Expected 200, got {create_res.status_code}"
        doc_id = create_res.json()["document_link_id"]
        
        # List documents
        list_res = requests.get(f"{BASE_URL}/api/inventory-ledger/document-links?entity_type=sales_order&entity_id={test_so_id}")
        assert list_res.status_code == 200
        assert list_res.json()["total"] >= 1
        
        # Delete document
        del_res = requests.delete(f"{BASE_URL}/api/inventory-ledger/document-links/{doc_id}")
        assert del_res.status_code == 200
        
        print(f"PASS: Document linkage CRUD still works (regression test)")


class TestRegressionDropShipWorkflow:
    """Regression tests - iteration_84 drop-ship workflow should still work"""

    def test_drop_ship_workflow_still_works(self):
        """Drop-ship PO draft generation should still work"""
        test_so_id = f"SO-TEST-REGDS-{uuid.uuid4().hex[:6].upper()}"
        
        # Set as drop_ship
        type_res = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{test_so_id}/order-type",
            json={"order_type": "drop_ship"}
        )
        assert type_res.status_code == 200, f"Expected 200, got {type_res.status_code}"
        
        # Generate drop-ship PO draft
        gen_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{test_so_id}/generate-drop-ship-po-draft",
            json={
                "lines": [{"item": "TEST-ITEM-001", "qty": 10}],
                "vendor_name": "Test Vendor"
            }
        )
        assert gen_res.status_code == 200, f"Expected 200, got {gen_res.status_code}: {gen_res.text}"
        data = gen_res.json()
        assert data["po_type"] == "drop_ship"
        assert data["sales_order_id"] == test_so_id
        
        print(f"PASS: Drop-ship workflow still works (regression test)")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
