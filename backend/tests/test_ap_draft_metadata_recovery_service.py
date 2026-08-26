import pytest

import services.ap_draft_metadata_recovery_service as svc


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
            for key, value in update.get("$set", {}).items():
                self.document[key] = value
            for key, value in update.get("$push", {}).items():
                self.document.setdefault(key, []).append(value)


class FakeDb:
    def __init__(self, document):
        self.hub_documents = FakeCollection(document)


def _pending_doc():
    return {
        "id": "doc-1",
        "status": "DraftNeedsMetadata",
        "bc_purchase_invoice": {
            "bc_record_no": "PI-1001",
            "bc_system_id": "draft-system-id",
        },
        "bc_purchase_invoice_no": "PI-1001",
        "bc_record_no": "PI-1001",
        "bc_system_id": "draft-system-id",
        "bc_record_id": "draft-system-id",
        "ImportReady": False,
        "import_ready": False,
        "delivery_status": "DraftNeedsMetadata",
        "workflow_history": [],
    }


@pytest.mark.asyncio
async def test_draft_metadata_recovery_patches_existing_item_and_restores_ready(monkeypatch):
    db = FakeDb(_pending_doc())
    captured = {}

    async def fake_resync(document_id, db_arg, *, identity_update=None):
        captured["document_id"] = document_id
        captured["identity"] = dict(identity_update or {})
        return {"success": True}

    monkeypatch.setattr(svc, "resync_existing_sharepoint_parity_metadata", fake_resync)

    result = await svc.recover_draft_purchase_invoice_metadata("doc-1", db)

    assert captured["document_id"] == "doc-1"
    assert captured["identity"]["GPI_SourceTableID"] == 38
    assert captured["identity"]["GPI_SourceDocumentType"] == "Purchase Invoice"
    assert captured["identity"]["GPI_SourceSystemId"] == "draft-system-id"
    assert captured["identity"]["GPI_SourceDocumentNo"] == "PI-1001"
    assert captured["identity"]["ImportReady"] is True
    assert result["status"] == "ReadyForPost"
    assert result["import_ready"] is True

    stored = db.hub_documents.document
    assert stored["status"] == "ReadyForPost"
    assert stored["workflow_status"] == "ready_for_post"
    assert stored["GPI_SourceTableID"] == 38
    assert stored["GPI_SourceSystemId"] == "draft-system-id"
    assert stored["ImportReady"] is True
    assert stored["delivery_status"] == "ImportReady"
    assert stored["workflow_history"][-1]["event"] == "draft_metadata_recovered"


@pytest.mark.asyncio
async def test_draft_metadata_failure_leaves_fail_closed_state_unchanged(monkeypatch):
    original = _pending_doc()
    db = FakeDb(original)

    async def fake_resync(*args, **kwargs):
        raise RuntimeError("Graph unavailable")

    monkeypatch.setattr(svc, "resync_existing_sharepoint_parity_metadata", fake_resync)

    with pytest.raises(RuntimeError, match="Graph unavailable"):
        await svc.recover_draft_purchase_invoice_metadata("doc-1", db)

    assert db.hub_documents.update_calls == []
    assert db.hub_documents.document == original


@pytest.mark.asyncio
async def test_draft_metadata_recovery_requires_exact_identity(monkeypatch):
    doc = _pending_doc()
    doc["bc_system_id"] = ""
    doc["bc_record_id"] = ""
    doc["bc_purchase_invoice"]["bc_system_id"] = ""
    db = FakeDb(doc)

    with pytest.raises(svc.DraftMetadataRecoveryError, match="exact BC Purchase Invoice draft identity"):
        await svc.recover_draft_purchase_invoice_metadata("doc-1", db)
    assert db.hub_documents.update_calls == []


@pytest.mark.asyncio
async def test_draft_metadata_recovery_rejects_wrong_state(monkeypatch):
    doc = _pending_doc()
    doc["status"] = "ReadyForPost"
    db = FakeDb(doc)

    with pytest.raises(svc.DraftMetadataRecoveryError, match="DraftNeedsMetadata"):
        await svc.recover_draft_purchase_invoice_metadata("doc-1", db)
    assert db.hub_documents.update_calls == []
