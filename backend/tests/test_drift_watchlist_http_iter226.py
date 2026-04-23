"""HTTP-level tests for Drift Watchlist endpoints (iter 226)."""
import os
import time
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://eod-controller-seq.preview.emergentagent.com").rstrip("/")
API = f"{BASE_URL}/api"


def test_preview_shape():
    r = requests.get(f"{API}/learning/drift-watchlist/preview", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert set(data.keys()) >= {"watchlist", "teams_card", "email_html"}
    wl = data["watchlist"]
    assert "vendors" in wl and isinstance(wl["vendors"], list)
    assert "open_drift_alerts_total" in wl
    assert "window_days" in wl
    assert isinstance(data["teams_card"], dict)
    assert isinstance(data["email_html"], str)


def test_send_now_empty_watchlist():
    r = requests.post(f"{API}/learning/drift-watchlist/send-now", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    # In preview env there's no vendors & no drift alerts → empty_watchlist
    # but if data exists, it might be no_channels_configured (also acceptable)
    assert data.get("skipped") in ("empty_watchlist", "no_channels_configured"), data


def test_send_now_unknown_channel_override():
    # Seed nothing — the behaviour we want is: if watchlist is empty, we still
    # get empty_watchlist skip (no per_channel). If watchlist is non-empty, we get
    # per_channel.sms_pigeon with error. Either proves the code path is wired.
    r = requests.post(
        f"{API}/learning/drift-watchlist/send-now",
        params={"channels": "sms_pigeon"},
        timeout=30,
    )
    assert r.status_code == 200, r.text
    data = r.json()
    if data.get("skipped") == "empty_watchlist":
        # Expected in preview env with no events/alerts
        assert "sms_pigeon" in data.get("channels_requested", [])
    else:
        assert "sms_pigeon" in data.get("per_channel", {})
        assert "error" in data["per_channel"]["sms_pigeon"]


def test_runs_endpoint_persists():
    # Trigger two quick sends then fetch runs
    requests.post(f"{API}/learning/drift-watchlist/send-now", timeout=30)
    time.sleep(0.2)
    requests.post(
        f"{API}/learning/drift-watchlist/send-now",
        params={"channels": "sms_pigeon"},
        timeout=30,
    )
    time.sleep(0.3)
    r = requests.get(f"{API}/learning/drift-watchlist/runs", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "total" in data and "runs" in data
    assert isinstance(data["runs"], list)
    assert data["total"] >= 1
    # Verify at least one recent run has expected fields
    if data["runs"]:
        run = data["runs"][0]
        assert "actor" in run or "generated_at" in run or "ran_at" in run


# ── Regression on unrelated endpoints ──
def test_inbox_stats_regression():
    r = requests.get(f"{API}/dashboard/inbox-stats", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert isinstance(data.get("posted_to_bc_7d"), int)
    assert isinstance(data.get("ready_for_post"), int)


def test_pattern_health_unified_regression():
    r = requests.get(f"{API}/learning/pattern-health/unified", timeout=30)
    assert r.status_code == 200, r.text
    data = r.json()
    assert "combined_summary" in data
    assert "domains" in data
