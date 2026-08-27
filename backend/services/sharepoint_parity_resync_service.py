"""Re-synchronize parity metadata on an existing SharePoint document item.

BC identity can legitimately evolve after the original file upload (for example
PO -> draft Purchase Invoice -> posted Purchase Invoice).  The file bytes must
not be uploaded again; only the existing list item's normalized GPI_* metadata
is patched so SharePoint, Hub, and BC remain reconcilable.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from services.sharepoint_service import write_sharepoint_parity_metadata


class SharePointParityResyncError(RuntimeError):
    pass


_PARITY_KEYS = (
    "GPI_SourceTableID",
    "GPI_SourceSystemId",
    "GPI_SourceDocumentType",
    "GPI_SourceDocumentNo",
    "GPI_SourcePartyType",
    "GPI_SourcePartyNo",
    "GPI_OriginalFileName",
    "GPI_SharePointFileName",
    "GPI_SharePointPath",
    "GPI_SharePointURL",
    "GPI_Status",
    "GPI_MatchStatus",
    "GPI_MatchMethod",
    "GPI_MatchConfidence",
    "GPI_Candidates",
    "ImportReady",
)


def build_existing_item_parity_metadata(
    document: Dict[str, Any],
    identity_update: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    merged = dict(document or {})
    merged.update(identity_update or {})

    metadata = {key: merged.get(key) for key in _PARITY_KEYS if key in merged}
    metadata.setdefault("GPI_SourceTableID", None)
    metadata.setdefault("GPI_SourceSystemId", "")
    metadata.setdefault("GPI_SourceDocumentType", "")
    metadata.setdefault("GPI_SourceDocumentNo", "")
    metadata.setdefault("GPI_SourcePartyType", "")
    metadata.setdefault("GPI_SourcePartyNo", "")
    metadata.setdefault(
        "GPI_OriginalFileName",
        merged.get("original_file_name") or merged.get("file_name") or "",
    )
    metadata.setdefault(
        "GPI_SharePointFileName",
        merged.get("sharepoint_file_name") or merged.get("file_name") or "",
    )
    metadata.setdefault(
        "GPI_SharePointPath",
        merged.get("sharepoint_folder_path") or "",
    )
    metadata.setdefault(
        "GPI_SharePointURL",
        merged.get("sharepoint_web_url") or "",
    )
    metadata.setdefault("GPI_Status", merged.get("delivery_status") or "NotImportReady")
    metadata.setdefault("GPI_MatchStatus", "")
    metadata.setdefault("GPI_MatchMethod", "")
    metadata.setdefault("GPI_MatchConfidence", 0.0)
    metadata.setdefault("GPI_Candidates", "")
    metadata["ImportReady"] = bool(merged.get("ImportReady", merged.get("import_ready", False)))
    return metadata


async def resync_existing_sharepoint_parity_metadata(
    document_id: str,
    db,
    *,
    identity_update: Dict[str, Any] | None = None,
) -> Dict[str, Any]:
    doc_id = str(document_id or "").strip()
    if not doc_id:
        raise ValueError("document_id is required")

    document = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not document:
        raise SharePointParityResyncError(f"Document {doc_id} not found")

    drive_id = str(document.get("sharepoint_drive_id") or "").strip()
    item_id = str(document.get("sharepoint_item_id") or "").strip()
    if not drive_id or not item_id:
        raise SharePointParityResyncError(
            f"Document {doc_id} has no existing SharePoint drive/item identity"
        )

    metadata = build_existing_item_parity_metadata(document, identity_update)
    result = await write_sharepoint_parity_metadata(drive_id, item_id, metadata)
    now = datetime.now(timezone.utc).isoformat()

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "sharepoint_parity_metadata": metadata,
            "sharepoint_metadata_written_at": now,
            "sharepoint_metadata_resynced_at": now,
            "sharepoint_metadata_error": None,
        }},
    )

    return {
        "success": True,
        "document_id": doc_id,
        "drive_id": drive_id,
        "item_id": item_id,
        "metadata": metadata,
        "write": result,
    }


__all__ = [
    "build_existing_item_parity_metadata",
    "resync_existing_sharepoint_parity_metadata",
    "SharePointParityResyncError",
]
