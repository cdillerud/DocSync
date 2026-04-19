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
    build_phase_b_readiness_report,
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


@router.get("/phase-b-readiness")
async def phase_b_readiness(
    days: int = Query(7, ge=1, le=90),
    min_coverage: int = Query(5, ge=2, le=100),
    format: str = Query("json", pattern="^(json|markdown)$"),
):
    """Phase-B extraction readiness matrix — ranks every observed
    caller × doc_type pair, categorizes as must_preserve / should_cover /
    edge_case, and emits a verdict. Set `format=markdown` to get a
    paste-ready PR-description block in `text/markdown`."""
    report = await build_phase_b_readiness_report(
        get_db(), days=days, min_coverage=min_coverage,
    )
    if format == "markdown":
        from fastapi.responses import PlainTextResponse
        return PlainTextResponse(report["markdown"], media_type="text/markdown")
    return report
