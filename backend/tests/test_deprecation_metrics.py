"""
Tests for /api/admin/deprecation-metrics response, especially the
`phase_4_gate` projection that collapses the drain-window check into a
single boolean.

Hard gate contract (per user directive 2026-04-22):
  Phase 4 (delete Path B AP mutation routes) ships only when the six
  mutation templates show zero hits for 7 consecutive days AND the
  regression suite is green.

This file covers the first half — the zero-hits projection — by
manipulating db.deprecation_hits directly and asserting the endpoint's
`phase_4_gate.gate_met` and `offending_callers` fields flip correctly.

Also asserts the endpoint documents its own observability limitation
(Pydantic 422 body-validation errors are raised BEFORE the _deprecate
wrapper runs, so they never reach db.deprecation_hits).
"""

import os
import pytest
import requests
from datetime import datetime, timezone, timedelta
from pymongo import MongoClient


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "hub-admin@gamerpackaging.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ChangeMeOnFirstDeploy-K8p2q")


def _load_env():
    raw = open("/app/backend/.env").read()
    out = {}
    for line in raw.splitlines():
        if "=" in line and not line.strip().startswith("#"):
            k, _, v = line.partition("=")
            out[k.strip()] = v.strip()
    return out


@pytest.fixture(scope="module")
def admin_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    if r.status_code != 200:
        pytest.skip(f"Admin login unavailable: {r.status_code}")
    return r.json().get("token")


@pytest.fixture
def clean_hits_collection():
    """Wipe db.deprecation_hits before and after each test (sync pymongo)."""
    env = _load_env()
    client = MongoClient(env["MONGO_URL"])
    db = client[env["DB_NAME"]]
    db.deprecation_hits.delete_many({})
    yield db
    db.deprecation_hits.delete_many({})
    client.close()


# ---------------------------------------------------------------------------
# Endpoint shape + auth
# ---------------------------------------------------------------------------


def test_endpoint_rejects_missing_jwt():
    r = requests.get(f"{BASE_URL}/api/admin/deprecation-metrics", timeout=10)
    assert r.status_code == 401


def test_endpoint_rejects_days_zero(admin_token):
    # Query validator enforces ge=1; days=0 must return 422, not a soft error.
    r = requests.get(
        f"{BASE_URL}/api/admin/deprecation-metrics?days=0",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 422


def test_phase_4_gate_block_present_in_response(admin_token):
    r = requests.get(
        f"{BASE_URL}/api/admin/deprecation-metrics",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    assert r.status_code == 200
    body = r.json()
    assert "phase_4_gate" in body
    gate = body["phase_4_gate"]

    # Contract-level assertions — the fields the user gates Phase 4 on.
    assert isinstance(gate["gate_met"], bool)
    assert gate["window_days"] == 7
    assert len(gate["ap_mutation_routes_monitored"]) == 6
    assert isinstance(gate["total_hits_in_window"], int)
    assert isinstance(gate["hits_by_template"], dict)
    assert isinstance(gate["offending_callers"], list)

    # 422 blind-spot disclosure must be present and must actually mention 422.
    limitations = gate.get("observability_limitations", [])
    assert any("422" in limit for limit in limitations), (
        "phase_4_gate.observability_limitations must disclose the 422 "
        "pre-wrapper blind spot in plain text so the limitation is impossible "
        "to miss."
    )


# ---------------------------------------------------------------------------
# gate_met flips correctly
# ---------------------------------------------------------------------------


def test_gate_met_true_when_no_hits(admin_token, clean_hits_collection):
    """Empty deprecation_hits → gate_met=true, zero offending callers."""
    r = requests.get(
        f"{BASE_URL}/api/admin/deprecation-metrics",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    gate = r.json()["phase_4_gate"]
    assert gate["gate_met"] is True
    assert gate["total_hits_in_window"] == 0
    assert gate["offending_callers"] == []
    # All six monitored templates must appear in hits_by_template with count 0.
    for template in gate["ap_mutation_routes_monitored"]:
        assert gate["hits_by_template"].get(template) == 0


def test_gate_met_false_when_in_window_hit_exists(admin_token, clean_hits_collection):
    """A single hit today on any of the six AP mutation templates → gate NOT met."""
    db = clean_hits_collection
    today = datetime.now(timezone.utc).strftime("%Y-%m-%d")
    db.deprecation_hits.insert_one({
        "deprecated_path": "/api/workflows/ap_invoice/{doc_id}/approve",
        "canonical_path": "/api/ap-review/documents/{doc_id}/approve",
        "method": "POST",
        "day_bucket": today,
        "count": 1,
        "first_seen_utc": datetime.now(timezone.utc).isoformat(),
        "last_seen_utc": datetime.now(timezone.utc).isoformat(),
        "last_status": 200,
        "last_client_host": "10.0.0.42",
        "last_user_agent": "suspicious-cron/1.0",
        "last_auth_present": True,
    })

    r = requests.get(
        f"{BASE_URL}/api/admin/deprecation-metrics",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    gate = r.json()["phase_4_gate"]
    assert gate["gate_met"] is False
    assert gate["total_hits_in_window"] == 1
    assert len(gate["offending_callers"]) == 1

    offender = gate["offending_callers"][0]
    assert offender["deprecated_path"] == "/api/workflows/ap_invoice/{doc_id}/approve"
    # Caller identification fields must be present — that's the whole point.
    assert offender["last_client_host"] == "10.0.0.42"
    assert offender["last_user_agent"] == "suspicious-cron/1.0"


def test_gate_met_true_when_hit_is_outside_7day_window(admin_token, clean_hits_collection):
    """A hit 30 days ago must NOT spoil today's gate — window is 7 days."""
    db = clean_hits_collection
    old_bucket = (
        datetime.now(timezone.utc) - timedelta(days=30)
    ).strftime("%Y-%m-%d")
    db.deprecation_hits.insert_one({
        "deprecated_path": "/api/workflows/ap_invoice/{doc_id}/approve",
        "canonical_path": "/api/ap-review/documents/{doc_id}/approve",
        "method": "POST",
        "day_bucket": old_bucket,
        "count": 5,
        "first_seen_utc": datetime.now(timezone.utc).isoformat(),
        "last_seen_utc": datetime.now(timezone.utc).isoformat(),
        "last_status": 200,
        "last_client_host": "10.0.0.99",
        "last_user_agent": "old-caller/0.1",
        "last_auth_present": True,
    })

    r = requests.get(
        f"{BASE_URL}/api/admin/deprecation-metrics",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    gate = r.json()["phase_4_gate"]
    assert gate["gate_met"] is True, (
        "A hit older than the 7-day gate window must not block Phase 4"
    )
    assert gate["total_hits_in_window"] == 0


def test_gate_query_is_independent_of_days_param(admin_token, clean_hits_collection):
    """days=1 on the query must not shrink the gate window — gate is always 7 days."""
    db = clean_hits_collection
    four_days_ago = (
        datetime.now(timezone.utc) - timedelta(days=4)
    ).strftime("%Y-%m-%d")
    db.deprecation_hits.insert_one({
        "deprecated_path": "/api/workflows/ap_invoice/{doc_id}/reject",
        "canonical_path": "/api/ap-review/documents/{doc_id}/reject",
        "method": "POST",
        "day_bucket": four_days_ago,
        "count": 1,
        "first_seen_utc": datetime.now(timezone.utc).isoformat(),
        "last_seen_utc": datetime.now(timezone.utc).isoformat(),
        "last_status": 400,
        "last_client_host": "10.0.0.7",
        "last_user_agent": "sneaky/1",
        "last_auth_present": False,
    })

    # Caller asks for days=1 (last 24h). The gate projection still looks at 7 days.
    r = requests.get(
        f"{BASE_URL}/api/admin/deprecation-metrics?days=1",
        headers={"Authorization": f"Bearer {admin_token}"},
        timeout=10,
    )
    body = r.json()
    assert body["window_days"] == 1, "caller's requested window respected for route_totals"
    # But gate_met reflects the 7-day mandatory window.
    assert body["phase_4_gate"]["gate_met"] is False
    assert body["phase_4_gate"]["total_hits_in_window"] == 1
