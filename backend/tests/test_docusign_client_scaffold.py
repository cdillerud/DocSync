"""Phase 1 — DocuSign client scaffold tests (no live API calls).

Covers:
  * env-driven settings parsing
  * is_configured() / is_webhook_ready() / status() reflecting env state
  * JWT assertion claim shape (iss, sub, aud, iat, exp, scope)
  * OAuth consent URL construction
  * HMAC validation behavior:
      - happy path with a single secret
      - tampered body / signature mismatch -> False
      - rotation: validates against secondary secret
      - missing secret / signature / body -> False (no exception)
  * Live-call guard: get_access_token() raises in Phase 1

Tests use a freshly-generated RSA keypair written to a temp file so they
do not depend on any production DocuSign credentials.

Run:
    cd /app/backend && python -m pytest tests/test_docusign_client_scaffold.py -q
"""

from __future__ import annotations

import hashlib
import hmac
from datetime import datetime, timezone
from pathlib import Path

import jwt
import pytest
from cryptography.hazmat.primitives import serialization
from cryptography.hazmat.primitives.asymmetric import rsa

from services.integrations.docusign_client import (
    DocuSignClient,
    DocuSignLiveCallsDisabled,
    DocuSignNotConfigured,
    DocuSignSettings,
    reset_docusign_client_for_tests,
    validate_connect_hmac,
)


# ---------------------------------------------------------------------------
# Fixtures
# ---------------------------------------------------------------------------

@pytest.fixture()
def rsa_keypair(tmp_path: Path):
    """Generate an ephemeral 2048-bit RSA keypair and write the private PEM."""
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    priv_pem = key.private_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PrivateFormat.PKCS8,
        encryption_algorithm=serialization.NoEncryption(),
    )
    pub_pem = key.public_key().public_bytes(
        encoding=serialization.Encoding.PEM,
        format=serialization.PublicFormat.SubjectPublicKeyInfo,
    )
    priv_path = tmp_path / "ds_test_priv.pem"
    priv_path.write_bytes(priv_pem)
    return {"priv_path": str(priv_path), "priv_pem": priv_pem, "pub_pem": pub_pem}


@pytest.fixture()
def configured_settings(rsa_keypair):
    return DocuSignSettings(
        integration_key="00000000-0000-0000-0000-000000000001",
        user_id="00000000-0000-0000-0000-000000000002",
        account_id="00000000-0000-0000-0000-000000000003",
        base_uri="https://demo.docusign.net",
        private_key_path=rsa_keypair["priv_path"],
        oauth_host="account-d.docusign.com",
        hmac_secrets=("primary-secret", "secondary-secret"),
        live_calls_enabled=False,
    )


@pytest.fixture(autouse=True)
def _reset_singleton():
    reset_docusign_client_for_tests()
    yield
    reset_docusign_client_for_tests()


# ---------------------------------------------------------------------------
# Settings + introspection
# ---------------------------------------------------------------------------

class TestSettings:
    def test_from_env_defaults_when_empty(self, monkeypatch):
        for k in (
            "DOCUSIGN_INTEGRATION_KEY", "DOCUSIGN_USER_ID", "DOCUSIGN_ACCOUNT_ID",
            "DOCUSIGN_BASE_URI", "DOCUSIGN_PRIVATE_KEY_PATH",
            "DOCUSIGN_OAUTH_HOST", "DOCUSIGN_HMAC_SECRET",
            "DOCUSIGN_HMAC_SECRET_2", "DOCUSIGN_LIVE_CALLS_ENABLED",
        ):
            monkeypatch.delenv(k, raising=False)
        s = DocuSignSettings.from_env()
        assert s.integration_key is None
        assert s.user_id is None
        assert s.account_id is None
        assert s.private_key_path is None
        assert s.hmac_secrets == ()
        assert s.live_calls_enabled is False
        assert s.oauth_host == "account-d.docusign.com"

    def test_from_env_parses_all(self, monkeypatch, rsa_keypair):
        monkeypatch.setenv("DOCUSIGN_INTEGRATION_KEY", "ik")
        monkeypatch.setenv("DOCUSIGN_USER_ID", "uid")
        monkeypatch.setenv("DOCUSIGN_ACCOUNT_ID", "acc")
        monkeypatch.setenv("DOCUSIGN_BASE_URI", "https://demo.docusign.net")
        monkeypatch.setenv("DOCUSIGN_PRIVATE_KEY_PATH", rsa_keypair["priv_path"])
        monkeypatch.setenv("DOCUSIGN_OAUTH_HOST", "account.docusign.com")
        monkeypatch.setenv("DOCUSIGN_HMAC_SECRET", "k1")
        monkeypatch.setenv("DOCUSIGN_HMAC_SECRET_2", "k2")
        monkeypatch.setenv("DOCUSIGN_LIVE_CALLS_ENABLED", "TRUE")
        s = DocuSignSettings.from_env()
        assert s.integration_key == "ik"
        assert s.user_id == "uid"
        assert s.account_id == "acc"
        assert s.oauth_host == "account.docusign.com"
        assert s.hmac_secrets == ("k1", "k2")
        assert s.live_calls_enabled is True


class TestClientIntrospection:
    def test_unconfigured(self):
        c = DocuSignClient(DocuSignSettings())
        assert c.is_configured() is False
        assert c.is_webhook_ready() is False
        st = c.status()
        assert st["configured"] is False
        assert st["webhook_ready"] is False
        assert st["hmac_secret_count"] == 0
        assert st["live_calls_enabled"] is False

    def test_configured(self, configured_settings):
        c = DocuSignClient(configured_settings)
        assert c.is_configured() is True
        assert c.is_webhook_ready() is True
        st = c.status()
        assert st["configured"] is True
        assert st["webhook_ready"] is True
        assert st["hmac_secret_count"] == 2
        assert st["has_private_key_file"] is True

    def test_missing_key_file_marks_unconfigured(self, configured_settings, tmp_path):
        bad = DocuSignSettings(
            integration_key=configured_settings.integration_key,
            user_id=configured_settings.user_id,
            account_id=configured_settings.account_id,
            base_uri=configured_settings.base_uri,
            private_key_path=str(tmp_path / "does_not_exist.pem"),
            oauth_host=configured_settings.oauth_host,
            hmac_secrets=configured_settings.hmac_secrets,
        )
        c = DocuSignClient(bad)
        assert c.is_configured() is False


# ---------------------------------------------------------------------------
# JWT assertion
# ---------------------------------------------------------------------------

class TestJWTAssertion:
    def test_claim_shape_and_signature(self, configured_settings, rsa_keypair):
        c = DocuSignClient(configured_settings)
        anchor = datetime(2026, 2, 1, 12, 0, 0, tzinfo=timezone.utc)
        token = c.build_jwt_assertion(ttl_seconds=600, now=anchor)

        # Verify with the public key. We disable `exp` enforcement so the
        # test stays deterministic regardless of when it runs relative to
        # the fixed `anchor` above.
        decoded = jwt.decode(
            token,
            rsa_keypair["pub_pem"],
            algorithms=["RS256"],
            audience=configured_settings.oauth_host,
            options={"verify_exp": False},
        )
        assert decoded["iss"] == configured_settings.integration_key
        assert decoded["sub"] == configured_settings.user_id
        assert decoded["aud"] == configured_settings.oauth_host
        assert decoded["scope"] == "signature impersonation"
        assert decoded["iat"] == int(anchor.timestamp())
        assert decoded["exp"] == int(anchor.timestamp()) + 600

    def test_ttl_clamped_to_max_one_hour(self, configured_settings):
        c = DocuSignClient(configured_settings)
        anchor = datetime(2026, 2, 1, tzinfo=timezone.utc)
        token = c.build_jwt_assertion(ttl_seconds=999_999, now=anchor)
        decoded = jwt.decode(
            token,
            options={"verify_signature": False, "verify_aud": False},
        )
        assert decoded["exp"] - decoded["iat"] == 3600

    def test_raises_when_unconfigured(self):
        c = DocuSignClient(DocuSignSettings())
        with pytest.raises(DocuSignNotConfigured):
            c.build_jwt_assertion()

    def test_raises_when_key_file_missing(self, configured_settings, tmp_path):
        bad = DocuSignSettings(
            integration_key=configured_settings.integration_key,
            user_id=configured_settings.user_id,
            account_id=configured_settings.account_id,
            private_key_path=str(tmp_path / "nope.pem"),
        )
        c = DocuSignClient(bad)
        with pytest.raises(DocuSignNotConfigured):
            c.build_jwt_assertion()


# ---------------------------------------------------------------------------
# OAuth consent URL
# ---------------------------------------------------------------------------

class TestConsentURL:
    def test_basic_shape(self, configured_settings):
        c = DocuSignClient(configured_settings)
        url = c.oauth_consent_url("https://hub.example.com/docusign/consent-done")
        assert url.startswith("https://account-d.docusign.com/oauth/auth?")
        assert "response_type=code" in url
        assert "scope=signature+impersonation" in url
        assert "client_id=" in url
        # Redirect URI must be URL-encoded
        assert "redirect_uri=https%3A%2F%2Fhub.example.com%2Fdocusign%2Fconsent-done" in url

    def test_requires_redirect_uri(self, configured_settings):
        c = DocuSignClient(configured_settings)
        with pytest.raises(ValueError):
            c.oauth_consent_url("")

    def test_unconfigured_raises(self):
        c = DocuSignClient(DocuSignSettings())
        with pytest.raises(DocuSignNotConfigured):
            c.oauth_consent_url("https://x")


# ---------------------------------------------------------------------------
# HMAC validator
# ---------------------------------------------------------------------------

def _sign(body: bytes, secret: str) -> str:
    return hmac.new(secret.encode("utf-8"), body, hashlib.sha256).hexdigest()


class TestHMACValidator:
    def test_happy_path_single_secret(self):
        body = b'{"event":"envelope-completed"}'
        sig = _sign(body, "alpha")
        assert validate_connect_hmac(body, sig, ("alpha",)) is True

    def test_tampered_body_rejected(self):
        body = b'{"event":"envelope-completed"}'
        sig = _sign(body, "alpha")
        tampered = b'{"event":"envelope-voided"}'
        assert validate_connect_hmac(tampered, sig, ("alpha",)) is False

    def test_wrong_signature_rejected(self):
        body = b'{"x":1}'
        assert validate_connect_hmac(body, "deadbeef", ("alpha",)) is False

    def test_rotation_secondary_key_accepted(self):
        body = b'{"x":1}'
        sig = _sign(body, "secondary")
        assert validate_connect_hmac(body, sig, ("primary", "secondary")) is True

    def test_missing_secret_returns_false(self):
        assert validate_connect_hmac(b"x", _sign(b"x", "k"), ()) is False

    def test_missing_signature_returns_false(self):
        assert validate_connect_hmac(b"x", None, ("k",)) is False
        assert validate_connect_hmac(b"x", "   ", ("k",)) is False

    def test_empty_secret_in_tuple_skipped(self):
        body = b"x"
        sig = _sign(body, "real")
        assert validate_connect_hmac(body, sig, ("", "real")) is True

    def test_client_method_wraps_module_fn(self, configured_settings):
        c = DocuSignClient(configured_settings)
        body = b'{"hello":"world"}'
        sig = _sign(body, "primary-secret")
        assert c.validate_webhook_signature(body, sig) is True
        assert c.validate_webhook_signature(body, "bad") is False


# ---------------------------------------------------------------------------
# Live call guard (Phase 1 read-only)
# ---------------------------------------------------------------------------

class TestLiveCallGuard:
    def test_disabled_by_default(self, configured_settings):
        c = DocuSignClient(configured_settings)
        with pytest.raises(DocuSignLiveCallsDisabled):
            c.get_access_token()

    def test_still_disabled_when_flag_on_in_phase1(self, configured_settings):
        # Even when DOCUSIGN_LIVE_CALLS_ENABLED is true, Phase 1 must NOT
        # make network calls. This guard prevents accidental live activation.
        flagged = DocuSignSettings(
            integration_key=configured_settings.integration_key,
            user_id=configured_settings.user_id,
            account_id=configured_settings.account_id,
            base_uri=configured_settings.base_uri,
            private_key_path=configured_settings.private_key_path,
            oauth_host=configured_settings.oauth_host,
            hmac_secrets=configured_settings.hmac_secrets,
            live_calls_enabled=True,
        )
        c = DocuSignClient(flagged)
        with pytest.raises(DocuSignLiveCallsDisabled):
            c.get_access_token()
