"""Dispatch AP post-success recovery states without entering generic retry paths.

``PostedNeedsIdentity`` and ``PostedNeedsMetadata`` both mean Business Central has
already posted the invoice. They must never flow through ordinary document retry,
which may refresh PO routing or upload delivery state. This dispatcher recognizes
only those two states and invokes their narrow, no-repost/no-reupload recovery
services. All other states return ``None`` so existing retry behavior is unchanged.
"""

from datetime import datetime, timezone
from typing import Any, Dict, Optional
import uuid


_POST_SUCCESS_RECOVERY_STATES = {"PostedNeedsIdentity", "PostedNeedsMetadata"}


async def dispatch_ap_posted_recovery_if_needed(
    document_id: str,
    db,
    document: Dict[str, Any],
) -> Optional[Dict[str, Any]]:
    status = str((document or {}).get("status") or "").strip()
    if status not in _POST_SUCCESS_RECOVERY_STATES:
        return None

    started = datetime.now(timezone.utc).isoformat()
    workflow_id = str(uuid.uuid4())

    try:
        if status == "PostedNeedsIdentity":
            from services.ap_posted_identity_recovery_service import (
                recover_posted_purchase_invoice_identity,
            )

            recovery = await recover_posted_purchase_invoice_identity(document_id, db)
            recovery_type = "posted_identity"
        else:
            from services.ap_posted_metadata_recovery_service import (
                recover_posted_purchase_invoice_metadata,
            )

            recovery = await recover_posted_purchase_invoice_metadata(document_id, db)
            recovery_type = "posted_metadata"

        ended = datetime.now(timezone.utc).isoformat()
        await db.hub_workflow_runs.insert_one({
            "id": workflow_id,
            "document_id": document_id,
            "workflow_name": "ap_posted_recovery",
            "recovery_type": recovery_type,
            "started_utc": started,
            "ended_utc": ended,
            "status": "Completed" if recovery.get("import_ready") else "CompletedWithWarnings",
            "document_status": recovery.get("status"),
            "posted": bool(recovery.get("posted", True)),
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
            "workflow_name": "ap_posted_recovery",
            "recovery_type": (
                "posted_identity" if status == "PostedNeedsIdentity" else "posted_metadata"
            ),
            "started_utc": started,
            "ended_utc": ended,
            "status": "Failed",
            "document_status": status,
            "posted": True,
            "import_ready": False,
            "error": str(exc),
        })
        raise


__all__ = ["dispatch_ap_posted_recovery_if_needed"]
