from copy import deepcopy

import pytest
from fastapi import HTTPException

from routes import document_delivery


class FakeInsertResult:
    inserted_id = "fake-id"


class FakeCollection:
    def __init__(self):
        self.documents = []

    async def find_one(self, query, projection=None):
        for document in self.documents:
            if all(document.get(key) == value for key, value in query.items()):
                result = deepcopy(document)
                if projection and projection.get("_id") == 0:
                    result.pop("_id", None)
                return result
        return None

    async def insert_one(self, document):
        stored = deepcopy(document)
        stored.setdefault("_id", "fake-id")
        self.documents.append(stored)
        return FakeInsertResult()

    async def count_documents(self, query):
        if not query:
            return len(self.documents)
        return sum(
            1
            for document in self.documents
            if all(document.get(key) == value for key, value in query.items())
        )


class FakeDatabase:
    def __init__(self):
        self.zetadocs_delivery_packages = FakeCollection()


def standard_payload():
    return {
        "correlation_id": "bc-sales-order-114679-order-confirmation-v1",
        "document": {
            "document_type": "SALES_ORDER_CONFIRMATION",
            "record_type": "Sales Order",
            "record_no": "114679",
            "system_id": "00000000-0000-0000-0000-000000000001",
            "report_id": 50020,
            "requested_action": "PREVIEW",
        },
        "customer": {
            "customer_no": "NATION",
            "sell_to_customer_no": "NATION",
            "bill_to_customer_no": "NATION",
            "ship_to_customer_no": "NATION",
            "organization": "National Dry",
            "document_email": "customer@example.com",
        },
        "order": {
            "order_type": "SALES_ORDER",
            "external_document_no": "BILLY EMAIL",
            "location_code": "00",
        },
        "actors": {
            "initiated_by": "cheryl@gamerpackaging.com",
            "sender_email": "cheryl@gamerpackaging.com",
            "isr_code": "CB",
            "isr_email": "cheryl@gamerpackaging.com",
            "osr_code": "DT",
            "osr_email": "dylan@gamerpackaging.com",
        },
        "metadata": {"sprint": "1", "test_payload": True},
    }


@pytest.fixture
def fake_database():
    database = FakeDatabase()
    document_delivery.set_db(database)
    return database


@pytest.mark.asyncio
async def test_standard_sales_order_preflight_is_ready_and_preview_only(fake_database):
    request = document_delivery.DeliveryPreflightRequest(**standard_payload())

    result = await document_delivery.create_preflight_package(request)
    package = result["package"]

    assert result["success"] is True
    assert result["duplicate"] is False
    assert package["status"] == "PREFLIGHT_READY"
    assert package["can_create_email_draft"] is True
    assert package["delivery_enabled"] is False
    assert package["email_send_status"] == "disabled_preview_only"
    assert package["bc_write_status"] == "not_applicable_no_bc_write"
    assert package["sharepoint_write_status"] == "not_applicable_no_sharepoint_write"
    assert package["document"]["report_id"] == 50020
    assert package["document"]["file_name"] == "Sales-Order 114679.pdf"
    assert package["email"]["from"] == "cheryl@gamerpackaging.com"
    assert package["email"]["to"] == ["customer@example.com"]
    assert package["email"]["cc"] == ["dylan@gamerpackaging.com"]
    assert package["archive"]["folder_path"] == "Sales/NATION/Orders/114679"
    assert package["blocking_warning_count"] == 0


@pytest.mark.asyncio
async def test_transfer_order_excludes_sales_copies_and_tiles(fake_database):
    payload = standard_payload()
    payload["correlation_id"] = "bc-transfer-114679-order-confirmation-v1"
    payload["order"]["order_type"] = "TRANSFER_ORDER"
    payload["order"]["is_transfer_order"] = True

    request = document_delivery.DeliveryPreflightRequest(**payload)
    result = await document_delivery.create_preflight_package(request)
    package = result["package"]

    assert package["routing"]["managed_by_department"] == "Logistics/Accounting"
    assert package["routing"]["include_osr"] is False
    assert package["routing"]["include_isr"] is False
    assert package["routing"]["show_in_sales_tiles"] is False
    assert package["email"]["cc"] == []


@pytest.mark.asyncio
async def test_missing_recipient_blocks_preflight(fake_database):
    payload = standard_payload()
    payload["correlation_id"] = "bc-sales-order-114680-order-confirmation-v1"
    payload["document"]["record_no"] = "114680"
    payload["customer"].pop("document_email")

    request = document_delivery.DeliveryPreflightRequest(**payload)
    result = await document_delivery.create_preflight_package(request)
    package = result["package"]

    assert package["status"] == "PREFLIGHT_BLOCKED"
    assert package["can_create_email_draft"] is False
    assert package["blocking_warning_count"] == 1
    assert package["warnings"][0]["code"] == "RECIPIENT_MISSING"


@pytest.mark.asyncio
async def test_same_payload_and_correlation_id_is_idempotent(fake_database):
    request = document_delivery.DeliveryPreflightRequest(**standard_payload())

    first = await document_delivery.create_preflight_package(request)
    second = await document_delivery.create_preflight_package(request)

    assert first["duplicate"] is False
    assert second["duplicate"] is True
    assert first["package"]["package_id"] == second["package"]["package_id"]
    assert len(fake_database.zetadocs_delivery_packages.documents) == 1


@pytest.mark.asyncio
async def test_correlation_id_collision_with_changed_payload_returns_409(fake_database):
    original = standard_payload()
    changed = deepcopy(original)
    changed["order"]["external_document_no"] = "DIFFERENT PO"

    await document_delivery.create_preflight_package(
        document_delivery.DeliveryPreflightRequest(**original)
    )

    with pytest.raises(HTTPException) as exc_info:
        await document_delivery.create_preflight_package(
            document_delivery.DeliveryPreflightRequest(**changed)
        )

    assert exc_info.value.status_code == 409


@pytest.mark.asyncio
async def test_wrong_report_id_is_rejected(fake_database):
    payload = standard_payload()
    payload["correlation_id"] = "bc-sales-order-wrong-report-v1"
    payload["document"]["report_id"] = 1305

    request = document_delivery.DeliveryPreflightRequest(**payload)

    with pytest.raises(HTTPException) as exc_info:
        await document_delivery.create_preflight_package(request)

    assert exc_info.value.status_code == 422
    assert "50020" in str(exc_info.value.detail)
