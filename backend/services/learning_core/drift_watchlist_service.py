"""
GPI Document Hub — Drift Watchlist Service (v2.5.4)
────────────────────────────────────────────────────

Weekly actionable notification that surfaces vendors the AI needs human
attention on. Pulls from:
  • `posting_pattern_analysis` + `learning_events_v2` (negative events in the
    last 30 days — BC corrections, explicit rejects, drift flags)
  • `learning_drift_alerts` (open, unacknowledged drift rules)

Dispatches the watchlist across any combination of channels configured via
the `DRIFT_WATCHLIST_CHANNELS` env var (comma-separated):
  • `teams_webhook`  — POST an Adaptive Card to `TEAMS_DRIFT_WEBHOOK_URL`
  • `graph_channel`  — MS Graph channel message to
                       `TEAMS_DRIFT_TEAM_ID` / `TEAMS_DRIFT_CHANNEL_ID`
  • `email`          — MS Graph /sendMail to `DRIFT_WATCHLIST_EMAIL_TO`

Empty watchlist = skip send (no noise). All operations best-effort — a
failing channel never blocks the others or the scheduler loop.
"""
from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

import httpx

from deps import get_db
from services.learning_core.pattern_health_service import (
    AP_DRIFT_WINDOW_DAYS,
    AP_NEGATIVE_EVENT_TYPES,
)

logger = logging.getLogger(__name__)

# ── Env / config ────────────────────────────────────────────────
CHANNELS_ENV = "DRIFT_WATCHLIST_CHANNELS"
TEAMS_WEBHOOK_ENV = "TEAMS_DRIFT_WEBHOOK_URL"
TEAMS_TEAM_ID_ENV = "TEAMS_DRIFT_TEAM_ID"
TEAMS_CHANNEL_ID_ENV = "TEAMS_DRIFT_CHANNEL_ID"
EMAIL_TO_ENV = "DRIFT_WATCHLIST_EMAIL_TO"
EMAIL_FROM_ENV = "DRIFT_WATCHLIST_EMAIL_FROM"
APP_BASE_URL_ENV = "APP_PUBLIC_URL"  # e.g. https://gpi-hub.example.com
MAX_VENDORS_IN_CARD = 15


# ── Build ───────────────────────────────────────────────────────

async def build_watchlist(db=None) -> Dict[str, Any]:
    """Aggregate vendors needing attention into a single sortable list.

    Returns:
        {
          "generated_at": iso,
          "window_days": 30,
          "vendors": [
            {vendor_no, vendor_name, negative_events_30d,
             open_drift_alerts, last_event_at, score},
          ],
          "open_drift_alerts_total": int,
        }
    """
    db = db if db is not None else get_db()
    since = (
        datetime.now(timezone.utc) - timedelta(days=AP_DRIFT_WINDOW_DAYS)
    ).isoformat()

    per_vendor: Dict[str, Dict[str, Any]] = {}

    # 1. Negative events per vendor
    try:
        pipeline = [
            {"$match": {
                "domain": "ap_posting",
                "event_type": {"$in": list(AP_NEGATIVE_EVENT_TYPES)},
                "scope_type": "vendor",
                "created_at": {"$gte": since},
            }},
            {"$group": {
                "_id": "$scope_value",
                "count": {"$sum": 1},
                "last_at": {"$max": "$created_at"},
            }},
        ]
        async for row in db.learning_events_v2.aggregate(pipeline):
            vn = row.get("_id")
            if not vn:
                continue
            per_vendor[vn] = {
                "vendor_no": vn,
                "vendor_name": None,
                "negative_events_30d": int(row.get("count", 0)),
                "last_event_at": row.get("last_at"),
                "open_drift_alerts": 0,
            }
    except Exception as e:  # noqa: BLE001
        logger.warning("[DriftWatchlist] negative events aggregation failed: %s", e)

    # 2. Open drift alerts (not ack'd, not resolved)
    open_alerts_total = 0
    try:
        async for a in db.learning_drift_alerts.find(
            {"status": {"$in": [None, "open", "new"]}},
            {"_id": 0, "scope_value": 1, "vendor_no": 1, "alert_type": 1, "created_at": 1},
        ):
            open_alerts_total += 1
            vn = a.get("scope_value") or a.get("vendor_no")
            if not vn:
                continue
            slot = per_vendor.setdefault(vn, {
                "vendor_no": vn,
                "vendor_name": None,
                "negative_events_30d": 0,
                "last_event_at": a.get("created_at"),
                "open_drift_alerts": 0,
            })
            slot["open_drift_alerts"] += 1
            if a.get("created_at") and (
                not slot.get("last_event_at") or a["created_at"] > slot["last_event_at"]
            ):
                slot["last_event_at"] = a["created_at"]
    except Exception as e:  # noqa: BLE001
        logger.warning("[DriftWatchlist] drift alerts scan failed: %s", e)

    # 3. Enrich with vendor_name from posting_pattern_analysis
    if per_vendor:
        try:
            async for p in db.posting_pattern_analysis.find(
                {"vendor_no": {"$in": list(per_vendor)}},
                {"_id": 0, "vendor_no": 1, "vendor_name": 1},
            ):
                if p.get("vendor_no") in per_vendor:
                    per_vendor[p["vendor_no"]]["vendor_name"] = p.get("vendor_name")
        except Exception as e:  # noqa: BLE001
            logger.debug("[DriftWatchlist] vendor name lookup failed: %s", e)

    # 4. Score = 2 * open_drift_alerts + negative_events_30d (alerts weigh more)
    vendors = list(per_vendor.values())
    for v in vendors:
        v["score"] = 2 * v["open_drift_alerts"] + v["negative_events_30d"]
    vendors.sort(key=lambda x: (-x["score"], x["vendor_no"]))

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "window_days": AP_DRIFT_WINDOW_DAYS,
        "vendors": vendors,
        "open_drift_alerts_total": open_alerts_total,
    }


# ── Format ──────────────────────────────────────────────────────

def _vendor_link(vendor_no: str, base_url: Optional[str] = None) -> str:
    base = base_url or os.environ.get(APP_BASE_URL_ENV, "").rstrip("/")
    if not base:
        return vendor_no
    return f"{base}/ai-learning?vendor={vendor_no}"


def format_teams_card(watchlist: Dict[str, Any]) -> Dict[str, Any]:
    """Build an Adaptive Card payload for Teams (webhook + Graph channel share
    the same card body shape)."""
    vendors = watchlist.get("vendors", [])[:MAX_VENDORS_IN_CARD]
    total = len(watchlist.get("vendors", []))
    truncated = total > MAX_VENDORS_IN_CARD

    if not vendors:
        body = [{
            "type": "TextBlock",
            "text": "Drift Watchlist — nothing to review this week.",
            "weight": "Bolder",
            "size": "Medium",
        }]
    else:
        facts = [
            {
                "title": f"{v.get('vendor_name') or v['vendor_no']} ({v['vendor_no']})",
                "value": (
                    f"{v['open_drift_alerts']} open alert(s), "
                    f"{v['negative_events_30d']} correction(s) in "
                    f"{watchlist['window_days']}d"
                ),
            }
            for v in vendors
        ]
        body = [
            {
                "type": "TextBlock",
                "text": f"Drift Watchlist — {total} vendor(s) need review",
                "weight": "Bolder",
                "size": "Large",
                "wrap": True,
            },
            {
                "type": "TextBlock",
                "text": (
                    f"Open drift alerts: **{watchlist.get('open_drift_alerts_total', 0)}** "
                    f"· window: last **{watchlist['window_days']}d**"
                ),
                "isSubtle": True,
                "wrap": True,
            },
            {"type": "FactSet", "facts": facts},
        ]
        if truncated:
            body.append({
                "type": "TextBlock",
                "text": f"(+{total - MAX_VENDORS_IN_CARD} more not shown)",
                "isSubtle": True,
                "wrap": True,
            })

    return {
        "type": "message",
        "attachments": [{
            "contentType": "application/vnd.microsoft.card.adaptive",
            "content": {
                "$schema": "http://adaptivecards.io/schemas/adaptive-card.json",
                "type": "AdaptiveCard",
                "version": "1.4",
                "body": body,
            },
        }],
    }


def format_email_html(watchlist: Dict[str, Any]) -> str:
    vendors = watchlist.get("vendors", [])
    if not vendors:
        return (
            "<p><strong>Drift Watchlist</strong> — nothing to review this week. "
            f"({watchlist.get('open_drift_alerts_total', 0)} open alerts total)</p>"
        )
    rows = "".join(
        f"<tr>"
        f"<td><a href='{_vendor_link(v['vendor_no'])}'>{v.get('vendor_name') or v['vendor_no']}</a></td>"
        f"<td>{v['vendor_no']}</td>"
        f"<td style='text-align:right'>{v['open_drift_alerts']}</td>"
        f"<td style='text-align:right'>{v['negative_events_30d']}</td>"
        f"<td>{v.get('last_event_at') or '—'}</td>"
        f"</tr>"
        for v in vendors
    )
    return (
        "<h2>Drift Watchlist</h2>"
        f"<p>{len(vendors)} vendor(s) need review "
        f"(window: last {watchlist['window_days']} days, "
        f"{watchlist.get('open_drift_alerts_total', 0)} open drift alerts total).</p>"
        "<table border='1' cellpadding='6' cellspacing='0' "
        "style='border-collapse:collapse;font-family:sans-serif;font-size:13px'>"
        "<thead><tr>"
        "<th>Vendor</th><th>No.</th><th>Open alerts</th>"
        "<th>Corrections (30d)</th><th>Last event</th>"
        "</tr></thead>"
        f"<tbody>{rows}</tbody>"
        "</table>"
    )


# ── Dispatch ────────────────────────────────────────────────────

async def _send_teams_webhook(card: Dict[str, Any], url: str) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(url, json=card)
        return {"status": r.status_code, "body": r.text[:200]}


async def _send_graph_channel_message(card: Dict[str, Any]) -> Dict[str, Any]:
    team_id = os.environ.get(TEAMS_TEAM_ID_ENV)
    channel_id = os.environ.get(TEAMS_CHANNEL_ID_ENV)
    if not team_id or not channel_id:
        return {"skipped": "missing TEAMS_DRIFT_TEAM_ID / TEAMS_DRIFT_CHANNEL_ID"}
    from services.config_service import get_graph_token
    token = await get_graph_token()
    if not token:
        return {"error": "graph token unavailable"}
    attachment_id = "drift-watchlist-1"
    import json as _json
    payload = {
        "body": {
            "contentType": "html",
            "content": f'<attachment id="{attachment_id}"></attachment>',
        },
        "attachments": [{
            "id": attachment_id,
            "contentType": "application/vnd.microsoft.card.adaptive",
            # Must be a JSON string per Graph API spec. `str(dict)` would
            # produce Python-repr output (single quotes, True/False/None)
            # which Graph 400s — and vendor names with apostrophes would
            # silently corrupt the payload. Use json.dumps.
            "content": _json.dumps(card["attachments"][0]["content"]),
        }],
    }
    url = (
        f"https://graph.microsoft.com/v1.0/teams/{team_id}"
        f"/channels/{channel_id}/messages"
    )
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        return {"status": r.status_code, "body": r.text[:200]}


async def _send_email(watchlist: Dict[str, Any]) -> Dict[str, Any]:
    to_addrs = os.environ.get(EMAIL_TO_ENV, "")
    sender = os.environ.get(EMAIL_FROM_ENV)
    if not to_addrs or not sender:
        return {"skipped": "missing DRIFT_WATCHLIST_EMAIL_TO / DRIFT_WATCHLIST_EMAIL_FROM"}
    from services.config_service import get_graph_token
    token = await get_graph_token()
    if not token:
        return {"error": "graph token unavailable"}
    html = format_email_html(watchlist)
    vendor_count = len(watchlist.get("vendors", []))
    subject = (
        f"[GPI Hub] Drift Watchlist — {vendor_count} vendor(s) need review"
        if vendor_count else "[GPI Hub] Drift Watchlist — quiet week"
    )
    payload = {
        "message": {
            "subject": subject,
            "body": {"contentType": "HTML", "content": html},
            "toRecipients": [
                {"emailAddress": {"address": a.strip()}}
                for a in to_addrs.split(",") if a.strip()
            ],
        },
        "saveToSentItems": False,
    }
    url = f"https://graph.microsoft.com/v1.0/users/{sender}/sendMail"
    async with httpx.AsyncClient(timeout=15) as c:
        r = await c.post(
            url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json=payload,
        )
        return {"status": r.status_code, "body": r.text[:200]}


def _resolve_channels(override: Optional[List[str]] = None) -> List[str]:
    if override:
        return [c.strip() for c in override if c and c.strip()]
    raw = os.environ.get(CHANNELS_ENV, "") or ""
    return [c.strip() for c in raw.split(",") if c.strip()]


async def send_watchlist(
    *,
    channels: Optional[List[str]] = None,
    actor: str = "scheduler",
    db=None,
) -> Dict[str, Any]:
    """Build and dispatch the watchlist. Returns a per-channel result map.

    Empty watchlist → logged + skipped (no noise).
    """
    db = db if db is not None else get_db()
    watchlist = await build_watchlist(db=db)
    vendor_count = len(watchlist.get("vendors", []))
    resolved = _resolve_channels(channels)

    result: Dict[str, Any] = {
        "actor": actor,
        "generated_at": watchlist["generated_at"],
        "vendor_count": vendor_count,
        "open_drift_alerts_total": watchlist.get("open_drift_alerts_total", 0),
        "channels_requested": resolved,
        "per_channel": {},
    }

    if vendor_count == 0 and watchlist.get("open_drift_alerts_total", 0) == 0:
        result["skipped"] = "empty_watchlist"
        logger.info("[DriftWatchlist] nothing to send — skipping dispatch")
        # Still persist a run record for observability
        await _persist_run(db, result)
        return result

    if not resolved:
        result["skipped"] = "no_channels_configured"
        logger.info("[DriftWatchlist] no channels configured; would have sent %d vendors", vendor_count)
        await _persist_run(db, result)
        return result

    card = format_teams_card(watchlist)

    for ch in resolved:
        try:
            if ch == "teams_webhook":
                url = os.environ.get(TEAMS_WEBHOOK_ENV)
                if not url:
                    result["per_channel"][ch] = {"skipped": f"missing {TEAMS_WEBHOOK_ENV}"}
                else:
                    result["per_channel"][ch] = await _send_teams_webhook(card, url)
            elif ch == "graph_channel":
                result["per_channel"][ch] = await _send_graph_channel_message(card)
            elif ch == "email":
                result["per_channel"][ch] = await _send_email(watchlist)
            else:
                result["per_channel"][ch] = {"error": f"unknown channel '{ch}'"}
        except Exception as e:  # noqa: BLE001 — one failing channel must not kill others
            logger.warning("[DriftWatchlist] channel %s failed: %s", ch, e)
            result["per_channel"][ch] = {"error": str(e)}

    await _persist_run(db, result)
    return result


async def _persist_run(db, result: Dict[str, Any]) -> None:
    try:
        await db.drift_watchlist_runs.insert_one({
            **result,
            "ran_at": datetime.now(timezone.utc).isoformat(),
        })
    except Exception as e:  # noqa: BLE001
        logger.debug("[DriftWatchlist] run log insert failed: %s", e)


__all__ = [
    "build_watchlist",
    "format_teams_card",
    "format_email_html",
    "send_watchlist",
]
