"""
Workflow Status Fix Router — Batch-fix documents stuck in 'captured' workflow_status.

After the intake pipeline runs, workflow_status should reflect the processing result.
Documents that were processed but left with workflow_status='captured' need updating.

Endpoints:
  POST /api/workflow-fix/dry-run   — Preview what would change
  POST /api/workflow-fix/run       — Apply the fix
"""

import logging
from datetime import datetime, timezone

from fastapi import APIRouter
from deps import get_db

logger = logging.getLogger("workflow_fix")
router = APIRouter(prefix="/workflow-fix", tags=["Workflow Fix"])


def _derive_status(doc: dict) -> str:
    """Derive correct workflow_status from existing document fields."""
    status = (doc.get("status") or "").lower()
    decision = (doc.get("automation_decision") or "")
    auto_cleared = doc.get("auto_cleared", False)
    routing_status = doc.get("routing_status")

    if auto_cleared:
        return "completed"
    if status in ("completed", "posted", "archived"):
        return "completed"
    if status == "exception":
        return "exception"
    if status in ("readytolink", "linkedtobc"):
        return "ready_for_approval"
    if status == "storedinsp":
        return "processed"
    if status in ("validated", "validationpassed"):
        return "validation_passed"
    if routing_status == "auto_process":
        return "validation_passed"
    if decision == "auto_link":
        return "validation_passed"
    if status == "needsreview":
        return "needs_review"
    # Has been through classification at minimum
    if doc.get("doc_type") or doc.get("document_type") or doc.get("suggested_job_type"):
        return "classified"
    return "captured"


# Map workflow_status to the correct top-level status field value
_WF_TO_STATUS = {
    "completed": "Completed",
    "validation_passed": "ValidationPassed",
    "processed": "StoredInSP",
    "ready_for_approval": "ReadyToLink",
    "exception": "Exception",
    "needs_review": "NeedsReview",
    "classified": "Classified",
}


@router.post("/dry-run")
async def dry_run():
    """Preview how many stuck docs would be fixed."""
    db = get_db()

    # Find docs where workflow_status doesn't match what it should be
    stuck = await db.hub_documents.find(
        {"$or": [
            {"workflow_status": "captured"},
            # Docs where status says NeedsReview but they actually passed
            {"status": "NeedsReview", "auto_cleared": True},
            {"status": "NeedsReview", "routing_status": "auto_process"},
            {"status": "NeedsReview", "automation_decision": "auto_link"},
            # Docs where workflow_status was fixed but status still says NeedsReview
            {"status": "NeedsReview", "workflow_status": {"$in": ["validation_passed", "processed", "completed", "ready_for_approval"]}},
        ]},
        {"_id": 0, "id": 1, "status": 1, "doc_type": 1, "document_type": 1,
         "automation_decision": 1, "auto_cleared": 1, "routing_status": 1,
         "suggested_job_type": 1, "file_name": 1, "workflow_status": 1},
    ).to_list(10000)

    changes = {}
    for doc in stuck:
        new_ws = _derive_status(doc)
        new_status = _WF_TO_STATUS.get(new_ws)
        current_ws = doc.get("workflow_status", "")
        current_status = doc.get("status", "")
        if new_ws != current_ws or (new_status and new_status != current_status):
            key = f"{new_ws} (status={new_status})"
            changes.setdefault(key, 0)
            changes[key] += 1

    return {
        "total_found": len(stuck),
        "would_fix": sum(changes.values()),
        "would_remain": len(stuck) - sum(changes.values()),
        "target_statuses": changes,
    }


@router.post("/run")
async def run_fix():
    """Batch-fix documents with incorrect workflow_status and status."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    stuck = await db.hub_documents.find(
        {"$or": [
            {"workflow_status": "captured"},
            {"status": "NeedsReview", "auto_cleared": True},
            {"status": "NeedsReview", "routing_status": "auto_process"},
            {"status": "NeedsReview", "automation_decision": "auto_link"},
            {"status": "NeedsReview", "workflow_status": {"$in": ["validation_passed", "processed", "completed", "ready_for_approval"]}},
        ]},
        {"_id": 0, "id": 1, "status": 1, "doc_type": 1, "document_type": 1,
         "automation_decision": 1, "auto_cleared": 1, "routing_status": 1,
         "suggested_job_type": 1, "workflow_status": 1},
    ).to_list(10000)

    fixed = 0
    by_status = {}

    for doc in stuck:
        new_ws = _derive_status(doc)
        new_status = _WF_TO_STATUS.get(new_ws)
        current_ws = doc.get("workflow_status", "")
        current_status = doc.get("status", "")

        if new_ws == current_ws and (not new_status or new_status == current_status):
            continue

        update_set = {
            "workflow_status": new_ws,
            "workflow_status_updated_utc": now,
        }
        if new_status and new_status != current_status:
            update_set["status"] = new_status

        await db.hub_documents.update_one(
            {"id": doc["id"]},
            {"$set": update_set,
            "$push": {
                "workflow_history": {
                    "timestamp": now,
                    "from_status": current_ws,
                    "to_status": new_ws,
                    "event": "batch_workflow_fix",
                    "actor": "system",
                    "reason": f"Batch fix: old_status={current_status}, decision={doc.get('automation_decision')}, auto_cleared={doc.get('auto_cleared')}",
                }
            }},
        )
        fixed += 1
        key = f"{new_ws} (status={new_status})"
        by_status.setdefault(key, 0)
        by_status[key] += 1

    return {
        "total_found": len(stuck),
        "fixed": fixed,
        "remained": len(stuck) - fixed,
        "by_new_status": by_status,
        "timestamp": now,
    }
