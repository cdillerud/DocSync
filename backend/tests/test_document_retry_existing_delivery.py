import pytest

import services.document_retry_service as retry


@pytest.mark.asyncio
async def test_bc_link_failure_recovers_existing_sharepoint_item_without_bytes(monkeypatch):
    doc = {
        "id": "doc-1",
        "delivery_status": "bc_link_failed",
        "sharepoint_drive_id": "drive-1",
        "sharepoint_item_id": "item-1",
        "sharepoint_web_url": "https://contoso.sharepoint.com/doc.pdf",
    }

    async def recover(doc_id):
        assert doc_id == "doc-1"
        return {
            "success": True,
            "import_ready": True,
            "delivery_status": "delivered",
            "already_linked": False,
        }

    import services.bc_document_link_recovery_service as recovery
    monkeypatch.setattr(recovery, "recover_bc_document_link", recover)

    result = await retry._retry_existing_delivery(None, doc)

    assert result["reused_existing_sharepoint_item"] is True
    assert result["recovered_bc_link"] is True
    assert result["import_ready"] is True
    assert result["drive_id"] == "drive-1"
    assert result["item_id"] == "item-1"


@pytest.mark.asyncio
async def test_existing_sharepoint_metadata_retry_uses_in_place_path(monkeypatch):
    doc = {
        "id": "doc-2",
        "delivery_status": "NeedsSystemId",
        "sharepoint_drive_id": "drive-2",
        "sharepoint_item_id": "item-2",
    }
    seen = {}

    async def in_place(db, passed_doc):
        seen["doc"] = passed_doc
        return {
            "drive_id": "drive-2",
            "item_id": "item-2",
            "delivery_status": "ImportReady",
            "import_ready": True,
            "reused_existing_sharepoint_item": True,
        }

    monkeypatch.setattr(retry, "_retry_existing_sharepoint_item", in_place)

    result = await retry._retry_existing_delivery(object(), doc)

    assert seen["doc"] is doc
    assert result["reused_existing_sharepoint_item"] is True
    assert result["item_id"] == "item-2"


@pytest.mark.asyncio
async def test_failed_bc_recovery_stays_failed(monkeypatch):
    doc = {
        "id": "doc-3",
        "delivery_status": "bc_link_failed",
        "sharepoint_drive_id": "drive-3",
        "sharepoint_item_id": "item-3",
    }

    async def recover(doc_id):
        return {"success": False, "error": "BC unavailable"}

    import services.bc_document_link_recovery_service as recovery
    monkeypatch.setattr(recovery, "recover_bc_document_link", recover)

    with pytest.raises(RuntimeError, match="BC unavailable"):
        await retry._retry_existing_delivery(None, doc)
