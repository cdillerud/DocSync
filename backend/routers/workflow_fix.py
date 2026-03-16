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


@router.post("/dry-run")
async def dry_run():
    """Preview how many stuck 'captured' docs would be fixed."""
    db = get_db()

    stuck = await db.hub_documents.find(
        {"workflow_status": "captured"},
        {"_id": 0, "id": 1, "status": 1, "doc_type": 1, "document_type": 1,
         "automation_decision": 1, "auto_cleared": 1, "routing_status": 1,
         "suggested_job_type": 1, "file_name": 1},
    ).to_list(5000)

    changes = {}
    for doc in stuck:
        new_ws = _derive_status(doc)
        if new_ws != "captured":
            changes.setdefault(new_ws, 0)
            changes[new_ws] += 1

    return {
        "total_stuck": len(stuck),
        "would_fix": sum(changes.values()),
        "would_remain_captured": len(stuck) - sum(changes.values()),
        "target_statuses": changes,
    }


@router.post("/run")
async def run_fix():
    """Batch-fix all documents stuck in 'captured' workflow_status."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    stuck = await db.hub_documents.find(
        {"workflow_status": "captured"},
        {"_id": 0, "id": 1, "status": 1, "doc_type": 1, "document_type": 1,
         "automation_decision": 1, "auto_cleared": 1, "routing_status": 1,
         "suggested_job_type": 1},
    ).to_list(5000)

    fixed = 0
    by_status = {}

    for doc in stuck:
        new_ws = _derive_status(doc)
        if new_ws != "captured":
            await db.hub_documents.update_one(
                {"id": doc["id"]},
                {"$set": {
                    "workflow_status": new_ws,
                    "workflow_status_updated_utc": now,
                },
                "$push": {
                    "workflow_history": {
                        "timestamp": now,
                        "from_status": "captured",
                        "to_status": new_ws,
                        "event": "batch_workflow_fix",
                        "actor": "system",
                        "reason": f"Batch fix: status={doc.get('status')}, decision={doc.get('automation_decision')}",
                    }
                }},
            )
            fixed += 1
            by_status.setdefault(new_ws, 0)
            by_status[new_ws] += 1

    return {
        "total_stuck": len(stuck),
        "fixed": fixed,
        "remained_captured": len(stuck) - fixed,
        "by_new_status": by_status,
        "timestamp": now,
    }
