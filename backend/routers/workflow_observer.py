"""
Workflow Observer Admin Router (v2.5.2)
────────────────────────────────────────

Read-only admin endpoints over `workflow_state_observations` — used
to de-risk Phase B of the Orchestration Extraction by showing which
call sites exercise `_update_standard_workflow_status` in production.
"""

from fastapi import APIRouter, Query
from typing import Optional

from deps import get_db
from services.workflow_state_observer import (
    get_observer_summary,
    list_recent_observations,
)

router = APIRouter(prefix="/admin/workflow-observer", tags=["Admin"])


@router.get("/summary")
async def observer_summary(days: int = Query(7, ge=1, le=90)):
    """Aggregate observations by caller + doc_type in the last `days` days."""
    return await get_observer_summary(get_db(), days=days)


@router.get("/recent")
async def observer_recent(
    limit: int = Query(50, ge=1, le=500),
    caller_func: Optional[str] = Query(None),
):
    """Tail of recent observations (newest first). Optional `caller_func` filter."""
    rows = await list_recent_observations(
        get_db(), limit=limit, caller_func=caller_func,
    )
    return {"total": len(rows), "observations": rows}
