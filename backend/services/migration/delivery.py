"""Historical document-body delivery through the normal SharePoint parity boundary."""

from datetime import datetime, timezone
from pathlib import PurePath
from typing import Any, Dict

from services.sharepoint_service import upload_to_sharepoint_with_routing


def _file_name(gpi_doc: Dict[str, Any], legacy_doc) -> str:
    existing = str(gpi_doc.get("GPI_OriginalFileName") or "").strip()
    if existing:
        return existing
    reference = str(getattr(legacy_doc, "binary_reference", None) or "").replace("\\", "/")
    name = PurePath(reference).name
    return name or f"{gpi_doc.get('legacy_id') or gpi_doc.get('id')}.bin"


def build_migration_metadata_override(gpi_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Build the exact historical parity identity to write with the uploaded file."""
    system_id = str(gpi_doc.get("GPI_SourceSystemId") or gpi_doc.get("bc_system_id") or "").strip()
    identity_required = bool(gpi_doc.get("migration_identity_required"))
    identity_ready = bool((not identity_required) or system_id)
    if identity_ready:
        status = "ImportReady"
    elif str(gpi_doc.get("migration_identity_status") or "") == "missing_record_number":
        status = "MigrationNeedsRecord"
    else:
        status = "MigrationNeedsSystemId"

    return {
        "GPI_SourceTableID": gpi_doc.get("GPI_SourceTableID") or "",
        "GPI_SourceSystemId": system_id,
        "GPI_SourceDocumentType": str(gpi_doc.get("GPI_SourceDocumentType") or ""),
        "GPI_SourceDocumentNo": str(gpi_doc.get("GPI_SourceDocumentNo") or ""),
        "GPI_SourcePartyType": str(gpi_doc.get("GPI_SourcePartyType") or ""),
        "GPI_SourcePartyNo": str(gpi_doc.get("GPI_SourcePartyNo") or ""),
        "GPI_OriginalFileName": str(gpi_doc.get("GPI_OriginalFileName") or ""),
        "GPI_SharePointFileName": "",
        "GPI_SharePointPath": "",
        "GPI_SharePointURL": "",
        "GPI_Status": status,
        "GPI_MatchStatus": str(gpi_doc.get("migration_identity_status") or "migration"),
        "GPI_MatchMethod": "historical_migration_exact_bc_identity" if system_id else "historical_migration_pending_identity",
        "GPI_MatchConfidence": 1.0 if system_id else 0.0,
        "GPI_Candidates": "",
        "ImportReady": identity_ready,
    }


async def deliver_migrated_document(source, legacy_doc, gpi_doc: Dict[str, Any]) -> Dict[str, Any]:
    """Read one legacy body and upload it through the existing parity boundary.

    The source owns byte retrieval. The SharePoint service owns routing, naming,
    upload, and normalized metadata persistence. A document is not considered
    delivered merely because its migration metadata was inserted into MongoDB.
    """
    file_content = source.read_binary(legacy_doc)
    if not isinstance(file_content, (bytes, bytearray)) or not file_content:
        raise ValueError("Legacy document body is empty")

    original_name = _file_name(gpi_doc, legacy_doc)
    metadata_override = build_migration_metadata_override(gpi_doc)
    metadata_override["GPI_OriginalFileName"] = original_name

    result = await upload_to_sharepoint_with_routing(
        file_content=bytes(file_content),
        file_name=original_name,
        doc=gpi_doc,
        parity_metadata_override=metadata_override,
    )

    metadata = result["parity_metadata"]
    now = datetime.now(timezone.utc).isoformat()
    gpi_doc.update({
        "sharepoint_drive_id": result.get("drive_id"),
        "sharepoint_item_id": result.get("item_id"),
        "sharepoint_web_url": result.get("web_url"),
        "sharepoint_folder_path": result.get("folder_path"),
        "uploaded_file_name": result.get("uploaded_file_name"),
        "sharepoint_parity_metadata": metadata,
        "GPI_SharePointFileName": metadata.get("GPI_SharePointFileName", ""),
        "GPI_SharePointPath": metadata.get("GPI_SharePointPath", ""),
        "GPI_SharePointURL": metadata.get("GPI_SharePointURL", ""),
        "GPI_Status": metadata.get("GPI_Status", "NotImportReady"),
        "ImportReady": bool(metadata.get("ImportReady")),
        "import_ready": bool(metadata.get("ImportReady")),
        "delivery_status": metadata.get("GPI_Status", "NotImportReady"),
        "migration_binary_status": "delivered",
        "migration_binary_delivered_at": now,
        "migration_binary_error": "",
        "status": "migrated_delivered" if metadata.get("ImportReady") else "migration_staged",
    })
    return gpi_doc


__all__ = ["deliver_migrated_document", "build_migration_metadata_override"]
