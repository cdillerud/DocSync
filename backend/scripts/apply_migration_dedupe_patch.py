"""One-time exact patch for source-scoped historical migration dedupe."""

from pathlib import Path

path = Path("backend/services/migration/job.py")
text = path.read_text(encoding="utf-8")

old_setup = '''        # Get existing legacy IDs if skip_duplicates is enabled\n        existing_ids = set()\n        if self.skip_duplicates and mode == MigrationMode.REAL:\n            existing_ids = await self._get_existing_legacy_ids()\n            logger.info(f"Found {len(existing_ids)} existing migrated documents")\n        \n        # Process documents\n        batch = []\n        for legacy_doc in self.source.iter_documents(source_filter, doc_type_filter, limit):\n            try:\n                # Skip duplicates\n                if legacy_doc.metadata.legacy_id in existing_ids:\n                    stats.record_skip(\n                        "Duplicate legacy_id",\n                        legacy_doc.metadata.legacy_id\n                    )\n                    continue\n'''
new_setup = '''        # Dedupe by source system + legacy ID. IDs are not globally unique\n        # across Square9 and Zetadocs, and the seen set is updated during the\n        # run so duplicates inside one export cannot be inserted twice.\n        existing_keys = set()\n        if self.skip_duplicates and mode == MigrationMode.REAL:\n            existing_keys = await self._get_existing_legacy_keys()\n            logger.info(f"Found {len(existing_keys)} existing migrated source identities")\n        \n        # Process documents\n        batch = []\n        for legacy_doc in self.source.iter_documents(source_filter, doc_type_filter, limit):\n            try:\n                source_key = self._legacy_identity_key(legacy_doc.metadata)\n                # Skip duplicates\n                if self.skip_duplicates and source_key in existing_keys:\n                    stats.record_skip(\n                        "Duplicate legacy source identity",\n                        legacy_doc.metadata.legacy_id\n                    )\n                    continue\n'''
if text.count(old_setup) != 1:
    raise SystemExit(f"migration dedupe setup: expected 1 match, found {text.count(old_setup)}")
text = text.replace(old_setup, new_setup, 1)

old_sample = '''                # Collect sample for dry-run review\n                if len(sample_documents) < 20:\n                    sample_documents.append(gpi_doc)\n'''
new_sample = '''                # Reserve the accepted source identity immediately. This\n                # prevents a duplicate later in the same source/run even before\n                # the current batch is written to MongoDB.\n                if self.skip_duplicates:\n                    existing_keys.add(source_key)\n\n                # Collect sample for dry-run review\n                if len(sample_documents) < 20:\n                    sample_documents.append(gpi_doc)\n'''
if text.count(old_sample) != 1:
    raise SystemExit(f"migration in-run reservation: expected 1 match, found {text.count(old_sample)}")
text = text.replace(old_sample, new_sample, 1)

old_method = '''    async def _get_existing_legacy_ids(self) -> set:\n        """Get set of legacy_ids already in the database."""\n        if self.db_collection is None:\n            return set()\n        \n        cursor = self.db_collection.find(\n            {"is_migrated": True},\n            {"legacy_id": 1, "_id": 0}\n        )\n        \n        ids = set()\n        async for doc in cursor:\n            if doc.get("legacy_id"):\n                ids.add(doc["legacy_id"])\n        \n        return ids\n'''
new_method = '''    @staticmethod\n    def _legacy_identity_key(metadata: LegacyDocumentMetadata) -> tuple[str, str]:\n        """Return stable source-scoped legacy identity for dedupe."""\n        return (\n            str(metadata.legacy_system or "UNKNOWN").strip().upper(),\n            str(metadata.legacy_id or "").strip(),\n        )\n\n    async def _get_existing_legacy_keys(self) -> set:\n        """Get source-scoped legacy identities already in the database."""\n        if self.db_collection is None:\n            return set()\n        \n        cursor = self.db_collection.find(\n            {"is_migrated": True},\n            {"legacy_system": 1, "source_system": 1, "legacy_id": 1, "_id": 0}\n        )\n        \n        keys = set()\n        async for doc in cursor:\n            legacy_id = str(doc.get("legacy_id") or "").strip()\n            if not legacy_id:\n                continue\n            legacy_system = str(\n                doc.get("legacy_system") or doc.get("source_system") or "UNKNOWN"\n            ).strip().upper()\n            keys.add((legacy_system, legacy_id))\n        \n        return keys\n'''
if text.count(old_method) != 1:
    raise SystemExit(f"migration existing identity method: expected 1 match, found {text.count(old_method)}")
text = text.replace(old_method, new_method, 1)

for needle in (
    "source_key = self._legacy_identity_key(legacy_doc.metadata)",
    "existing_keys.add(source_key)",
    "async def _get_existing_legacy_keys(self) -> set:",
):
    if needle not in text:
        raise SystemExit(f"post-patch verification missing: {needle}")

path.write_text(text, encoding="utf-8")
print("PASS: historical migration source-scoped dedupe patch applied")
