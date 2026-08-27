import pytest

import services.bc_posted_purchase_invoice_identity_service as svc


@pytest.mark.asyncio
async def test_maps_api_id_to_real_posted_header_system_id(monkeypatch):
    monkeypatch.setattr(svc, "HAS_CREDENTIALS", True)
    monkeypatch.setattr(svc, "BC_TENANT_ID", "tenant")
    monkeypatch.setattr(svc, "BC_WRITE_ENVIRONMENT", "Sandbox_NoZetadocs_UAT")

    async def fake_token():
        return "token"

    async def fake_company(environment=None):
        assert environment == "Sandbox_NoZetadocs_UAT"
        return "company-id"

    captured = {}

    class Response:
        status_code = 200
        text = ""
        def json(self):
            return {"value": [{
                "id": "posted-system-id",
                "number": "PPI-2001",
                "apiId": "draft-api-id",
            }]}

    class Client:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def get(self, url, **kwargs):
            captured["url"] = url
            captured["params"] = kwargs.get("params")
            return Response()

    monkeypatch.setattr(svc, "_get_token", fake_token)
    monkeypatch.setattr(svc, "_resolve_company_id", fake_company)
    monkeypatch.setattr(svc.httpx, "AsyncClient", Client)

    result = await svc.resolve_posted_purchase_invoice_identity("draft-api-id", max_attempts=1)

    assert result["posted_system_id"] == "posted-system-id"
    assert result["posted_number"] == "PPI-2001"
    assert result["api_id"] == "draft-api-id"
    assert "/api/microsoft/automate/v1.0/companies(company-id)/postedPurchaseInvoices" in captured["url"]
    assert captured["params"]["$filter"] == "apiId eq draft-api-id"


@pytest.mark.asyncio
async def test_zero_matches_fails_closed(monkeypatch):
    monkeypatch.setattr(svc, "HAS_CREDENTIALS", True)

    async def fake_token():
        return "token"

    async def fake_company(environment=None):
        return "company-id"

    class Response:
        status_code = 200
        text = ""
        def json(self):
            return {"value": []}

    class Client:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def get(self, url, **kwargs):
            return Response()

    monkeypatch.setattr(svc, "_get_token", fake_token)
    monkeypatch.setattr(svc, "_resolve_company_id", fake_company)
    monkeypatch.setattr(svc.httpx, "AsyncClient", Client)

    with pytest.raises(svc.PostedPurchaseInvoiceIdentityNotFound):
        await svc.resolve_posted_purchase_invoice_identity("draft-api-id", max_attempts=1)


@pytest.mark.asyncio
async def test_ambiguous_api_id_fails_closed(monkeypatch):
    monkeypatch.setattr(svc, "HAS_CREDENTIALS", True)

    async def fake_token():
        return "token"

    async def fake_company(environment=None):
        return "company-id"

    class Response:
        status_code = 200
        text = ""
        def json(self):
            return {"value": [
                {"id": "posted-1", "number": "PPI-1", "apiId": "draft-api-id"},
                {"id": "posted-2", "number": "PPI-2", "apiId": "draft-api-id"},
            ]}

    class Client:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def get(self, url, **kwargs):
            return Response()

    monkeypatch.setattr(svc, "_get_token", fake_token)
    monkeypatch.setattr(svc, "_resolve_company_id", fake_company)
    monkeypatch.setattr(svc.httpx, "AsyncClient", Client)

    with pytest.raises(svc.PostedPurchaseInvoiceIdentityNotFound, match="Ambiguous"):
        await svc.resolve_posted_purchase_invoice_identity("draft-api-id", max_attempts=1)
