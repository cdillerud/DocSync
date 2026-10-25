"""Zetadocs memory: documents staff attached to BC records (DocsNAV site).

Every file in the DocsNAV Zetadocs libraries was attached by staff to a BC
record, and SharePoint keeps that record on the file: Record Type (Purchase
Order, Sales Order, Purchase Invoice...), Record No. (W118604, 117804...) and
Company No. (the BC vendor or customer). Freight bills, customs entries,
container lists, BOLs and confirmations sit on the order they belong to, often
renamed by staff with the orders ("W118604 W118607_TUMALO_0314238.pdf").

That makes the library a labelled record of the document flow: which
documents belong to which order. order_flow_service learns from it which
numbers on a document (container, ocean bill, forwarder reference) tie it to
an order, for documents that do not print our order number.

Read-only against SharePoint (GET only). Kept in its own collection
(zetadocs_memory) so the similar-document index stays the AP library's.
"""
from __future__ import annotations

import asyncio
import collections
import io
import logging
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List

from services.document_memory_service import SP_HOST, MAX_BYTES, _graph, pdf_text

logger = logging.getLogger("zetadocs_memory")

G = "https://graph.microsoft.com/v1.0"
SITE = "/sites/DocsNAV"
LIBS = ("Zetadocs", "Zetadocs2023", "Zetadocs2022", "Zetadocs2021")
FIELDS = ("ZetadocsRecordType,ZetadocsRecordNo,ZetadocsCompanyNo,ZetadocsOrganization,ZetadocsDocumentType,"
          "FileLeafRef,ContentType,Created,Modified,File_x0020_Size")
TEXT_CHARS = 4000
READ_EXT = {"pdf", "xlsx"}
# The order-flow learner needs the shipment paperwork on purchase orders and
# the freight bills on purchase invoices; read those first, newest first.
READ_FIRST = ("Purchase Order", "Purchase Invoice", "Posted Purchase Invoice", "Posted Purchase Receipt")


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def xlsx_text(data: bytes) -> str:
    try:
        import openpyxl
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
        out: List[str] = []
        for ws in wb.worksheets[:3]:
            for row in ws.iter_rows(max_row=200, values_only=True):
                cells = [str(v) for v in row if v not in (None, "")]
                if cells:
                    out.append(" | ".join(cells))
                if sum(len(x) for x in out) > TEXT_CHARS:
                    break
        return "\n".join(out)[:TEXT_CHARS]
    except Exception:
        return ""


async def _site(c, box) -> Dict[str, Any]:
    site = (await _graph(c, f"{G}/sites/{SP_HOST}:{SITE}:", box)).json()
    lists = (await _graph(c, f"{G}/sites/{site['id']}/lists?$select=id,name", box)).json()["value"]
    return {"id": site["id"], "lists": {l["name"]: l["id"] for l in lists if l["name"] in LIBS}}


async def harvest_labels(db, seconds: int = 1500) -> Dict[str, Any]:
    """Remember every file's Zetadocs labels (no file contents). Resumes
    from the saved page of each library; a finished library is re-listed
    from the start on the next pass, skipping unchanged files."""
    import httpx
    t0, stats = time.time(), collections.Counter()
    box: Dict[str, Any] = {}
    await db.zetadocs_memory.create_index("record_no")
    await db.zetadocs_memory.create_index([("has_text", 1), ("created", -1)])
    st = await db.learning_state.find_one({"_id": "zetadocs"}) or {}
    pos = dict(st.get("next") or {})
    async with httpx.AsyncClient(timeout=180) as c:
        s = await _site(c, box)
        for lib in LIBS:
            if lib not in s["lists"] or time.time() - t0 > seconds:
                continue
            url = pos.get(lib) or f"{G}/sites/{s['id']}/lists/{s['lists'][lib]}/items?$top=999&$expand=fields($select={FIELDS})"
            while url and time.time() - t0 < seconds:
                r = await _graph(c, url, box)
                if r.status_code != 200:
                    stats["list_errors"] += 1
                    url = None
                    break
                j = r.json()
                ops = []
                for it in j.get("value", []):
                    f = it.get("fields") or {}
                    if f.get("ContentType") == "Folder":
                        continue
                    stats["files"] += 1
                    name = f.get("FileLeafRef") or ""
                    ops.append({"_id": f"{lib}:{it['id']}", "lib": lib, "list_item_id": it["id"], "name": name,
                                "ext": name.rsplit(".", 1)[-1].lower() if "." in name else "",
                                "record_type": f.get("ZetadocsRecordType") or "", "record_no": str(f.get("ZetadocsRecordNo") or "").strip().upper(),
                                "company_no": str(f.get("ZetadocsCompanyNo") or "").strip().upper(), "organization": f.get("ZetadocsOrganization") or "",
                                "doc_type": f.get("ZetadocsDocumentType") or "", "created": f.get("Created"), "modified": f.get("Modified"),
                                "size": int(f.get("File_x0020_Size") or 0) if str(f.get("File_x0020_Size") or "").isdigit() else 0})
                if ops:
                    from pymongo import UpdateOne
                    res = await db.zetadocs_memory.bulk_write([UpdateOne({"_id": o["_id"]}, {"$set": o, "$setOnInsert": {"has_text": False}}, upsert=True)
                                                               for o in ops], ordered=False)
                    stats["new"] += res.upserted_count
                url = j.get("@odata.nextLink")
                pos[lib] = url
            stats[f"done:{lib}"] = int(not url)
            if not url:
                pos.pop(lib, None)
    stats["seconds"] = int(time.time() - t0)
    await db.learning_state.update_one({"_id": "zetadocs"}, {"$set": {"next": pos, "labels_at": _now(), "labels": dict(stats)}}, upsert=True)
    return dict(stats)


async def read_text(db, seconds: int = 1500, workers: int = 4) -> Dict[str, Any]:
    """Read the first pages of labelled files that have none yet: files on
    orders first, newest first; a few at a time."""
    import httpx
    t0, stats = time.time(), collections.Counter()
    box: Dict[str, Any] = {}
    async with httpx.AsyncClient(timeout=180) as c:
        s = await _site(c, box)
        await _graph(c, f"{G}/sites/{s['id']}", box)  # token before the workers start

        async def one(m):
            if m.get("size") and m["size"] > MAX_BYTES:
                await db.zetadocs_memory.update_one({"_id": m["_id"]}, {"$set": {"read_failed": True}})
                return
            try:
                r = await _graph(c, f"{G}/sites/{s['id']}/lists/{s['lists'][m['lib']]}/items/{m['list_item_id']}/driveItem/content", box)
            except httpx.TransportError:
                stats["read_errors"] += 1
                return
            text = ""
            if r.status_code == 200:
                fn = pdf_text if m["ext"] == "pdf" else xlsx_text
                text = await asyncio.get_running_loop().run_in_executor(None, fn, r.content)
            stats["read" if text else "no_text"] += 1
            await db.zetadocs_memory.update_one({"_id": m["_id"]}, {"$set": {
                "text": text, "has_text": bool(text), "read_failed": not text, "read_at": _now()}})

        for first in (True, False):
            q = {"has_text": False, "ext": {"$in": sorted(READ_EXT)}, "read_failed": {"$ne": True},
                 "record_type": {"$in" if first else "$nin": list(READ_FIRST)}}
            batch: List[Dict[str, Any]] = []
            async for m in db.zetadocs_memory.find(q, {"_id": 1, "lib": 1, "list_item_id": 1, "ext": 1, "size": 1}).sort("created", -1):
                if time.time() - t0 > seconds:
                    break
                batch.append(m)
                if len(batch) >= workers:
                    await asyncio.gather(*(one(x) for x in batch))
                    batch = []
            if batch and time.time() - t0 <= seconds:
                await asyncio.gather(*(one(x) for x in batch))
    stats["seconds"] = int(time.time() - t0)
    await db.learning_state.update_one({"_id": "zetadocs"}, {"$set": {"text_at": _now(), "text": dict(stats)}}, upsert=True)
    return dict(stats)
