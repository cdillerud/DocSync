import pytest

import services.migration.job as migration_job
from services.migration.job import MigrationJob, MigrationMode
from services.migration.sources import InMemorySource, LegacyDocument, LegacyDocumentMetadata


class _Cursor:
    def __init__(self, docs):
        self._docs = iter(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self._docs)
        except StopIteration:
            raise StopAsyncIteration


class _Collection:
    def __init__(self, fail=False):
        self.fail = fail
        self.inserted = []
        self.insert_attempts = 0

    def find(self, query, projection):
        return _Cursor([])

    async def insert_many(self, docs):
        self.insert_attempts += 1
        if self.fail:
            raise RuntimeError("simulated mongo batch failure")
        self.inserted.extend(docs)

        class _Result:
            inserted_ids = list(range(len(docs)))

        return _Result()


class _Source(InMemorySource):
    def read_binary(self, doc):
        return b"migration-body"


def _legacy(legacy_id):
    return LegacyDocument(
        metadata=LegacyDocumentMetadata(
            legacy_system="SQUARE9",
            legacy_id=legacy_id,
            legacy_workflow_name="Statement",
        ),
        binary_reference=f"/{legacy_id}.pdf",
    )


@pytest.fixture(autouse=True)
def _stub_external_delivery(monkeypatch):
    async def resolve(doc, metadata, doc_type):
        return doc

    async def deliver(source, legacy_doc, doc):
        doc = dict(doc)
        doc["migration_binary_status"] = "delivered"
        doc["sharepoint_item_id"] = f"sp-{legacy_doc.metadata.legacy_id}"
        return doc

    monkeypatch.setattr(migration_job, "resolve_migration_identity", resolve)
    monkeypatch.setattr(migration_job, "deliver_migrated_document", deliver)


@pytest.mark.asyncio
async def test_real_success_is_counted_only_after_batch_persists():
    source = _Source("durable")
    source.add_documents([_legacy("A"), _legacy("B")])
    collection = _Collection()
    job = MigrationJob(source, db_collection=collection, batch_size=2)

    result = await job.run(mode=MigrationMode.REAL)

    assert collection.insert_attempts == 1
    assert len(collection.inserted) == 2
    assert result.stats.total_success == 2
    assert result.stats.total_errors == 0


@pytest.mark.asyncio
async def test_failed_batch_reports_every_document_as_error_and_zero_success():
    source = _Source("durability-failure")
    source.add_documents([_legacy("A"), _legacy("B")])
    collection = _Collection(fail=True)
    job = MigrationJob(source, db_collection=collection, batch_size=2)

    result = await job.run(mode=MigrationMode.REAL)

    assert collection.insert_attempts == 1
    assert result.stats.total_success == 0
    assert result.stats.total_errors == 2
    assert {e["legacy_id"] for e in result.stats.errors} == {"A", "B"}
    assert all("Mongo persistence failed after document delivery" in e["error"] for e in result.stats.errors)


@pytest.mark.asyncio
async def test_final_partial_batch_failure_is_reconciled_not_raised():
    source = _Source("final-batch-failure")
    source.add_document(_legacy("A"))
    collection = _Collection(fail=True)
    job = MigrationJob(source, db_collection=collection, batch_size=50)

    result = await job.run(mode=MigrationMode.REAL)

    assert collection.insert_attempts == 1
    assert result.stats.total_success == 0
    assert result.stats.total_errors == 1
    assert result.stats.total_processed == 1


@pytest.mark.asyncio
async def test_failed_batch_identity_remains_reserved_for_current_run():
    source = _Source("same-run-failure")
    source.add_documents([_legacy("A"), _legacy("A")])
    collection = _Collection(fail=True)
    job = MigrationJob(source, db_collection=collection, batch_size=1)

    result = await job.run(mode=MigrationMode.REAL)

    assert collection.insert_attempts == 1
    assert result.stats.total_success == 0
    assert result.stats.total_errors == 1
    assert result.stats.total_skipped == 1
