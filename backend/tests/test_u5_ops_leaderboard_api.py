"""
U5 — Learning Ops API regression.
Covers:
  * Regression on U3 /pattern-health/unified (domain + combined)
  * Regression on U4 /feedback (customer + vendor shapes)
  * Regression on hygiene/run + drift/scan + drift/summary

2026-09-24: dropped TestLeaderboard (GET /api/learning/reviewers/leaderboard
removed, was Learning-Ops-page-only) and the events-summary/events-feed
checks in TestOpsDependencies (GET /api/learning/events and
/api/learning/events/summary removed, same reason).
"""
import os
import requests

BASE_URL = os.environ.get("REACT_APP_BACKEND_URL", "").rstrip("/")
S = requests.Session()
S.headers.update({"Content-Type": "application/json"})


class TestPatternHealthUnifiedRegression:
    def test_domain_ap_posting(self):
        r = S.get(f"{BASE_URL}/api/learning/pattern-health/unified?domain=ap_posting&limit=15", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("domain") == "ap_posting"
        assert "summary" in d
        assert "per_scope" in d
        assert "trend_7d" in d

    def test_domain_sales_intake(self):
        r = S.get(f"{BASE_URL}/api/learning/pattern-health/unified?domain=sales_intake&limit=15", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert d.get("domain") == "sales_intake"
        assert "summary" in d
        assert isinstance(d.get("per_scope"), list)

    def test_combined(self):
        r = S.get(f"{BASE_URL}/api/learning/pattern-health/unified?limit=15", timeout=30)
        assert r.status_code == 200
        d = r.json()
        assert "combined_summary" in d
        assert isinstance(d.get("domains"), list)


class TestUnifiedFeedbackRegression:
    def test_customer_feedback(self):
        body = {
            "scope_type": "customer",
            "scope_value": "C-TEST_U5",
            "event_type": "suggestion_accepted",
            "item_no": "ITM-TEST",
            "actor": "TEST_u5",
        }
        r = S.post(f"{BASE_URL}/api/learning/feedback", json=body, timeout=30)
        assert r.status_code == 200, r.text

    def test_vendor_feedback_missing_document_id(self):
        body = {"scope_type": "vendor", "scope_value": "V-TEST", "actor": "TEST_u5"}
        r = S.post(f"{BASE_URL}/api/learning/feedback", json=body, timeout=30)
        # Router returns 200 with {error: ...} per contract (never raises)
        assert r.status_code == 200

    def test_invalid_scope_type(self):
        body = {"scope_type": "banana", "actor": "TEST_u5"}
        r = S.post(f"{BASE_URL}/api/learning/feedback", json=body, timeout=30)
        assert r.status_code == 200


class TestOpsDependencies:
    def test_drift_summary(self):
        r = S.get(f"{BASE_URL}/api/learning/drift/summary", timeout=30)
        assert r.status_code == 200

    def test_drift_alerts_open(self):
        r = S.get(f"{BASE_URL}/api/learning/drift/alerts?status=open&limit=25", timeout=30)
        assert r.status_code == 200
        assert "alerts" in r.json()

    def test_hygiene_run_all(self):
        r = S.post(f"{BASE_URL}/api/learning/hygiene/run?domain=all", timeout=60)
        assert r.status_code == 200

    def test_drift_scan(self):
        r = S.post(f"{BASE_URL}/api/learning/drift/scan", timeout=60)
        assert r.status_code == 200
