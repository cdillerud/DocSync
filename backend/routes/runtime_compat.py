"""Small compatibility endpoints for integrations that need graceful degradation."""

from __future__ import annotations

import logging
import sys

from fastapi import APIRouter

logger = logging.getLogger(__name__)
router = APIRouter(tags=["Runtime Compatibility"])


def _server_module():
    return sys.modules.get("server") or sys.modules.get("backend.server")


@router.get("/bc/companies")
async def list_bc_companies_compat():
    """Return BC companies without turning a configuration outage into HTTP 500.

    Consumers historically use this endpoint as a connectivity/status lookup.
    A missing environment, expired credential, or permission problem is exposed
    in ``connection_error`` while the API remains available and returns an empty
    company list.
    """
    server_module = _server_module()
    get_companies = getattr(server_module, "get_bc_companies", None)
    if get_companies is None:
        return {
            "companies": [],
            "available": False,
            "connection_error": "Business Central service is not initialized",
        }

    try:
        companies = await get_companies()
        return {
            "companies": companies,
            "available": True,
            "connection_error": None,
        }
    except Exception as exc:
        logger.error("Business Central companies lookup failed: %s", exc)
        return {
            "companies": [],
            "available": False,
            "connection_error": str(exc),
        }
