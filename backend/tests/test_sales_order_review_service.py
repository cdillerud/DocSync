import pytest

from services.sales_order_review_service import (
    approve_candidate,
    create_draft_order,
    run_shadow_preflight,
)


class FakeUpdateResult:
    modified_count = 1


class FakeCollection:
    def __init__(self, documents=None):
        self.documents = documents or []

    async def find_one(self, query, projection=None):
        for document in self.documents:
            if self._matches(document, query):
                return dict(document)
        return None

    async def update_one(self, selector, update):
        for document in self.documents:
            if self._matches(document, selector):
                document.update(update.get("$set") or {})
                return FakeUpdateResult()
        return FakeUpdateResult()

    @staticmethod
    def _matches(document, query):
        if "$or" in query:
            return any(
                FakeCollection._matches(document, clause)
                for clause in query["$or"]
            )

        for key, expected in query.items():
            if key.startswith("$"):
                continue
            if document.get(key) != expected:
                return False
        return True


class FakeDatabase:
    def __init__(self, sales_documents=None, hub_documents=None):
        self.sales_documents = FakeCollection(sales_documents)
        self.hub_documents = FakeCollection(hub_documents)


def valid_sales_document(review_status="approved"):
    return {
        "document_id": "sales-doc-1",
        "document_type": "Sales_Order",
        "ai_confidence": 0.98,
        "bc_customer_no": "C10000",
        "extracted_fields": {
            "customer_name": "Example Customer",
            "customer_po_no": "PO-45001",
            "lines": [
                {
                    "bc_item_number": "ITEM-100",
                    "customer_sku": "CUSTOMER-ABC",
                    "quantity": "12",
                    "uom": "CASE",
                    "mapping_status": "approved",
                    "item_match_confidence": 0.99,
                }
            ],
        },
        "sharepoint_web_url": "https://example.sharepoint.com/order.pdf",
        "review_status": review_status,
        "workflow_status": "validated",
    }


@pytest.mark.asyncio
async def test_shadow_preflight_persists_result_on_sales_document():
    document = valid_sales_document()
    db = FakeDatabase(sales_documents=[document])

    result = await run_shadow_preflight(db, "sales-doc-1")

    assert result["can_create"] is True
    assert result["collection"] == "sales_documents"
    assert document["sales_order_preflight"]["can_create"] is True
    assert document["bc_create_ready"] is True
    assert document["sales_order_idempotency_key"]


@pytest.mark.asyncio
async def test_string_false_mapping_approval_does_not_become_truthy():
    document = valid_sales_document()
    line = document["extracted_fields"]["lines"][0]
    line["item_match_confidence"] = 0.40
    line["mapping_approved"] = "false"
    db = FakeDatabase(sales_documents=[document])

    result = await run_shadow_preflight(db, "sales-doc-1")
    codes = {issue["code"] for issue in result["errors"]}

    assert "ITEM_MATCH_CONFIDENCE_LOW" in codes
    assert result["can_create"] is False


@pytest.mark.asyncio
async def test_approval_is_recorded_and_preflight_is_rerun():
    document = valid_sales_document(review_status="needs_review")
    db = FakeDatabase(sales_documents=[document])

    before = await run_shadow_preflight(db, "sales-doc-1")
    assert before["can_create"] is False

    after = await approve_candidate(
        db,
        "sales-doc-1",
        reviewer="Chad Dillerud",
        note="Customer PO reviewed against the source document.",
    )

    assert after["can_create"] is True
    assert document["sales_order_approved"] is True
    assert document["sales_order_approved_by"] == "Chad Dillerud"
    assert document["sales_order_approval_note"]


@pytest.mark.asyncio
async def test_create_draft_stays_in_shadow_mode(monkeypatch):
    document = valid_sales_document()
    db = FakeDatabase(sales_documents=[document])
    monkeypatch.setenv("AUTO_CREATE_SALES_ORDER_ENABLED", "false")

    class ExplodingBCService:
        use_mock = False

        def __getattr__(self, name):
            raise AssertionError(f"BC must not be called in shadow mode: {name}")

    result = await create_draft_order(
        db,
        ExplodingBCService(),
        "sales-doc-1",
    )

    assert result["success"] is False
    assert result["status"] == "shadow_mode"
    assert result["preflight"]["can_create"] is True
