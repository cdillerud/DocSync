"""
GPI Document Hub — Shared Pattern Health Service (U3, v2.5.2)
──────────────────────────────────────────────────────────────

Cross-domain trust/drift/retire aggregator. Normalizes intake-side
(`order_line_patterns`, accept_rate-based) and AP-side
(`posting_pattern_analysis`, confidence-tier-based) pattern state into
one canonical `HealthReport` shape so dashboards, schedulers, and
alerts can treat them identically.

Adapters are pluggable — register a new domain by adding to
HEALTH_ADAPTERS. Shared hygiene pass runs each domain's adapter
in sequence and records a summary in `pattern_hygiene_runs`.

Normalized HealthReport:
{
  domain: str,
  generated_at: ISO str,
  summary: {trusted, drifting, retired, unscored, total},
  per_scope: [
    {scope_value, scope_name?, patterns_total,
     trusted, drifting, retired, unscored, last_feedback_at?}
  ],
  recent_events: [...]    # from learning_events_v2 filtered by domain
}

Read-only wrt BC. Mutations (retire/promote) only touch local pattern
collections via each adapter's `run_hygiene()` method.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Callable, Dict, List, Optional

from deps import get_db
from services.learning_core.events_service import list_events, get_trend

logger = logging.getLogger(__name__)

HYGIENE_RUNS_COLL = "pattern_hygiene_runs"

# ─────────────────────────────────────────────────────────────
# Normalized types
# ─────────────────────────────────────────────────────────────

EMPTY_SUMMARY = {"trusted": 0, "drifting": 0, "retired": 0, "unscored": 0, "total": 0}


def _empty_report(domain: str) -> Dict[str, Any]:
    return {
        "domain": domain,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "summary": dict(EMPTY_SUMMARY),
        "per_scope": [],
        "recent_events": [],
    }


# ─────────────────────────────────────────────────────────────
# Adapter: sales_intake (order_line_patterns)
# ─────────────────────────────────────────────────────────────

async def _intake_health(db, limit: int) -> Dict[str, Any]:
    rep = _empty_report("sales_intake")
    per_customer: Dict[str, Dict[str, Any]] = {}
    async for p in db.order_line_patterns.find({}, {"_id": 0}):
        cust = p.get("customer_no") or "UNKNOWN"
        bucket = per_customer.setdefault(cust, {
            "scope_value": cust,
            "patterns_total": 0,
            "trusted": 0, "drifting": 0, "retired": 0, "unscored": 0,
            "last_feedback_at": p.get("last_feedback_at"),
        })
        lines = p.get("associated_lines") or []
        bucket["patterns_total"] += len(lines)
        if p.get("last_feedback_at") and (
            not bucket["last_feedback_at"]
            or p["last_feedback_at"] > bucket["last_feedback_at"]
        ):
            bucket["last_feedback_at"] = p["last_feedback_at"]
        for ln in lines:
            if ln.get("retired"):
                rep["summary"]["retired"] += 1
                bucket["retired"] += 1
            elif ln.get("trusted"):
                rep["summary"]["trusted"] += 1
                bucket["trusted"] += 1
            elif (ln.get("accept_count", 0) + ln.get("reject_count", 0)) >= 1:
                rep["summary"]["drifting"] += 1
                bucket["drifting"] += 1
            else:
                rep["summary"]["unscored"] += 1
                bucket["unscored"] += 1
    rep["summary"]["total"] = sum(
        rep["summary"][k] for k in ("trusted", "drifting", "retired", "unscored")
    )
    rep["per_scope"] = sorted(
        per_customer.values(), key=lambda x: x["patterns_total"], reverse=True,
    )[:limit]
    rep["recent_events"] = await list_events(
        domain="sales_intake", limit=10, db=db,
    )
    rep["trend_7d"] = await get_trend(domain="sales_intake", days=7, db=db)
    return rep


# ─────────────────────────────────────────────────────────────
# Adapter: ap_posting (posting_pattern_analysis)
# ─────────────────────────────────────────────────────────────

AP_TRUSTED_TIERS = {"high"}
AP_DRIFTING_TIERS = {"medium"}
AP_RETIRED_TIERS = {"none"}

# Implicit-trust thresholds: a vendor with a clean history earns trust even
# without explicit thumbs-up feedback. "No corrective events + N posted
# invoices" is treated as quiet success.
AP_IMPLICIT_TRUST_MIN_SAMPLES = 10
# Event types that *disqualify* a vendor from implicit trust. These indicate
# real drift: BC human corrections, explicit rejects, or flagged mismatches.
AP_NEGATIVE_EVENT_TYPES = {
    "draft_bc_feedback",        # BC user edited our auto-draft
    "draft_rejected",
    "pattern_rejected",
    "suggestion_rejected",
    "correction_applied",
    "drift_flagged",
}
# Window for considering a vendor "currently drifting" — anything older than
# this is stale and doesn't disqualify implicit trust.
AP_DRIFT_WINDOW_DAYS = 30


async def _fetch_ap_negative_events_by_vendor(db) -> Dict[str, int]:
    """Return {vendor_no: negative_event_count_last_N_days} aggregated from
    the unified learning_events_v2 log. Used to distinguish real drift from
    silent success."""
    from datetime import timedelta
    since = (
        datetime.now(timezone.utc) - timedelta(days=AP_DRIFT_WINDOW_DAYS)
    ).isoformat()
    counts: Dict[str, int] = {}
    try:
        pipeline = [
            {"$match": {
                "domain": "ap_posting",
                "event_type": {"$in": list(AP_NEGATIVE_EVENT_TYPES)},
                "scope_type": "vendor",
                "created_at": {"$gte": since},
            }},
            {"$group": {"_id": "$scope_value", "c": {"$sum": 1}}},
        ]
        async for row in db.learning_events_v2.aggregate(pipeline):
            if row.get("_id"):
                counts[row["_id"]] = int(row.get("c", 0))
    except Exception as e:  # noqa: BLE001 — implicit trust is best-effort
        logger.debug("[PatternHealth] negative event aggregation failed: %s", e)
    return counts


async def _ap_health(db, limit: int) -> Dict[str, Any]:
    rep = _empty_report("ap_posting")
    per_vendor: List[Dict[str, Any]] = []

    # Pull per-vendor negative event counts once (single aggregation) so the
    # main loop stays O(N_vendors) and not O(N_vendors * N_events).
    negative_counts = await _fetch_ap_negative_events_by_vendor(db)

    async for p in db.posting_pattern_analysis.find({}, {"_id": 0}):
        template = p.get("posting_template") or {}
        tier = (template.get("confidence") or "low").lower()
        samples = int(p.get("invoices_analyzed", 0) or 0)
        scope_value = p.get("vendor_no") or "UNKNOWN"
        neg_events = negative_counts.get(scope_value, 0)
        has_drift_signal = neg_events > 0

        # Normalize AP tier → our 4-state model. Rules (in order):
        #   1. Explicit retired / tier=none           → retired
        #   2. Tier=high (any samples)                → trusted   (explicit)
        #   3. Recent corrective events               → drifting  (real drift)
        #   4. Samples >= IMPLICIT_MIN and no drift   → trusted   (implicit)
        #      ("quiet success" — vendor posts cleanly, no BC corrections)
        #   5. Tier=medium                            → drifting  (still
        #                                               maturing, needs feedback)
        #   6. Everything else                        → unscored
        if p.get("status") == "retired" or tier in AP_RETIRED_TIERS:
            state = "retired"
            trust_reason = "retired"
        elif tier in AP_TRUSTED_TIERS and samples >= 3:
            state = "trusted"
            trust_reason = "explicit_high_tier"
        elif has_drift_signal:
            state = "drifting"
            trust_reason = f"{neg_events}_negative_event(s)_last_{AP_DRIFT_WINDOW_DAYS}d"
        elif samples >= AP_IMPLICIT_TRUST_MIN_SAMPLES:
            state = "trusted"
            trust_reason = f"implicit_success_{samples}_samples_no_drift"
        elif tier in AP_DRIFTING_TIERS:
            state = "drifting"
            trust_reason = "medium_tier_still_maturing"
        else:
            state = "unscored"
            trust_reason = "insufficient_samples"

        rep["summary"][state] += 1
        per_vendor.append({
            "scope_value": scope_value,
            "scope_name": p.get("vendor_name"),
            "patterns_total": 1,  # one profile per vendor
            "trusted": 1 if state == "trusted" else 0,
            "drifting": 1 if state == "drifting" else 0,
            "retired": 1 if state == "retired" else 0,
            "unscored": 1 if state == "unscored" else 0,
            "last_feedback_at": p.get("last_feedback_at")
                or p.get("last_posting_at")
                or p.get("last_analyzed_at"),
            "invoices_analyzed": samples,
            "confidence_tier": tier,
            "negative_events_30d": neg_events,
            "trust_reason": trust_reason,
        })

    rep["summary"]["total"] = sum(
        rep["summary"][k] for k in ("trusted", "drifting", "retired", "unscored")
    )
    rep["per_scope"] = sorted(
        per_vendor, key=lambda x: x.get("invoices_analyzed", 0), reverse=True,
    )[:limit]
    rep["recent_events"] = await list_events(
        domain="ap_posting", limit=10, db=db,
    )
    rep["trend_7d"] = await get_trend(domain="ap_posting", days=7, db=db)
    return rep


# ─────────────────────────────────────────────────────────────
# Hygiene adapters (retire / promote)
# ─────────────────────────────────────────────────────────────

async def _intake_hygiene(db) -> Dict[str, Any]:
    """Delegates to existing intake hygiene to avoid schema drift."""
    from services.intake_learning_feedback_service import run_pattern_hygiene
    return await run_pattern_hygiene(db=db)


async def _ap_hygiene(db) -> Dict[str, Any]:
    """Mark AP profiles retired when they drop to tier='none' and get 0 matches.
    Conservative: only retires — never auto-promotes (AP promotion is driven by
    `advanced_learning_engine` on actual posts, not by our heuristics)."""
    scanned = 0
    retired = 0
    async for p in db.posting_pattern_analysis.find(
        {"status": {"$ne": "retired"}}, {"_id": 0, "vendor_no": 1, "posting_template": 1},
    ):
        scanned += 1
        tier = ((p.get("posting_template") or {}).get("confidence") or "").lower()
        if tier == "none":
            await db.posting_pattern_analysis.update_one(
                {"vendor_no": p["vendor_no"]},
                {"$set": {
                    "status": "retired",
                    "retired_at": datetime.now(timezone.utc).isoformat(),
                    "retired_reason": "confidence dropped to none (unified hygiene)",
                }},
            )
            retired += 1
    return {
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "patterns_scanned": scanned,
        "retired": retired,
        "promoted": 0,
    }


# ─────────────────────────────────────────────────────────────
# Adapter registry
# ─────────────────────────────────────────────────────────────

HEALTH_ADAPTERS: Dict[str, Callable] = {
    "sales_intake": _intake_health,
    "ap_posting":   _ap_health,
}

HYGIENE_ADAPTERS: Dict[str, Callable] = {
    "sales_intake": _intake_hygiene,
    "ap_posting":   _ap_hygiene,
}


# ─────────────────────────────────────────────────────────────
# Public API
# ─────────────────────────────────────────────────────────────

async def get_health(
    domain: Optional[str] = None,
    *,
    limit: int = 25,
    db=None,
) -> Dict[str, Any]:
    """Return a HealthReport for a single domain, or a combined report
    if `domain` is None."""
    db = db if db is not None else get_db()
    if domain:
        adapter = HEALTH_ADAPTERS.get(domain)
        if not adapter:
            return {"error": f"unknown domain '{domain}'", "known": sorted(HEALTH_ADAPTERS)}
        return await adapter(db, limit)

    # Combined: run every adapter, aggregate summaries
    reports = []
    combined_summary = dict(EMPTY_SUMMARY)
    for d, adapter in HEALTH_ADAPTERS.items():
        try:
            r = await adapter(db, limit)
            reports.append(r)
            for k in EMPTY_SUMMARY:
                combined_summary[k] += r["summary"].get(k, 0)
        except Exception as e:
            logger.warning("[PatternHealth] adapter %s failed: %s", d, e)
            reports.append({
                "domain": d, "error": str(e),
                "summary": dict(EMPTY_SUMMARY),
                "per_scope": [], "recent_events": [],
            })
    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "combined_summary": combined_summary,
        "domains": reports,
    }


async def run_hygiene(
    domain: str = "all",
    *,
    actor: str = "user",
    db=None,
) -> Dict[str, Any]:
    """Run hygiene for a single domain or all domains. Records a summary
    row in `pattern_hygiene_runs` for audit."""
    db = db if db is not None else get_db()
    domains = list(HYGIENE_ADAPTERS) if domain == "all" else [domain]
    results: Dict[str, Any] = {}
    total_scanned = 0
    total_retired = 0
    total_promoted = 0
    for d in domains:
        adapter = HYGIENE_ADAPTERS.get(d)
        if not adapter:
            results[d] = {"error": f"unknown domain '{d}'"}
            continue
        try:
            r = await adapter(db)
            results[d] = r
            total_scanned += r.get("patterns_scanned", 0)
            total_retired += r.get("retired", 0)
            total_promoted += r.get("promoted", 0)
        except Exception as e:
            logger.warning("[PatternHealth.hygiene] %s failed: %s", d, e)
            results[d] = {"error": str(e)}

    run_doc = {
        "id": str(uuid.uuid4()),
        "ran_at": datetime.now(timezone.utc).isoformat(),
        "domain_requested": domain,
        "actor": actor,
        "total_scanned": total_scanned,
        "total_retired": total_retired,
        "total_promoted": total_promoted,
        "per_domain": results,
    }
    try:
        await db[HYGIENE_RUNS_COLL].insert_one(run_doc)
    except Exception as e:
        logger.warning("[PatternHealth.hygiene] log insert failed: %s", e)

    return {
        "ran_at": run_doc["ran_at"],
        "actor": actor,
        "domain_requested": domain,
        "total_scanned": total_scanned,
        "total_retired": total_retired,
        "total_promoted": total_promoted,
        "per_domain": results,
    }


__all__ = [
    "get_health",
    "run_hygiene",
    "HEALTH_ADAPTERS",
    "HYGIENE_ADAPTERS",
    "HYGIENE_RUNS_COLL",
]
