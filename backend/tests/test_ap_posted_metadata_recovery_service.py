import pytest

import services.ap_posted_metadata_recovery_service as svc


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


def _pending_metadata_doc():
    return {
        "id": "doc-1",
        "status": "PostedNeedsMetadata",
        "workflow_status": "posted_needs_metadata",
        "bc_posting_status": "posted_needs_metadata",
        "bc_true_post_confirmed": True,
        "bc_api_id": "draft-api-id",
        "bc_record_no": "PPI-9001",
        "bc_purchase_invoice_no": "PPI-9001",
        "bc_system_id": "real-posted-system-id",
        "bc_record_id": "real-posted-system-id",
        "GPI_SourceTableID": 122,
        "GPI_SourceSystemId": "real-posted-system-id",
        "GPI_SourceDocumentNo": "PPI-9001",
        "GPI_Status": "PostedNeedsMetadata",
        "ImportReady": False,
        "import_ready": False,
        "delivery_status": "PostedNeedsMetadata",
        "workflow_history": [],
    }


@pytest.mark.asyncio
async def test_metadata_only_recovery_patches_existing_item_and_finalizes(monkeypatch):
    db = FakeDb(_pending_metadata_doc())
    captured = {}

    async def fake_resync(document_id, db_arg, *, identity_update=None):
        captured["document_id"] = document_id
        captured["identity_update"] = dict(identity_update or {})
        return {"success": True, "item_id": "item-1"}

    monkeypatch.setattr(svc, "resync_existing_sharepoint_parity_metadata", fake_resync)

    result = await svc.recover_posted_purchase_invoice_metadata("doc-1", db)

    assert captured["document_id"] == "doc-1"
    assert captured["identity_update"]["GPI_SourceTableID"] == 122
    assert captured["identity_update"]["GPI_SourceSystemId"] == "real-posted-system-id"
    assert captured["identity_update"]["ImportReady"] is True
    assert result["status"] == "Posted"
    assert result["import_ready"] is True

    stored = db.hub_documents.document
    assert stored["status"] == "Posted"
    assert stored["bc_posting_status"] == "posted"
    assert stored["GPI_SourceSystemId"] == "real-posted-system-id"
    assert stored["ImportReady"] is True
    assert stored["delivery_status"] == "ImportReady"
    assert stored["workflow_history"][-1]["event"] == "posted_metadata_recovered"


@pytest.mark.asyncio
async def test_metadata_recovery_failure_leaves_fail_closed_state(monkeypatch):
    original = _pending_metadata_doc()
    db = FakeDb(original)

    async def fake_resync(*args, **kwargs):
        raise RuntimeError("Graph still unavailable")

    monkeypatch.setattr(svc, "resync_existing_sharepoint_parity_metadata", fake_resync)

    with pytest.raises(RuntimeError, match="Graph still unavailable"):
        await svc.recover_posted_purchase_invoice_metadata("doc-1", db)

    assert db.hub_documents.update_calls == []
    assert db.hub_documents.document == original


@pytest.mark.asyncio
async def test_metadata_recovery_requires_confirmed_post(monkeypatch):
    doc = _pending_metadata_doc()
    doc["bc_true_post_confirmed"] = False
    db = FakeDb(doc)
    called = False

    async def fake_resync(*args, **kwargs):
        nonlocal called
        called = True

    monkeypatch.setattr(svc, "resync_existing_sharepoint_parity_metadata", fake_resync)

    with pytest.raises(svc.PostedMetadataRecoveryError, match="confirmed BC post"):
        await svc.recover_posted_purchase_invoice_metadata("doc-1", db)
    assert called is False
    assert db.hub_documents.update_calls == []


@pytest.mark.asyncio
async def test_metadata_recovery_requires_real_posted_identity(monkeypatch):
    doc = _pending_metadata_doc()
    doc["bc_system_id"] = ""
    doc["bc_record_id"] = ""
    db = FakeDb(doc)

    with pytest.raises(svc.PostedMetadataRecoveryError, match="real posted Purchase Invoice identity"):
        await svc.recover_posted_purchase_invoice_metadata("doc-1", db)
    assert db.hub_documents.update_calls == []
