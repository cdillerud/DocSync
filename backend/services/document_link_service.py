"""Manual document-to-Business-Central linking with fail-closed entity selection."""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from deps import get_db
from services.bc_link_service import link_document_to_bc as _link_document_to_bc

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


_ENTITY_BY_DOC_TYPE = {
    "AP_INVOICE": "purchaseInvoices",
    "AP_INVOICE_DRAFT": "purchaseInvoices",
    "AP_Invoice": "purchaseInvoices",
    "PurchaseInvoice": "purchaseInvoices",
    "PURCHASE_INVOICE": "purchaseInvoices",
    "PURCHASE_ORDER": "purchaseOrders",
    "Purchase_Order": "purchaseOrders",
    "PurchaseOrder": "purchaseOrders",
    "SALES_ORDER": "salesOrders",
    "SalesOrder": "salesOrders",
    "DS_Sales_Order": "salesOrders",
    "WH_Sales_Order": "salesOrders",
    "SALES_INVOICE": "salesInvoices",
    "SalesInvoice": "salesInvoices",
    "AR_Invoice": "salesInvoices",
}


def _infer_bc_entity(doc: dict) -> str:
    explicit = str(doc.get("bc_entity") or "").strip()
    if explicit:
        return explicit

    for key in ("document_type", "doc_type", "suggested_job_type"):
        value = str(doc.get(key) or "").strip()
        if value in _ENTITY_BY_DOC_TYPE:
            return _ENTITY_BY_DOC_TYPE[value]
    return ""


async def link_document(doc_id: str, bc_record_id: str):
    """Manually attach a document to an explicitly identified BC SystemId."""
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    if not str(bc_record_id or "").strip():
        raise HTTPException(status_code=400, detail="BC record SystemId is required")

    bc_entity = _infer_bc_entity(doc)
    if not bc_entity:
        raise HTTPException(
            status_code=400,
            detail=(
                "Cannot determine the Business Central entity for this document. "
                "Correct the document type before linking; no default entity will be guessed."
            ),
        )

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found")

    link_result = await _link_document_to_bc(
        bc_record_id=bc_record_id,
        share_link=doc.get("sharepoint_share_link_url", ""),
        file_name=doc.get("file_name") or f"{doc_id}.pdf",
        file_content=file_path.read_bytes(),
        bc_entity=bc_entity,
    )

    if link_result.get("success"):
        now = datetime.now(timezone.utc).isoformat()
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "bc_record_id": bc_record_id,
                "bc_entity": bc_entity,
                "bc_link_method": "manual_system_id",
                "bc_linked_at": now,
                "status": "LinkedToBC",
                "updated_utc": now,
            }},
        )

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {"document": updated_doc, "link_result": link_result}
