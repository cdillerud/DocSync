"""
GPI Document Hub — Drift Alert Service (v2.5.0)
────────────────────────────────────────────────

Scans the unified `learning_events_v2` log (U1) and flags anomalies
where a previously-confident pattern is being repeatedly rejected or
a customer/vendor is suddenly generating lots of new items. Writes
structured alerts to `learning_drift_alerts` with severity + evidence.

Alert rules (configurable via env — see SCAN_CONFIG):
  • TRUSTED_PATTERN_DRIFT   — trusted line rejected ≥2× in last 7d
  • BOUNDS_DRIFT            — customer had ≥3 bounds_violation_overridden in 7d
  • CATALOG_EXPLOSION       — scope had ≥5 unmatched_item_confirmed_new in 30d
  • AP_TEMPLATE_DRIFT       — vendor had ≥3 draft_bc_feedback in 7d
  • CUSTOMER_REJECT_SPIKE   — customer had ≥5 suggestion_rejected in 14d

Alerts are idempotent: re-running the scan updates `last_seen_at` on
an existing open alert instead of duplicating.

Read-only against BC. Never writes or mutates patterns — pure telemetry.
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional

from deps import get_db

logger = logging.getLogger(__name__)

ALERTS_COLL = "learning_drift_alerts"

# ─────────────────────────────────────────────────────────────
# Scan configuration (env-overridable)
# ─────────────────────────────────────────────────────────────

import os as _os

SCAN_CONFIG = {
    "trusted_drift_window_days": int(_os.environ.get("DRIFT_TRUSTED_WINDOW_DAYS", "7")),
    "trusted_drift_min_rejects": int(_os.environ.get("DRIFT_TRUSTED_MIN_REJECTS", "2")),
    "bounds_drift_window_days":  int(_os.environ.get("DRIFT_BOUNDS_WINDOW_DAYS", "7")),
    "bounds_drift_min_overrides": int(_os.environ.get("DRIFT_BOUNDS_MIN_OVERRIDES", "3")),
    "catalog_explosion_window_days": int(_os.environ.get("DRIFT_CATALOG_WINDOW_DAYS", "30")),
    "catalog_explosion_min_new": int(_os.environ.get("DRIFT_CATALOG_MIN_NEW", "5")),
    "ap_drift_window_days": int(_os.environ.get("DRIFT_AP_WINDOW_DAYS", "7")),
    "ap_drift_min_events": int(_os.environ.get("DRIFT_AP_MIN_EVENTS", "3")),
    "reject_spike_window_days": int(_os.environ.get("DRIFT_REJECT_WINDOW_DAYS", "14")),
    "reject_spike_min": int(_os.environ.get("DRIFT_REJECT_MIN", "5")),
}


# ─────────────────────────────────────────────────────────────
# Core scanner
# ─────────────────────────────────────────────────────────────

async def run_drift_scan(db=None, *, actor: str = "scheduler") -> Dict[str, Any]:
    """Run a full scan pass. Safe to call repeatedly — alerts are upserted
    by (scope_type, scope_value, alert_type) so we don't duplicate."""
    db = db if db is not None else get_db()
    now = datetime.now(timezone.utc)
    rules_fired = 0

    rules_fired += await _rule_reject_spike(db, now)
    rules_fired += await _rule_bounds_drift(db, now)
    rules_fired += await _rule_catalog_explosion(db, now)
    rules_fired += await _rule_ap_template_drift(db, now)
    rules_fired += await _rule_trusted_pattern_drift(db, now)

    open_count = await db[ALERTS_COLL].count_documents({"status": "open"})
    summary = {
        "ran_at": now.isoformat(),
        "rules_fired": rules_fired,
        "open_alerts_total": open_count,
        "actor": actor,
    }
    logger.info(
        "[DriftScan] rules_fired=%d open_alerts=%d actor=%s",
        rules_fired, open_count, actor,
    )
    return summary


# ─────────────────────────────────────────────────────────────
# Rule helpers
# ─────────────────────────────────────────────────────────────

async def _upsert_alert(
    db,
    *,
    domain: str,
    scope_type: str,
    scope_value: str,
    alert_type: str,
    severity: str,
    title: str,
    description: str,
    evidence: Dict[str, Any],
) -> None:
    """Upsert an open alert (or refresh last_seen_at if already open)."""
    now = datetime.now(timezone.utc).isoformat()
    existing = await db[ALERTS_COLL].find_one(
        {
            "scope_type": scope_type,
            "scope_value": scope_value,
            "alert_type": alert_type,
            "status": {"$in": ["open", "acknowledged"]},
        },
        {"_id": 0, "id": 1, "status": 1},
    )
    if existing:
        await db[ALERTS_COLL].update_one(
            {"id": existing["id"]},
            {"$set": {
                "last_seen_at": now,
                "evidence": evidence,
                "severity": severity,
                "description": description,
            }},
        )
        return
    await db[ALERTS_COLL].insert_one({
        "id": str(uuid.uuid4()),
        "domain": domain,
        "scope_type": scope_type,
        "scope_value": scope_value,
        "alert_type": alert_type,
        "severity": severity,
        "title": title,
        "description": description,
        "evidence": evidence,
        "status": "open",
        "created_at": now,
        "last_seen_at": now,
    })


def _cutoff(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


async def _rule_reject_spike(db, now: datetime) -> int:
    """≥N suggestion_rejected in the window, grouped by scope_value."""
    cfg = SCAN_CONFIG
    pipeline = [
        {"$match": {
            "event_type": "suggestion_rejected",
            "domain": "sales_intake",
            "scope_type": "customer",
            "scope_value": {"$ne": None},
            "created_at": {"$gte": _cutoff(cfg["reject_spike_window_days"])},
        }},
        {"$group": {
            "_id": "$scope_value",
            "count": {"$sum": 1},
            "items": {"$addToSet": "$target.item_no"},
        }},
        {"$match": {"count": {"$gte": cfg["reject_spike_min"]}}},
    ]
    fired = 0
    async for r in db["learning_events_v2"].aggregate(pipeline):
        await _upsert_alert(
            db,
            domain="sales_intake",
            scope_type="customer",
            scope_value=r["_id"],
            alert_type="customer_reject_spike",
            severity="warn",
            title=f"{r['_id']} — {r['count']} rejections in {cfg['reject_spike_window_days']}d",
            description=(
                f"Customer {r['_id']} has rejected {r['count']} suggestions "
                f"across {len(r.get('items', []))} items in the last "
                f"{cfg['reject_spike_window_days']} days. Their blanket pattern may have shifted."
            ),
            evidence={"count": r["count"], "items": r.get("items", [])[:15]},
        )
        fired += 1
    return fired


async def _rule_bounds_drift(db, now: datetime) -> int:
    cfg = SCAN_CONFIG
    pipeline = [
        {"$match": {
            "event_type": "bounds_violation_overridden",
            "scope_type": "customer",
            "scope_value": {"$ne": None},
            "created_at": {"$gte": _cutoff(cfg["bounds_drift_window_days"])},
        }},
        {"$group": {
            "_id": "$scope_value",
            "count": {"$sum": 1},
            "items": {"$addToSet": "$target.item_no"},
        }},
        {"$match": {"count": {"$gte": cfg["bounds_drift_min_overrides"]}}},
    ]
    fired = 0
    async for r in db["learning_events_v2"].aggregate(pipeline):
        await _upsert_alert(
            db,
            domain="sales_intake",
            scope_type="customer",
            scope_value=r["_id"],
            alert_type="bounds_drift",
            severity="warn",
            title=f"{r['_id']} — {r['count']} qty bounds overrides in {cfg['bounds_drift_window_days']}d",
            description=(
                f"Customer {r['_id']} had {r['count']} quantity-bounds overrides "
                f"across {len(r.get('items', []))} items. Their ordering volume pattern is shifting — "
                f"consider running the BC re-learn."
            ),
            evidence={"count": r["count"], "items": r.get("items", [])[:15]},
        )
        fired += 1
    return fired


async def _rule_catalog_explosion(db, now: datetime) -> int:
    cfg = SCAN_CONFIG
    pipeline = [
        {"$match": {
            "event_type": "unmatched_item_confirmed_new",
            "scope_type": "customer",
            "scope_value": {"$ne": None},
            "created_at": {"$gte": _cutoff(cfg["catalog_explosion_window_days"])},
        }},
        {"$group": {
            "_id": "$scope_value",
            "count": {"$sum": 1},
            "items": {"$addToSet": "$target.item_no"},
        }},
        {"$match": {"count": {"$gte": cfg["catalog_explosion_min_new"]}}},
    ]
    fired = 0
    async for r in db["learning_events_v2"].aggregate(pipeline):
        await _upsert_alert(
            db,
            domain="sales_intake",
            scope_type="customer",
            scope_value=r["_id"],
            alert_type="catalog_explosion",
            severity="info",
            title=f"{r['_id']} — {r['count']} new items confirmed in {cfg['catalog_explosion_window_days']}d",
            description=(
                f"Customer {r['_id']} has introduced {r['count']} new items. "
                f"Review the BC admin queue and consider bulk-onboarding these parts."
            ),
            evidence={"count": r["count"], "items": r.get("items", [])[:20]},
        )
        fired += 1
    return fired


async def _rule_ap_template_drift(db, now: datetime) -> int:
    cfg = SCAN_CONFIG
    pipeline = [
        {"$match": {
            "event_type": "draft_bc_feedback",
            "domain": "ap_posting",
            "scope_type": "vendor",
            "scope_value": {"$ne": None},
            "created_at": {"$gte": _cutoff(cfg["ap_drift_window_days"])},
        }},
        {"$group": {
            "_id": "$scope_value",
            "count": {"$sum": 1},
            "docs": {"$addToSet": "$target.doc_id"},
        }},
        {"$match": {"count": {"$gte": cfg["ap_drift_min_events"]}}},
    ]
    fired = 0
    async for r in db["learning_events_v2"].aggregate(pipeline):
        await _upsert_alert(
            db,
            domain="ap_posting",
            scope_type="vendor",
            scope_value=r["_id"],
            alert_type="ap_template_drift",
            severity="warn",
            title=f"Vendor {r['_id']} — {r['count']} AP posting corrections in {cfg['ap_drift_window_days']}d",
            description=(
                f"Vendor {r['_id']} required {r['count']} corrective edits on draft "
                f"BC postings across {len(r.get('docs', []))} invoices. Posting template may be stale."
            ),
            evidence={"count": r["count"], "doc_ids": r.get("docs", [])[:15]},
        )
        fired += 1
    return fired


async def _rule_trusted_pattern_drift(db, now: datetime) -> int:
    """Trusted pattern line getting rejects = high-severity drift."""
    cfg = SCAN_CONFIG
    fired = 0
    # Iterate trusted lines across all patterns
    async for p in db.order_line_patterns.find({}, {"_id": 0}):
        customer_no = p.get("customer_no")
        if not customer_no:
            continue
        for ln in p.get("associated_lines") or []:
            if not ln.get("trusted"):
                continue
            item_no = (ln.get("item_no") or "").strip()
            if not item_no:
                continue
            # Count recent rejects targeting this customer + item
            reject_count = await db["learning_events_v2"].count_documents({
                "domain": "sales_intake",
                "event_type": "suggestion_rejected",
                "scope_value": customer_no,
                "target.item_no": item_no,
                "created_at": {"$gte": _cutoff(cfg["trusted_drift_window_days"])},
            })
            if reject_count >= cfg["trusted_drift_min_rejects"]:
                await _upsert_alert(
                    db,
                    domain="sales_intake",
                    scope_type="customer",
                    scope_value=customer_no,
                    alert_type=f"trusted_pattern_drift:{item_no}",
                    severity="critical",
                    title=f"TRUSTED pattern drifting — {customer_no} · {item_no}",
                    description=(
                        f"Previously-trusted line {item_no} for customer {customer_no} "
                        f"has been rejected {reject_count} times in the last "
                        f"{cfg['trusted_drift_window_days']} days. This is unusual and worth a human look."
                    ),
                    evidence={
                        "customer_no": customer_no,
                        "item_no": item_no,
                        "reject_count": reject_count,
                        "pattern_accept_rate": ln.get("accept_rate"),
                    },
                )
                fired += 1
    return fired


# ─────────────────────────────────────────────────────────────
# Reader / CRUD helpers
# ─────────────────────────────────────────────────────────────

async def list_drift_alerts(
    *,
    status: Optional[str] = "open",
    domain: Optional[str] = None,
    severity: Optional[str] = None,
    scope_value: Optional[str] = None,
    limit: int = 100,
    db=None,
) -> List[Dict[str, Any]]:
    db = db if db is not None else get_db()
    q: Dict[str, Any] = {}
    if status and status != "all":
        q["status"] = status
    if domain:
        q["domain"] = domain
    if severity:
        q["severity"] = severity
    if scope_value:
        q["scope_value"] = scope_value
    return await db[ALERTS_COLL].find(q, {"_id": 0}).sort(
        "last_seen_at", -1,
    ).limit(limit).to_list(limit)


async def acknowledge_alert(alert_id: str, *, actor: str = "user", db=None) -> Dict[str, Any]:
    db = db if db is not None else get_db()
    now = datetime.now(timezone.utc).isoformat()
    res = await db[ALERTS_COLL].find_one_and_update(
        {"id": alert_id, "status": "open"},
        {"$set": {
            "status": "acknowledged",
            "acknowledged_at": now,
            "acknowledged_by": actor,
        }},
        projection={"_id": 0},
        return_document=True,
    ) if hasattr(db[ALERTS_COLL], "find_one_and_update") else None
    if not res:
        # Fallback for fake DB harnesses: update + read
        await db[ALERTS_COLL].update_one(
            {"id": alert_id},
            {"$set": {
                "status": "acknowledged",
                "acknowledged_at": now,
                "acknowledged_by": actor,
            }},
        )
        res = await db[ALERTS_COLL].find_one({"id": alert_id}, {"_id": 0})
    if not res:
        return {"error": "alert not found"}
    return res


async def resolve_alert(alert_id: str, *, actor: str = "user", db=None) -> Dict[str, Any]:
    db = db if db is not None else get_db()
    now = datetime.now(timezone.utc).isoformat()
    await db[ALERTS_COLL].update_one(
        {"id": alert_id},
        {"$set": {
            "status": "resolved",
            "resolved_at": now,
            "resolved_by": actor,
        }},
    )
    res = await db[ALERTS_COLL].find_one({"id": alert_id}, {"_id": 0})
    return res or {"error": "alert not found"}


async def get_drift_summary(db=None) -> Dict[str, Any]:
    db = db if db is not None else get_db()
    counts = {"open": 0, "acknowledged": 0, "resolved": 0}
    by_severity = {"critical": 0, "warn": 0, "info": 0}
    by_type: Dict[str, int] = {}
    try:
        async for r in db[ALERTS_COLL].aggregate([
            {"$group": {"_id": "$status", "c": {"$sum": 1}}},
        ]):
            counts[r["_id"] or "open"] = r["c"]
        async for r in db[ALERTS_COLL].aggregate([
            {"$match": {"status": "open"}},
            {"$group": {"_id": "$severity", "c": {"$sum": 1}}},
        ]):
            by_severity[r["_id"] or "info"] = r["c"]
        async for r in db[ALERTS_COLL].aggregate([
            {"$match": {"status": "open"}},
            {"$group": {"_id": "$alert_type", "c": {"$sum": 1}}},
        ]):
            by_type[r["_id"] or "unknown"] = r["c"]
    except Exception as e:
        logger.debug("[DriftAlerts] summary aggregate failed: %s", e)
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "by_status": counts,
        "open_by_severity": by_severity,
        "open_by_type": by_type,
    }


__all__ = [
    "run_drift_scan",
    "list_drift_alerts",
    "acknowledge_alert",
    "resolve_alert",
    "get_drift_summary",
    "SCAN_CONFIG",
    "ALERTS_COLL",
]
