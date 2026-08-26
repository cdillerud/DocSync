"""Dispatch AP BC-created recovery states before generic document retry.

These states all represent a BC record that must be preserved:
- ``DraftNeedsMetadata``: Purchase Invoice draft exists; only SharePoint metadata is pending.
- ``PostedNeedsIdentity``: BC has posted; actual table-122 identity is pending.
- ``PostedNeedsMetadata``: BC has posted and identity is known; SharePoint metadata is pending.

None may flow through ordinary document retry because that path can refresh PO
routing and delivery state. Recovery here is deliberately narrow: no BC create,
no BC repost, and no SharePoint file upload. All other states return ``None`` so
existing retry behavior remains unchanged.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid


_SAFE_AP_RECOVERY_STATES = {
    "DraftNeedsMetadata",
    "PostedNeedsIdentity",
    "PostedNeedsMetadata",
}


def _recovery_type(status: str) -> str:
    if status == "DraftNeedsMetadata":
        return "draft_metadata"
    if status == "PostedNeedsIdentity":
        return "posted_identity"
    return "posted_metadata"


async def dispatch_ap_posted_recovery_if_needed(
    document_id: str,
    db,
    document: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    """Compatibility-named dispatcher for all BC-preserving AP recovery states."""
    status = str((document or {}).get("status") or "").strip()
    if status not in _SAFE_AP_RECOVERY_STATES:
        return None

    started = datetime.now(timezone.utc).isoformat()
    workflow_id = str(uuid.uuid4())
    recovery_type = _recovery_type(status)

    try:
        if status == "DraftNeedsMetadata":
            from services.ap_draft_metadata_recovery_service import (
                recover_draft_purchase_invoice_metadata,
            )
            recovery = await recover_draft_purchase_invoice_metadata(document_id, db)
        elif status == "PostedNeedsIdentity":
            from services.ap_posted_identity_recovery_service import (
                recover_posted_purchase_invoice_identity,
            )
            recovery = await recover_posted_purchase_invoice_identity(document_id, db)
        else:
            from services.ap_posted_metadata_recovery_service import (
                recover_posted_purchase_invoice_metadata,
            )
            recovery = await recover_posted_purchase_invoice_metadata(document_id, db)

        ended = datetime.now(timezone.utc).isoformat()
        await db.hub_workflow_runs.insert_one({
            "id": workflow_id,
            "document_id": document_id,
            "workflow_name": "ap_bc_preserving_recovery",
            "recovery_type": recovery_type,
            "started_utc": started,
            "ended_utc": ended,
            "status": "Completed" if recovery.get("import_ready") else "CompletedWithWarnings",
            "document_status": recovery.get("status"),
            "posted": bool(recovery.get("posted", status.startswith("Posted"))),
            "drafted": bool(recovery.get("drafted", status == "DraftNeedsMetadata")),
            "import_ready": bool(recovery.get("import_ready")),
            "bc_record_no": recovery.get("bc_record_no"),
            "bc_system_id": recovery.get("bc_system_id"),
        })
        return {
            "success": True,
            "workflow_id": workflow_id,
            "recovery_dispatched": True,
            "recovery_type": recovery_type,
            **recovery,
        }
    except Exception as exc:
        ended = datetime.now(timezone.utc).isoformat()
        await db.hub_workflow_runs.insert_one({
            "id": workflow_id,
            "document_id": document_id,
            "workflow_name": "ap_bc_preserving_recovery",
            "recovery_type": recovery_type,
            "started_utc": started,
            "ended_utc": ended,
            "status": "Failed",
            "document_status": status,
            "posted": status.startswith("Posted"),
            "drafted": status == "DraftNeedsMetadata",
            "import_ready": False,
            "error": str(exc),
        })
        raise


__all__ = ["dispatch_ap_posted_recovery_if_needed"]
