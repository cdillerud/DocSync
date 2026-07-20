#!/usr/bin/env python3
"""Mirror the production Square9/AP SharePoint folder tree into the test site.

Safe defaults:
- Source is read-only: GamerAccounting / Shared Documents /
  General/Accounting/Accounts Payable/Temp Folder
- Target is GPI-DocumentHub-Test / Documents / Temp Folder
- Without --apply this only inventories and reports differences.
- --apply creates the target root and missing folders. It never deletes files or folders.
- Test-only folders under the target root are reported for later review.

Run inside the backend container so the existing Graph credentials and token helper are used:

    python scripts/sync_test_ap_folders_from_production.py
    python scripts/sync_test_ap_folders_from_production.py --apply
"""

from __future__ import annotations

import argparse
import asyncio
import json
import sys
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Iterable, List, Optional, Set, Tuple
from urllib.parse import quote

import httpx

# Make /app/backend-style imports work when the script is launched directly.
SCRIPT_DIR = Path(__file__).resolve().parent
BACKEND_DIR = SCRIPT_DIR.parent
if str(BACKEND_DIR) not in sys.path:
    sys.path.insert(0, str(BACKEND_DIR))

from services.config_service import get_graph_token  # noqa: E402


HOSTNAME = "gamerpackaging1.sharepoint.com"
SOURCE_SITE_PATH = "/sites/GamerAccounting"
SOURCE_LIBRARY_CANDIDATES = ("Shared Documents", "Documents")
SOURCE_BASE_FOLDER = "General/Accounting/Accounts Payable/Temp Folder"

TARGET_SITE_PATH = "/sites/GPI-DocumentHub-Test"
TARGET_LIBRARY_CANDIDATES = ("Documents", "Shared Documents")
TARGET_BASE_FOLDER = "Temp Folder"

GRAPH_ROOT = "https://graph.microsoft.com/v1.0"


@dataclass(frozen=True)
class DriveLocation:
    site_path: str
    site_id: str
    drive_id: str
    drive_name: str
    base_folder: str


class GraphFailure(RuntimeError):
    pass


def normalize_path(value: str) -> str:
    parts = [part.strip() for part in str(value or "").replace("\\", "/").split("/") if part.strip()]
    if any(part in {".", ".."} for part in parts):
        raise ValueError(f"Unsafe path: {value!r}")
    return "/".join(parts)


def path_key(value: str) -> str:
    return normalize_path(value).casefold()


def parent_path(value: str) -> str:
    normalized = normalize_path(value)
    return "/".join(normalized.split("/")[:-1])


def leaf_name(value: str) -> str:
    normalized = normalize_path(value)
    return normalized.split("/")[-1] if normalized else ""


async def request_json(
    client: httpx.AsyncClient,
    method: str,
    url: str,
    token: str,
    *,
    expected: Iterable[int] = (200,),
    json_body: Optional[Dict] = None,
    params: Optional[Dict] = None,
) -> Dict:
    response = await client.request(
        method,
        url,
        headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
        json=json_body,
        params=params,
    )
    if response.status_code not in set(expected):
        detail = response.text[:1000]
        raise GraphFailure(f"{method} {url} -> HTTP {response.status_code}: {detail}")
    if not response.content:
        return {}
    return response.json()


async def resolve_location(
    client: httpx.AsyncClient,
    token: str,
    *,
    site_path: str,
    library_candidates: Tuple[str, ...],
    base_folder: str,
) -> DriveLocation:
    site = await request_json(
        client,
        "GET",
        f"{GRAPH_ROOT}/sites/{HOSTNAME}:{site_path}:",
        token,
    )
    site_id = site.get("id")
    if not site_id:
        raise GraphFailure(f"No site id returned for {site_path}")

    payload = await request_json(client, "GET", f"{GRAPH_ROOT}/sites/{site_id}/drives", token)
    drives = payload.get("value", [])
    drive = None
    for candidate in library_candidates:
        drive = next((item for item in drives if str(item.get("name", "")).casefold() == candidate.casefold()), None)
        if drive:
            break
    if not drive:
        drive = next((item for item in drives if item.get("driveType") == "documentLibrary"), None)
    if not drive or not drive.get("id"):
        names = [item.get("name") for item in drives]
        raise GraphFailure(f"No usable document library found at {site_path}. Available: {names}")

    return DriveLocation(
        site_path=site_path,
        site_id=site_id,
        drive_id=drive["id"],
        drive_name=drive.get("name", ""),
        base_folder=normalize_path(base_folder),
    )


async def get_item_by_path(
    client: httpx.AsyncClient,
    token: str,
    drive_id: str,
    path: str,
) -> Optional[Dict]:
    normalized = normalize_path(path)
    if not normalized:
        return await request_json(client, "GET", f"{GRAPH_ROOT}/drives/{drive_id}/root", token)
    safe_path = quote(normalized, safe="/")
    response = await client.get(
        f"{GRAPH_ROOT}/drives/{drive_id}/root:/{safe_path}",
        headers={"Authorization": f"Bearer {token}"},
        params={"$select": "id,name,folder,parentReference,webUrl"},
    )
    if response.status_code == 404:
        return None
    if response.status_code != 200:
        raise GraphFailure(f"GET item {normalized} -> HTTP {response.status_code}: {response.text[:1000]}")
    return response.json()


async def list_child_folders(
    client: httpx.AsyncClient,
    token: str,
    drive_id: str,
    folder_path: str,
) -> List[Dict]:
    normalized = normalize_path(folder_path)
    if normalized:
        safe_path = quote(normalized, safe="/")
        url = f"{GRAPH_ROOT}/drives/{drive_id}/root:/{safe_path}:/children"
    else:
        url = f"{GRAPH_ROOT}/drives/{drive_id}/root/children"

    folders: List[Dict] = []
    params: Optional[Dict] = {"$select": "id,name,folder,webUrl", "$top": "200"}
    while url:
        payload = await request_json(client, "GET", url, token, params=params)
        params = None
        for item in payload.get("value", []):
            if item.get("folder") is not None:
                folders.append(item)
        url = payload.get("@odata.nextLink")
    folders.sort(key=lambda item: str(item.get("name", "")).casefold())
    return folders


async def inventory_tree(
    client: httpx.AsyncClient,
    token: str,
    location: DriveLocation,
) -> Dict[str, Dict]:
    root_item = await get_item_by_path(client, token, location.drive_id, location.base_folder)
    if root_item is None:
        return {}

    inventory: Dict[str, Dict] = {}
    queue: List[str] = [""]
    while queue:
        relative_parent = queue.pop(0)
        absolute_parent = "/".join(
            part for part in (location.base_folder, relative_parent) if part
        )
        children = await list_child_folders(client, token, location.drive_id, absolute_parent)
        for item in children:
            relative_path = "/".join(
                part for part in (relative_parent, str(item.get("name", "")).strip()) if part
            )
            inventory[path_key(relative_path)] = {
                "path": relative_path,
                "id": item.get("id"),
                "name": item.get("name", ""),
                "child_count": int((item.get("folder") or {}).get("childCount") or 0),
                "web_url": item.get("webUrl", ""),
            }
            queue.append(relative_path)
    return inventory


async def ensure_folder_path(
    client: httpx.AsyncClient,
    token: str,
    drive_id: str,
    path: str,
) -> List[str]:
    normalized = normalize_path(path)
    if not normalized:
        return []

    created: List[str] = []
    current = ""
    parent_item = await get_item_by_path(client, token, drive_id, "")
    if not parent_item or not parent_item.get("id"):
        raise GraphFailure("Could not resolve target drive root")

    for part in normalized.split("/"):
        current = "/".join(piece for piece in (current, part) if piece)
        existing = await get_item_by_path(client, token, drive_id, current)
        if existing:
            parent_item = existing
            continue

        parent = parent_path(current)
        parent_item = await get_item_by_path(client, token, drive_id, parent)
        if not parent_item or not parent_item.get("id"):
            raise GraphFailure(f"Could not resolve parent folder for {current}")

        created_item = await request_json(
            client,
            "POST",
            f"{GRAPH_ROOT}/drives/{drive_id}/items/{parent_item['id']}/children",
            token,
            expected=(200, 201),
            json_body={
                "name": part,
                "folder": {},
                "@microsoft.graph.conflictBehavior": "fail",
            },
        )
        parent_item = created_item
        created.append(current)
    return created


def render_report(
    source: DriveLocation,
    target: DriveLocation,
    source_inventory: Dict[str, Dict],
    target_inventory: Dict[str, Dict],
) -> Dict:
    source_keys: Set[str] = set(source_inventory)
    target_keys: Set[str] = set(target_inventory)
    missing_keys = sorted(source_keys - target_keys, key=lambda key: source_inventory[key]["path"].casefold())
    extra_keys = sorted(target_keys - source_keys, key=lambda key: target_inventory[key]["path"].casefold())
    matching_keys = source_keys & target_keys

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source": {
            "site": source.site_path,
            "library": source.drive_name,
            "base_folder": source.base_folder,
            "folder_count": len(source_inventory),
        },
        "target": {
            "site": target.site_path,
            "library": target.drive_name,
            "base_folder": target.base_folder,
            "folder_count": len(target_inventory),
        },
        "matching_count": len(matching_keys),
        "missing_in_test": [source_inventory[key]["path"] for key in missing_keys],
        "test_only": [target_inventory[key]["path"] for key in extra_keys],
    }


async def run(args: argparse.Namespace) -> int:
    token = await get_graph_token()
    if not token:
        raise GraphFailure("Could not obtain Microsoft Graph token")

    async with httpx.AsyncClient(timeout=45.0) as client:
        source = await resolve_location(
            client,
            token,
            site_path=SOURCE_SITE_PATH,
            library_candidates=SOURCE_LIBRARY_CANDIDATES,
            base_folder=SOURCE_BASE_FOLDER,
        )
        target = await resolve_location(
            client,
            token,
            site_path=TARGET_SITE_PATH,
            library_candidates=TARGET_LIBRARY_CANDIDATES,
            base_folder=args.target_base,
        )

        source_root = await get_item_by_path(client, token, source.drive_id, source.base_folder)
        if source_root is None:
            raise GraphFailure(f"Production source folder does not exist: {source.base_folder}")

        source_inventory = await inventory_tree(client, token, source)
        target_inventory = await inventory_tree(client, token, target)
        before_report = render_report(source, target, source_inventory, target_inventory)

        print(json.dumps({"phase": "before", **before_report}, indent=2))

        if not args.apply:
            print("\nDRY RUN ONLY. Re-run with --apply to create the missing test folders.")
            return 0

        created: List[str] = []
        created.extend(await ensure_folder_path(client, token, target.drive_id, target.base_folder))

        missing_paths = before_report["missing_in_test"]
        for relative_path in sorted(missing_paths, key=lambda value: (value.count("/"), value.casefold())):
            absolute_target_path = "/".join(
                part for part in (target.base_folder, relative_path) if part
            )
            created.extend(await ensure_folder_path(client, token, target.drive_id, absolute_target_path))

        target_inventory_after = await inventory_tree(client, token, target)
        after_report = render_report(source, target, source_inventory, target_inventory_after)
        output = {
            "phase": "after",
            "created_count": len(created),
            "created_paths": created,
            **after_report,
        }
        print(json.dumps(output, indent=2))

        if after_report["missing_in_test"]:
            print("\nERROR: Some production folders are still missing from test.", file=sys.stderr)
            return 2
        if after_report["test_only"]:
            print(
                "\nNOTE: Test-only folders were preserved and reported. "
                "Nothing was deleted or moved.",
                file=sys.stderr,
            )
        return 0


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Create the target Temp Folder and any production folders missing from test.",
    )
    parser.add_argument(
        "--target-base",
        default=TARGET_BASE_FOLDER,
        help=f"Target folder in the test library (default: {TARGET_BASE_FOLDER!r}).",
    )
    return parser.parse_args()


if __name__ == "__main__":
    try:
        raise SystemExit(asyncio.run(run(parse_args())))
    except (GraphFailure, ValueError) as error:
        print(f"ERROR: {error}", file=sys.stderr)
        raise SystemExit(1)
