import pytest

import services.bc_document_identity_service as identity


class _FakeResponse:
    def __init__(self, matches):
        self._matches = matches

    def raise_for_status(self):
        return None

    def json(self):
        return {"value": self._matches}


class _FakeClient:
    matches = []
    last_url = None
    last_params = None

    def __init__(self, *args, **kwargs):
        pass

    async def __aenter__(self):
        return self

    async def __aexit__(self, exc_type, exc, tb):
        return False

    async def get(self, url, headers=None, params=None):
        type(self).last_url = url
        type(self).last_params = params
        return _FakeResponse(type(self).matches)


@pytest.fixture(autouse=True)
def _configure(monkeypatch):
    monkeypatch.setattr(identity, "HAS_CREDENTIALS", True)

    async def fake_token():
        return "token"

    async def fake_company_id(environment=None):
        assert environment == "Sandbox_NoZetadocs_UAT"
        return "company-id"

    monkeypatch.setattr(identity, "_get_token", fake_token)
    monkeypatch.setattr(identity, "_get_company_id_standard_api", fake_company_id)
    monkeypatch.setattr(identity.httpx, "AsyncClient", _FakeClient)
    _FakeClient.matches = []
    _FakeClient.last_url = None
    _FakeClient.last_params = None


@pytest.mark.asyncio
async def test_resolves_exact_system_id_in_write_environment():
    _FakeClient.matches = [{"id": "11111111-2222-3333-4444-555555555555", "number": "PO123"}]

    result = await identity.resolve_bc_document_system_id(
        "purchaseOrders", "PO123", environment="Sandbox_NoZetadocs_UAT"
    )

    assert result["bc_system_id"] == "11111111-2222-3333-4444-555555555555"
    assert result["bc_document_no"] == "PO123"
    assert "/Sandbox_NoZetadocs_UAT/api/v2.0/companies(company-id)/purchaseOrders" in _FakeClient.last_url
    assert _FakeClient.last_params["$filter"] == "number eq 'PO123'"
    assert _FakeClient.last_params["$top"] == "2"


@pytest.mark.asyncio
async def test_fails_closed_when_record_not_found():
    with pytest.raises(LookupError, match="was not found"):
        await identity.resolve_bc_document_system_id(
            "purchaseInvoices", "PI404", environment="Sandbox_NoZetadocs_UAT"
        )


@pytest.mark.asyncio
async def test_fails_closed_when_record_is_ambiguous():
    _FakeClient.matches = [
        {"id": "a", "number": "123"},
        {"id": "b", "number": "123"},
    ]

    with pytest.raises(LookupError, match="ambiguous"):
        await identity.resolve_bc_document_system_id(
            "purchaseOrders", "123", environment="Sandbox_NoZetadocs_UAT"
        )


@pytest.mark.asyncio
async def test_rejects_unsupported_entity_before_calling_bc():
    with pytest.raises(ValueError, match="Unsupported BC document entity"):
        await identity.resolve_bc_document_system_id(
            "vendors", "V100", environment="Sandbox_NoZetadocs_UAT"
        )


@pytest.mark.asyncio
async def test_odata_escapes_document_number():
    _FakeClient.matches = [{"id": "id-1", "number": "A'B"}]

    await identity.resolve_bc_document_system_id(
        "purchaseOrders", "A'B", environment="Sandbox_NoZetadocs_UAT"
    )

    assert _FakeClient.last_params["$filter"] == "number eq 'A''B'"
