"""
GPI Document Hub — Centralized Configuration Service

Single source of truth for all environment variables, OAuth token acquisition,
and configuration utility functions. Extracted from server.py to decouple
downstream routers and services.

Usage:
    from services.config_service import TENANT_ID, get_graph_token, current_config
"""

import os
import logging

import httpx

logger = logging.getLogger("config_service")

# ---------------------------------------------------------------------------
# Core identity / tenant
# ---------------------------------------------------------------------------
DEMO_MODE = os.environ.get("DEMO_MODE", "true").lower() == "true"
JWT_SECRET = os.environ.get("JWT_SECRET", "gpi-hub-secret-key")

# ---------------------------------------------------------------------------
# Azure AD / Entra
# ---------------------------------------------------------------------------
TENANT_ID = os.environ.get("TENANT_ID", "")

# ---------------------------------------------------------------------------
# Business Central
# ---------------------------------------------------------------------------
BC_ENVIRONMENT = os.environ.get("BC_ENVIRONMENT", "")
BC_READ_ENVIRONMENT = os.environ.get(
    "BC_PROD_ENVIRONMENT", os.environ.get("BC_ENVIRONMENT", "")
)
BC_COMPANY_NAME = os.environ.get("BC_COMPANY_NAME", "")
BC_CLIENT_ID = os.environ.get("BC_CLIENT_ID", "")
BC_CLIENT_SECRET = os.environ.get("BC_CLIENT_SECRET", "")

# ---------------------------------------------------------------------------
# Microsoft Graph / Email
# ---------------------------------------------------------------------------
GRAPH_CLIENT_ID = os.environ.get("GRAPH_CLIENT_ID", "")
GRAPH_CLIENT_SECRET = os.environ.get("GRAPH_CLIENT_SECRET", "")
EMAIL_CLIENT_ID = os.environ.get("EMAIL_CLIENT_ID", "")
EMAIL_CLIENT_SECRET = os.environ.get("EMAIL_CLIENT_SECRET", "")

# ---------------------------------------------------------------------------
# Email Polling
# ---------------------------------------------------------------------------
EMAIL_POLLING_ENABLED = os.environ.get("EMAIL_POLLING_ENABLED", "false").lower() == "true"
EMAIL_POLLING_INTERVAL_MINUTES = int(os.environ.get("EMAIL_POLLING_INTERVAL_MINUTES", "5"))
EMAIL_POLLING_USER = os.environ.get("EMAIL_POLLING_USER", "")
EMAIL_POLLING_LOOKBACK_MINUTES = int(os.environ.get("EMAIL_POLLING_LOOKBACK_MINUTES", "60"))
EMAIL_POLLING_MAX_MESSAGES = int(os.environ.get("EMAIL_POLLING_MAX_MESSAGES", "25"))
EMAIL_POLLING_MAX_ATTACHMENT_MB = int(os.environ.get("EMAIL_POLLING_MAX_ATTACHMENT_MB", "25"))

SALES_EMAIL_POLLING_ENABLED = os.environ.get("SALES_EMAIL_POLLING_ENABLED", "false").lower() == "true"
SALES_EMAIL_POLLING_USER = os.environ.get("SALES_EMAIL_POLLING_USER", "")
SALES_EMAIL_POLLING_INTERVAL_MINUTES = int(os.environ.get("SALES_EMAIL_POLLING_INTERVAL_MINUTES", "5"))

# ---------------------------------------------------------------------------
# SharePoint
# ---------------------------------------------------------------------------
SHAREPOINT_SITE_HOSTNAME = os.environ.get("SHAREPOINT_SITE_HOSTNAME", "gamerpackaging.sharepoint.com")
SHAREPOINT_SITE_PATH = os.environ.get("SHAREPOINT_SITE_PATH", "/sites/GPI-DocumentHub-Test")
SHAREPOINT_LIBRARY_NAME = os.environ.get("SHAREPOINT_LIBRARY_NAME", "Documents")

# ---------------------------------------------------------------------------
# AI / LLM
# ---------------------------------------------------------------------------
AI_CLASSIFICATION_ENABLED = os.environ.get("AI_CLASSIFICATION_ENABLED", "true").lower() == "true"
AI_CLASSIFICATION_THRESHOLD = float(os.environ.get("AI_CLASSIFICATION_THRESHOLD", "0.8"))
EMERGENT_LLM_KEY = os.environ.get("EMERGENT_LLM_KEY", "")

# ---------------------------------------------------------------------------
# Feature flags
# ---------------------------------------------------------------------------
ENABLE_CREATE_DRAFT_HEADER = os.environ.get("ENABLE_CREATE_DRAFT_HEADER", "false").lower() == "true"

# ---------------------------------------------------------------------------
# Static maps
# ---------------------------------------------------------------------------
FOLDER_MAP = {
    "SalesOrder": "Sales",
    "SalesInvoice": "Sales",
    "PurchaseInvoice": "Purchase",
    "PurchaseOrder": "Purchase",
    "Shipment": "Warehouse",
    "Receipt": "Warehouse",
    "Other": "Incoming",
}

SECRET_KEYS = {"BC_CLIENT_SECRET", "GRAPH_CLIENT_SECRET"}

VENDOR_ALIAS_MAP: dict = {}


# ---------------------------------------------------------------------------
# Utility helpers
# ---------------------------------------------------------------------------

def mask(val: str) -> str:
    """Mask a secret value showing only first 4 and last 4 chars."""
    if not val or len(val) < 10:
        return "****" if val else ""
    return val[:4] + "*" * (len(val) - 8) + val[-4:]


# Keep backward-compatible alias
_mask = mask


def current_config() -> dict:
    """Return a snapshot of the live module-level config vars."""
    return {
        "TENANT_ID": TENANT_ID,
        "BC_ENVIRONMENT": BC_ENVIRONMENT,
        "BC_COMPANY_NAME": BC_COMPANY_NAME,
        "BC_CLIENT_ID": BC_CLIENT_ID,
        "BC_CLIENT_SECRET": BC_CLIENT_SECRET,
        "GRAPH_CLIENT_ID": GRAPH_CLIENT_ID,
        "GRAPH_CLIENT_SECRET": GRAPH_CLIENT_SECRET,
        "SHAREPOINT_SITE_HOSTNAME": SHAREPOINT_SITE_HOSTNAME,
        "SHAREPOINT_SITE_PATH": SHAREPOINT_SITE_PATH,
        "SHAREPOINT_LIBRARY_NAME": SHAREPOINT_LIBRARY_NAME,
        "DEMO_MODE": str(DEMO_MODE).lower(),
    }


# Keep backward-compatible alias
_current_config = current_config


# ---------------------------------------------------------------------------
# DB-driven config override
# ---------------------------------------------------------------------------

async def load_config_from_db():
    """Load saved config from MongoDB and apply to module globals."""
    global DEMO_MODE, TENANT_ID, BC_ENVIRONMENT, BC_COMPANY_NAME
    global BC_CLIENT_ID, BC_CLIENT_SECRET, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET
    global SHAREPOINT_SITE_HOSTNAME, SHAREPOINT_SITE_PATH, SHAREPOINT_LIBRARY_NAME

    from deps import get_db
    db = get_db()

    saved = await db.hub_config.find_one({"_key": "credentials"}, {"_id": 0, "_key": 0})
    if not saved:
        return
    if saved.get("TENANT_ID"):
        TENANT_ID = saved["TENANT_ID"]
    if saved.get("BC_ENVIRONMENT"):
        BC_ENVIRONMENT = saved["BC_ENVIRONMENT"]
    if saved.get("BC_COMPANY_NAME"):
        BC_COMPANY_NAME = saved["BC_COMPANY_NAME"]
    if saved.get("BC_CLIENT_ID"):
        BC_CLIENT_ID = saved["BC_CLIENT_ID"]
    if saved.get("BC_CLIENT_SECRET"):
        BC_CLIENT_SECRET = saved["BC_CLIENT_SECRET"]
    if saved.get("GRAPH_CLIENT_ID"):
        GRAPH_CLIENT_ID = saved["GRAPH_CLIENT_ID"]
    if saved.get("GRAPH_CLIENT_SECRET"):
        GRAPH_CLIENT_SECRET = saved["GRAPH_CLIENT_SECRET"]
    if saved.get("SHAREPOINT_SITE_HOSTNAME"):
        SHAREPOINT_SITE_HOSTNAME = saved["SHAREPOINT_SITE_HOSTNAME"]
    if saved.get("SHAREPOINT_SITE_PATH"):
        SHAREPOINT_SITE_PATH = saved["SHAREPOINT_SITE_PATH"]
    if saved.get("SHAREPOINT_LIBRARY_NAME"):
        SHAREPOINT_LIBRARY_NAME = saved["SHAREPOINT_LIBRARY_NAME"]
    if "DEMO_MODE" in saved:
        DEMO_MODE = str(saved["DEMO_MODE"]).lower() == "true"


# ---------------------------------------------------------------------------
# OAuth token acquisition
# ---------------------------------------------------------------------------

async def get_graph_token() -> str:
    """Acquire an OAuth2 token for Microsoft Graph API."""
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return "mock-graph-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(
            f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": GRAPH_CLIENT_ID,
                "client_secret": GRAPH_CLIENT_SECRET,
                "scope": "https://graph.microsoft.com/.default",
            },
        )
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"Graph token error: {error_desc}")
        return data["access_token"]


async def get_email_token() -> str:
    """Acquire an OAuth2 token for email access (Mail.Read)."""
    client_id = EMAIL_CLIENT_ID or GRAPH_CLIENT_ID
    client_secret = EMAIL_CLIENT_SECRET or GRAPH_CLIENT_SECRET

    if DEMO_MODE or not client_id:
        return "mock-email-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(
            f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
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


async def get_bc_token() -> str:
    """Acquire an OAuth2 token for Dynamics 365 Business Central API."""
    if DEMO_MODE or not BC_CLIENT_ID:
        return "mock-bc-token"
    async with httpx.AsyncClient() as c:
        resp = await c.post(
            f"https://login.microsoftonline.com/{TENANT_ID}/oauth2/v2.0/token",
            data={
                "grant_type": "client_credentials",
                "client_id": BC_CLIENT_ID,
                "client_secret": BC_CLIENT_SECRET,
                "scope": "https://api.businesscentral.dynamics.com/.default",
            },
        )
        data = resp.json()
        if "access_token" not in data:
            error_desc = data.get("error_description", data.get("error", "Unknown auth error"))
            raise Exception(f"BC token error: {error_desc}")
        return data["access_token"]
