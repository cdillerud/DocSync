"""
Tests for PO Draft to Incoming Supply conversion feature (iteration_75)
Tests the POST /api/inventory-ledger/po-drafts/{id}/create-incoming-supply endpoint
"""
import pytest
import requests
import os
import json

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Known test data from context
HORMEL_CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"
CONVERTED_DRAFT_ID = "PO-DRAFT-20260314163256-689B67"  # Already converted
ARCHIVED_DRAFT_ID = "PO-DRAFT-20260314162131-7BD97C"  # Archived draft


class TestPODraftCreateIncomingSupply:
    """Tests for POST /api/inventory-ledger/po-drafts/{id}/create-incoming-supply"""

    def test_duplicate_prevention_returns_409(self):
        """Calling create-incoming-supply on already-converted draft returns 409"""
        res = requests.post(f"{BASE_URL}/api/inventory-ledger/po-drafts/{CONVERTED_DRAFT_ID}/create-incoming-supply")
        print(f"Duplicate prevention test - Status: {res.status_code}, Response: {res.text[:500]}")
        
        assert res.status_code == 409, f"Expected 409 for already converted draft, got {res.status_code}"
        data = res.json()
        assert "already been converted" in data.get("detail", "").lower() or "already" in data.get("detail", "").lower()
        print("PASS: Duplicate prevention returns 409 for already-converted draft")

    def test_archived_draft_rejection_returns_422(self):
        """Calling create-incoming-supply on archived draft returns 422"""
        res = requests.post(f"{BASE_URL}/api/inventory-ledger/po-drafts/{ARCHIVED_DRAFT_ID}/create-incoming-supply")
        print(f"Archived draft test - Status: {res.status_code}, Response: {res.text[:500]}")
        
        assert res.status_code == 422, f"Expected 422 for archived draft, got {res.status_code}"
        data = res.json()
        assert "archived" in data.get("detail", "").lower()
        print("PASS: Archived draft rejection returns 422")

    def test_nonexistent_draft_returns_404(self):
        """Calling create-incoming-supply on non-existent draft returns 404"""
        res = requests.post(f"{BASE_URL}/api/inventory-ledger/po-drafts/NONEXISTENT-DRAFT-12345/create-incoming-supply")
        print(f"Nonexistent draft test - Status: {res.status_code}")
        
        assert res.status_code == 404
        print("PASS: Non-existent draft returns 404")

    def test_get_converted_draft_has_incoming_supply_created_flag(self):
        """Already converted draft has incoming_supply_created=true flag"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{CONVERTED_DRAFT_ID}")
        print(f"Get converted draft - Status: {res.status_code}")
        
        assert res.status_code == 200
        data = res.json()
        assert data.get("incoming_supply_created") == True, f"Expected incoming_supply_created=true, got {data.get('incoming_supply_created')}"
        assert "incoming_supply_created_at" in data, "Missing incoming_supply_created_at field"
        print(f"PASS: Draft has incoming_supply_created=true, created_at={data.get('incoming_supply_created_at')}")


class TestCreateNewDraftAndConvert:
    """Test creating a new draft and converting it to incoming supply"""

    def test_create_draft_and_convert_to_supply(self):
        """Create a new PO draft and convert it to incoming supply"""
        import time
        import uuid
        
        # Step 1: Get an item from action center to use in draft
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/action-center?customer_id={HORMEL_CUSTOMER_ID}")
        assert res.status_code == 200, f"Action center request failed: {res.status_code}"
        actions = res.json().get("actions", [])
        
        if not actions:
            pytest.skip("No action items available to test with")
        
        # Find an item that can be used for PO draft
        test_item = None
        for a in actions:
            if 'reorder' in a.get('action_types', []) or 'shortage' in a.get('action_types', []) or 'coverage_risk' in a.get('action_types', []):
                test_item = a
                break
        
        if not test_item:
            # Use first action item
            test_item = actions[0]
        
        item_name = test_item['item']
        rec_qty = test_item.get('recommended_qty', 10)
        
        print(f"Using item: {item_name} with qty: {rec_qty}")
        
        # Step 2: Wait a bit to avoid duplicate window (5 min)
        # Instead, we'll use a unique item approach or check existing drafts
        
        # Step 3: Create a new PO draft
        payload = {
            "customer_id": HORMEL_CUSTOMER_ID,
            "items": [
                {"item": item_name, "recommended_qty": rec_qty, "source": "test_conversion"}
            ]
        }
        
        res = requests.post(
            f"{BASE_URL}/api/inventory-ledger/generate-po-draft",
            json=payload,
            headers={"Content-Type": "application/json"}
        )
        
        # If 409 (duplicate), find an existing unconverted draft
        if res.status_code == 409:
            print(f"Draft creation returned 409 (duplicate) - finding existing unconverted draft")
            res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={HORMEL_CUSTOMER_ID}")
            assert res.status_code == 200
            drafts = res.json().get("drafts", [])
            
            unconverted_draft = None
            for d in drafts:
                if not d.get("incoming_supply_created") and d.get("status") != "archived":
                    unconverted_draft = d
                    break
            
            if not unconverted_draft:
                pytest.skip("No unconverted non-archived draft available to test conversion")
            
            draft_id = unconverted_draft["po_draft_id"]
            print(f"Using existing unconverted draft: {draft_id}")
        else:
            assert res.status_code == 200, f"Failed to create draft: {res.status_code} - {res.text}"
            draft_data = res.json()
            draft_id = draft_data["po_draft_id"]
            print(f"Created new draft: {draft_id}")
        
        # Step 4: Convert draft to incoming supply
        res = requests.post(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/create-incoming-supply")
        print(f"Conversion response: {res.status_code} - {res.text[:500]}")
        
        assert res.status_code == 200, f"Conversion failed: {res.status_code} - {res.text}"
        conversion_data = res.json()
        
        # Verify conversion response structure
        assert "po_draft_id" in conversion_data
        assert "rows_processed" in conversion_data
        assert "rows_created" in conversion_data
        assert "rows_skipped" in conversion_data
        assert "created_supply_ids" in conversion_data
        assert "messages" in conversion_data
        
        assert conversion_data["rows_created"] >= 1 or conversion_data["rows_skipped"] >= 1
        print(f"PASS: Conversion successful - processed={conversion_data['rows_processed']}, created={conversion_data['rows_created']}, skipped={conversion_data['rows_skipped']}")
        
        # Step 5: Verify draft now has incoming_supply_created flag
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}")
        assert res.status_code == 200
        updated_draft = res.json()
        assert updated_draft.get("incoming_supply_created") == True
        print("PASS: Draft now has incoming_supply_created=true")
        
        # Step 6: Try to convert again - should return 409
        res = requests.post(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/create-incoming-supply")
        assert res.status_code == 409, f"Expected 409 for second conversion, got {res.status_code}"
        print("PASS: Second conversion attempt returns 409 (duplicate prevention)")


class TestIncomingSupplyImpactOnBalances:
    """Test that created incoming supply affects balance calculations"""

    def test_incoming_affects_derive_balances(self):
        """Verify that planned incoming supply appears in balance calculations"""
        # Get balances for Hormel
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/balances")
        assert res.status_code == 200
        balances = res.json().get("balances", [])
        
        # Check if there are any items with incoming > 0
        items_with_incoming = [b for b in balances if b.get("incoming", 0) > 0]
        print(f"Found {len(items_with_incoming)} items with incoming supply in balances")
        
        # Also check incoming supply records
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/incoming")
        assert res.status_code == 200
        incoming_records = res.json()
        
        planned_records = [r for r in incoming_records if r.get("status") == "planned"]
        print(f"Found {len(planned_records)} planned incoming supply records")
        
        # Verify balance calculation includes incoming
        for b in balances[:5]:  # Check first 5
            available = b.get("available", 0)
            on_hand = b.get("on_hand", 0)
            incoming = b.get("incoming", 0)
            committed = b.get("committed", 0)
            expected_avail = on_hand + incoming - committed
            assert abs(available - expected_avail) < 0.01, f"Balance calculation mismatch for {b['item']}: available={available}, expected={expected_avail}"
        
        print("PASS: Balance calculations correctly include incoming supply")


class TestRegressionEndpoints:
    """Regression tests for existing functionality"""

    def test_action_center_still_works(self):
        """Action Center endpoint still works"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/action-center?customer_id={HORMEL_CUSTOMER_ID}")
        assert res.status_code == 200
        data = res.json()
        assert "action_summary" in data
        assert "actions" in data
        print(f"PASS: Action Center returns {len(data['actions'])} actions")

    def test_po_drafts_list_still_works(self):
        """PO Drafts list endpoint still works"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={HORMEL_CUSTOMER_ID}")
        assert res.status_code == 200
        data = res.json()
        assert "drafts" in data
        print(f"PASS: PO Drafts list returns {len(data['drafts'])} drafts")

    def test_balances_endpoint_still_works(self):
        """Balances endpoint still works"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/balances")
        assert res.status_code == 200
        data = res.json()
        assert "balances" in data
        print(f"PASS: Balances endpoint returns {len(data['balances'])} balance rows")

    def test_incoming_supply_list_still_works(self):
        """Incoming supply list endpoint still works"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/customers/{HORMEL_CUSTOMER_ID}/incoming")
        assert res.status_code == 200
        data = res.json()
        assert isinstance(data, list)
        print(f"PASS: Incoming supply list returns {len(data)} records")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
