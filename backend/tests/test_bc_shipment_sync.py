"""
Test P4-A: BC Shipment Sync → Inventory Ledger

Tests:
  - sync_bc_shipments creates outbound_shipment movements from BC shipment data
  - Duplicate shipments are idempotently skipped (no double movements)
  - Sync status tracking (last_sync_at, shipments_processed_today, last_error)
  - POST /api/inventory-ledger/sync-bc-shipments endpoint
  - GET /api/inventory-ledger/sync-status endpoint
  - outbound_shipment movement type is valid in the ledger
  - bc_shipment source type is valid in the ledger
  - Movement record has correct fields: negative qty, source_type, reference_id
"""
import pytest
import sys
import os
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from unittest.mock import AsyncMock, patch
from datetime import datetime, timezone

from services.inventory_ledger_service import (
    MOVEMENT_TYPES, SOURCE_TYPES, MOVEMENTS_COLL, CUSTOMERS_COLL,
    create_movement, get_customer,
)
from services.inventory_so_integration import (
    sync_bc_shipments, get_sync_status, _is_shipment_already_synced,
    _mark_shipment_synced, BC_SHIPMENT_SYNC_COLL, _SYNC_STATUS_KEY,
    resolve_inventory_workspace,
)

_MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
_DB_NAME = os.environ.get("DB_NAME", "gpi_document_hub")


def _motor_db():
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(_MONGO_URL)
    return client, client[_DB_NAME]


def _sync_cleanup(collections=None):
    from pymongo import MongoClient
    c = MongoClient(_MONGO_URL)
    db = c[_DB_NAME]
    if collections:
        for coll in collections:
            db[coll].delete_many({"_test": True})
    db[BC_SHIPMENT_SYNC_COLL].delete_many({"_test_marker": True})
    db.hub_config.delete_one({"_key": _SYNC_STATUS_KEY})
    # Cleanup test customer workspaces and movements
    db[CUSTOMERS_COLL].delete_many({"code": {"$regex": "^TEST-SHIP"}})
    db[MOVEMENTS_COLL].delete_many({"created_by": "bc_shipment_sync_test"})
    db[MOVEMENTS_COLL].delete_many({"created_by": "bc_shipment_sync"})
    db[BC_SHIPMENT_SYNC_COLL].delete_many({})
    c.close()


# =========================================================================
# Movement Type Registration Tests
# =========================================================================

class TestMovementTypeRegistration:
    def test_outbound_shipment_is_valid_movement_type(self):
        assert "outbound_shipment" in MOVEMENT_TYPES

    def test_bc_shipment_is_valid_source_type(self):
        assert "bc_shipment" in SOURCE_TYPES


# =========================================================================
# Sync Function Unit Tests (with mocked BC API)
# =========================================================================

class TestSyncBcShipments:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        self._client, self.db = _motor_db()
        yield
        _sync_cleanup()
        self._client.close()

    @pytest.fixture
    def test_workspace(self):
        """Create a test inventory workspace (sync pymongo for setup)."""
        from pymongo import MongoClient
        ws_id = str(uuid.uuid4())
        c = MongoClient(_MONGO_URL)
        c[_DB_NAME][CUSTOMERS_COLL].insert_one({
            "id": ws_id,
            "name": "Test Shipper Inc",
            "code": "TEST-SHIP-01",
            "active": True,
            "negative_balance_policy": "warn_only",
        })
        c.close()
        return ws_id

    @pytest.mark.asyncio
    async def test_sync_creates_outbound_shipment_movement(self, test_workspace):
        """A BC shipment line should create a negative outbound_shipment movement."""
        ws_id = test_workspace

        # Mock BC API to return one shipment line
        mock_lines = [{
            "documentNo": "SHIP-001",
            "lineNo": 10000,
            "number": "ITEM-A",
            "description": "Widget A",
            "quantity": 25,
            "unitOfMeasureCode": "PCS",
            "shipmentDate": "2026-02-15",
            "sellToCustomerNo": "TEST-SHIP-01",
            "orderNo": "SO-5001",
            "locationCode": "WH-MAIN",
        }]

        with patch(
            "services.inventory_so_integration._fetch_bc_shipment_lines",
            new_callable=AsyncMock, return_value=mock_lines,
        ):
            result = await sync_bc_shipments(self.db, lookback_hours=24)

        assert result["synced"] == 1
        assert result["skipped"] == 0
        assert result["total_fetched"] == 1
        assert len(result["errors"]) == 0

        # Verify the movement was created correctly
        mv = await self.db[MOVEMENTS_COLL].find_one(
            {"customer_id": ws_id, "movement_type": "outbound_shipment"},
            {"_id": 0},
        )
        assert mv is not None
        assert mv["item"] == "ITEM-A"
        assert mv["quantity_delta"] == -25  # Negative = outbound
        assert mv["source_type"] == "bc_shipment"
        assert mv["reference_id"] == "SO-5001"
        assert mv["warehouse"] == "WH-MAIN"
        assert mv["unit_of_measure"] == "PCS"

    @pytest.mark.asyncio
    async def test_duplicate_sync_skips_already_processed(self, test_workspace):
        """Running sync twice with the same data should not create duplicate movements."""
        mock_lines = [{
            "documentNo": "SHIP-002",
            "lineNo": 20000,
            "number": "ITEM-B",
            "description": "Widget B",
            "quantity": 10,
            "unitOfMeasureCode": "EA",
            "shipmentDate": "2026-02-15",
            "sellToCustomerNo": "TEST-SHIP-01",
            "orderNo": "SO-5002",
            "locationCode": "MAIN",
        }]

        with patch(
            "services.inventory_so_integration._fetch_bc_shipment_lines",
            new_callable=AsyncMock, return_value=mock_lines,
        ):
            result1 = await sync_bc_shipments(self.db, lookback_hours=24)
            result2 = await sync_bc_shipments(self.db, lookback_hours=24)

        assert result1["synced"] == 1
        assert result2["synced"] == 0
        assert result2["skipped"] == 1

        # Only one movement should exist
        count = await self.db[MOVEMENTS_COLL].count_documents({
            "customer_id": test_workspace,
            "movement_type": "outbound_shipment",
            "reference_id": "SO-5002",
        })
        assert count == 1

    @pytest.mark.asyncio
    async def test_sync_with_no_workspace_records_error(self):
        """Lines for unknown customers should produce errors, not movements."""
        mock_lines = [{
            "documentNo": "SHIP-003",
            "lineNo": 30000,
            "number": "ITEM-C",
            "description": "Widget C",
            "quantity": 5,
            "shipmentDate": "2026-02-15",
            "sellToCustomerNo": "UNKNOWN-CUSTOMER-999",
            "orderNo": "SO-5003",
        }]

        with patch(
            "services.inventory_so_integration._fetch_bc_shipment_lines",
            new_callable=AsyncMock, return_value=mock_lines,
        ):
            result = await sync_bc_shipments(self.db, lookback_hours=24)

        assert result["synced"] == 0
        assert len(result["errors"]) == 1
        assert "no inventory workspace" in result["errors"][0]

    @pytest.mark.asyncio
    async def test_sync_skips_zero_quantity_lines(self, test_workspace):
        """Lines with quantity 0 should be skipped."""
        mock_lines = [{
            "documentNo": "SHIP-004",
            "lineNo": 40000,
            "number": "ITEM-D",
            "quantity": 0,
            "shipmentDate": "2026-02-15",
            "sellToCustomerNo": "TEST-SHIP-01",
            "orderNo": "SO-5004",
        }]

        with patch(
            "services.inventory_so_integration._fetch_bc_shipment_lines",
            new_callable=AsyncMock, return_value=mock_lines,
        ):
            result = await sync_bc_shipments(self.db, lookback_hours=24)

        assert result["synced"] == 0
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_sync_skips_lines_without_item(self, test_workspace):
        """Lines without an item number should be skipped."""
        mock_lines = [{
            "documentNo": "SHIP-005",
            "lineNo": 50000,
            "number": "",
            "quantity": 10,
            "shipmentDate": "2026-02-15",
            "sellToCustomerNo": "TEST-SHIP-01",
            "orderNo": "SO-5005",
        }]

        with patch(
            "services.inventory_so_integration._fetch_bc_shipment_lines",
            new_callable=AsyncMock, return_value=mock_lines,
        ):
            result = await sync_bc_shipments(self.db, lookback_hours=24)

        assert result["synced"] == 0
        assert result["skipped"] == 1

    @pytest.mark.asyncio
    async def test_sync_handles_empty_bc_response(self):
        """Empty BC response should return cleanly with zero counts."""
        with patch(
            "services.inventory_so_integration._fetch_bc_shipment_lines",
            new_callable=AsyncMock, return_value=[],
        ):
            result = await sync_bc_shipments(self.db, lookback_hours=24)

        assert result["synced"] == 0
        assert result["skipped"] == 0
        assert result["total_fetched"] == 0

    @pytest.mark.asyncio
    async def test_sync_multiple_lines_from_same_shipment(self, test_workspace):
        """Multiple lines from the same shipment doc should each create a movement."""
        mock_lines = [
            {
                "documentNo": "SHIP-006",
                "lineNo": 10000,
                "number": "ITEM-E",
                "description": "Widget E",
                "quantity": 15,
                "shipmentDate": "2026-02-15",
                "sellToCustomerNo": "TEST-SHIP-01",
                "orderNo": "SO-5006",
                "locationCode": "WH1",
            },
            {
                "documentNo": "SHIP-006",
                "lineNo": 20000,
                "number": "ITEM-F",
                "description": "Widget F",
                "quantity": 30,
                "shipmentDate": "2026-02-15",
                "sellToCustomerNo": "TEST-SHIP-01",
                "orderNo": "SO-5006",
                "locationCode": "WH1",
            },
        ]

        with patch(
            "services.inventory_so_integration._fetch_bc_shipment_lines",
            new_callable=AsyncMock, return_value=mock_lines,
        ):
            result = await sync_bc_shipments(self.db, lookback_hours=24)

        assert result["synced"] == 2
        assert result["total_fetched"] == 2


# =========================================================================
# Sync Status Tests
# =========================================================================

class TestSyncStatus:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        self._client, self.db = _motor_db()
        yield
        _sync_cleanup()
        self._client.close()

    @pytest.mark.asyncio
    async def test_default_status_when_never_synced(self):
        status = await get_sync_status(self.db)
        assert status["last_sync_at"] is None
        assert status["shipments_processed_today"] == 0
        assert status["last_error"] == ""

    @pytest.mark.asyncio
    async def test_status_updates_after_sync(self):
        with patch(
            "services.inventory_so_integration._fetch_bc_shipment_lines",
            new_callable=AsyncMock, return_value=[],
        ):
            await sync_bc_shipments(self.db)

        status = await get_sync_status(self.db)
        assert status["last_sync_at"] is not None
        assert status["last_error"] == ""

    @pytest.mark.asyncio
    async def test_status_increments_today_counter(self):
        """Create a test workspace and sync one shipment to verify counter."""
        from pymongo import MongoClient
        ws_id = str(uuid.uuid4())
        c = MongoClient(_MONGO_URL)
        c[_DB_NAME][CUSTOMERS_COLL].insert_one({
            "id": ws_id,
            "name": "Counter Test",
            "code": "TEST-SHIP-CNT",
            "active": True,
            "negative_balance_policy": "warn_only",
        })
        c.close()

        mock_lines = [{
            "documentNo": "SHIP-CNT",
            "lineNo": 10000,
            "number": "ITEM-CNT",
            "quantity": 1,
            "shipmentDate": "2026-02-15",
            "sellToCustomerNo": "TEST-SHIP-CNT",
            "orderNo": "SO-CNT",
        }]

        with patch(
            "services.inventory_so_integration._fetch_bc_shipment_lines",
            new_callable=AsyncMock, return_value=mock_lines,
        ):
            await sync_bc_shipments(self.db)

        status = await get_sync_status(self.db)
        assert status["shipments_processed_today"] == 1


# =========================================================================
# Idempotency Guard Tests
# =========================================================================

class TestIdempotencyGuard:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        self._client, self.db = _motor_db()
        yield
        _sync_cleanup()
        self._client.close()

    @pytest.mark.asyncio
    async def test_mark_and_check_synced(self):
        key = "TEST-SHIP-100_10000"
        assert await _is_shipment_already_synced(self.db, key) is False
        await _mark_shipment_synced(self.db, key, "mv-123", {"documentNo": "TEST-SHIP-100", "lineNo": 10000})
        assert await _is_shipment_already_synced(self.db, key) is True


# =========================================================================
# Create Movement with New Types
# =========================================================================

class TestOutboundShipmentMovement:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        self._client, self.db = _motor_db()
        yield
        _sync_cleanup()
        self._client.close()

    @pytest.mark.asyncio
    async def test_create_outbound_shipment_directly(self):
        """Verify outbound_shipment movement can be created via the ledger service."""
        from pymongo import MongoClient
        ws_id = str(uuid.uuid4())
        c = MongoClient(_MONGO_URL)
        c[_DB_NAME][CUSTOMERS_COLL].insert_one({
            "id": ws_id,
            "name": "Direct Test",
            "code": "TEST-SHIP-DIR",
            "active": True,
            "negative_balance_policy": "warn_only",
        })
        c.close()

        result = await create_movement(
            self.db, ws_id,
            item="ITEM-TEST",
            item_description="Test Item",
            warehouse="MAIN",
            ownership_type="customer_owned",
            movement_type="outbound_shipment",
            quantity_delta=-10,
            unit_of_measure="PCS",
            source_type="bc_shipment",
            reference_type="sales_order",
            reference_id="SO-TEST-001",
            notes="Test outbound shipment",
            created_by="bc_shipment_sync_test",
            skip_balance_check=True,
        )
        assert result["success"] is True
        mv = result["movement"]
        assert mv["movement_type"] == "outbound_shipment"
        assert mv["source_type"] == "bc_shipment"
        assert mv["quantity_delta"] == -10
        assert mv["reference_id"] == "SO-TEST-001"


# =========================================================================
# API Endpoint Tests
# =========================================================================

class TestSyncEndpoints:
    @pytest.fixture
    def base_url(self):
        return os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

    def test_get_sync_status_endpoint(self, base_url):
        import requests
        resp = requests.get(f"{base_url}/api/inventory-ledger/sync-status")
        assert resp.status_code == 200
        data = resp.json()
        assert "last_sync_at" in data
        assert "shipments_processed_today" in data
        assert "last_error" in data

    def test_post_sync_bc_shipments_endpoint(self, base_url):
        """POST sync — BC is not configured in preview env, so it returns 0 synced."""
        import requests
        resp = requests.post(f"{base_url}/api/inventory-ledger/sync-bc-shipments")
        assert resp.status_code == 200
        data = resp.json()
        assert "synced" in data
        assert "skipped" in data
        assert "total_fetched" in data

    def test_sync_with_lookback_param(self, base_url):
        import requests
        resp = requests.post(
            f"{base_url}/api/inventory-ledger/sync-bc-shipments",
            params={"lookback_hours": 48},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["total_fetched"] == 0  # BC not configured


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
