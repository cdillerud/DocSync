"""
Startup secret and cutover-safety validation — fail loudly if the environment
is misconfigured.

The Square9 parity phase is AP/Warehouse only. In addition to refusing missing
or insecure secrets, startup refuses configuration that can activate Sales,
Inside Sales, or the legacy Graph webhook during this cutover. Non-demo runtime
also requires the dedicated Business Central -> Hub machine credential.
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
    ("TENANT_ID", "Microsoft Entra tenant used by Business Central and Graph"),
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

    os.environ.setdefault("AUTO_POST_ENABLED", "false")

    if not _is_explicit_false("AUTO_CREATE_SALES_ORDER_ENABLED"):
        failures.append(
            "  - AUTO_CREATE_SALES_ORDER_ENABLED: must be explicitly false during AP/Warehouse parity"
        )

    for name in (
        "ENABLE_OUT_OF_SCOPE_SALES_ROUTES",
        "SALES_EMAIL_POLLING_ENABLED",
        "BC_SALES_LINK_WRITE_ENABLED",
        "INSIDE_SALES_PILOT_ENABLED",
        "GRAPH_WEBHOOK_ENABLED",
    ):
        if _is_truthy(name):
            reason = (
                "legacy Graph webhook is prohibited during AP/Warehouse parity"
                if name == "GRAPH_WEBHOOK_ENABLED"
                else "Sales/Inside Sales activation is prohibited during AP/Warehouse parity"
            )
            failures.append(f"  - {name}: {reason}")


def _validate_machine_credential(failures: List[str]) -> None:
    """Require a strong BC->Hub key in every non-demo runtime."""
    if _is_truthy("DEMO_MODE"):
        return

    value = os.environ.get("BC_HUB_API_KEY", "")
    insecure = {"", "changeme", "secret", "test", "gpi-hub-key", "gpi-document-hub-secret"}
    if value.strip().lower() in insecure or len(value) < 32:
        failures.append(
            "  - BC_HUB_API_KEY: non-demo runtime requires a random machine credential of at least 32 characters"
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
    _validate_machine_credential(failures)

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
