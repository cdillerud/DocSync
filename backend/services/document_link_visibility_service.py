"""Type-safe selectors for Business Central Gamer Documents visibility.

BC document numbers are not globally unique across entity types, and lifecycle
records can share an entity family. Every FactBox lookup therefore binds number
to the requested BC entity/document family and, when the caller supplies it, the
immutable Business Central SystemId of the exact record.
"""

from typing import Dict, List
from uuid import UUID


_ENTITY_DOC_TYPES: Dict[str, List[str]] = {
    "purchaseOrders": ["Purchase_Order", "PurchaseOrder", "Purchase Order"],
    "purchaseInvoices": [
        "AP_Invoice",
        "APInvoice",
        "AP Invoice",
        "PurchaseInvoice",
        "Purchase_Invoice",
    ],
    "salesOrders": ["Sales_Order", "SalesOrder", "Sales Order"],
    "postedSalesShipments": [
        "Posted_Sales_Shipment",
        "Posted Sales Shipment",
        "Warehouse_Receipt",
        "Shipping_Document",
        "Freight_Document",
    ],
}

_ENTITY_STORAGE_ALIASES: Dict[str, List[str]] = {
    "purchaseOrders": ["purchaseOrders", "purchase_order", "purchaseOrder"],
    "purchaseInvoices": ["purchaseInvoices", "purchase_invoice", "purchaseInvoice"],
    "salesOrders": ["salesOrders", "sales_order", "salesOrder"],
    "postedSalesShipments": [
        "postedSalesShipments",
        "posted_sales_shipment",
        "postedSalesShipment",
    ],
}


def canonical_document_type(bc_entity: str) -> str:
    aliases = _ENTITY_DOC_TYPES.get(bc_entity)
    if not aliases:
        raise ValueError(f"Unsupported BC document entity for FactBox visibility: {bc_entity!r}")
    return aliases[0]


def document_type_aliases(bc_entity: str) -> List[str]:
    aliases = _ENTITY_DOC_TYPES.get(bc_entity)
    if not aliases:
        raise ValueError(f"Unsupported BC document entity for FactBox visibility: {bc_entity!r}")
    return list(aliases)


def entity_storage_aliases(bc_entity: str) -> List[str]:
    document_type_aliases(bc_entity)
    return list(_ENTITY_STORAGE_ALIASES.get(bc_entity, [bc_entity]))


def build_bc_identity_clause(bc_entity: str) -> dict:
    """Return a Mongo clause proving a row belongs to the requested BC family."""
    aliases = document_type_aliases(bc_entity)
    entity_aliases = entity_storage_aliases(bc_entity)
    return {
        "$or": [
            {"bc_entity": {"$in": entity_aliases}},
            {"bc_entity_type": {"$in": entity_aliases}},
            {"document_type": {"$in": aliases}},
            {"doc_type": {"$in": aliases}},
            {"suggested_job_type": {"$in": aliases}},
        ]
    }


def _normalize_system_id(value: str) -> str:
    raw = str(value or "").strip()
    if not raw:
        return ""
    try:
        return str(UUID(raw))
    except (ValueError, AttributeError, TypeError) as exc:
        raise ValueError(f"Invalid Business Central SystemId: {value!r}") from exc


def _hub_system_id_clause(bc_system_id: str) -> dict:
    system_id = _normalize_system_id(bc_system_id)
    return {
        "$or": [
            {"bc_record_id": system_id},
            {"bc_system_id": system_id},
            {"GPI_SourceSystemId": system_id},
        ]
    }


def build_hub_document_link_query(
    bc_entity: str,
    bc_document_no: str,
    bc_system_id: str = "",
) -> dict:
    """Build a fail-closed Mongo selector for one BC record's visible links.

    Untyped legacy rows are deliberately excluded. When an exact SystemId is
    supplied, a row must match both the document number/family and immutable BC
    record identity. Callers not yet upgraded retain the historical typed-number
    behavior for backward compatibility.
    """
    clauses = [
        {"$or": [{"deleted": {"$exists": False}}, {"deleted": False}]},
        build_bc_identity_clause(bc_entity),
    ]
    if str(bc_system_id or "").strip():
        clauses.append(_hub_system_id_clause(bc_system_id))

    return {
        "bc_document_no": bc_document_no,
        "sharepoint_web_url": {"$nin": [None, ""]},
        "$and": clauses,
    }


def build_folder_match_query(
    bc_entity: str,
    bc_document_no: str,
    bc_system_id: str = "",
) -> dict:
    """Build a type-safe selector for reusing an existing SharePoint folder."""
    clauses = [build_bc_identity_clause(bc_entity)]
    if str(bc_system_id or "").strip():
        clauses.append(_hub_system_id_clause(bc_system_id))
    return {
        "bc_document_no": bc_document_no,
        "sharepoint_folder_path": {"$nin": [None, ""]},
        "$and": clauses,
    }


def _odata_quote(value: str) -> str:
    return str(value).replace("'", "''")


def build_bc_document_link_filter(
    bc_entity: str,
    bc_document_no: str,
    bc_system_id: str = "",
) -> str:
    """Build an OData filter bound to number/type and optional exact SystemId."""
    document_type = canonical_document_type(bc_entity)
    parts = [
        f"bcDocumentNo eq '{_odata_quote(bc_document_no)}'",
        f"documentType eq '{_odata_quote(document_type)}'",
    ]
    if str(bc_system_id or "").strip():
        parts.append(f"targetSystemId eq {_normalize_system_id(bc_system_id)}")
    return " and ".join(parts)


__all__ = [
    "canonical_document_type",
    "document_type_aliases",
    "entity_storage_aliases",
    "build_bc_identity_clause",
    "build_hub_document_link_query",
    "build_folder_match_query",
    "build_bc_document_link_filter",
]
