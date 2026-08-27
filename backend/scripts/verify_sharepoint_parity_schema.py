#!/usr/bin/env python3
"""Read-only verification of the SharePoint parity metadata schema.

Purpose
-------
Prove that the active GPI Document Hub SharePoint library exposes every list
column written by ``sharepoint_service.write_sharepoint_parity_metadata`` with a
compatible Graph field type. This script performs GET requests only.

Run from ``backend`` in the same environment/configuration as the service:

    python scripts/verify_sharepoint_parity_schema.py

Optional target override:

    SHAREPOINT_TARGET=test python scripts/verify_sharepoint_parity_schema.py

Exit code 0 means the required contract is present and type-compatible.
Exit code 1 means at least one required column is missing/incompatible or the
site/library cannot be resolved.
"""

from __future__ import annotations

import asyncio
import os
import sys
from typing import Any, Dict, Iterable, Tuple

import httpx

# Allow execution from backend/ or repository root.
BACKEND_DIR = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
if BACKEND_DIR not in sys.path:
    sys.path.insert(0, BACKEND_DIR)

from services.config_service import get_graph_token  # noqa: E402


_TARGETS = {
    "test": {
        "hostname": "gamerpackaging1.sharepoint.com",
        "site_path": "/sites/GPI-DocumentHub-Test",
        "library_name": "Shared Documents",
    },
    "production": {
        "hostname": "gamerpackaging1.sharepoint.com",
        "site_path": "/sites/GamerAccounting",
        "library_name": "Shared Documents",
    },
}

# Graph column facets accepted for each internal column name. Most metadata is
# intentionally text because identifiers/status/match evidence are contracts,
# not arithmetic values. Two fields have stronger types.
_REQUIRED: Dict[str, Tuple[str, ...]] = {
    "GPI_SourceTableID": ("number", "text"),
    "GPI_SourceSystemId": ("text",),
    "GPI_SourceDocumentType": ("text",),
    "GPI_SourceDocumentNo": ("text",),
    "GPI_SourcePartyType": ("text",),
    "GPI_SourcePartyNo": ("text",),
    "GPI_OriginalFileName": ("text",),
    "GPI_SharePointFileName": ("text",),
    "GPI_SharePointPath": ("text",),
    "GPI_SharePointURL": ("text", "hyperlinkOrPicture"),
    "GPI_Status": ("text", "choice"),
    "GPI_MatchStatus": ("text", "choice"),
    "GPI_MatchMethod": ("text",),
    "GPI_MatchConfidence": ("number", "text"),
    "GPI_Candidates": ("text",),
    "ImportReady": ("boolean",),
}


def _column_facet(column: Dict[str, Any]) -> str:
    for facet in (
        "text",
        "number",
        "boolean",
        "choice",
        "hyperlinkOrPicture",
        "dateTime",
        "currency",
        "lookup",
        "personOrGroup",
    ):
        if column.get(facet) is not None:
            return facet
    return "unknown"


def _index_columns(columns: Iterable[Dict[str, Any]]) -> Dict[str, Dict[str, Any]]:
    indexed: Dict[str, Dict[str, Any]] = {}
    for column in columns:
        # Graph's `name` is the internal field name used in listItem/fields PATCH.
        name = str(column.get("name") or "").strip()
        if name:
            indexed[name.casefold()] = column
    return indexed


async def _get_json(client: httpx.AsyncClient, url: str, token: str) -> Dict[str, Any]:
    response = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    try:
        data = response.json()
    except Exception:
        data = {}
    if response.status_code >= 400:
        detail = data.get("error", {}).get("message") if isinstance(data, dict) else None
        raise RuntimeError(f"GET {url} -> HTTP {response.status_code}: {detail or response.text[:300]}")
    return data


async def verify() -> int:
    target_name = os.environ.get("SHAREPOINT_TARGET", "test").strip().lower()
    if target_name not in _TARGETS:
        print(f"FAIL: unsupported SHAREPOINT_TARGET={target_name!r}")
        return 1

    target = _TARGETS[target_name]
    hostname = os.environ.get("SHAREPOINT_SITE_HOSTNAME") or target["hostname"]
    site_path = os.environ.get("SHAREPOINT_SITE_PATH") or target["site_path"]
    library_name = os.environ.get("SHAREPOINT_LIBRARY_NAME") or target["library_name"]

    print("=" * 88)
    print("SHAREPOINT PARITY SCHEMA VERIFICATION — READ ONLY")
    print("=" * 88)
    print(f"Target        : {target_name}")
    print(f"Site          : https://{hostname}{site_path}")
    print(f"Library       : {library_name}")
    print("Writes        : NONE")
    print()

    token = await get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as client:
        site = await _get_json(
            client,
            f"https://graph.microsoft.com/v1.0/sites/{hostname}:{site_path}:",
            token,
        )
        site_id = site.get("id")
        if not site_id:
            raise RuntimeError("Resolved SharePoint site has no id")

        drives = await _get_json(
            client,
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
            token,
        )
        wanted = library_name.casefold()
        drive = next(
            (d for d in drives.get("value", []) if str(d.get("name") or "").casefold() == wanted),
            None,
        )
        if drive is None and wanted == "shared documents":
            drive = next(
                (d for d in drives.get("value", []) if str(d.get("name") or "").casefold() == "documents"),
                None,
            )
        if drive is None:
            available = [d.get("name") for d in drives.get("value", [])]
            raise RuntimeError(f"Library {library_name!r} not found; available={available}")

        drive_id = drive["id"]
        list_info = await _get_json(
            client,
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/list",
            token,
        )
        list_id = list_info.get("id")
        if not list_id:
            raise RuntimeError("Document library did not expose a backing list id")

        columns_data = await _get_json(
            client,
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/columns?$top=999",
            token,
        )

    columns = _index_columns(columns_data.get("value", []))
    failures = 0

    print(f"Resolved site : {site_id}")
    print(f"Resolved drive: {drive_id}")
    print(f"Backing list  : {list_id}")
    print()
    print(f"{'Column':32} {'Facet':20} {'Status':10} Details")
    print("-" * 88)

    for required_name, allowed_facets in _REQUIRED.items():
        column = columns.get(required_name.casefold())
        if column is None:
            print(f"{required_name:32} {'-':20} {'FAIL':10} missing internal column")
            failures += 1
            continue

        facet = _column_facet(column)
        if facet not in allowed_facets:
            print(
                f"{required_name:32} {facet:20} {'FAIL':10} "
                f"expected one of {', '.join(allowed_facets)}"
            )
            failures += 1
            continue

        print(
            f"{required_name:32} {facet:20} {'PASS':10} "
            f"display={column.get('displayName')!r}"
        )

    print("-" * 88)
    if failures:
        print(f"RESULT: FAIL — {failures} required SharePoint parity column(s) missing/incompatible")
        return 1

    print(f"RESULT: PASS — all {len(_REQUIRED)} required parity columns are present and compatible")
    return 0


async def _main() -> int:
    try:
        return await verify()
    except Exception as exc:
        print(f"RESULT: FAIL — {exc}")
        return 1


if __name__ == "__main__":
    raise SystemExit(asyncio.run(_main()))
