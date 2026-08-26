import pytest

import services.ap_posted_recovery_dispatch_service as svc


class InsertCollection:
    def __init__(self):
        self.rows = []

    async def insert_one(self, row):
        self.rows.append(dict(row))


class FakeDb:
    def __init__(self):
        self.hub_workflow_runs = InsertCollection()


@pytest.mark.asyncio
async def test_non_post_success_state_is_not_intercepted(monkeypatch):
    db = FakeDb()
    result = await svc.dispatch_ap_posted_recovery_if_needed(
        "doc-1", db, {"status": "ReadyForPost"}
    )
    assert result is None
    assert db.hub_workflow_runs.rows == []


@pytest.mark.asyncio
async def test_posted_needs_identity_routes_only_to_identity_recovery(monkeypatch):
    db = FakeDb()
    called = {}

    async def fake_identity(document_id, db_arg):
        called["identity"] = document_id
        return {
            "recovered": True,
            "posted": True,
            "status": "PostedNeedsMetadata",
            "import_ready": False,
            "bc_record_no": "PPI-9001",
            "bc_system_id": "posted-system-id",
        }

    import services.ap_posted_identity_recovery_service as identity_svc
    monkeypatch.setattr(identity_svc, "recover_posted_purchase_invoice_identity", fake_identity)

    result = await svc.dispatch_ap_posted_recovery_if_needed(
        "doc-1", db, {"status": "PostedNeedsIdentity"}
    )

    assert called == {"identity": "doc-1"}
    assert result["recovery_dispatched"] is True
    assert result["recovery_type"] == "posted_identity"
    assert result["status"] == "PostedNeedsMetadata"
    assert result["import_ready"] is False
    assert db.hub_workflow_runs.rows[-1]["status"] == "CompletedWithWarnings"


@pytest.mark.asyncio
async def test_posted_needs_metadata_routes_only_to_metadata_recovery(monkeypatch):
    db = FakeDb()
    called = {}

    async def fake_metadata(document_id, db_arg):
        called["metadata"] = document_id
        return {
            "recovered": True,
            "posted": True,
            "status": "Posted",
            "import_ready": True,
            "bc_record_no": "PPI-9001",
            "bc_system_id": "posted-system-id",
        }

    import services.ap_posted_metadata_recovery_service as metadata_svc
    monkeypatch.setattr(metadata_svc, "recover_posted_purchase_invoice_metadata", fake_metadata)

    result = await svc.dispatch_ap_posted_recovery_if_needed(
        "doc-1", db, {"status": "PostedNeedsMetadata"}
    )

    assert called == {"metadata": "doc-1"}
    assert result["recovery_type"] == "posted_metadata"
    assert result["status"] == "Posted"
    assert result["import_ready"] is True
    assert db.hub_workflow_runs.rows[-1]["status"] == "Completed"


@pytest.mark.asyncio
async def test_recovery_failure_is_audited_and_propagates(monkeypatch):
    db = FakeDb()

    async def fake_metadata(document_id, db_arg):
        raise RuntimeError("Graph unavailable")

    import services.ap_posted_metadata_recovery_service as metadata_svc
    monkeypatch.setattr(metadata_svc, "recover_posted_purchase_invoice_metadata", fake_metadata)

    with pytest.raises(RuntimeError, match="Graph unavailable"):
        await svc.dispatch_ap_posted_recovery_if_needed(
            "doc-1", db, {"status": "PostedNeedsMetadata"}
        )

    row = db.hub_workflow_runs.rows[-1]
    assert row["workflow_name"] == "ap_posted_recovery"
    assert row["status"] == "Failed"
    assert row["posted"] is True
    assert row["import_ready"] is False
