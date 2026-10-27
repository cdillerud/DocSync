"""Price letters and price books from a supplier-facing mailbox (GamerSalesteam@) -> the sales assistant's price lists.

Run on the Hub VM by a scheduled job (scripts/Install-Hub-Price-Lists-Job.ps1), inside gpi-backend for its Graph app
credentials and intake settings. Not imported by the Hub; it doesn't change the Hub's own mail processing.

Each run reads the mailbox's messages with attachments received in the last ``days`` (Mail.Read, read only: nothing is
moved, marked or deleted), sends every PDF attachment not sent before to /api/v70/catalog/intake/price-lists, and
prints counts only (no subjects, senders or file names). The service keeps Berry letters and Amcor price books and
answers NOT_A_PRICE_LIST for anything else. Attachments already sent are remembered in a state file (by message and
attachment id) so a file goes once.

  MAILBOX   PRICE_LIST_MAILBOX (default gamersalesteam@gamerpackaging.com)
  URL       PRICE_LISTS_URL, else NEW_ITEM_REQUESTS_URL with /new-items -> /price-lists
  KEY       NEW_ITEM_REQUESTS_KEY (or CATALOG_FORWARD_KEY)
"""
from __future__ import annotations

import asyncio
import base64
import json
import os
import re
import sys
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

import httpx

GRAPH = "https://graph.microsoft.com/v1.0"
MAX_BYTES = 15 * 1024 * 1024


def _settings() -> Dict[str, str]:
    url = os.environ.get("PRICE_LISTS_URL", "").strip()
    if not url:
        base = os.environ.get("NEW_ITEM_REQUESTS_URL", "").strip()
        if not base and os.environ.get("CATALOG_FORWARD_URL", "").strip().endswith("/submit"):
            base = re.sub(r"/submit/?$", "/new-items", os.environ["CATALOG_FORWARD_URL"].strip())
        url = re.sub(r"/new-items/?$", "/price-lists", base) if base else ""
    key = (os.environ.get("NEW_ITEM_REQUESTS_KEY") or os.environ.get("CATALOG_FORWARD_KEY") or "").strip()
    mailbox = os.environ.get("PRICE_LIST_MAILBOX", "gamersalesteam@gamerpackaging.com").strip()
    return {"url": url, "key": key, "mailbox": mailbox}


async def _get(client: httpx.AsyncClient, token: str, url: str) -> httpx.Response:
    for attempt in range(5):
        r = await client.get(url, headers={"Authorization": f"Bearer {token}"})
        if r.status_code in (429, 503, 504):
            await asyncio.sleep(min(30, int(r.headers.get("Retry-After") or 2 ** attempt)))
            continue
        return r
    return r


async def run(days: int = 2, state_path: str = "/tmp/price-lists-seen.json", dry_run: bool = False) -> Dict[str, Any]:
    s = _settings()
    if not dry_run and not (s["url"] and s["key"]):
        return {"status": "NOT_CONFIGURED", "reason": "no price-lists URL or intake key in the Hub settings"}
    from services.config_service import get_email_token
    token = await get_email_token()
    if not token or token.startswith("mock-"):
        return {"status": "NO_GRAPH", "reason": "no mail token (demo mode or mail settings missing)"}
    try:
        with open(state_path, encoding="utf-8") as fh:
            seen = set(json.load(fh).get("seen") or [])
    except Exception:
        seen = set()
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days), 730)))).strftime("%Y-%m-%dT%H:%M:%SZ")
    counts = {"messages": 0, "pdfs": 0, "already_sent": 0, "sent": 0, "price_lists_kept": 0, "not_price_lists": 0,
              "too_big": 0, "errors": 0}
    async with httpx.AsyncClient(timeout=120.0) as client:
        url = (f"{GRAPH}/users/{s['mailbox']}/messages?$filter=hasAttachments eq true and receivedDateTime ge {since}"
               "&$select=id,receivedDateTime&$orderby=receivedDateTime asc&$top=50")
        while url:
            r = await _get(client, token, url)
            if r.status_code in (401, 403):
                return {"status": "ACCESS_DENIED", "mailbox": s["mailbox"],
                        "reason": "the Hub's mail app can't read this mailbox (Exchange application access policy); "
                                  "run Grant-Hub-Mailbox-Access.ps1 as an Exchange admin"}
            if r.status_code == 404:
                return {"status": "MAILBOX_NOT_FOUND", "mailbox": s["mailbox"],
                        "reason": "no mailbox by that address (a distribution group has no mailbox to read)"}
            if r.status_code >= 400:
                return {"status": "GRAPH_ERROR", "http": r.status_code}
            page = r.json()
            for msg in page.get("value") or []:
                counts["messages"] += 1
                ra = await _get(client, token, f"{GRAPH}/users/{s['mailbox']}/messages/{msg['id']}/attachments"
                                                "?$select=id,name,contentType,size")
                if ra.status_code >= 400:
                    counts["errors"] += 1
                    continue
                for att in ra.json().get("value") or []:
                    name = str(att.get("name") or "")
                    if "itemAttachment" in str(att.get("@odata.type") or ""):
                        continue  # an attached email (.msg): its own attachments aren't opened here
                    if not (name.lower().endswith(".pdf") or "pdf" in str(att.get("contentType") or "").lower()):
                        continue
                    counts["pdfs"] += 1
                    mark = f"{msg['id']}|{att['id']}"
                    if mark in seen:
                        counts["already_sent"] += 1
                        continue
                    if (att.get("size") or 0) > MAX_BYTES:
                        counts["too_big"] += 1
                        seen.add(mark)
                        continue
                    if dry_run:
                        continue
                    rb = await _get(client, token, f"{GRAPH}/users/{s['mailbox']}/messages/{msg['id']}/attachments/{att['id']}")
                    b64 = (rb.json() or {}).get("contentBytes") if rb.status_code < 400 else None
                    if not b64:
                        counts["errors"] += 1
                        continue
                    try:
                        base64.b64decode(b64, validate=True)
                    except Exception:
                        counts["errors"] += 1
                        continue
                    rp = await client.post(s["url"], json={"name": name if name.lower().endswith(".pdf") else name + ".pdf",
                                                           "pdf_b64": b64},
                                           headers={"X-GPI-Intake-Key": s["key"], "Content-Type": "application/json"})
                    if rp.status_code >= 400:
                        counts["errors"] += 1
                        continue
                    answer = rp.json() if rp.content else {}
                    counts["sent"] += 1
                    kept = len(answer.get("read") or [])
                    if kept:
                        counts["price_lists_kept"] += kept
                    else:
                        counts["not_price_lists"] += 1
                    seen.add(mark)
            url = page.get("@odata.nextLink")
    if not dry_run:
        try:
            with open(state_path, "w", encoding="utf-8") as fh:
                json.dump({"seen": sorted(seen)[-20000:], "updated": datetime.now(timezone.utc).isoformat()}, fh)
        except Exception:
            counts["errors"] += 1
    return {"status": "DRY_RUN" if dry_run else "OK", "mailbox": s["mailbox"], "days": days, **counts}


if __name__ == "__main__":
    days = int(sys.argv[1]) if len(sys.argv) > 1 else 2
    dry = len(sys.argv) > 2 and sys.argv[2] == "dry"
    print(json.dumps(asyncio.run(run(days=days, dry_run=dry))))
