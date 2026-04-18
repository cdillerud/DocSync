"""
GPI Document Hub — Learning Core Router (U1, v2.4.1)
─────────────────────────────────────────────────────

Unified cross-domain event log API. Sits alongside the legacy
`/api/intake/learning/events` and AP learning dashboard endpoints
during the 30-day dual-write window.
"""

from fastapi import APIRouter, Query
from typing import Optional

from services.learning_core import list_events, get_domain_summary, DOMAINS

router = APIRouter(prefix="/learning", tags=["learning-core"])


@router.get("/events")
async def get_events(
    domain: Optional[str] = Query(None, description=f"One of {sorted(DOMAINS)}"),
    event_type: Optional[str] = None,
    scope_type: Optional[str] = None,
    scope_value: Optional[str] = None,
    since_iso: Optional[str] = None,
    limit: int = Query(100, le=500),
):
    """Unified cross-domain event feed.

    Filter by any combination of domain / event_type / scope (e.g.
    all `suggestion_accepted` for customer C-10250, or all AP events
    in the last 24h).
    """
    events = await list_events(
        domain=domain,
        event_type=event_type,
        scope_type=scope_type,
        scope_value=scope_value,
        since_iso=since_iso,
        limit=limit,
    )
    return {"total": len(events), "events": events}


@router.get("/events/summary")
async def events_summary():
    """Dashboard aggregates: total, by_domain, top_event_types, recent."""
    return await get_domain_summary()
