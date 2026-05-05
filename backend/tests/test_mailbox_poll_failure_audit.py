"""
Regression tests for the silent-MailboxPoll-failure bug.

Symptom (pre-fix): when Graph returned non-2xx for a configured
mailbox (e.g. billing@gamerpackaging.com → HTTP 404), the poll
function logged "Starting" but never logged "Complete" or "Failed",
never persisted run stats to mail_poll_runs, and never raised. As a
result, AP intake silently stopped for 7+ days without any telemetry.

The fix in services/email_polling_service.py guarantees:
  • Every invocation of poll_mailbox_for_documents persists an audit
    row to mail_poll_runs (status = ok | failed_graph | failed_token
    | failed_exception).
  • Graph non-2xx responses are recorded with the HTTP status and
    body excerpt.
  • Successful runs continue to log "Complete" with mailbox + counts.
  • Successful all-duplicate runs (the hub-ap-intake steady-state
    case) still complete cleanly with status=ok.
"""
from __future__ import annotations

import os
import asyncio
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
    """In-memory stand-in for the parts of the db the function uses."""
    inserted: List[Dict[str, Any]] = []

    class _Coll:
        async def insert_one(self, doc):
            inserted.append(doc)

        async def find_one(self, *a, **kw):
            return None

        async def update_one(self, *a, **kw):
            return None

    db = MagicMock()
    db.mail_poll_runs = _Coll()
    db.hub_settings = _Coll()
    db.hub_documents = _Coll()
    db.mail_intake_log = _Coll()
    db._inserted_runs = inserted  # test handle
    return db


@pytest.fixture
def patched_module(fake_db, monkeypatch):
    """Import email_polling_service with get_db monkey-patched."""
    monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
    monkeypatch.setenv("DB_NAME", "test")
    monkeypatch.setenv("EMAIL_POLLING_ENABLED", "true")
    monkeypatch.setenv("EMAIL_POLLING_USER", "hub-ap-intake@gamerpackaging.com")

    import services.email_polling_service as eps
    importlib.reload(eps)
    monkeypatch.setattr(eps, "get_db", lambda: fake_db)
    monkeypatch.setattr(eps, "get_email_token",
                        AsyncMock(return_value="fake-token"), raising=False)
    return eps


@pytest.mark.asyncio
async def test_graph_404_records_failed_poll_run(patched_module, fake_db):
    """Graph 404 must produce a mail_poll_runs row with status=failed_graph."""
    eps = patched_module

    fake_resp = _fake_graph_resp(404, text='{"error":"Resource not found"}')

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def get(self, *a, **kw): return fake_resp

    with patch.object(eps, "httpx") as mock_httpx, \
         patch("services.config_service.get_email_token",
               new=AsyncMock(return_value="fake-token")):
        mock_httpx.AsyncClient = _FakeClient
        stats = await eps.poll_mailbox_for_documents(
            mailbox_address="billing@gamerpackaging.com",
            default_category="AP",
            source_id="src-billing",
        )

    assert stats["status"] == "failed_graph"
    assert stats["graph_http_status"] == 404
    assert any("404" in e for e in stats["errors"])
    assert len(fake_db._inserted_runs) == 1, "must persist failure to mail_poll_runs"
    row = fake_db._inserted_runs[0]
    assert row["mailbox"] == "billing@gamerpackaging.com"
    assert row["default_category"] == "AP"
    assert row["status"] == "failed_graph"
    assert row["graph_http_status"] == 404
    assert "completed_at" in row


@pytest.mark.asyncio
async def test_failed_token_records_failed_poll_run(patched_module, fake_db):
    """No Graph token → status=failed_token, audit row persisted."""
    eps = patched_module

    with patch("services.config_service.get_email_token",
               new=AsyncMock(return_value=None)):
        stats = await eps.poll_mailbox_for_documents(
            mailbox_address="billing@gamerpackaging.com",
            default_category="AP",
            source_id="src-billing",
        )

    assert stats["status"] == "failed_token"
    assert any("token" in e.lower() for e in stats["errors"])
    assert len(fake_db._inserted_runs) == 1
    assert fake_db._inserted_runs[0]["status"] == "failed_token"


@pytest.mark.asyncio
async def test_steady_state_all_duplicate_still_completes_ok(patched_module, fake_db):
    """hub-ap-intake's 25-msg dedup steady-state must remain status=ok."""
    eps = patched_module

    msgs_resp = _fake_graph_resp(200, body={
        "value": [
            {"id": f"msg-{i}",
             "subject": f"inv {i}",
             "from": {"emailAddress": {"address": f"vendor{i}@x.com"}},
             "receivedDateTime": "2026-05-05T17:00:00Z",
             "internetMessageId": f"<mid-{i}@x>",
             "hasAttachments": True,
             "bodyPreview": "..."} for i in range(25)
        ],
    })

    class _FakeClient:
        def __init__(self, *a, **kw): pass
        async def __aenter__(self): return self
        async def __aexit__(self, *a): return None
        async def get(self, url, **kw):
            # Only return on /messages? — attachments path returns 404
            # to short-circuit per-attachment work.
            if "/Inbox/messages" in url:
                return msgs_resp
            return _fake_graph_resp(404)

    with patch.object(eps, "httpx") as mock_httpx, \
         patch("services.config_service.get_email_token",
               new=AsyncMock(return_value="fake-token")):
        mock_httpx.AsyncClient = _FakeClient
        stats = await eps.poll_mailbox_for_documents(
            mailbox_address="hub-ap-intake@gamerpackaging.com",
            default_category="AP",
            source_id="src-hub-ap",
        )

    assert stats["status"] == "ok"
    assert stats["graph_http_status"] == 200
    assert stats["messages_detected"] == 25
    assert len(fake_db._inserted_runs) == 1
    assert fake_db._inserted_runs[0]["status"] == "ok"
