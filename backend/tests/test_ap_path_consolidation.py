"""
AP Path consolidation regression tests.

The canonical AP mutation surface is:
  /api/ap-review/documents/{doc_id}/{action}

The six legacy /api/workflows/ap_invoice/{doc_id}/{action} routes completed
their one-release compatibility window and are now retired. These tests assert
that Path A remains registered and authenticated while Path B stays absent
from OpenAPI and returns 404 without deprecation headers.
"""

import os
import pytest
import requests


BASE_URL = (
    os.environ.get("REACT_APP_BACKEND_URL")
    or "http://localhost:8001"
).rstrip("/")

ADMIN_EMAIL = os.environ.get("ADMIN_EMAIL", "hub-admin@gamerpackaging.com")
ADMIN_PASSWORD = os.environ.get("ADMIN_PASSWORD", "ChangeMeOnFirstDeploy-K8p2q")


AP_MUTATION_ACTIONS = [
    ("set-vendor", {"vendor_id": "V1"}),
    ("update-fields", {"invoice_number": "INV-1"}),
    ("override-bc-validation", {"override_reason": "r", "override_user": "u"}),
    ("start-approval", {"approver": "u"}),
    ("approve", {"approver": "u"}),
    ("reject", {"reason": "no", "approver": "u"}),
]


@pytest.fixture(scope="module")
def jwt_token():
    r = requests.post(
        f"{BASE_URL}/api/auth/login",
        json={"email": ADMIN_EMAIL, "password": ADMIN_PASSWORD},
        timeout=10,
    )
    if r.status_code != 200:
        pytest.skip(f"Admin login unavailable at {BASE_URL}: {r.status_code}")
    return r.json().get("token")


# ---------------------------------------------------------------------------
# OpenAPI schema inventory
# ---------------------------------------------------------------------------


@pytest.fixture(scope="module")
def openapi():
    r = requests.get(f"{BASE_URL}/openapi.json", timeout=10)
    if r.status_code != 200:
        pytest.skip(f"openapi.json unavailable: {r.status_code}")
    return r.json()


class TestCanonicalPathARegistered:
    """Path A canonical AP mutation surface must exist."""

    @pytest.mark.parametrize("action,_body", AP_MUTATION_ACTIONS)
    def test_path_a_registered(self, openapi, action, _body):
        path = f"/api/ap-review/documents/{{doc_id}}/{action}"
        assert path in openapi["paths"], f"Missing canonical route {path}"
        assert "post" in openapi["paths"][path], f"{path} must expose POST"




# ---------------------------------------------------------------------------
# Auth enforcement on Path A
# ---------------------------------------------------------------------------


class TestPathAAuthEnforcement:
    @pytest.mark.parametrize("action,body", AP_MUTATION_ACTIONS)
    def test_requires_jwt(self, action, body):
        r = requests.post(
            f"{BASE_URL}/api/ap-review/documents/nonexistent/{action}",
            json=body,
            timeout=10,
        )
        assert r.status_code == 401, (
            f"Path A {action} must enforce JWT, got {r.status_code}"
        )

    @pytest.mark.parametrize("action,body", AP_MUTATION_ACTIONS)
    def test_authenticated_reaches_handler(self, jwt_token, action, body):
        r = requests.post(
            f"{BASE_URL}/api/ap-review/documents/nonexistent/{action}",
            json=body,
            headers={"Authorization": f"Bearer {jwt_token}"},
            timeout=10,
        )
        # Handler is reached → either 404 (doc not found) or 400 (validation).
        # We must NOT see 401 any more.
        assert r.status_code in (400, 404), (
            f"Path A {action} with auth should hit handler (400/404), "
            f"got {r.status_code}: {r.text}"
        )


# ---------------------------------------------------------------------------
# X-Deprecated headers on Path B (success AND error paths)
# ---------------------------------------------------------------------------

# ---------------------------------------------------------------------------
# Retired Path B stays removed
# ---------------------------------------------------------------------------


class TestRetiredPathBRemoved:
    # Path B completed its release window and must remain retired.

    @pytest.mark.parametrize("action,_body", AP_MUTATION_ACTIONS)
    def test_path_b_absent_from_openapi(self, openapi, action, _body):
        path = f"/api/workflows/ap_invoice/{{doc_id}}/{action}"
        assert path not in openapi["paths"], (
            f"Retired Path B route unexpectedly registered: {path}"
        )

    @pytest.mark.parametrize("action,body", AP_MUTATION_ACTIONS)
    def test_path_b_returns_404(self, action, body):
        r = requests.post(
            f"{BASE_URL}/api/workflows/ap_invoice/nonexistent-id/{action}",
            json=body,
            timeout=10,
        )
        assert r.status_code == 404, (
            f"Retired Path B {action} must return 404, got "
            f"{r.status_code}: {r.text}"
        )
        assert r.headers.get("X-Deprecated") is None
        assert r.headers.get("X-Deprecated-Use") is None
        assert r.headers.get("X-Deprecated-Sunset") is None
