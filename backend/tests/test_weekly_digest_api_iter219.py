"""
API-level regression tests for Weekly Digest endpoints (iteration 219).

Exercises the public REACT_APP_BACKEND_URL so we validate routing,
auth, idempotency, and invalid input via real HTTP.
"""

import os
import requests
import pytest

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
if not BASE_URL:
    pytest.skip("REACT_APP_BACKEND_URL not set", allow_module_level=True)


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


class TestWeeklyDigestAPI:
    # POST rebuild — happy path
    def test_rebuild_current_week_returns_expected_shape(self, client):
        r = client.post(f"{BASE_URL}/api/learning/digest/rebuild", timeout=30)
        assert r.status_code == 200, r.text
        d = r.json()
        for key in (
            "week_key", "week_start", "week_end", "headline", "events",
            "top_reviewers", "drift_summary", "pattern_health_snapshot",
            "trend_7d",
        ):
            assert key in d, f"missing key {key} in digest payload: {list(d.keys())}"
        assert isinstance(d["events"], dict)
        for sub in ("total", "by_domain", "by_event_type"):
            assert sub in d["events"]
        assert isinstance(d["top_reviewers"], list)
        assert "sales_intake" in d["trend_7d"]
        assert "ap_posting" in d["trend_7d"]

    # POST rebuild — invalid week_of → returns 200 w/ {error}
    def test_rebuild_invalid_week_of_returns_error_payload(self, client):
        r = client.post(
            f"{BASE_URL}/api/learning/digest/rebuild",
            params={"week_of": "not-a-date"},
            timeout=15,
        )
        assert r.status_code == 200
        body = r.json()
        assert "error" in body
        assert "invalid" in body["error"].lower()

    # POST rebuild — idempotency: two calls → one doc (verified via list dedup)
    def test_rebuild_is_idempotent_by_week_key(self, client):
        r1 = client.post(f"{BASE_URL}/api/learning/digest/rebuild", timeout=30).json()
        r2 = client.post(f"{BASE_URL}/api/learning/digest/rebuild", timeout=30).json()
        assert r1["week_key"] == r2["week_key"]
        lst = client.get(f"{BASE_URL}/api/learning/digest", params={"limit": 50}, timeout=15).json()
        items = (
            lst.get("digests") or lst.get("items")
            if isinstance(lst, dict) else lst
        )
        # count occurrences of this week_key
        wk = r1["week_key"]
        matching = [d for d in items if d.get("week_key") == wk]
        assert len(matching) == 1, f"Expected 1 row for {wk}, got {len(matching)}"

    # GET latest
    def test_latest_returns_current_digest(self, client):
        # ensure at least one exists
        mk = client.post(f"{BASE_URL}/api/learning/digest/rebuild", timeout=30).json()
        r = client.get(f"{BASE_URL}/api/learning/digest/latest", timeout=15)
        assert r.status_code == 200
        body = r.json()
        # API may wrap in {digest: ...} or return the digest directly
        d = body.get("digest") if isinstance(body, dict) and "digest" in body else body
        assert d is not None
        assert d.get("week_key") == mk["week_key"]

    # GET by unknown week_key -> 404
    def test_get_digest_by_unknown_week_key_returns_404(self, client):
        r = client.get(f"{BASE_URL}/api/learning/digest/1999-W01", timeout=15)
        assert r.status_code == 404

    # GET by known week_key -> 200
    def test_get_digest_by_known_week_key_returns_200(self, client):
        mk = client.post(f"{BASE_URL}/api/learning/digest/rebuild", timeout=30).json()
        r = client.get(f"{BASE_URL}/api/learning/digest/{mk['week_key']}", timeout=15)
        assert r.status_code == 200
        d = r.json()
        assert d.get("week_key") == mk["week_key"]

    # GET list newest-first with slim fields
    def test_list_digests_newest_first(self, client):
        r = client.get(f"{BASE_URL}/api/learning/digest", params={"limit": 5}, timeout=15)
        assert r.status_code == 200
        body = r.json()
        items = (
            body.get("digests") or body.get("items")
            if isinstance(body, dict) else body
        )
        assert isinstance(items, list)
        starts = [x.get("week_start") for x in items if x.get("week_start")]
        assert starts == sorted(starts, reverse=True), f"Not newest-first: {starts}"


if __name__ == "__main__":
    pytest.main([__file__, "-v"])
