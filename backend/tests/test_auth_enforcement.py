"""
Tests for the auth enforcement fix (Findings #1 + #10 of the 2026-04 review).

Covers:
  * ``services.auth_deps`` — hash/verify/encode/decode pure functions
  * startup validator — rejects missing or known-insecure secrets
  * end-to-end login + /me + /logout via the live FastAPI app
  * protected endpoints reject unauthenticated requests
"""

from __future__ import annotations

import os
import uuid
from unittest.mock import patch

import jwt as pyjwt
import pytest


# ---------------------------------------------------------------------------
# Pure helpers
# ---------------------------------------------------------------------------

class TestPasswordHashing:
    def test_hash_is_bcrypt_and_verifies(self):
        from services.auth_deps import hash_password, verify_password
        h = hash_password("s3cret!")
        assert h.startswith("$2b$") or h.startswith("$2a$") or h.startswith("$2y$")
        assert verify_password("s3cret!", h) is True
        assert verify_password("wrong", h) is False

    def test_verify_returns_false_on_garbage_hash(self):
        from services.auth_deps import verify_password
        assert verify_password("anything", "") is False
        assert verify_password("anything", "not-a-bcrypt-hash") is False


class TestTokenCreateDecode:
    @pytest.fixture(autouse=True)
    def _set_secret(self, monkeypatch):
        monkeypatch.setenv("JWT_SECRET", "a" * 96)

    def test_roundtrip(self):
        from services.auth_deps import create_access_token, decode_access_token
        token = create_access_token("uid-1", "a@b.com", "admin")
        payload = decode_access_token(token)
        assert payload["sub"] == "uid-1"
        assert payload["email"] == "a@b.com"
        assert payload["role"] == "admin"
        assert payload["type"] == "access"

    def test_expired_token_rejected(self, monkeypatch):
        """Forge a token with past exp and expect 401."""
        from services.auth_deps import decode_access_token
        from fastapi import HTTPException
        from datetime import datetime, timedelta, timezone
        bad = pyjwt.encode(
            {
                "sub": "x", "email": "x", "role": "user", "type": "access",
                "exp": datetime.now(timezone.utc) - timedelta(hours=1),
            },
            os.environ["JWT_SECRET"], algorithm="HS256",
        )
        with pytest.raises(HTTPException) as exc:
            decode_access_token(bad)
        assert exc.value.status_code == 401
        assert "expired" in exc.value.detail.lower()

    def test_tampered_signature_rejected(self):
        from services.auth_deps import create_access_token, decode_access_token
        from fastapi import HTTPException
        token = create_access_token("uid", "a@b.com")
        tampered = token[:-5] + "XXXXX"
        with pytest.raises(HTTPException) as exc:
            decode_access_token(tampered)
        assert exc.value.status_code == 401

    def test_missing_secret_raises_runtime(self, monkeypatch):
        from services.auth_deps import create_access_token
        monkeypatch.delenv("JWT_SECRET", raising=False)
        with pytest.raises(RuntimeError):
            create_access_token("u", "e")

    def test_insecure_default_secret_rejected(self, monkeypatch):
        from services.auth_deps import create_access_token
        monkeypatch.setenv("JWT_SECRET", "gpi-hub-secret-key")
        with pytest.raises(RuntimeError):
            create_access_token("u", "e")

    def test_wrong_token_type_rejected(self, monkeypatch):
        """A token with type != 'access' is rejected."""
        from services.auth_deps import decode_access_token
        from fastapi import HTTPException
        from datetime import datetime, timedelta, timezone
        odd = pyjwt.encode(
            {
                "sub": "x", "email": "x", "role": "user", "type": "refresh",
                "exp": datetime.now(timezone.utc) + timedelta(hours=1),
            },
            os.environ["JWT_SECRET"], algorithm="HS256",
        )
        with pytest.raises(HTTPException):
            decode_access_token(odd)


# ---------------------------------------------------------------------------
# Startup validator
# ---------------------------------------------------------------------------

class TestStartupValidator:
    def test_passes_when_all_secrets_present(self, monkeypatch):
        from services.startup_validator import validate_startup_secrets
        monkeypatch.setenv("JWT_SECRET", "x" * 96)
        monkeypatch.setenv("ADMIN_EMAIL", "ops@example.com")
        monkeypatch.setenv("ADMIN_PASSWORD", "StrongPass-2026!")
        monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
        validate_startup_secrets()  # must not raise

    @pytest.mark.parametrize("missing", ["JWT_SECRET", "ADMIN_EMAIL", "ADMIN_PASSWORD", "MONGO_URL"])
    def test_fails_when_required_missing(self, monkeypatch, missing):
        from services.startup_validator import validate_startup_secrets
        monkeypatch.setenv("JWT_SECRET", "x" * 96)
        monkeypatch.setenv("ADMIN_EMAIL", "ops@example.com")
        monkeypatch.setenv("ADMIN_PASSWORD", "StrongPass-2026!")
        monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
        monkeypatch.delenv(missing, raising=False)
        with pytest.raises(RuntimeError) as exc:
            validate_startup_secrets()
        assert missing in str(exc.value)

    @pytest.mark.parametrize("insecure", [
        ("JWT_SECRET", "gpi-hub-secret-key"),
        ("JWT_SECRET", "changeme"),
        ("ADMIN_PASSWORD", "admin"),
        ("ADMIN_PASSWORD", "admin123"),
        ("ADMIN_EMAIL", "admin@example.com"),
    ])
    def test_rejects_insecure_defaults(self, monkeypatch, insecure):
        from services.startup_validator import validate_startup_secrets
        key, bad_value = insecure
        monkeypatch.setenv("JWT_SECRET", "x" * 96)
        monkeypatch.setenv("ADMIN_EMAIL", "ops@example.com")
        monkeypatch.setenv("ADMIN_PASSWORD", "StrongPass-2026!")
        monkeypatch.setenv("MONGO_URL", "mongodb://localhost:27017")
        monkeypatch.setenv(key, bad_value)
        with pytest.raises(RuntimeError):
            validate_startup_secrets()


# ---------------------------------------------------------------------------
# End-to-end auth flow via live backend (requires running uvicorn @ 8001)
# ---------------------------------------------------------------------------

import httpx

BACKEND = "http://localhost:8001"


def _backend_up() -> bool:
    try:
        r = httpx.get(f"{BACKEND}/api/health", timeout=1.0)
        return r.status_code == 200
    except Exception:
        return False


@pytest.mark.skipif(not _backend_up(), reason="live backend not reachable")
class TestLiveAuthFlow:

    ADMIN_EMAIL = "hub-admin@gamerpackaging.com"
    ADMIN_PASSWORD = "ChangeMeOnFirstDeploy-K8p2q"

    def test_login_then_me_then_logout(self):
        with httpx.Client(base_url=BACKEND) as c:
            r = c.post(
                "/api/auth/login",
                json={"email": self.ADMIN_EMAIL, "password": self.ADMIN_PASSWORD},
            )
            assert r.status_code == 200
            token = r.json()["token"]
            assert token.count(".") == 2  # three JWT segments

            me = c.get(
                "/api/auth/me", headers={"Authorization": f"Bearer {token}"}
            )
            assert me.status_code == 200
            assert me.json()["email"] == self.ADMIN_EMAIL
            assert me.json()["role"] == "admin"

            lo = c.post(
                "/api/auth/logout", headers={"Authorization": f"Bearer {token}"}
            )
            assert lo.status_code == 200

    def test_me_without_token_is_401(self):
        with httpx.Client(base_url=BACKEND) as c:
            r = c.get("/api/auth/me")
            assert r.status_code == 401

    def test_me_with_garbage_token_is_401(self):
        with httpx.Client(base_url=BACKEND) as c:
            r = c.get("/api/auth/me", headers={"Authorization": "Bearer garbage.token.here"})
            assert r.status_code == 401

    def test_login_wrong_password_is_401(self):
        with httpx.Client(base_url=BACKEND) as c:
            r = c.post(
                "/api/auth/login",
                json={"email": self.ADMIN_EMAIL, "password": "wrong"},
            )
            assert r.status_code == 401
            # Must not leak which check failed
            assert "invalid" in r.json()["detail"].lower()

    def test_login_unknown_email_is_401(self):
        with httpx.Client(base_url=BACKEND) as c:
            r = c.post(
                "/api/auth/login",
                json={"email": "nobody@example.com", "password": "x"},
            )
            assert r.status_code == 401

    def test_backfill_endpoint_anonymous_blocked(self):
        """/api/admin/backfill-ap-mailbox must reject anonymous callers —
        this was the reviewer's specific call-out as the single most
        dangerous unauthenticated route."""
        with httpx.Client(base_url=BACKEND) as c:
            r = c.post("/api/admin/backfill-ap-mailbox?dry_run=true")
            assert r.status_code == 401, (
                f"Expected 401, got {r.status_code}: {r.text[:200]}"
            )

    def test_post_to_bc_endpoint_anonymous_blocked(self):
        """The financial-integrity-critical BC write endpoint must be
        auth'd. If anon can hit this, duplicate invoices are trivial."""
        with httpx.Client(base_url=BACKEND) as c:
            r = c.post(
                "/api/ap-review/documents/nonexistent-doc-id/post-to-bc"
            )
            assert r.status_code == 401, (
                f"Expected 401, got {r.status_code}: {r.text[:200]}"
            )

    def test_backfill_with_admin_token_allowed(self):
        """Confirm the auth dep isn't over-broad: valid admin token
        passes through (we check the handler reaches its own 503 for
        uninitialized email service, not 401/403)."""
        with httpx.Client(base_url=BACKEND) as c:
            tok_resp = c.post(
                "/api/auth/login",
                json={"email": self.ADMIN_EMAIL, "password": self.ADMIN_PASSWORD},
            )
            token = tok_resp.json()["token"]
            r = c.post(
                "/api/admin/backfill-ap-mailbox?dry_run=true",
                headers={"Authorization": f"Bearer {token}"},
            )
            # Either 200 (if email service is configured) or 503 (service
            # not initialized in preview) — but NOT 401/403.
            assert r.status_code not in (401, 403), (
                f"Admin token was rejected with {r.status_code}: {r.text[:200]}"
            )
