import pytest

import services.bc_document_link_recovery_service as recovery


class FakeCollection:
    def __init__(self, document):
        self.document = dict(document)
        self.updates = []

    async def find_one(self, query, projection=None):
        return dict(self.document) if query.get("id") == self.document.get("id") else None

    async def update_one(self, query, update):
        self.updates.append((query, update))
        self.document.update(update.get("$set", {}))


class FakeDB:
    def __init__(self, document):
        self.hub_documents = FakeCollection(document)


def _bc_drop_doc():
    return {
        "id": "doc-1",
        "source": "bc_drop",
        "bc_entity_type": "purchaseInvoices",
        "bc_document_no": "PI-100",
        "bc_system_id": "11111111-1111-1111-1111-111111111111",
        "bc_source_table_id": 38,
        "bc_source_document_type": "Purchase Invoice",
        "sharepoint_drive_id": "drive-1",
        "sharepoint_item_id": "item-1",
        "sharepoint_web_url": "https://contoso.sharepoint.com/doc.pdf",
        "sharepoint_folder_path": "AP/Vendor",
        "file_name": "doc.pdf",
        "uploaded_by": "tester",
        "delivery_status": "bc_link_failed",
        "import_ready": False,
    }


@pytest.mark.asyncio
async def test_bc_drop_metadata_recovery_patches_existing_item_ready(monkeypatch):
    doc = _bc_drop_doc()
    db = FakeDB(doc)
    calls = []

    async def fake_write(document, *, ready):
        calls.append((dict(document), ready))
        return {
            "GPI_SourceSystemId": document["bc_system_id"],
            "GPI_Status": "ImportReady",
            "ImportReady": True,
        }

    import services.bc_drop_parity_metadata_service as metadata_service
    monkeypatch.setattr(metadata_service, "write_bc_drop_parity_metadata", fake_write)

    result = await recovery._finalize_existing_item_metadata(
        "doc-1", db, doc, doc["bc_system_id"]
    )

    assert calls and calls[0][1] is True
    assert calls[0][0]["sharepoint_drive_id"] == "drive-1"
    assert calls[0][0]["sharepoint_item_id"] == "item-1"
    assert result["ImportReady"] is True
    assert db.hub_documents.document["sharepoint_metadata_error"] is None


@pytest.mark.asyncio
async def test_recovery_metadata_failure_never_marks_import_ready(monkeypatch):
    doc = _bc_drop_doc()
    db = FakeDB(doc)

    monkeypatch.setattr(recovery, "get_db", lambda: db)

    async def fake_find_existing(*args, **kwargs):
        return {"id": "existing-link"}

    async def fake_finalize(*args, **kwargs):
        raise RuntimeError("metadata patch failed")

    monkeypatch.setattr(recovery, "_find_existing_link", fake_find_existing)
    monkeypatch.setattr(recovery, "_finalize_existing_item_metadata", fake_finalize)

    result = await recovery.recover_bc_document_link("doc-1")

    assert result["success"] is False
    assert result["bc_link_recovered"] is True
    assert result["metadata_recovered"] is False
    assert result["delivery_status"] == "bc_link_recovered_metadata_failed"
    assert db.hub_documents.document["import_ready"] is False
    assert db.hub_documents.document["ImportReady"] is False


@pytest.mark.asyncio
async def test_recovery_success_becomes_ready_only_after_metadata(monkeypatch):
    doc = _bc_drop_doc()
    db = FakeDB(doc)
    sequence = []

    monkeypatch.setattr(recovery, "get_db", lambda: db)

    async def fake_find_existing(*args, **kwargs):
        sequence.append("link")
        return {"id": "existing-link"}

    async def fake_finalize(*args, **kwargs):
        sequence.append("metadata")
        return {"GPI_Status": "ImportReady", "ImportReady": True}

    monkeypatch.setattr(recovery, "_find_existing_link", fake_find_existing)
    monkeypatch.setattr(recovery, "_finalize_existing_item_metadata", fake_finalize)

    result = await recovery.recover_bc_document_link("doc-1")

    assert sequence == ["link", "metadata"]
    assert result["success"] is True
    assert result["metadata_recovered"] is True
    assert result["delivery_status"] == "ImportReady"
    assert db.hub_documents.document["import_ready"] is True
    assert db.hub_documents.document["ImportReady"] is True
