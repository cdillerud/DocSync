"""
GPI Document Hub - SharePoint Service

Extracted from server.py — authoritative implementation of SharePoint operations:
  - upload_to_sharepoint: Upload a file to a SharePoint document library
  - create_sharing_link: Create an organization-scoped sharing link
  - ensure_sharepoint_folder_exists: Create folder hierarchy if missing
  - upload_to_sharepoint_with_routing: Upload with accounting folder routing

All functions fall back to mock behavior in DEMO_MODE or when GRAPH_CLIENT_ID
is not configured.
"""

import os
import uuid
import logging
import httpx
from typing import Dict, Any, Optional

from dotenv import load_dotenv
load_dotenv()

logger = logging.getLogger(__name__)

# ── SharePoint / Graph Config ──
DEMO_MODE = os.environ.get('DEMO_MODE', 'true').lower() == 'true'
GRAPH_CLIENT_ID = os.environ.get('GRAPH_CLIENT_ID', '')

# Single, safe toggle between the test and real production SharePoint
# targets. Defaults to "test" if unset or unrecognized - this is
# deliberate: an accidental blank/typo'd value must never silently fall
# through to writing real documents into the real site. Set explicitly
# via SHAREPOINT_TARGET=production in the environment to go live.
#
# Each individual SHAREPOINT_* var below can still be set explicitly to
# override a single piece (backward compatible), but the normal way to
# flip between test and prod is this one variable.
SHAREPOINT_TARGET = os.environ.get('SHAREPOINT_TARGET', 'test').strip().lower()

_SHAREPOINT_TARGETS = {
    'test': {
        'hostname': 'gamerpackaging.sharepoint.com',
        'site_path': '/sites/GPI-DocumentHub-Test',
        'library_name': 'Shared Documents',
        'base_folder': '',
    },
    'production': {
        # Confirmed 2026-07-08 against live Square9 GlobalCapture "Office
        # 365 Connect" node configs (3 separate nodes checked).
        'hostname': 'gamerpackaging1.sharepoint.com',
        'site_path': '/sites/GamerAccounting',
        'library_name': 'Shared Documents',
        'base_folder': 'General/Accounting/Accounts Payable/Temp Folder',
    },
}

if SHAREPOINT_TARGET not in _SHAREPOINT_TARGETS:
    logger.warning(
        "[SharePoint] Unrecognized SHAREPOINT_TARGET=%r - falling back to 'test' for safety. "
        "Valid values: %s", SHAREPOINT_TARGET, list(_SHAREPOINT_TARGETS.keys())
    )
    SHAREPOINT_TARGET = 'test'

_target_config = _SHAREPOINT_TARGETS[SHAREPOINT_TARGET]

SHAREPOINT_SITE_HOSTNAME = os.environ.get('SHAREPOINT_SITE_HOSTNAME') or _target_config['hostname']
SHAREPOINT_SITE_PATH = os.environ.get('SHAREPOINT_SITE_PATH') or _target_config['site_path']
SHAREPOINT_LIBRARY_NAME = os.environ.get('SHAREPOINT_LIBRARY_NAME') or _target_config['library_name']
SHAREPOINT_BASE_FOLDER = os.environ.get('SHAREPOINT_BASE_FOLDER')
if SHAREPOINT_BASE_FOLDER is None:
    SHAREPOINT_BASE_FOLDER = _target_config['base_folder']

logger.warning(
    "[SharePoint] ACTIVE TARGET: %s -> %s%s (base folder: %r)",
    SHAREPOINT_TARGET.upper(), SHAREPOINT_SITE_HOSTNAME, SHAREPOINT_SITE_PATH,
    SHAREPOINT_BASE_FOLDER,
)


async def _get_graph_token():
    """Import from config_service to avoid circular dependency with server.py."""
    from services.config_service import get_graph_token
    return await get_graph_token()


async def upload_to_sharepoint(file_content: bytes, file_name: str, folder: str):
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        item_id = str(uuid.uuid4())
        drive_id = "mock-drive-" + str(uuid.uuid4())[:8]
        return {
            "drive_id": drive_id, "item_id": item_id,
            "web_url": f"https://{SHAREPOINT_SITE_HOSTNAME}{SHAREPOINT_SITE_PATH}/{SHAREPOINT_LIBRARY_NAME}/{folder}/{file_name}",
            "name": file_name
        }
    token = await _get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        # Step 1: Resolve site
        site_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_HOSTNAME}:{SHAREPOINT_SITE_PATH}:",
            headers={"Authorization": f"Bearer {token}"})
        site_data = site_resp.json()
        if site_resp.status_code in (401, 403):
            raise Exception(
                f"Graph API permission denied (HTTP {site_resp.status_code}). "
                f"The app registration needs 'Sites.ReadWrite.All' (Application) permission with admin consent. "
                f"Go to Azure Portal > App Registrations > {GRAPH_CLIENT_ID} > API Permissions > Add 'Sites.ReadWrite.All' > Grant admin consent."
            )
        if site_resp.status_code == 404 or "id" not in site_data:
            error = site_data.get("error", {})
            raise Exception(
                f"SharePoint site not found (HTTP {site_resp.status_code}). "
                f"Check SHAREPOINT_SITE_HOSTNAME='{SHAREPOINT_SITE_HOSTNAME}' and SHAREPOINT_SITE_PATH='{SHAREPOINT_SITE_PATH}'. "
                f"Detail: {error.get('message', error.get('code', 'unknown'))}"
            )
        if "id" not in site_data:
            raise Exception(f"Unexpected Graph response: {str(site_data)[:200]}")
        site_id = site_data["id"]

        # Step 2: Resolve drive
        drives_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
            headers={"Authorization": f"Bearer {token}"})
        drives_data = drives_resp.json()
        if drives_resp.status_code in (401, 403):
            raise Exception(f"Graph permission denied listing drives (HTTP {drives_resp.status_code}). Ensure 'Sites.ReadWrite.All' permission is granted.")
        if "error" in drives_data:
            raise Exception(f"Drive list error: {drives_data['error'].get('message', drives_data['error'])}")
        drives = drives_data.get("value", [])
        lib_name = SHAREPOINT_LIBRARY_NAME
        drive = next((d for d in drives if d["name"] == lib_name), None)
        if not drive:
            drive = next((d for d in drives if d["name"].lower() == lib_name.lower()), None)
        if not drive:
            alt_names = {"documents": "shared documents", "shared documents": "documents"}
            alt = alt_names.get(lib_name.lower())
            if alt:
                drive = next((d for d in drives if d["name"].lower() == alt), None)
        if not drive:
            drive = next((d for d in drives if d.get("driveType") == "documentLibrary"), None)
        if not drive:
            raise Exception(f"Document library '{SHAREPOINT_LIBRARY_NAME}' not found. Available: {[d['name'] for d in drives]}")
        drive_id = drive["id"]

        # Step 3: Upload file (URL-encode path components to handle # and special chars)
        from urllib.parse import quote
        safe_folder = quote(folder, safe="/")
        safe_name = quote(file_name, safe="")
        upload_resp = await c.put(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{safe_folder}/{safe_name}:/content",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
            content=file_content)
        item = upload_resp.json()
        if upload_resp.status_code in (401, 403):
            raise Exception(f"Upload permission denied (HTTP {upload_resp.status_code}). Ensure app has 'Files.ReadWrite.All' or 'Sites.ReadWrite.All'.")
        if "id" not in item:
            error = item.get("error", {})
            raise Exception(f"Upload failed (HTTP {upload_resp.status_code}): {error.get('message', error.get('code', item))}")
        return {"drive_id": drive_id, "item_id": item["id"], "web_url": item.get("webUrl", ""), "name": file_name}


async def create_sharing_link(drive_id: str, item_id: str):
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return f"https://{SHAREPOINT_SITE_HOSTNAME}/:b:/s/GPI-DocumentHub-Test/{item_id[:8]}"
    token = await _get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.post(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/createLink",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"type": "view", "scope": "organization"})
        data = resp.json()
        if "error" in data:
            raise Exception(f"Sharing link error: {data['error'].get('message', data['error'])}")
        return data.get("link", {}).get("webUrl", "")


async def ensure_sharepoint_folder_exists(folder_path: str) -> bool:
    """Ensure a folder exists in SharePoint, creating it and any parent folders if needed."""
    if DEMO_MODE or not GRAPH_CLIENT_ID:
        return True

    token = await _get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        site_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{SHAREPOINT_SITE_HOSTNAME}:{SHAREPOINT_SITE_PATH}:",
            headers={"Authorization": f"Bearer {token}"})
        if site_resp.status_code != 200:
            logger.warning("Could not resolve SharePoint site for folder creation")
            return False
        site_id = site_resp.json()["id"]

        drives_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
            headers={"Authorization": f"Bearer {token}"})
        drives = drives_resp.json().get("value", [])
        lib_name = SHAREPOINT_LIBRARY_NAME
        drive = next((d for d in drives if d["name"] == lib_name), None)
        if not drive:
            drive = next((d for d in drives if d["name"].lower() == lib_name.lower()), None)
        if not drive:
            alt_names = {"documents": "shared documents", "shared documents": "documents"}
            alt = alt_names.get(lib_name.lower())
            if alt:
                drive = next((d for d in drives if d["name"].lower() == alt), None)
        if not drive:
            drive = next((d for d in drives if d.get("driveType") == "documentLibrary"), None)
        if not drive:
            return False
        drive_id = drive["id"]

        folder_parts = folder_path.split("/")
        current_path = ""

        for part in folder_parts:
            if not part:
                continue
            current_path = f"{current_path}/{part}" if current_path else part

            from urllib.parse import quote
            safe_path = quote(current_path, safe="/")
            check_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{safe_path}"
            check_resp = await c.get(check_url, headers={"Authorization": f"Bearer {token}"})

            if check_resp.status_code == 404:
                if current_path == part:
                    create_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
                else:
                    parent = "/".join(folder_parts[:folder_parts.index(part)])
                    safe_parent = quote(parent, safe="/")
                    create_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{safe_parent}:/children"

                create_resp = await c.post(
                    create_url,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"name": part, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"}
                )

                if create_resp.status_code not in (200, 201, 409):
                    logger.warning("Failed to create folder %s: %s", current_path, create_resp.text[:200])
                else:
                    logger.info("Created SharePoint folder: %s", current_path)

        return True


async def upload_to_sharepoint_with_routing(
    file_content: bytes,
    file_name: str,
    doc: Dict[str, Any],
    freight_direction: Optional[str] = None,
    is_international: bool = False
) -> Dict[str, Any]:
    """Upload a file to SharePoint using accounting folder routing logic."""
    from services.folder_routing_service import route_with_feedback

    folder_path, routing_reason, routing_details = await route_with_feedback(
        doc,
        freight_direction=freight_direction,
        is_international=is_international
    )

    # Apply the locked production base path once, here. folder_path from
    # the routing service is always relative to this base (see
    # SHAREPOINT_BASE_FOLDER above and folder_routing_service.py's
    # AP_STAGING_FOLDER/AP_LANE_REVIEW_FOLDER comments).
    full_folder_path = (
        f"{SHAREPOINT_BASE_FOLDER}/{folder_path}" if folder_path
        else SHAREPOINT_BASE_FOLDER
    )

    logger.info("[Folder Routing] Doc %s -> %s (reason: %s)",
                doc.get("id", "unknown"), full_folder_path, routing_reason)

    await ensure_sharepoint_folder_exists(full_folder_path)

    result = await upload_to_sharepoint(file_content, file_name, full_folder_path)

    result["folder_path"] = full_folder_path
    result["routing_reason"] = routing_reason
    result["routing_details"] = routing_details

    return result
