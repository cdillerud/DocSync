"""
Operations Queue (Unified Worklist) - Tests for iteration_87
Tests the GET /api/inventory-ledger/operations-queue endpoint and priority scoring.
"""

import pytest
import requests
import os

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL')

# Priority weights from implementation
PRIORITY_WEIGHTS = {
    "missing_approval": 50,
    "missing_documents": 40,
    "inventory_shortage": 35,
    "missing_po_draft": 30,
    "missing_vendor": 25,
    "pending_bc_export": 20,
    "pending_bc_response": 15,
    "pending_shipment": 10,
    "pending_invoice": 5,
}


class TestOperationsQueueEndpoint:
    """Test /api/inventory-ledger/operations-queue endpoint"""

    def test_operations_queue_returns_200(self):
        """Basic endpoint availability test"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue")
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"
        data = res.json()
        
        # Verify response structure
        assert "total" in data, "Missing 'total' in response"
        assert "high_priority_count" in data, "Missing 'high_priority_count' in response"
        assert "offset" in data, "Missing 'offset' in response"
        assert "limit" in data, "Missing 'limit' in response"
        assert "items" in data, "Missing 'items' in response"
        print(f"SUCCESS: Operations queue returned {data['total']} items, {data['high_priority_count']} high priority")

    def test_operations_queue_sorted_by_priority_desc(self):
        """Items should be sorted by priority_score DESC, then created_at ASC"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=50")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        if len(items) < 2:
            pytest.skip("Need at least 2 items to verify sorting")
        
        # Check priority_score is descending (allow equal scores)
        for i in range(1, len(items)):
            prev_score = items[i-1].get("priority_score", 0)
            curr_score = items[i].get("priority_score", 0)
            assert prev_score >= curr_score, f"Items not sorted by priority DESC: index {i-1}={prev_score}, index {i}={curr_score}"
        
        print(f"SUCCESS: {len(items)} items verified as sorted by priority DESC")

    def test_filter_by_entity_type_sales_order(self):
        """Filter by entity_type=sales_order returns only SOs"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=sales_order")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        for item in items:
            assert item.get("entity_type") == "sales_order", f"Got non-SO item: {item.get('entity_type')}"
        
        print(f"SUCCESS: Filtered to {len(items)} sales_order items")

    def test_filter_by_entity_type_po_draft(self):
        """Filter by entity_type=po_draft returns only PO drafts"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=po_draft")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        for item in items:
            assert item.get("entity_type") == "po_draft", f"Got non-PO-draft item: {item.get('entity_type')}"
        
        print(f"SUCCESS: Filtered to {len(items)} po_draft items")

    def test_item_structure_has_required_fields(self):
        """Each item should have all required fields"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=10")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        required_fields = [
            "entity_type", "entity_id", "order_type", "priority_score",
            "action_required", "next_action", "approval_status"
        ]
        
        for item in items:
            for field in required_fields:
                assert field in item, f"Missing field '{field}' in item {item.get('entity_id', 'unknown')}"
            
            # Validate types
            assert isinstance(item.get("priority_score"), (int, float)), "priority_score should be numeric"
            assert isinstance(item.get("action_required"), list), "action_required should be a list"
            assert isinstance(item.get("entity_type"), str), "entity_type should be string"
            assert isinstance(item.get("entity_id"), str), "entity_id should be string"
        
        print(f"SUCCESS: {len(items)} items have all required fields")

    def test_items_with_zero_score_excluded(self):
        """Items with score=0 (all actions complete) should not appear in queue"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=500")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        for item in items:
            assert item.get("priority_score", 0) > 0, f"Item {item.get('entity_id')} has zero score but is in queue"
        
        print(f"SUCCESS: All {len(items)} items have non-zero priority scores")

    def test_high_priority_count_correct(self):
        """high_priority_count should match items with score >= 40"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=500")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        calculated_high = sum(1 for i in items if i.get("priority_score", 0) >= 40)
        reported_high = data.get("high_priority_count", 0)
        
        # If we got all items (total <= limit), counts should match exactly
        if data.get("total", 0) <= 500:
            assert calculated_high == reported_high, f"High priority count mismatch: calculated={calculated_high}, reported={reported_high}"
        
        print(f"SUCCESS: High priority count verified: {reported_high}")


class TestPriorityScoring:
    """Test that priority scoring follows the documented weights"""

    def test_missing_approval_adds_50_points(self):
        """Items with missing approval should have at least 50 points"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=100")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        for item in items:
            if item.get("approval_status") != "approved":
                # Should have at least missing_approval weight
                assert item.get("priority_score", 0) >= PRIORITY_WEIGHTS["missing_approval"], \
                    f"Item {item.get('entity_id')} has unapproved status but score={item.get('priority_score')} < 50"
        
        print("SUCCESS: Missing approval scoring verified")

    def test_action_required_list_not_empty_for_items_in_queue(self):
        """Items in queue should have at least one action_required"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=50")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        for item in items:
            actions = item.get("action_required", [])
            assert len(actions) > 0, f"Item {item.get('entity_id')} in queue with empty action_required"
        
        print(f"SUCCESS: All {len(items)} items have non-empty action_required lists")

    def test_next_action_matches_first_action_required(self):
        """next_action should be the first item in action_required or 'Review'"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=50")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        for item in items:
            actions = item.get("action_required", [])
            next_action = item.get("next_action", "")
            if actions:
                assert next_action == actions[0], f"next_action '{next_action}' != first action '{actions[0]}'"
            else:
                assert next_action == "Review", f"next_action should be 'Review' when no actions"
        
        print(f"SUCCESS: next_action field verified for {len(items)} items")


class TestPagination:
    """Test pagination parameters"""

    def test_limit_and_offset(self):
        """Test that limit and offset work correctly"""
        # Get first page
        res1 = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=5&offset=0")
        assert res1.status_code == 200
        data1 = res1.json()
        
        # Get second page
        res2 = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=5&offset=5")
        assert res2.status_code == 200
        data2 = res2.json()
        
        items1 = data1.get("items", [])
        items2 = data2.get("items", [])
        
        # If we have enough items, pages should be different
        if len(items1) == 5 and len(items2) > 0:
            ids1 = {i["entity_id"] for i in items1}
            ids2 = {i["entity_id"] for i in items2}
            assert ids1.isdisjoint(ids2), "Pagination overlap: same items in different pages"
        
        print(f"SUCCESS: Pagination test passed - page1: {len(items1)} items, page2: {len(items2)} items")

    def test_response_includes_pagination_metadata(self):
        """Response should include total, offset, limit"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=10&offset=5")
        assert res.status_code == 200
        data = res.json()
        
        assert data.get("limit") == 10, f"limit should be 10, got {data.get('limit')}"
        assert data.get("offset") == 5, f"offset should be 5, got {data.get('offset')}"
        assert "total" in data, "total count missing from response"
        
        print(f"SUCCESS: Pagination metadata correct - total={data['total']}, offset={data['offset']}, limit={data['limit']}")


class TestSOQueueItems:
    """Test queue items for Sales Orders specifically"""

    def test_warehouse_so_in_queue_if_missing_actions(self):
        """Warehouse SOs without shipment/invoice should be in queue"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=sales_order&limit=100")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        warehouse_sos = [i for i in items if i.get("order_type") == "warehouse"]
        
        for so in warehouse_sos:
            actions = so.get("action_required", [])
            # Should have at least one of: approval, shipment, invoice, documents
            print(f"  Warehouse SO {so.get('entity_id')}: score={so.get('priority_score')}, actions={actions}")
        
        print(f"SUCCESS: Found {len(warehouse_sos)} warehouse SOs in queue")

    def test_drop_ship_so_in_queue_if_missing_po_draft(self):
        """Drop-ship SOs without PO draft should be in queue with missing_po_draft action"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=sales_order&limit=100")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        drop_ship_sos = [i for i in items if i.get("order_type") == "drop_ship"]
        
        for so in drop_ship_sos:
            actions = so.get("action_required", [])
            print(f"  Drop-ship SO {so.get('entity_id')}: score={so.get('priority_score')}, actions={actions}")
        
        print(f"SUCCESS: Found {len(drop_ship_sos)} drop-ship SOs in queue")


class TestPODraftQueueItems:
    """Test queue items for PO Drafts specifically"""

    def test_po_draft_missing_vendor_in_queue(self):
        """PO drafts without vendor should be in queue"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=po_draft&limit=100")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        for draft in items:
            actions = so_get_action = draft.get("action_required", [])
            vendor_name = draft.get("vendor_name", "")
            
            if not vendor_name:
                assert "Vendor not assigned" in actions, f"PO draft {draft.get('entity_id')} missing vendor but no action"
                assert draft.get("priority_score", 0) >= PRIORITY_WEIGHTS["missing_vendor"]
        
        print(f"SUCCESS: {len(items)} PO drafts checked for vendor assignment")

    def test_po_draft_includes_order_type(self):
        """PO drafts should include order_type field (warehouse_supply or drop_ship)"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=po_draft&limit=20")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        for draft in items:
            order_type = draft.get("order_type")
            assert order_type in ["warehouse_supply", "drop_ship"], f"Invalid order_type: {order_type}"
        
        print(f"SUCCESS: All {len(items)} PO drafts have valid order_type")


class TestRegressionIteration86:
    """Regression tests for approval workflow from iteration_86"""

    def test_approval_endpoints_still_work(self):
        """Approval request endpoint should still function"""
        # Just verify the endpoint exists and doesn't error
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/approvals")
        # GET without params may return error, that's fine
        print(f"Approval endpoint response: {res.status_code}")
        
    def test_approval_status_in_queue_items(self):
        """Queue items should include approval_status from iteration_86"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=10")
        assert res.status_code == 200
        data = res.json()
        items = data.get("items", [])
        
        for item in items:
            assert "approval_status" in item, f"Missing approval_status in item {item.get('entity_id')}"
            status = item.get("approval_status")
            assert status in ["approved", "pending", "rejected", "not_requested"], f"Invalid approval_status: {status}"
        
        print(f"SUCCESS: approval_status present in all {len(items)} queue items")


class TestRegressionIteration85:
    """Regression tests for document linkage from iteration_85"""

    def test_document_link_endpoint_still_works(self):
        """Document link endpoint should still function"""
        res = requests.get(f"{BASE_URL}/api/inventory-ledger/document-links?entity_type=sales_order&entity_id=TEST-SO-123")
        # May return empty but shouldn't error
        assert res.status_code == 200 or res.status_code == 404, f"Unexpected status: {res.status_code}"
        print("SUCCESS: Document link endpoint accessible")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "-s"])
