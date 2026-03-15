"""
GPI Document Hub - Microsoft Graph API Access

Token acquisition for Graph API (SharePoint, email).
Mirrors the bc_access.py pattern for BC API tokens.
Extracted from server.py during Architecture Hardening pass.
"""

import httpx
import logging

import deps

logger = logging.getLogger(__name__)


async def get_graph_token() -> str:
    """Acquire an OAuth2 client-credentials token for the Microsoft Graph API."""
    if deps.DEMO_MODE or not deps.GRAPH_CLIENT_ID:
        return "mock-graph-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(
            f"https://login.microsoftonline.com/{deps.TENANT_ID}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": deps.GRAPH_CLIENT_ID,
                "client_secret": deps.GRAPH_CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"Graph token error: {error_desc}")
        return data["access_token"]


async def get_email_token() -> str:
    """Acquire a Graph token specifically for email access (Mail.Read).

    Uses EMAIL_CLIENT_ID/SECRET if set, otherwise falls back to GRAPH credentials.
    """
    client_id = deps.EMAIL_CLIENT_ID or deps.GRAPH_CLIENT_ID
    client_secret = deps.EMAIL_CLIENT_SECRET or deps.GRAPH_CLIENT_SECRET

    if deps.DEMO_MODE or not client_id:
        return "mock-email-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(
            f"https://login.microsoftonline.com/{deps.TENANT_ID}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": client_id,
                "client_secret": client_secret,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"Email token error: {error_desc}")
        return data["access_token"]
