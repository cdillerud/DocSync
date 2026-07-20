"""Live SharePoint destination-folder browser for human routing review."""

from __future__ import annotations

from typing import Any, Dict, List
from urllib.parse import quote

import httpx
from fastapi import APIRouter, HTTPException, Query

from deps import get_db

router = APIRouter(prefix="/human-routing-review", tags=["Human Routing Review"])


def _normalize_relative_path(path: str) -> str:
    raw = str(path or "").replace("\\", "/").strip()
    if raw.startswith("/"):
        raise HTTPException(400, "Folder paths must be relative to the configured SharePoint root")
    parts = [part.strip() for part in raw.split("/") if part.strip()]
    if any(part in {".", ".."} for part in parts):
        raise HTTPException(400, "Parent-folder traversal is not allowed")
    return "/".join(parts)


async def _configured_paths() -> List[str]:
    db = get_db()
    rules = await db.sharepoint_folder_rules.find(
        {"is_active": {"$ne": False}}, {"_id": 0}
    ).sort("sort_order", 1).to_list(500)

    if not rules:
        from services.folder_routing_service import get_all_folder_paths
        return sorted(set(get_all_folder_paths()), key=str.lower)

    by_key = {rule.get("folder_key"): rule for rule in rules if rule.get("folder_key")}
    cache: Dict[str, str] = {}

    def full_path(rule: Dict[str, Any], seen: set[str] | None = None) -> str:
        key = rule.get("folder_key") or ""
        if key in cache:
            return cache[key]
        seen = set(seen or set())
        if key in seen:
            return str(rule.get("path") or "").strip("/")
        seen.add(key)
        own = str(rule.get("path") or "").strip().strip("/")
        parent = by_key.get(rule.get("parent_key"))
        value = f"{full_path(parent, seen)}/{own}" if parent and own else own
        cache[key] = value.strip("/")
        return cache[key]

    return sorted(
        {full_path(rule) for rule in rules if full_path(rule)},
        key=str.lower,
    )


def _configured_children(paths: List[str], current_path: str) -> List[Dict[str, Any]]:
    prefix = f"{current_path}/" if current_path else ""
    children: Dict[str, Dict[str, Any]] = {}

    for path in paths:
        normalized = _normalize_relative_path(path)
        if not normalized.lower().startswith(prefix.lower()):
            continue
        remainder = normalized[len(prefix):]
        if not remainder:
            continue
        child_name = remainder.split("/", 1)[0]
        child_path = f"{prefix}{child_name}".strip("/")
        has_children = "/" in remainder or any(
            other.lower().startswith(f"{child_path.lower()}/") for other in paths
        )
        children.setdefault(
            child_path.lower(),
            {
                "id": child_path,
                "name": child_name,
                "path": child_path,
                "child_count": 1 if has_children else 0,
                "has_children": has_children,
                "web_url": "",
            },
        )

    return sorted(children.values(), key=lambda item: item["name"].lower())


async def _resolve_drive(client: httpx.AsyncClient, token: str) -> str:
    from services.sharepoint_service import (
        SHAREPOINT_LIBRARY_NAME,
        SHAREPOINT_SITE_HOSTNAME,
        SHAREPOINT_SITE_PATH,
    )

    headers = {"Authorization": f"Bearer {token}"}
    site_response = await client.get(
        f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_HOSTNAME}:{SHAREPOINT_SITE_PATH}:",
        headers=headers,
    )
    if site_response.status_code in (401, 403):
        raise HTTPException(502, "SharePoint permission denied while resolving the configured site")
    if site_response.status_code != 200 or not site_response.json().get("id"):
        raise HTTPException(502, f"SharePoint site lookup failed (HTTP {site_response.status_code})")

    drives_response = await client.get(
        f"https://graph.microsoft.com/v1.0/sites/{site_response.json()['id']}/drives",
        headers=headers,
    )
    if drives_response.status_code != 200:
        raise HTTPException(502, f"SharePoint library lookup failed (HTTP {drives_response.status_code})")

    drives = drives_response.json().get("value", [])
    drive = next((item for item in drives if item.get("name") == SHAREPOINT_LIBRARY_NAME), None)
    if not drive:
        drive = next(
            (item for item in drives if str(item.get("name", "")).lower() == SHAREPOINT_LIBRARY_NAME.lower()),
            None,
        )
    if not drive:
        drive = next((item for item in drives if item.get("driveType") == "documentLibrary"), None)
    if not drive or not drive.get("id"):
        raise HTTPException(502, f"SharePoint library '{SHAREPOINT_LIBRARY_NAME}' was not found")
    return drive["id"]


@router.get("/sharepoint-folders")
async def browse_sharepoint_folders(
    path: str = Query("", description="Path relative to the configured SharePoint AP root"),
):
    """Browse actual SharePoint folders beneath the protected AP base folder."""
    from services.config_service import get_graph_token
    from services.sharepoint_service import (
        DEMO_MODE,
        GRAPH_CLIENT_ID,
        SHAREPOINT_BASE_FOLDER,
        SHAREPOINT_LIBRARY_NAME,
        SHAREPOINT_SITE_HOSTNAME,
        SHAREPOINT_SITE_PATH,
        SHAREPOINT_TARGET,
    )

    current_path = _normalize_relative_path(path)
    base_folder = _normalize_relative_path(SHAREPOINT_BASE_FOLDER)
    root_label = base_folder.split("/")[-1] if base_folder else SHAREPOINT_LIBRARY_NAME
    common = {
        "current_path": current_path,
        "parent_path": "/".join(current_path.split("/")[:-1]) if current_path else "",
        "root_label": root_label,
        "base_folder": base_folder,
        "site": f"{SHAREPOINT_SITE_HOSTNAME}{SHAREPOINT_SITE_PATH}",
        "library": SHAREPOINT_LIBRARY_NAME,
        "target": SHAREPOINT_TARGET,
    }

    if DEMO_MODE or not GRAPH_CLIENT_ID:
        paths = await _configured_paths()
        return {
            **common,
            "source": "configured_fallback",
            "folders": _configured_children(paths, current_path),
        }

    token = await get_graph_token()
    headers = {"Authorization": f"Bearer {token}"}
    full_path = "/".join(part for part in (base_folder, current_path) if part)

    async with httpx.AsyncClient(timeout=30.0) as client:
        drive_id = await _resolve_drive(client, token)
        if full_path:
            safe_path = quote(full_path, safe="/")
            url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{safe_path}:/children"
        else:
            url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"

        folders: List[Dict[str, Any]] = []
        params = {"$select": "id,name,folder,webUrl", "$top": "200"}
        while url:
            response = await client.get(url, headers=headers, params=params)
            params = None
            if response.status_code == 404:
                raise HTTPException(404, f"SharePoint folder not found: {current_path or root_label}")
            if response.status_code in (401, 403):
                raise HTTPException(502, "SharePoint permission denied while browsing folders")
            if response.status_code != 200:
                raise HTTPException(502, f"SharePoint folder browse failed (HTTP {response.status_code})")

            payload = response.json()
            for item in payload.get("value", []):
                folder = item.get("folder")
                if folder is None:
                    continue
                child_path = "/".join(
                    part for part in (current_path, str(item.get("name", "")).strip()) if part
                )
                count = int(folder.get("childCount") or 0)
                folders.append(
                    {
                        "id": item.get("id", child_path),
                        "name": item.get("name", ""),
                        "path": child_path,
                        "child_count": count,
                        "has_children": count > 0,
                        "web_url": item.get("webUrl", ""),
                    }
                )
            url = payload.get("@odata.nextLink")

    folders.sort(key=lambda item: str(item.get("name", "")).lower())
    return {**common, "source": "sharepoint_graph", "folders": folders}
