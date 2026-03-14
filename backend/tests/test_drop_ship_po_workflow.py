"""
Test Drop-Ship Purchase Order Workflow
Iteration 84: Drop-Ship SO → PO draft generation → Vendor shipment → Invoice closeout

Tests:
- POST /generate-drop-ship-po-draft creates PO with po_type=drop_ship and sales_order_id
- generate-drop-ship-po-draft rejects warehouse SO with 422
- GET /drop-ship-po-drafts lists linked DS PO drafts
- Drop-ship PO draft excluded from incoming supply conversion (POST create-incoming-supply returns 422)
- PATCH /bc-response works for drop_ship draft (captures bc_po_number, bc_response_status) but does NOT create incoming supply
- POST /drop-ship-vendor-shipment records vendor shipment
- drop-ship-vendor-shipment rejects warehouse SO with 422
- drop-ship-vendor-shipment validates linked PO draft if provided
- GET /drop-ship-vendor-shipment-log lists vendor shipment logs
- POST bc-invoice for drop-ship SO succeeds after vendor shipment (no commitment checks)
- GET summary for drop-ship SO shows enriched fields
- summary operational_status reflects ds workflow stages: pending -> po_drafted -> shipped -> complete
- POST reconcile-sales-order for drop_ship still returns 422 (iteration_83 regression)
"""
import pytest
import requests
import os
import uuid

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')


class TestDropShipPOWorkflow:
    """Test drop-ship PO draft generation and vendor shipment flow"""
    
    @pytest.fixture(autouse=True)
    def setup(self):
        """Setup test SO ID for each test"""
        self.test_so_id = f"SO-DS-TEST-{uuid.uuid4().hex[:6].upper()}"
        # First set order type to drop_ship
        self._ensure_drop_ship_order_type(self.test_so_id)
        yield
    
    def _ensure_drop_ship_order_type(self, so_id):
        """Ensure the SO is set to drop_ship type"""
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/order-type",
            json={"order_type": "drop_ship"}
        )
        # May return 200 or already be drop_ship
        return response
    
    # ═══════════════════════════════════════════════════════════════
    # POST /generate-drop-ship-po-draft
    # ═══════════════════════════════════════════════════════════════
    
    def test_generate_drop_ship_po_draft_success(self):
        """POST /generate-drop-ship-po-draft creates PO with po_type=drop_ship and sales_order_id"""
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/generate-drop-ship-po-draft",
            json={
                "lines": [
                    {"item": "TEST-ITEM-001", "qty": 100, "description": "Test item 1"},
                    {"item": "TEST-ITEM-002", "qty": 50, "description": "Test item 2"}
                ],
                "vendor_name": "Acme Plastics",
                "notes": "Test drop-ship PO"
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Validate PO draft structure
        assert "po_draft_id" in data
        assert data["po_draft_id"].startswith("PO-DS-"), f"Expected PO-DS- prefix, got {data['po_draft_id']}"
        assert data["po_type"] == "drop_ship", f"Expected po_type='drop_ship', got {data.get('po_type')}"
        assert data["sales_order_id"] == self.test_so_id, f"Expected sales_order_id={self.test_so_id}, got {data.get('sales_order_id')}"
        assert data["total_lines"] == 2
        assert data["total_qty"] == 150
        assert data["vendor_name"] == "Acme Plastics"
        assert data["status"] == "draft"
        
        # Verify lines structure
        assert len(data["lines"]) == 2
        assert data["lines"][0]["item"] == "TEST-ITEM-001"
        assert data["lines"][0]["qty"] == 100
        assert data["lines"][0]["source"] == "drop_ship_so"
        
        print(f"✓ Drop-ship PO draft created: {data['po_draft_id']}")
        return data["po_draft_id"]
    
    def test_generate_drop_ship_po_draft_rejects_warehouse_so(self):
        """POST /generate-drop-ship-po-draft rejects warehouse SO with 422"""
        # Use a warehouse SO (not set to drop_ship)
        warehouse_so_id = f"SO-WH-TEST-{uuid.uuid4().hex[:6].upper()}"
        # Don't set order type - defaults to warehouse
        
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{warehouse_so_id}/generate-drop-ship-po-draft",
            json={
                "lines": [{"item": "TEST-ITEM", "qty": 10, "description": "Test"}],
                "vendor_name": "Test Vendor"
            }
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        data = response.json()
        assert "warehouse" in data.get("detail", "").lower() or "drop_ship" in data.get("detail", "").lower()
        print(f"✓ Warehouse SO correctly rejected: {data.get('detail')}")
    
    # ═══════════════════════════════════════════════════════════════
    # GET /drop-ship-po-drafts
    # ═══════════════════════════════════════════════════════════════
    
    def test_list_drop_ship_po_drafts(self):
        """GET /drop-ship-po-drafts lists linked DS PO drafts"""
        # First create a PO draft
        create_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/generate-drop-ship-po-draft",
            json={
                "lines": [{"item": "TEST-ITEM-LIST", "qty": 25, "description": "List test"}],
                "vendor_name": "List Vendor"
            }
        )
        assert create_res.status_code == 200
        created_draft_id = create_res.json()["po_draft_id"]
        
        # List drafts
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/drop-ship-po-drafts"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "drafts" in data
        assert "total" in data
        assert data["total"] >= 1
        
        # Find our draft
        our_draft = next((d for d in data["drafts"] if d["po_draft_id"] == created_draft_id), None)
        assert our_draft is not None, f"Created draft {created_draft_id} not found in list"
        assert our_draft["po_type"] == "drop_ship"
        assert our_draft["sales_order_id"] == self.test_so_id
        
        print(f"✓ Listed {data['total']} drop-ship PO drafts for {self.test_so_id}")
    
    # ═══════════════════════════════════════════════════════════════
    # POST /create-incoming-supply for drop_ship draft (must be blocked)
    # ═══════════════════════════════════════════════════════════════
    
    def test_drop_ship_po_draft_excluded_from_incoming_supply(self):
        """Drop-ship PO draft excluded from incoming supply conversion (POST create-incoming-supply returns 422)"""
        # Create a drop-ship PO draft
        create_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/generate-drop-ship-po-draft",
            json={
                "lines": [{"item": "TEST-SUPPLY-BLOCK", "qty": 30, "description": "Supply test"}],
                "vendor_name": "Supply Vendor"
            }
        )
        assert create_res.status_code == 200
        draft_id = create_res.json()["po_draft_id"]
        
        # Try to convert to incoming supply - should be blocked
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/create-incoming-supply"
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        data = response.json()
        assert "drop" in data.get("detail", "").lower() or "ship" in data.get("detail", "").lower()
        print(f"✓ Drop-ship PO draft correctly blocked from incoming supply: {data.get('detail')}")
    
    # ═══════════════════════════════════════════════════════════════
    # PATCH /bc-response for drop_ship draft
    # ═══════════════════════════════════════════════════════════════
    
    def test_bc_response_for_drop_ship_draft(self):
        """PATCH /bc-response works for drop_ship draft (captures bc_po_number, bc_response_status) but does NOT create incoming supply"""
        # Create a drop-ship PO draft
        create_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/generate-drop-ship-po-draft",
            json={
                "lines": [{"item": "TEST-BC-RESP", "qty": 40, "description": "BC response test"}],
                "vendor_name": "BC Vendor"
            }
        )
        assert create_res.status_code == 200
        draft_id = create_res.json()["po_draft_id"]
        
        # Record BC response
        bc_po_num = f"BC-PO-{uuid.uuid4().hex[:6].upper()}"
        response = requests.patch(
            f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/bc-response",
            json={
                "bc_response_status": "created",
                "bc_po_number": bc_po_num,
                "bc_document_id": "BC-DOC-123",
                "bc_response_notes": "Drop-ship PO created in BC"
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert data["bc_response_status"] == "created"
        assert data["bc_po_number"] == bc_po_num
        
        # Verify no incoming supply was created for this draft
        supply_res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/incoming-supply")
        assert supply_res.status_code == 200
        supply_data = supply_res.json()
        # Drop-ship drafts should have 0 linked supply records
        assert supply_data["total"] == 0, f"Expected 0 linked supply records for drop-ship draft, got {supply_data['total']}"
        
        print(f"✓ BC response captured for drop-ship draft without creating incoming supply")
    
    # ═══════════════════════════════════════════════════════════════
    # POST /drop-ship-vendor-shipment
    # ═══════════════════════════════════════════════════════════════
    
    def test_drop_ship_vendor_shipment_success(self):
        """POST /drop-ship-vendor-shipment records vendor shipment"""
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/drop-ship-vendor-shipment",
            json={
                "shipped_lines": [
                    {"item": "TEST-SHIP-001", "qty_shipped": 50},
                    {"item": "TEST-SHIP-002", "qty_shipped": 25}
                ],
                "vendor_shipment_number": "VSH-001",
                "vendor_document_id": "VDOC-001",
                "shipment_notes": "Shipped direct to customer"
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "vendor_shipment_id" in data
        assert data["vendor_shipment_id"].startswith("VSH-")
        assert data["sales_order_id"] == self.test_so_id
        assert data["vendor_shipment_number"] == "VSH-001"
        assert data["total_recorded"] == 2
        
        # Verify results
        assert len(data["results"]) == 2
        assert data["results"][0]["status"] == "recorded"
        assert "drop-ship" in data["results"][0]["note"].lower()
        
        print(f"✓ Vendor shipment recorded: {data['vendor_shipment_id']}")
        return data["vendor_shipment_id"]
    
    def test_drop_ship_vendor_shipment_rejects_warehouse_so(self):
        """POST /drop-ship-vendor-shipment rejects warehouse SO with 422"""
        warehouse_so_id = f"SO-WH-SHIP-{uuid.uuid4().hex[:6].upper()}"
        # Don't set order type - defaults to warehouse
        
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{warehouse_so_id}/drop-ship-vendor-shipment",
            json={
                "shipped_lines": [{"item": "TEST-ITEM", "qty_shipped": 10}],
                "vendor_shipment_number": "VSH-TEST"
            }
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        data = response.json()
        assert "warehouse" in data.get("detail", "").lower() or "drop_ship" in data.get("detail", "").lower()
        print(f"✓ Warehouse SO correctly rejected for vendor shipment: {data.get('detail')}")
    
    def test_drop_ship_vendor_shipment_validates_linked_po_draft(self):
        """POST /drop-ship-vendor-shipment validates linked PO draft if provided"""
        # Create a drop-ship PO draft first
        create_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/generate-drop-ship-po-draft",
            json={
                "lines": [{"item": "TEST-LINKED", "qty": 20, "description": "Linked test"}],
                "vendor_name": "Linked Vendor"
            }
        )
        assert create_res.status_code == 200
        valid_draft_id = create_res.json()["po_draft_id"]
        
        # Test with valid linked PO draft
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/drop-ship-vendor-shipment",
            json={
                "shipped_lines": [{"item": "TEST-LINKED", "qty_shipped": 20}],
                "po_draft_id": valid_draft_id,
                "vendor_shipment_number": "VSH-LINKED"
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        
        # Test with non-existent PO draft
        response_invalid = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/drop-ship-vendor-shipment",
            json={
                "shipped_lines": [{"item": "TEST-ITEM", "qty_shipped": 10}],
                "po_draft_id": "PO-NONEXISTENT-123",
                "vendor_shipment_number": "VSH-INVALID"
            }
        )
        assert response_invalid.status_code == 404, f"Expected 404, got {response_invalid.status_code}"
        print(f"✓ PO draft validation working correctly")
        
        # Test with PO draft linked to different SO (should fail)
        different_so_id = f"SO-OTHER-{uuid.uuid4().hex[:6].upper()}"
        self._ensure_drop_ship_order_type(different_so_id)
        diff_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{different_so_id}/generate-drop-ship-po-draft",
            json={
                "lines": [{"item": "OTHER-ITEM", "qty": 10, "description": "Other"}],
                "vendor_name": "Other Vendor"
            }
        )
        assert diff_res.status_code == 200
        other_draft_id = diff_res.json()["po_draft_id"]
        
        response_wrong_so = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/drop-ship-vendor-shipment",
            json={
                "shipped_lines": [{"item": "TEST-ITEM", "qty_shipped": 10}],
                "po_draft_id": other_draft_id,
                "vendor_shipment_number": "VSH-WRONGSO"
            }
        )
        assert response_wrong_so.status_code == 422, f"Expected 422, got {response_wrong_so.status_code}"
        print(f"✓ PO draft linked to wrong SO correctly rejected")
    
    # ═══════════════════════════════════════════════════════════════
    # GET /drop-ship-vendor-shipment-log
    # ═══════════════════════════════════════════════════════════════
    
    def test_list_vendor_shipment_logs(self):
        """GET /drop-ship-vendor-shipment-log lists vendor shipment logs"""
        # First create a vendor shipment
        ship_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/drop-ship-vendor-shipment",
            json={
                "shipped_lines": [{"item": "LOG-TEST-ITEM", "qty_shipped": 15}],
                "vendor_shipment_number": "VSH-LOG-TEST",
                "shipment_notes": "Log test shipment"
            }
        )
        assert ship_res.status_code == 200
        
        # List logs
        response = requests.get(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/drop-ship-vendor-shipment-log"
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "entries" in data
        assert "total" in data
        assert data["total"] >= 1
        
        # Find our log entry
        our_log = next((e for e in data["entries"] if e.get("vendor_shipment_number") == "VSH-LOG-TEST"), None)
        assert our_log is not None, "Created vendor shipment log not found"
        assert our_log["sales_order_id"] == self.test_so_id
        assert "shipped_lines" in our_log
        
        print(f"✓ Listed {data['total']} vendor shipment logs for {self.test_so_id}")
    
    # ═══════════════════════════════════════════════════════════════
    # POST /bc-invoice for drop-ship SO (after vendor shipment)
    # ═══════════════════════════════════════════════════════════════
    
    def test_bc_invoice_for_drop_ship_after_vendor_shipment(self):
        """POST bc-invoice for drop-ship SO succeeds after vendor shipment (no commitment checks)"""
        # First record a vendor shipment
        ship_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/drop-ship-vendor-shipment",
            json={
                "shipped_lines": [{"item": "INV-TEST-ITEM", "qty_shipped": 30}],
                "vendor_shipment_number": "VSH-INV-TEST"
            }
        )
        assert ship_res.status_code == 200
        
        # Now record invoice
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/bc-invoice",
            json={
                "bc_invoice_number": f"INV-DS-{uuid.uuid4().hex[:6].upper()}",
                "bc_document_id": "BC-INV-DOC",
                "invoice_date": "2026-01-15",
                "invoice_notes": "Drop-ship invoice test"
            }
        )
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        assert "invoice_log_id" in data
        assert data["order_type"] == "drop_ship"
        assert data["sales_order_id"] == self.test_so_id
        
        print(f"✓ Invoice captured for drop-ship SO: {data['bc_invoice_number']}")
    
    def test_bc_invoice_for_drop_ship_without_shipment_fails(self):
        """POST bc-invoice for drop-ship SO without shipment fails"""
        # Create a fresh drop-ship SO without any shipments
        fresh_so_id = f"SO-FRESH-INV-{uuid.uuid4().hex[:6].upper()}"
        self._ensure_drop_ship_order_type(fresh_so_id)
        
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{fresh_so_id}/bc-invoice",
            json={
                "bc_invoice_number": "INV-SHOULD-FAIL",
                "invoice_notes": "Should fail - no shipment"
            }
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        data = response.json()
        assert "shipment" in data.get("detail", "").lower()
        print(f"✓ Invoice without shipment correctly rejected: {data.get('detail')}")
    
    # ═══════════════════════════════════════════════════════════════
    # GET /summary for drop-ship SO (enriched fields)
    # ═══════════════════════════════════════════════════════════════
    
    def test_summary_shows_drop_ship_enrichment(self):
        """GET summary for drop-ship SO shows enriched fields"""
        # Create PO draft
        po_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/generate-drop-ship-po-draft",
            json={
                "lines": [{"item": "SUMM-TEST", "qty": 100, "description": "Summary test"}],
                "vendor_name": "Summary Vendor"
            }
        )
        assert po_res.status_code == 200
        po_draft_id = po_res.json()["po_draft_id"]
        
        # Get summary after PO creation
        response = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{self.test_so_id}/summary")
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        
        # Verify enriched fields
        assert data["order_type"] == "drop_ship"
        assert "linked_drop_ship_po_draft_count" in data
        assert data["linked_drop_ship_po_draft_count"] >= 1
        assert "linked_drop_ship_po_draft_id" in data
        assert "latest_drop_ship_po_status" in data
        assert "latest_vendor_shipment_number" in data
        assert "latest_vendor_shipped_at" in data
        
        print(f"✓ Summary shows drop-ship enrichment: {data['linked_drop_ship_po_draft_count']} PO drafts")
        return data
    
    def test_summary_operational_status_workflow(self):
        """summary operational_status reflects ds workflow stages: pending -> po_drafted -> shipped -> complete"""
        # Fresh SO - should be pending
        fresh_so = f"SO-STATUS-{uuid.uuid4().hex[:6].upper()}"
        self._ensure_drop_ship_order_type(fresh_so)
        
        # Stage 1: pending (no PO, no shipment)
        res1 = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{fresh_so}/summary")
        assert res1.status_code == 200
        assert res1.json()["operational_status"] == "pending", f"Expected 'pending', got {res1.json()['operational_status']}"
        print(f"✓ Stage 1: operational_status = pending")
        
        # Stage 2: po_drafted (create PO draft)
        po_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{fresh_so}/generate-drop-ship-po-draft",
            json={
                "lines": [{"item": "STATUS-ITEM", "qty": 10, "description": "Status test"}],
                "vendor_name": "Status Vendor"
            }
        )
        assert po_res.status_code == 200
        
        res2 = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{fresh_so}/summary")
        assert res2.status_code == 200
        assert res2.json()["operational_status"] == "po_drafted", f"Expected 'po_drafted', got {res2.json()['operational_status']}"
        print(f"✓ Stage 2: operational_status = po_drafted")
        
        # Stage 3: shipped (record vendor shipment)
        ship_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{fresh_so}/drop-ship-vendor-shipment",
            json={
                "shipped_lines": [{"item": "STATUS-ITEM", "qty_shipped": 10}],
                "vendor_shipment_number": "VSH-STATUS"
            }
        )
        assert ship_res.status_code == 200
        
        res3 = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{fresh_so}/summary")
        assert res3.status_code == 200
        assert res3.json()["operational_status"] == "shipped", f"Expected 'shipped', got {res3.json()['operational_status']}"
        print(f"✓ Stage 3: operational_status = shipped")
        
        # Stage 4: complete (record invoice)
        inv_res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/sales-orders/{fresh_so}/bc-invoice",
            json={"bc_invoice_number": "INV-STATUS-TEST"}
        )
        assert inv_res.status_code == 200
        
        res4 = requests.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{fresh_so}/summary")
        assert res4.status_code == 200
        assert res4.json()["operational_status"] == "complete", f"Expected 'complete', got {res4.json()['operational_status']}"
        print(f"✓ Stage 4: operational_status = complete")
    
    # ═══════════════════════════════════════════════════════════════
    # POST /reconcile-sales-order for drop_ship (regression test)
    # ═══════════════════════════════════════════════════════════════
    
    def test_reconcile_rejects_drop_ship_so(self):
        """POST reconcile-sales-order for drop_ship still returns 422 (iteration_83 regression)"""
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/reconcile-sales-order",
            json={
                "customer_id": "TEST-CUST",
                "sales_order_id": self.test_so_id,
                "items_to_reconcile": [{"item": "TEST-ITEM", "qty": 10}]
            }
        )
        assert response.status_code == 422, f"Expected 422, got {response.status_code}: {response.text}"
        data = response.json()
        assert "drop" in data.get("detail", "").lower() or "inventory" in data.get("detail", "").lower()
        print(f"✓ Reconcile correctly rejects drop-ship SO: {data.get('detail')}")


class TestDropShipPODraftIsolation:
    """Test that drop-ship PO drafts don't interfere with warehouse supply flows"""
    
    def test_warehouse_po_draft_still_works(self):
        """Verify warehouse PO drafts still work normally (regression test)"""
        # First we need a customer workspace for warehouse PO draft
        # List customers to get an existing one
        cust_res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers")
        if cust_res.status_code != 200 or not cust_res.json():
            pytest.skip("No customers available for warehouse PO test")
        
        customer = cust_res.json()[0]
        customer_id = customer["id"]
        
        # Get balances to find an existing item
        bal_res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{customer_id}/balances")
        if bal_res.status_code != 200:
            pytest.skip("Cannot fetch balances")
        
        balances = bal_res.json().get("balances", [])
        if not balances:
            pytest.skip("No inventory items available")
        
        test_item = balances[0]["item"]
        
        # Generate a warehouse PO draft (existing action center flow)
        # This uses the standard generate-po-draft endpoint
        response = requests.post(
            f"{BASE_URL}/api/inventory-ledger/generate-po-draft",
            json={
                "customer_id": customer_id,
                "items": [
                    {"item": test_item, "recommended_qty": 10, "source": "test"}
                ]
            }
        )
        
        # May get 409 if recent duplicate - that's OK for this test
        if response.status_code == 409:
            print(f"✓ Warehouse PO draft endpoint working (duplicate protection active)")
            return
        
        assert response.status_code == 200, f"Expected 200, got {response.status_code}: {response.text}"
        data = response.json()
        assert data["po_type"] == "warehouse_supply", f"Expected po_type='warehouse_supply', got {data.get('po_type')}"
        
        print(f"✓ Warehouse PO draft created: {data['po_draft_id']}")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
