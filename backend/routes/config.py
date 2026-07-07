"""
Settings/config endpoints: BC/Graph/SharePoint credentials + draft-creation
feature toggle.

Extracted from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 8 - deliberately done LAST per
the Decisions Log). Behavior is unchanged, but the internal mechanism is
simplified: the original server.py version kept its OWN module-level
globals (TENANT_ID, BC_CLIENT_ID, etc.) synced to core.config via a
"dual-write" - that was a transitional hack needed only because other
already-migrated modules read config.X while server.py's settings routes
still used bare global names. Now that the routes THEMSELVES are moving
here, there's no reason to keep two copies in sync - this file reads and
writes `core.config.X` directly, and core.config is the single source of
truth for everyone (server.py, routes/*.py, services/*.py, core/*.py).

server.py still calls _load_config_from_db() once at startup (see
MIGRATION_PROGRESS.md) - imported back there for that one call.
"""
import logging
import httpx
from typing import Optional
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from core.db import db
from core import config as core_config
from core.job_config import DRAFT_CREATION_CONFIG
from core.legacy_hub_helpers import FOLDER_MAP, get_graph_token, get_bc_token

router = APIRouter(prefix="/api")
logger = logging.getLogger(__name__)

CONFIG_KEYS = [
    "TENANT_ID", "BC_ENVIRONMENT", "BC_COMPANY_NAME", "BC_CLIENT_ID",
    "BC_CLIENT_SECRET", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET",
    "SHAREPOINT_SITE_HOSTNAME", "SHAREPOINT_SITE_PATH", "SHAREPOINT_LIBRARY_NAME",
    "DEMO_MODE"
]
SECRET_KEYS = {"BC_CLIENT_SECRET", "GRAPH_CLIENT_SECRET"}


def _mask(val: str) -> str:
    """Mask a secret value showing only first 4 and last 4 chars."""
    if not val or len(val) < 10:
        return "****" if val else ""
    return val[:4] + "*" * (len(val) - 8) + val[-4:]


def _current_config():
    """Read live config vars from core.config (the single source of truth)."""
    return {
        "TENANT_ID": core_config.TENANT_ID,
        "BC_ENVIRONMENT": core_config.BC_ENVIRONMENT,
        "BC_COMPANY_NAME": core_config.BC_COMPANY_NAME,
        "BC_CLIENT_ID": core_config.BC_CLIENT_ID,
        "BC_CLIENT_SECRET": core_config.BC_CLIENT_SECRET,
        "GRAPH_CLIENT_ID": core_config.GRAPH_CLIENT_ID,
        "GRAPH_CLIENT_SECRET": core_config.GRAPH_CLIENT_SECRET,
        "SHAREPOINT_SITE_HOSTNAME": core_config.SHAREPOINT_SITE_HOSTNAME,
        "SHAREPOINT_SITE_PATH": core_config.SHAREPOINT_SITE_PATH,
        "SHAREPOINT_LIBRARY_NAME": core_config.SHAREPOINT_LIBRARY_NAME,
        "DEMO_MODE": str(core_config.DEMO_MODE).lower(),
    }


async def _load_config_from_db():
    """Load saved config from MongoDB and apply to core.config."""
    saved = await db.hub_config.find_one({"_key": "credentials"}, {"_id": 0, "_key": 0})
    if not saved:
        return
    if saved.get("TENANT_ID"):
        core_config.TENANT_ID = saved["TENANT_ID"]
    if saved.get("BC_ENVIRONMENT"):
        core_config.BC_ENVIRONMENT = saved["BC_ENVIRONMENT"]
    if saved.get("BC_COMPANY_NAME"):
        core_config.BC_COMPANY_NAME = saved["BC_COMPANY_NAME"]
    if saved.get("BC_CLIENT_ID"):
        core_config.BC_CLIENT_ID = saved["BC_CLIENT_ID"]
    if saved.get("BC_CLIENT_SECRET"):
        core_config.BC_CLIENT_SECRET = saved["BC_CLIENT_SECRET"]
    if saved.get("GRAPH_CLIENT_ID"):
        core_config.GRAPH_CLIENT_ID = saved["GRAPH_CLIENT_ID"]
    if saved.get("GRAPH_CLIENT_SECRET"):
        core_config.GRAPH_CLIENT_SECRET = saved["GRAPH_CLIENT_SECRET"]
    if saved.get("SHAREPOINT_SITE_HOSTNAME"):
        core_config.SHAREPOINT_SITE_HOSTNAME = saved["SHAREPOINT_SITE_HOSTNAME"]
    if saved.get("SHAREPOINT_SITE_PATH"):
        core_config.SHAREPOINT_SITE_PATH = saved["SHAREPOINT_SITE_PATH"]
    if saved.get("SHAREPOINT_LIBRARY_NAME"):
        core_config.SHAREPOINT_LIBRARY_NAME = saved["SHAREPOINT_LIBRARY_NAME"]
    if "DEMO_MODE" in saved:
        core_config.DEMO_MODE = str(saved["DEMO_MODE"]).lower() == "true"


@router.get("/settings/status")
async def get_settings_status():
    c = core_config
    return {
        "demo_mode": c.DEMO_MODE,
        "connections": {
            "mongodb": {"status": "connected", "detail": "Configured"},
            "sharepoint": {
                "status": "configured" if (c.GRAPH_CLIENT_ID and not c.DEMO_MODE) else ("demo" if c.DEMO_MODE else "not_configured"),
                "site": c.SHAREPOINT_SITE_HOSTNAME or "Not set",
                "path": c.SHAREPOINT_SITE_PATH or "Not set",
                "library": c.SHAREPOINT_LIBRARY_NAME
            },
            "business_central": {
                "status": "configured" if (c.BC_CLIENT_ID and not c.DEMO_MODE) else ("demo" if c.DEMO_MODE else "not_configured"),
                "environment": c.BC_ENVIRONMENT or "Not set",
                "company": c.BC_COMPANY_NAME or "Not set"
            },
            "entra_id": {
                "status": "configured" if (c.TENANT_ID and not c.DEMO_MODE) else ("demo" if c.DEMO_MODE else "not_configured"),
                "tenant_id": (c.TENANT_ID[:8] + "...") if c.TENANT_ID else "Not set"
            }
        },
        "sharepoint_folders": list(set(FOLDER_MAP.values())),
        # Phase 4: Draft creation feature flag
        "features": {
            "create_draft_header": {
                "enabled": c.ENABLE_CREATE_DRAFT_HEADER,
                "description": "Phase 4: Create Purchase Invoice draft headers for high-confidence AP Invoice matches",
                "safety_thresholds": DRAFT_CREATION_CONFIG
            }
        }
    }


@router.get("/settings/config")
async def get_settings_config():
    """Return current config with secrets masked."""
    raw = _current_config()
    masked = {}
    for k, v in raw.items():
        masked[k] = _mask(v) if k in SECRET_KEYS else v
    return {"config": masked}


class ConfigUpdate(BaseModel):
    TENANT_ID: Optional[str] = None
    BC_ENVIRONMENT: Optional[str] = None
    BC_COMPANY_NAME: Optional[str] = None
    BC_CLIENT_ID: Optional[str] = None
    BC_CLIENT_SECRET: Optional[str] = None
    GRAPH_CLIENT_ID: Optional[str] = None
    GRAPH_CLIENT_SECRET: Optional[str] = None
    SHAREPOINT_SITE_HOSTNAME: Optional[str] = None
    SHAREPOINT_SITE_PATH: Optional[str] = None
    SHAREPOINT_LIBRARY_NAME: Optional[str] = None
    DEMO_MODE: Optional[str] = None


@router.put("/settings/config")
async def update_settings_config(update: ConfigUpdate):
    """Save config to MongoDB and reload in-memory. No .env write = no server restart."""
    # Load current saved config from DB
    saved = await db.hub_config.find_one({"_key": "credentials"}, {"_id": 0}) or {"_key": "credentials"}

    # Merge updates — skip masked placeholder values, strip whitespace
    update_dict = update.model_dump(exclude_none=True)
    for key, val in update_dict.items():
        if val is not None and "****" not in val:
            saved[key] = val.strip() if isinstance(val, str) else val

    # Upsert into MongoDB
    await db.hub_config.update_one(
        {"_key": "credentials"},
        {"$set": saved},
        upsert=True
    )

    # Reload in-memory immediately - core.config IS the live state everyone reads
    core_config.TENANT_ID = saved.get("TENANT_ID", core_config.TENANT_ID)
    core_config.BC_ENVIRONMENT = saved.get("BC_ENVIRONMENT", core_config.BC_ENVIRONMENT)
    core_config.BC_COMPANY_NAME = saved.get("BC_COMPANY_NAME", core_config.BC_COMPANY_NAME)
    core_config.BC_CLIENT_ID = saved.get("BC_CLIENT_ID", core_config.BC_CLIENT_ID)
    core_config.BC_CLIENT_SECRET = saved.get("BC_CLIENT_SECRET", core_config.BC_CLIENT_SECRET)
    core_config.GRAPH_CLIENT_ID = saved.get("GRAPH_CLIENT_ID", core_config.GRAPH_CLIENT_ID)
    core_config.GRAPH_CLIENT_SECRET = saved.get("GRAPH_CLIENT_SECRET", core_config.GRAPH_CLIENT_SECRET)
    core_config.SHAREPOINT_SITE_HOSTNAME = saved.get("SHAREPOINT_SITE_HOSTNAME", core_config.SHAREPOINT_SITE_HOSTNAME)
    core_config.SHAREPOINT_SITE_PATH = saved.get("SHAREPOINT_SITE_PATH", core_config.SHAREPOINT_SITE_PATH)
    core_config.SHAREPOINT_LIBRARY_NAME = saved.get("SHAREPOINT_LIBRARY_NAME", core_config.SHAREPOINT_LIBRARY_NAME)
    core_config.DEMO_MODE = str(saved.get("DEMO_MODE", "true")).lower() == "true"

    logger.info("Configuration updated via UI. Demo mode: %s", core_config.DEMO_MODE)

    # Return fresh masked config
    raw = _current_config()
    masked = {k: (_mask(v) if k in SECRET_KEYS else v) for k, v in raw.items()}
    return {"message": "Configuration saved successfully", "config": masked}


@router.post("/settings/test-connection")
async def test_connection(service: str = Query(...)):
    """Quick connectivity test with detailed permission diagnostics."""
    c = core_config
    if service == "graph":
        try:
            token = await get_graph_token()
            if token == "mock-graph-token":
                return {"service": "graph", "status": "demo", "detail": "Running in demo mode"}
            async with httpx.AsyncClient(timeout=15.0) as client:
                site_resp = await client.get(
                    f"https://graph.microsoft.com/v1.0/sites/{c.SHAREPOINT_SITE_HOSTNAME}:{c.SHAREPOINT_SITE_PATH}:",
                    headers={"Authorization": f"Bearer {token}"})
                if site_resp.status_code == 200:
                    site_data = site_resp.json()
                    return {"service": "graph", "status": "ok", "detail": f"Connected. Site: {site_data.get('displayName', 'OK')}"}
                elif site_resp.status_code in (401, 403):
                    return {"service": "graph", "status": "error",
                        "detail": f"Permission denied (HTTP {site_resp.status_code}). Your app registration needs 'Sites.ReadWrite.All' (Application permission, NOT Delegated). Go to Azure Portal > App Registrations > API Permissions > Add permission > Microsoft Graph > Application > Sites.ReadWrite.All > then click 'Grant admin consent'."}
                elif site_resp.status_code == 404:
                    return {"service": "graph", "status": "error",
                        "detail": f"Site not found (HTTP 404). Verify hostname='{c.SHAREPOINT_SITE_HOSTNAME}' and path='{c.SHAREPOINT_SITE_PATH}'. The path should be like '/sites/YourSiteName' (not a full URL)."}
                else:
                    error_body = site_resp.text[:500]
                    try:
                        error_json = site_resp.json()
                        error_msg = error_json.get('error', {}).get('message', error_body)
                        error_code = error_json.get('error', {}).get('code', '')
                    except:
                        error_msg = error_body
                        error_code = ''
                    logger.error(f"Graph site resolution failed (HTTP {site_resp.status_code}): {error_msg}")
                    return {"service": "graph", "status": "error",
                        "detail": f"HTTP {site_resp.status_code}: {error_msg}",
                        "error_code": error_code,
                        "hint": f"URL tried: https://graph.microsoft.com/v1.0/sites/{c.SHAREPOINT_SITE_HOSTNAME}:{c.SHAREPOINT_SITE_PATH}:"}
        except Exception as e:
            return {"service": "graph", "status": "error", "detail": str(e)}
    elif service == "bc":
        try:
            token = await get_bc_token()
            if token == "mock-bc-token":
                return {"service": "bc", "status": "demo", "detail": "Running in demo mode"}
            async with httpx.AsyncClient(timeout=15.0) as client:
                resp = await client.get(
                    f"https://api.businesscentral.dynamics.com/v2.0/{c.TENANT_ID}/{c.BC_ENVIRONMENT}/api/v2.0/companies",
                    headers={"Authorization": f"Bearer {token}"})
                if resp.status_code == 200:
                    try:
                        data = resp.json()
                    except Exception:
                        return {"service": "bc", "status": "error", "detail": f"BC returned non-JSON response (HTTP 200): {resp.text[:200]}"}
                    companies = data.get("value", [])
                    return {"service": "bc", "status": "ok", "detail": f"Connected. Found {len(companies)} companies: {', '.join(comp.get('displayName', comp.get('name','?')) for comp in companies[:3])}"}
                elif resp.status_code == 404:
                    if "NoEnvironment" in resp.text:
                        return {"service": "bc", "status": "error",
                            "detail": f"Environment '{c.BC_ENVIRONMENT}' does not exist. Check the exact name in BC admin center (it's case-sensitive)."}
                    return {"service": "bc", "status": "error", "detail": f"BC API not found (404): {resp.text[:200]}"}
                elif resp.status_code in (401, 403):
                    return {"service": "bc", "status": "error",
                        "detail": f"Permission denied (HTTP {resp.status_code}). Ensure the app is registered in BC under 'Microsoft Entra Applications' with D365 AUTOMATION role, and API.ReadWrite.All permission is granted."}
                else:
                    return {"service": "bc", "status": "error",
                        "detail": f"HTTP {resp.status_code}: {resp.text[:200]}"}
        except Exception as e:
            return {"service": "bc", "status": "error", "detail": str(e)}
    return {"service": service, "status": "unknown", "detail": "Unknown service"}


class DraftFeatureToggle(BaseModel):
    enabled: bool


@router.post("/settings/features/create-draft-header")
async def toggle_draft_creation_feature(toggle: DraftFeatureToggle):
    """
    Toggle the CREATE_DRAFT_HEADER feature flag.
    This is for SANDBOX testing only - production should use environment variables.

    IMPORTANT: This is a safety-critical feature. Only enable in sandbox environment.
    """
    old_value = core_config.ENABLE_CREATE_DRAFT_HEADER
    core_config.ENABLE_CREATE_DRAFT_HEADER = toggle.enabled

    logger.info(
        "CREATE_DRAFT_HEADER feature toggled: %s -> %s (by UI toggle)",
        old_value, core_config.ENABLE_CREATE_DRAFT_HEADER
    )

    return {
        "feature": "create_draft_header",
        "previous_value": old_value,
        "current_value": core_config.ENABLE_CREATE_DRAFT_HEADER,
        "message": f"Draft creation feature {'enabled' if core_config.ENABLE_CREATE_DRAFT_HEADER else 'disabled'}",
        "safety_thresholds": DRAFT_CREATION_CONFIG if core_config.ENABLE_CREATE_DRAFT_HEADER else None
    }


@router.get("/settings/features/create-draft-header")
async def get_draft_creation_feature_status():
    """
    Get the current status of the CREATE_DRAFT_HEADER feature.
    """
    return {
        "feature": "create_draft_header",
        "enabled": core_config.ENABLE_CREATE_DRAFT_HEADER,
        "safety_thresholds": DRAFT_CREATION_CONFIG,
        "eligible_match_methods": DRAFT_CREATION_CONFIG["eligible_match_methods"],
        "min_match_score": DRAFT_CREATION_CONFIG["min_match_score_for_draft"],
        "min_confidence": DRAFT_CREATION_CONFIG["min_confidence_for_draft"],
        "supported_job_types": ["AP_Invoice"]
    }
