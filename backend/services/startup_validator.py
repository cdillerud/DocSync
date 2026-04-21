"""
Startup secret validation — fail loudly if the environment is misconfigured.

Addresses Finding #10 from the 2026-04 engineering review: the pre-fix code
provided permissive ``os.environ.get("X", "")`` defaults for secrets, which
meant a missing/misset env produced silent auth bypass or opaque 500s at
request time. This module runs once at FastAPI startup and raises a clear
``RuntimeError`` (crashing the process loud) if any required secret is
missing or matches a known-insecure default.

Only secrets that MUST be set in every deployment are validated here.
BC/Graph credentials that may be optional in dev are checked but emit
warnings rather than crashing.
"""

from __future__ import annotations

import logging
import os
from typing import List, Tuple

logger = logging.getLogger(__name__)


# (env_var_name, insecure_defaults_to_refuse, description)
_REQUIRED_SECRETS: List[Tuple[str, set, str]] = [
    ("JWT_SECRET",
     {"", "gpi-hub-secret-key", "changeme", "secret", "test"},
     "JWT signing key — must be a random 64+ char string"),
    ("ADMIN_EMAIL",
     {"", "admin@example.com"},
     "Seed admin account email"),
    ("ADMIN_PASSWORD",
     {"", "admin", "admin123", "changeme", "password"},
     "Seed admin account password — change on first deploy"),
    ("MONGO_URL",
     {""},
     "MongoDB connection string"),
]

# Secrets that SHOULD be set in production but whose absence is tolerated
# in dev. A warning is emitted instead of crashing.
_OPTIONAL_SECRETS: List[Tuple[str, str]] = [
    ("BC_CLIENT_ID", "Business Central app registration — required for live BC writes"),
    ("BC_CLIENT_SECRET", "Business Central app registration secret"),
    ("BC_TENANT_ID", "BC Azure tenant"),
    ("GRAPH_CLIENT_ID", "Microsoft Graph app registration — required for email/SharePoint"),
    ("GRAPH_CLIENT_SECRET", "Graph app secret"),
    ("FRONTEND_URL", "Explicit frontend origin for CORS (defaults to localhost)"),
]


def validate_startup_secrets() -> None:
    """Validate required env vars. Raises RuntimeError on any failure.

    Call this from the FastAPI startup event BEFORE anything else that
    touches config. The intent is that a misconfigured deploy fails fast
    and visibly — not silently at the first authenticated request.
    """
    failures: List[str] = []
    for name, bad_defaults, desc in _REQUIRED_SECRETS:
        value = os.environ.get(name, "")
        if value in bad_defaults:
            failures.append(
                f"  - {name}: missing or set to insecure default. ({desc})"
            )

    if failures:
        checklist = "\n".join(failures)
        raise RuntimeError(
            "Startup blocked — required secrets missing or insecure:\n"
            f"{checklist}\n\n"
            "Fix the env (or docker-compose.yml) and restart. "
            "This check exists because a prior silent-default allowed the "
            "server to run with a publicly-known JWT signing key."
        )

    for name, desc in _OPTIONAL_SECRETS:
        if not os.environ.get(name, ""):
            logger.warning(
                "[StartupValidator] Optional secret %s not set — %s",
                name, desc,
            )

    logger.info("[StartupValidator] All required secrets present")
