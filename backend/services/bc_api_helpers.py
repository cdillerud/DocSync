"""
GPI Document Hub - BC API Helpers

Authoritative implementations of Business Central company and sales order
lookup functions, extracted from server.py during the "Shared Helper Extraction"
remediation pass.

These are thin BC API wrappers used by routers/bc_integration.py and
internally by server.py orchestration logic.
"""

import os
import logging
import httpx
from typing import Optional

from deps import DEMO_MODE

logger = logging.getLogger(__name__)

# ---------------------------------------------------------------------------
# Config (read from env vars directly, matching server.py semantics)
# ---------------------------------------------------------------------------

_TENANT_ID = os.environ.get('TENANT_ID', '')
_BC_READ_ENVIRONMENT = os.environ.get('BC_PROD_ENVIRONMENT', os.environ.get('BC_ENVIRONMENT', ''))
_BC_CLIENT_ID = os.environ.get('BC_CLIENT_ID', '')
_BC_CLIENT_SECRET = os.environ.get('BC_CLIENT_SECRET', '')

# ---------------------------------------------------------------------------
# Mock data (demo mode)
# ---------------------------------------------------------------------------

MOCK_COMPANIES = [
    {"id": "c1d2e3f4-0000-0000-0000-000000000001", "name": "GPI Packaging Ltd", "displayName": "GPI Packaging Ltd"},
    {"id": "c1d2e3f4-0000-0000-0000-000000000002", "name": "GPI Test Company", "displayName": "GPI Test Company"},
]

MOCK_SALES_ORDERS = [
    {"id": "a1b2c3d4-1111-0000-0000-000000000001", "number": "SO-1001", "orderDate": "2025-11-15", "customerName": "Acme Corp", "status": "Open", "totalAmountIncludingVAT": 1250.00},
    {"id": "a1b2c3d4-1111-0000-0000-000000000002", "number": "SO-1002", "orderDate": "2025-11-16", "customerName": "Widget Co", "status": "Open", "totalAmountIncludingVAT": 3400.50},
    {"id": "a1b2c3d4-1111-0000-0000-000000000003", "number": "SO-1003", "orderDate": "2025-12-01", "customerName": "TechnoServ Ltd", "status": "Released", "totalAmountIncludingVAT": 8900.00},
    {"id": "a1b2c3d4-1111-0000-0000-000000000004", "number": "SO-1004", "orderDate": "2025-12-05", "customerName": "PackRight Inc", "status": "Open", "totalAmountIncludingVAT": 520.75},
    {"id": "a1b2c3d4-1111-0000-0000-000000000005", "number": "SO-1005", "orderDate": "2026-01-10", "customerName": "Global Foods Ltd", "status": "Released", "totalAmountIncludingVAT": 12300.00},
    {"id": "a1b2c3d4-1111-0000-0000-000000000006", "number": "SO-1006", "orderDate": "2026-01-15", "customerName": "MediPack Solutions", "status": "Open", "totalAmountIncludingVAT": 4560.25},
    {"id": "a1b2c3d4-1111-0000-0000-000000000007", "number": "SO-1007", "orderDate": "2026-02-01", "customerName": "EuroPack GmbH", "status": "Open", "totalAmountIncludingVAT": 7800.00},
]


# ---------------------------------------------------------------------------
# Token helper (self-contained, mirrors server.py get_bc_token semantics)
# ---------------------------------------------------------------------------

async def _get_bc_token() -> str:
    """Obtain a BC OAuth2 token. Returns mock token in demo mode."""
    if DEMO_MODE or not _BC_CLIENT_ID:
        return "mock-bc-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(
            f"https://login.microsoftonline.com/{_TENANT_ID}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": _BC_CLIENT_ID,
                "client_secret": _BC_CLIENT_SECRET,
                "scope": "https://api.businesscentral.dynamics.com/.default",
            },
        )
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"BC token error: {error_desc}")
        return data["access_token"]


# ---------------------------------------------------------------------------
# BC API lookup functions
# ---------------------------------------------------------------------------

async def get_bc_companies():
    """List available Business Central companies."""
    if DEMO_MODE or not _BC_CLIENT_ID:
        return MOCK_COMPANIES
    token = await _get_bc_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.get(
            f"https://api.businesscentral.dynamics.com/v2.0/{_TENANT_ID}/{_BC_READ_ENVIRONMENT}/api/v2.0/companies",
            headers={"Authorization": f"Bearer {token}"},
        )
        if resp.status_code == 404:
            if "NoEnvironment" in resp.text:
                raise Exception(f"BC environment '{_BC_READ_ENVIRONMENT}' does not exist. Check the environment name in Settings.")
            raise Exception(f"BC API not found (404): {resp.text[:200]}")
        if resp.status_code in (401, 403):
            raise Exception(f"BC permission denied (HTTP {resp.status_code}). Ensure the app is registered in BC under 'Microsoft Entra Applications' with D365 AUTOMATION role.")
        try:
            data = resp.json()
        except Exception:
            raise Exception(f"BC returned non-JSON (HTTP {resp.status_code}): {resp.text[:200]}")
        if "error" in data:
            raise Exception(f"BC companies error: {data['error'].get('message', data['error'])}")
        return data.get("value", [])


async def get_bc_sales_orders(order_no: Optional[str] = None):
    """Search Business Central sales orders."""
    if DEMO_MODE or not _BC_CLIENT_ID:
        orders = MOCK_SALES_ORDERS
        if order_no:
            orders = [o for o in orders if order_no.lower() in o["number"].lower()]
        return orders
    token = await _get_bc_token()
    companies = await get_bc_companies()
    if not companies:
        raise Exception("No BC companies found")
    company_id = companies[0]["id"]
    async with httpx.AsyncClient(timeout=30.0) as c:
        url = f"https://api.businesscentral.dynamics.com/v2.0/{_TENANT_ID}/{_BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/salesOrders"
        if order_no:
            url += f"?$filter=contains(number,'{order_no}')"
        resp = await c.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code in (401, 403):
            raise Exception(f"BC sales orders permission denied (HTTP {resp.status_code}). Ensure the app has D365 AUTOMATION role in BC.")
        try:
            data = resp.json()
        except Exception:
            raise Exception(f"BC returned non-JSON (HTTP {resp.status_code}): {resp.text[:200]}")
        if "error" in data:
            raise Exception(f"BC sales orders error: {data['error'].get('message', data['error'])}")
        return data.get("value", [])
