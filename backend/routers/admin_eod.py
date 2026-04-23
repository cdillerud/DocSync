"""GPI Hub — Admin EOD router (Lane C Step 3B).

Endpoint-triggered only. Not scheduled. Feature-flagged behind EOD_ENABLED.
"""

from __future__ import annotations

import os
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel


router = APIRouter(prefix="/admin/eod", tags=["EOD"])


def _eod_enabled() -> bool:
    return os.environ.get("EOD_ENABLED", "false").lower() == "true"


class RunEodRequest(BaseModel):
    steps: Optional[list[str]] = None
    dry_run: bool = False
    force: bool = False   # allows flag-off preview-environment smoke tests


@router.post("/run")
async def run_eod(payload: RunEodRequest):
    """Execute the 5-step EOD controller. Returns aggregate report."""
    if not _eod_enabled() and not payload.force:
        raise HTTPException(
            status_code=501,
            detail="EOD_ENABLED=false; set EOD_ENABLED=true (or force=true) to run.",
        )
    from deps import get_db
    from workflows.batch.eod_controller import EodController

    db = get_db()
    controller = EodController(db)
    try:
        return await controller.run_close_day(
            steps=payload.steps, dry_run=payload.dry_run
        )
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))


@router.get("/last-run")
async def last_run(
    step: Optional[str] = Query(None, description="Optional step name filter"),
):
    """Return the latest eod_run_log entry (overall or per step)."""
    if not _eod_enabled():
        raise HTTPException(
            status_code=501,
            detail="EOD_ENABLED=false; set EOD_ENABLED=true to query run log.",
        )
    from deps import get_db
    from workflows.batch.eod_controller import get_last_run as _last

    db = get_db()
    try:
        return await _last(db, step=step)
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
