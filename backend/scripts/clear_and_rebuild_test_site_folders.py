"""
Clears all items from the TEST SharePoint site and replicates the real
production folder structure onto it (empty folders only), so that a
subsequent release of documents lands in a site whose folder names/
structure genuinely match production - not whatever the test site has
drifted to over time.

SAFETY DESIGN:
- Test site hostname/path are HARDCODED here, independent of the
  SHAREPOINT_TARGET toggle - this can never accidentally target
  production even if the toggle's state changes for an unrelated reason.
- Before any deletion, asserts the resolved site's description == "Testing"
  (confirmed earlier today via direct Graph API check) as a second,
  independent safety net.
- Defaults to DRY RUN: reports what would be deleted and what folders
  would be created, with zero side effects. Real action requires
  --confirm CLEAR-AND-REBUILD, matching the confirm-gate pattern already
  used elsewhere in this codebase (e.g. bucket_A_one_shot_data_patch_apply.py).
"""
import argparse
import asyncio
import os
import sys
sys.path.insert(0, '.')

import httpx

TEST_HOSTNAME = "gamerpackaging1.sharepoint.com"
TEST_PATH = "/sites/GPI-DocumentHub-Test"
TEST_LIBRARY = "Shared Documents"
EXPECTED_TEST_DESCRIPTION = "Testing"

PROD_HOSTNAME = "gamerpackaging1.sharepoint.com"
PROD_PATH = "/sites/GamerAccounting"
PROD_LIBRARY = "Shared Documents"
PROD_BASE_FOLDER = "General/Accounting/Accounts Payable/Temp Folder"


async def resolve_site_and_drive(client: httpx.AsyncClient, token: str, hostname: str, path: str, library: str):
    resp = await client.get(
        f"https://graph.microsoft.com/v1.0/sites/{hostname}:{path}:",
        headers={"Authorization": f"Bearer {token}"})
    data = resp.json()
    if resp.status_code != 200 or "id" not in data:
        raise RuntimeError(f"Failed to resolve site {hostname}{path}: HTTP {resp.status_code} {data}")
    site_id = data["id"]
    description = data.get("description", "")

    drives_resp = await client.get(
        f"https://graph.microsoft.com/v1.0/sites/{site_id}/drives",
        headers={"Authorization": f"Bearer {token}"})
    drives = drives_resp.json().get("value", [])
    drive = next((d for d in drives if d["name"].lower() == library.lower()), None)
    if not drive:
        drive = next((d for d in drives if d.get("driveType") == "documentLibrary"), None)
    if not drive:
        raise RuntimeError(f"No document library found for {hostname}{path}")
    return site_id, description, drive["id"]


async def list_all_folders(client: httpx.AsyncClient, token: str, drive_id: str, base_path: str) -> list:
    """Recursively list every folder under base_path, returning paths RELATIVE to base_path."""
    folders = []

    async def _walk(rel_path: str):
        full_path = f"{base_path}/{rel_path}" if rel_path else base_path
        safe_path = full_path.strip("/")
        resp = await client.get(
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{safe_path}:/children",
            headers={"Authorization": f"Bearer {token}"})
        if resp.status_code != 200:
            return
        for item in resp.json().get("value", []):
            if "folder" in item:
                child_rel = f"{rel_path}/{item['name']}" if rel_path else item["name"]
                folders.append(child_rel)
                await _walk(child_rel)

    await _walk("")
    return folders


async def list_root_items(client: httpx.AsyncClient, token: str, drive_id: str) -> list:
    resp = await client.get(
        f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children",
        headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        return []
    return resp.json().get("value", [])


async def delete_item(client: httpx.AsyncClient, token: str, drive_id: str, item_id: str):
    resp = await client.delete(
        f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}",
        headers={"Authorization": f"Bearer {token}"})
    return resp.status_code in (204, 404)


async def create_folder(client: httpx.AsyncClient, token: str, drive_id: str, rel_path: str):
    """Create a folder at rel_path (relative to test site root), creating parents as needed."""
    parts = rel_path.split("/")
    current = ""
    for part in parts:
        parent = current
        current = f"{current}/{part}" if current else part
        parent_url = (
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root:/{parent}:/children"
            if parent else
            f"https://graph.microsoft.com/v1.0/drives/{drive_id}/root/children"
        )
        resp = await client.post(
            parent_url,
            headers={"Authorization": f"Bearer {token}", "Content-Type": "application/json"},
            json={"name": part, "folder": {}, "@microsoft.graph.conflictBehavior": "replace"},
        )
        if resp.status_code not in (200, 201):
            print(f"    WARN creating {current}: HTTP {resp.status_code} {resp.text[:150]}")


async def main():
    p = argparse.ArgumentParser()
    p.add_argument("--confirm", default=None, help="Pass CLEAR-AND-REBUILD to actually execute")
    args = p.parse_args()

    from services.sharepoint_service import _get_graph_token

    token = await _get_graph_token()
    async with httpx.AsyncClient(timeout=60.0) as client:
        # Resolve TEST site with hardcoded values, independent of any toggle
        test_site_id, test_description, test_drive_id = await resolve_site_and_drive(
            client, token, TEST_HOSTNAME, TEST_PATH, TEST_LIBRARY)

        if test_description != EXPECTED_TEST_DESCRIPTION:
            print(f"SAFETY ABORT: resolved test site description is {test_description!r}, "
                  f"expected {EXPECTED_TEST_DESCRIPTION!r}. Refusing to proceed.")
            return
        print(f"Test site confirmed: {TEST_HOSTNAME}{TEST_PATH} (description={test_description!r})")

        # Resolve PROD site read-only, to discover its real folder structure
        prod_site_id, prod_description, prod_drive_id = await resolve_site_and_drive(
            client, token, PROD_HOSTNAME, PROD_PATH, PROD_LIBRARY)
        print(f"Production site resolved (read-only): {PROD_HOSTNAME}{PROD_PATH} (description={prod_description!r})")
        print()

        # Discover real production folder structure under the base folder
        prod_folders = await list_all_folders(client, token, prod_drive_id, PROD_BASE_FOLDER)
        print(f"Found {len(prod_folders)} folders under production's base folder.")
        for f in prod_folders[:20]:
            print(f"  {f}")
        if len(prod_folders) > 20:
            print(f"  ... and {len(prod_folders) - 20} more")
        print()

        # Discover what's currently on the test site root
        test_items = await list_root_items(client, token, test_drive_id)
        print(f"Found {len(test_items)} items at test site root to delete.")
        print()

        if args.confirm != "CLEAR-AND-REBUILD":
            print("DRY RUN ONLY - no changes made.")
            print("Re-run with --confirm CLEAR-AND-REBUILD to actually delete and rebuild.")
            return

        print("Deleting all test site root items...")
        deleted = 0
        for item in test_items:
            ok = await delete_item(client, token, test_drive_id, item["id"])
            if ok:
                deleted += 1
        print(f"Deleted {deleted}/{len(test_items)} items.")
        print()

        print("Recreating production's folder structure on the test site (empty folders)...")
        for i, folder_path in enumerate(prod_folders, 1):
            await create_folder(client, token, test_drive_id, folder_path)
            if i % 10 == 0 or i == len(prod_folders):
                print(f"  [{i}/{len(prod_folders)}] created")
        print()
        print("=== DONE ===")


asyncio.run(main())
