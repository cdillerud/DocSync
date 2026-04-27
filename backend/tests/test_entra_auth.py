"""
P1.H — Entra ID token validation test suite (offline; no network calls).

Six classes:
  A. JWKS cache behavior (TTL, kid-miss refresh, stale-on-fail)
  B. Happy-path validation (claims extraction, app-only detection)
  C. Negative validation (aud/iss/tid/exp/nbf/sig/kid/alg)
  D. Role guard (require_role)
  E. App-only guard (require_app_only)
  F. Hybrid facade (Entra + legacy bcrypt JWT coexistence)

All tests use a self-signed RSA keypair injected via the
``ENTRA_JWKS_OVERRIDE`` env var; zero traffic to login.microsoftonline.com.
"""
from __future__ import annotations

import asyncio
import json
import time
from typing import Any, Dict
from unittest.mock import patch

import pytest
from fastapi import Depends, FastAPI
from fastapi.testclient import TestClient

from services.entra_auth import (
    Actor,
    JWKSCache,
    get_current_actor,
    get_current_user_hybrid,
    require_app_only,
    require_role,
    reset_jwks_cache,
    validate_entra_token,
)
from tests.fixtures.entra_test_keys import (
    install_jwks_override,
    make_test_keypair,
    mint_token,
)

TENANT = "11111111-2222-3333-4444-555555555555"
CLIENT = "aaaaaaaa-bbbb-cccc-dddd-eeeeeeeeeeee"
AUDIENCE = f"api://{CLIENT}/access_as_users"


@pytest.fixture
def entra_env(monkeypatch):
    monkeypatch.setenv("ENTRA_AUTH_ENABLED", "true")
    monkeypatch.setenv("LEGACY_AUTH_ENABLED", "false")
    monkeypatch.setenv("ENTRA_TENANT_ID", TENANT)
    monkeypatch.setenv("ENTRA_CLIENT_ID", CLIENT)
    monkeypatch.setenv("ENTRA_API_AUDIENCE", AUDIENCE)
    yield


@pytest.fixture
def keypair(monkeypatch, entra_env):
    kp = make_test_keypair(kid="test-key-1")
    install_jwks_override(monkeypatch, kp)
    yield kp


def _user_token(kp, **overrides) -> str:
    defaults = dict(
        keypair=kp,
        tenant_id=TENANT,
        audience=AUDIENCE,
        roles=["viewer"],
    )
    defaults.update(overrides)
    return mint_token(**defaults)


# ---------------------------------------------------------------------------
# A) JWKS cache
# ---------------------------------------------------------------------------


class TestJWKSCache:
    def test_initial_fetch_via_override(self, monkeypatch):
        kp = make_test_keypair()
        monkeypatch.setenv("ENTRA_JWKS_OVERRIDE", json.dumps(kp.as_jwks()))
        cache = JWKSCache(ttl_seconds=60)
        key = cache.get_signing_key(kp.kid)
        assert key is not None

    def test_kid_miss_triggers_refresh(self, monkeypatch):
        kp1 = make_test_keypair(kid="kid-A")
        monkeypatch.setenv("ENTRA_JWKS_OVERRIDE", json.dumps(kp1.as_jwks()))
        cache = JWKSCache(ttl_seconds=3600)
        cache.get_signing_key("kid-A")  # populates

        # Rotate: a new kid is introduced; cache must refresh on miss.
        kp2 = make_test_keypair(kid="kid-B")
        combined = {"keys": [kp1.jwk, kp2.jwk]}
        monkeypatch.setenv("ENTRA_JWKS_OVERRIDE", json.dumps(combined))
        # kid-B is not in cache yet; lookup must trigger refresh and succeed.
        assert cache.get_signing_key("kid-B") is not None

    def test_stale_on_network_fail(self, monkeypatch):
        kp = make_test_keypair()
        monkeypatch.setenv("ENTRA_JWKS_OVERRIDE", json.dumps(kp.as_jwks()))
        cache = JWKSCache(ttl_seconds=0)  # always stale
        cache.get_signing_key(kp.kid)  # populates once

        # Remove the override so the next refresh would fail (no network in tests).
        monkeypatch.delenv("ENTRA_JWKS_OVERRIDE", raising=False)
        # Force the cache fetch path to fail on next refresh.
        with patch("services.entra_auth.requests.get", side_effect=RuntimeError("net")):
            # Lookup should still succeed using the stale cache.
            assert cache.get_signing_key(kp.kid) is not None

    def test_unknown_kid_after_refresh_raises(self, monkeypatch):
        kp = make_test_keypair(kid="kid-only")
        monkeypatch.setenv("ENTRA_JWKS_OVERRIDE", json.dumps(kp.as_jwks()))
        cache = JWKSCache(ttl_seconds=60)
        with pytest.raises(KeyError):
            cache.get_signing_key("does-not-exist")


# ---------------------------------------------------------------------------
# B) Happy-path validation
# ---------------------------------------------------------------------------


class TestHappyPath:
    def test_valid_user_token_returns_actor(self, keypair):
        token = _user_token(keypair, roles=["admin", "approver"])
        actor = validate_entra_token(token)
        assert isinstance(actor, Actor)
        assert actor.tenant_id == TENANT
        assert actor.roles == ["admin", "approver"]
        assert actor.is_app_only is False  # has scp

    def test_oid_claim_used_when_present(self, keypair):
        token = _user_token(keypair, oid="user-oid-123")
        actor = validate_entra_token(token)
        assert actor.oid == "user-oid-123"

    def test_email_and_username_propagated(self, keypair):
        token = _user_token(
            keypair,
            email="alice@example.com",
            preferred_username="alice@example.com",
        )
        actor = validate_entra_token(token)
        assert actor.email == "alice@example.com"
        assert actor.preferred_username == "alice@example.com"

    def test_app_only_token_detected(self, keypair):
        token = _user_token(keypair, scp=None, roles=["service"])
        actor = validate_entra_token(token)
        assert actor.is_app_only is True
        assert "service" in actor.roles


# ---------------------------------------------------------------------------
# C) Negative validation
# ---------------------------------------------------------------------------


class TestNegativeValidation:
    def test_wrong_audience(self, keypair):
        token = mint_token(
            keypair=keypair,
            tenant_id=TENANT,
            audience="api://other-client/scope",
            roles=["viewer"],
        )
        with pytest.raises(Exception) as exc:
            validate_entra_token(token)
        assert exc.value.status_code == 401

    def test_wrong_issuer(self, keypair):
        token = mint_token(
            keypair=keypair,
            tenant_id=TENANT,
            audience=AUDIENCE,
            issuer="https://login.microsoftonline.com/other-tenant/v2.0",
            roles=["viewer"],
        )
        with pytest.raises(Exception) as exc:
            validate_entra_token(token)
        assert exc.value.status_code == 401

    def test_wrong_tid_with_matching_iss(self, keypair):
        # Forge token where iss matches our tenant but tid claim does not.
        token = mint_token(
            keypair=keypair,
            tenant_id=TENANT,
            audience=AUDIENCE,
            extra_claims={"tid": "spoofed-tenant"},
            roles=["viewer"],
        )
        with pytest.raises(Exception) as exc:
            validate_entra_token(token)
        assert exc.value.status_code == 401
        assert "tenant" in exc.value.detail.lower()

    def test_expired_token(self, keypair):
        token = mint_token(
            keypair=keypair,
            tenant_id=TENANT,
            audience=AUDIENCE,
            roles=["viewer"],
            expires_in=-3600,  # expired an hour ago
        )
        with pytest.raises(Exception) as exc:
            validate_entra_token(token)
        assert exc.value.status_code == 401
        assert "expired" in exc.value.detail.lower()

    def test_nbf_in_future(self, keypair):
        token = mint_token(
            keypair=keypair,
            tenant_id=TENANT,
            audience=AUDIENCE,
            roles=["viewer"],
            not_before_offset=600,  # 10 min in future, beyond 30s leeway
        )
        with pytest.raises(Exception) as exc:
            validate_entra_token(token)
        assert exc.value.status_code == 401

    def test_invalid_signature(self, keypair, monkeypatch):
        # Mint with a different keypair than what's in the JWKS.
        impostor = make_test_keypair(kid=keypair.kid)  # same kid, different key
        token = mint_token(
            keypair=impostor,
            tenant_id=TENANT,
            audience=AUDIENCE,
            roles=["viewer"],
        )
        with pytest.raises(Exception) as exc:
            validate_entra_token(token)
        assert exc.value.status_code == 401

    def test_missing_kid(self, keypair):
        token = mint_token(
            keypair=keypair,
            tenant_id=TENANT,
            audience=AUDIENCE,
            roles=["viewer"],
            omit_kid=True,
        )
        with pytest.raises(Exception) as exc:
            validate_entra_token(token)
        assert exc.value.status_code == 401
        assert "kid" in exc.value.detail.lower()

    def test_alg_none_rejected(self, keypair):
        # Cannot actually sign with alg=none via PyJWT; build header manually.
        import base64

        header = base64.urlsafe_b64encode(b'{"alg":"none","typ":"JWT"}').rstrip(b"=")
        body = base64.urlsafe_b64encode(b'{"aud":"x","iss":"x","exp":9999999999}').rstrip(b"=")
        token = (header + b"." + body + b".").decode("ascii")
        with pytest.raises(Exception) as exc:
            validate_entra_token(token)
        assert exc.value.status_code == 401

    def test_empty_token(self, keypair):
        with pytest.raises(Exception) as exc:
            validate_entra_token("")
        assert exc.value.status_code == 401

    def test_clock_leeway_allows_30s_drift(self, keypair):
        # 20s past expiry should still pass thanks to leeway=30.
        token = mint_token(
            keypair=keypair,
            tenant_id=TENANT,
            audience=AUDIENCE,
            roles=["viewer"],
            expires_in=-20,
        )
        actor = validate_entra_token(token)
        assert actor.tenant_id == TENANT


# ---------------------------------------------------------------------------
# D) Role guard
# ---------------------------------------------------------------------------


def _build_role_app() -> FastAPI:
    app = FastAPI()

    @app.get("/me")
    async def me(actor: Actor = Depends(get_current_actor)):
        return {"oid": actor.oid, "roles": actor.roles}

    @app.get("/admin", dependencies=[Depends(require_role("admin"))])
    async def admin_only():
        return {"ok": True}

    @app.get(
        "/approve-or-admin",
        dependencies=[Depends(require_role("approver", "admin"))],
    )
    async def approve_or_admin():
        return {"ok": True}

    @app.get("/svc", dependencies=[Depends(require_app_only())])
    async def service_only():
        return {"ok": True}

    return app


class TestRoleGuard:
    def test_strict_dep_401_without_token(self, keypair):
        client = TestClient(_build_role_app())
        resp = client.get("/me")
        assert resp.status_code == 401

    def test_strict_dep_returns_actor(self, keypair):
        token = _user_token(keypair, roles=["viewer"])
        client = TestClient(_build_role_app())
        resp = client.get("/me", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        assert resp.json()["roles"] == ["viewer"]

    def test_role_required_403_on_miss(self, keypair):
        token = _user_token(keypair, roles=["viewer"])
        client = TestClient(_build_role_app())
        resp = client.get("/admin", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_role_required_passes_on_match(self, keypair):
        token = _user_token(keypair, roles=["admin"])
        client = TestClient(_build_role_app())
        resp = client.get("/admin", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200

    def test_role_required_passes_with_any_of(self, keypair):
        token = _user_token(keypair, roles=["approver"])
        client = TestClient(_build_role_app())
        resp = client.get(
            "/approve-or-admin", headers={"Authorization": f"Bearer {token}"}
        )
        assert resp.status_code == 200

    def test_role_required_factory_rejects_empty(self):
        with pytest.raises(ValueError):
            require_role()


# ---------------------------------------------------------------------------
# E) App-only guard
# ---------------------------------------------------------------------------


class TestAppOnlyGuard:
    def test_app_only_blocks_user_token(self, keypair):
        token = _user_token(keypair, roles=["service"])  # has scp
        client = TestClient(_build_role_app())
        resp = client.get("/svc", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 403

    def test_app_only_admits_service_principal(self, keypair):
        token = _user_token(keypair, scp=None, roles=["service"])
        client = TestClient(_build_role_app())
        resp = client.get("/svc", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200


# ---------------------------------------------------------------------------
# F) Hybrid facade
# ---------------------------------------------------------------------------


def _build_hybrid_app() -> FastAPI:
    app = FastAPI()

    @app.get("/whoami")
    async def whoami(user: Dict[str, Any] = Depends(get_current_user_hybrid)):
        return user

    return app


class TestHybridFacade:
    def test_entra_path_when_flag_on_and_token_valid(self, keypair):
        token = _user_token(keypair, roles=["admin"])
        client = TestClient(_build_hybrid_app())
        resp = client.get("/whoami", headers={"Authorization": f"Bearer {token}"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_source"] == "entra"
        assert body["roles"] == ["admin"]

    def test_legacy_path_when_entra_off_and_legacy_on(self, monkeypatch, keypair):
        # Disable Entra, enable legacy. Stub the legacy dep so we don't need a real DB.
        monkeypatch.setenv("ENTRA_AUTH_ENABLED", "false")
        monkeypatch.setenv("LEGACY_AUTH_ENABLED", "true")

        async def fake_legacy_get_current_user(request):
            return {"id": "legacy-1", "email": "legacy@example.com", "role": "viewer"}

        monkeypatch.setattr(
            "services.auth_deps.get_current_user", fake_legacy_get_current_user
        )

        client = TestClient(_build_hybrid_app())
        resp = client.get("/whoami", headers={"Authorization": "Bearer junk"})
        assert resp.status_code == 200
        body = resp.json()
        assert body["auth_source"] == "legacy"
        assert body["id"] == "legacy-1"

    def test_entra_invalid_falls_back_to_legacy(self, monkeypatch, keypair):
        monkeypatch.setenv("LEGACY_AUTH_ENABLED", "true")

        async def fake_legacy(request):
            return {"id": "legacy-2", "email": "legacy2@example.com", "role": "viewer"}

        monkeypatch.setattr("services.auth_deps.get_current_user", fake_legacy)

        # Garbage token; Entra rejects → legacy fallback fires.
        client = TestClient(_build_hybrid_app())
        resp = client.get("/whoami", headers={"Authorization": "Bearer not-a-jwt"})
        assert resp.status_code == 200
        assert resp.json()["auth_source"] == "legacy"

    def test_both_disabled_returns_401(self, monkeypatch, keypair):
        monkeypatch.setenv("ENTRA_AUTH_ENABLED", "false")
        monkeypatch.setenv("LEGACY_AUTH_ENABLED", "false")
        client = TestClient(_build_hybrid_app())
        resp = client.get("/whoami", headers={"Authorization": "Bearer x"})
        assert resp.status_code == 401
