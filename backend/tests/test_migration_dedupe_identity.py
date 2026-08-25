import pytest

from services.migration.job import MigrationJob, MigrationMode
from services.migration.sources import InMemorySource, LegacyDocument, LegacyDocumentMetadata


class _Cursor:
    def __init__(self, docs):
        self.docs = iter(docs)

    def __aiter__(self):
        return self

    async def __anext__(self):
        try:
            return next(self.docs)
        except StopIteration:
            raise StopAsyncIteration


class _Collection:
    def __init__(self, existing=None):
        self.existing = existing or []
        self.inserted = []

    def find(self, query, projection):
        return _Cursor(self.existing)

    async def insert_many(self, docs):
        self.inserted.extend(docs)

        class _Result:
            inserted_ids = list(range(len(docs)))

        return _Result()


def _legacy(system, legacy_id):
    return LegacyDocument(
        metadata=LegacyDocumentMetadata(
            legacy_system=system,
            legacy_id=legacy_id,
            legacy_workflow_name="Statement",
        )
    )


@pytest.mark.asyncio
async def test_same_legacy_id_from_different_systems_does_not_collide():
    source = InMemorySource("mixed")
    source.add_documents([
        _legacy("SQUARE9", "123"),
        _legacy("ZETADOCS", "123"),
    ])
    collection = _Collection()
    job = MigrationJob(source, db_collection=collection, batch_size=10)

    result = await job.run(mode=MigrationMode.REAL)

    assert result.stats.total_success == 2
    assert result.stats.total_skipped == 0
    assert len(collection.inserted) == 2


@pytest.mark.asyncio
async def test_duplicate_source_identity_inside_same_run_is_written_once():
    source = InMemorySource("square9")
    source.add_documents([
        _legacy("SQUARE9", "123"),
        _legacy("SQUARE9", "123"),
    ])
    collection = _Collection()
    job = MigrationJob(source, db_collection=collection, batch_size=10)

    result = await job.run(mode=MigrationMode.REAL)

    assert result.stats.total_success == 1
    assert result.stats.total_skipped == 1
    assert len(collection.inserted) == 1


@pytest.mark.asyncio
async def test_existing_square9_id_does_not_block_same_zetadocs_id():
    source = InMemorySource("zetadocs")
    source.add_document(_legacy("ZETADOCS", "123"))
    collection = _Collection(existing=[{
        "legacy_system": "SQUARE9",
        "legacy_id": "123",
        "is_migrated": True,
    }])
    job = MigrationJob(source, db_collection=collection, batch_size=10)

    result = await job.run(mode=MigrationMode.REAL)

    assert result.stats.total_success == 1
    assert result.stats.total_skipped == 0
    assert len(collection.inserted) == 1
