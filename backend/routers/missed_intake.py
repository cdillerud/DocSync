"""Admin endpoints for the missed-document safety net.

See services/missed_document_intake_service.py.
"""
from fastapi import APIRouter, Depends, Query

from deps import get_db
from services.auth_deps import require_admin
from services.missed_document_intake_service import (
    LOG_COLLECTION, RUNS, backfill_square9_gaps, poll_drop_folder, start_background_run,
)

router = APIRouter(prefix="/missed-intake", tags=["Missed Intake"])


@router.post("/square9-backfill")
async def run_square9_backfill(limit: int = Query(50, ge=1, le=500), _admin=Depends(require_admin)):
    """Start ingesting Square9 AP documents Hub never received (triage Bucket C)."""
    return start_background_run("square9_backfill", backfill_square9_gaps(limit=limit))


@router.post("/drop-folder/poll")
async def run_drop_folder_poll(limit: int = Query(100, ge=1, le=500), _admin=Depends(require_admin)):
    """Start ingesting new files from the Hub Drop Folder."""
    return start_background_run("drop_folder", poll_drop_folder(limit=limit))


@router.get("/log")
async def missed_intake_log(limit: int = Query(100, ge=1, le=1000), _admin=Depends(require_admin)):
    """Most recent safety-net intake attempts."""
    rows = await get_db()[LOG_COLLECTION].find({}, {"_id": 0}).sort("updated_at", -1).limit(limit).to_list(limit)
    return {"count": len(rows), "entries": rows}


@router.get("/status")
async def missed_intake_status(_admin=Depends(require_admin)):
    """State of the latest safety-net runs."""
    return RUNS
