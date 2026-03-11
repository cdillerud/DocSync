"""
GPI Document Hub — Auth Router (Thin Wrapper)

Extracts auth routes from server.py during modular refactor.
Handler functions remain in server.py; this router re-registers them
so they are served by the new modular entry point first.
"""

from fastapi import APIRouter
import server

router = APIRouter(prefix="/auth", tags=["Auth"])

# POST /auth/login
router.add_api_route("/login", server.login, methods=["POST"])

# GET /auth/me
router.add_api_route("/me", server.get_me, methods=["GET"])
