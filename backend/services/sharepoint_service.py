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
SHAREPOINT_SITE_HOSTNAME = os.environ.get('SHAREPOINT_SITE_HOSTNAME', 'gamerpackaging.sharepoint.com')
SHAREPOINT_SITE_PATH = os.environ.get('SHAREPOINT_SITE_PATH', '/sites/GPI-DocumentHub-Test')
SHAREPOINT_LIBRARY_NAME = os.environ.get('SHAREPOINT_LIBRARY_NAME', 'Shared Documents')


async def _get_graph_token():
    """Lazy import to avoid circular dependency with server.py."""
    from server import get_graph_token
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

        # Step 3: Upload file
        upload_resp = await c.put(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{folder}/{file_name}:/content",
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

            check_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{current_path}"
            check_resp = await c.get(check_url, headers={"Authorization": f"Bearer {token}"})

            if check_resp.status_code == 404:
                if current_path == part:
                    create_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
                else:
                    parent = "/".join(folder_parts[:folder_parts.index(part)])
                    create_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{parent}:/children"

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
    from services.folder_routing_service import determine_folder_path

    folder_path, routing_reason, routing_details = determine_folder_path(
        doc,
        freight_direction=freight_direction,
        is_international=is_international
    )

    logger.info("[Folder Routing] Doc %s -> %s (reason: %s)",
                doc.get("id", "unknown"), folder_path, routing_reason)

    await ensure_sharepoint_folder_exists(folder_path)

    result = await upload_to_sharepoint(file_content, file_name, folder_path)

    result["folder_path"] = folder_path
    result["routing_reason"] = routing_reason
    result["routing_details"] = routing_details

    return result
