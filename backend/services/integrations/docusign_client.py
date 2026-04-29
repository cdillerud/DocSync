"""DocuSign eSignature client — Phase 1 scaffold.

Read-only, env-driven, defensive. NO live DocuSign calls are made from
Phase 1 code; `get_access_token()` raises unless `DOCUSIGN_LIVE_CALLS_ENABLED`
is explicitly set to "true". This lets us:

  * Construct and unit-test the JWT assertion claim shape end-to-end.
  * Compute the admin OAuth consent URL without external dependencies.
  * Validate Connect webhook HMAC signatures (used by Phase 2 receiver).
  * Surface a clear `is_configured()` boolean for health checks / dashboards.

Required env vars (all optional in Phase 1; absence is logged not raised):

    DOCUSIGN_INTEGRATION_KEY       Application client ID (UUID)
    DOCUSIGN_USER_ID               GUID of the user to impersonate
    DOCUSIGN_ACCOUNT_ID            DocuSign account UUID
    DOCUSIGN_BASE_URI              e.g. https://demo.docusign.net
    DOCUSIGN_PRIVATE_KEY_PATH      Filesystem path to RSA private key (PEM)
    DOCUSIGN_OAUTH_HOST            account-d.docusign.com (sandbox) /
                                   account.docusign.com (production)
    DOCUSIGN_HMAC_SECRET           Connect HMAC shared secret (key index 1)
    DOCUSIGN_HMAC_SECRET_2         Optional second secret for rotation
    DOCUSIGN_LIVE_CALLS_ENABLED    "true" to permit network access
                                   (Phase 1 default: "false")

The DocuSign SDK (`docusign-esign`) is intentionally NOT imported here.
Phase 2 will install and import it where live envelope fetching lands.
"""

from __future__ import annotations

import hashlib
import hmac
import logging
import os
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Dict, List, Optional, Tuple
from urllib.parse import quote_plus

import jwt  # PyJWT (already in requirements.txt)

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Default JWT scopes for server-to-server eSignature access.
DOCUSIGN_DEFAULT_SCOPES: Tuple[str, ...] = ("signature", "impersonation")

# DocuSign OAuth host defaults (sandbox vs production). The `aud` claim must
# match the OAuth host the assertion is being POSTed to.
_DEFAULT_SANDBOX_OAUTH_HOST = "account-d.docusign.com"
_DEFAULT_PRODUCTION_OAUTH_HOST = "account.docusign.com"


def _bool_env(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class DocuSignSettings:
    """Snapshot of DocuSign configuration read from process env at instantiation."""

    integration_key: Optional[str] = None
    user_id: Optional[str] = None
    account_id: Optional[str] = None
    base_uri: Optional[str] = None
    private_key_path: Optional[str] = None
    oauth_host: str = _DEFAULT_SANDBOX_OAUTH_HOST
    hmac_secrets: Tuple[str, ...] = field(default_factory=tuple)
    live_calls_enabled: bool = False
    scopes: Tuple[str, ...] = DOCUSIGN_DEFAULT_SCOPES

    @classmethod
    def from_env(cls) -> "DocuSignSettings":
        secrets: List[str] = []
        for key in ("DOCUSIGN_HMAC_SECRET", "DOCUSIGN_HMAC_SECRET_2"):
            val = os.environ.get(key)
            if val:
                secrets.append(val)

        oauth_host = os.environ.get(
            "DOCUSIGN_OAUTH_HOST",
            _DEFAULT_SANDBOX_OAUTH_HOST,
        ).strip()

        return cls(
            integration_key=os.environ.get("DOCUSIGN_INTEGRATION_KEY") or None,
            user_id=os.environ.get("DOCUSIGN_USER_ID") or None,
            account_id=os.environ.get("DOCUSIGN_ACCOUNT_ID") or None,
            base_uri=os.environ.get("DOCUSIGN_BASE_URI") or None,
            private_key_path=os.environ.get("DOCUSIGN_PRIVATE_KEY_PATH") or None,
            oauth_host=oauth_host or _DEFAULT_SANDBOX_OAUTH_HOST,
            hmac_secrets=tuple(secrets),
            live_calls_enabled=_bool_env("DOCUSIGN_LIVE_CALLS_ENABLED", False),
        )


# ---------------------------------------------------------------------------
# Connect webhook HMAC validator
# ---------------------------------------------------------------------------

def validate_connect_hmac(
    raw_body: bytes,
    signature_header: Optional[str],
    secrets: Tuple[str, ...],
) -> bool:
    """Validate a DocuSign Connect HMAC-SHA256 signature.

    DocuSign computes ``hex(HMAC_SHA256(raw_body, secret))`` and sends it in
    the ``X-DocuSign-Signature-{n}`` header (n is the configured key index).
    We accept any of the configured secrets to support rotation.

    Constant-time comparison is used to prevent timing oracles. Returns False
    on any missing input rather than raising — caller decides whether to 400.

    Args:
        raw_body: The raw, unparsed request body bytes.
        signature_header: Header value (hex string).
        secrets: Tuple of configured HMAC secrets (rotation supported).

    Returns:
        True iff at least one configured secret produces an exact match.
    """
    if not signature_header or not secrets or raw_body is None:
        return False

    sig = signature_header.strip()
    if not sig:
        return False

    for secret in secrets:
        if not secret:
            continue
        expected = hmac.new(
            secret.encode("utf-8"),
            raw_body,
            hashlib.sha256,
        ).hexdigest()
        if hmac.compare_digest(expected, sig):
            return True
    return False


# ---------------------------------------------------------------------------
# DocuSign client (Phase 1 scaffold)
# ---------------------------------------------------------------------------

class DocuSignNotConfigured(RuntimeError):
    """Raised when a configured-required path is taken without env vars."""


class DocuSignLiveCallsDisabled(RuntimeError):
    """Raised when a network-touching path is taken in Phase 1."""


class DocuSignClient:
    """Defensive, env-driven DocuSign scaffold.

    Phase 1 surface area is intentionally limited:
      * ``is_configured()`` — boolean, no I/O
      * ``build_jwt_assertion()`` — pure CPU, used by tests and Phase 2 OAuth
      * ``oauth_consent_url()`` — pure string utility for admin consent
      * ``validate_webhook_signature()`` — wraps the module-level HMAC fn
      * ``get_access_token()`` — raises in Phase 1 unless live calls enabled
    """

    def __init__(self, settings: Optional[DocuSignSettings] = None) -> None:
        self.settings: DocuSignSettings = settings or DocuSignSettings.from_env()
        self._cached_token: Optional[str] = None
        self._cached_token_expires_at: Optional[datetime] = None

    # -- introspection ------------------------------------------------------

    def is_configured(self) -> bool:
        """Return True iff all credentials needed for JWT exchange are present.

        HMAC secrets are intentionally NOT required for `is_configured` —
        webhook validation has its own readiness signal via `is_webhook_ready`.
        """
        s = self.settings
        if not (s.integration_key and s.user_id and s.account_id):
            return False
        if not s.private_key_path:
            return False
        try:
            return Path(s.private_key_path).is_file()
        except OSError:
            return False

    def is_webhook_ready(self) -> bool:
        """True iff at least one HMAC secret is configured."""
        return any(bool(s) for s in self.settings.hmac_secrets)

    def status(self) -> Dict[str, Any]:
        """Lightweight, secret-free status object suitable for /health probes."""
        s = self.settings
        return {
            "configured": self.is_configured(),
            "webhook_ready": self.is_webhook_ready(),
            "live_calls_enabled": s.live_calls_enabled,
            "oauth_host": s.oauth_host,
            "base_uri": s.base_uri,
            "has_integration_key": bool(s.integration_key),
            "has_user_id": bool(s.user_id),
            "has_account_id": bool(s.account_id),
            "has_private_key_file": bool(
                s.private_key_path and Path(s.private_key_path).is_file()
            ) if s.private_key_path else False,
            "hmac_secret_count": sum(1 for x in s.hmac_secrets if x),
        }

    # -- JWT assertion ------------------------------------------------------

    def _read_private_key(self) -> str:
        s = self.settings
        if not s.private_key_path:
            raise DocuSignNotConfigured("DOCUSIGN_PRIVATE_KEY_PATH not set")
        path = Path(s.private_key_path)
        if not path.is_file():
            raise DocuSignNotConfigured(
                f"DocuSign RSA private key not found at {path}"
            )
        return path.read_text(encoding="utf-8")

    def build_jwt_assertion(
        self,
        *,
        ttl_seconds: int = 3600,
        now: Optional[datetime] = None,
    ) -> str:
        """Construct a signed JWT assertion for the OAuth token exchange.

        Pure function. Does NOT contact DocuSign. Used by Phase 2's OAuth
        client and by Phase 1 tests to verify claim shape.

        Args:
            ttl_seconds: Validity of the assertion (DocuSign max is 1 hour).
            now: Override clock (test hook).

        Returns:
            Signed JWT compact string.

        Raises:
            DocuSignNotConfigured: if required credentials/key are missing.
        """
        s = self.settings
        if not (s.integration_key and s.user_id):
            raise DocuSignNotConfigured(
                "DOCUSIGN_INTEGRATION_KEY and DOCUSIGN_USER_ID required"
            )
        ttl = max(60, min(int(ttl_seconds), 3600))
        anchor = (now or datetime.now(timezone.utc)).replace(microsecond=0)
        claims = {
            "iss": s.integration_key,
            "sub": s.user_id,
            "aud": s.oauth_host,
            "iat": int(anchor.timestamp()),
            "exp": int((anchor + timedelta(seconds=ttl)).timestamp()),
            "scope": " ".join(s.scopes),
        }
        private_key = self._read_private_key()
        return jwt.encode(claims, private_key, algorithm="RS256")

    # -- OAuth consent URL --------------------------------------------------

    def oauth_consent_url(self, redirect_uri: str) -> str:
        """Return the one-time admin consent URL for JWT impersonation grant.

        The admin (or each user, if domain consent isn't configured) opens
        this URL once to grant `signature` and `impersonation` scopes.

        Args:
            redirect_uri: A URL that DocuSign should redirect to after consent.
                          Will be URL-encoded automatically.

        Raises:
            DocuSignNotConfigured: if the integration key isn't set.
        """
        s = self.settings
        if not s.integration_key:
            raise DocuSignNotConfigured("DOCUSIGN_INTEGRATION_KEY not set")
        if not redirect_uri:
            raise ValueError("redirect_uri is required")
        scope = quote_plus(" ".join(s.scopes))
        client = quote_plus(s.integration_key)
        redirect = quote_plus(redirect_uri)
        return (
            f"https://{s.oauth_host}/oauth/auth"
            f"?response_type=code&scope={scope}"
            f"&client_id={client}&redirect_uri={redirect}"
        )

    # -- Webhook HMAC --------------------------------------------------------

    def validate_webhook_signature(
        self,
        raw_body: bytes,
        signature_header: Optional[str],
    ) -> bool:
        """Thin wrapper around the module-level HMAC validator."""
        return validate_connect_hmac(
            raw_body=raw_body,
            signature_header=signature_header,
            secrets=self.settings.hmac_secrets,
        )

    # -- Live access (Phase 1 guard) ----------------------------------------

    def get_access_token(self) -> str:
        """Obtain an OAuth access token. **Disabled in Phase 1.**

        Phase 2 will replace the body with the JWT-grant token exchange
        described in the integration playbook. Phase 1 raises immediately
        unless `DOCUSIGN_LIVE_CALLS_ENABLED=true` is explicitly set, which
        is reserved for future operator-driven smoke tests.
        """
        if not self.settings.live_calls_enabled:
            raise DocuSignLiveCallsDisabled(
                "DocuSign live calls are disabled in Phase 1. "
                "Set DOCUSIGN_LIVE_CALLS_ENABLED=true once Phase 2 lands."
            )
        if not self.is_configured():
            raise DocuSignNotConfigured(
                "DocuSign client is missing required environment variables"
            )
        # Phase 2 implementation goes here. We intentionally do NOT make a
        # network call from Phase 1, even when the flag is on, to keep the
        # surface area tiny and reviewable.
        raise DocuSignLiveCallsDisabled(
            "Token exchange not implemented until Phase 2."
        )


# ---------------------------------------------------------------------------
# Module-level singleton accessor (lazy)
# ---------------------------------------------------------------------------

_singleton: Optional[DocuSignClient] = None


def get_docusign_client() -> DocuSignClient:
    """Return a process-wide DocuSign client constructed from current env."""
    global _singleton
    if _singleton is None:
        _singleton = DocuSignClient()
        logger.info("DocuSign client initialized: %s", _singleton.status())
    return _singleton


def reset_docusign_client_for_tests() -> None:
    """Drop the singleton — used by unit tests that mutate env vars."""
    global _singleton
    _singleton = None
