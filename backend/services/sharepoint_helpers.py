"""
GPI Document Hub - SharePoint Helpers

SharePoint file upload, folder creation, and sharing link management.
Extracted from server.py during Architecture Hardening pass.

Dependencies:
  - deps: config vars (DEMO_MODE, GRAPH_CLIENT_ID, SHAREPOINT_*)
  - services.graph_access: get_graph_token()
"""

import logging
import uuid

import httpx

import deps
from services.graph_access import get_graph_token

logger = logging.getLogger(__name__)


async def upload_to_sharepoint(file_content: bytes, file_name: str, folder: str) -> dict:
    """Upload a file to SharePoint via the Graph API."""
    if deps.DEMO_MODE or not deps.GRAPH_CLIENT_ID:
        item_id = str(uuid.uuid4())
        drive_id = "mock-drive-" + str(uuid.uuid4())[:8]
        return {
            "drive_id": drive_id,
            "item_id": item_id,
            "web_url": f"https://{deps.SHAREPOINT_SITE_HOSTNAME}{deps.SHAREPOINT_SITE_PATH}/{deps.SHAREPOINT_LIBRARY_NAME}/{folder}/{file_name}",
            "name": file_name,
        }
    token = await get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        # Step 1: Resolve site
        site_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{deps.SHAREPOINT_SITE_HOSTNAME}:{deps.SHAREPOINT_SITE_PATH}:",
            headers={"Authorization": f"Bearer {token}"},
        )
        site_data = site_resp.json()
        if site_resp.status_code in (401, 403):
            raise Exception(
                f"Graph API permission denied (HTTP {site_resp.status_code}). "
                f"The app registration needs 'Sites.ReadWrite.All' (Application) permission with admin consent. "
                f"Go to Azure Portal > App Registrations > {deps.GRAPH_CLIENT_ID} > API Permissions > Add 'Sites.ReadWrite.All' > Grant admin consent."
            )
        if site_resp.status_code == 404 or "id" not in site_data:
            error = site_data.get("error", {})
            raise Exception(
                f"SharePoint site not found (HTTP {site_resp.status_code}). "
                f"Check SHAREPOINT_SITE_HOSTNAME='{deps.SHAREPOINT_SITE_HOSTNAME}' and SHAREPOINT_SITE_PATH='{deps.SHAREPOINT_SITE_PATH}'. "
                f"Detail: {error.get('message', error.get('code', 'unknown'))}"
            )
        if "id" not in site_data:
            raise Exception(f"Unexpected Graph response: {str(site_data)[:200]}")
        site_id = site_data["id"]

        # Step 2: Resolve drive
        drives_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
            headers={"Authorization": f"Bearer {token}"},
        )
        drives_data = drives_resp.json()
        if drives_resp.status_code in (401, 403):
            raise Exception(f"Graph permission denied listing drives (HTTP {drives_resp.status_code}). Ensure 'Sites.ReadWrite.All' permission is granted.")
        if "error" in drives_data:
            raise Exception(f"Drive list error: {drives_data['error'].get('message', drives_data['error'])}")
        drives = drives_data.get("value", [])
        drive = next((d for d in drives if d["name"] == deps.SHAREPOINT_LIBRARY_NAME), drives[0] if drives else None)
        if not drive:
            raise Exception(f"Document library '{deps.SHAREPOINT_LIBRARY_NAME}' not found. Available: {[d['name'] for d in drives]}")
        drive_id = drive["id"]

        # Step 3: Upload file
        upload_resp = await c.put(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{folder}/{file_name}:/content",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/octet-stream"},
            content=file_content,
        )
        item = upload_resp.json()
        if upload_resp.status_code in (401, 403):
            raise Exception(f"Upload permission denied (HTTP {upload_resp.status_code}). Ensure app has 'Files.ReadWrite.All' or 'Sites.ReadWrite.All'.")
        if "id" not in item:
            error = item.get("error", {})
            raise Exception(f"Upload failed (HTTP {upload_resp.status_code}): {error.get('message', error.get('code', item))}")
        return {"drive_id": drive_id, "item_id": item["id"], "web_url": item.get("webUrl", ""), "name": file_name}


async def create_sharing_link(drive_id: str, item_id: str) -> str:
    """Create an organization-scoped view link for a SharePoint item."""
    if deps.DEMO_MODE or not deps.GRAPH_CLIENT_ID:
        return f"https://{deps.SHAREPOINT_SITE_HOSTNAME}/:b:/s/GPI-DocumentHub-Test/{item_id[:8]}"
    token = await get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.post(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/createLink",
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"type": "view", "scope": "organization"},
        )
        data = resp.json()
        if "error" in data:
            raise Exception(f"Sharing link error: {data['error'].get('message', data['error'])}")
        return data.get("link", {}).get("webUrl", "")


async def ensure_sharepoint_folder_exists(folder_path: str) -> bool:
    """Ensure a folder exists in SharePoint, creating it and any parents if needed."""
    if deps.DEMO_MODE or not deps.GRAPH_CLIENT_ID:
        return True

    token = await get_graph_token()
    async with httpx.AsyncClient(timeout=30.0) as c:
        # Get site and drive
        site_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{deps.SHAREPOINT_SITE_HOSTNAME}:{deps.SHAREPOINT_SITE_PATH}:",
            headers={"Authorization": f"Bearer {token}"},
        )
        if site_resp.status_code != 200:
            logger.warning("Could not resolve SharePoint site for folder creation")
            return False
        site_id = site_resp.json()["id"]

        drives_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
            headers={"Authorization": f"Bearer {token}"},
        )
        drives = drives_resp.json().get("value", [])
        drive = next((d for d in drives if d["name"] == deps.SHAREPOINT_LIBRARY_NAME), drives[0] if drives else None)
        if not drive:
            return False
        drive_id = drive["id"]

        # Create folder path
        folder_parts = folder_path.split("/")
        current_path = ""

        for part in folder_parts:
            if not part:
                continue
            parent_path = current_path if current_path else "root"
            current_path = f"{current_path}/{part}" if current_path else part

            check_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{current_path}"
            check_resp = await c.get(check_url, headers={"Authorization": f"Bearer {token}"})

            if check_resp.status_code == 404:
                if parent_path == "root":
                    create_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
                else:
                    create_url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{'/'.join(folder_parts[:folder_parts.index(part)])}:/children"

                create_resp = await c.post(
                    create_url,
                    headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
                    json={"name": part, "folder": {}, "@microsoft.graph.conflictBehavior": "fail"},
                )

                if create_resp.status_code not in (200, 201, 409):
                    logger.warning("Failed to create folder %s: %s", current_path, create_resp.text[:200])
                else:
                    logger.info("Created SharePoint folder: %s", current_path)

        return True
