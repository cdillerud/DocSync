"""
GPI Document Hub — Learning Core Router (U1, v2.4.1)
─────────────────────────────────────────────────────

Unified cross-domain event log API. Sits alongside the legacy
`/api/intake/learning/events` and AP learning dashboard endpoints
during the 30-day dual-write window.
"""

from fastapi import APIRouter, Query
from pydantic import BaseModel, Field
from typing import Any, Dict, List, Optional

from workflows.core.learning_core import list_events, get_domain_summary, DOMAINS
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


@router.get("/reviewers/leaderboard")
async def reviewers_leaderboard(
    days: int = Query(7, ge=1, le=90),
    limit: int = Query(10, ge=1, le=100),
):
    """Who's been giving the most feedback in the last `days` days?
    Aggregates `learning_events_v2` by actor across all domains, returns
    a ranked leaderboard with per-domain + top-event-type breakdown."""
    from workflows.core.learning_core import get_reviewer_leaderboard
    return await get_reviewer_leaderboard(days=days, limit=limit)


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
    from workflows.core.learning_core import rebuild_all
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
    from workflows.core.learning_core import get_or_build, find_similar
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


# ─────────────────────────────────────────────────────────────
# U3 — Shared Pattern Health + Unified Hygiene (v2.5.2)
# ─────────────────────────────────────────────────────────────

@router.get("/pattern-health/unified")
async def pattern_health_unified(
    domain: Optional[str] = Query(None, description="sales_intake | ap_posting | None for all"),
    limit: int = Query(25, le=200),
):
    """Cross-domain trust/drift/retire aggregate. Omit `domain` for
    a combined view across AP + intake (+ future domains)."""
    from workflows.core.learning_core import get_health
    return await get_health(domain=domain, limit=limit)


@router.post("/hygiene/run")
async def hygiene_run(
    domain: str = Query("all", description="sales_intake | ap_posting | all"),
):
    """Run hygiene across one or all domains. Replaces the per-domain
    triggers (`/api/intake/learning/hygiene` still works but now
    delegates here)."""
    from workflows.core.learning_core import run_hygiene
    return await run_hygiene(domain=domain, actor="user")


# ─────────────────────────────────────────────────────────────
# U4 — Shared Feedback Ingest (v2.5.2)
# ─────────────────────────────────────────────────────────────

class UnifiedFeedbackBody(BaseModel):
    """Polymorphic body — `scope_type` discriminates customer vs vendor.

    For `scope_type="customer"` (intake reviewer feedback): `event_type`
    and `scope_value` (customer_no) are the primary fields.

    For `scope_type="vendor"` (AP advisory reviewer feedback):
    `document_id` (or `doc_id`) and `reviewer_assessment` are required.
    """
    scope_type: str = Field(..., description="customer | vendor")
    scope_value: Optional[str] = Field(
        None, description="customer_no (for customer) or vendor_no (for vendor)"
    )

    # customer (intake) shape
    event_type: Optional[str] = None
    doc_id: Optional[str] = None
    staging_id: Optional[str] = None
    item_no: Optional[str] = None
    trigger_item: Optional[str] = None

    # vendor (AP) shape
    document_id: Optional[str] = None
    reviewer_assessment: Optional[str] = None
    final_human_decision: Optional[str] = None
    disagreed_fields: Optional[List[str]] = None
    notes: Optional[str] = None

    # shared
    actor: Optional[str] = "user"
    extra: Optional[Dict[str, Any]] = None


@router.post("/feedback")
async def unified_feedback(body: UnifiedFeedbackBody):
    """Single cross-domain feedback ingest. Routes by `scope_type` to
    the correct underlying service while keeping legacy endpoints alive
    during the 30-day dual-write window.

    Never raises for input errors — returns `{error: "..."}` with a
    200 so the caller can surface the message without a 5xx. HTTP
    error statuses are reserved for infra-level failures.
    """
    from workflows.core.learning_core import record_unified_feedback
    return await record_unified_feedback(
        scope_type=body.scope_type,
        scope_value=body.scope_value,
        event_type=body.event_type,
        doc_id=body.doc_id,
        staging_id=body.staging_id,
        item_no=body.item_no,
        trigger_item=body.trigger_item,
        document_id=body.document_id,
        reviewer_assessment=body.reviewer_assessment,
        final_human_decision=body.final_human_decision,
        disagreed_fields=body.disagreed_fields,
        notes=body.notes,
        actor=body.actor or "user",
        extra=body.extra,
    )


# ─────────────────────────────────────────────────────────────
# Weekly Digest (U5+)
# ─────────────────────────────────────────────────────────────

@router.get("/digest/latest")
async def digest_latest():
    """Return the most recent weekly digest, or `null` if none exists yet."""
    from workflows.core.learning_core import get_latest_digest
    d = await get_latest_digest()
    return d or {"digest": None, "hint": "No digest generated yet. POST /api/learning/digest/rebuild to generate one."}


@router.get("/digest/{week_key}")
async def digest_by_week(week_key: str):
    """Fetch a specific digest by its ISO week_key (e.g. '2026-W16')."""
    from workflows.core.learning_core import get_digest_by_week
    d = await get_digest_by_week(week_key)
    if not d:
        from fastapi import HTTPException
        raise HTTPException(status_code=404, detail=f"No digest for week_key '{week_key}'")
    return d


@router.get("/digest")
async def digest_history(limit: int = Query(12, ge=1, le=52)):
    """History of weekly digests, newest first."""
    from workflows.core.learning_core import list_digests
    digests = await list_digests(limit=limit)
    return {"total": len(digests), "digests": digests}


@router.post("/digest/rebuild")
async def digest_rebuild(
    week_of: Optional[str] = Query(None, description="YYYY-MM-DD — any date in the target week; defaults to current week"),
):
    """Rebuild the digest for the week containing `week_of`. Idempotent
    per week_key. Normally fires on the weekly scheduler."""
    from workflows.core.learning_core import build_weekly_digest
    return await build_weekly_digest(week_of=week_of, actor="user")



# ───────────────────────────── Drift Watchlist ─────────────────────────────

@router.get("/drift-watchlist/preview")
async def drift_watchlist_preview():
    """Dry-run the weekly Drift Watchlist — returns the aggregated vendor
    list + rendered Teams card + email HTML without sending anywhere. Use
    this to verify channel payloads before enabling the scheduler."""
    from workflows.core.learning_core.drift_watchlist_service import (
        build_watchlist, format_teams_card, format_email_html,
    )
    wl = await build_watchlist()
    return {
        "watchlist": wl,
        "teams_card": format_teams_card(wl),
        "email_html": format_email_html(wl),
    }


@router.post("/drift-watchlist/send-now")
async def drift_watchlist_send_now(
    channels: Optional[str] = Query(
        None,
        description="Comma-separated override of channels "
                    "(teams_webhook,graph_channel,email). Defaults to env "
                    "DRIFT_WATCHLIST_CHANNELS.",
    ),
):
    """Immediately build + dispatch the watchlist. Safe — still honours
    'empty watchlist = skip' and logs the run in `drift_watchlist_runs`."""
    from workflows.core.learning_core.drift_watchlist_service import send_watchlist
    override = [c.strip() for c in channels.split(",")] if channels else None
    return await send_watchlist(channels=override, actor="manual_trigger")


@router.get("/drift-watchlist/runs")
async def drift_watchlist_runs(limit: int = Query(20, ge=1, le=100)):
    """Recent watchlist dispatch runs (for audit / debugging)."""
    from deps import get_db
    db = get_db()
    runs = await db.drift_watchlist_runs.find(
        {}, {"_id": 0},
    ).sort("ran_at", -1).limit(limit).to_list(limit)
    return {"total": len(runs), "runs": runs}
