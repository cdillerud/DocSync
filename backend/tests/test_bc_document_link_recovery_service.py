import pytest

import services.bc_document_link_recovery_service as recovery


class _Collection:
    def __init__(self, doc):
        self.doc = dict(doc)
        self.updates = []

    async def find_one(self, query, projection=None):
        if query.get("id") == self.doc.get("id"):
            return dict(self.doc)
        return None

    async def update_one(self, query, update):
        self.updates.append(update["$set"])
        self.doc.update(update["$set"])


class _DB:
    def __init__(self, doc):
        self.hub_documents = _Collection(doc)


def _base_doc():
    return {
        "id": "doc-1",
        "bc_entity_type": "purchaseOrders",
        "bc_document_no": "PO100",
        "bc_system_id": "11111111-2222-3333-4444-555555555555",
        "sharepoint_web_url": "https://contoso.sharepoint.com/doc.pdf",
        "sharepoint_drive_id": "drive-1",
        "sharepoint_item_id": "item-1",
        "uploaded_by": "BC Drop",
        "delivery_status": "bc_link_failed",
        "import_ready": False,
    }


def _install_metadata_success(monkeypatch, seen=None):
    async def finalize(doc_id, db, doc, system_id):
        if seen is not None:
            seen.append((doc_id, system_id, doc.get("sharepoint_item_id")))
        return {
            "GPI_SourceSystemId": system_id,
            "GPI_Status": "ImportReady",
            "ImportReady": True,
        }

    monkeypatch.setattr(recovery, "_finalize_existing_item_metadata", finalize)


@pytest.mark.asyncio
async def test_recovery_reuses_existing_link_without_creating_duplicate(monkeypatch):
    db = _DB(_base_doc())
    monkeypatch.setattr(recovery, "get_db", lambda: db)
    metadata_seen = []
    _install_metadata_success(monkeypatch, metadata_seen)

    async def existing(*args, **kwargs):
        return {"id": "link-1", "sharePointItemId": "item-1"}

    async def should_not_create(**kwargs):
        raise AssertionError("create_gpi_document_link must not run when link already exists")

    monkeypatch.setattr(recovery, "_find_existing_link", existing)
    monkeypatch.setattr(recovery, "create_gpi_document_link", should_not_create)

    result = await recovery.recover_bc_document_link("doc-1")

    assert result["success"] is True
    assert result["already_linked"] is True
    assert result["metadata_recovered"] is True
    assert result["delivery_status"] == "ImportReady"
    assert db.hub_documents.doc["import_ready"] is True
    assert db.hub_documents.doc["ImportReady"] is True
    assert metadata_seen == [
        ("doc-1", "11111111-2222-3333-4444-555555555555", "item-1")
    ]


@pytest.mark.asyncio
async def test_recovery_creates_only_missing_link(monkeypatch):
    db = _DB(_base_doc())
    monkeypatch.setattr(recovery, "get_db", lambda: db)
    _install_metadata_success(monkeypatch)

    async def none_found(*args, **kwargs):
        return None

    seen = {}

    async def create_link(**kwargs):
        seen.update(kwargs)
        return {"success": True, "id": "new-link"}

    monkeypatch.setattr(recovery, "_find_existing_link", none_found)
    monkeypatch.setattr(recovery, "create_gpi_document_link", create_link)

    result = await recovery.recover_bc_document_link("doc-1")

    assert result["success"] is True
    assert result["already_linked"] is False
    assert result["metadata_recovered"] is True
    assert seen["bc_system_id"] == "11111111-2222-3333-4444-555555555555"
    assert seen["sharepoint_item_id"] == "item-1"
    assert db.hub_documents.doc["delivery_status"] == "ImportReady"
    assert db.hub_documents.doc["ImportReady"] is True


@pytest.mark.asyncio
async def test_recovery_resolves_missing_system_id_without_upload(monkeypatch):
    doc = _base_doc()
    doc["bc_system_id"] = ""
    db = _DB(doc)
    monkeypatch.setattr(recovery, "get_db", lambda: db)
    metadata_seen = []
    _install_metadata_success(monkeypatch, metadata_seen)

    async def resolve(entity, number):
        assert entity == "purchaseOrders"
        assert number == "PO100"
        return {"bc_system_id": "11111111-aaaa-bbbb-cccc-222222222222"}

    async def none_found(*args, **kwargs):
        return None

    async def create_link(**kwargs):
        assert kwargs["bc_system_id"] == "11111111-aaaa-bbbb-cccc-222222222222"
        return {"success": True}

    monkeypatch.setattr(recovery, "resolve_bc_document_system_id", resolve)
    monkeypatch.setattr(recovery, "_find_existing_link", none_found)
    monkeypatch.setattr(recovery, "create_gpi_document_link", create_link)

    result = await recovery.recover_bc_document_link("doc-1")

    assert result["bc_system_id"] == "11111111-aaaa-bbbb-cccc-222222222222"
    assert result["delivery_status"] == "ImportReady"
    assert db.hub_documents.doc["import_ready"] is True
    assert metadata_seen[0][1] == "11111111-aaaa-bbbb-cccc-222222222222"


@pytest.mark.asyncio
async def test_failed_relink_stays_not_import_ready_and_skips_metadata(monkeypatch):
    db = _DB(_base_doc())
    monkeypatch.setattr(recovery, "get_db", lambda: db)

    async def none_found(*args, **kwargs):
        return None

    async def create_link(**kwargs):
        return {"success": False, "error": "BC unavailable"}

    async def should_not_finalize(*args, **kwargs):
        raise AssertionError("metadata must not finalize when the BC link failed")

    monkeypatch.setattr(recovery, "_find_existing_link", none_found)
    monkeypatch.setattr(recovery, "create_gpi_document_link", create_link)
    monkeypatch.setattr(recovery, "_finalize_existing_item_metadata", should_not_finalize)

    result = await recovery.recover_bc_document_link("doc-1")

    assert result["success"] is False
    assert db.hub_documents.doc["delivery_status"] == "bc_link_failed"
    assert db.hub_documents.doc["import_ready"] is False
    assert db.hub_documents.doc["ImportReady"] is False
    assert db.hub_documents.doc["bc_link_error"] == "BC unavailable"
