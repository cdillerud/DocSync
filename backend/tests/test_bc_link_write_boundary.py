"""Parity/safety tests for the Business Central attachment write boundary."""

import pytest

from services import bc_link_service


def test_sales_write_is_disabled_by_default(monkeypatch):
    monkeypatch.setattr(bc_link_service, "BC_SALES_LINK_WRITE_ENABLED", False)
    assert bc_link_service._sales_write_allowed("salesOrders") is False
    assert bc_link_service._sales_write_allowed("purchaseInvoices") is True


def test_write_environment_is_split_write_environment(monkeypatch):
    monkeypatch.setattr(bc_link_service, "BC_WRITE_ENVIRONMENT", "Sandbox_NoZetadocs_UAT")
    monkeypatch.setattr(bc_link_service, "BC_READ_ENVIRONMENT", "Production")
    assert bc_link_service._write_environment() == "Sandbox_NoZetadocs_UAT"


def test_write_boundary_calls_central_production_guard(monkeypatch):
    import services.business_central_service as bc_service

    calls = []

    def fake_guard(operation):
        calls.append(operation)
        raise bc_service.ProductionWriteBlockedError(operation)

    monkeypatch.setattr(bc_service, "_check_write_protection", fake_guard)

    with pytest.raises(bc_service.ProductionWriteBlockedError):
        bc_link_service._check_write_boundary("purchaseInvoices")

    assert calls == ["link_document_to_bc"]


@pytest.mark.asyncio
async def test_production_guard_runs_before_token_or_network(monkeypatch):
    import services.business_central_service as bc_service

    monkeypatch.setattr(bc_link_service, "DEMO_MODE", False)
    monkeypatch.setattr(bc_link_service, "BC_CLIENT_ID", "configured")

    side_effects = []

    async def fake_token():
        side_effects.append("token")
        return "token"

    def fake_guard(operation):
        raise bc_service.ProductionWriteBlockedError(operation)

    monkeypatch.setattr(bc_link_service, "_get_bc_token", fake_token)
    monkeypatch.setattr(bc_service, "_check_write_protection", fake_guard)

    with pytest.raises(bc_service.ProductionWriteBlockedError):
        await bc_link_service.link_document_to_bc(
            bc_record_id="11111111-2222-3333-4444-555555555555",
            share_link="https://example.sharepoint.com/doc.pdf",
            file_name="invoice.pdf",
            file_content=b"pdf",
            bc_entity="purchaseInvoices",
        )

    assert side_effects == []


@pytest.mark.asyncio
async def test_sales_write_fails_before_token_when_lane_disabled(monkeypatch):
    monkeypatch.setattr(bc_link_service, "DEMO_MODE", False)
    monkeypatch.setattr(bc_link_service, "BC_CLIENT_ID", "configured")
    monkeypatch.setattr(bc_link_service, "BC_SALES_LINK_WRITE_ENABLED", False)

    import services.business_central_service as bc_service
    monkeypatch.setattr(bc_service, "_check_write_protection", lambda operation: None)

    side_effects = []

    async def fake_token():
        side_effects.append("token")
        return "token"

    monkeypatch.setattr(bc_link_service, "_get_bc_token", fake_token)

    with pytest.raises(PermissionError, match="Sales attachment writes are disabled"):
        await bc_link_service.link_document_to_bc(
            bc_record_id="aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee",
            share_link="https://example.sharepoint.com/doc.pdf",
            file_name="sales.pdf",
            file_content=b"pdf",
            bc_entity="salesOrders",
        )

    assert side_effects == []


@pytest.mark.asyncio
async def test_multiple_companies_fail_closed_without_explicit_company(monkeypatch):
    monkeypatch.setattr(bc_link_service, "BC_COMPANY_ID", "")
    monkeypatch.setattr(bc_link_service, "BC_COMPANY_NAME", "")
    monkeypatch.setattr(bc_link_service, "TENANT_ID", "tenant")

    class Response:
        status_code = 200
        text = ""

        @staticmethod
        def json():
            return {"value": [{"id": "one"}, {"id": "two"}]}

    class Client:
        async def __aenter__(self):
            return self

        async def __aexit__(self, *args):
            return False

        async def get(self, *args, **kwargs):
            return Response()

    monkeypatch.setattr(bc_link_service.httpx, "AsyncClient", lambda **kwargs: Client())

    with pytest.raises(RuntimeError, match="refusing to guess the write target"):
        await bc_link_service._resolve_company_id("token", "Sandbox_NoZetadocs_UAT")
