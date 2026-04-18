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
from services.drift_alert_service import (
    run_drift_scan,
    list_drift_alerts,
    acknowledge_alert,
    resolve_alert,
    get_drift_summary,
)

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


# ─────────────────────────────────────────────────────────────
# v2.5.0 — Drift Alerts
# ─────────────────────────────────────────────────────────────

@router.post("/drift/scan")
async def drift_scan():
    """Run a full drift-detection scan. Safe to call repeatedly —
    alerts are upserted by (scope, alert_type) so no duplicates.
    Normally fires on the nightly scheduler."""
    return await run_drift_scan(actor="user")


@router.get("/drift/alerts")
async def drift_alerts(
    status: Optional[str] = Query("open", description="open | acknowledged | resolved | all"),
    domain: Optional[str] = None,
    severity: Optional[str] = None,
    scope_value: Optional[str] = None,
    limit: int = Query(100, le=500),
):
    """List drift alerts. Default filter returns only open ones."""
    alerts = await list_drift_alerts(
        status=status, domain=domain, severity=severity,
        scope_value=scope_value, limit=limit,
    )
    return {"total": len(alerts), "alerts": alerts}


@router.get("/drift/summary")
async def drift_summary():
    """Dashboard aggregates for the drift-alerts panel."""
    return await get_drift_summary()


@router.post("/drift/alerts/{alert_id}/acknowledge")
async def drift_ack(alert_id: str):
    res = await acknowledge_alert(alert_id)
    if res.get("error"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=res["error"])
    return res


@router.post("/drift/alerts/{alert_id}/resolve")
async def drift_resolve(alert_id: str):
    res = await resolve_alert(alert_id)
    if res.get("error"):
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=res["error"])
    return res


# ─────────────────────────────────────────────────────────────
# U2 — Shared Fingerprint Service (v2.5.1)
# ─────────────────────────────────────────────────────────────

@router.post("/fingerprints/rebuild")
async def fingerprints_rebuild(
    scope_type: str = Query("customer", description="customer | vendor"),
):
    """Rebuild all fingerprints for the given scope_type."""
    from services.learning_core import rebuild_all
    return await rebuild_all(scope_type)


@router.get("/fingerprints/similar")
async def fingerprints_similar(
    scope_type: str = Query("customer"),
    scope_value: Optional[str] = None,
    top_k: int = Query(3, le=10),
):
    """Find peer fingerprints most similar to the given scope. Useful
    both for customer cold-start peer exploration and AP vendor-alias
    discovery."""
    from services.learning_core import get_or_build, find_similar
    if not scope_value:
        from fastapi import HTTPException
        raise HTTPException(status_code=400, detail="scope_value is required")
    fp = await get_or_build(scope_type, scope_value)
    query_tokens: list = list((fp.get("tf") or {}).keys())
    matches = await find_similar(
        query_tokens,
        scope_type=scope_type,
        top_k=top_k,
        exclude_scope_value=scope_value,
    )
    return {"query_scope": scope_value, "token_count": len(query_tokens), "matches": matches}
