"""One-time exact patch: count REAL migration success only after Mongo persistence."""

from pathlib import Path

path = Path("backend/services/migration/job.py")
text = path.read_text(encoding="utf-8")

old_success = '''                # Reserve the accepted source identity immediately. This\n                # prevents a duplicate later in the same source/run even before\n                # the current batch is written to MongoDB.\n                if self.skip_duplicates:\n                    existing_keys.add(source_key)\n\n                # Collect sample for dry-run review\n                if len(sample_documents) < 20:\n                    sample_documents.append(gpi_doc)\n                \n                # Record success stats\n                stats.record_success(\n                    gpi_doc.get("doc_type", "OTHER"),\n                    gpi_doc.get("source_system", "UNKNOWN"),\n                    gpi_doc.get("workflow_status", "unknown")\n                )\n                \n                # Batch for database insertion\n                if mode == MigrationMode.REAL:\n                    batch.append(gpi_doc)\n                    \n                    if len(batch) >= self.batch_size:\n                        await self._write_batch(batch)\n                        batch = []\n'''
new_success = '''                # Reserve the accepted source identity immediately for the\n                # current run, preventing an identical source item from being\n                # delivered twice before the batch commits. A failed batch keeps\n                # this in-memory reservation only for this run; a future run\n                # rebuilds durable identities from MongoDB and can reconcile it.\n                if self.skip_duplicates:\n                    existing_keys.add(source_key)\n\n                # Collect sample for dry-run review\n                if len(sample_documents) < 20:\n                    sample_documents.append(gpi_doc)\n\n                if mode == MigrationMode.REAL:\n                    # Do not count success until MongoDB confirms persistence.\n                    batch.append({\n                        "doc": gpi_doc,\n                        "source_key": source_key,\n                        "legacy_id": legacy_doc.metadata.legacy_id,\n                    })\n                    if len(batch) >= self.batch_size:\n                        await self._commit_batch(batch, stats)\n                        batch = []\n                else:\n                    stats.record_success(\n                        gpi_doc.get("doc_type", "OTHER"),\n                        gpi_doc.get("source_system", "UNKNOWN"),\n                        gpi_doc.get("workflow_status", "unknown")\n                    )\n'''
if text.count(old_success) != 1:
    raise SystemExit(f"success/batch block: expected 1 match, found {text.count(old_success)}")
text = text.replace(old_success, new_success, 1)

old_final = '''        # Write remaining batch\n        if mode == MigrationMode.REAL and batch:\n            await self._write_batch(batch)\n'''
new_final = '''        # Commit the final partial batch through the same durable accounting\n        # boundary. Persistence failure is reconciled into per-document errors\n        # rather than escaping after earlier success counts were recorded.\n        if mode == MigrationMode.REAL and batch:\n            await self._commit_batch(batch, stats)\n'''
if text.count(old_final) != 1:
    raise SystemExit(f"final batch block: expected 1 match, found {text.count(old_final)}")
text = text.replace(old_final, new_final, 1)

old_write = '''    async def _write_batch(self, batch: List[Dict[str, Any]]) -> None:\n        """Write a batch of documents to the database."""\n        if not batch or self.db_collection is None:\n            return\n        \n        try:\n            result = await self.db_collection.insert_many(batch)\n            logger.debug(f"Inserted batch of {len(result.inserted_ids)} documents")\n        except Exception as e:\n            logger.error(f"Error writing batch: {e}")\n            raise\n'''
new_write = '''    async def _commit_batch(\n        self,\n        batch: List[Dict[str, Any]],\n        stats: MigrationStats,\n    ) -> bool:\n        """Persist one delivered batch, then and only then record success.\n\n        SharePoint delivery occurs before this boundary. If MongoDB persistence\n        fails, every item in the affected batch is reported as an error and no\n        success is claimed. Source identities remain reserved only in memory for\n        the rest of this run, preventing a duplicate source row from immediately\n        re-uploading the same file. A future run reconstructs durable identities\n        from MongoDB and can reconcile the failed batch.\n        """\n        if not batch:\n            return True\n\n        docs = [entry["doc"] for entry in batch]\n        try:\n            await self._write_batch(docs)\n        except Exception as error:\n            message = (\n                "Mongo persistence failed after document delivery; "\n                "SharePoint delivery may already exist and must be reconciled: "\n                f"{error}"\n            )\n            for entry in batch:\n                stats.record_error(message, str(entry.get("legacy_id") or ""))\n            return False\n\n        for entry in batch:\n            doc = entry["doc"]\n            stats.record_success(\n                doc.get("doc_type", "OTHER"),\n                doc.get("source_system", "UNKNOWN"),\n                doc.get("workflow_status", "unknown"),\n            )\n        return True\n\n    async def _write_batch(self, batch: List[Dict[str, Any]]) -> None:\n        """Write a batch of documents to the database."""\n        if not batch or self.db_collection is None:\n            return\n        \n        try:\n            result = await self.db_collection.insert_many(batch)\n            logger.debug(f"Inserted batch of {len(result.inserted_ids)} documents")\n        except Exception as e:\n            logger.error(f"Error writing batch: {e}")\n            raise\n'''
if text.count(old_write) != 1:
    raise SystemExit(f"write batch method: expected 1 match, found {text.count(old_write)}")
text = text.replace(old_write, new_write, 1)

for needle in (
    'await self._commit_batch(batch, stats)',
    '"Mongo persistence failed after document delivery; "',
    'stats.record_success(',
):
    if needle not in text:
        raise SystemExit(f"post-patch verification missing: {needle}")

path.write_text(text, encoding="utf-8")
print("PASS: durable migration accounting patch applied")

# trigger: workflow exists on branch
