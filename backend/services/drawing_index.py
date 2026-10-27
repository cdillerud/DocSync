"""Drawing index for the Packaging Catalog: the supplier drawings on OneGamer, sent to the sales assistant.

Lists the files under OneGamer ``General/Manufacturers - Vendors/<supplier>/<...Drawings...>/**`` (PDFs, images,
CAD) through Microsoft Graph with the Hub's app token, and sends the list (supplier folder, file name, link, modified)
to the catalog service's drawings intake in batches. The service links each sourcing option to the drawing in its
supplier's folder whose file name carries the option's mold or item number. Nothing is downloaded or changed: only
names and links travel. Counts only in the answer.
"""
from __future__ import annotations

import asyncio
import logging
import os
import re
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
SITE_PATH = "/sites/OneGamer"
ROOT = "General/Manufacturers - Vendors"
DRAWING_FOLDER = re.compile(r"drawing|dwg|spec", re.IGNORECASE)
EXTENSIONS = (".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff", ".dwg", ".dxf")
MAX_DEPTH = 6
BATCH = 1500


class DrawingIndexError(RuntimeError):
    pass


async def _get(client: httpx.AsyncClient, token: str, url: str) -> Dict[str, Any]:
    for attempt in range(6):
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code in (429, 503, 504):
            await asyncio.sleep(min(60, int(resp.headers.get("Retry-After") or 2 ** attempt)))
            continue
        if resp.status_code in (401, 403):
            raise DrawingIndexError(f"Microsoft Graph refused access ({resp.status_code}): the Hub's app needs read "
                                    "access to the OneGamer site (Sites.Read.All or the site granted)")
        if resp.status_code == 404:
            return {}
        if resp.status_code >= 400:
            raise DrawingIndexError(f"Microsoft Graph returned HTTP {resp.status_code}")
        return resp.json()
    raise DrawingIndexError("Microsoft Graph kept throttling; try again later")


async def _children(client: httpx.AsyncClient, token: str, drive_id: str, item_id: str) -> List[Dict[str, Any]]:
    url: Optional[str] = (f"{GRAPH}/drives/{drive_id}/items/{item_id}/children"
                          "?$top=999&$select=id,name,folder,file,webUrl,lastModifiedDateTime")
    out: List[Dict[str, Any]] = []
    while url:
        page = await _get(client, token, url)
        out += page.get("value") or []
        url = page.get("@odata.nextLink")
    return out


async def crawl(site_path: str = SITE_PATH, root: str = ROOT, host: str = "",
                suppliers: Optional[List[str]] = None) -> Dict[str, Any]:
    """{'drawings': [...], 'suppliers': n, 'folders': n} for the drawing folders under each supplier folder."""
    if not host:
        from services.config_service import SHAREPOINT_SITE_HOSTNAME
        host = SHAREPOINT_SITE_HOSTNAME
    from services.catalog_forward import _graph_token
    token = await _graph_token()
    if not token or token.startswith("mock-"):
        raise DrawingIndexError("no Microsoft Graph token (demo mode or Graph settings missing)")
    drawings: List[Dict[str, Any]] = []
    folders_read = 0
    with_drawings = 0
    async with httpx.AsyncClient(timeout=120.0) as client:
        site = await _get(client, token, f"{GRAPH}/sites/{host}:{site_path}")
        if not site:
            raise DrawingIndexError(f"site {site_path} not found")
        drive = await _get(client, token, f"{GRAPH}/sites/{site['id']}/drive?$select=id")
        top = await _get(client, token, f"{GRAPH}/drives/{drive['id']}/root:/{root}?$select=id")
        if not top:
            raise DrawingIndexError(f"folder {root} not found on {site_path}")
        for sup in await _children(client, token, drive["id"], top["id"]):
            if "folder" not in sup:
                continue
            name = str(sup.get("name") or "")
            if suppliers and not any(s.casefold() in name.casefold() for s in suppliers):
                continue
            found_here = 0
            stack = [(child, 1, child.get("name") or "") for child in await _children(client, token, drive["id"], sup["id"])
                     if "folder" in child and DRAWING_FOLDER.search(str(child.get("name") or ""))]
            folders_read += 1
            while stack:
                folder, depth, rel = stack.pop()
                folders_read += 1
                for it in await _children(client, token, drive["id"], folder["id"]):
                    nm = str(it.get("name") or "")
                    if "folder" in it and depth < MAX_DEPTH:
                        stack.append((it, depth + 1, f"{rel}/{nm}"))
                    elif "file" in it and nm.lower().endswith(EXTENSIONS):
                        drawings.append({"supplier": name, "name": nm, "url": it.get("webUrl") or "",
                                         "modified": it.get("lastModifiedDateTime") or "", "path": rel})
                        found_here += 1
            with_drawings += 1 if found_here else 0
    return {"drawings": drawings, "suppliers": with_drawings, "folders": folders_read}


def _intake_url() -> str:
    from services.new_item_requests import get_settings
    url = get_settings().url
    return re.sub(r"/new-items/?$", "/drawings", url) if url else ""


async def send(drawings: List[Dict[str, Any]]) -> Dict[str, Any]:
    """Send the listing in batches; the service keeps its old index unless every batch arrives."""
    from services.new_item_requests import get_settings
    settings = get_settings()
    url = _intake_url()
    if not (url and settings.key):
        return {"status": "NOT_CONFIGURED", "reason": "NEW_ITEM_REQUESTS_URL/KEY (or the catalog forward's) missing"}
    snapshot = uuid.uuid4().hex[:12]
    batches = max(1, -(-len(drawings) // BATCH))
    last: Dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=120.0) as client:
        for i in range(batches):
            body = {"snapshot_id": snapshot, "batch": i + 1, "batches": batches, "source": "GPI Hub (OneGamer)",
                    "drawings": drawings[i * BATCH:(i + 1) * BATCH]}
            resp = await client.post(url, json=body, headers={"X-GPI-Intake-Key": settings.key,
                                                              "Content-Type": "application/json"})
            try:
                last = resp.json()
            except Exception:
                last = {"status": f"HTTP {resp.status_code}"}
            if resp.status_code >= 400:
                return {"status": "SEND_FAILED", "batch": i + 1, "batches": batches, "answer": last}
    return {"status": "SENT", "batches": batches, "answer": last}


async def run(send_it: bool = False, suppliers: Optional[List[str]] = None) -> Dict[str, Any]:
    """Crawl, then (with ``send_it``) send. Counts only."""
    started = datetime.now(timezone.utc)
    try:
        listing = await crawl(suppliers=suppliers)
    except DrawingIndexError as exc:
        return {"status": "SHAREPOINT_ERROR", "reason": str(exc)}
    rows = listing["drawings"]
    out: Dict[str, Any] = {"status": "LISTED", "drawings": len(rows), "suppliers_with_drawings": listing["suppliers"],
                           "folders_read": listing["folders"],
                           "by_type": {ext: sum(1 for r in rows if r["name"].lower().endswith(ext)) for ext in EXTENSIONS
                                       if any(r["name"].lower().endswith(ext) for r in rows)},
                           "seconds": round((datetime.now(timezone.utc) - started).total_seconds())}
    if send_it and rows:
        out["send"] = await send(rows)
        out["status"] = out["send"].get("status")
    return out
