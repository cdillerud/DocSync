"""Regression coverage for routes/zetadocs_mirror.py.

Previously had zero test coverage even though it's watched by the Sprint 1
CI workflow's trigger paths -- a change here would run the CI job, but the
job only ever executed test_document_delivery_preflight.py, so nothing in
this file was ever actually exercised by a test. All calls below use the
default live_bc=False (offline preview) path, so no real network/BC calls
are made.
"""

from copy import deepcopy

import pytest

from routes import zetadocs_mirror


class FakeCursor:
    def __init__(self, documents):
        self._documents = documents

    def sort(self, key, direction=1):
        self._documents = sorted(
            self._documents, key=lambda d: d.get(key), reverse=(direction == -1)
        )
        return self

    def limit(self, n):
        self._documents = self._documents[:n]
        return self

    async def to_list(self, _n):
        return [deepcopy(d) for d in self._documents]


class FakeCollection:
    def __init__(self):
        self.documents = []

    async def find_one(self, query, projection=None):
        for document in self.documents:
            if all(document.get(k) == v for k, v in query.items()):
                result = deepcopy(document)
                if projection and projection.get("_id") == 0:
                    result.pop("_id", None)
                return result
        return None

    def find(self, query, projection=None):
        matched = [
            deepcopy(d) for d in self.documents
            if all(d.get(k) == v for k, v in query.items())
        ]
        if projection and projection.get("_id") == 0:
            for d in matched:
                d.pop("_id", None)
        return FakeCursor(matched)

    async def insert_one(self, document):
        stored = deepcopy(document)
        stored.setdefault("_id", f"fake-{len(self.documents)}")
        self.documents.append(stored)
        return stored


class FakeDatabase:
    def __init__(self):
        self.zetadocs_delivery_packages = FakeCollection()


@pytest.fixture
def fake_database():
    database = FakeDatabase()
    zetadocs_mirror.set_db(database)
    return database


async def create_package(order_no="114679", **overrides):
    kwargs = dict(
        order_no=order_no,
        live_bc=False,
        recipient_override=None,
        sender_override=None,
        organization_override=None,
        external_doc_no_override=None,
        source_document_type="ORDER_CONFIRMATION",
        source_order_type="SALES_ORDER",
        managed_by_department=None,
        customer_no=None,
        sell_to_customer_no=None,
        bill_to_customer_no=None,
        ship_to_customer_no=None,
        is_transfer_order=None,
        internal_customer=None,
        include_osr=None,
        include_isr=None,
        show_in_sales_tiles=None,
        created_by="gpi-hub-preview",
        notes=None,
    )
    kwargs.update(overrides)
    return await zetadocs_mirror.create_order_confirmation_delivery_package_preview(**kwargs)


@pytest.mark.asyncio
async def test_preview_endpoint_is_offline_and_send_disabled(fake_database):
    result = await zetadocs_mirror.preview_order_confirmation(
        order_no="114679",
        live_bc=False,
        recipient_override=None,
        sender_override=None,
        organization_override=None,
        external_doc_no_override=None,
        source_document_type="ORDER_CONFIRMATION",
        source_order_type="SALES_ORDER",
        managed_by_department=None,
        customer_no=None,
        sell_to_customer_no=None,
        bill_to_customer_no=None,
        ship_to_customer_no=None,
        is_transfer_order=None,
        internal_customer=None,
        include_osr=None,
        include_isr=None,
        show_in_sales_tiles=None,
    )

    assert result["success"] is True
    assert result["mode"] == "preview_only_no_send_no_write"
    assert result["live_bc"] is False
    assert result["order_no"] == "114679"
    assert result["zetadocs"]["report_id"] == 50020


@pytest.mark.asyncio
async def test_delivery_package_preview_creates_send_disabled_record(fake_database):
    result = await create_package(order_no="114679")

    assert result["success"] is True
    assert result["delivery_enabled"] is False
    assert result["email_send_status"] == "disabled_preview_only"
    assert result["bc_write_status"] == "not_applicable_no_bc_write"
    assert result["package_id"]
    assert len(fake_database.zetadocs_delivery_packages.documents) == 1


@pytest.mark.asyncio
async def test_get_delivery_package_returns_created_package(fake_database):
    created = await create_package(order_no="114679")
    package_id = created["package_id"]

    fetched = await zetadocs_mirror.get_delivery_package(package_id)

    assert fetched["success"] is True
    assert fetched["package"]["package_id"] == package_id
    assert fetched["package"]["order_no"] == "114679"


@pytest.mark.asyncio
async def test_get_delivery_package_404s_for_unknown_id(fake_database):
    with pytest.raises(Exception) as exc_info:
        await zetadocs_mirror.get_delivery_package("does-not-exist")

    assert getattr(exc_info.value, "status_code", None) == 404


@pytest.mark.asyncio
async def test_list_delivery_packages_filters_by_order_no(fake_database):
    await create_package(order_no="114679")
    await create_package(order_no="999999")

    result = await zetadocs_mirror.list_order_confirmation_delivery_packages(
        order_no="114679", limit=25
    )

    assert result["success"] is True
    assert result["count"] == 1
    assert result["packages"][0]["order_no"] == "114679"


@pytest.mark.asyncio
async def test_transfer_order_excludes_osr_isr_and_sales_tiles(fake_database):
    result = await create_package(
        order_no="114679",
        source_order_type="TRANSFER_ORDER",
        is_transfer_order=True,
    )

    routing = result["package"]["routing_context"]
    assert routing["is_transfer_order"] is True
    assert routing["include_osr"] is False
    assert routing["include_isr"] is False
    assert routing["show_in_sales_tiles"] is False
