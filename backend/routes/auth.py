"""
GPI Document Hub - Auth Router

Authentication endpoints.
"""

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel
from datetime import datetime, timezone
import jwt as pyjwt
import os

router = APIRouter(prefix="/auth", tags=["auth"])

# JWT Config
JWT_SECRET = os.environ.get('JWT_SECRET', 'gpi-hub-secret-key')

# Test user (will be replaced with Entra ID SSO)
TEST_USER = {
    "username": "admin", 
    "password": "admin", 
    "display_name": "Hub Admin", 
    "role": "administrator"
}


class LoginRequest(BaseModel):
    username: str
    password: str


def create_token(username: str) -> str:
    payload = {"sub": username, "exp": datetime.now(timezone.utc).timestamp() + 86400}
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
                "role": TEST_USER["role"]
            }
        }
    raise HTTPException(status_code=401, detail="Invalid credentials")


@router.get("/me")
async def get_me():
    """Get current user info (simplified - no token validation)."""
    return {
        "username": TEST_USER["username"], 
        "display_name": TEST_USER["display_name"], 
        "role": TEST_USER["role"]
    }
