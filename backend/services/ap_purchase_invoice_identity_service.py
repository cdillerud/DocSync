"""Durable AP Purchase Invoice identity for Gamer Documents visibility.

The AP pipeline may first resolve a Purchase Order, but once a BC Purchase
Invoice exists, the Hub's authoritative BC identity must point at that invoice
so Purchase Invoice / Posted Purchase Invoice FactBoxes can retrieve it by exact
entity + document number.
"""

from typing import Dict, Any


def build_ap_purchase_invoice_identity_update(
    bc_record_no: str,
    bc_system_id: str,
    *,
    posted: bool,
) -> Dict[str, Any]:
    record_no = str(bc_record_no or "").strip()
    system_id = str(bc_system_id or "").strip()
    if not record_no:
        raise ValueError("Purchase Invoice identity requires BC document number")

    source_table_id = 122 if posted else 38
    source_document_type = "Posted Purchase Invoice" if posted else "Purchase Invoice"
    identity_ready = bool(system_id)

    return {
        "bc_record_no": record_no,
        "bc_purchase_invoice_no": record_no,
        "bc_document_no": record_no,
        "bc_entity": "purchaseInvoices",
        "bc_entity_type": "purchase_invoice",
        "bc_record_type": "purchaseInvoices",
        "bc_system_id": system_id,
        "bc_record_id": system_id or None,
        "GPI_SourceTableID": source_table_id,
        "GPI_SourceSystemId": system_id,
        "GPI_SourceDocumentType": source_document_type,
        "GPI_SourceDocumentNo": record_no,
        "GPI_Status": "ImportReady" if identity_ready else "NeedsSystemId",
        "ImportReady": identity_ready,
        "import_ready": identity_ready,
        "delivery_status": "ImportReady" if identity_ready else "NeedsSystemId",
        "bc_identity_status": "resolved" if identity_ready else "missing_system_id",
    }


__all__ = ["build_ap_purchase_invoice_identity_update"]
