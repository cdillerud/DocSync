"""
Startup secret and cutover-safety validation — fail loudly if the environment
is misconfigured.

The Square9 parity phase is AP/Warehouse only. In addition to refusing missing
or insecure secrets, startup refuses any configuration that can activate Sales
or Inside Sales writes/polling during this cutover.
"""

from __future__ import annotations

import logging
import os
from typing import List, Tuple

logger = logging.getLogger(__name__)


# (env_var_name, insecure_defaults_to_refuse, description)
_REQUIRED_SECRETS: List[Tuple[str, set, str]] = [
    (
        "JWT_SECRET",
        {"", "gpi-hub-secret-key", "changeme", "secret", "test"},
        "JWT signing key — must be a random 64+ char string",
    ),
    (
        "ADMIN_EMAIL",
        {"", "admin@example.com"},
        "Seed admin account email",
    ),
    (
        "ADMIN_PASSWORD",
        {"", "admin", "admin123", "changeme", "password"},
        "Seed admin account password — change on first deploy",
    ),
    (
        "MONGO_URL",
        {""},
        "MongoDB connection string",
    ),
]

# Secrets that SHOULD be set in production but whose absence is tolerated
# in dev. A warning is emitted instead of crashing.
_OPTIONAL_SECRETS: List[Tuple[str, str]] = [
    ("BC_CLIENT_ID", "Business Central app registration — required for live BC writes"),
    ("BC_CLIENT_SECRET", "Business Central app registration secret"),
    ("BC_TENANT_ID", "BC Azure tenant"),
    ("GRAPH_CLIENT_ID", "Microsoft Graph app registration — required for email/SharePoint"),
    ("GRAPH_CLIENT_SECRET", "Graph app secret"),
    ("FRONTEND_URL", "Explicit frontend origin for CORS (same-origin is preferred)"),
]


_FALSE_VALUES = {"0", "false", "no", "off"}


def _is_explicit_false(name: str) -> bool:
    raw = os.environ.get(name)
    return raw is not None and raw.strip().lower() in _FALSE_VALUES


def _is_truthy(name: str) -> bool:
    raw = os.environ.get(name, "")
    return raw.strip().lower() in {"1", "true", "yes", "on"}


def _validate_parity_scope(failures: List[str]) -> None:
    """Enforce AP/Warehouse-only cutover scope at process startup."""

    # AP auto-post is in scope, but missing configuration must never mean
    # "enabled". Set the process default before server/workflow modules import
    # their feature flags. Controlled UAT may still explicitly set this true.
    os.environ.setdefault("AUTO_POST_ENABLED", "false")

    # This legacy Sales service historically defaulted TRUE when the variable
    # was missing, so require an explicit false rather than treating absence as safe.
    if not _is_explicit_false("AUTO_CREATE_SALES_ORDER_ENABLED"):
        failures.append(
            "  - AUTO_CREATE_SALES_ORDER_ENABLED: must be explicitly false during AP/Warehouse parity"
        )

    for name in (
        "ENABLE_OUT_OF_SCOPE_SALES_ROUTES",
        "SALES_EMAIL_POLLING_ENABLED",
        "BC_SALES_LINK_WRITE_ENABLED",
        "INSIDE_SALES_PILOT_ENABLED",
    ):
        if _is_truthy(name):
            failures.append(
                f"  - {name}: Sales/Inside Sales activation is prohibited during AP/Warehouse parity"
            )


def validate_startup_secrets() -> None:
    """Validate required secrets and parity safety before app initialization."""
    failures: List[str] = []

    for name, bad_defaults, desc in _REQUIRED_SECRETS:
        value = os.environ.get(name, "")
        if value in bad_defaults:
            failures.append(
                f"  - {name}: missing or set to insecure default. ({desc})"
            )

    _validate_parity_scope(failures)

    if failures:
        checklist = "\n".join(failures)
        raise RuntimeError(
            "Startup blocked — required secrets or parity safety settings are invalid:\n"
            f"{checklist}\n\n"
            "Fix backend/.env (or the runtime secret store) and restart. "
            "The AP/Warehouse parity process intentionally fails closed."
        )

    for name, desc in _OPTIONAL_SECRETS:
        if not os.environ.get(name, ""):
            logger.warning(
                "[StartupValidator] Optional secret %s not set — %s",
                name,
                desc,
            )

    logger.info("[StartupValidator] Required secrets and AP/Warehouse parity scope validated")
