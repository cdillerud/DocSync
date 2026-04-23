"""
Iter 220 — Backend coverage for Rep Overrides UI + WoW Delta Banner.

Endpoints exercised:
  - GET    /api/sales-dashboard/rep-overrides?active_only=true
  - GET    /api/sales-dashboard/reps
  - POST   /api/sales-dashboard/rep-overrides
  - DELETE /api/sales-dashboard/rep-overrides/{customer_no}
  - GET    /api/learning/digest?limit=2
  - Regression U3/U4/U5: pattern-health, events/summary, drift/summary,
    hygiene/run, digest/rebuild, feedback (customer shape)
"""
import os
import pytest
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "https://eod-controller-seq.preview.emergentagent.com").rstrip("/")


@pytest.fixture(scope="module")
def client():
    s = requests.Session()
    s.headers.update({"Content-Type": "application/json"})
    return s


# ---------- Rep Overrides CRUD ----------
class TestRepOverrides:
    def test_list_active_overrides(self, client):
        r = client.get(f"{BASE_URL}/api/sales-dashboard/rep-overrides?active_only=true", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "overrides" in data
        assert isinstance(data["overrides"], list)

    def test_demo_override_seed_present(self, client):
        r = client.get(f"{BASE_URL}/api/sales-dashboard/rep-overrides?active_only=true", timeout=30)
        assert r.status_code == 200
        rows = r.json().get("overrides", [])
        demo = [o for o in rows if (o.get("customer_no") == "C-DEMO-OVRD-1")]
        assert demo, "Seed override C-DEMO-OVRD-1 missing"
        o = demo[0]
        assert o.get("rep_email"), "rep_email missing on demo override"

    def test_reps_endpoint(self, client):
        r = client.get(f"{BASE_URL}/api/sales-dashboard/reps", timeout=30)
        assert r.status_code == 200
        data = r.json()
        assert "reps" in data
        assert isinstance(data["reps"], list)

    def test_upsert_and_delete_iter220(self, client):
        payload = {
            "customer_no": "C-ITER-220-TEST",
            "customer_name": "Iter 220 Test Co.",
            "rep_email": "iter220-test@example.com",
            "rep_name": "Iter 220 Rep",
            "reason": "Automated test",
            "notes": "created by test_iter220",
        }
        # CREATE
        r = client.post(f"{BASE_URL}/api/sales-dashboard/rep-overrides", json=payload, timeout=30)
        assert r.status_code in (200, 201), r.text
        body = r.json()
        assert body.get("rep_email") == payload["rep_email"]

        # VERIFY persistence via GET
        r2 = client.get(f"{BASE_URL}/api/sales-dashboard/rep-overrides?active_only=true", timeout=30)
        assert r2.status_code == 200
        rows = r2.json().get("overrides", [])
        found = [o for o in rows if o.get("customer_no") == "C-ITER-220-TEST"]
        assert found, "Upserted override not visible in list"
        assert found[0]["rep_email"] == payload["rep_email"]

        # DELETE (cleanup)
        r3 = client.delete(f"{BASE_URL}/api/sales-dashboard/rep-overrides/C-ITER-220-TEST", timeout=30)
        assert r3.status_code in (200, 204), r3.text

        # VERIFY removal (no longer in active list)
        r4 = client.get(f"{BASE_URL}/api/sales-dashboard/rep-overrides?active_only=true", timeout=30)
        rows = r4.json().get("overrides", [])
        assert not [o for o in rows if o.get("customer_no") == "C-ITER-220-TEST"], "Override still active after DELETE"


# ---------- WoW Digest Banner data source ----------
class TestDigestsForBanner:
    def test_digest_limit_two(self, client):
        r = client.get(f"{BASE_URL}/api/learning/digest?limit=2", timeout=30)
        assert r.status_code == 200, r.text
        data = r.json()
        assert "digests" in data
        assert isinstance(data["digests"], list)
        # Should have >=1; ideally 2 given iter220 seed
        assert len(data["digests"]) >= 1


# ---------- Regression: U3/U4/U5 ----------
class TestLearningRegression:
    def test_pattern_health_unified(self, client):
        r = client.get(f"{BASE_URL}/api/learning/pattern-health/unified", timeout=30)
        assert r.status_code == 200

    def test_events_summary(self, client):
        r = client.get(f"{BASE_URL}/api/learning/events/summary", timeout=30)
        assert r.status_code == 200

    def test_drift_summary(self, client):
        r = client.get(f"{BASE_URL}/api/learning/drift/summary", timeout=30)
        assert r.status_code == 200

    def test_feedback_customer_shape(self, client):
        payload = {
            "domain": "sales_intake",
            "event_type": "customer_feedback",
            "scope_type": "customer",
            "scope_value": "ITER-220",
            "actor": "iter220-tester",
            "signal": "confirm",
            "payload": {"note": "regression test"},
        }
        r = client.post(f"{BASE_URL}/api/learning/feedback", json=payload, timeout=30)
        assert r.status_code in (200, 201), r.text

    def test_hygiene_run(self, client):
        r = client.post(f"{BASE_URL}/api/learning/hygiene/run", timeout=60)
        assert r.status_code == 200

    def test_digest_rebuild(self, client):
        # Soft check — do not fail hard if rebuild endpoint returns server-side state issue
        r = client.post(f"{BASE_URL}/api/learning/digest/rebuild", timeout=60)
        assert r.status_code in (200, 201, 202), r.text
