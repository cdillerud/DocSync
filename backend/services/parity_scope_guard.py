"""HTTP scope and access barrier for Square9 AP/Warehouse parity.

Sales and Inside Sales remain paused until explicitly re-authorized after parity.
Operational control-plane and batch-maintenance surfaces are admin-only. Normal
AP/Warehouse operator surfaces require an authenticated user so anonymous callers
cannot mutate workflow/document state. Legacy Graph webhook intake is disabled by
default for the parity baseline and must be explicitly enabled post-parity.
"""

from __future__ import annotations

import os
from typing import Iterable

from fastapi import HTTPException
from starlette.middleware.base import BaseHTTPMiddleware
from starlette.requests import Request
from starlette.responses import JSONResponse


OUT_OF_SCOPE_SALES_PREFIXES = (
    "/api/sales",
    "/api/sales-dashboard",
    "/api/salesperson-dashboard",
    "/api/inside-sales-pilot",
    # Hidden under the generic BC router; this is still a real Sales write.
    "/api/bc/sales-orders/create",
)

ADMIN_ONLY_PREFIXES = (
    "/api/settings",
    "/api/admin",
    "/api/dev",
    "/api/migration",
    "/api/sharepoint",
    "/api/sharepoint-routing",
    "/api/email-polling",
    "/api/vendor-reprocess",
    "/api/auto-clear-reprocess",
    "/api/workflow-fix",
    "/api/dedup",
    "/api/vendor-profiles",
    "/api/auto-approve",
    "/api/file-integrity",
)

AUTHENTICATED_ONLY_PREFIXES = (
    "/api/documents",
    "/api/workflows",
    "/api/ap-review",
    "/api/human-routing-review",
)

LEGACY_WEBHOOK_PATH = "/api/graph/webhook"


def _env_true(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def sales_routes_enabled() -> bool:
    """Sales HTTP activation is explicit opt-in and defaults off."""
    return _env_true("ENABLE_OUT_OF_SCOPE_SALES_ROUTES", False)


def graph_webhook_enabled() -> bool:
    """Legacy Graph webhook intake is explicit opt-in and defaults off."""
    return _env_true("GRAPH_WEBHOOK_ENABLED", False)


def _path_matches(path: str, prefixes: Iterable[str]) -> bool:
    normalized = "/" + str(path or "").lstrip("/")
    normalized = normalized.rstrip("/") or "/"
    for prefix in prefixes:
        base = prefix.rstrip("/")
        if normalized == base or normalized.startswith(base + "/"):
            return True
    return False


def is_out_of_scope_sales_path(path: str, prefixes: Iterable[str] = OUT_OF_SCOPE_SALES_PREFIXES) -> bool:
    return _path_matches(path, prefixes)


def is_admin_only_path(path: str, prefixes: Iterable[str] = ADMIN_ONLY_PREFIXES) -> bool:
    return _path_matches(path, prefixes)


def is_authenticated_only_path(path: str, prefixes: Iterable[str] = AUTHENTICATED_ONLY_PREFIXES) -> bool:
    return _path_matches(path, prefixes)


def _http_exception_response(exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


class ParityScopeGuardMiddleware(BaseHTTPMiddleware):
    """Enforce parity scope, control-plane auth, operator auth, and webhook posture."""

    async def dispatch(self, request: Request, call_next):
        path = request.url.path

        if not sales_routes_enabled() and is_out_of_scope_sales_path(path):
            return JSONResponse(
                status_code=404,
                content={
                    "detail": "Route unavailable during AP/Warehouse Square9 parity phase",
                    "parity_scope": "AP/Warehouse",
                },
            )

        if path.rstrip("/") == LEGACY_WEBHOOK_PATH and not graph_webhook_enabled():
            return JSONResponse(
                status_code=404,
                content={
                    "detail": "Graph webhook disabled for AP/Warehouse parity baseline",
                    "parity_scope": "AP/Warehouse",
                },
            )

        # Import lazily to avoid creating auth/config cycles at module load.
        if is_admin_only_path(path):
            from services.auth_deps import require_admin

            try:
                await require_admin(request)
            except HTTPException as exc:
                return _http_exception_response(exc)

        elif is_authenticated_only_path(path):
            from services.auth_deps import get_current_user

            try:
                await get_current_user(request)
            except HTTPException as exc:
                return _http_exception_response(exc)

        return await call_next(request)


__all__ = [
    "ADMIN_ONLY_PREFIXES",
    "AUTHENTICATED_ONLY_PREFIXES",
    "LEGACY_WEBHOOK_PATH",
    "OUT_OF_SCOPE_SALES_PREFIXES",
    "ParityScopeGuardMiddleware",
    "graph_webhook_enabled",
    "is_admin_only_path",
    "is_authenticated_only_path",
    "is_out_of_scope_sales_path",
    "sales_routes_enabled",
]
