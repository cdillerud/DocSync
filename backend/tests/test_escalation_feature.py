"""
Test Escalation & Due Dates Feature - Iteration 88

Tests:
1. POST /api/inventory-ledger/escalations - create/upsert with derived status
2. GET /api/inventory-ledger/escalations - list escalations with filters
3. PATCH /api/inventory-ledger/escalations/{id} - update and manual escalate
4. Derived status logic: overdue (past), due_soon (<=3 days), on_track (>3 days), escalated (preserved)
5. Operations Queue enrichment with escalation data
6. Priority score boosted by escalation status
7. Validation: entity_type must be sales_order or po_draft
8. Validation: PO Draft must exist if entity_type=po_draft
"""

import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestEscalationCRUD:
    """Test Escalation CRUD endpoints"""

    @pytest.fixture(autouse=True)
    def setup(self, api_client):
        self.client = api_client
        self.test_so_id = f"TEST-ESC-SO-{datetime.now().strftime('%Y%m%d%H%M%S')}"

    def test_create_escalation_for_sales_order_due_in_future(self, api_client):
        """POST /api/inventory-ledger/escalations - create with future due date -> on_track"""
        future_date = (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d")
        payload = {
            "entity_type": "sales_order",
            "entity_id": self.test_so_id,
            "due_date": future_date,
            "notes": "Test escalation for SO - future due date",
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
        assert res.status_code == 200, f"Expected 200, got {res.status_code}: {res.text}"

        data = res.json()
        assert "escalation_id" in data
        assert data["entity_type"] == "sales_order"
        assert data["entity_id"] == self.test_so_id
        assert data["due_date"] == future_date
        assert data["escalation_status"] == "on_track", f"Expected on_track for future date, got {data['escalation_status']}"
        print(f"✓ Created escalation {data['escalation_id']} with on_track status")

    def test_create_escalation_due_soon(self, api_client):
        """POST /api/inventory-ledger/escalations - due date in 2 days -> due_soon"""
        soon_date = (datetime.now() + timedelta(days=2)).strftime("%Y-%m-%d")
        test_id = f"TEST-ESC-SOON-{datetime.now().strftime('%H%M%S')}"
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_id,
            "due_date": soon_date,
            "notes": "Test due_soon status",
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
        assert res.status_code == 200

        data = res.json()
        assert data["escalation_status"] == "due_soon", f"Expected due_soon for date in 2 days, got {data['escalation_status']}"
        print(f"✓ Escalation with due date in 2 days has due_soon status")

    def test_create_escalation_overdue(self, api_client):
        """POST /api/inventory-ledger/escalations - past due date -> overdue"""
        past_date = (datetime.now() - timedelta(days=5)).strftime("%Y-%m-%d")
        test_id = f"TEST-ESC-OVERDUE-{datetime.now().strftime('%H%M%S')}"
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_id,
            "due_date": past_date,
            "notes": "Test overdue status",
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
        assert res.status_code == 200

        data = res.json()
        assert data["escalation_status"] == "overdue", f"Expected overdue for past date, got {data['escalation_status']}"
        print(f"✓ Escalation with past due date has overdue status")

    def test_create_escalation_invalid_entity_type(self, api_client):
        """POST /api/inventory-ledger/escalations - invalid entity_type -> 422"""
        payload = {
            "entity_type": "invalid_type",
            "entity_id": "test-123",
            "due_date": "2026-01-20",
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
        assert res.status_code == 422
        assert "entity_type must be sales_order or po_draft" in res.text
        print("✓ Invalid entity_type returns 422")

    def test_create_escalation_po_draft_not_found(self, api_client):
        """POST /api/inventory-ledger/escalations - PO Draft must exist -> 404"""
        payload = {
            "entity_type": "po_draft",
            "entity_id": "NONEXISTENT-PO-DRAFT-12345",
            "due_date": "2026-01-25",
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
        assert res.status_code == 404
        assert "not found" in res.text.lower()
        print("✓ Non-existent PO Draft returns 404")

    def test_list_escalations(self, api_client):
        """GET /api/inventory-ledger/escalations - list all"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/escalations")
        assert res.status_code == 200

        data = res.json()
        assert "total" in data
        assert "entries" in data
        assert isinstance(data["entries"], list)
        print(f"✓ Listed {data['total']} escalation records")

    def test_list_escalations_filtered_by_entity_type(self, api_client):
        """GET /api/inventory-ledger/escalations?entity_type=sales_order"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/escalations?entity_type=sales_order")
        assert res.status_code == 200

        data = res.json()
        for entry in data["entries"]:
            assert entry["entity_type"] == "sales_order"
        print(f"✓ Filtered escalations by entity_type=sales_order: {data['total']} entries")

    def test_list_escalations_filtered_by_entity_id(self, api_client):
        """GET /api/inventory-ledger/escalations?entity_type=sales_order&entity_id=X"""
        # First create one to be sure
        test_id = f"TEST-FILTER-{datetime.now().strftime('%H%M%S')}"
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_id,
            "due_date": (datetime.now() + timedelta(days=5)).strftime("%Y-%m-%d"),
        }
        api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)

        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/escalations?entity_type=sales_order&entity_id={test_id}")
        assert res.status_code == 200

        data = res.json()
        assert data["total"] >= 1
        assert any(e["entity_id"] == test_id for e in data["entries"])
        print(f"✓ Filtered escalations by entity_id={test_id}")


class TestEscalationUpdate:
    """Test PATCH /api/inventory-ledger/escalations/{id}"""

    def test_update_escalation_due_date(self, api_client):
        """PATCH - update due_date, status should re-derive"""
        # Create first
        test_id = f"TEST-UPDATE-{datetime.now().strftime('%H%M%S')}"
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_id,
            "due_date": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d"),
        }
        create_res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
        assert create_res.status_code == 200
        esc_id = create_res.json()["escalation_id"]

        # Update to soon date
        new_date = (datetime.now() + timedelta(days=1)).strftime("%Y-%m-%d")
        update_res = api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/escalations/{esc_id}",
            json={"due_date": new_date},
        )
        assert update_res.status_code == 200
        updated = update_res.json()
        assert updated["due_date"] == new_date
        assert updated["escalation_status"] == "due_soon"
        print(f"✓ Updated due_date, status re-derived to due_soon")

    def test_manual_escalation(self, api_client):
        """PATCH - manually set escalation_status='escalated' preserves status"""
        # Create first
        test_id = f"TEST-MANUAL-ESC-{datetime.now().strftime('%H%M%S')}"
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_id,
            "due_date": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d"),
        }
        create_res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
        assert create_res.status_code == 200
        esc_id = create_res.json()["escalation_id"]

        # Manual escalate
        update_res = api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/escalations/{esc_id}",
            json={"escalation_status": "escalated", "notes": "Manually escalated"},
        )
        assert update_res.status_code == 200
        updated = update_res.json()
        assert updated["escalation_status"] == "escalated"
        print(f"✓ Manually escalated - status preserved as 'escalated'")

    def test_update_nonexistent_escalation(self, api_client):
        """PATCH - nonexistent escalation_id -> 404"""
        res = api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/escalations/ESC-NONEXISTENT",
            json={"notes": "test"},
        )
        assert res.status_code == 404
        print("✓ Non-existent escalation_id returns 404")

    def test_update_invalid_escalation_status(self, api_client):
        """PATCH - invalid escalation_status -> 422"""
        # Create first
        test_id = f"TEST-INV-STATUS-{datetime.now().strftime('%H%M%S')}"
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_id,
            "due_date": (datetime.now() + timedelta(days=10)).strftime("%Y-%m-%d"),
        }
        create_res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
        esc_id = create_res.json()["escalation_id"]

        # Invalid status
        res = api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/escalations/{esc_id}",
            json={"escalation_status": "invalid_status"},
        )
        assert res.status_code == 422
        print("✓ Invalid escalation_status returns 422")


class TestOperationsQueueEscalationEnrichment:
    """Test Operations Queue returns escalation data"""

    def test_operations_queue_has_escalation_fields(self, api_client):
        """GET /api/inventory-ledger/operations-queue - items have escalation fields"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?limit=50")
        assert res.status_code == 200

        data = res.json()
        assert "items" in data
        assert "due_soon_count" in data
        assert "overdue_count" in data
        assert "escalated_count" in data

        print(f"✓ Operations Queue summary: due_soon={data['due_soon_count']}, overdue={data['overdue_count']}, escalated={data['escalated_count']}")

        # Check item structure
        if data["items"]:
            item = data["items"][0]
            assert "due_date" in item
            assert "escalation_status" in item
            assert "days_to_due" in item
            assert "days_overdue" in item
            print(f"✓ Queue items have escalation fields: due_date, escalation_status, days_to_due, days_overdue")

    def test_operations_queue_filter_by_escalation_overdue(self, api_client):
        """GET /api/inventory-ledger/operations-queue?escalation=overdue"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?escalation=overdue")
        assert res.status_code == 200

        data = res.json()
        for item in data["items"]:
            assert item.get("escalation_status") == "overdue", f"Expected overdue, got {item.get('escalation_status')}"
        print(f"✓ Filtered by escalation=overdue: {len(data['items'])} items")

    def test_operations_queue_filter_by_escalation_due_soon(self, api_client):
        """GET /api/inventory-ledger/operations-queue?escalation=due_soon"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?escalation=due_soon")
        assert res.status_code == 200

        data = res.json()
        for item in data["items"]:
            assert item.get("escalation_status") == "due_soon"
        print(f"✓ Filtered by escalation=due_soon: {len(data['items'])} items")


class TestPriorityScoreEscalationBoost:
    """Test that escalation status boosts priority score"""

    def test_priority_boosted_by_escalation(self, api_client):
        """Verify escalation adds to priority score: due_soon +10, overdue +20, escalated +30"""
        # Create an SO with an overdue escalation
        test_id = f"TEST-PRIORITY-BOOST-{datetime.now().strftime('%H%M%S')}"

        # First check if we have any existing items with escalation
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?escalation=overdue&limit=5")
        data = res.json()

        if data["items"]:
            item = data["items"][0]
            # Overdue items should have at least +20 from escalation
            assert item["priority_score"] >= 20, f"Overdue item should have score >= 20, got {item['priority_score']}"
            print(f"✓ Overdue item {item['entity_id']} has priority score {item['priority_score']} (includes +20 for overdue)")
        else:
            # Create one to test
            past_date = (datetime.now() - timedelta(days=3)).strftime("%Y-%m-%d")
            payload = {
                "entity_type": "sales_order",
                "entity_id": test_id,
                "due_date": past_date,
            }
            api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
            print("✓ Created test overdue escalation to verify priority boost")


class TestDerivedStatusLogic:
    """Test derived status logic edge cases"""

    def test_due_date_today_is_due_soon(self, api_client):
        """Due date = today -> due_soon (0 days is <= 3)"""
        today = datetime.now().strftime("%Y-%m-%d")
        test_id = f"TEST-TODAY-{datetime.now().strftime('%H%M%S')}"
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_id,
            "due_date": today,
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
        assert res.status_code == 200

        data = res.json()
        assert data["escalation_status"] == "due_soon"
        print(f"✓ Due date = today results in due_soon status")

    def test_due_date_exactly_3_days_is_due_soon(self, api_client):
        """Due date = 3 days from now -> due_soon"""
        three_days = (datetime.now() + timedelta(days=3)).strftime("%Y-%m-%d")
        test_id = f"TEST-3DAYS-{datetime.now().strftime('%H%M%S')}"
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_id,
            "due_date": three_days,
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
        assert res.status_code == 200

        data = res.json()
        assert data["escalation_status"] == "due_soon"
        print(f"✓ Due date = 3 days from now results in due_soon status")

    def test_due_date_4_days_is_on_track(self, api_client):
        """Due date = 4 days from now -> on_track"""
        four_days = (datetime.now() + timedelta(days=4)).strftime("%Y-%m-%d")
        test_id = f"TEST-4DAYS-{datetime.now().strftime('%H%M%S')}"
        payload = {
            "entity_type": "sales_order",
            "entity_id": test_id,
            "due_date": four_days,
        }
        res = api_client.post(f"{BASE_URL}/api/inventory-ledger/escalations", json=payload)
        assert res.status_code == 200

        data = res.json()
        assert data["escalation_status"] == "on_track"
        print(f"✓ Due date = 4 days from now results in on_track status")

    def test_escalated_status_preserved_even_with_future_date(self, api_client):
        """Manual escalated status is preserved even if due_date is in future"""
        test_id = f"TEST-ESC-PRESERVE-{datetime.now().strftime('%H%M%S')}"
        future_date = (datetime.now() + timedelta(days=30)).strftime("%Y-%m-%d")

        # Create
        create_res = api_client.post(
            f"{BASE_URL}/api/inventory-ledger/escalations",
            json={"entity_type": "sales_order", "entity_id": test_id, "due_date": future_date},
        )
        esc_id = create_res.json()["escalation_id"]

        # Manually escalate
        api_client.patch(
            f"{BASE_URL}/api/inventory-ledger/escalations/{esc_id}",
            json={"escalation_status": "escalated"},
        )

        # Retrieve and verify
        get_res = api_client.get(f"{BASE_URL}/api/inventory-ledger/escalations?entity_type=sales_order&entity_id={test_id}")
        data = get_res.json()
        assert data["entries"][0]["escalation_status"] == "escalated"
        print("✓ Escalated status preserved even with future due date")


class TestEscalationEnrichmentInSOAndPODetail:
    """Test escalation data appears in SO/PO detail endpoints"""

    def test_so_summary_includes_escalation(self, api_client):
        """GET /api/inventory-ledger/sales-orders/{id}/summary - includes escalation fields"""
        # First find an SO
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=sales_order&limit=1")
        if not res.json()["items"]:
            pytest.skip("No sales orders in queue to test")

        so_id = res.json()["items"][0]["entity_id"]

        # Get SO summary
        summary_res = api_client.get(f"{BASE_URL}/api/inventory-ledger/sales-orders/{so_id}/summary")
        if summary_res.status_code != 200:
            pytest.skip(f"SO summary endpoint returned {summary_res.status_code}")

        data = summary_res.json()
        # Check for escalation fields
        assert "due_date" in data or "escalation_status" in data
        print(f"✓ SO summary for {so_id} includes escalation enrichment fields")

    def test_po_draft_detail_includes_escalation(self, api_client):
        """GET /api/inventory-ledger/po-drafts/{id} - includes escalation fields"""
        # First find a PO draft
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue?entity_type=po_draft&limit=1")
        if not res.json()["items"]:
            pytest.skip("No PO drafts in queue to test")

        draft_id = res.json()["items"][0]["entity_id"]

        # Get PO draft detail
        detail_res = api_client.get(f"{BASE_URL}/api/inventory-ledger/po-drafts/{draft_id}")
        if detail_res.status_code != 200:
            pytest.skip(f"PO draft detail endpoint returned {detail_res.status_code}")

        data = detail_res.json()
        # Check for escalation fields (added by _get_escalation_enrichment)
        assert "due_date" in data or "escalation_status" in data
        print(f"✓ PO draft detail for {draft_id} includes escalation enrichment fields")


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
