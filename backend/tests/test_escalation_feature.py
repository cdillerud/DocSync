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
BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")


@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


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


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
