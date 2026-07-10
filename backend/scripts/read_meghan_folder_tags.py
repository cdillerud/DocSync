import asyncio
import os
import sys
sys.path.insert(0, '.')

import httpx

TEST_HOSTNAME = "gamerpackaging1.sharepoint.com"
TEST_PATH = "/sites/GPI-DocumentHub-Test"


async def main():
    from services.sharepoint_service import _get_graph_token
    token = await _get_graph_token()

    async with httpx.AsyncClient(timeout=30.0) as c:
        site_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{TEST_HOSTNAME}:{TEST_PATH}:",
            headers={"Authorization": f"Bearer {token}"})
        site_id = site_resp.json()["id"]

        lists_resp = await c.get(
            f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists",
            headers={"Authorization": f"Bearer {token}"})
        lists = lists_resp.json().get("value", [])
        doc_list = next(
            (l for l in lists if l.get("list", {}).get("template") == "documentLibrary"
             and l.get("displayName") == "Documents"),
            None,
        )
        if not doc_list:
            print("Could not find Documents list. Available lists:")
            for l in lists:
                print(f"  {l.get('displayName')} (template={l.get('list', {}).get('template')})")
            return
        list_id = doc_list["id"]
        print(f"Found list: {doc_list['displayName']} ({list_id})")

        all_items = []
        url = f"https://graph.microsoft.com/v1.0/sites/{site_id}/lists/{list_id}/items?expand=fields&$top=200"
        while url:
            resp = await c.get(url, headers={"Authorization": f"Bearer {token}"})
            data = resp.json()
            all_items.extend(data.get("value", []))
            url = data.get("@odata.nextLink")

        print(f"Total items in library: {len(all_items)}")

        tagged = [i for i in all_items if i.get("fields", {}).get("Folder")]
        print(f"Items with Folder tag filled in: {len(tagged)}")
        print()
        for i in tagged:
            f = i["fields"]
            print(f"{f.get('FileLeafRef')} :: {f.get('Folder')}")


asyncio.run(main())
