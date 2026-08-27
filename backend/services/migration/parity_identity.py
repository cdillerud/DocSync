"""Parity identity/readiness contract for historical Square9/Zetadocs migration.

Historical records may preserve their legacy workflow state, but they are never
ImportReady merely because a BC document number was present in the export. AP
and Purchase Order records that require BC visibility must resolve the exact
Production BC SystemId first.
"""

from pathlib import PurePath
from typing import Any, Dict

from services.bc_document_identity_service import resolve_bc_document_system_id
from services.gpi_integration_service import BC_READ_ENVIRONMENT


AP_INVOICE = "AP_INVOICE"
PURCHASE_ORDER = "PURCHASE_ORDER"

# Business Central source tables for the in-scope historical record types.
# AP_INVOICE historical links target posted purchase invoice headers.
SOURCE_TABLE_BY_DOC_TYPE = {
    AP_INVOICE: 122,
    PURCHASE_ORDER: 38,
}

BC_ENTITY_BY_DOC_TYPE = {
    AP_INVOICE: "purchaseInvoices",
    PURCHASE_ORDER: "purchaseOrders",
}

SOURCE_DOCUMENT_TYPE_BY_DOC_TYPE = {
    AP_INVOICE: "Posted Purchase Invoice",
    PURCHASE_ORDER: "Purchase Order",
}


def _original_file_name(binary_reference: str | None) -> str:
    if not binary_reference:
        return ""
    # Handles ordinary file-path exports without pretending a URL is local.
    normalized = str(binary_reference).replace("\\", "/")
    return PurePath(normalized).name


def _legacy_bc_document_no(metadata) -> str:
    return str(getattr(metadata, "legacy_bc_doc_no", None) or "").strip()


def stage_migration_parity_fields(
    gpi_doc: Dict[str, Any],
    metadata,
    doc_type: str,
) -> Dict[str, Any]:
    """Apply normalized, fail-closed migration metadata without network I/O."""
    bc_entity = BC_ENTITY_BY_DOC_TYPE.get(doc_type)
    source_table_id = SOURCE_TABLE_BY_DOC_TYPE.get(doc_type)
    source_doc_type = SOURCE_DOCUMENT_TYPE_BY_DOC_TYPE.get(doc_type, doc_type)
    source_doc_no = _legacy_bc_document_no(metadata)
    requires_bc_identity = bc_entity is not None

    gpi_doc.update({
        "GPI_SourceTableID": source_table_id,
        "GPI_SourceSystemId": "",
        "GPI_SourceDocumentType": source_doc_type,
        "GPI_SourceDocumentNo": source_doc_no,
        "GPI_SourcePartyType": "Vendor" if doc_type in {AP_INVOICE, PURCHASE_ORDER} else "",
        "GPI_SourcePartyNo": str(getattr(metadata, "vendor_no", None) or ""),
        "GPI_OriginalFileName": _original_file_name(gpi_doc.get("legacy_file_reference")),
        "GPI_SharePointFileName": "",
        "GPI_SharePointPath": "",
        "GPI_SharePointURL": "",
        "GPI_Status": (
            "MigrationNeedsSystemId"
            if requires_bc_identity and source_doc_no
            else "MigrationNeedsRecord"
            if requires_bc_identity
            else "MigrationStaged"
        ),
        "ImportReady": False,
        "import_ready": False,
        "delivery_status": (
            "MigrationNeedsSystemId"
            if requires_bc_identity and source_doc_no
            else "MigrationNeedsRecord"
            if requires_bc_identity
            else "MigrationStaged"
        ),
        "migration_identity_required": requires_bc_identity,
        "migration_identity_status": (
            "pending_system_id"
            if requires_bc_identity and source_doc_no
            else "missing_record_number"
            if requires_bc_identity
            else "not_required"
        ),
        "bc_entity_type": bc_entity,
        "bc_document_no": source_doc_no or None,
        "bc_record_id": None,
        "bc_system_id": None,
    })

    # Top-level migration status must not be confused with downstream delivery.
    gpi_doc["status"] = "migration_staged"
    return gpi_doc


async def resolve_migration_identity(
    gpi_doc: Dict[str, Any],
    metadata,
    doc_type: str,
) -> Dict[str, Any]:
    """Resolve exact Production BC identity for in-scope historical records.

    Resolution failure is retained as a visible/recoverable migration state so
    a bulk run can continue without ever marking the record ImportReady.
    """
    bc_entity = BC_ENTITY_BY_DOC_TYPE.get(doc_type)
    bc_document_no = _legacy_bc_document_no(metadata)
    if not bc_entity:
        return gpi_doc
    if not bc_document_no:
        return gpi_doc

    try:
        identity = await resolve_bc_document_system_id(
            bc_entity,
            bc_document_no,
            environment=BC_READ_ENVIRONMENT,
        )
    except Exception as exc:
        gpi_doc.update({
            "GPI_SourceSystemId": "",
            "GPI_Status": "MigrationNeedsSystemId",
            "ImportReady": False,
            "import_ready": False,
            "delivery_status": "MigrationNeedsSystemId",
            "migration_identity_status": "resolution_failed",
            "migration_identity_error": str(exc),
            "bc_record_id": None,
            "bc_system_id": None,
        })
        return gpi_doc

    system_id = str(identity["bc_system_id"])
    gpi_doc.update({
        "GPI_SourceSystemId": system_id,
        "GPI_Status": "MigrationIdentityReady",
        "ImportReady": True,
        "import_ready": True,
        "delivery_status": "MigrationIdentityReady",
        "migration_identity_status": "resolved",
        "migration_identity_error": "",
        "bc_record_id": system_id,
        "bc_system_id": system_id,
        "bc_entity_type": bc_entity,
        "bc_document_no": str(identity.get("bc_document_no") or bc_document_no),
    })
    return gpi_doc


__all__ = [
    "stage_migration_parity_fields",
    "resolve_migration_identity",
    "BC_ENTITY_BY_DOC_TYPE",
]
