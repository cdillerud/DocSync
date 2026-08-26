import pytest

import services.sharepoint_parity_resync_service as svc


class FakeCollection:
    def __init__(self, document):
        self.document = document.copy() if document else None
        self.update_calls = []

    async def find_one(self, query, projection=None):
        if self.document and self.document.get("id") == query.get("id"):
            return self.document.copy()
        return None

    async def update_one(self, query, update):
        self.update_calls.append((query, update))
        if self.document and self.document.get("id") == query.get("id"):
            self.document.update(update.get("$set", {}))


class FakeDb:
    def __init__(self, document):
        self.hub_documents = FakeCollection(document)


def _base_document():
    return {
        "id": "doc-1",
        "file_name": "original.pdf",
        "original_file_name": "original.pdf",
        "sharepoint_file_name": "109204 Vendor.pdf",
        "sharepoint_folder_path": "Accounting/AP/Invoices",
        "sharepoint_web_url": "https://example/doc.pdf",
        "sharepoint_drive_id": "drive-1",
        "sharepoint_item_id": "item-1",
        "GPI_SourceTableID": 38,
        "GPI_SourceSystemId": "po-system-id",
        "GPI_SourceDocumentType": "Purchase Order",
        "GPI_SourceDocumentNo": "109204",
        "GPI_SourcePartyType": "Vendor",
        "GPI_SourcePartyNo": "V100",
        "GPI_Status": "ImportReady",
        "ImportReady": True,
    }


def test_builder_overlays_final_posted_identity_without_losing_file_traceability():
    metadata = svc.build_existing_item_parity_metadata(
        _base_document(),
        {
            "GPI_SourceTableID": 122,
            "GPI_SourceSystemId": "posted-system-id",
            "GPI_SourceDocumentType": "Posted Purchase Invoice",
            "GPI_SourceDocumentNo": "PPI-9001",
            "GPI_Status": "ImportReady",
            "ImportReady": True,
        },
    )

    assert metadata["GPI_SourceTableID"] == 122
    assert metadata["GPI_SourceSystemId"] == "posted-system-id"
    assert metadata["GPI_SourceDocumentType"] == "Posted Purchase Invoice"
    assert metadata["GPI_SourceDocumentNo"] == "PPI-9001"
    assert metadata["GPI_OriginalFileName"] == "original.pdf"
    assert metadata["GPI_SharePointFileName"] == "109204 Vendor.pdf"
    assert metadata["GPI_SharePointPath"] == "Accounting/AP/Invoices"
    assert metadata["GPI_SharePointURL"] == "https://example/doc.pdf"
    assert metadata["ImportReady"] is True


@pytest.mark.asyncio
async def test_resync_patches_existing_item_only_and_persists_metadata(monkeypatch):
    db = FakeDb(_base_document())
    captured = {}

    async def fake_write(drive_id, item_id, metadata):
        captured.update({"drive_id": drive_id, "item_id": item_id, "metadata": metadata})
        return {"updated": True}

    monkeypatch.setattr(svc, "write_sharepoint_parity_metadata", fake_write)

    result = await svc.resync_existing_sharepoint_parity_metadata(
        "doc-1",
        db,
        identity_update={
            "GPI_SourceTableID": 122,
            "GPI_SourceSystemId": "posted-system-id",
            "GPI_SourceDocumentType": "Posted Purchase Invoice",
            "GPI_SourceDocumentNo": "PPI-9001",
            "GPI_Status": "ImportReady",
            "ImportReady": True,
        },
    )

    assert result["success"] is True
    assert captured["drive_id"] == "drive-1"
    assert captured["item_id"] == "item-1"
    assert captured["metadata"]["GPI_SourceSystemId"] == "posted-system-id"
    assert db.hub_documents.document["sharepoint_parity_metadata"]["GPI_SourceTableID"] == 122
    assert db.hub_documents.document["sharepoint_metadata_error"] is None


@pytest.mark.asyncio
async def test_resync_without_existing_sharepoint_item_fails_closed(monkeypatch):
    doc = _base_document()
    doc["sharepoint_item_id"] = None
    db = FakeDb(doc)
    called = False

    async def fake_write(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(svc, "write_sharepoint_parity_metadata", fake_write)

    with pytest.raises(svc.SharePointParityResyncError, match="no existing SharePoint"):
        await svc.resync_existing_sharepoint_parity_metadata("doc-1", db)
    assert called is False


@pytest.mark.asyncio
async def test_graph_failure_does_not_persist_false_sync_success(monkeypatch):
    db = FakeDb(_base_document())

    async def fake_write(*args, **kwargs):
        raise RuntimeError("Graph rejected metadata")

    monkeypatch.setattr(svc, "write_sharepoint_parity_metadata", fake_write)

    with pytest.raises(RuntimeError, match="Graph rejected"):
        await svc.resync_existing_sharepoint_parity_metadata(
            "doc-1",
            db,
            identity_update={"GPI_SourceSystemId": "posted-system-id", "ImportReady": True},
        )
    assert db.hub_documents.update_calls == []
