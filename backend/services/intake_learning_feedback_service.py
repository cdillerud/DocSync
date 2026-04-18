"""
GPI Document Hub — Intake Learning Feedback Service
───────────────────────────────────────────────────

Turns every reviewer click into training data for the Giovanni-style
BC learning patterns.

When a reviewer looks at an `intake_insights` payload on a document
(or XLS staging) and either accepts a suggested line, rejects it,
overrides a qty bounds violation, or resolves an unmatched item,
those events flow here:

  1. Event persisted to `intake_learning_events` (audit trail)
  2. Pattern confidence adjusted in `order_line_patterns`:
     • Accepts  → bump occurrences, raise frequency
     • Rejects  → lower frequency; retire when acceptance <40% / ≥5 samples
     • Overrides of qty bounds → widen std_dev or lower sample weight
     • Unmatched items confirmed as new → seed a new item-alias candidate
  3. Per-customer pattern-health aggregates surface drift on the dashboard

Read-only wrt Business Central — we only mutate local pattern state.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from deps import get_db

logger = logging.getLogger(__name__)

EVENTS_COLL = "intake_learning_events"
PATTERNS_COLL = "order_line_patterns"

EVENT_TYPES = {
    "suggestion_accepted",
    "suggestion_rejected",
    "bounds_violation_confirmed",
    "bounds_violation_overridden",
    "unmatched_item_confirmed_new",
    "unmatched_item_mapped",
}

RETIRE_THRESHOLD = 0.40       # acceptance rate below which we retire a pattern
RETIRE_MIN_SAMPLES = 5        # need at least this many samples before retiring
TRUSTED_THRESHOLD = 0.90      # acceptance rate at/above which pattern is "trusted"


# ─────────────────────────────────────────────────────────────
# Record a reviewer feedback event
# ─────────────────────────────────────────────────────────────

async def record_feedback_event(
    *,
    event_type: str,
    doc_id: Optional[str] = None,
    staging_id: Optional[str] = None,
    customer_no: Optional[str] = None,
    item_no: Optional[str] = None,
    trigger_item: Optional[str] = None,
    extra: Optional[Dict[str, Any]] = None,
    actor: str = "user",
    db=None,
) -> Dict[str, Any]:
    """Persist a single feedback event and apply its effect to the
    underlying pattern (or create an item-alias candidate).

    Always returns a dict — never raises on application errors so the
    calling UI/endpoint stays resilient.
    """
    if event_type not in EVENT_TYPES:
        return {"error": f"unknown event_type '{event_type}'", "known": sorted(EVENT_TYPES)}

    db = db if db is not None else get_db()
    now = datetime.now(timezone.utc)
    event = {
        "id": str(uuid.uuid4()),
        "event_type": event_type,
        "doc_id": doc_id,
        "staging_id": staging_id,
        "customer_no": customer_no,
        "item_no": item_no,
        "trigger_item": trigger_item,
        "extra": extra or {},
        "actor": actor,
        "created_at": now.isoformat(),
    }

    try:
        await db[EVENTS_COLL].insert_one(event)
        event.pop("_id", None)
    except Exception as e:
        logger.warning("[LearnFeedback] insert event failed: %s", e)

    applied: Dict[str, Any] = {"event_id": event["id"], "applied": None}
    try:
        if event_type == "suggestion_accepted" and customer_no and item_no:
            applied["applied"] = await _apply_suggestion_delta(
                db, customer_no=customer_no, item_no=item_no,
                trigger_item=trigger_item or "*", delta=+1,
            )
        elif event_type == "suggestion_rejected" and customer_no and item_no:
            applied["applied"] = await _apply_suggestion_delta(
                db, customer_no=customer_no, item_no=item_no,
                trigger_item=trigger_item or "*", delta=-1,
            )
        elif event_type == "bounds_violation_confirmed" and customer_no:
            applied["applied"] = await _apply_bounds_feedback(
                db, customer_no=customer_no, item_no=item_no or "*",
                confirmed=True,
            )
        elif event_type == "bounds_violation_overridden" and customer_no:
            applied["applied"] = await _apply_bounds_feedback(
                db, customer_no=customer_no, item_no=item_no or "*",
                confirmed=False,
            )
        elif event_type == "unmatched_item_confirmed_new" and item_no:
            applied["applied"] = await _record_new_item_candidate(
                db, customer_no=customer_no, item_no=item_no, extra=extra,
            )
        elif event_type == "unmatched_item_mapped" and item_no and extra:
            # `extra` is expected to include mapped_to_bc_item
            applied["applied"] = await _record_item_mapping(
                db, from_item=item_no, to_bc_item=extra.get("mapped_to_bc_item"),
                customer_no=customer_no,
            )
    except Exception as e:
        logger.warning("[LearnFeedback] apply %s failed: %s", event_type, e)
        applied["error"] = str(e)

    logger.info(
        "[LearnFeedback] event=%s cust=%s item=%s applied=%s",
        event_type, customer_no, item_no, applied.get("applied"),
    )
    return {"ok": True, **applied, "event": event}


# ─────────────────────────────────────────────────────────────
# Pattern mutation helpers
# ─────────────────────────────────────────────────────────────

async def _apply_suggestion_delta(
    db, *, customer_no: str, item_no: str, trigger_item: str, delta: int,
) -> Dict[str, Any]:
    """Bump or decay the occurrence count of an associated_line on a pattern.

    Searches first for the exact (customer_no, trigger_item) pattern; if
    not found, falls back to any pattern for this customer that contains
    a matching `item_no`. Recomputes `frequency` as occurrences /
    total_orders_analyzed. Retires lines whose acceptance drops below
    threshold once enough samples are collected.
    """
    pattern = None
    if trigger_item and trigger_item != "*":
        pattern = await db[PATTERNS_COLL].find_one(
            {"customer_no": customer_no, "trigger_item_no": trigger_item},
            {"_id": 0},
        )
    if not pattern:
        # Fallback: any pattern for this customer containing the line
        pattern = await db[PATTERNS_COLL].find_one(
            {"customer_no": customer_no,
             "associated_lines.item_no": item_no},
            {"_id": 0},
        )
    if not pattern:
        return {"action": "no_matching_pattern", "reason": "pattern or line not found"}

    trigger_key = pattern.get("trigger_item_no")

    lines = pattern.get("associated_lines") or []
    updated_line = None
    for ln in lines:
        if (ln.get("item_no") or "").strip() == item_no.strip():
            total = max(pattern.get("total_orders_analyzed", 1), 1)
            new_occ = max(0, int(ln.get("occurrences", 0)) + int(delta))
            ln["occurrences"] = new_occ
            ln["frequency"] = round(min(1.0, new_occ / total), 3)
            ln["feedback_count"] = int(ln.get("feedback_count", 0)) + 1
            if delta > 0:
                ln["accept_count"] = int(ln.get("accept_count", 0)) + 1
            else:
                ln["reject_count"] = int(ln.get("reject_count", 0)) + 1
            # Retire if acceptance trend is bad
            ac = int(ln.get("accept_count", 0))
            rc = int(ln.get("reject_count", 0))
            sample = ac + rc
            if sample >= RETIRE_MIN_SAMPLES:
                accept_rate = ac / sample
                ln["accept_rate"] = round(accept_rate, 3)
                if accept_rate < RETIRE_THRESHOLD:
                    ln["retired"] = True
                    ln["retired_at"] = datetime.now(timezone.utc).isoformat()
                elif accept_rate >= TRUSTED_THRESHOLD:
                    ln["trusted"] = True
                else:
                    ln["retired"] = False
                    ln["trusted"] = False
            updated_line = ln
            break

    if not updated_line:
        return {"action": "line_not_in_pattern"}

    pattern["last_feedback_at"] = datetime.now(timezone.utc).isoformat()
    await db[PATTERNS_COLL].update_one(
        {"customer_no": customer_no, "trigger_item_no": trigger_key},
        {"$set": {
            "associated_lines": lines,
            "last_feedback_at": pattern["last_feedback_at"],
        }},
    )
    # Invalidate the customer's fingerprint so cold-start matches see
    # the updated pattern on next lookup.
    try:
        from services.cold_start_matcher_service import invalidate_fingerprint
        await invalidate_fingerprint(customer_no, db=db)
    except Exception:
        pass
    return {
        "action": "applied",
        "item_no": item_no,
        "delta": delta,
        "new_occurrences": updated_line["occurrences"],
        "new_frequency": updated_line["frequency"],
        "retired": updated_line.get("retired", False),
        "trusted": updated_line.get("trusted", False),
    }


async def _apply_bounds_feedback(
    db, *, customer_no: str, item_no: str, confirmed: bool,
) -> Dict[str, Any]:
    """When a reviewer confirms or overrides a qty-bounds violation, we
    nudge the stored qty_history: confirmed → keep sample (flag as outlier),
    overridden → include the reported value so the bounds widen."""
    pattern = await db[PATTERNS_COLL].find_one(
        {"customer_no": customer_no, "qty_history": {"$exists": True}},
        {"_id": 0},
    )
    if not pattern:
        return {"action": "no_qty_history"}

    qh = pattern.get("qty_history") or {}
    qh["feedback_events"] = int(qh.get("feedback_events", 0)) + 1
    if confirmed:
        qh["confirmed_outliers"] = int(qh.get("confirmed_outliers", 0)) + 1
    else:
        qh["overridden_count"] = int(qh.get("overridden_count", 0)) + 1
        # Widen the envelope by relaxing stddev 10% once per override
        if qh.get("std_dev", 0) > 0:
            qh["std_dev"] = round(qh["std_dev"] * 1.10, 3)

    await db[PATTERNS_COLL].update_one(
        {"customer_no": customer_no, "qty_history": {"$exists": True}},
        {"$set": {"qty_history": qh,
                  "last_feedback_at": datetime.now(timezone.utc).isoformat()}},
    )
    return {
        "action": "bounds_nudged",
        "confirmed": confirmed,
        "new_std_dev": qh.get("std_dev"),
        "feedback_events": qh["feedback_events"],
    }


async def _record_new_item_candidate(
    db, *, customer_no: Optional[str], item_no: str, extra: Optional[Dict[str, Any]],
) -> Dict[str, Any]:
    """The reviewer confirmed that an unmatched item really is a new
    part number (not a typo of an existing BC item). We seed a candidate
    row that an admin can promote into BC later."""
    await db.intake_item_candidates.update_one(
        {"item_no": item_no, "customer_no": customer_no or ""},
        {"$set": {
            "item_no": item_no,
            "customer_no": customer_no,
            "description": (extra or {}).get("description", ""),
            "first_seen": datetime.now(timezone.utc).isoformat(),
            "confirmed_new": True,
        }, "$inc": {"occurrences": 1}},
        upsert=True,
    )
    return {"action": "candidate_recorded", "item_no": item_no}


async def _record_item_mapping(
    db, *, from_item: str, to_bc_item: Optional[str], customer_no: Optional[str],
) -> Dict[str, Any]:
    if not to_bc_item:
        return {"action": "no_target_item"}
    await db.intake_item_aliases.update_one(
        {"from_item": from_item, "customer_no": customer_no or ""},
        {"$set": {
            "from_item": from_item,
            "to_bc_item": to_bc_item,
            "customer_no": customer_no,
            "last_mapped_at": datetime.now(timezone.utc).isoformat(),
        }, "$inc": {"mapping_count": 1}},
        upsert=True,
    )
    return {"action": "alias_saved", "from": from_item, "to": to_bc_item}


# ─────────────────────────────────────────────────────────────
# Pattern health aggregation (dashboard)
# ─────────────────────────────────────────────────────────────

async def get_pattern_health(db=None, limit: int = 50) -> Dict[str, Any]:
    """Aggregate pattern health across all customers.

    Returns trusted / retired / drifting counts and per-customer drill-down
    so the dashboard can surface which patterns are learning well and which
    need human intervention.
    """
    db = db if db is not None else get_db()

    trusted = 0
    retired = 0
    drifting = 0
    unscored = 0
    per_customer: Dict[str, Dict[str, Any]] = {}

    async for p in db[PATTERNS_COLL].find({}, {"_id": 0}):
        cust = p.get("customer_no") or "UNKNOWN"
        bucket = per_customer.setdefault(
            cust,
            {
                "customer_no": cust,
                "patterns_total": 0,
                "trusted": 0,
                "retired": 0,
                "drifting": 0,
                "unscored": 0,
                "last_feedback_at": None,
                "recent_retirements": [],
            },
        )
        lines = p.get("associated_lines") or []
        bucket["patterns_total"] += len(lines)
        if p.get("last_feedback_at"):
            if not bucket["last_feedback_at"] or p["last_feedback_at"] > bucket["last_feedback_at"]:
                bucket["last_feedback_at"] = p["last_feedback_at"]

        for ln in lines:
            if ln.get("retired"):
                retired += 1
                bucket["retired"] += 1
                if ln.get("retired_at"):
                    bucket["recent_retirements"].append({
                        "item_no": ln.get("item_no"),
                        "retired_at": ln["retired_at"],
                        "accept_rate": ln.get("accept_rate"),
                    })
            elif ln.get("trusted"):
                trusted += 1
                bucket["trusted"] += 1
            elif (ln.get("accept_count", 0) + ln.get("reject_count", 0)) >= 1:
                drifting += 1
                bucket["drifting"] += 1
            else:
                unscored += 1
                bucket["unscored"] += 1

    customers = sorted(
        per_customer.values(), key=lambda c: c["patterns_total"], reverse=True,
    )[:limit]

    # Recent events (last 72h) for activity feed
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=72)).isoformat()
    recent = await db[EVENTS_COLL].find(
        {"created_at": {"$gte": cutoff}},
        {"_id": 0, "id": 1, "event_type": 1, "doc_id": 1, "staging_id": 1,
         "customer_no": 1, "item_no": 1, "actor": 1, "created_at": 1},
    ).sort("created_at", -1).limit(25).to_list(25)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": {
            "trusted": trusted, "retired": retired,
            "drifting": drifting, "unscored": unscored,
            "total": trusted + retired + drifting + unscored,
        },
        "per_customer": customers,
        "recent_events": recent,
    }


# ─────────────────────────────────────────────────────────────
# Nightly hygiene scheduler
# ─────────────────────────────────────────────────────────────

async def run_pattern_hygiene(db=None) -> Dict[str, Any]:
    """Scheduled pass to clean up / promote patterns based on accumulated
    feedback. Currently:
      • Retires any line with accept_rate < RETIRE_THRESHOLD over ≥ RETIRE_MIN_SAMPLES
      • Marks trusted any line with accept_rate ≥ TRUSTED_THRESHOLD
      • Records a summary row in `intake_pattern_hygiene_runs`
    Every nudge also happens inline in `_apply_suggestion_delta`; this job
    exists as a safety net for patterns that accumulated feedback outside
    our regular path.
    """
    db = db if db is not None else get_db()
    retired = 0
    promoted = 0
    scanned = 0
    async for p in db[PATTERNS_COLL].find({}, {"_id": 0}):
        lines = p.get("associated_lines") or []
        dirty = False
        for ln in lines:
            accept_count = ln.get("accept_count", 0)
            reject_count = ln.get("reject_count", 0)
            sample = accept_count + reject_count
            if sample < RETIRE_MIN_SAMPLES:
                continue
            rate = accept_count / sample
            ln["accept_rate"] = round(rate, 3)
            if rate < RETIRE_THRESHOLD and not ln.get("retired"):
                ln["retired"] = True
                ln["retired_at"] = datetime.now(timezone.utc).isoformat()
                retired += 1
                dirty = True
            elif rate >= TRUSTED_THRESHOLD and not ln.get("trusted"):
                ln["trusted"] = True
                promoted += 1
                dirty = True
            scanned += 1
        if dirty:
            await db[PATTERNS_COLL].update_one(
                {"customer_no": p["customer_no"], "trigger_item_no": p["trigger_item_no"]},
                {"$set": {"associated_lines": lines}},
            )
    summary = {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "patterns_scanned": scanned,
        "retired": retired,
        "promoted": promoted,
    }
    hygiene_doc = {"id": str(uuid.uuid4()), **summary}
    try:
        await db.intake_pattern_hygiene_runs.insert_one(hygiene_doc)
    except Exception as e:
        logger.warning("[LearnFeedback.hygiene] insert run failed: %s", e)
    logger.info(
        "[LearnFeedback.hygiene] scanned=%d retired=%d promoted=%d",
        scanned, retired, promoted,
    )
    return summary


async def list_recent_events(
    limit: int = 100,
    event_type: Optional[str] = None,
    customer_no: Optional[str] = None,
    db=None,
) -> List[Dict[str, Any]]:
    db = db if db is not None else get_db()
    q: Dict[str, Any] = {}
    if event_type:
        q["event_type"] = event_type
    if customer_no:
        q["customer_no"] = customer_no
    return await db[EVENTS_COLL].find(q, {"_id": 0}).sort("created_at", -1).limit(limit).to_list(limit)


__all__ = [
    "record_feedback_event",
    "get_pattern_health",
    "run_pattern_hygiene",
    "list_recent_events",
    "EVENT_TYPES",
    "RETIRE_THRESHOLD", "RETIRE_MIN_SAMPLES", "TRUSTED_THRESHOLD",
]
