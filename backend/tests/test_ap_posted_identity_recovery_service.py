import pytest

import services.ap_posted_identity_recovery_service as svc


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


@pytest.mark.asyncio
async def test_identity_only_recovery_uses_api_id_and_makes_document_ready(monkeypatch):
    db = FakeDb({
        "id": "doc-1",
        "status": "PostedNeedsIdentity",
        "workflow_status": "posted_needs_identity",
        "bc_posting_status": "posted_needs_identity",
        "bc_true_post_confirmed": True,
        "bc_api_id": "draft-api-id",
        "bc_draft_invoice_no": "PI-DRAFT-1",
        "workflow_history": [],
    })
    captured = {}

    async def fake_resolve(api_id):
        captured["api_id"] = api_id
        return {
            "posted_system_id": "real-posted-system-id",
            "posted_number": "PPI-9001",
            "api_id": api_id,
            "attempts": 2,
        }

    monkeypatch.setattr(svc, "resolve_posted_purchase_invoice_identity", fake_resolve)

    result = await svc.recover_posted_purchase_invoice_identity("doc-1", db)

    assert captured["api_id"] == "draft-api-id"
    assert result["status"] == "Posted"
    assert result["bc_record_no"] == "PPI-9001"
    assert result["bc_system_id"] == "real-posted-system-id"
    assert result["import_ready"] is True

    stored = db.hub_documents.document
    assert stored["bc_record_id"] == "real-posted-system-id"
    assert stored["bc_document_no"] == "PPI-9001"
    assert stored["GPI_SourceTableID"] == 122
    assert stored["GPI_SourceSystemId"] == "real-posted-system-id"
    assert stored["GPI_SourceDocumentNo"] == "PPI-9001"
    assert stored["ImportReady"] is True
    assert stored["delivery_status"] == "ImportReady"
    assert stored["workflow_history"][-1]["event"] == "posted_identity_recovered"


@pytest.mark.asyncio
async def test_recovery_rejects_wrong_state_without_resolving(monkeypatch):
    db = FakeDb({
        "id": "doc-1",
        "status": "ReadyForPost",
        "bc_true_post_confirmed": False,
        "bc_api_id": "draft-api-id",
    })
    called = False

    async def fake_resolve(api_id):
        nonlocal called
        called = True
        return {}

    monkeypatch.setattr(svc, "resolve_posted_purchase_invoice_identity", fake_resolve)

    with pytest.raises(svc.PostedIdentityRecoveryError, match="PostedNeedsIdentity"):
        await svc.recover_posted_purchase_invoice_identity("doc-1", db)
    assert called is False
    assert db.hub_documents.update_calls == []


@pytest.mark.asyncio
async def test_recovery_rejects_missing_api_id(monkeypatch):
    db = FakeDb({
        "id": "doc-1",
        "status": "PostedNeedsIdentity",
        "bc_true_post_confirmed": True,
        "bc_api_id": "",
    })
    with pytest.raises(svc.PostedIdentityRecoveryError, match="bc_api_id"):
        await svc.recover_posted_purchase_invoice_identity("doc-1", db)
    assert db.hub_documents.update_calls == []


@pytest.mark.asyncio
async def test_resolver_failure_leaves_document_unchanged(monkeypatch):
    original = {
        "id": "doc-1",
        "status": "PostedNeedsIdentity",
        "bc_true_post_confirmed": True,
        "bc_api_id": "draft-api-id",
    }
    db = FakeDb(original)

    async def fake_resolve(api_id):
        raise RuntimeError("not materialized yet")

    monkeypatch.setattr(svc, "resolve_posted_purchase_invoice_identity", fake_resolve)

    with pytest.raises(RuntimeError, match="not materialized"):
        await svc.recover_posted_purchase_invoice_identity("doc-1", db)
    assert db.hub_documents.update_calls == []
    assert db.hub_documents.document == original
