"""One-time exact patch for historical migration document-body delivery."""

from pathlib import Path

sources_path = Path("backend/services/migration/sources.py")
sharepoint_path = Path("backend/services/sharepoint_service.py")
job_path = Path("backend/services/migration/job.py")

sources = sources_path.read_text(encoding="utf-8")
sharepoint = sharepoint_path.read_text(encoding="utf-8")
job = job_path.read_text(encoding="utf-8")

# 1) Legacy source owns byte retrieval. Base implementation supports local paths;
# JsonFileSource additionally resolves paths relative to the export manifest.
old_base = '''    @abstractmethod\n    def get_source_name(self) -> str:\n        """Return a descriptive name for this source."""\n        pass\n\n\nclass InMemorySource(LegacyDocumentSource):\n'''
new_base = '''    @abstractmethod\n    def get_source_name(self) -> str:\n        """Return a descriptive name for this source."""\n        pass\n\n    def read_binary(self, doc: LegacyDocument) -> bytes:\n        """Read the document body for migration. Local paths only by default."""\n        reference = str(doc.binary_reference or "").strip()\n        if not reference:\n            raise FileNotFoundError(\n                f"Legacy document {doc.metadata.legacy_id!r} has no binary_reference"\n            )\n        if reference.lower().startswith(("http://", "https://")):\n            raise ValueError(\n                "Remote legacy binary references require an explicit source implementation"\n            )\n        path = Path(reference)\n        if not path.is_file():\n            raise FileNotFoundError(f"Legacy document body not found: {reference}")\n        return path.read_bytes()\n\n\nclass InMemorySource(LegacyDocumentSource):\n'''
if sources.count(old_base) != 1:
    raise SystemExit(f"sources base binary reader: expected 1 match, found {sources.count(old_base)}")
sources = sources.replace(old_base, new_base, 1)

old_json = '''    def get_source_name(self) -> str:\n        self._load()\n        return self._data.get("source_name", self._file_path.stem)\n    \n    def _get_doc_type_hint(self, metadata: LegacyDocumentMetadata) -> Optional[str]:\n'''
new_json = '''    def get_source_name(self) -> str:\n        self._load()\n        return self._data.get("source_name", self._file_path.stem)\n\n    def read_binary(self, doc: LegacyDocument) -> bytes:\n        """Read a local body, resolving relative references beside the JSON export."""\n        reference = str(doc.binary_reference or "").strip()\n        if not reference:\n            raise FileNotFoundError(\n                f"Legacy document {doc.metadata.legacy_id!r} has no binary_reference"\n            )\n        if reference.lower().startswith(("http://", "https://")):\n            raise ValueError(\n                "Remote legacy binary references require an explicit source implementation"\n            )\n        path = Path(reference)\n        if not path.is_absolute():\n            path = self._file_path.parent / path\n        if not path.is_file():\n            raise FileNotFoundError(f"Legacy document body not found: {path}")\n        return path.read_bytes()\n    \n    def _get_doc_type_hint(self, metadata: LegacyDocumentMetadata) -> Optional[str]:\n'''
if sources.count(old_json) != 1:
    raise SystemExit(f"JsonFileSource binary reader: expected 1 match, found {sources.count(old_json)}")
sources = sources.replace(old_json, new_json, 1)

# 2) Existing SharePoint boundary accepts an exact normalized metadata override.
old_sig = '''async def upload_to_sharepoint_with_routing(\n    file_content: bytes,\n    file_name: str,\n    doc: Dict[str, Any],\n    freight_direction: Optional[str] = None,\n    is_international: bool = False,\n) -> Dict[str, Any]:\n'''
new_sig = '''async def upload_to_sharepoint_with_routing(\n    file_content: bytes,\n    file_name: str,\n    doc: Dict[str, Any],\n    freight_direction: Optional[str] = None,\n    is_international: bool = False,\n    parity_metadata_override: Optional[Dict[str, Any]] = None,\n) -> Dict[str, Any]:\n'''
if sharepoint.count(old_sig) != 1:
    raise SystemExit(f"SharePoint signature: expected 1 match, found {sharepoint.count(old_sig)}")
sharepoint = sharepoint.replace(old_sig, new_sig, 1)

old_metadata = '''    parity_metadata = build_square9_parity_metadata(\n        routing_doc,\n        po_result,\n        file_name,\n        upload_file_name,\n        full_folder_path,\n        result.get("web_url", ""),\n    )\n\n    try:\n'''
new_metadata = '''    if parity_metadata_override is not None:\n        # Historical migration may already have exact BC identity from the\n        # legacy linkage. Preserve that evidence instead of replacing it with\n        # a live PO re-resolution result. File/path/url are authoritative from\n        # this upload and are always refreshed here.\n        parity_metadata = dict(parity_metadata_override)\n        parity_metadata.update({\n            "GPI_OriginalFileName": file_name,\n            "GPI_SharePointFileName": upload_file_name,\n            "GPI_SharePointPath": full_folder_path,\n            "GPI_SharePointURL": result.get("web_url", ""),\n            "ImportReady": bool(parity_metadata_override.get("ImportReady")),\n        })\n        parity_metadata.setdefault(\n            "GPI_Status",\n            "ImportReady" if parity_metadata["ImportReady"] else "NotImportReady",\n        )\n    else:\n        parity_metadata = build_square9_parity_metadata(\n            routing_doc,\n            po_result,\n            file_name,\n            upload_file_name,\n            full_folder_path,\n            result.get("web_url", ""),\n        )\n\n    try:\n'''
if sharepoint.count(old_metadata) != 1:
    raise SystemExit(f"SharePoint metadata build: expected 1 match, found {sharepoint.count(old_metadata)}")
sharepoint = sharepoint.replace(old_metadata, new_metadata, 1)

# 3) REAL migration must move the body before reserving dedupe identity or
# counting the item as migrated.
old_import = '''from .parity_identity import stage_migration_parity_fields, resolve_migration_identity\n'''
new_import = '''from .parity_identity import stage_migration_parity_fields, resolve_migration_identity\nfrom .delivery import deliver_migrated_document\n'''
if job.count(old_import) != 1:
    raise SystemExit(f"migration delivery import: expected 1 match, found {job.count(old_import)}")
job = job.replace(old_import, new_import, 1)

old_real = '''                if mode == MigrationMode.REAL:\n                    gpi_doc = await resolve_migration_identity(\n                        gpi_doc,\n                        legacy_doc.metadata,\n                        gpi_doc.get("doc_type", "OTHER"),\n                    )\n                \n                # Reserve the accepted source identity immediately. This\n'''
new_real = '''                if mode == MigrationMode.REAL:\n                    gpi_doc = await resolve_migration_identity(\n                        gpi_doc,\n                        legacy_doc.metadata,\n                        gpi_doc.get("doc_type", "OTHER"),\n                    )\n                    # Migration is not successful until the historical body is\n                    # actually delivered to SharePoint with parity metadata.\n                    # Missing/unreadable bodies raise here, are recorded as\n                    # migration errors, and are not inserted or dedupe-reserved.\n                    gpi_doc = await deliver_migrated_document(\n                        self.source, legacy_doc, gpi_doc\n                    )\n                \n                # Reserve the accepted source identity immediately. This\n'''
if job.count(old_real) != 1:
    raise SystemExit(f"migration body delivery call: expected 1 match, found {job.count(old_real)}")
job = job.replace(old_real, new_real, 1)

for needle, content in (
    ("def read_binary(self, doc: LegacyDocument) -> bytes:", sources),
    ("parity_metadata_override: Optional[Dict[str, Any]] = None", sharepoint),
    ("if parity_metadata_override is not None:", sharepoint),
    ("await deliver_migrated_document(", job),
):
    if needle not in content:
        raise SystemExit(f"post-patch verification missing: {needle}")

sources_path.write_text(sources, encoding="utf-8")
sharepoint_path.write_text(sharepoint, encoding="utf-8")
job_path.write_text(job, encoding="utf-8")
print("PASS: historical migration body delivery patch applied")
