"""
GPI Document Hub — Weekly Learning Digest Service (U5+, v2.5.2)
───────────────────────────────────────────────────────────────

Assembles a one-week snapshot of learning-core activity:
  • Top-3 reviewers by feedback volume
  • Total feedback events (per domain breakdown)
  • New drift alerts in the window
  • Pattern-health snapshot at window close
  • 7-day sparkline series

Stored idempotently in `learning_digests` keyed by `week_key` (ISO year
+ ISO week, e.g. "2026-W16"). Safe to rebuild at any time — the same
week_key always overwrites.

This module DOES NOT send email. It's a content-generation + storage
layer. A future iteration can plug MS Graph / Resend into
`send_digest()` without changing the build pipeline.
"""

import logging
import uuid
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

from deps import get_db
from services.learning_core.events_service import (
    list_events, get_trend, get_reviewer_leaderboard, EVENTS_COLL,
)
from services.learning_core.pattern_health_service import get_health

logger = logging.getLogger(__name__)

DIGESTS_COLL = "learning_digests"


def _monday_of(d: date) -> date:
    """Return the Monday of the ISO week containing `d`."""
    return d - timedelta(days=d.weekday())


def _week_key(d: date) -> str:
    """ISO year + ISO week number, e.g. '2026-W16'."""
    iso_year, iso_week, _ = d.isocalendar()
    return f"{iso_year}-W{iso_week:02d}"


async def build_weekly_digest(
    *,
    week_of: Optional[str] = None,
    actor: str = "scheduler",
    db=None,
) -> Dict[str, Any]:
    """Build and persist the digest for the week containing `week_of`
    (YYYY-MM-DD). Defaults to the CURRENT week (in-progress).

    Returns the digest document (with `_id` stripped) and upserts it
    by `week_key` so repeat calls are idempotent.
    """
    db = db if db is not None else get_db()

    if week_of:
        try:
            target = date.fromisoformat(week_of)
        except ValueError:
            return {"error": f"invalid week_of '{week_of}' (expected YYYY-MM-DD)"}
    else:
        target = datetime.now(timezone.utc).date()

    week_start = _monday_of(target)
    week_end = week_start + timedelta(days=6)
    window_start_iso = week_start.isoformat() + "T00:00:00+00:00"
    window_end_iso = (week_end + timedelta(days=1)).isoformat() + "T00:00:00+00:00"
    key = _week_key(week_start)

    # Reviewer leaderboard — 7 days ending at week_end
    leaderboard = await get_reviewer_leaderboard(days=7, limit=5, db=db)

    # Count events IN this specific week window (leaderboard uses rolling
    # 7d ending today — for a past-week digest we want the exact window)
    events_in_week = 0
    by_domain: Dict[str, int] = {}
    by_event_type: Dict[str, int] = {}
    try:
        async for e in db[EVENTS_COLL].find(
            {
                "created_at": {"$gte": window_start_iso, "$lt": window_end_iso},
            },
            {"_id": 0, "domain": 1, "event_type": 1, "actor": 1},
        ):
            if (e.get("actor") or "") in ("", None, "test"):
                continue
            events_in_week += 1
            d = e.get("domain") or "unknown"
            by_domain[d] = by_domain.get(d, 0) + 1
            t = e.get("event_type") or "unknown"
            by_event_type[t] = by_event_type.get(t, 0) + 1
    except Exception as e:
        logger.warning("[WeeklyDigest] events aggregate failed: %s", e)

    # New drift alerts raised in the window
    new_drift: List[Dict[str, Any]] = []
    try:
        async for a in db["learning_drift_alerts"].find(
            {
                "first_seen_at": {"$gte": window_start_iso, "$lt": window_end_iso},
            },
            {"_id": 0, "id": 1, "severity": 1, "domain": 1, "alert_type": 1,
             "title": 1, "description": 1, "first_seen_at": 1, "status": 1},
        ).sort("first_seen_at", -1).to_list(25):
            new_drift.append(a)
    except Exception as e:
        logger.debug("[WeeklyDigest] drift fetch skipped: %s", e)

    # Pattern health snapshot at build time (not historical — best-effort)
    health = await get_health(domain=None, limit=5, db=db)

    # 7-day sparkline series per domain (ending at build time)
    trend = {
        "sales_intake": await get_trend(domain="sales_intake", days=7, db=db),
        "ap_posting":   await get_trend(domain="ap_posting",   days=7, db=db),
    }

    # Compose narrative headline — best-effort one-liner
    top_reviewer = leaderboard["reviewers"][0] if leaderboard.get("reviewers") else None
    crit_count = sum(1 for a in new_drift if a.get("severity") == "critical")
    warn_count = sum(1 for a in new_drift if a.get("severity") == "warn")
    if events_in_week == 0:
        headline = "Quiet week — no reviewer feedback events recorded."
    elif top_reviewer:
        headline = (
            f"{top_reviewer['actor']} led the week with {top_reviewer['events']} events. "
            f"{events_in_week} total feedback events across {len(by_domain)} domain(s)."
        )
    else:
        headline = f"{events_in_week} total feedback events this week."
    if crit_count or warn_count:
        headline += f" Drift: {crit_count} critical, {warn_count} warn."

    doc = {
        "id": str(uuid.uuid4()),
        "week_key": key,
        "week_start": week_start.isoformat(),
        "week_end": week_end.isoformat(),
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "generated_by": actor,
        "headline": headline,
        "events": {
            "total": events_in_week,
            "by_domain": by_domain,
            "by_event_type": dict(sorted(
                by_event_type.items(), key=lambda kv: kv[1], reverse=True,
            )[:10]),
        },
        "top_reviewers": leaderboard.get("reviewers", [])[:3],
        "leaderboard_unique_actors": leaderboard.get("unique_actors", 0),
        "new_drift_alerts": new_drift,
        "drift_summary": {
            "total_new": len(new_drift),
            "critical": crit_count,
            "warn": warn_count,
            "info": sum(1 for a in new_drift if a.get("severity") == "info"),
        },
        "pattern_health_snapshot": {
            "combined_summary": health.get("combined_summary", {}),
            "per_domain_summaries": [
                {"domain": d.get("domain"), "summary": d.get("summary", {})}
                for d in (health.get("domains") or [])
            ],
        },
        "trend_7d": trend,
    }

    # Upsert by week_key — strip any residual _id before returning
    try:
        await db[DIGESTS_COLL].update_one(
            {"week_key": key}, {"$set": doc}, upsert=True,
        )
    except Exception as e:
        logger.warning("[WeeklyDigest] upsert failed: %s", e)
    doc.pop("_id", None)
    return doc


async def get_latest_digest(*, db=None) -> Optional[Dict[str, Any]]:
    """Return the most recently built digest, or None if none exist."""
    db = db if db is not None else get_db()
    d = await db[DIGESTS_COLL].find_one(
        {}, {"_id": 0}, sort=[("week_start", -1)],
    )
    return d


async def get_digest_by_week(week_key: str, *, db=None) -> Optional[Dict[str, Any]]:
    db = db if db is not None else get_db()
    return await db[DIGESTS_COLL].find_one({"week_key": week_key}, {"_id": 0})


async def list_digests(limit: int = 12, *, db=None) -> List[Dict[str, Any]]:
    """History of weekly digests, newest first. Capped at 12 weeks by default."""
    db = db if db is not None else get_db()
    limit = max(1, min(int(limit), 52))
    return await db[DIGESTS_COLL].find(
        {}, {"_id": 0,
             "id": 1, "week_key": 1, "week_start": 1, "week_end": 1,
             "generated_at": 1, "headline": 1,
             "events": 1, "drift_summary": 1},
    ).sort("week_start", -1).to_list(limit)


__all__ = [
    "build_weekly_digest",
    "get_latest_digest",
    "get_digest_by_week",
    "list_digests",
    "DIGESTS_COLL",
]
