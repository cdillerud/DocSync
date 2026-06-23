import pytest

import services.sales_order_bc_lookup as lookup_module
import services.sales_order_enrichment_runtime as runtime


class FakeResponse:
    status_code = 200
    text = ""

    def __init__(self, values):
        self._values = values

    def json(self):
        return {"value": self._values}


class FakeClient:
    def __init__(self, captured, values):
        self.captured = captured
        self.values = values

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None, params=None):
        self.captured["url"] = url
        self.captured["headers"] = headers
        self.captured["params"] = params
        return FakeResponse(self.values)


class FakeBCService:
    use_mock = False

    async def _get_company_id(self):
        return "company-id"


@pytest.mark.asyncio
async def test_live_lookup_can_search_by_external_reference_without_customer(
    monkeypatch,
):
    captured = {}
    values = [
        {
            "id": "bc-order-id",
            "number": "SO-12345",
            "customerNumber": "C10000",
            "externalDocumentNumber": "111169",
            "status": "Open",
        }
    ]

    async def fake_token():
        return "token"

    monkeypatch.setattr(lookup_module, "get_bc_token", fake_token)
    monkeypatch.setattr(
        lookup_module.httpx,
        "AsyncClient",
        lambda timeout=None: FakeClient(captured, values),
    )

    result = await lookup_module.find_existing_bc_sales_order(
        FakeBCService(),
        customer_number="",
        external_document_number="111169",
    )

    assert captured["params"]["$filter"] == (
        "externalDocumentNumber eq '111169'"
    )
    assert result["number"] == "SO-12345"
    assert result["lookupMatchedCustomer"] is False
    assert result["multipleMatches"] is False


@pytest.mark.asyncio
async def test_runtime_live_lookup_resolves_customer_after_cache_miss(
    monkeypatch,
):
    enriched = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "extracted_fields": {"customer_po_no": "111169"},
    }
    evidence = {"existing_order": None, "warnings": []}

    async def fake_lookup(
        service,
        *,
        customer_number,
        external_document_number,
    ):
        assert customer_number == ""
        assert external_document_number == "111169"
        return {
            "id": "bc-order-id",
            "number": "SO-12345",
            "customerNumber": "C10000",
            "externalDocumentNumber": "111169",
            "status": "Open",
            "lookupMatchedCustomer": False,
            "multipleMatches": False,
        }

    service = object()

    def optional_attr(module_name, attribute):
        values = {
            (
                "services.sales_order_bc_lookup",
                "find_existing_bc_sales_order",
            ): fake_lookup,
            (
                "services.business_central_service",
                "get_bc_service",
            ): lambda: service,
        }
        return values.get((module_name, attribute))

    monkeypatch.setattr(runtime, "_optional_attr", optional_attr)

    await runtime._lookup_live_existing_order(enriched, evidence)

    assert enriched["bc_customer_no"] == "C10000"
    assert enriched["resolved_customer"]["displayName"] == ""
    assert evidence["existing_order"]["bc_order_number"] == "SO-12345"
    assert evidence["existing_order"]["source"] == "bc_api"
    assert evidence["live_bc_lookup"]["matched"] is True


@pytest.mark.asyncio
async def test_ambiguous_reference_does_not_hydrate_customer(monkeypatch):
    enriched = {
        "document_id": "doc-1",
        "document_type": "Sales_Order",
        "extracted_fields": {"customer_po_no": "111169"},
    }
    evidence = {"existing_order": None, "warnings": []}

    async def fake_lookup(service, **kwargs):
        return {
            "id": "bc-order-id",
            "number": "SO-12345",
            "customerNumber": "C10000",
            "externalDocumentNumber": "111169",
            "status": "Open",
            "lookupMatchedCustomer": False,
            "multipleMatches": True,
        }

    def optional_attr(module_name, attribute):
        if attribute == "find_existing_bc_sales_order":
            return fake_lookup
        if attribute == "get_bc_service":
            return lambda: object()
        return None

    monkeypatch.setattr(runtime, "_optional_attr", optional_attr)

    await runtime._lookup_live_existing_order(enriched, evidence)

    assert enriched.get("bc_customer_no") is None
    assert evidence["ambiguous_existing_order"] is True
    assert evidence["live_bc_lookup"]["matched"] is True
    assert evidence["warnings"]
