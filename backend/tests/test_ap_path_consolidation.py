"""
AP Path Consolidation tests — verifies AP_PATH_CONSOLIDATION.md Phase 2.

Phase 2 of the AP Path consolidation (2026-04-21) established:
  1. /api/ap-review/documents/{doc_id}/{action} is the canonical Path A surface
     for the six AP mutation endpoints (set-vendor, update-fields,
     override-bc-validation, start-approval, approve, reject).
  2. The six legacy /api/workflows/ap_invoice/{doc_id}/{action} endpoints
     remain live for one release window but are flagged deprecated=True in
     the OpenAPI schema and emit X-Deprecated response headers so callers
     know to migrate.

These tests assert both:
  * Path A exists, enforces JWT auth, and delegates correctly.
  * Path B exists, is marked deprecated, and every response (including
    HTTPException paths) carries the X-Deprecated headers.
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


class TestDeprecatedPathBFlagged:
    """Path B legacy AP routes must stay live but be flagged deprecated."""

    @pytest.mark.parametrize("action,_body", AP_MUTATION_ACTIONS)
    def test_path_b_still_present(self, openapi, action, _body):
        path = f"/api/workflows/ap_invoice/{{doc_id}}/{action}"
        assert path in openapi["paths"], (
            f"Path B route {path} must stay live for one release"
        )

    @pytest.mark.parametrize("action,_body", AP_MUTATION_ACTIONS)
    def test_path_b_marked_deprecated(self, openapi, action, _body):
        path = f"/api/workflows/ap_invoice/{{doc_id}}/{action}"
        meta = openapi["paths"][path]["post"]
        assert meta.get("deprecated") is True, (
            f"{path} must have deprecated=True in OpenAPI"
        )


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


class TestPathBDeprecationHeaders:
    @pytest.mark.parametrize("action,body", AP_MUTATION_ACTIONS)
    def test_error_response_carries_deprecation_headers(self, action, body):
        r = requests.post(
            f"{BASE_URL}/api/workflows/ap_invoice/nonexistent-id/{action}",
            json=body,
            timeout=10,
        )
        # Handler raises HTTPException for missing doc — wrapper must still
        # attach deprecation headers.
        assert r.headers.get("X-Deprecated") == "true", (
            f"{action}: X-Deprecated header missing on error response"
        )
        assert r.headers.get("X-Deprecated-Use") == (
            f"/api/ap-review/documents/{{doc_id}}/{action}"
        ), f"{action}: X-Deprecated-Use must point at Path A"
        assert r.headers.get("X-Deprecated-Sunset") == "next-release"
