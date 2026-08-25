"""Type-safe selectors for Business Central Gamer Documents visibility.

BC document numbers are not globally unique across entity types.  Every FactBox
lookup therefore has to bind the number to the requested BC entity/document
family; querying by number alone can surface a document from the wrong record.
"""

from typing import Dict, List


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


def build_hub_document_link_query(bc_entity: str, bc_document_no: str) -> dict:
    """Build a fail-closed Mongo selector for one BC record's visible links.

    Untyped legacy rows are deliberately excluded: when numbers collide, an
    untyped row cannot be proven to belong to the requested BC record.
    """
    aliases = document_type_aliases(bc_entity)
    return {
        "bc_document_no": bc_document_no,
        "sharepoint_web_url": {"$nin": [None, ""]},
        "$and": [
            {"$or": [{"deleted": {"$exists": False}}, {"deleted": False}]},
            {
                "$or": [
                    {"bc_entity": bc_entity},
                    {"bc_entity_type": bc_entity},
                    {"document_type": {"$in": aliases}},
                    {"doc_type": {"$in": aliases}},
                    {"suggested_job_type": {"$in": aliases}},
                ]
            },
        ],
    }


def _odata_quote(value: str) -> str:
    return str(value).replace("'", "''")


def build_bc_document_link_filter(bc_entity: str, bc_document_no: str) -> str:
    """Build an OData filter bound to both document number and document type."""
    document_type = canonical_document_type(bc_entity)
    return (
        f"bcDocumentNo eq '{_odata_quote(bc_document_no)}' and "
        f"documentType eq '{_odata_quote(document_type)}'"
    )


__all__ = [
    "canonical_document_type",
    "document_type_aliases",
    "build_hub_document_link_query",
    "build_bc_document_link_filter",
]
