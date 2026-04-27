"""
GPI Document Hub — Microsoft Entra ID Token Validation (P1.H)

Sole authority for validating Entra-issued access tokens. Co-located with the
existing legacy bcrypt JWT in ``services/auth_deps.py`` during the migration
window; convergence is via the hybrid facade ``get_current_user_hybrid``.

Contract (frozen for P1.C):
- Algorithm: RS256 only (no symmetric, no alg=none).
- Issuer: ``https://login.microsoftonline.com/<tenant>/v2.0`` (v2.0 endpoint only).
- Audience: full ``api://<client-id>/<scope>`` URI; exact-match.
- Tenant: ``tid`` claim must equal ``ENTRA_TENANT_ID``.
- Clock leeway: 30 seconds.
- User-delegated tokens carry ``scp``; app-only (service principal) tokens
  carry ``roles`` only and no ``scp``.

Test fences:
- All unit tests run against a self-signed RSA keypair injected via the
  ``ENTRA_JWKS_OVERRIDE`` test seam — no live Entra calls in pytest.
"""
from __future__ import annotations

import json
import logging
import os
import threading
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

import jwt
import requests
from fastapi import Depends, HTTPException, Request, status
from fastapi.security import HTTPAuthorizationCredentials, HTTPBearer

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Configuration helpers (env-driven; no defaults for tenant identity values)
# ---------------------------------------------------------------------------

_DEFAULT_LEEWAY_SECONDS = 30
_DEFAULT_JWKS_TTL_SECONDS = 900  # 15 minutes per playbook §2


def _env(name: str) -> str:
    val = os.environ.get(name, "").strip()
    if not val:
        raise RuntimeError(f"Required Entra env var missing: {name}")
    return val


def _entra_enabled() -> bool:
    return os.environ.get("ENTRA_AUTH_ENABLED", "false").strip().lower() == "true"


def _legacy_enabled() -> bool:
    return os.environ.get("LEGACY_AUTH_ENABLED", "true").strip().lower() == "true"


def _tenant_id() -> str:
    return _env("ENTRA_TENANT_ID")


def _audience() -> str:
    return _env("ENTRA_API_AUDIENCE")


def _issuer() -> str:
    explicit = os.environ.get("ENTRA_AUTHORITY", "").strip()
    if explicit:
        return explicit
    return f"https://login.microsoftonline.com/{_tenant_id()}/v2.0"


def _jwks_url() -> str:
    explicit = os.environ.get("ENTRA_JWKS_URL", "").strip()
    if explicit:
        return explicit
    return f"https://login.microsoftonline.com/{_tenant_id()}/discovery/v2.0/keys"


# ---------------------------------------------------------------------------
# JWKS cache (in-process, thread-safe, TTL with stale-on-network-fail)
# ---------------------------------------------------------------------------


class JWKSCache:
    """In-process JWKS cache keyed by ``kid``.

    - TTL: ``_DEFAULT_JWKS_TTL_SECONDS`` (overridable via constructor).
    - On ``kid`` miss: forces a single refresh, then re-checks.
    - On network failure with a stale cache: serves stale (logged at WARNING).
    - On network failure with no cache: raises.

    Concurrency: a single ``threading.Lock`` guards refreshes so a stampede
    of requests during expiry triggers exactly one network fetch.
    """

    def __init__(self, ttl_seconds: int = _DEFAULT_JWKS_TTL_SECONDS):
        self.ttl_seconds = ttl_seconds
        self._keys_by_kid: Dict[str, Dict[str, Any]] = {}
        self._fetched_at: float = 0.0
        self._lock = threading.Lock()

    def _is_fresh(self) -> bool:
        if not self._keys_by_kid:
            return False
        return (time.time() - self._fetched_at) < self.ttl_seconds

    def _fetch(self) -> Dict[str, Dict[str, Any]]:
        """Pull JWKS from the configured URL or test-override JSON."""
        override = os.environ.get("ENTRA_JWKS_OVERRIDE")
        if override:
            data = json.loads(override)
        else:
            url = _jwks_url()
            response = requests.get(url, timeout=10)
            response.raise_for_status()
            data = response.json()

        keys = {k["kid"]: k for k in data.get("keys", []) if "kid" in k}
        if not keys:
            raise RuntimeError("JWKS response contained no keys with 'kid'")
        return keys

    def _refresh(self) -> None:
        try:
            self._keys_by_kid = self._fetch()
            self._fetched_at = time.time()
            logger.info("[entra_auth] JWKS refreshed (%d keys)", len(self._keys_by_kid))
        except Exception as exc:
            if self._keys_by_kid:
                logger.warning(
                    "[entra_auth] JWKS refresh failed; serving stale cache: %s", exc
                )
                return
            raise

    def get_signing_key(self, kid: str) -> Any:
        """Return a PyJWT-compatible public key for the given ``kid``.

        Triggers a refresh on cache miss after staleness; if the ``kid`` is
        still missing post-refresh, raises ``KeyError``.
        """
        with self._lock:
            if not self._is_fresh():
                self._refresh()

            if kid not in self._keys_by_kid:
                # Force a one-shot refresh to pick up rotated keys.
                self._refresh()

            jwk = self._keys_by_kid.get(kid)
            if not jwk:
                raise KeyError(f"Signing key '{kid}' not found in JWKS")

        return jwt.algorithms.RSAAlgorithm.from_jwk(json.dumps(jwk))


# Module-level cache instance. Reset by tests via ``reset_jwks_cache``.
_jwks_cache: JWKSCache = JWKSCache()


def reset_jwks_cache(ttl_seconds: int = _DEFAULT_JWKS_TTL_SECONDS) -> JWKSCache:
    """Test seam: rebuild the module-level JWKS cache. Returns the new instance."""
    global _jwks_cache
    _jwks_cache = JWKSCache(ttl_seconds=ttl_seconds)
    return _jwks_cache


# ---------------------------------------------------------------------------
# Actor + validation contract
# ---------------------------------------------------------------------------


@dataclass(frozen=True)
class Actor:
    """Authenticated principal extracted from a validated Entra token.

    ``oid`` is the stable Entra object ID; use it as the actor primary key.
    ``preferred_username`` is display-only and may collide across tenants.
    ``is_app_only`` distinguishes service-principal (client-credentials) tokens.
    """

    oid: str
    preferred_username: str
    email: Optional[str]
    roles: List[str]
    tenant_id: str
    is_app_only: bool
    correlation_id: str = field(default_factory=lambda: uuid.uuid4().hex)
    raw_claims: Dict[str, Any] = field(default_factory=dict)


def _unauthorized(detail: str) -> HTTPException:
    return HTTPException(
        status_code=status.HTTP_401_UNAUTHORIZED,
        detail=detail,
        headers={"WWW-Authenticate": "Bearer"},
    )


def _forbidden(detail: str) -> HTTPException:
    return HTTPException(status_code=status.HTTP_403_FORBIDDEN, detail=detail)


def validate_entra_token(token: str) -> Actor:
    """Validate an Entra-issued access token and return the parsed ``Actor``.

    Raises ``HTTPException(401)`` on any validation failure.
    """
    if not token or not isinstance(token, str):
        raise _unauthorized("Missing token")

    try:
        unverified = jwt.get_unverified_header(token)
    except jwt.PyJWTError as exc:
        raise _unauthorized(f"Malformed token header: {exc}")

    alg = unverified.get("alg")
    if alg != "RS256":
        raise _unauthorized(f"Unsupported algorithm: {alg!r}")
    kid = unverified.get("kid")
    if not kid:
        raise _unauthorized("Token header missing 'kid'")

    try:
        signing_key = _jwks_cache.get_signing_key(kid)
    except KeyError as exc:
        raise _unauthorized(str(exc))
    except Exception as exc:  # network / config
        logger.error("[entra_auth] JWKS lookup failed: %s", exc)
        raise _unauthorized("Signing key unavailable")

    try:
        claims = jwt.decode(
            token,
            signing_key,
            algorithms=["RS256"],
            audience=_audience(),
            issuer=_issuer(),
            leeway=_DEFAULT_LEEWAY_SECONDS,
            options={
                "require": ["exp", "iss", "aud"],
                "verify_signature": True,
                "verify_exp": True,
                "verify_iss": True,
                "verify_aud": True,
            },
        )
    except jwt.ExpiredSignatureError:
        raise _unauthorized("Token expired")
    except jwt.ImmatureSignatureError:
        raise _unauthorized("Token not yet valid (nbf)")
    except jwt.InvalidAudienceError:
        raise _unauthorized("Invalid token audience")
    except jwt.InvalidIssuerError:
        raise _unauthorized("Invalid token issuer")
    except jwt.InvalidSignatureError:
        raise _unauthorized("Invalid token signature")
    except jwt.MissingRequiredClaimError as exc:
        raise _unauthorized(f"Missing required claim: {exc}")
    except jwt.PyJWTError as exc:
        raise _unauthorized(f"Token validation failed: {exc}")

    expected_tid = _tenant_id()
    if claims.get("tid") != expected_tid:
        raise _unauthorized("Invalid token tenant")

    oid = claims.get("oid") or claims.get("sub")
    if not oid:
        raise _unauthorized("Token missing 'oid'/'sub'")

    raw_roles = claims.get("roles") or []
    if isinstance(raw_roles, str):
        roles = [r.strip() for r in raw_roles.split(",") if r.strip()]
    else:
        roles = [str(r) for r in raw_roles]

    return Actor(
        oid=str(oid),
        preferred_username=str(claims.get("preferred_username") or ""),
        email=claims.get("email"),
        roles=roles,
        tenant_id=str(claims.get("tid")),
        is_app_only=("scp" not in claims),
        raw_claims=claims,
    )


# ---------------------------------------------------------------------------
# FastAPI dependencies
# ---------------------------------------------------------------------------

_bearer_scheme = HTTPBearer(auto_error=False)


def _extract_bearer(
    request: Request, credentials: Optional[HTTPAuthorizationCredentials]
) -> Optional[str]:
    """Pull the Bearer token from the Authorization header or access_token cookie.

    The cookie path mirrors the legacy ``services.auth_deps`` behavior so
    Entra-issued tokens placed in the same cookie work without a UI change.
    """
    if credentials and credentials.scheme.lower() == "bearer":
        return credentials.credentials
    cookie_token = request.cookies.get("access_token")
    if cookie_token:
        return cookie_token
    return None


async def get_current_actor(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Actor:
    """Strict Entra-only dependency. Returns ``Actor`` or raises 401."""
    if not _entra_enabled():
        raise _unauthorized("Entra authentication disabled")
    token = _extract_bearer(request, credentials)
    if not token:
        raise _unauthorized("Missing bearer token")
    return validate_entra_token(token)


def require_role(*allowed_roles: str):
    """Dependency factory enforcing that the caller carries at least one
    of ``allowed_roles`` in the Entra ``roles`` claim.

    403 with structured detail on miss; 401 if unauthenticated.
    """
    if not allowed_roles:
        raise ValueError("require_role(): at least one role must be specified")

    allowed = set(allowed_roles)

    async def _check(actor: Actor = Depends(get_current_actor)) -> Actor:
        if not (allowed & set(actor.roles)):
            logger.warning(
                "[entra_auth] role-deny actor=%s required=%s have=%s",
                actor.oid,
                sorted(allowed),
                sorted(actor.roles),
            )
            raise _forbidden(
                f"Insufficient permissions. Required one of: {sorted(allowed)}"
            )
        return actor

    return _check


def require_app_only():
    """Dependency factory restricting an endpoint to service-principal
    (client-credentials, no ``scp``) callers."""

    async def _check(actor: Actor = Depends(get_current_actor)) -> Actor:
        if not actor.is_app_only:
            raise _forbidden("This endpoint is only available for service principals")
        return actor

    return _check


# ---------------------------------------------------------------------------
# Hybrid facade (Entra + legacy bcrypt JWT during migration window)
# ---------------------------------------------------------------------------


async def get_current_user_hybrid(
    request: Request,
    credentials: Optional[HTTPAuthorizationCredentials] = Depends(_bearer_scheme),
) -> Dict[str, Any]:
    """Migration facade returning a legacy-shaped user dict.

    Order of preference:
      1. If ``ENTRA_AUTH_ENABLED`` and a Bearer token validates → return Actor-as-dict.
      2. Else if ``LEGACY_AUTH_ENABLED`` → delegate to legacy ``get_current_user``.
      3. Else → 401.

    The legacy code path is preserved byte-identically: routes that depended on
    the legacy dict shape (``{"id","email","role",...}``) keep working unchanged.
    """
    token = _extract_bearer(request, credentials)

    if _entra_enabled() and token:
        try:
            actor = validate_entra_token(token)
            return {
                "id": actor.oid,
                "email": actor.email or actor.preferred_username,
                "username": actor.preferred_username,
                "role": (actor.roles[0] if actor.roles else "viewer"),
                "roles": actor.roles,
                "tenant_id": actor.tenant_id,
                "is_app_only": actor.is_app_only,
                "auth_source": "entra",
            }
        except HTTPException:
            if not _legacy_enabled():
                raise
            logger.debug("[entra_auth] Entra validation failed; trying legacy")

    if _legacy_enabled():
        from services.auth_deps import get_current_user as _legacy_get_current_user

        legacy_user = await _legacy_get_current_user(request)
        legacy_user.setdefault("auth_source", "legacy")
        return legacy_user

    raise _unauthorized("Authentication disabled")


__all__ = [
    "Actor",
    "JWKSCache",
    "validate_entra_token",
    "get_current_actor",
    "get_current_user_hybrid",
    "require_role",
    "require_app_only",
    "reset_jwks_cache",
]
