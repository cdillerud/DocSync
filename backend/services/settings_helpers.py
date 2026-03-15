"""
GPI Document Hub - Settings Admin Helpers

Utilities for the settings admin UI: config masking, config snapshot.
Extracted from server.py during Architecture Hardening pass.
"""

from deps import (
    DEMO_MODE, TENANT_ID, BC_ENVIRONMENT, BC_COMPANY_NAME,
    BC_CLIENT_ID, BC_CLIENT_SECRET, GRAPH_CLIENT_ID, GRAPH_CLIENT_SECRET,
    SHAREPOINT_SITE_HOSTNAME, SHAREPOINT_SITE_PATH, SHAREPOINT_LIBRARY_NAME,
)

SECRET_KEYS = {"BC_CLIENT_SECRET", "GRAPH_CLIENT_SECRET"}

CONFIG_KEYS = [
    "TENANT_ID", "BC_ENVIRONMENT", "BC_COMPANY_NAME", "BC_CLIENT_ID",
    "BC_CLIENT_SECRET", "GRAPH_CLIENT_ID", "GRAPH_CLIENT_SECRET",
    "SHAREPOINT_SITE_HOSTNAME", "SHAREPOINT_SITE_PATH", "SHAREPOINT_LIBRARY_NAME",
    "DEMO_MODE",
]


def mask_secret(val: str) -> str:
    """Mask a secret value showing only first 4 and last 4 chars."""
    if not val or len(val) < 10:
        return "****" if val else ""
    return val[:4] + "*" * (len(val) - 8) + val[-4:]


def current_config() -> dict:
    """Read live module-level config vars from deps."""
    import deps
    return {
        "TENANT_ID": deps.TENANT_ID,
        "BC_ENVIRONMENT": deps.BC_ENVIRONMENT,
        "BC_COMPANY_NAME": deps.BC_COMPANY_NAME,
        "BC_CLIENT_ID": deps.BC_CLIENT_ID,
        "BC_CLIENT_SECRET": deps.BC_CLIENT_SECRET,
        "GRAPH_CLIENT_ID": deps.GRAPH_CLIENT_ID,
        "GRAPH_CLIENT_SECRET": deps.GRAPH_CLIENT_SECRET,
        "SHAREPOINT_SITE_HOSTNAME": deps.SHAREPOINT_SITE_HOSTNAME,
        "SHAREPOINT_SITE_PATH": deps.SHAREPOINT_SITE_PATH,
        "SHAREPOINT_LIBRARY_NAME": deps.SHAREPOINT_LIBRARY_NAME,
        "DEMO_MODE": str(deps.DEMO_MODE).lower(),
    }
