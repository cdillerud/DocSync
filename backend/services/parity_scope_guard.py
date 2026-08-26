"""HTTP scope and access barrier for Square9 AP/Warehouse parity.

Sales and Inside Sales remain paused until explicitly re-authorized after parity.
Operational control-plane and batch-maintenance surfaces are admin-only. Normal
AP/Warehouse operator surfaces require an authenticated user. Business Central
FactBox API calls use a dedicated machine-to-machine key over HTTPS; authenticated
Hub users may access the same document-link API from the browser experience.
"""

from __future__ import annotations

import os
import secrets
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
    "/api/bc/sales-orders/create",
    "/api/gpi-integration/sales-orders",
    "/api/gpi-integration/ds-purchase-orders",
    "/api/gpi-integration/order-patterns",
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
    "/api/gpi-integration/status",
    "/api/gpi-integration/companies",
    "/api/gpi-integration/bc-api-schema",
    "/api/gpi-integration/logs",
    "/api/gpi-integration/dashboard",
    "/api/gpi-integration/item-mappings",
    "/api/gpi-integration/catalog",
    "/api/gpi-integration/customers",
    "/api/gpi-integration/vendors",
    "/api/gpi-integration/document-links/migrate-from-zetadocs",
    "/api/gpi-integration/purchase-invoices/retry-lines",
)

AUTHENTICATED_ONLY_PREFIXES = (
    "/api/documents",
    "/api/workflows",
    "/api/ap-review",
    "/api/human-routing-review",
    "/api/gpi-integration/purchase-invoices",
    "/api/gpi-integration/factbox-ui",
)

M2M_OR_USER_PREFIXES = (
    "/api/gpi-integration/document-links",
)

LEGACY_WEBHOOK_PATH = "/api/graph/webhook"
M2M_HEADER_NAME = "X-GPI-Hub-Key"


def _env_true(name: str, default: bool = False) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def sales_routes_enabled() -> bool:
    return _env_true("ENABLE_OUT_OF_SCOPE_SALES_ROUTES", False)


def graph_webhook_enabled() -> bool:
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


def is_m2m_or_user_path(path: str, prefixes: Iterable[str] = M2M_OR_USER_PREFIXES) -> bool:
    return _path_matches(path, prefixes)


def _valid_m2m_key(request: Request) -> bool:
    expected = os.environ.get("BC_HUB_API_KEY", "")
    supplied = request.headers.get(M2M_HEADER_NAME, "")
    if not expected or not supplied:
        return False
    return secrets.compare_digest(supplied, expected)


def _http_exception_response(exc: HTTPException) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={"detail": exc.detail},
        headers=getattr(exc, "headers", None),
    )


class ParityScopeGuardMiddleware(BaseHTTPMiddleware):
    """Enforce parity scope plus admin, operator, and BC machine authentication."""

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

        # Specific admin-only paths win over the broader document-links prefix.
        if is_admin_only_path(path):
            from services.auth_deps import require_admin
            try:
                await require_admin(request)
            except HTTPException as exc:
                return _http_exception_response(exc)

        elif is_m2m_or_user_path(path):
            if not _valid_m2m_key(request):
                from services.auth_deps import get_current_user
                try:
                    await get_current_user(request)
                except HTTPException:
                    return JSONResponse(
                        status_code=401,
                        content={"detail": "Valid Business Central machine credential or Hub user session required"},
                        headers={"WWW-Authenticate": "GPI-Hub-Key, Bearer"},
                    )

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
    "M2M_HEADER_NAME",
    "M2M_OR_USER_PREFIXES",
    "OUT_OF_SCOPE_SALES_PREFIXES",
    "ParityScopeGuardMiddleware",
    "graph_webhook_enabled",
    "is_admin_only_path",
    "is_authenticated_only_path",
    "is_m2m_or_user_path",
    "is_out_of_scope_sales_path",
    "sales_routes_enabled",
]
