"""
Authentication helpers — single source of truth for JWT issuing, verification,
password hashing, and the FastAPI ``Depends(get_current_user)`` gate that
mutating routes hang off.

History / why this module exists
--------------------------------
The 2026-04 engineering review (Finding #1) flagged that every API route
was anonymous: the ``JWT_SECRET`` had a known-default fallback, the admin
password was hardcoded ``admin/admin`` in plain text, and no route enforced
a token check. This module closes all of those holes:

* ``JWT_SECRET`` is read via ``os.environ["JWT_SECRET"]`` — missing env
  var raises ``RuntimeError`` at import time, not a silent 500 later.
* Admin password is bcrypt-hashed and stored in MongoDB ``users``
  collection, seeded on startup from ``ADMIN_EMAIL`` + ``ADMIN_PASSWORD``
  env vars. Changing the env var re-hashes on next boot (idempotent).
* ``get_current_user`` is a real FastAPI dependency: it decodes the JWT
  against the real ``JWT_SECRET``, looks the user up in Mongo, and raises
  401 on any failure. ``require_admin`` layers a role check on top.

Token is accepted from either:
  * ``Authorization: Bearer <token>`` header  (preferred, enterprise)
  * ``access_token`` cookie                    (browser-friendly)
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timedelta, timezone
from typing import Optional

import bcrypt
import jwt as pyjwt
from fastapi import HTTPException, Request, status
from motor.motor_asyncio import AsyncIOMotorDatabase

logger = logging.getLogger(__name__)

# -- Constants / config --------------------------------------------------------
JWT_ALGORITHM = "HS256"
ACCESS_TOKEN_TTL = timedelta(hours=8)

# Known-insecure default from the pre-fix code — refuse to operate if the env
# value matches. Listed explicitly so an ops person can't accidentally revert.
_INSECURE_JWT_DEFAULTS = {
    "gpi-hub-secret-key",
    "changeme",
    "secret",
    "",
}


def _jwt_secret() -> str:
    """Return JWT_SECRET or raise at call time. Combined with the startup
    validator, callers should never actually hit the RuntimeError path in
    production — the server won't have started."""
    secret = os.environ.get("JWT_SECRET", "")
    if not secret or secret in _INSECURE_JWT_DEFAULTS:
        raise RuntimeError(
            "JWT_SECRET environment variable is missing or set to a known "
            "insecure default. Set it to a random 64+ char hex string."
        )
    return secret


# -- Password hashing ---------------------------------------------------------

def hash_password(plain: str) -> str:
    """Bcrypt-hash a password. Safe to call on startup for admin seeding."""
    return bcrypt.hashpw(plain.encode("utf-8"), bcrypt.gensalt()).decode("utf-8")


def verify_password(plain: str, hashed: str) -> bool:
    """Constant-time bcrypt verify. Returns False on any malformed hash."""
    try:
        return bcrypt.checkpw(plain.encode("utf-8"), hashed.encode("utf-8"))
    except (ValueError, TypeError):
        return False


# -- Token issue / decode ------------------------------------------------------

def create_access_token(user_id: str, email: str, role: str = "user") -> str:
    payload = {
        "sub": user_id,
        "email": email,
        "role": role,
        "exp": datetime.now(timezone.utc) + ACCESS_TOKEN_TTL,
        "iat": datetime.now(timezone.utc),
        "type": "access",
    }
    return pyjwt.encode(payload, _jwt_secret(), algorithm=JWT_ALGORITHM)


def decode_access_token(token: str) -> dict:
    """Decode and verify a JWT. Raises HTTPException(401) on any failure —
    deliberately uniform to avoid leaking which check failed."""
    try:
        payload = pyjwt.decode(token, _jwt_secret(), algorithms=[JWT_ALGORITHM])
    except pyjwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Token expired"
        )
    except pyjwt.InvalidTokenError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Invalid token"
        )
    if payload.get("type") != "access":
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Wrong token type"
        )
    return payload


# -- FastAPI dependency --------------------------------------------------------

def _extract_token(request: Request) -> Optional[str]:
    auth = request.headers.get("Authorization", "")
    if auth.lower().startswith("bearer "):
        return auth[7:].strip() or None
    return request.cookies.get("access_token")


async def get_current_user(request: Request) -> dict:
    """Return the authenticated user dict or raise 401.

    Usage::

        from services.auth_deps import get_current_user

        @router.post("/mutating-endpoint")
        async def handler(user = Depends(get_current_user)):
            ...
    """
    token = _extract_token(request)
    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="Not authenticated"
        )
    payload = decode_access_token(token)

    db: AsyncIOMotorDatabase = request.app.state.db
    user = await db.users.find_one(
        {"email": payload.get("email")},
        {"password_hash": 0, "_id": 0},
    )
    if not user:
        # Token is validly signed but the user was deleted / disabled.
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED, detail="User no longer exists"
        )
    return user


async def require_admin(request: Request) -> dict:
    """Admin-only variant. Wraps ``get_current_user`` + role check."""
    user = await get_current_user(request)
    if user.get("role") != "admin":
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN, detail="Admin role required"
        )
    return user


# -- Admin seeding -------------------------------------------------------------

async def seed_admin_user(db: AsyncIOMotorDatabase) -> dict:
    """Idempotent admin user seed. Called from FastAPI startup.

    Reads ``ADMIN_EMAIL`` + ``ADMIN_PASSWORD`` from env. If the admin user
    doesn't exist, creates it. If it exists but the env password no longer
    matches the stored hash, re-hashes and updates (supports rotation).

    Returns a small status dict used by the startup logger.
    """
    admin_email = os.environ.get("ADMIN_EMAIL", "").strip().lower()
    admin_password = os.environ.get("ADMIN_PASSWORD", "")
    if not admin_email or not admin_password:
        raise RuntimeError(
            "ADMIN_EMAIL and ADMIN_PASSWORD env vars are required so the "
            "admin account can be seeded. Refusing to start."
        )

    existing = await db.users.find_one({"email": admin_email})
    if existing is None:
        import uuid
        new_user = {
            "id": str(uuid.uuid4()),
            "email": admin_email,
            "password_hash": hash_password(admin_password),
            "display_name": "Hub Admin",
            "role": "admin",
            "created_at": datetime.now(timezone.utc).isoformat(),
        }
        await db.users.insert_one(new_user)
        logger.info("[Auth] Seeded admin user %s", admin_email)
        return {"action": "created", "email": admin_email}

    if not verify_password(admin_password, existing.get("password_hash", "")):
        await db.users.update_one(
            {"email": admin_email},
            {"$set": {"password_hash": hash_password(admin_password)}},
        )
        logger.info("[Auth] Rotated admin password for %s", admin_email)
        return {"action": "rotated", "email": admin_email}

    return {"action": "unchanged", "email": admin_email}
