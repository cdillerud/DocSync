"""
GPI Document Hub - Auth Router

Authentication endpoints.
"""

from datetime import datetime, timezone
import os
import sys

from fastapi import APIRouter, HTTPException
import jwt as pyjwt
from pydantic import BaseModel

router = APIRouter(prefix="/auth", tags=["auth"])

JWT_SECRET = os.environ.get("JWT_SECRET", "gpi-hub-secret-key")

TEST_USER = {
    "username": "admin",
    "password": "admin",
    "display_name": "Hub Admin",
    "role": "administrator",
}


class LoginRequest(BaseModel):
    username: str
    password: str


def create_token(username: str) -> str:
    payload = {
        "sub": username,
        "exp": datetime.now(timezone.utc).timestamp() + 86400,
    }
    return pyjwt.encode(payload, JWT_SECRET, algorithm="HS256")


@router.post("/login")
async def login(req: LoginRequest):
    """Authenticate user and return JWT token."""
    if req.username == TEST_USER["username"] and req.password == TEST_USER["password"]:
        token = create_token(req.username)
        return {
            "token": token,
            "user": {
                "username": TEST_USER["username"],
                "display_name": TEST_USER["display_name"],
                "role": TEST_USER["role"],
            },
        }
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/me")
async def get_me():
    """Get current user info (simplified - no token validation)."""
    return {
        "username": TEST_USER["username"],
        "display_name": TEST_USER["display_name"],
        "role": TEST_USER["role"],
    }


def _register_compatibility_routes() -> None:
    """Attach isolated compatibility routers during the server import."""
    server_module = sys.modules.get("server") or sys.modules.get("backend.server")
    api_router = getattr(server_module, "api_router", None)
    if api_router is None:
        return

    from routes.legacy_migration import router as legacy_migration_router
    from routes.runtime_compat import router as runtime_compat_router

    existing_paths = {route.path for route in api_router.routes}
    if not any(path.startswith("/migration/") for path in existing_paths):
        api_router.include_router(legacy_migration_router)
    if "/bc/companies" not in existing_paths:
        api_router.include_router(runtime_compat_router)


_register_compatibility_routes()
