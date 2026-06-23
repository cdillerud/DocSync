import pytest

import services.sales_order_enrichment as enrichment
import services.sales_order_enrichment_runtime as runtime


class FakeResolution:
    customer_no = "C10000"
    customer_name = "Example Customer"
    match_method = "cache_lookup"
    confidence = 0.98
    source = "bc_cache"

    def to_dict(self):
        return {
            "customer_no": self.customer_no,
            "customer_name": self.customer_name,
            "match_method": self.match_method,
            "confidence": self.confidence,
            "source": self.source,
        }


class FakeUpdateResult:
    modified_count = 1


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = documents or []

    async def find_one(self, query, projection=None):
        for document in self.documents:
            if any(document.get(key) == value for key, value in query.items()):
                return dict(document)
        return None

    async def update_one(self, selector, update):
        for document in self.documents:
            if all(document.get(key) == value for key, value in selector.items()):
                document.update(update.get("$set") or {})
                return FakeUpdateResult()
        return FakeUpdateResult()


class FakeDatabase:
    def __init__(self, sales_documents=None, hub_documents=None):
        self.sales_documents = FakeCollection(sales_documents)
        self.hub_documents = FakeCollection(hub_documents)
        self.catalog = FakeCollection(
            [
                {
                    "item_no": "ITEM-100",
                    "description": "Mapped Item",
                    "base_uom": "CASE",
                    "blocked": False,
                }
            ]
        )

    def __getitem__(self, name):
        return getattr(self, name)


@pytest.mark.asyncio
async def test_existing_resolvers_enrich_customer_item_and_uom(monkeypatch):
    async def no_existing_order(db, po_number, customer_number=""):
        return None, None, []

    async def resolve_customer(doc):
        return FakeResolution()

    async def map_line_to_item(**kwargs):
        return {
            "matched": True,
            "target_type": "item",
            "target_no": "ITEM-100",
            "confidence": 0.98,
            "method": "configured_mapping",
            "mapping_id": "mapping-1",
            "catalog_validated": True,
        }

    def optional_attr(module_name, attribute):
        values = {
            ("services.entity_resolution_service", "resolve_customer"): resolve_customer,
            ("services.item_mapping_service", "map_line_to_item"): map_line_to_item,
            ("services.bc_catalog_sync_service", "ITEMS_COLLECTION"): "catalog",
        }
        return values.get((module_name, attribute))

    monkeypatch.setattr(enrichment, "_find_existing_order", no_existing_order)
    monkeypatch.setattr(enrichment, "_optional_attr", optional_attr)

    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "extracted_fields": {
            "customer_name": "Example Customer",
            "customer_po_no": "PO-100",
            "lines": [
                {
                    "description": "Customer Item Description",
                    "quantity": 12,
                }
            ],
        },
    }

    enriched, evidence = await enrichment.enrich_sales_order_document(
        FakeDatabase(),
        document,
    )

    assert enriched["bc_customer_no"] == "C10000"
    assert enriched["resolved_customer"]["displayName"] == "Example Customer"
    assert enriched["sales_order_lines"][0]["itemNumber"] == "ITEM-100"
    assert enriched["sales_order_lines"][0]["unitOfMeasureCode"] == "CASE"
    assert enriched["sales_order_lines"][0]["mappingStatus"] == "auto_matched"
    assert evidence["line_mappings"][0]["method"] == "configured_mapping"


@pytest.mark.asyncio
async def test_existing_bc_order_supplies_customer_and_line_mapping(monkeypatch):
    existing = {
        "bc_record_id": "bc-order-id",
        "bc_document_no": "SO-12345",
        "bc_external_document_no": "PO-100",
        "bc_customer_no": "C10000",
        "bc_customer_name": "Example Customer",
        "status": "Open",
    }

    async def find_existing(db, po_number, customer_number=""):
        return existing, object(), []

    async def fetch_lines(cache, record):
        return [
            {
                "lineObjectNumber": "ITEM-100",
                "description": "12 ounce printed carton",
                "unitOfMeasureCode": "CASE",
                "unitPrice": 42.50,
            }
        ], None

    monkeypatch.setattr(enrichment, "_find_existing_order", find_existing)
    monkeypatch.setattr(enrichment, "_fetch_bc_order_lines", fetch_lines)
    monkeypatch.setattr(enrichment, "_optional_attr", lambda *args: None)

    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "extracted_fields": {
            "customer_po_no": "PO-100",
            "lines": [
                {
                    "description": "12 ounce printed carton",
                    "quantity": 10,
                }
            ],
        },
    }

    enriched, evidence = await enrichment.enrich_sales_order_document(
        FakeDatabase(),
        document,
    )

    assert enriched["bc_customer_no"] == "C10000"
    assert enriched["sales_order_lines"][0]["itemNumber"] == "ITEM-100"
    assert enriched["sales_order_lines"][0]["unitOfMeasureCode"] == "CASE"
    assert enriched["sales_order_lines"][0]["itemMatchConfidence"] == 0.99
    assert evidence["existing_order"]["bc_order_number"] == "SO-12345"
    assert evidence["existing_order_lines_checked"] == 1


@pytest.mark.asyncio
async def test_duplicate_validation_message_is_idempotent(monkeypatch):
    document = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "validation_errors": ["Keep this validation error"],
    }
    db = FakeDatabase(sales_documents=[document])

    async def fake_enrich(db, source):
        enriched = dict(source)
        enriched["sales_order_lines"] = []
        evidence = {
            "existing_order": {"bc_order_number": "SO-12345"},
            "line_mappings": [],
            "warnings": [],
        }
        return enriched, evidence

    monkeypatch.setattr(runtime, "enrich_sales_order_document", fake_enrich)

    await runtime.enrich_and_persist_sales_order_document(db, "doc-1")
    await runtime.enrich_and_persist_sales_order_document(db, "doc-1")

    duplicate_messages = [
        value
        for value in document["validation_errors"]
        if str(value).startswith(runtime._EXISTING_ORDER_ERROR_PREFIX)
    ]
    assert document["validation_errors"][0] == "Keep this validation error"
    assert len(duplicate_messages) == 1
