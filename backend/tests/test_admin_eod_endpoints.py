"""Pytest for admin EOD router (Lane C Step 3B).

Covers:
  - Flag-off → 501 on both /run and /last-run
  - force=true bypasses the flag on /run only
  - Valid dry-run returns aggregate report with 5 step rows
"""

from __future__ import annotations

import os
import uuid
from typing import Any

import mongomock_motor
import pytest
from fastapi.testclient import TestClient


@pytest.fixture
def client_and_db(monkeypatch):
    # Use an isolated mongomock DB for each test and inject via deps.set_db.
    mongo_client = mongomock_motor.AsyncMongoMockClient()
    db = mongo_client[f"test_eod_router_{uuid.uuid4().hex[:8]}"]

    # Build a minimal FastAPI app containing only the admin_eod router.
    from fastapi import FastAPI
    import deps
    from routers.admin_eod import router as admin_eod_router

    deps.set_db(db)
    app = FastAPI()
    app.include_router(admin_eod_router, prefix="/api")

    client = TestClient(app)
    return client, db


def _set_flag(monkeypatch, enabled: bool):
    monkeypatch.setenv("EOD_ENABLED", "true" if enabled else "false")


def test_run_endpoint_returns_501_when_flag_off(client_and_db, monkeypatch):
    client, _ = client_and_db
    _set_flag(monkeypatch, False)
    resp = client.post("/api/admin/eod/run", json={})
    assert resp.status_code == 501


def test_last_run_endpoint_returns_501_when_flag_off(client_and_db, monkeypatch):
    client, _ = client_and_db
    _set_flag(monkeypatch, False)
    resp = client.get("/api/admin/eod/last-run")
    assert resp.status_code == 501


def test_force_true_bypasses_flag_on_run(client_and_db, monkeypatch):
    client, db = client_and_db
    _set_flag(monkeypatch, False)
    resp = client.post(
        "/api/admin/eod/run",
        json={"force": True, "dry_run": True},
    )
    assert resp.status_code == 200
    payload = resp.json()
    assert payload["dry_run"] is True
    assert len(payload["steps"]) == 5


def test_run_and_last_run_happy_path_when_flag_on(client_and_db, monkeypatch):
    client, db = client_and_db
    _set_flag(monkeypatch, True)

    resp = client.post("/api/admin/eod/run", json={"dry_run": True})
    assert resp.status_code == 200
    run_id = resp.json()["run_id"]

    resp2 = client.get("/api/admin/eod/last-run")
    assert resp2.status_code == 200
    body = resp2.json()
    assert "latest_per_step" in body
    assert set(body["latest_per_step"].keys()) == {
        "advance_readiness", "post_ready_docs", "send_posted_docs",
        "escalate_stuck", "reconcile_cost_receipt",
    }
    for step in body["latest_per_step"].values():
        assert step["run_id"] == run_id


def test_run_with_unknown_step_returns_400(client_and_db, monkeypatch):
    client, _ = client_and_db
    _set_flag(monkeypatch, True)
    resp = client.post(
        "/api/admin/eod/run",
        json={"steps": ["bogus_step"], "dry_run": True},
    )
    assert resp.status_code == 400


def test_last_run_unknown_step_returns_400(client_and_db, monkeypatch):
    client, _ = client_and_db
    _set_flag(monkeypatch, True)
    resp = client.get("/api/admin/eod/last-run?step=bogus")
    assert resp.status_code == 400
