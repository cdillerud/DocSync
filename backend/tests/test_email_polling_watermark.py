"""
Regression tests for the watermark-stuck-cluster bug in
services.email_polling_service.poll_mailbox_for_attachments.

Symptom (pre-fix): the function used
    filter_query = "receivedDateTime ge {watermark - 5min}"
combined with $top=25 and $orderby=receivedDateTime asc. When 25+ messages
landed inside a 5-minute window at the watermark, every poll cycle re-fetched
the same 25 oldest messages, max(receivedDateTime) equaled the current
watermark, and the watermark never advanced. New messages received after
that cluster were trapped at position 26+ and never reached.

Production impact: hub-ap-intake@gamerpackaging.com watermark stuck at
2026-04-09T21:02:12Z for 27 days. 4,199 polls between 2026-04-21 and
2026-05-06, every one with attachments_ingested=0. AP intake silently
dead while polling logs reported "ok".

The fix:
  • filter_query = "receivedDateTime gt {watermark}"  (strict, no buffer)
  • watermark only updates when newest_received > current watermark
  • when a batch is non-empty but cannot advance the watermark, record
    stalled_watermark in mail_poll_runs and emit a WARNING log line
"""
from __future__ import annotations

import importlib
from typing import Any, Dict, List
from unittest.mock import AsyncMock, MagicMock, patch

import pytest


def _fake_graph_resp(status: int, body: Dict[str, Any] | None = None,
                     text: str = "") -> MagicMock:
    r = MagicMock()
    r.status_code = status
    r.json = MagicMock(return_value=body or {})
    r.text = text
    return r


@pytest.fixture
def fake_db():
    inserted_runs: List[Dict[str, Any]] = []
    watermark_state: Dict[str, Any] = {}
    update_calls: List[Dict[str, Any]] = []

    class _RunsColl:
        async def insert_one(self, doc):
            inserted_runs.append(doc)

    class _SettingsColl:
        async def find_one(self, *a, **kw):
            if watermark_state:
                d = dict(watermark_state)
                d.pop("_id", None)
                return d
            return None

        async def update_one(self, query, update, upsert=False):
            set_block = update.get("$set", {})
            watermark_state.update(set_block)
            watermark_state["type"] = query.get("type")
            update_calls.append({"query": query, "update": update, "upsert": upsert})

    class _NoopColl:
        async def insert_one(self, *a, **kw): return None
        async def find_one(self, *a, **kw): return None
        async def update_one(self, *a, **kw): return None

    db = MagicMock()
    db.mail_poll_runs = _RunsColl()
    db.hub_settings = _SettingsColl()
    db.hub_documents = _NoopColl()
    db.mail_intake_log = _NoopColl()
    db._inserted_runs = inserted_runs
    db._watermark_state = watermark_state
    db._update_calls = update_calls
    return db


@pytest.fixture
def patched_module(fake_db, monkeypatch):
    monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
    monkeypatch.setenv("DB_NAME", "test")
    monkeypatch.setenv("EMAIL_POLLING_ENABLED", "true")
    monkeypatch.setenv("EMAIL_POLLING_USER", "hub-ap-intake@gamerpackaging.com")
    monkeypatch.setenv("DEMO_MODE", "false")

    import services.email_polling_service as eps
    importlib.reload(eps)
    monkeypatch.setattr(eps, "get_db", lambda: fake_db)
    monkeypatch.setattr(eps, "EMAIL_POLLING_ENABLED", True)
    monkeypatch.setattr(eps, "EMAIL_POLLING_USER", "hub-ap-intake@gamerpackaging.com")
    monkeypatch.setattr(eps, "DEMO_MODE", False)
    return eps


def _make_fake_client(messages_response, attachments_response=None):
    """Builds a fake httpx.AsyncClient that captures the $filter param."""
    captured = {"filter": None, "calls": 0}

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None

        async def get(self, url, headers=None, params=None):
            captured["calls"] += 1
            if "/Inbox/messages" in url:
                if params:
                    captured["filter"] = params.get("$filter")
                    captured["top"] = params.get("$top")
                    captured["orderby"] = params.get("$orderby")
                return messages_response
            if "/attachments" in url:
                return attachments_response or _fake_graph_resp(200, {"value": []})
            return _fake_graph_resp(404)

    return _FakeClient, captured


# ─────────────────────────────────────────────────────────────────────────────
# Test 1: strict gt cursor — filter must use gt, not ge
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_filter_uses_strict_gt_watermark(patched_module, fake_db):
    """The Graph $filter must use 'gt {watermark}', not 'ge {watermark - 5min}'."""
    eps = patched_module
    fake_db._watermark_state.update({
        "type": "email_poll_watermark",
        "last_received_datetime": "2026-04-09T21:02:12Z",
    })

    msgs_resp = _fake_graph_resp(200, body={"value": []})
    FakeClient, captured = _make_fake_client(msgs_resp)

    with patch.object(eps, "httpx") as mock_httpx, \
         patch("services.config_service.get_email_token",
               new=AsyncMock(return_value="fake-token")):
        mock_httpx.AsyncClient = FakeClient
        await eps.poll_mailbox_for_attachments()

    assert captured["filter"] is not None, "must call /Inbox/messages"
    assert captured["filter"].startswith("receivedDateTime gt "), \
        f"expected strict gt cursor, got: {captured['filter']!r}"
    assert "2026-04-09T21:02:12Z" in captured["filter"], \
        "filter must use exact watermark, no 5-minute back-buffer"
    assert captured["orderby"] == "receivedDateTime asc"


# ─────────────────────────────────────────────────────────────────────────────
# Test 2: 25 dup messages exactly at watermark must NOT trap polling
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_25_duplicate_messages_at_boundary_do_not_trap(patched_module, fake_db):
    """
    Pre-fix bug: 25 messages with receivedDateTime <= watermark looped
    forever. Post-fix: strict gt means those messages are filtered out
    server-side, so the next poll fetches the next page.

    Simulate: watermark = 2026-04-09T21:02:12Z. Inbox has 25 messages
    received exactly at that timestamp (or earlier). With strict gt,
    Graph would return [] for those, and the function should NOT
    retreat the watermark.
    """
    eps = patched_module
    initial_watermark = "2026-04-09T21:02:12Z"
    fake_db._watermark_state.update({
        "type": "email_poll_watermark",
        "last_received_datetime": initial_watermark,
    })

    # With strict gt {watermark}, Graph would filter out the 25 stuck ones
    # server-side. Simulate by returning empty.
    msgs_resp = _fake_graph_resp(200, body={"value": []})
    FakeClient, _ = _make_fake_client(msgs_resp)

    with patch.object(eps, "httpx") as mock_httpx, \
         patch("services.config_service.get_email_token",
               new=AsyncMock(return_value="fake-token")):
        mock_httpx.AsyncClient = FakeClient
        await eps.poll_mailbox_for_attachments()

    # Watermark must NOT regress.
    assert fake_db._watermark_state["last_received_datetime"] == initial_watermark, \
        "watermark must never retreat"
    # No advance attempted (empty batch).
    assert len(fake_db._update_calls) == 0, \
        "no watermark write when batch is empty"


# ─────────────────────────────────────────────────────────────────────────────
# Test 3: watermark advances when later messages arrive
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_watermark_advances_on_newer_messages(patched_module, fake_db):
    """When the batch contains messages newer than the current watermark,
    the watermark must advance to max(receivedDateTime)."""
    eps = patched_module
    fake_db._watermark_state.update({
        "type": "email_poll_watermark",
        "last_received_datetime": "2026-04-09T21:02:12Z",
    })

    msgs_resp = _fake_graph_resp(200, body={"value": [
        {"id": "m1", "subject": "Test 1",
         "from": {"emailAddress": {"address": "v1@x.com"}},
         "receivedDateTime": "2026-05-06T01:42:54Z",
         "internetMessageId": "<m1@x>",
         "hasAttachments": False},
        {"id": "m2", "subject": "Test 2",
         "from": {"emailAddress": {"address": "v2@x.com"}},
         "receivedDateTime": "2026-05-06T01:47:59Z",
         "internetMessageId": "<m2@x>",
         "hasAttachments": False},
    ]})
    FakeClient, _ = _make_fake_client(msgs_resp)

    with patch.object(eps, "httpx") as mock_httpx, \
         patch("services.config_service.get_email_token",
               new=AsyncMock(return_value="fake-token")):
        mock_httpx.AsyncClient = FakeClient
        stats = await eps.poll_mailbox_for_attachments()

    assert fake_db._watermark_state["last_received_datetime"] == "2026-05-06T01:47:59Z", \
        "watermark must advance to max(receivedDateTime) in batch"
    assert stats.get("watermark_advanced") is True
    assert stats.get("watermark_in") == "2026-04-09T21:02:12Z"
    assert stats.get("watermark_out") == "2026-05-06T01:47:59Z"
    assert "stalled_watermark" not in stats


# ─────────────────────────────────────────────────────────────────────────────
# Test 4: stalled_watermark recorded when batch cannot advance cursor
# ─────────────────────────────────────────────────────────────────────────────
@pytest.mark.asyncio
async def test_stalled_watermark_audit_when_no_advance(patched_module, fake_db):
    """Defense-in-depth canary: if a non-empty batch arrives but its
    max(receivedDateTime) does not exceed the current watermark, the
    function must record stalled_watermark for visibility instead of
    silently looping. With strict gt this is theoretically unreachable
    via Graph, but we audit it anyway."""
    eps = patched_module
    initial_watermark = "2026-04-09T21:02:12Z"
    fake_db._watermark_state.update({
        "type": "email_poll_watermark",
        "last_received_datetime": initial_watermark,
    })

    # Pathological: messages with receivedDateTime <= watermark
    # (would not be returned by a correctly-functioning Graph
    # filter using strict gt, but we simulate the broken case).
    msgs_resp = _fake_graph_resp(200, body={"value": [
        {"id": f"m{i}", "subject": f"stuck {i}",
         "from": {"emailAddress": {"address": f"v{i}@x.com"}},
         "receivedDateTime": "2026-04-09T21:02:12Z",
         "internetMessageId": f"<stuck-{i}@x>",
         "hasAttachments": False} for i in range(25)
    ]})
    FakeClient, _ = _make_fake_client(msgs_resp)

    with patch.object(eps, "httpx") as mock_httpx, \
         patch("services.config_service.get_email_token",
               new=AsyncMock(return_value="fake-token")):
        mock_httpx.AsyncClient = FakeClient
        stats = await eps.poll_mailbox_for_attachments()

    # Watermark must NOT regress.
    assert fake_db._watermark_state["last_received_datetime"] == initial_watermark
    # No watermark write attempted (advancement check failed).
    assert len(fake_db._update_calls) == 0
    # Stall must be visibly recorded.
    assert stats.get("watermark_advanced") is False
    assert "stalled_watermark" in stats
    stall = stats["stalled_watermark"]
    assert stall["mailbox"] == "hub-ap-intake@gamerpackaging.com"
    assert stall["watermark_in"] == initial_watermark
    assert stall["max_seen"] == "2026-04-09T21:02:12Z"
    assert stall["batch_size"] == 25
    # And it must be in the persisted mail_poll_runs row.
    assert len(fake_db._inserted_runs) == 1
    assert "stalled_watermark" in fake_db._inserted_runs[0]
