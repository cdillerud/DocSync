"""Non-invoice mail out of the invoice folders (Hub test SharePoint site only).

Tax-exemption requests, statements, vendor forms and price notices are
uploaded at intake before the hourly cycle marks them non-AP (non_ap_kind),
so they landed in invoice folders such as "Misc Invoices - need approval".
Staff never file them in Square 9. Chad, 2026-11-05: one folder for all of
them, moved there automatically. Hourly; idempotent; the previous folder is
kept on the document.
"""
import logging
from datetime import datetime, timezone
from typing import Any, Dict
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

NON_AP_FOLDER = "Not AP - No Action"


async def move_non_ap(db, apply: bool = True, limit: int = 200) -> Dict[str, Any]:
    import services.sharepoint_service as S
    if S.DEMO_MODE or not S.GRAPH_CLIENT_ID:
        return {"skipped": "SharePoint not configured"}
    if S.SHAREPOINT_TARGET != "test" or "DocumentHub-Test" not in S.SHAREPOINT_SITE_PATH:
        return {"skipped": f"target is {S.SHAREPOINT_TARGET} {S.SHAREPOINT_SITE_PATH}; only the Hub test site"}
    base = (S.SHAREPOINT_BASE_FOLDER or "").strip("/")
    folder = f"{base}/{NON_AP_FOLDER}" if base else NON_AP_FOLDER
    q = {"non_ap_kind": {"$exists": True}, "sharepoint_item_id": {"$nin": [None, ""]},
         "sharepoint_folder_path": {"$ne": folder}}
    todo = [d async for d in db.hub_documents.find(q, {"_id": 0, "id": 1, "sharepoint_drive_id": 1, "sharepoint_item_id": 1,
                                                       "sharepoint_folder_path": 1}).limit(limit)]
    out = {"to_move": len(todo), "moved": 0, "other_drive": 0, "gone": 0, "errors": 0, "folder": folder}
    if not todo or not apply:
        return out
    await S.ensure_sharepoint_folder_exists(folder)
    token = await S._get_graph_token()
    h = {"Authorization": f"Bearer {token}"}
    now = datetime.now(timezone.utc).isoformat()
    async with httpx.AsyncClient(timeout=30) as c:
        _, drive = await S._site_and_drive(c, token)
        r = await c.get(f"https://graph.microsoft.com/v1.0/drives/{drive}/root:/{quote(folder, safe='/')}", headers=h)
        r.raise_for_status()
        folder_id = r.json()["id"]
        for d in todo:
            if d.get("sharepoint_drive_id") != drive:
                out["other_drive"] += 1
                continue
            r = await c.patch(f"https://graph.microsoft.com/v1.0/drives/{drive}/items/{d['sharepoint_item_id']}",
                              headers={**h, "Content-Type": "application/json"},
                              json={"parentReference": {"id": folder_id},
                                    "@microsoft.graph.conflictBehavior": "rename"})
            if r.status_code == 404:
                out["gone"] += 1
                continue
            if r.status_code not in (200, 201):
                out["errors"] += 1
                logger.warning("[NonAPFiling] move %s failed %s %s", d["id"], r.status_code, r.text[:200])
                continue
            j = r.json()
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {
                "sharepoint_folder_path": folder, "sharepoint_web_url": j.get("webUrl"),
                "sharepoint_folder_previous": d.get("sharepoint_folder_path"), "sharepoint_moved_at": now,
                "sharepoint_move_reason": "non-AP document: " + NON_AP_FOLDER}})
            out["moved"] += 1
    logger.info("[NonAPFiling] %s", out)
    return out
