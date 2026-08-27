"""Metadata-only recovery for AP invoices already posted in Business Central.

This handles ``PostedNeedsMetadata``. The real posted Purchase Invoice identity is
already known and BC posting is already confirmed. Recovery must therefore never
post again and never upload document bytes; it only PATCHes parity metadata on the
existing SharePoint item and then finalizes the Hub readiness state.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from services.ap_purchase_invoice_identity_service import (
    build_ap_purchase_invoice_identity_update,
)
from services.sharepoint_parity_resync_service import (
    resync_existing_sharepoint_parity_metadata,
)


class PostedMetadataRecoveryError(RuntimeError):
    pass


async def recover_posted_purchase_invoice_metadata(
    document_id: str,
    db,
) -> Dict[str, Any]:
    doc_id = str(document_id or "").strip()
    if not doc_id:
        raise ValueError("document_id is required")

    document = await db.hub_documents.find_one(
        {"id": doc_id},
        {
            "_id": 0,
            "id": 1,
            "status": 1,
            "bc_true_post_confirmed": 1,
            "bc_api_id": 1,
            "bc_record_no": 1,
            "bc_purchase_invoice_no": 1,
            "bc_system_id": 1,
            "bc_record_id": 1,
        },
    )
    if not document:
        raise PostedMetadataRecoveryError(f"Document {doc_id} not found")
    if document.get("status") != "PostedNeedsMetadata":
        raise PostedMetadataRecoveryError(
            f"Document {doc_id} is not in PostedNeedsMetadata state"
        )
    if not document.get("bc_true_post_confirmed"):
        raise PostedMetadataRecoveryError(
            f"Document {doc_id} does not contain confirmed BC post evidence"
        )

    posted_number = str(
        document.get("bc_record_no") or document.get("bc_purchase_invoice_no") or ""
    ).strip()
    posted_system_id = str(
        document.get("bc_system_id") or document.get("bc_record_id") or ""
    ).strip()
    if not posted_number or not posted_system_id:
        raise PostedMetadataRecoveryError(
            f"Document {doc_id} lacks the real posted Purchase Invoice identity"
        )

    identity = build_ap_purchase_invoice_identity_update(
        posted_number,
        posted_system_id,
        posted=True,
    )

    # This is the only external action. The resync service PATCHes the existing
    # list item by drive_id/item_id; it has no upload code path.
    await resync_existing_sharepoint_parity_metadata(
        doc_id,
        db,
        identity_update=identity,
    )

    now = datetime.now(timezone.utc).isoformat()
    audit_event = {
        "timestamp": now,
        "event": "posted_metadata_recovered",
        "actor": "system",
        "metadata": {
            "bc_api_id": document.get("bc_api_id"),
            "posted_number": posted_number,
            "posted_system_id": posted_system_id,
            "sharepoint_metadata_resynced": True,
        },
    }

    await db.hub_documents.update_one(
        {
            "id": doc_id,
            "status": "PostedNeedsMetadata",
            "bc_system_id": posted_system_id,
        },
        {
            "$set": {
                **identity,
                "status": "Posted",
                "workflow_status": "posted",
                "bc_posting_status": "posted",
                "bc_posting_error": None,
                "auto_post_error": None,
                "bc_true_post_confirmed": True,
                "sharepoint_metadata_error": None,
                "posted_metadata_recovered_at": now,
                "updated_utc": now,
            },
            "$push": {"workflow_history": audit_event},
        },
    )

    return {
        "success": True,
        "recovered": True,
        "posted": True,
        "document_id": doc_id,
        "bc_record_no": posted_number,
        "bc_system_id": posted_system_id,
        "import_ready": True,
        "status": "Posted",
    }


__all__ = [
    "recover_posted_purchase_invoice_metadata",
    "PostedMetadataRecoveryError",
]
