"""Normalized SharePoint metadata for exact-record Business Central FactBox uploads.

BC Drop uploads are AP/Warehouse parity surfaces, not a separate delivery model.
They must carry the same immutable SystemId and normalized GPI_* metadata as
mailbox intake. Sales/Inside Sales document families remain blocked here.
"""

from typing import Any, Dict, Tuple
from uuid import UUID

from services.sharepoint_service import write_sharepoint_parity_metadata


_ALLOWED_SOURCE_CONTRACTS = {
    ("purchaseInvoices", 38, "Purchase Invoice"),
    ("purchaseInvoices", 122, "Posted Purchase Invoice"),
    ("purchaseOrders", 38, "Purchase Order"),
    ("postedSalesShipments", 110, "Posted Sales Shipment"),
}


def normalize_system_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        raise ValueError("BC Drop upload requires Business Central SystemId")
    try:
        return str(UUID(raw))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"Invalid Business Central SystemId: {value!r}") from exc


def validate_bc_drop_source_contract(
    bc_entity: str,
    source_table_id: int,
    source_document_type: str,
) -> Tuple[str, int, str]:
    entity = str(bc_entity or "").strip()
    try:
        table_id = int(source_table_id)
    except (TypeError, ValueError) as exc:
        raise ValueError("BC Drop upload requires a numeric source table ID") from exc
    document_type = str(source_document_type or "").strip()

    contract = (entity, table_id, document_type)
    if contract not in _ALLOWED_SOURCE_CONTRACTS:
        raise ValueError(
            "BC Drop upload is not enabled for this source contract: "
            f"{entity!r} / table {table_id} / {document_type!r}"
        )
    return contract


def build_bc_drop_parity_metadata(
    *,
    bc_entity: str,
    bc_document_no: str,
    bc_system_id: str,
    source_table_id: int,
    source_document_type: str,
    original_file_name: str,
    sharepoint_file_name: str,
    sharepoint_path: str,
    sharepoint_url: str,
    ready: bool,
) -> Dict[str, Any]:
    validate_bc_drop_source_contract(bc_entity, source_table_id, source_document_type)
    system_id = normalize_system_id(bc_system_id)
    document_no = str(bc_document_no or "").strip()
    if not document_no:
        raise ValueError("BC Drop upload requires BC document number")

    return {
        "GPI_SourceTableID": int(source_table_id),
        "GPI_SourceSystemId": system_id,
        "GPI_SourceDocumentType": str(source_document_type).strip(),
        "GPI_SourceDocumentNo": document_no,
        "GPI_SourcePartyType": "",
        "GPI_SourcePartyNo": "",
        "GPI_OriginalFileName": str(original_file_name or ""),
        "GPI_SharePointFileName": str(sharepoint_file_name or original_file_name or ""),
        "GPI_SharePointPath": str(sharepoint_path or ""),
        "GPI_SharePointURL": str(sharepoint_url or ""),
        "GPI_Status": "ImportReady" if ready else "NeedsBCLink",
        "GPI_MatchStatus": "resolved",
        "GPI_MatchMethod": "bc_factbox_exact_system_id",
        "GPI_MatchConfidence": 1.0,
        "GPI_Candidates": "",
        "ImportReady": bool(ready),
    }


async def write_bc_drop_parity_metadata(doc: Dict[str, Any], *, ready: bool) -> Dict[str, Any]:
    drive_id = str(doc.get("sharepoint_drive_id") or "").strip()
    item_id = str(doc.get("sharepoint_item_id") or "").strip()
    if not drive_id or not item_id:
        raise ValueError("BC Drop metadata write requires existing SharePoint drive/item identity")

    metadata = build_bc_drop_parity_metadata(
        bc_entity=str(doc.get("bc_entity_type") or doc.get("bc_entity") or ""),
        bc_document_no=str(doc.get("bc_document_no") or ""),
        bc_system_id=str(doc.get("bc_system_id") or doc.get("bc_record_id") or ""),
        source_table_id=int(doc.get("bc_source_table_id") or doc.get("GPI_SourceTableID") or 0),
        source_document_type=str(
            doc.get("bc_source_document_type") or doc.get("GPI_SourceDocumentType") or ""
        ),
        original_file_name=str(doc.get("original_file_name") or doc.get("file_name") or ""),
        sharepoint_file_name=str(doc.get("sharepoint_file_name") or doc.get("file_name") or ""),
        sharepoint_path=str(doc.get("sharepoint_folder_path") or ""),
        sharepoint_url=str(doc.get("sharepoint_web_url") or doc.get("sharepoint_share_link_url") or ""),
        ready=ready,
    )
    await write_sharepoint_parity_metadata(drive_id, item_id, metadata)
    return metadata


__all__ = [
    "normalize_system_id",
    "validate_bc_drop_source_contract",
    "build_bc_drop_parity_metadata",
    "write_bc_drop_parity_metadata",
]
