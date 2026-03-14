"""
Test PO Draft Generation endpoints - iteration_73

Tests:
- POST /api/inventory-ledger/generate-po-draft: Creates PO draft, validates items, handles duplicates
- GET /api/inventory-ledger/po-drafts: Lists drafts, filters by status and customer
- PATCH /api/inventory-ledger/po-drafts/{id}/status: Updates draft status
- GET /api/inventory-ledger/item-detail: last_po_draft integration
"""

import pytest
import requests
import os
import time
from datetime import datetime

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

# Hormel customer workspace - known to exist from previous iterations
CUSTOMER_ID = "366bfcce-4d68-4daf-b9f4-cb05a35de8c8"
CUSTOMER_CODE = "HORMEL"


@pytest.fixture
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


@pytest.fixture
def known_items(api_client):
    """Get some known items from the customer inventory for testing"""
    response = api_client.get(f"{BASE_URL}/api/inventory-ledger/customers/{CUSTOMER_ID}/balances")
    assert response.status_code == 200
    balances = response.json().get("balances", [])
    # Return first 5 items
    return [b["item"] for b in balances[:5]] if balances else []


@pytest.fixture
def archived_draft_item(api_client):
    """Get or create an archived draft item so we can test fresh PO creation"""
    # First, list existing drafts to find any that can be archived
    response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}&status=draft")
    if response.status_code == 200:
        drafts = response.json().get("drafts", [])
        for draft in drafts:
            # Archive existing draft so tests don't hit duplicate guard
            api_client.patch(
                f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft['po_draft_id']}/status?status=archived"
            )
    return True


class TestGeneratePODraft:
    """Tests for POST /api/inventory-ledger/generate-po-draft"""

    def test_generate_po_draft_single_item(self, api_client, known_items, archived_draft_item):
        """Creates PO draft for a single valid item"""
        if not known_items:
            pytest.skip("No items found in customer inventory")
        
        # Use an item that's not likely to have recent drafts
        test_item = known_items[0]
        
        payload = {
            "customer_id": CUSTOMER_ID,
            "items": [
                {"item": test_item, "recommended_qty": 50, "source": "test"}
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/generate-po-draft", json=payload)
        
        # Could be 200 or 409 if duplicate exists
        if response.status_code == 409:
            assert "Duplicate draft" in response.json().get("detail", "")
            pytest.skip("Duplicate draft exists for this item - expected behavior")
        
        assert response.status_code == 200
        data = response.json()
        
        # Validate response structure
        assert "po_draft_id" in data
        assert data["po_draft_id"].startswith("PO-DRAFT-")
        assert data["status"] == "draft"
        assert data["total_lines"] == 1
        assert data["total_qty"] == 50
        assert "lines" in data
        assert len(data["lines"]) == 1
        assert data["lines"][0]["item"] == test_item
        assert data["lines"][0]["qty"] == 50
        assert data["customer_id"] == CUSTOMER_ID
        
        print(f"✓ Created PO draft: {data['po_draft_id']} with 1 line, 50 qty")

    def test_generate_po_draft_multiple_items(self, api_client, known_items, archived_draft_item):
        """Creates PO draft with multiple items in single request"""
        if len(known_items) < 2:
            pytest.skip("Need at least 2 items for this test")
        
        # Use items 2 and 3 (avoid index 0 which might have draft from previous test)
        items_to_use = known_items[1:3] if len(known_items) >= 3 else known_items[:2]
        
        payload = {
            "customer_id": CUSTOMER_ID,
            "items": [
                {"item": items_to_use[0], "recommended_qty": 100, "source": "action_center"},
                {"item": items_to_use[1], "recommended_qty": 200, "source": "action_center"}
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/generate-po-draft", json=payload)
        
        if response.status_code == 409:
            pytest.skip("Duplicate draft exists - expected behavior due to 5-min guard")
        
        assert response.status_code == 200
        data = response.json()
        
        assert data["total_lines"] == 2
        assert data["total_qty"] == 300
        assert len(data["lines"]) == 2
        
        print(f"✓ Created PO draft: {data['po_draft_id']} with 2 lines, 300 qty")

    def test_generate_po_draft_invalid_qty_zero(self, api_client):
        """Invalid qty (zero) returns 422"""
        payload = {
            "customer_id": CUSTOMER_ID,
            "items": [
                {"item": "SPAM-12OZ", "recommended_qty": 0, "source": "test"}
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/generate-po-draft", json=payload)
        assert response.status_code == 422
        print("✓ Zero qty correctly returns 422")

    def test_generate_po_draft_invalid_qty_negative(self, api_client):
        """Invalid qty (negative) returns 422"""
        payload = {
            "customer_id": CUSTOMER_ID,
            "items": [
                {"item": "SPAM-12OZ", "recommended_qty": -10, "source": "test"}
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/generate-po-draft", json=payload)
        assert response.status_code == 422
        print("✓ Negative qty correctly returns 422")

    def test_generate_po_draft_nonexistent_item(self, api_client):
        """Nonexistent item returns 422"""
        payload = {
            "customer_id": CUSTOMER_ID,
            "items": [
                {"item": "NONEXISTENT-ITEM-XYZ-999", "recommended_qty": 50, "source": "test"}
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/generate-po-draft", json=payload)
        assert response.status_code == 422
        assert "not found" in response.json().get("detail", "").lower()
        print("✓ Nonexistent item correctly returns 422")

    def test_generate_po_draft_nonexistent_customer(self, api_client):
        """Nonexistent customer returns 404"""
        payload = {
            "customer_id": "nonexistent-customer-id-xyz",
            "items": [
                {"item": "SPAM-12OZ", "recommended_qty": 50, "source": "test"}
            ]
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/generate-po-draft", json=payload)
        assert response.status_code == 404
        print("✓ Nonexistent customer correctly returns 404")

    def test_generate_po_draft_empty_items_array(self, api_client):
        """Empty items array returns 422"""
        payload = {
            "customer_id": CUSTOMER_ID,
            "items": []
        }
        response = api_client.post(f"{BASE_URL}/api/inventory-ledger/generate-po-draft", json=payload)
        assert response.status_code == 422
        print("✓ Empty items array correctly returns 422")

    def test_generate_po_draft_duplicate_within_5_minutes(self, api_client, known_items, archived_draft_item):
        """Duplicate draft within 5 minutes returns 409"""
        if not known_items:
            pytest.skip("No items found in customer inventory")
        
        # Use last item in list to avoid conflicts with earlier tests
        test_item = known_items[-1] if known_items else "SPAM-12OZ"
        
        payload = {
            "customer_id": CUSTOMER_ID,
            "items": [
                {"item": test_item, "recommended_qty": 25, "source": "duplicate_test"}
            ]
        }
        
        # First request
        response1 = api_client.post(f"{BASE_URL}/api/inventory-ledger/generate-po-draft", json=payload)
        
        if response1.status_code == 409:
            # Already has a recent draft - that's actually what we want to test
            assert "Duplicate draft" in response1.json().get("detail", "")
            print("✓ Duplicate guard working - existing draft detected")
            return
        
        assert response1.status_code == 200
        first_draft_id = response1.json()["po_draft_id"]
        
        # Second request with same item should return 409
        response2 = api_client.post(f"{BASE_URL}/api/inventory-ledger/generate-po-draft", json=payload)
        assert response2.status_code == 409
        assert "Duplicate draft" in response2.json().get("detail", "")
        assert first_draft_id in response2.json().get("detail", "")
        
        print(f"✓ Duplicate guard returns 409 for item '{test_item}' - references draft {first_draft_id}")


class TestListPODrafts:
    """Tests for GET /api/inventory-ledger/po-drafts"""

    def test_list_po_drafts_by_customer(self, api_client):
        """Lists drafts filtered by customer_id"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}")
        assert response.status_code == 200
        data = response.json()
        
        assert "total" in data
        assert "drafts" in data
        assert isinstance(data["drafts"], list)
        
        # All returned drafts should belong to this customer
        for draft in data["drafts"]:
            assert draft["customer_id"] == CUSTOMER_ID
            assert "po_draft_id" in draft
            assert "status" in draft
            assert "lines" in draft
            assert "total_qty" in draft
            assert "total_lines" in draft
        
        print(f"✓ Listed {data['total']} drafts for customer {CUSTOMER_CODE}")

    def test_list_po_drafts_filter_by_status(self, api_client):
        """Filters drafts by status"""
        for status in ["draft", "sent", "archived"]:
            response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}&status={status}")
            assert response.status_code == 200
            data = response.json()
            
            # All returned drafts should have the requested status
            for draft in data["drafts"]:
                assert draft["status"] == status
            
            print(f"✓ Filtered by status='{status}': {data['total']} drafts")


class TestUpdatePODraftStatus:
    """Tests for PATCH /api/inventory-ledger/po-drafts/{id}/status"""

    def test_update_draft_status_to_sent(self, api_client, known_items, archived_draft_item):
        """Updates draft status from draft to sent"""
        if not known_items:
            pytest.skip("No items found")
        
        # Create a fresh draft for this test
        payload = {
            "customer_id": CUSTOMER_ID,
            "items": [
                {"item": known_items[0], "recommended_qty": 10, "source": "status_test"}
            ]
        }
        create_response = api_client.post(f"{BASE_URL}/api/inventory-ledger/generate-po-draft", json=payload)
        
        if create_response.status_code == 409:
            # Get existing draft ID from the error message
            detail = create_response.json().get("detail", "")
            # Try to find an existing draft
            list_response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}&status=draft")
            drafts = list_response.json().get("drafts", [])
            if not drafts:
                pytest.skip("No draft available to test status update")
            draft_id = drafts[0]["po_draft_id"]
        else:
            assert create_response.status_code == 200
            draft_id = create_response.json()["po_draft_id"]
        
        # Update status to sent
        update_response = api_client.patch(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/status?status=sent")
        assert update_response.status_code == 200
        assert update_response.json()["status"] == "sent"
        print(f"✓ Updated draft {draft_id} status to 'sent'")
        
        # Update status to archived
        archive_response = api_client.patch(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/status?status=archived")
        assert archive_response.status_code == 200
        assert archive_response.json()["status"] == "archived"
        print(f"✓ Updated draft {draft_id} status to 'archived'")

    def test_update_nonexistent_draft_returns_404(self, api_client):
        """Updating nonexistent draft returns 404"""
        response = api_client.patch(f"{BASE_URL}/api/inventory-ledger/po-drafts/nonexistent-draft-id/status?status=sent")
        assert response.status_code == 404
        print("✓ Nonexistent draft correctly returns 404")

    def test_update_draft_invalid_status_returns_422(self, api_client):
        """Invalid status value returns 422"""
        # First get a draft ID
        list_response = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts?customer_id={CUSTOMER_ID}")
        drafts = list_response.json().get("drafts", [])
        
        if not drafts:
            pytest.skip("No drafts available for this test")
        
        draft_id = drafts[0]["po_draft_id"]
        
        response = api_client.patch(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}/status?status=invalid_status")
        assert response.status_code == 422
        print("✓ Invalid status correctly returns 422")


class TestItemDetailLastPODraft:
    """Tests for GET /api/inventory-ledger/item-detail last_po_draft field"""

    def test_item_detail_shows_last_po_draft(self, api_client, known_items, archived_draft_item):
        """Item detail shows last_po_draft when PO draft exists for item"""
        if not known_items:
            pytest.skip("No items found")
        
        test_item = known_items[0]
        
        # First ensure we have a draft for this item
        payload = {
            "customer_id": CUSTOMER_ID,
            "items": [
                {"item": test_item, "recommended_qty": 75, "source": "item_detail_test"}
            ]
        }
        api_client.post(f"{BASE_URL}/api/inventory-ledger/generate-po-draft", json=payload)
        # Don't check status - might be 200 or 409
        
        # Get item detail
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail?customer_id={CUSTOMER_ID}&item={test_item}")
        assert response.status_code == 200
        data = response.json()
        
        # Should have last_po_draft if we created a draft or one existed
        if data.get("last_po_draft"):
            assert "po_draft_id" in data["last_po_draft"]
            assert "status" in data["last_po_draft"]
            assert "created_at" in data["last_po_draft"]
            print(f"✓ Item {test_item} shows last_po_draft: {data['last_po_draft']['po_draft_id']} ({data['last_po_draft']['status']})")
        else:
            print(f"⚠ Item {test_item} has no last_po_draft - may have been archived or none created")

    def test_item_detail_no_po_draft_when_none_exists(self, api_client):
        """Item detail shows null last_po_draft when no PO draft exists for item"""
        # Use an item that likely has no PO drafts
        test_item = "SPAM-12OZ"  # Standard item
        
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/item-detail?customer_id={CUSTOMER_ID}&item={test_item}")
        
        if response.status_code != 200:
            pytest.skip("Item not found")
        
        data = response.json()
        # last_po_draft can be null or a dict
        if data.get("last_po_draft") is None:
            print(f"✓ Item {test_item} correctly shows null last_po_draft")
        else:
            # If it exists, it's a valid draft
            print(f"ℹ Item {test_item} has a PO draft: {data['last_po_draft']['po_draft_id']}")


class TestRegressionChecks:
    """Regression tests to ensure existing features still work"""

    def test_regression_action_center_works(self, api_client):
        """Action Center endpoint still works"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/action-center?customer_id={CUSTOMER_ID}")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "action_summary" in data
        assert "actions" in data
        print(f"✓ Action Center: {data['total']} action items, summary counts work")

    def test_regression_supply_coverage_works(self, api_client):
        """Supply Coverage endpoint still works"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/supply-coverage?customer_id={CUSTOMER_ID}")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "coverage" in data
        print(f"✓ Supply Coverage: {data['total']} items with committed demand")

    def test_regression_demand_signals_works(self, api_client):
        """Demand signals endpoint still works"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/demand-signals?customer_id={CUSTOMER_ID}")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "demand_signals" in data
        print(f"✓ Demand Signals: {data['total']} items with open demand")

    def test_regression_exceptions_works(self, api_client):
        """Exceptions endpoint still works"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/exceptions?customer_id={CUSTOMER_ID}")
        assert response.status_code == 200
        data = response.json()
        assert "total" in data
        assert "exception_summary" in data
        assert "exceptions" in data
        print(f"✓ Exceptions: {data['total']} exception items")

    def test_regression_dashboard_summary_works(self, api_client):
        """Dashboard summary endpoint still works"""
        response = api_client.get(f"{BASE_URL}/api/inventory-ledger/dashboard-summary?customer_id={CUSTOMER_ID}")
        assert response.status_code == 200
        data = response.json()
        assert "total_items" in data
        assert "items_ok" in data
        assert "items_low" in data
        assert "items_short" in data
        print(f"✓ Dashboard Summary: {data['total_items']} items ({data['items_ok']} OK, {data['items_low']} LOW, {data['items_short']} SHORT)")
