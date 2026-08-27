"""Identity-only recovery for AP invoices already posted in Business Central.

This service is intentionally read-only toward BC and never uploads file bytes.
It exists for the narrow ``PostedNeedsIdentity`` state: BC has already confirmed
posting, but the real table-122 Purch. Inv. Header SystemId/final number was not
yet visible through the automate API. Recovery re-runs only that identity lookup,
then patches parity metadata on the *existing* SharePoint item before the Hub may
become ImportReady/Posted.
"""

from datetime import datetime, timezone
from typing import Any, Dict

from services.ap_purchase_invoice_identity_service import (
    build_ap_purchase_invoice_identity_update,
)
from services.bc_posted_purchase_invoice_identity_service import (
    resolve_posted_purchase_invoice_identity,
)
from services.sharepoint_parity_resync_service import (
    resync_existing_sharepoint_parity_metadata,
)


class PostedIdentityRecoveryError(RuntimeError):
    pass


def _metadata_blocked_identity(identity: Dict[str, Any]) -> Dict[str, Any]:
    """Preserve the proven posted identity while failing readiness closed."""
    blocked = dict(identity)
    blocked.update({
        "GPI_Status": "PostedNeedsMetadata",
        "ImportReady": False,
        "import_ready": False,
        "delivery_status": "PostedNeedsMetadata",
    })
    return blocked


async def recover_posted_purchase_invoice_identity(
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
            "workflow_status": 1,
            "bc_posting_status": 1,
            "bc_true_post_confirmed": 1,
            "bc_api_id": 1,
            "bc_draft_invoice_no": 1,
        },
    )
    if not document:
        raise PostedIdentityRecoveryError(f"Document {doc_id} not found")

    if document.get("status") != "PostedNeedsIdentity":
        raise PostedIdentityRecoveryError(
            f"Document {doc_id} is not in PostedNeedsIdentity state"
        )
    if not document.get("bc_true_post_confirmed"):
        raise PostedIdentityRecoveryError(
            f"Document {doc_id} does not contain confirmed BC post evidence"
        )

    api_id = str(document.get("bc_api_id") or "").strip()
    if not api_id:
        raise PostedIdentityRecoveryError(
            f"Document {doc_id} has no bc_api_id for posted identity recovery"
        )

    resolved = await resolve_posted_purchase_invoice_identity(api_id)
    posted_system_id = str(resolved.get("posted_system_id") or "").strip()
    posted_number = str(resolved.get("posted_number") or "").strip()
    if not posted_system_id or not posted_number:
        raise PostedIdentityRecoveryError(
            f"Posted identity resolver returned incomplete identity for {doc_id}"
        )

    identity = build_ap_purchase_invoice_identity_update(
        posted_number,
        posted_system_id,
        posted=True,
    )
    now = datetime.now(timezone.utc).isoformat()

    # The real posted identity is now known, but the delivery contract is not
    # complete until the already-uploaded SharePoint list item carries that same
    # table-122 identity. This function only PATCHes metadata; it never uploads.
    try:
        await resync_existing_sharepoint_parity_metadata(
            doc_id,
            db,
            identity_update=identity,
        )
    except Exception as exc:
        blocked = _metadata_blocked_identity(identity)
        audit_event = {
            "timestamp": now,
            "event": "posted_identity_recovered_metadata_pending",
            "actor": "system",
            "metadata": {
                "bc_api_id": api_id,
                "posted_number": posted_number,
                "posted_system_id": posted_system_id,
                "metadata_error": str(exc)[:1000],
            },
        }
        await db.hub_documents.update_one(
            {"id": doc_id, "status": "PostedNeedsIdentity", "bc_api_id": api_id},
            {
                "$set": {
                    **blocked,
                    "status": "PostedNeedsMetadata",
                    "workflow_status": "posted_needs_metadata",
                    "bc_posting_status": "posted_needs_metadata",
                    "bc_posting_error": str(exc),
                    "auto_post_error": str(exc),
                    "bc_true_post_confirmed": True,
                    "bc_api_id": api_id,
                    "bc_record_no": posted_number,
                    "bc_purchase_invoice_no": posted_number,
                    "bc_system_id": posted_system_id,
                    "bc_record_id": posted_system_id,
                    "bc_post_identity_recovered_at": now,
                    "bc_post_identity_resolution_attempts": resolved.get("attempts"),
                    "sharepoint_metadata_error": str(exc),
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
            "bc_api_id": api_id,
            "bc_record_no": posted_number,
            "bc_system_id": posted_system_id,
            "import_ready": False,
            "status": "PostedNeedsMetadata",
            "metadata_error": str(exc),
        }

    update = {
        **identity,
        "status": "Posted",
        "workflow_status": "posted",
        "bc_posting_status": "posted",
        "bc_posting_error": None,
        "auto_post_error": None,
        "bc_true_post_confirmed": True,
        "bc_api_id": api_id,
        "bc_record_no": posted_number,
        "bc_purchase_invoice_no": posted_number,
        "bc_system_id": posted_system_id,
        "bc_record_id": posted_system_id,
        "bc_post_identity_recovered_at": now,
        "bc_post_identity_resolution_attempts": resolved.get("attempts"),
        "sharepoint_metadata_error": None,
        "updated_utc": now,
    }
    audit_event = {
        "timestamp": now,
        "event": "posted_identity_recovered",
        "actor": "system",
        "metadata": {
            "bc_api_id": api_id,
            "posted_number": posted_number,
            "posted_system_id": posted_system_id,
            "attempts": resolved.get("attempts"),
            "sharepoint_metadata_resynced": True,
        },
    }

    await db.hub_documents.update_one(
        {"id": doc_id, "status": "PostedNeedsIdentity", "bc_api_id": api_id},
        {
            "$set": update,
            "$push": {"workflow_history": audit_event},
        },
    )

    return {
        "success": True,
        "recovered": True,
        "document_id": doc_id,
        "bc_api_id": api_id,
        "bc_record_no": posted_number,
        "bc_system_id": posted_system_id,
        "import_ready": True,
        "status": "Posted",
    }


__all__ = [
    "recover_posted_purchase_invoice_identity",
    "PostedIdentityRecoveryError",
]
