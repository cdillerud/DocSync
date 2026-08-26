"""Fail-closed SharePoint production write protection.

The parity branch is allowed to read Production evidence, but SharePoint writes
must remain on the UAT/test site until cutover is explicitly authorized.
"""

from __future__ import annotations

import os
from typing import Optional


PRODUCTION_SITE_PATH = "/sites/GamerAccounting"


class SharePointProductionWriteBlocked(RuntimeError):
    """Raised before any network side effect when production writes are blocked."""


def _env_bool(name: str, default: bool) -> bool:
    raw = os.environ.get(name)
    if raw is None:
        return default
    return raw.strip().lower() not in {"0", "false", "no", "off"}


def is_production_sharepoint_target(
    *,
    target: Optional[str] = None,
    site_path: Optional[str] = None,
) -> bool:
    """Identify Production from either the named target or effective site path.

    Checking the effective path prevents a misleading ``SHAREPOINT_TARGET=test``
    combined with a manual ``SHAREPOINT_SITE_PATH=/sites/GamerAccounting`` from
    bypassing the interlock.
    """
    effective_target = str(
        target if target is not None else os.environ.get("SHAREPOINT_TARGET", "test")
    ).strip().lower()
    effective_path = str(
        site_path if site_path is not None else os.environ.get("SHAREPOINT_SITE_PATH", "")
    ).strip().rstrip("/").lower()

    return (
        effective_target == "production"
        or effective_path == PRODUCTION_SITE_PATH.lower()
    )


def check_sharepoint_write_protection(
    operation: str,
    *,
    target: Optional[str] = None,
    site_path: Optional[str] = None,
    block_production_writes: Optional[bool] = None,
) -> None:
    """Raise before a SharePoint Production write unless explicitly unblocked."""
    blocked = (
        _env_bool("SHAREPOINT_BLOCK_PRODUCTION_WRITES", True)
        if block_production_writes is None
        else bool(block_production_writes)
    )
    if blocked and is_production_sharepoint_target(target=target, site_path=site_path):
        raise SharePointProductionWriteBlocked(
            "SharePoint Production write blocked for "
            f"{operation!r}. Keep SHAREPOINT_BLOCK_PRODUCTION_WRITES=true during "
            "parity/UAT. Cutover requires explicit authorization and setting it false."
        )


__all__ = [
    "PRODUCTION_SITE_PATH",
    "SharePointProductionWriteBlocked",
    "is_production_sharepoint_target",
    "check_sharepoint_write_protection",
]
