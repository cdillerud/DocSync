"""
GPI Document Hub — Centralized Business Central Configuration

PROTECTED INFRASTRUCTURE — Do not modify environment variable names
without updating all consumers.

This module is the SINGLE SOURCE OF TRUTH for all BC environment
configuration.  Every service that talks to Business Central must
import its settings from here rather than reading os.environ directly.

Design:
  READ operations  → BC Production  (complete operational data)
  WRITE operations → BC Sandbox     (safe testing target)

Key variables (from .env / environment):
  BC_READ_ENVIRONMENT   — environment name for reads  (default: Production)
  BC_WRITE_ENVIRONMENT  — environment name for writes (default: Sandbox)
  BC_WRITE_ENABLED      — master switch for write ops (default: false)
"""

import os
import logging
from typing import Dict, Any

logger = logging.getLogger(__name__)

# =============================================================================
# CANONICAL ENVIRONMENT VARIABLES  [PROTECTED INFRASTRUCTURE]
#
# BC_READ_ENVIRONMENT  — always points at Production for reliable matching
# BC_WRITE_ENVIRONMENT — always points at Sandbox for safe experimentation
# BC_WRITE_ENABLED     — master kill-switch for any BC mutation
# =============================================================================

BC_READ_ENVIRONMENT = (
    os.environ.get("BC_READ_ENVIRONMENT")
    or os.environ.get("BC_PROD_ENVIRONMENT")
    or "Production"
)

BC_WRITE_ENVIRONMENT = (
    os.environ.get("BC_WRITE_ENVIRONMENT")
    or os.environ.get("BC_ENVIRONMENT")
    or os.environ.get("BC_SANDBOX_ENVIRONMENT")
    or "Sandbox"
)

BC_WRITE_ENABLED = os.environ.get("BC_WRITE_ENABLED", "false").lower() == "true"

# =============================================================================
# CREDENTIALS — Read side (Production)
# =============================================================================

BC_READ_TENANT_ID = (
    os.environ.get("BC_PROD_TENANT_ID")
    or os.environ.get("TENANT_ID")
    or os.environ.get("BC_TENANT_ID", "")
)

BC_READ_CLIENT_ID = (
    os.environ.get("BC_PROD_CLIENT_ID")
    or os.environ.get("BC_CLIENT_ID", "")
)

BC_READ_CLIENT_SECRET = (
    os.environ.get("BC_PROD_CLIENT_SECRET")
    or os.environ.get("BC_CLIENT_SECRET", "")
)

# =============================================================================
# CREDENTIALS — Write side (Sandbox)
# =============================================================================

BC_WRITE_TENANT_ID = (
    os.environ.get("TENANT_ID")
    or os.environ.get("BC_TENANT_ID", "")
)

BC_WRITE_CLIENT_ID = (
    os.environ.get("BC_CLIENT_ID")
    or os.environ.get("BC_SANDBOX_CLIENT_ID", "")
)

BC_WRITE_CLIENT_SECRET = (
    os.environ.get("BC_CLIENT_SECRET")
    or os.environ.get("BC_SANDBOX_CLIENT_SECRET", "")
)

# =============================================================================
# SHARED
# =============================================================================

BC_COMPANY_NAME = (
    os.environ.get("BC_COMPANY_NAME")
    or os.environ.get("BC_SANDBOX_COMPANY_NAME", "")
)

BC_COMPANY_ID = os.environ.get("BC_COMPANY_ID", "")

BC_API_BASE = "https://api.businesscentral.dynamics.com/v2.0"
BC_REQUEST_TIMEOUT = 30.0

# =============================================================================
# DERIVED FLAGS
# =============================================================================

HAS_READ_CREDENTIALS = bool(
    BC_READ_TENANT_ID and BC_READ_CLIENT_ID and BC_READ_CLIENT_SECRET
)

HAS_WRITE_CREDENTIALS = bool(
    BC_WRITE_TENANT_ID and BC_WRITE_CLIENT_ID and BC_WRITE_CLIENT_SECRET
)

IS_READ_SANDBOX = "sandbox" in BC_READ_ENVIRONMENT.lower()
IS_READ_PRODUCTION = not IS_READ_SANDBOX


def _mask(val: str) -> str:
    if not val:
        return "NOT SET"
    return val[:8] + "..." if len(val) > 8 else "***"


# =============================================================================
# PUBLIC API
# =============================================================================

def get_read_config() -> Dict[str, Any]:
    """Configuration dict for all READ operations (validation, matching, cache)."""
    return {
        "tenant_id": BC_READ_TENANT_ID,
        "client_id": BC_READ_CLIENT_ID,
        "client_secret": BC_READ_CLIENT_SECRET,
        "environment": BC_READ_ENVIRONMENT,
        "company_name": BC_COMPANY_NAME,
        "label": f"Production ({BC_READ_ENVIRONMENT})" if IS_READ_PRODUCTION else f"Sandbox ({BC_READ_ENVIRONMENT})",
    }


def get_write_config() -> Dict[str, Any]:
    """Configuration dict for all WRITE operations (draft creation, posting)."""
    return {
        "tenant_id": BC_WRITE_TENANT_ID,
        "client_id": BC_WRITE_CLIENT_ID,
        "client_secret": BC_WRITE_CLIENT_SECRET,
        "environment": BC_WRITE_ENVIRONMENT,
        "company_name": BC_COMPANY_NAME,
        "label": f"Sandbox ({BC_WRITE_ENVIRONMENT})",
    }


def is_write_enabled() -> bool:
    return BC_WRITE_ENABLED


def check_write_allowed(action: str = "unknown") -> Dict[str, Any]:
    """
    Check whether a BC write operation is permitted.
    Returns dict with 'allowed' bool and 'reason' if blocked.
    """
    if not BC_WRITE_ENABLED:
        return {
            "allowed": False,
            "reason": "BC_WRITE_ENABLED is false — production safety lock",
            "action": action,
            "event": "bc.write_blocked",
        }
    if not HAS_WRITE_CREDENTIALS:
        return {
            "allowed": False,
            "reason": "Write credentials not configured",
            "action": action,
            "event": "bc.write_blocked",
        }
    return {"allowed": True, "action": action}


def get_config_fingerprint() -> Dict[str, str]:
    """Safe-to-log configuration fingerprint (no secrets)."""
    return {
        "BC_READ_ENVIRONMENT": BC_READ_ENVIRONMENT,
        "BC_WRITE_ENVIRONMENT": BC_WRITE_ENVIRONMENT,
        "BC_WRITE_ENABLED": str(BC_WRITE_ENABLED).lower(),
        "READ_CREDENTIALS": "present" if HAS_READ_CREDENTIALS else "MISSING",
        "WRITE_CREDENTIALS": "present" if HAS_WRITE_CREDENTIALS else "MISSING",
        "READ_TENANT": _mask(BC_READ_TENANT_ID),
        "WRITE_TENANT": _mask(BC_WRITE_TENANT_ID),
        "COMPANY": BC_COMPANY_NAME or "NOT SET",
    }


def get_mode_label() -> str:
    """Human-readable mode description."""
    if IS_READ_PRODUCTION and not BC_WRITE_ENABLED:
        return "SAFE (production reads, sandbox writes disabled)"
    if IS_READ_PRODUCTION and BC_WRITE_ENABLED:
        return "ACTIVE (production reads, sandbox writes enabled)"
    if IS_READ_SANDBOX and not BC_WRITE_ENABLED:
        return "DEGRADED (sandbox reads — validation may be unreliable)"
    return "DANGEROUS (sandbox reads, writes enabled)"


def get_diagnostics() -> Dict[str, Any]:
    """
    Public diagnostics payload for /api/admin/bc-config.
    Never exposes secrets.
    """
    return {
        "bc_read_environment": BC_READ_ENVIRONMENT,
        "bc_write_environment": BC_WRITE_ENVIRONMENT,
        "writes_enabled": BC_WRITE_ENABLED,
        "mode": get_mode_label(),
        "read_credentials_present": HAS_READ_CREDENTIALS,
        "write_credentials_present": HAS_WRITE_CREDENTIALS,
        "company_name": BC_COMPANY_NAME,
        "is_read_production": IS_READ_PRODUCTION,
    }


# =============================================================================
# STARTUP VALIDATION — call from main.py / server.py startup
# =============================================================================

def validate_and_log() -> None:
    """
    Validate BC configuration and emit startup log block.
    Should be called once during application startup.
    """
    fp = get_config_fingerprint()

    logger.info("=" * 60)
    logger.info("BC CONFIGURATION")
    logger.info("-" * 60)
    logger.info("  Read Environment : %s", BC_READ_ENVIRONMENT)
    logger.info("  Write Environment: %s", BC_WRITE_ENVIRONMENT)
    logger.info("  Writes Enabled   : %s", BC_WRITE_ENABLED)
    logger.info("  Mode             : %s", get_mode_label())
    logger.info("-" * 60)
    logger.info("CONFIG FINGERPRINT")
    for k, v in fp.items():
        logger.info("  %s=%s", k, v)
    logger.info("=" * 60)

    # Rule 1: BC_READ_ENVIRONMENT must be defined
    if not BC_READ_ENVIRONMENT:
        logger.error("[BC Config] BC_READ_ENVIRONMENT is not set!")

    # Rule 2: BC_WRITE_ENVIRONMENT must be defined
    if not BC_WRITE_ENVIRONMENT:
        logger.error("[BC Config] BC_WRITE_ENVIRONMENT is not set!")

    # Rule 3: If write env is production, require writes disabled
    if "production" in BC_WRITE_ENVIRONMENT.lower() and BC_WRITE_ENABLED:
        logger.warning(
            "[BC Config] DANGER: BC_WRITE_ENVIRONMENT is '%s' and BC_WRITE_ENABLED=true. "
            "Production writes are ENABLED. This is unsafe for non-production testing.",
            BC_WRITE_ENVIRONMENT,
        )

    # Rule 4: Warn if read environment is sandbox
    if IS_READ_SANDBOX:
        logger.warning(
            "[BC Config] WARNING: BC_READ_ENVIRONMENT='%s' appears to be a Sandbox. "
            "Reference intelligence and validation accuracy may be severely reduced. "
            "Set BC_READ_ENVIRONMENT=Production for reliable document processing.",
            BC_READ_ENVIRONMENT,
        )

    if not HAS_READ_CREDENTIALS:
        logger.warning("[BC Config] Read credentials are missing — BC reads will fail.")

    if not HAS_WRITE_CREDENTIALS:
        logger.warning("[BC Config] Write credentials are missing — BC writes will fail.")
