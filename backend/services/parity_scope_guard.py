"""HTTP scope barrier for the Square9 AP/Warehouse parity phase.

Sales and Inside Sales remain paused until explicitly re-authorized after parity.
This module blocks their mounted HTTP route families centrally so an endpoint
cannot become reachable merely because a router was imported by main.py.
"""

from __future__ import annotations

import os
from typing import Iterable

from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


OUT_OF_SCOPE_SALES_PREFIXES = (
    "/api/sales",
    "/api/sales-dashboard",
    "/api/salesperson-dashboard",
    "/api/inside-sales-pilot",
)


def _env_true(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def sales_routes_enabled() -> bool:
    """Sales HTTP activation is explicit opt-in and defaults off."""
    return _env_true("ENABLE_OUT_OF_SCOPE_SALES_ROUTES", False)


def is_out_of_scope_sales_path(path: str, prefixes: Iterable[str] = OUT_OF_SCOPE_SALES_PREFIXES) -> bool:
    normalized = "/" + str(path or "").lstrip("/")
    normalized = normalized.rstrip("/") or "/"
    for prefix in prefixes:
        base = prefix.rstrip("/")
        if normalized == base or normalized.startswith(base + "/"):
            return True
    return False


class ParityScopeGuardMiddleware(BaseHTTPMiddleware):
    """Hide paused Sales/Inside Sales APIs unless explicitly enabled."""

    async def dispatch(self, request: Request, call_next):
        if not sales_routes_enabled() and is_out_of_scope_sales_path(request.url.path):
            return JSONResponse(
                status_code=404,
                content={
                    "detail": "Route unavailable during AP/Warehouse Square9 parity phase",
                    "parity_scope": "AP/Warehouse",
                },
            )
        return await call_next(request)


__all__ = [
    "OUT_OF_SCOPE_SALES_PREFIXES",
    "ParityScopeGuardMiddleware",
    "is_out_of_scope_sales_path",
    "sales_routes_enabled",
]
