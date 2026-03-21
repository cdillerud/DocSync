"""
Test P3-C: Warehouse SO Booked Notifications

Tests:
  - notification_service content builders produce correct HTML/text
  - send_warehouse_receiving_notice with dry_run=True logs without sending
  - send_so_confirmation_to_customer with dry_run=True logs without sending
  - on_warehouse_so_booked orchestrator calls both functions
  - Notification config read/write via hub_config
  - GET/PUT /api/settings/notification-config endpoint
  - Notifications skipped when disabled or no recipient
  - Non-dry-run mode sends via email_service (mock provider)
  - Preflight/from-document flow includes notification_results for warehouse SO
"""
import pytest
import sys
import os
import uuid

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from services.notification_service import (
    _build_warehouse_receiving_notice_content,
    _build_so_confirmation_content,
    send_warehouse_receiving_notice,
    send_so_confirmation_to_customer,
    on_warehouse_so_booked,
    get_notification_config,
    save_notification_config,
    NOTIFICATION_CONFIG_KEY,
)

_MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
_DB_NAME = os.environ.get("DB_NAME", "gpi_document_hub")


def _sync_cleanup():
    """Sync cleanup using pymongo (avoids event loop issues in teardown)."""
    from pymongo import MongoClient
    c = MongoClient(_MONGO_URL)
    c[_DB_NAME].hub_config.delete_one({"_key": NOTIFICATION_CONFIG_KEY})
    c.close()


def _motor_db():
    """Return a motor async database handle."""
    from motor.motor_asyncio import AsyncIOMotorClient
    client = AsyncIOMotorClient(_MONGO_URL)
    return client, client[_DB_NAME]


# =========================================================================
# Fixtures
# =========================================================================

@pytest.fixture
def sample_doc():
    return {
        "id": "test-doc-001",
        "document_type": "Sales_Order",
        "extracted_fields": {
            "customer": "Acme Corp",
            "po_number": "PO-12345",
            "order_date": "2026-02-15",
            "ship_date": "2026-02-20",
            "delivery_date": "2026-02-22",
            "location_code": "WH-01",
            "customer_email": "buyer@acme.com",
            "amount": "5000.00",
            "line_items": [
                {"description": "Widget A", "quantity": 100, "unit_price": 25.00, "item_number": "WA-100"},
                {"description": "Widget B", "quantity": 50, "unit_price": 50.00, "item_number": "WB-200"},
            ],
        },
        "normalized_fields": {},
    }


@pytest.fixture
def sample_so_data():
    return {
        "bc_record_no": "SO-10042",
        "customer_name": "Acme Corp",
        "external_doc_no": "PO-12345",
        "order_date": "2026-02-15",
        "so_type": "warehouse",
        "so_routing": {
            "so_type": "warehouse",
            "location_code": "WH-01",
            "ship_to_code": "",
            "ship_to_name": "",
        },
        "resolved_lines": [
            {"lineObjectNumber": "WA-100", "description": "Widget A", "quantity": 100, "unitPrice": 25.00},
            {"lineObjectNumber": "WB-200", "description": "Widget B", "quantity": 50, "unitPrice": 50.00},
        ],
    }


# =========================================================================
# Content Builder Tests
# =========================================================================

class TestBuildWarehouseReceivingNotice:
    def test_subject_contains_so_number(self, sample_doc, sample_so_data):
        content = _build_warehouse_receiving_notice_content(sample_doc, sample_so_data)
        assert "SO-10042" in content["subject"]
        assert "Warehouse Receiving Notice" in content["subject"]

    def test_html_contains_customer(self, sample_doc, sample_so_data):
        content = _build_warehouse_receiving_notice_content(sample_doc, sample_so_data)
        assert "Acme Corp" in content["html_body"]

    def test_html_contains_po_number(self, sample_doc, sample_so_data):
        content = _build_warehouse_receiving_notice_content(sample_doc, sample_so_data)
        assert "PO-12345" in content["html_body"]

    def test_html_contains_warehouse_location(self, sample_doc, sample_so_data):
        content = _build_warehouse_receiving_notice_content(sample_doc, sample_so_data)
        assert "WH-01" in content["html_body"]

    def test_html_contains_line_items(self, sample_doc, sample_so_data):
        content = _build_warehouse_receiving_notice_content(sample_doc, sample_so_data)
        assert "Widget A" in content["html_body"]
        assert "Widget B" in content["html_body"]
        assert "100" in content["html_body"]

    def test_html_contains_delivery_date(self, sample_doc, sample_so_data):
        content = _build_warehouse_receiving_notice_content(sample_doc, sample_so_data)
        assert "2026-02-22" in content["html_body"]

    def test_text_body_present(self, sample_doc, sample_so_data):
        content = _build_warehouse_receiving_notice_content(sample_doc, sample_so_data)
        assert "SO-10042" in content["text_body"]
        assert "Acme Corp" in content["text_body"]

    def test_empty_lines_shows_placeholder(self):
        doc = {"extracted_fields": {}, "normalized_fields": {}}
        so = {"bc_record_no": "SO-999"}
        content = _build_warehouse_receiving_notice_content(doc, so)
        assert "No line items available" in content["html_body"]


class TestBuildSOConfirmation:
    def test_subject_contains_so_and_po(self, sample_doc, sample_so_data):
        content = _build_so_confirmation_content(sample_doc, sample_so_data)
        assert "SO-10042" in content["subject"]
        assert "PO-12345" in content["subject"]

    def test_html_contains_customer(self, sample_doc, sample_so_data):
        content = _build_so_confirmation_content(sample_doc, sample_so_data)
        assert "Acme Corp" in content["html_body"]

    def test_html_contains_ship_date(self, sample_doc, sample_so_data):
        content = _build_so_confirmation_content(sample_doc, sample_so_data)
        assert "2026-02-20" in content["html_body"]

    def test_html_contains_line_items(self, sample_doc, sample_so_data):
        content = _build_so_confirmation_content(sample_doc, sample_so_data)
        assert "Widget A" in content["html_body"]
        assert "Widget B" in content["html_body"]

    def test_subject_without_po(self):
        doc = {"extracted_fields": {}, "normalized_fields": {}}
        so = {"bc_record_no": "SO-888", "external_doc_no": ""}
        content = _build_so_confirmation_content(doc, so)
        assert "SO-888" in content["subject"]
        assert "PO" not in content["subject"]


# =========================================================================
# Dry-Run Send Tests
# =========================================================================

class TestSendWarehouseNoticeDryRun:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        self._client, self.db = _motor_db()
        yield
        _sync_cleanup()
        self._client.close()

    @pytest.mark.asyncio
    async def test_dry_run_does_not_send(self, sample_doc, sample_so_data):
        result = await send_warehouse_receiving_notice(
            sample_doc, sample_so_data, dry_run=True, db=self.db
        )
        assert result["dry_run"] is True
        assert result["sent"] is False
        assert result["reason"] == "dry_run"
        assert "Warehouse Receiving Notice" in result["subject"]

    @pytest.mark.asyncio
    async def test_dry_run_includes_content(self, sample_doc, sample_so_data):
        result = await send_warehouse_receiving_notice(
            sample_doc, sample_so_data, dry_run=True, db=self.db
        )
        assert result["content"]["subject"].startswith("Warehouse Receiving Notice")
        assert "SO-10042" in result["content"]["html_body"]


class TestSendSOConfirmationDryRun:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        self._client, self.db = _motor_db()
        yield
        _sync_cleanup()
        self._client.close()

    @pytest.mark.asyncio
    async def test_dry_run_does_not_send(self, sample_doc, sample_so_data):
        result = await send_so_confirmation_to_customer(
            sample_doc, sample_so_data, dry_run=True, db=self.db
        )
        assert result["dry_run"] is True
        assert result["sent"] is False
        assert result["reason"] == "dry_run"

    @pytest.mark.asyncio
    async def test_dry_run_picks_customer_email_from_doc(self, sample_doc, sample_so_data):
        result = await send_so_confirmation_to_customer(
            sample_doc, sample_so_data, dry_run=True, db=self.db
        )
        assert result["to"] == "buyer@acme.com"

    @pytest.mark.asyncio
    async def test_explicit_customer_email_overrides_doc(self, sample_doc, sample_so_data):
        result = await send_so_confirmation_to_customer(
            sample_doc, sample_so_data, customer_email="override@test.com",
            dry_run=True, db=self.db
        )
        assert result["to"] == "override@test.com"

    @pytest.mark.asyncio
    async def test_spiro_email_fallback(self, sample_so_data):
        doc_no_email = {
            "id": "doc-spiro",
            "extracted_fields": {"customer": "SpiroCo"},
            "spiro_data": {"email": "spiro@customer.com"},
        }
        result = await send_so_confirmation_to_customer(
            doc_no_email, sample_so_data, dry_run=True, db=self.db
        )
        assert result["to"] == "spiro@customer.com"


# =========================================================================
# Non-Dry-Run Send Tests (via mock email provider)
# =========================================================================

class TestSendActualViaEmailService:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        self._client, self.db = _motor_db()
        # Use sync pymongo to seed config before async tests
        from pymongo import MongoClient
        sc = MongoClient(_MONGO_URL)
        sc[_DB_NAME].hub_config.update_one(
            {"_key": NOTIFICATION_CONFIG_KEY},
            {"$set": {
                "_key": NOTIFICATION_CONFIG_KEY,
                "warehouse_receiving_email": "logistics@gpi.com",
                "from_address": "GPI Document Hub <noreply@gpi-hub.local>",
                "enabled": True,
            }},
            upsert=True,
        )
        sc.close()
        yield
        _sync_cleanup()
        self._client.close()

    @pytest.mark.asyncio
    async def test_sends_warehouse_notice_via_mock(self, sample_doc, sample_so_data):
        result = await send_warehouse_receiving_notice(
            sample_doc, sample_so_data, dry_run=False, db=self.db
        )
        assert result["sent"] is True
        assert result["dry_run"] is False
        assert "result" in result
        assert result["result"]["success"] is True

    @pytest.mark.asyncio
    async def test_sends_so_confirmation_via_mock(self, sample_doc, sample_so_data):
        result = await send_so_confirmation_to_customer(
            sample_doc, sample_so_data, dry_run=False, db=self.db
        )
        assert result["sent"] is True
        assert result["to"] == "buyer@acme.com"

    @pytest.mark.asyncio
    async def test_skips_when_disabled(self, sample_doc, sample_so_data):
        await save_notification_config(self.db, warehouse_receiving_email="logistics@gpi.com", enabled=False)
        result = await send_warehouse_receiving_notice(
            sample_doc, sample_so_data, dry_run=False, db=self.db
        )
        assert result["sent"] is False
        assert result["reason"] == "disabled"

    @pytest.mark.asyncio
    async def test_skips_when_no_recipient(self, sample_doc, sample_so_data):
        await save_notification_config(self.db, warehouse_receiving_email="", enabled=True)
        result = await send_warehouse_receiving_notice(
            sample_doc, sample_so_data, dry_run=False, db=self.db
        )
        assert result["sent"] is False
        assert result["reason"] == "no_recipient"

    @pytest.mark.asyncio
    async def test_so_confirmation_skips_no_customer_email(self, sample_so_data):
        doc_no_email = {"id": "doc-noemail", "extracted_fields": {}}
        result = await send_so_confirmation_to_customer(
            doc_no_email, sample_so_data, dry_run=False, db=self.db
        )
        assert result["sent"] is False
        assert result["reason"] == "no_recipient"


# =========================================================================
# Orchestrator Tests
# =========================================================================

class TestOnWarehouseSOBooked:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        self._client, self.db = _motor_db()
        yield
        _sync_cleanup()
        self._client.close()

    @pytest.mark.asyncio
    async def test_orchestrator_returns_both_results(self, sample_doc, sample_so_data):
        results = await on_warehouse_so_booked(
            sample_doc, sample_so_data, dry_run=True, db=self.db
        )
        assert "warehouse_notice" in results
        assert "so_confirmation" in results
        assert results["warehouse_notice"]["type"] == "warehouse_receiving_notice"
        assert results["so_confirmation"]["type"] == "so_confirmation"

    @pytest.mark.asyncio
    async def test_orchestrator_dry_run_does_not_send(self, sample_doc, sample_so_data):
        results = await on_warehouse_so_booked(
            sample_doc, sample_so_data, dry_run=True, db=self.db
        )
        assert results["warehouse_notice"]["sent"] is False
        assert results["so_confirmation"]["sent"] is False


# =========================================================================
# Notification Config CRUD Tests
# =========================================================================

class TestNotificationConfig:
    @pytest.fixture(autouse=True)
    def setup_db(self):
        self._client, self.db = _motor_db()
        yield
        _sync_cleanup()
        self._client.close()

    @pytest.mark.asyncio
    async def test_get_default_config(self):
        config = await get_notification_config(self.db)
        assert config["warehouse_receiving_email"] == ""
        assert config["enabled"] is True

    @pytest.mark.asyncio
    async def test_save_and_read_config(self):
        await save_notification_config(
            self.db, warehouse_receiving_email="wh@gpi.com", from_address="hub@gpi.com", enabled=True
        )
        config = await get_notification_config(self.db)
        assert config["warehouse_receiving_email"] == "wh@gpi.com"
        assert config["from_address"] == "hub@gpi.com"
        assert config["enabled"] is True

    @pytest.mark.asyncio
    async def test_update_config(self):
        await save_notification_config(self.db, warehouse_receiving_email="old@gpi.com")
        await save_notification_config(self.db, warehouse_receiving_email="new@gpi.com")
        config = await get_notification_config(self.db)
        assert config["warehouse_receiving_email"] == "new@gpi.com"


# =========================================================================
# API Endpoint Tests
# =========================================================================

class TestNotificationConfigAPI:
    @pytest.fixture
    def base_url(self):
        return os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")

    def test_get_notification_config(self, base_url):
        import requests
        resp = requests.get(f"{base_url}/api/settings/notification-config")
        assert resp.status_code == 200
        data = resp.json()
        assert "notification_config" in data
        assert "warehouse_receiving_email" in data["notification_config"]
        assert "enabled" in data["notification_config"]

    def test_put_notification_config(self, base_url):
        import requests
        resp = requests.put(
            f"{base_url}/api/settings/notification-config",
            json={"warehouse_receiving_email": "test-logistics@gpi.com", "enabled": True},
        )
        assert resp.status_code == 200
        data = resp.json()
        assert data["notification_config"]["warehouse_receiving_email"] == "test-logistics@gpi.com"

        # Read back
        resp2 = requests.get(f"{base_url}/api/settings/notification-config")
        assert resp2.status_code == 200
        assert resp2.json()["notification_config"]["warehouse_receiving_email"] == "test-logistics@gpi.com"

        # Cleanup
        requests.put(
            f"{base_url}/api/settings/notification-config",
            json={"warehouse_receiving_email": ""},
        )

    def test_put_partial_update(self, base_url):
        import requests
        # Set initial
        requests.put(
            f"{base_url}/api/settings/notification-config",
            json={"warehouse_receiving_email": "partial@gpi.com", "enabled": True},
        )
        # Partial update — only disable
        resp = requests.put(
            f"{base_url}/api/settings/notification-config",
            json={"enabled": False},
        )
        assert resp.status_code == 200
        data = resp.json()["notification_config"]
        assert data["enabled"] is False
        # Email should remain unchanged
        assert data["warehouse_receiving_email"] == "partial@gpi.com"

        # Cleanup
        requests.put(
            f"{base_url}/api/settings/notification-config",
            json={"warehouse_receiving_email": "", "enabled": True},
        )


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
