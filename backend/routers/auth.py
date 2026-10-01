"""
GPI Document Hub — Authentication Router

Routes:
  POST /api/auth/login — email + password -> JWT (Bearer + cookie)
  POST /api/auth/logout — clear access_token cookie
  GET  /api/auth/me    — return authenticated user (requires valid token)

The hardcoded ``admin/admin`` + default JWT_SECRET from the pre-fix code
have been removed. Login now bcrypt-verifies against the ``users``
collection, which is seeded on startup from ``ADMIN_EMAIL`` +
``ADMIN_PASSWORD`` env vars. See ``services/auth_deps.py`` for details.
"""

import time
from collections import deque

from fastapi import APIRouter, Depends, HTTPException, Request, Response
from pydantic import BaseModel, Field

from services.auth_deps import (
    create_access_token,
    get_current_user,
    verify_password,
)

router = APIRouter(prefix="/auth", tags=["auth"])


# -- Login throttling -----------------------------------------------------------
# Lock a client IP out after _MAX_FAILURES failed logins within _WINDOW_SECONDS.
# In-memory state is fine: the backend runs as a single uvicorn process.
_MAX_FAILURES = 10
_WINDOW_SECONDS = 15 * 60
_failed_logins: dict[str, deque] = {}


def _client_ip(request: Request) -> str:
    peer = request.client.host if request.client else ""
    # gpi-frontend's nginx sets X-Real-IP to the real client; only trust it
    # when the request comes from a private (docker network) peer.
    if peer.startswith(("172.", "10.", "192.168.", "127.")):
        return request.headers.get("X-Real-IP") or peer
    return peer


def _recent_failures(ip: str) -> int:
    q = _failed_logins.get(ip)
    if not q:
        return 0
    cutoff = time.monotonic() - _WINDOW_SECONDS
    while q and q[0] < cutoff:
        q.popleft()
    if not q:
        del _failed_logins[ip]
        return 0
    return len(q)


class LoginRequest(BaseModel):
    # Accept both 'email' and legacy 'username' for a transition window —
    # the frontend still sends 'username'. Either maps to the users.email field.
    email: str | None = Field(default=None)
    username: str | None = Field(default=None)
    password: str

    def resolved_email(self) -> str:
        return (self.email or self.username or "").strip().lower()


@router.post("/login")
async def login(req: LoginRequest, request: Request, response: Response):
    """Authenticate user and return JWT token.

    Token is returned in the response body AND set as an httpOnly cookie
    (browser-friendly). The frontend can use either.
    """
    ip = _client_ip(request)
    if _recent_failures(ip) >= _MAX_FAILURES:
        raise HTTPException(
            status_code=429, detail="Too many failed login attempts. Try again later."
        )

    email = req.resolved_email()
    if not email or not req.password:
        raise HTTPException(status_code=400, detail="Email and password required")

    db = request.app.state.db
    user = await db.users.find_one({"email": email})
    if not user or not verify_password(req.password, user.get("password_hash", "")):
        _failed_logins.setdefault(ip, deque()).append(time.monotonic())
        # Uniform error — don't leak whether the email exists.
        raise HTTPException(status_code=401, detail="Invalid credentials")

    _failed_logins.pop(ip, None)

    token = create_access_token(
        user_id=user.get("id") or str(user.get("_id", "")),
        email=user["email"],
        role=user.get("role", "user"),
    )
    response.set_cookie(
        key="access_token", value=token,
        httponly=True, samesite="lax",
        max_age=8 * 3600, path="/",
    )
    return {
        "token": token,
        "user": {
            "username": user["email"],     # kept for frontend backwards-compat
            "email": user["email"],
            "display_name": user.get("display_name", user["email"]),
            "role": user.get("role", "user"),
        },
    }


@router.post("/logout")
async def logout(response: Response, _user=Depends(get_current_user)):
    """Clear the access_token cookie. Requires a valid token to call."""
    response.delete_cookie(key="access_token", path="/")
    return {"ok": True}


@router.get("/me")
async def get_me(user=Depends(get_current_user)):
    """Return the authenticated user. 401 if token is missing/invalid/expired."""
    return {
        "username": user["email"],
        "email": user["email"],
        "display_name": user.get("display_name", user["email"]),
        "role": user.get("role", "user"),
    }
