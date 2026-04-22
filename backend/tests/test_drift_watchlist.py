"""
Unit tests for the Drift Watchlist service (v2.5.4).

Covers:
    - build_watchlist aggregation from learning_events_v2 + learning_drift_alerts
    - score/sort ordering (alerts weigh 2x negative events)
    - format_teams_card: empty + populated + truncation
    - format_email_html: empty + populated with <tr> rows
    - send_watchlist: empty-watchlist skip, no-channels skip,
      per-channel dispatch, per-channel failure isolation
    - _resolve_channels env parsing
"""
import os
from datetime import datetime, timedelta, timezone
from unittest.mock import patch, AsyncMock

import pytest

from workflows.core.learning_core.drift_watchlist_service import (
    build_watchlist,
    format_teams_card,
    format_email_html,
    send_watchlist,
    _resolve_channels,
    MAX_VENDORS_IN_CARD,
)


# ────────── Fake DB plumbing ──────────

class _FakeCursor:
    def __init__(self, docs):
        self._docs = list(docs)
        self._i = 0

    def __aiter__(self):
        return self

    async def __anext__(self):
        if self._i >= len(self._docs):
            raise StopAsyncIteration
        d = self._docs[self._i]
        self._i += 1
        return d

    def sort(self, *_a, **_kw):
        return self

    def limit(self, *_a, **_kw):
        return self

    async def to_list(self, *_a, **_kw):
        return list(self._docs)


class _FakeCollection:
    def __init__(self, docs=None, aggregate_rows=None):
        self.docs = list(docs or [])
        self.agg = list(aggregate_rows or [])
        self.inserted = []

    def find(self, *_a, **_kw):
        return _FakeCursor(self.docs)

    def aggregate(self, *_a, **_kw):
        return _FakeCursor(self.agg)

    async def insert_one(self, d):
        self.inserted.append(d)
        return d


class _FakeDB:
    def __init__(self, events_agg=None, alerts=None, ppa=None):
        self.learning_events_v2 = _FakeCollection(aggregate_rows=events_agg or [])
        self.learning_drift_alerts = _FakeCollection(docs=alerts or [])
        self.posting_pattern_analysis = _FakeCollection(docs=ppa or [])
        self.drift_watchlist_runs = _FakeCollection()


# ────────── build_watchlist ──────────

@pytest.mark.asyncio
async def test_empty_db_yields_empty_watchlist():
    db = _FakeDB()
    wl = await build_watchlist(db=db)
    assert wl["vendors"] == []
    assert wl["open_drift_alerts_total"] == 0
    assert wl["window_days"] > 0


@pytest.mark.asyncio
async def test_negative_events_roll_up_per_vendor():
    now = datetime.now(timezone.utc).isoformat()
    db = _FakeDB(events_agg=[
        {"_id": "V1", "count": 4, "last_at": now},
        {"_id": "V2", "count": 1, "last_at": now},
    ])
    wl = await build_watchlist(db=db)
    by_vendor = {v["vendor_no"]: v for v in wl["vendors"]}
    assert by_vendor["V1"]["negative_events_30d"] == 4
    assert by_vendor["V2"]["negative_events_30d"] == 1


@pytest.mark.asyncio
async def test_open_alerts_merge_into_watchlist_and_count():
    now = datetime.now(timezone.utc).isoformat()
    db = _FakeDB(
        events_agg=[{"_id": "V1", "count": 2, "last_at": now}],
        alerts=[
            {"scope_value": "V1", "status": "open", "created_at": now},
            {"scope_value": "V3", "status": "open", "created_at": now},
            {"vendor_no": "V4", "status": None, "created_at": now},
        ],
    )
    wl = await build_watchlist(db=db)
    vendors = {v["vendor_no"]: v for v in wl["vendors"]}
    assert wl["open_drift_alerts_total"] == 3
    assert vendors["V1"]["open_drift_alerts"] == 1  # has both events and 1 alert
    assert vendors["V1"]["negative_events_30d"] == 2
    assert vendors["V3"]["open_drift_alerts"] == 1  # alert-only
    assert vendors["V4"]["open_drift_alerts"] == 1  # vendor_no fallback


@pytest.mark.asyncio
async def test_sort_score_and_ties():
    """score = 2 * alerts + events. Higher score first; ties broken by vendor_no."""
    now = datetime.now(timezone.utc).isoformat()
    db = _FakeDB(
        events_agg=[
            {"_id": "LOW", "count": 1, "last_at": now},
            {"_id": "HIGH", "count": 10, "last_at": now},
            {"_id": "MID", "count": 3, "last_at": now},
        ],
        alerts=[
            # Give MID 2 alerts → score = 4+3 = 7; HIGH = 0+10 = 10; LOW = 0+1 = 1
            {"scope_value": "MID", "status": "open", "created_at": now},
            {"scope_value": "MID", "status": "open", "created_at": now},
        ],
    )
    wl = await build_watchlist(db=db)
    ordered = [v["vendor_no"] for v in wl["vendors"]]
    assert ordered == ["HIGH", "MID", "LOW"]


@pytest.mark.asyncio
async def test_vendor_name_enriched_from_ppa():
    now = datetime.now(timezone.utc).isoformat()
    db = _FakeDB(
        events_agg=[{"_id": "V1", "count": 1, "last_at": now}],
        ppa=[{"vendor_no": "V1", "vendor_name": "Acme Corp"}],
    )
    wl = await build_watchlist(db=db)
    assert wl["vendors"][0]["vendor_name"] == "Acme Corp"


# ────────── format_teams_card ──────────

def test_teams_card_empty():
    card = format_teams_card({"vendors": [], "open_drift_alerts_total": 0, "window_days": 30})
    text = card["attachments"][0]["content"]["body"][0]["text"]
    assert "nothing to review" in text.lower()


def test_teams_card_populated_has_factset():
    wl = {
        "vendors": [
            {"vendor_no": "V1", "vendor_name": "Acme",
             "negative_events_30d": 3, "open_drift_alerts": 1},
            {"vendor_no": "V2", "vendor_name": None,
             "negative_events_30d": 1, "open_drift_alerts": 0},
        ],
        "open_drift_alerts_total": 1,
        "window_days": 30,
    }
    card = format_teams_card(wl)
    body = card["attachments"][0]["content"]["body"]
    factset = [b for b in body if b.get("type") == "FactSet"][0]
    assert len(factset["facts"]) == 2
    assert "Acme" in factset["facts"][0]["title"]
    assert "V2" in factset["facts"][1]["title"]  # falls back to vendor_no


def test_teams_card_truncated_when_over_max():
    wl = {
        "vendors": [
            {"vendor_no": f"V{i}", "vendor_name": None,
             "negative_events_30d": 1, "open_drift_alerts": 0}
            for i in range(MAX_VENDORS_IN_CARD + 5)
        ],
        "open_drift_alerts_total": 0, "window_days": 30,
    }
    card = format_teams_card(wl)
    body = card["attachments"][0]["content"]["body"]
    last = body[-1]["text"]
    assert "+5 more" in last


# ────────── format_email_html ──────────

def test_email_empty_html():
    html = format_email_html({"vendors": [], "open_drift_alerts_total": 0, "window_days": 30})
    assert "Drift Watchlist" in html
    assert "<tr>" not in html


def test_email_populated_html_has_table_rows():
    wl = {
        "vendors": [
            {"vendor_no": "V1", "vendor_name": "Acme",
             "negative_events_30d": 3, "open_drift_alerts": 1, "last_event_at": "2026-04-18T12:00:00"},
        ],
        "open_drift_alerts_total": 1, "window_days": 30,
    }
    html = format_email_html(wl)
    assert "<tr>" in html
    assert "Acme" in html
    assert "V1" in html


# ────────── send_watchlist dispatch ──────────

@pytest.mark.asyncio
async def test_send_empty_watchlist_skips():
    db = _FakeDB()
    with patch.dict(os.environ, {"DRIFT_WATCHLIST_CHANNELS": "teams_webhook"}, clear=False):
        result = await send_watchlist(db=db, actor="test")
    assert result["skipped"] == "empty_watchlist"
    assert result["per_channel"] == {}
    # Still logged
    assert len(db.drift_watchlist_runs.inserted) == 1


@pytest.mark.asyncio
async def test_send_no_channels_configured_skips():
    now = datetime.now(timezone.utc).isoformat()
    db = _FakeDB(events_agg=[{"_id": "V1", "count": 1, "last_at": now}])
    with patch.dict(os.environ, {"DRIFT_WATCHLIST_CHANNELS": ""}, clear=False):
        result = await send_watchlist(db=db, actor="test")
    assert result["skipped"] == "no_channels_configured"


@pytest.mark.asyncio
async def test_send_teams_webhook_success():
    now = datetime.now(timezone.utc).isoformat()
    db = _FakeDB(events_agg=[{"_id": "V1", "count": 2, "last_at": now}])
    env = {
        "DRIFT_WATCHLIST_CHANNELS": "teams_webhook",
        "TEAMS_DRIFT_WEBHOOK_URL": "https://example.com/hook",
    }
    with patch.dict(os.environ, env, clear=False), \
         patch("workflows.core.learning_core.drift_watchlist_service._send_teams_webhook",
               new_callable=AsyncMock) as mock_send:
        mock_send.return_value = {"status": 200, "body": "ok"}
        result = await send_watchlist(db=db, actor="test")
    assert result["vendor_count"] == 1
    assert result["per_channel"]["teams_webhook"] == {"status": 200, "body": "ok"}
    mock_send.assert_awaited_once()


@pytest.mark.asyncio
async def test_send_one_failing_channel_does_not_kill_others():
    now = datetime.now(timezone.utc).isoformat()
    db = _FakeDB(events_agg=[{"_id": "V1", "count": 1, "last_at": now}])
    env = {"DRIFT_WATCHLIST_CHANNELS": "teams_webhook,email"}
    with patch.dict(os.environ, env, clear=False), \
         patch("workflows.core.learning_core.drift_watchlist_service._send_teams_webhook",
               new_callable=AsyncMock) as mock_teams, \
         patch("workflows.core.learning_core.drift_watchlist_service._send_email",
               new_callable=AsyncMock) as mock_email:
        mock_teams.side_effect = RuntimeError("boom")
        mock_email.return_value = {"status": 202}
        # Also need TEAMS_DRIFT_WEBHOOK_URL to be present so the webhook path runs
        with patch.dict(os.environ, {"TEAMS_DRIFT_WEBHOOK_URL": "https://x/y"}, clear=False):
            result = await send_watchlist(db=db, actor="test")
    assert "error" in result["per_channel"]["teams_webhook"]
    assert result["per_channel"]["email"] == {"status": 202}


@pytest.mark.asyncio
async def test_unknown_channel_is_reported_not_thrown():
    now = datetime.now(timezone.utc).isoformat()
    db = _FakeDB(events_agg=[{"_id": "V1", "count": 1, "last_at": now}])
    with patch.dict(os.environ, {"DRIFT_WATCHLIST_CHANNELS": "sms_pigeon"}, clear=False):
        result = await send_watchlist(db=db, actor="test")
    assert "error" in result["per_channel"]["sms_pigeon"]


def test_resolve_channels_env_parsing():
    with patch.dict(os.environ, {"DRIFT_WATCHLIST_CHANNELS": "teams_webhook, email, "}, clear=False):
        assert _resolve_channels() == ["teams_webhook", "email"]
    with patch.dict(os.environ, {"DRIFT_WATCHLIST_CHANNELS": ""}, clear=False):
        assert _resolve_channels() == []
    # Override takes precedence
    assert _resolve_channels(["email"]) == ["email"]
