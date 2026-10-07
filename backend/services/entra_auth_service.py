"""Microsoft Entra ID (work account) sign-in for the Hub.

The browser signs in with Microsoft (MSAL, authorization code + PKCE) and
posts the ID token once to /api/auth/entra. Here it is verified against
the tenant's published signing keys (signature, audience = this app,
issuer and tid = our tenant, not expired) and exchanged for the Hub's own
session token, so every /api route keeps the existing auth middleware.

Config (backend .env):
  ENTRA_TENANT_ID        directory (tenant) id; required
  ENTRA_CLIENT_ID        the Hub's app registration (SPA) client id; required
  ENTRA_ALLOWED_DOMAINS  comma list of e-mail domains (default gamerpackaging.com)
Users are created on first sign-in (role "user") and named per person,
which is what AP history and approvals record.
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)

_jwk_client = None


def config() -> Dict[str, Any]:
    return {
        "tenant_id": os.environ.get("ENTRA_TENANT_ID", "").strip(),
        "client_id": os.environ.get("ENTRA_CLIENT_ID", "").strip(),
        "domains": [d.strip().lower() for d in os.environ.get("ENTRA_ALLOWED_DOMAINS", "gamerpackaging.com").split(",") if d.strip()],
    }


def enabled() -> bool:
    c = config()
    return bool(c["tenant_id"] and c["client_id"])


def _client():
    global _jwk_client
    if _jwk_client is None:
        import jwt
        _jwk_client = jwt.PyJWKClient(
            f"https://login.microsoftonline.com/{config()['tenant_id']}/discovery/v2.0/keys",
            cache_keys=True, lifespan=24 * 3600)
    return _jwk_client


def verify_id_token(id_token: str) -> Dict[str, Any]:
    """Claims of a valid ID token for this app and tenant; raises ValueError."""
    import jwt
    c = config()
    if not enabled():
        raise ValueError("Entra sign-in is not configured")
    try:
        key = _client().get_signing_key_from_jwt(id_token).key
        claims = jwt.decode(
            id_token, key, algorithms=["RS256"], audience=c["client_id"],
            issuer=f"https://login.microsoftonline.com/{c['tenant_id']}/v2.0",
            options={"require": ["exp", "iat", "aud", "iss", "sub"]}, leeway=120)
    except Exception as e:
        raise ValueError(f"invalid token: {e.__class__.__name__}")
    if claims.get("tid") != c["tenant_id"]:
        raise ValueError("token is from another tenant")
    email = email_of(claims)
    if not email:
        raise ValueError("token has no e-mail")
    if c["domains"] and email.split("@")[-1] not in c["domains"]:
        raise ValueError("account domain is not allowed")
    return claims


def email_of(claims: Dict[str, Any]) -> Optional[str]:
    e = claims.get("email") or claims.get("preferred_username") or claims.get("upn")
    return str(e).strip().lower() if e and "@" in str(e) else None


async def upsert_user(db, claims: Dict[str, Any]) -> Dict[str, Any]:
    email = email_of(claims)
    now = datetime.now(timezone.utc).isoformat()
    existing = await db.users.find_one({"email": email}, {"_id": 0, "password_hash": 0})
    fields = {"display_name": claims.get("name") or email, "entra_oid": claims.get("oid"), "auth_provider": "entra",
              "last_login_at": now}
    if existing:
        await db.users.update_one({"email": email}, {"$set": fields})
        return {**existing, **fields}
    import uuid
    user = {"id": str(uuid.uuid4()), "email": email, "role": "user", "created_at": now, **fields}
    await db.users.insert_one(dict(user))
    logger.info("[EntraAuth] first sign-in: %s", email)
    return user

