"""Metadata-only recovery for an AP Purchase Invoice draft already created in BC.

``DraftNeedsMetadata`` means the BC draft exists and its exact SystemId is known,
but the existing SharePoint item's parity metadata did not move from the prior
identity to the Purchase Invoice draft identity. Recovery never creates/recreates
a BC invoice and never uploads file bytes; it only PATCHes existing list-item
metadata and restores the draft-ready state.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from services.ap_purchase_invoice_identity_service import (
    build_ap_purchase_invoice_identity_update,
)
from services.sharepoint_parity_resync_service import (
    resync_existing_sharepoint_parity_metadata,
)


class DraftMetadataRecoveryError(RuntimeError):
    pass


async def recover_draft_purchase_invoice_metadata(
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
            "bc_purchase_invoice": 1,
            "bc_purchase_invoice_no": 1,
            "bc_record_no": 1,
            "bc_system_id": 1,
            "bc_record_id": 1,
        },
    )
    if not document:
        raise DraftMetadataRecoveryError(f"Document {doc_id} not found")
    if document.get("status") != "DraftNeedsMetadata":
        raise DraftMetadataRecoveryError(
            f"Document {doc_id} is not in DraftNeedsMetadata state"
        )

    nested = document.get("bc_purchase_invoice") or {}
    draft_number = str(
        document.get("bc_record_no")
        or document.get("bc_purchase_invoice_no")
        or nested.get("bc_record_no")
        or ""
    ).strip()
    draft_system_id = str(
        document.get("bc_system_id")
        or document.get("bc_record_id")
        or nested.get("bc_system_id")
        or ""
    ).strip()
    if not draft_number or not draft_system_id:
        raise DraftMetadataRecoveryError(
            f"Document {doc_id} lacks exact BC Purchase Invoice draft identity"
        )

    identity = build_ap_purchase_invoice_identity_update(
        draft_number,
        draft_system_id,
        posted=False,
    )

    # PATCH existing SharePoint metadata only. No BC create/post and no upload.
    await resync_existing_sharepoint_parity_metadata(
        doc_id,
        db,
        identity_update=identity,
    )

    now = datetime.now(timezone.utc).isoformat()
    audit_event = {
        "timestamp": now,
        "event": "draft_metadata_recovered",
        "actor": "system",
        "metadata": {
            "draft_number": draft_number,
            "draft_system_id": draft_system_id,
            "sharepoint_metadata_resynced": True,
        },
    }
    await db.hub_documents.update_one(
        {
            "id": doc_id,
            "status": "DraftNeedsMetadata",
            "bc_system_id": draft_system_id,
        },
        {
            "$set": {
                **identity,
                "status": "ReadyForPost",
                "workflow_status": "ready_for_post",
                "sharepoint_metadata_error": None,
                "draft_metadata_recovered_at": now,
                "updated_utc": now,
            },
            "$push": {"workflow_history": audit_event},
        },
    )

    return {
        "success": True,
        "recovered": True,
        "drafted": True,
        "document_id": doc_id,
        "bc_record_no": draft_number,
        "bc_system_id": draft_system_id,
        "import_ready": True,
        "status": "ReadyForPost",
    }


__all__ = [
    "recover_draft_purchase_invoice_metadata",
    "DraftMetadataRecoveryError",
]
