"""
Test Activity Timeline Feature (Iteration 90)
- POST /api/inventory-ledger/activities - manual notes
- GET /api/inventory-ledger/activities - list with filters
- System auto-generated activities (assignments, approvals, documents, escalations)
- Activity enrichment in Operations Queue and SO/PO detail
- stale_days filter, sort_by=latest_activity, dashboard counts
"""
import pytest
import requests
import os
from datetime import datetime, timedelta

BASE_URL = os.environ.get('REACT_APP_BACKEND_URL', '').rstrip('/')

@pytest.fixture(scope="module")
def api_client():
    """Shared requests session"""
    session = requests.Session()
    session.headers.update({"Content-Type": "application/json"})
    return session


class TestOperationsQueueActivityEnrichment:
    """Test activity enrichment in Operations Queue"""

    def test_operations_queue_returns_activity_fields(self, api_client):
        """Operations Queue items include latest_activity_at, latest_activity_type, activity_count"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue", params={"limit": 10})
        assert res.status_code == 200
        data = res.json()
        
        # Check response-level activity counts
        assert "recent_activity_today" in data, "Missing recent_activity_today in response"
        assert "no_recent_activity_7d" in data, "Missing no_recent_activity_7d in response"
        print(f"Activity counts - Today: {data['recent_activity_today']}, Stale 7d: {data['no_recent_activity_7d']}")
        
        # Check item-level enrichment (check first item if exists)
        if data["items"]:
            item = data["items"][0]
            assert "latest_activity_at" in item, "Item missing latest_activity_at"
            assert "latest_activity_type" in item, "Item missing latest_activity_type"
            assert "activity_count" in item, "Item missing activity_count"
            print(f"Sample item activity: type={item.get('latest_activity_type')}, count={item.get('activity_count')}")

    def test_sort_by_latest_activity(self, api_client):
        """sort_by=latest_activity sorts by most recent activity first"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue", params={
            "sort_by": "latest_activity",
            "limit": 20
        })
        assert res.status_code == 200
        data = res.json()
        
        if len(data["items"]) >= 2:
            # Items with activity should be sorted by latest_activity_at descending
            items_with_activity = [i for i in data["items"] if i.get("latest_activity_at")]
            if len(items_with_activity) >= 2:
                dates = [i["latest_activity_at"] for i in items_with_activity]
                assert dates == sorted(dates, reverse=True), "Items should be sorted by latest_activity_at descending"
        print("sort_by=latest_activity verified")

    def test_stale_days_filter(self, api_client):
        """stale_days=7 filters for items with no recent activity"""
        res = api_client.get(f"{BASE_URL}/api/inventory-ledger/operations-queue", params={
            "stale_days": 7,
            "limit": 50
        })
        assert res.status_code == 200
        data = res.json()
        
        # All items should have no activity or activity older than 7 days
        cutoff = (datetime.utcnow() - timedelta(days=7)).isoformat()
        for item in data["items"]:
            act_at = item.get("latest_activity_at", "")
            if act_at:
                assert act_at < cutoff, f"Item {item['entity_id']} has recent activity but passed stale filter"
        print(f"stale_days=7 filter returned {data['total']} items")


if __name__ == "__main__":
    pytest.main([__file__, "-v", "--tb=short"])
