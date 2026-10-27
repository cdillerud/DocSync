"""Supplier price lists for the price audit: the price letters and price books on OneGamer, sent to the sales assistant.

Lists the PDFs under OneGamer ``General/Manufacturers - Vendors/<supplier>/<...Pricing...>/**`` (Berry's letters in
``Berry (M&H)/Pricing/2026``, Amcor's Bev / Legacy / Pharma books in ``Amcor/Pricing/2026``) modified since a date,
downloads the ones not sent before (or changed since), and posts each to the catalog service's price-list intake,
which keeps the ones it can read (supplier, account, ship-to, effective date, item prices) for the price audit.
Read only on SharePoint: nothing there is changed. A small state file (file id -> eTag and what the service read)
keeps nightly runs to the new and changed files. Counts and file names only in the answer; no prices.
"""
from __future__ import annotations

import asyncio
import base64
import json
import logging
import os
import re
from datetime import date, datetime, timezone
from typing import Any, Dict, List, Optional

import httpx

logger = logging.getLogger(__name__)

GRAPH = "https://graph.microsoft.com/v1.0"
SITE_PATH = "/sites/OneGamer"
ROOT = "General/Manufacturers - Vendors"


class PriceListIndexError(RuntimeError):
    pass


async def _get(client: httpx.AsyncClient, token: str, url: str) -> Dict[str, Any]:
    for attempt in range(6):
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if resp.status_code in (429, 503, 504):
            await asyncio.sleep(min(60, int(resp.headers.get("Retry-After") or 2 ** attempt)))
            continue
        if resp.status_code in (401, 403):
            raise PriceListIndexError(f"Microsoft Graph refused access ({resp.status_code}): the Hub's app needs read "
                                      "access to the OneGamer site")
        if resp.status_code == 404:
            return {}
        if resp.status_code >= 400:
            raise PriceListIndexError(f"Microsoft Graph returned HTTP {resp.status_code}")
        return resp.json()
    raise PriceListIndexError("Microsoft Graph kept throttling; try again later")


async def _children(client: httpx.AsyncClient, token: str, drive_id: str, item_id: str) -> List[Dict[str, Any]]:
    url: Optional[str] = (f"{GRAPH}/drives/{drive_id}/items/{item_id}/children"
                          "?$top=999&$select=id,name,folder,file,webUrl,lastModifiedDateTime,eTag")
    out: List[Dict[str, Any]] = []
    while url:
        page = await _get(client, token, url)
        out += page.get("value") or []
        url = page.get("@odata.nextLink")
    return out

PRICING_FOLDER = re.compile(r"pric", re.IGNORECASE)
MAX_DEPTH = 5
MAX_BYTES = 14 * 1024 * 1024  # base64 grows a third; the intake takes 20 MB
STATE_PATH = os.environ.get("GPI_PRICE_LIST_STATE", "/tmp/price-lists-sent.json")


def _since_default() -> str:
    return f"{date.today().year - 1}-01-01"


async def crawl(since: str = "", site_path: str = SITE_PATH, root: str = ROOT, host: str = "",
                suppliers: Optional[List[str]] = None) -> Dict[str, Any]:
    """{'files': [...], 'drive_id': ..., 'folders': n}: PDFs in each supplier's pricing folders modified since ``since``."""
    since = since or _since_default()
    if not host:
        from services.config_service import SHAREPOINT_SITE_HOSTNAME
        host = SHAREPOINT_SITE_HOSTNAME
    from services.catalog_forward import _graph_token
    token = await _graph_token()
    if not token or token.startswith("mock-"):
        raise PriceListIndexError("no Microsoft Graph token (demo mode or Graph settings missing)")
    files: List[Dict[str, Any]] = []
    folders_read = 0
    async with httpx.AsyncClient(timeout=120.0) as client:
        site = await _get(client, token, f"{GRAPH}/sites/{host}:{site_path}")
        if not site:
            raise PriceListIndexError(f"site {site_path} not found")
        drive = await _get(client, token, f"{GRAPH}/sites/{site['id']}/drive?$select=id")
        top = await _get(client, token, f"{GRAPH}/drives/{drive['id']}/root:/{root}?$select=id")
        if not top:
            raise PriceListIndexError(f"folder {root} not found on {site_path}")
        for sup in await _children(client, token, drive["id"], top["id"]):
            if "folder" not in sup:
                continue
            name = str(sup.get("name") or "")
            if suppliers and not any(s.casefold() in name.casefold() for s in suppliers):
                continue
            folders_read += 1
            stack = [(child, 1, child.get("name") or "") for child in await _children(client, token, drive["id"], sup["id"])
                     if "folder" in child and PRICING_FOLDER.search(str(child.get("name") or ""))]
            while stack:
                folder, depth, rel = stack.pop()
                folders_read += 1
                for it in await _children(client, token, drive["id"], folder["id"]):
                    nm = str(it.get("name") or "")
                    if "folder" in it and depth < MAX_DEPTH:
                        stack.append((it, depth + 1, f"{rel}/{nm}"))
                    elif "file" in it and nm.lower().endswith(".pdf") and str(it.get("lastModifiedDateTime") or "")[:10] >= since:
                        files.append({"id": it["id"], "supplier": name, "name": nm, "path": rel,
                                      "modified": it.get("lastModifiedDateTime") or "",
                                      "etag": it.get("eTag") or it.get("lastModifiedDateTime") or ""})
    return {"files": files, "drive_id": drive["id"], "folders": folders_read, "since": since}


def _intake_url() -> str:
    from services.new_item_requests import get_settings
    url = get_settings().url
    return re.sub(r"/new-items/?$", "/price-lists", url) if url else ""


def _load_state(path: str) -> Dict[str, Any]:
    try:
        with open(path, encoding="utf-8") as fh:
            data = json.load(fh)
        return data if isinstance(data, dict) else {}
    except Exception:
        return {}


def _save_state(path: str, state: Dict[str, Any]) -> None:
    tmp = path + ".tmp"
    with open(tmp, "w", encoding="utf-8") as fh:
        json.dump(state, fh, indent=1, sort_keys=True)
    os.replace(tmp, path)


async def run(send_it: bool = False, since: str = "", suppliers: Optional[List[str]] = None, resend: bool = False,
              state_path: str = STATE_PATH, limit: int = 0) -> Dict[str, Any]:
    """Crawl, then (with ``send_it``) send the new and changed files. Counts and file names only."""
    started = datetime.now(timezone.utc)
    try:
        listing = await crawl(since=since, suppliers=suppliers)
    except PriceListIndexError as exc:
        return {"status": "SHAREPOINT_ERROR", "reason": str(exc)}
    files = listing["files"]
    state = {} if resend else _load_state(state_path)
    todo = [f for f in files if state.get(f["id"], {}).get("etag") != f["etag"]]
    if limit:
        todo = todo[:limit]
    out: Dict[str, Any] = {"status": "LISTED", "since": listing["since"], "pdfs": len(files), "new_or_changed": len(todo),
                           "by_supplier": {}, "folders_read": listing["folders"]}
    for f in files:
        out["by_supplier"][f["supplier"]] = out["by_supplier"].get(f["supplier"], 0) + 1
    if not send_it:
        out["would_send"] = [f["name"][:70] for f in sorted(todo, key=lambda f: f["modified"], reverse=True)[:25]]
        out["seconds"] = round((datetime.now(timezone.utc) - started).total_seconds())
        return out
    from services.new_item_requests import get_settings
    settings = get_settings()
    url = _intake_url()
    if not (url and settings.key):
        out["status"] = "NOT_CONFIGURED"
        return out
    from services.catalog_forward import _graph_token
    token = await _graph_token()
    kept = not_read = failed = lists = 0
    unread: List[str] = []
    async with httpx.AsyncClient(timeout=180.0, follow_redirects=True) as client:
        for f in todo:
            try:
                resp = await client.get(f"{GRAPH}/drives/{listing['drive_id']}/items/{f['id']}/content",
                                        headers={"Authorization": f"Bearer {token}"})
                if resp.status_code >= 400 or not resp.content or len(resp.content) > MAX_BYTES:
                    failed += 1
                    continue
                body = {"name": f["name"], "pdf_b64": base64.b64encode(resp.content).decode("ascii"),
                        "source": f"OneGamer {f['supplier']}/{f['path']}"}
                answer = await client.post(url, json=body, headers={"X-GPI-Intake-Key": settings.key,
                                                                   "Content-Type": "application/json"})
                if answer.status_code >= 400:
                    failed += 1
                    continue
                result = answer.json()
                read = len(result.get("read") or [])
                if read:
                    kept += 1
                    lists += read
                else:
                    not_read += 1
                    unread.append(f"{f['supplier']}/{f['name']}")
                state[f["id"]] = {"etag": f["etag"], "name": f["name"], "lists": read,
                                  "sent": datetime.now(timezone.utc).isoformat(timespec="seconds")}
                _save_state(state_path, state)
            except Exception as exc:  # one bad file never stops the run
                logger.warning("price list %s not sent: %s", f.get("name"), type(exc).__name__)
                failed += 1
    out.update({"status": "SENT" if not failed else "SENT_WITH_ERRORS", "files_read": kept, "lists_kept": lists,
                "not_a_price_list_it_reads": not_read, "failed": failed, "unread_examples": [u[:70] for u in unread[:10]],
                "seconds": round((datetime.now(timezone.utc) - started).total_seconds())})
    return out
