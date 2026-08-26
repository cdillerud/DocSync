import pytest

import services.bc_purchase_invoice_posting_service as svc


@pytest.mark.asyncio
async def test_missing_system_id_fails_before_network(monkeypatch):
    called = {"token": False}

    async def fake_token():
        called["token"] = True
        return "token"

    monkeypatch.setattr(svc, "_get_token", fake_token)
    with pytest.raises(ValueError, match="SystemId"):
        await svc.post_purchase_invoice_system_id("")
    assert called["token"] is False


@pytest.mark.asyncio
async def test_true_post_uses_bound_action_and_204_is_success(monkeypatch):
    captured = {}

    monkeypatch.setattr(svc, "HAS_CREDENTIALS", True)
    monkeypatch.setattr(svc, "BC_TENANT_ID", "tenant")
    monkeypatch.setattr(svc, "BC_WRITE_ENVIRONMENT", "Sandbox_NoZetadocs_UAT")

    def fake_guard(operation):
        captured["guard"] = operation

    async def fake_token():
        return "token"

    async def fake_company(environment=None):
        captured["company_environment"] = environment
        return "company-id"

    class Response:
        status_code = 204
        text = ""
        extensions = {"bc_retry": {"attempts": 1, "retry_reasons": []}}

    class Client:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, url, **kwargs):
            captured["url"] = url
            return Response()

    async def fake_retry(send, *, op, max_attempts=None):
        captured["retry_op"] = op
        return await send()

    monkeypatch.setattr(svc, "_check_write_protection", fake_guard)
    monkeypatch.setattr(svc, "_get_token", fake_token)
    monkeypatch.setattr(svc, "_resolve_company_id", fake_company)
    monkeypatch.setattr(svc.httpx, "AsyncClient", Client)
    monkeypatch.setattr(svc, "bc_http_with_retry", fake_retry)

    result = await svc.post_purchase_invoice_system_id("system-id")

    assert captured["guard"] == "post_purchase_invoice"
    assert captured["company_environment"] == "Sandbox_NoZetadocs_UAT"
    assert captured["retry_op"] == "post_purchase_invoice"
    assert captured["url"].endswith(
        "/companies(company-id)/purchaseInvoices(system-id)/Microsoft.NAV.post"
    )
    assert result["posted"] is True
    assert result["http_status"] == 204
    assert result["recovery_verified"] is False


@pytest.mark.asyncio
async def test_non_success_response_is_not_reported_posted(monkeypatch):
    monkeypatch.setattr(svc, "HAS_CREDENTIALS", True)
    monkeypatch.setattr(svc, "BC_TENANT_ID", "tenant")
    monkeypatch.setattr(svc, "BC_WRITE_ENVIRONMENT", "Sandbox_NoZetadocs_UAT")
    monkeypatch.setattr(svc, "_check_write_protection", lambda operation: None)

    async def fake_token():
        return "token"

    async def fake_company(environment=None):
        return "company-id"

    class Response:
        status_code = 422
        text = "cannot post"
        extensions = {}

    class VerifyResponse:
        status_code = 404

    class Client:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, url, **kwargs):
            return Response()
        async def get(self, url, **kwargs):
            return VerifyResponse()

    async def fake_retry(send, *, op, max_attempts=None):
        return await send()

    monkeypatch.setattr(svc, "_get_token", fake_token)
    monkeypatch.setattr(svc, "_resolve_company_id", fake_company)
    monkeypatch.setattr(svc.httpx, "AsyncClient", Client)
    monkeypatch.setattr(svc, "bc_http_with_retry", fake_retry)

    with pytest.raises(RuntimeError, match="HTTP 422"):
        await svc.post_purchase_invoice_system_id("system-id")


@pytest.mark.asyncio
async def test_repeat_post_rejection_recovers_when_bc_proves_invoice_is_posted(monkeypatch):
    captured = {"verify_url": None}
    monkeypatch.setattr(svc, "HAS_CREDENTIALS", True)
    monkeypatch.setattr(svc, "BC_TENANT_ID", "tenant")
    monkeypatch.setattr(svc, "BC_WRITE_ENVIRONMENT", "Sandbox_NoZetadocs_UAT")
    monkeypatch.setattr(svc, "_check_write_protection", lambda operation: None)

    async def fake_token():
        return "token"

    async def fake_company(environment=None):
        return "company-id"

    class PostResponse:
        status_code = 422
        text = "document already posted"
        extensions = {}

    class VerifyResponse:
        status_code = 200

    class Client:
        def __init__(self, *args, **kwargs):
            pass
        async def __aenter__(self):
            return self
        async def __aexit__(self, *args):
            return False
        async def post(self, url, **kwargs):
            return PostResponse()
        async def get(self, url, **kwargs):
            captured["verify_url"] = url
            return VerifyResponse()

    async def fake_retry(send, *, op, max_attempts=None):
        return await send()

    monkeypatch.setattr(svc, "_get_token", fake_token)
    monkeypatch.setattr(svc, "_resolve_company_id", fake_company)
    monkeypatch.setattr(svc.httpx, "AsyncClient", Client)
    monkeypatch.setattr(svc, "bc_http_with_retry", fake_retry)

    result = await svc.post_purchase_invoice_system_id("system-id")

    assert result["posted"] is True
    assert result["recovery_verified"] is True
    assert captured["verify_url"].endswith(
        "/companies(company-id)/purchaseInvoices(system-id)/pdfDocument"
    )
