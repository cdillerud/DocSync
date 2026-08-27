import pytest

import services.sharepoint_service as sharepoint
from services.sharepoint_write_guard_service import SharePointProductionWriteBlocked


def _force_production(monkeypatch):
    monkeypatch.setattr(sharepoint, "SHAREPOINT_TARGET", "production")
    monkeypatch.setattr(sharepoint, "SHAREPOINT_SITE_PATH", "/sites/GamerAccounting")
    monkeypatch.setenv("SHAREPOINT_BLOCK_PRODUCTION_WRITES", "true")


def _forbid_token(monkeypatch):
    calls = {"count": 0}

    async def forbidden_token():
        calls["count"] += 1
        raise AssertionError("Graph token acquisition must not occur for blocked Production write")

    monkeypatch.setattr(sharepoint, "_get_graph_token", forbidden_token)
    return calls


@pytest.mark.asyncio
async def test_production_upload_blocked_before_token_or_network(monkeypatch):
    _force_production(monkeypatch)
    calls = _forbid_token(monkeypatch)

    with pytest.raises(SharePointProductionWriteBlocked):
        await sharepoint.upload_to_sharepoint(b"pdf", "invoice.pdf", "AP_Invoices")

    assert calls["count"] == 0


@pytest.mark.asyncio
async def test_production_metadata_patch_blocked_before_token_or_network(monkeypatch):
    _force_production(monkeypatch)
    calls = _forbid_token(monkeypatch)

    with pytest.raises(SharePointProductionWriteBlocked):
        await sharepoint.write_sharepoint_parity_metadata(
            "drive-1", "item-1", {"ImportReady": True}
        )

    assert calls["count"] == 0


@pytest.mark.asyncio
async def test_production_sharing_link_blocked_before_token_or_network(monkeypatch):
    _force_production(monkeypatch)
    calls = _forbid_token(monkeypatch)

    with pytest.raises(SharePointProductionWriteBlocked):
        await sharepoint.create_sharing_link("drive-1", "item-1")

    assert calls["count"] == 0


@pytest.mark.asyncio
async def test_production_folder_creation_blocked_before_token_or_network(monkeypatch):
    _force_production(monkeypatch)
    calls = _forbid_token(monkeypatch)

    with pytest.raises(SharePointProductionWriteBlocked):
        await sharepoint.ensure_sharepoint_folder_exists("General/AP")

    assert calls["count"] == 0


@pytest.mark.asyncio
async def test_uat_mock_write_remains_available_with_production_block(monkeypatch):
    monkeypatch.setattr(sharepoint, "SHAREPOINT_TARGET", "test")
    monkeypatch.setattr(sharepoint, "SHAREPOINT_SITE_PATH", "/sites/GPI-DocumentHub-Test")
    monkeypatch.setattr(sharepoint, "DEMO_MODE", True)
    monkeypatch.setenv("SHAREPOINT_BLOCK_PRODUCTION_WRITES", "true")

    result = await sharepoint.upload_to_sharepoint(b"pdf", "invoice.pdf", "AP_Invoices")

    assert result["drive_id"].startswith("mock-drive-")
    assert result["name"] == "invoice.pdf"
