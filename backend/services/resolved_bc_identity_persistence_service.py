"""Durable top-level BC identity derived from exact PO/shipment resolution.

The nested ``po_resolution`` object is useful audit evidence, but the BC Gamer
Documents visibility contract intentionally queries top-level typed identity.
This helper promotes only resolved, SystemId-bearing identities. Ambiguous,
not-found, and local-staging results fail closed and cannot masquerade as a
visible BC link.
"""

from typing import Any, Dict


_RESOLVED_STATUSES = {"resolved", "resolved_shipment"}
_ENTITY_MAP = {
    "purchase_order": "purchaseOrders",
    "posted_sales_shipment": "postedSalesShipments",
}
_RECORD_TYPE_MAP = {
    "purchase_order": "purchaseOrder",
    "posted_sales_shipment": "posted_sales_shipment",
}


def build_resolved_bc_identity_update(po_result: Dict[str, Any]) -> Dict[str, Any]:
    """Return top-level Hub identity only for an exact, SystemId-bearing match."""
    result = dict(po_result or {})
    status = str(result.get("status") or "").strip()
    entity_type = str(result.get("bc_entity_type") or "").strip()
    system_id = str(result.get("bc_record_id") or "").strip()
    document_no = str(result.get("po_number") or "").strip()

    if status not in _RESOLVED_STATUSES:
        return {}
    if not system_id or not document_no:
        return {}

    bc_entity = _ENTITY_MAP.get(entity_type)
    bc_record_type = _RECORD_TYPE_MAP.get(entity_type)
    if not bc_entity or not bc_record_type:
        return {}

    return {
        "bc_record_id": system_id,
        "bc_system_id": system_id,
        "bc_document_no": document_no,
        "bc_entity": bc_entity,
        "bc_entity_type": entity_type,
        "bc_record_type": bc_record_type,
        "bc_identity_source": "po_resolution",
        "bc_identity_match_method": str(result.get("match_method") or ""),
        "bc_identity_confidence": float(result.get("confidence") or 0.0),
    }


__all__ = ["build_resolved_bc_identity_update"]
