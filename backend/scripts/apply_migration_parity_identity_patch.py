"""One-time exact patch for historical migration SystemId readiness."""

from pathlib import Path

path = Path("backend/services/migration/job.py")
text = path.read_text(encoding="utf-8")

old_import = '''from .sources import LegacyDocumentSource, LegacyDocument, LegacyDocumentMetadata\nfrom .workflow_initializer import WorkflowInitializer\n'''
new_import = '''from .sources import LegacyDocumentSource, LegacyDocument, LegacyDocumentMetadata\nfrom .workflow_initializer import WorkflowInitializer\nfrom .parity_identity import stage_migration_parity_fields, resolve_migration_identity\n'''
if text.count(old_import) != 1:
    raise SystemExit(f"migration imports: expected 1 match, found {text.count(old_import)}")
text = text.replace(old_import, new_import, 1)

old_run = '''                # Transform to GPI Hub document\n                gpi_doc = self._transform_document(legacy_doc)\n                \n                if gpi_doc is None:\n                    stats.record_skip(\n                        "Transformation failed",\n                        legacy_doc.metadata.legacy_id\n                    )\n                    continue\n                \n                # Collect sample for dry-run review\n'''
new_run = '''                # Transform to GPI Hub document\n                gpi_doc = self._transform_document(legacy_doc)\n                \n                if gpi_doc is None:\n                    stats.record_skip(\n                        "Transformation failed",\n                        legacy_doc.metadata.legacy_id\n                    )\n                    continue\n\n                # REAL migration resolves exact Production BC identity before a\n                # historical AP/PO record can be considered ImportReady. A\n                # failed lookup remains staged/recoverable and does not stop\n                # the bulk run or falsely report downstream readiness.\n                if mode == MigrationMode.REAL:\n                    gpi_doc = await resolve_migration_identity(\n                        gpi_doc,\n                        legacy_doc.metadata,\n                        gpi_doc.get("doc_type", "OTHER"),\n                    )\n                \n                # Collect sample for dry-run review\n'''
if text.count(old_run) != 1:
    raise SystemExit(f"migration run identity gate: expected 1 match, found {text.count(old_run)}")
text = text.replace(old_run, new_run, 1)

old_return = '''        # Add legacy status snapshot\n        gpi_doc["legacy_status"] = {\n            "is_paid": metadata.is_paid,\n            "is_posted": metadata.is_posted,\n            "is_exported": metadata.is_exported,\n            "is_approved": metadata.is_approved,\n            "is_canceled": metadata.is_canceled,\n            "is_voided": metadata.is_voided,\n            "is_closed": metadata.is_closed,\n            "is_reviewed": metadata.is_reviewed,\n        }\n        \n        return gpi_doc\n'''
new_return = '''        # Add legacy status snapshot\n        gpi_doc["legacy_status"] = {\n            "is_paid": metadata.is_paid,\n            "is_posted": metadata.is_posted,\n            "is_exported": metadata.is_exported,\n            "is_approved": metadata.is_approved,\n            "is_canceled": metadata.is_canceled,\n            "is_voided": metadata.is_voided,\n            "is_closed": metadata.is_closed,\n            "is_reviewed": metadata.is_reviewed,\n        }\n\n        # Stage normalized parity metadata for every migration mode. Legacy\n        # workflow state is preserved separately, but delivery readiness fails\n        # closed until exact BC identity is resolved where required.\n        gpi_doc = stage_migration_parity_fields(gpi_doc, metadata, doc_type)\n        \n        return gpi_doc\n'''
if text.count(old_return) != 1:
    raise SystemExit(f"migration staged parity metadata: expected 1 match, found {text.count(old_return)}")
text = text.replace(old_return, new_return, 1)

for needle in (
    "stage_migration_parity_fields(gpi_doc, metadata, doc_type)",
    "await resolve_migration_identity(",
    "if mode == MigrationMode.REAL:",
):
    if needle not in text:
        raise SystemExit(f"post-patch verification missing: {needle}")

path.write_text(text, encoding="utf-8")
print("PASS: historical migration parity identity patch applied")
