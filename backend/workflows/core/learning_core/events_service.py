"""
GPI Document Hub — Unified Learning Events (U1)
────────────────────────────────────────────────

Canonical writer + reader for a single cross-domain event log. Lives
alongside the 3 legacy collections (`intake_learning_events`,
`posting_learning_events`, `learning_events`) during a 30-day dual-write
window so nothing breaks.

Schema (stable):
{
  id: str (uuid),
  domain: "ap_posting" | "sales_intake" | "inventory_xls" | "generic",
  event_type: str,                      # "suggestion_accepted", etc.
  actor: "user" | "scheduler" | "bc_write_hook",
  scope_type: "vendor" | "customer" | "xls_staging" | "global",
  scope_value: str | None,              # e.g. "V-00123" or "C-10250"
  target: {
    doc_id?:  str,
    staging_id?: str,
    item_no?: str,
    trigger_item?: str,
    field_path?: str,
  },
  applied: dict | None,                 # side-effect result from the caller
  extra: dict,                          # free-form metadata
  source: str,                          # which service emitted the event
  created_at: str (ISO),
}

Design:
  • Never raises. Feedback ingest must never be blocked by telemetry.
  • Indexes auto-created on first use (domain, scope_value, created_at).
  • No secondary writes — callers dual-write to legacy collections on
    their own during the migration window.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from deps import get_db

logger = logging.getLogger(__name__)

EVENTS_COLL = "learning_events_v2"   # v2 namespace; clean collection

DOMAINS = {"ap_posting", "sales_intake", "inventory_xls", "generic"}
SCOPE_TYPES = {"vendor", "customer", "xls_staging", "global"}

_INDEXES_CREATED = False


async def _ensure_indexes(db) -> None:
    global _INDEXES_CREATED
    if _INDEXES_CREATED:
        return
    try:
        await db[EVENTS_COLL].create_index(
            [("domain", 1), ("created_at", -1)], name="domain_time"
        )
        await db[EVENTS_COLL].create_index(
            [("scope_type", 1), ("scope_value", 1), ("created_at", -1)],
            name="scope_time",
        )
        await db[EVENTS_COLL].create_index(
            [("event_type", 1), ("created_at", -1)], name="type_time"
        )
        _INDEXES_CREATED = True
    except Exception as e:
        logger.debug("[LearningCore.events] index create skipped: %s", e)


async def record_event(
    *,
    domain: str,
    event_type: str,
    scope_type: str = "global",
    scope_value: Optional[str] = None,
    target: Optional[Dict[str, Any]] = None,
    applied: Optional[Dict[str, Any]] = None,
    extra: Optional[Dict[str, Any]] = None,
    actor: str = "user",
    source: str = "unknown",
    db=None,
) -> Dict[str, Any]:
    """Write a single event to the unified log. Returns the written
    document (with `_id` stripped) for convenience. Safe — never raises.
    """
    if domain not in DOMAINS:
        logger.warning("[LearningCore.events] unknown domain '%s', coercing to generic", domain)
        domain = "generic"
    if scope_type not in SCOPE_TYPES:
        scope_type = "global"

    db = db if db is not None else get_db()
    await _ensure_indexes(db)

    doc = {
        "id": str(uuid.uuid4()),
        "domain": domain,
        "event_type": event_type,
        "actor": actor,
        "scope_type": scope_type,
        "scope_value": scope_value,
        "target": target or {},
        "applied": applied,
        "extra": extra or {},
        "source": source,
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    try:
        await db[EVENTS_COLL].insert_one(doc)
        doc.pop("_id", None)
    except Exception as e:
        logger.warning("[LearningCore.events] insert failed: %s", e)
    return doc


async def list_events(
    *,
    domain: Optional[str] = None,
    event_type: Optional[str] = None,
    scope_type: Optional[str] = None,
    scope_value: Optional[str] = None,
    since_iso: Optional[str] = None,
    limit: int = 100,
    db=None,
) -> List[Dict[str, Any]]:
    """Query the unified log with common filters."""
    db = db if db is not None else get_db()
    q: Dict[str, Any] = {}
    if domain:
        q["domain"] = domain
    if event_type:
        q["event_type"] = event_type
    if scope_type:
        q["scope_type"] = scope_type
    if scope_value:
        q["scope_value"] = scope_value
    if since_iso:
        q["created_at"] = {"$gte": since_iso}
    return await db[EVENTS_COLL].find(q, {"_id": 0}).sort(
        "created_at", -1,
    ).limit(limit).to_list(limit)


async def get_domain_summary(db=None) -> Dict[str, Any]:
    """Dashboard-friendly aggregate: counts by domain + event_type."""
    db = db if db is not None else get_db()
    await _ensure_indexes(db)

    total = await db[EVENTS_COLL].count_documents({})
    by_domain: Dict[str, int] = {}
    by_event: Dict[str, int] = {}
    try:
        async for r in db[EVENTS_COLL].aggregate([
            {"$group": {"_id": "$domain", "c": {"$sum": 1}}},
        ]):
            by_domain[r["_id"] or "unknown"] = r["c"]
        async for r in db[EVENTS_COLL].aggregate([
            {"$group": {"_id": "$event_type", "c": {"$sum": 1}}},
            {"$sort": {"c": -1}},
            {"$limit": 20},
        ]):
            by_event[r["_id"] or "unknown"] = r["c"]
    except Exception as e:
        logger.warning("[LearningCore.events] aggregate failed: %s", e)

    recent = await list_events(limit=10, db=db)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "total_events": total,
        "by_domain": by_domain,
        "top_event_types": by_event,
        "recent_events": recent,
    }


async def get_trend(
    *,
    domain: Optional[str] = None,
    days: int = 7,
    db=None,
) -> List[Dict[str, Any]]:
    """Per-day event count for the last `days` days (ascending). Fills
    missing days with 0 so the result length is always exactly `days`.

    Returns: [{"date": "YYYY-MM-DD", "count": int}, ...]
    """
    from datetime import timedelta

    days = max(1, min(int(days), 90))
    db = db if db is not None else get_db()

    today_utc = datetime.now(timezone.utc).date()
    start_date = today_utc - timedelta(days=days - 1)
    since_iso = start_date.isoformat() + "T00:00:00+00:00"

    q: Dict[str, Any] = {"created_at": {"$gte": since_iso}}
    if domain:
        q["domain"] = domain

    buckets: Dict[str, int] = {}
    try:
        async for doc in db[EVENTS_COLL].find(q, {"_id": 0, "created_at": 1}):
            ca = doc.get("created_at") or ""
            if len(ca) >= 10:
                buckets[ca[:10]] = buckets.get(ca[:10], 0) + 1
    except Exception as e:
        logger.warning("[LearningCore.events] trend aggregate failed: %s", e)

    out: List[Dict[str, Any]] = []
    for i in range(days):
        d = (start_date + timedelta(days=i)).isoformat()
        out.append({"date": d, "count": int(buckets.get(d, 0))})
    return out


async def get_reviewer_leaderboard(
    *,
    days: int = 7,
    limit: int = 10,
    db=None,
) -> Dict[str, Any]:
    """Who's been giving the most feedback in the last `days` days?

    Returns: {
      "window_days": N,
      "since": "YYYY-MM-DD",
      "total_events": int,
      "unique_actors": int,
      "reviewers": [
        {"actor": "...", "events": N, "domains": {...}, "top_event_type": "..."},
        ...
      ],
    }
    """
    from datetime import timedelta

    days = max(1, min(int(days), 90))
    limit = max(1, min(int(limit), 100))
    db = db if db is not None else get_db()

    today_utc = datetime.now(timezone.utc).date()
    start_date = today_utc - timedelta(days=days - 1)
    since_iso = start_date.isoformat() + "T00:00:00+00:00"

    # Skip auto-generated actors — focus on human reviewers + named systems
    SKIP_ACTORS = {"", None, "test"}

    # Collect events into memory (bounded by the time window — small per day)
    per_actor: Dict[str, Dict[str, Any]] = {}
    total = 0
    try:
        async for doc in db[EVENTS_COLL].find(
            {"created_at": {"$gte": since_iso}},
            {"_id": 0, "actor": 1, "domain": 1, "event_type": 1},
        ):
            actor = doc.get("actor") or ""
            if actor in SKIP_ACTORS:
                continue
            total += 1
            bucket = per_actor.setdefault(actor, {
                "actor": actor,
                "events": 0,
                "domains": {},
                "event_types": {},
            })
            bucket["events"] += 1
            dom = doc.get("domain") or "unknown"
            bucket["domains"][dom] = bucket["domains"].get(dom, 0) + 1
            et = doc.get("event_type") or "unknown"
            bucket["event_types"][et] = bucket["event_types"].get(et, 0) + 1
    except Exception as e:
        logger.warning("[LearningCore.events] leaderboard aggregate failed: %s", e)

    reviewers = []
    for b in per_actor.values():
        top_et = max(b["event_types"].items(), key=lambda kv: kv[1])[0] if b["event_types"] else None
        reviewers.append({
            "actor": b["actor"],
            "events": b["events"],
            "domains": b["domains"],
            "top_event_type": top_et,
        })
    reviewers.sort(key=lambda r: r["events"], reverse=True)

    return {
        "window_days": days,
        "since": start_date.isoformat(),
        "total_events": total,
        "unique_actors": len(per_actor),
        "reviewers": reviewers[:limit],
    }


__all__ = [
    "record_event",
    "list_events",
    "get_domain_summary",
    "get_trend",
    "get_reviewer_leaderboard",
    "DOMAINS",
    "SCOPE_TYPES",
    "EVENTS_COLL",
]
