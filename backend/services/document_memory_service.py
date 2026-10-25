"""Document memory: every document AP has already handled, as examples.

The AP library on SharePoint (GamerAccounting / Accounts Payable) holds
~44,000 documents staff have filed since 2012 - paid invoices by check
date, wires, DO NOT PAY, the Temp Folder lanes, inventory disposals - and
where each one sits (and what staff named it) is a record of what happened
to it. The Hub's own documents add what the Hub saw and what AP entered in
BC. Both go into document_memory with the first pages' text, so that for
a new document the AI can be shown the past documents most like it and
what became of them (similar(), used by classification and routing as one
more learned source next to the ones already there).

Nothing here decides anything; it remembers. Read-only against SharePoint
(GET only). harvest() is incremental: files already remembered (same item
id and modified time) are skipped, so the hourly learning cycle only reads
what is new.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import math
import re
import time
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger("document_memory")

SP_HOST = "gamerpackaging1.sharepoint.com"
SP_SITE = "/sites/GamerAccounting"
SP_ROOT = "General/Accounting/Accounts Payable"
TEXT_CHARS = 4000          # first pages are what identify a document
TEXT_PAGES = 2
MAX_BYTES = 25_000_000
READ_EXT = {"pdf"}
HARVEST_SECONDS = 1500     # per learning-cycle run; the first full read takes several runs


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def pdf_text(data: bytes) -> str:
    try:
        import fitz  # pymupdf
        with fitz.open(stream=data, filetype="pdf") as doc:
            out = []
            for i, page in enumerate(doc):
                if i >= TEXT_PAGES:
                    break
                out.append(page.get_text("text"))
        return re.sub(r"[ \t]+", " ", "\n".join(out)).strip()[:TEXT_CHARS]
    except Exception:
        return ""


def _labels(path: str) -> Dict[str, Any]:
    """Folder levels with date-only folders (2016, 160101) kept apart: they
    say when, not what."""
    parts = [p for p in path.split("/") if p]
    what = [p for p in parts if not re.fullmatch(r"\d{4}|\d{6}|\d{8}", p)]
    return {"folder": "/".join(parts), "top": parts[0] if parts else "", "kind": "/".join(what[:3])}


async def _graph(client, url: str, token_box: Dict[str, Any], stream: bool = False):
    import httpx
    from services.config_service import get_graph_token
    for attempt in range(4):
        if not token_box.get("t") or time.time() - token_box.get("at", 0) > 2400:
            token_box["t"], token_box["at"] = await get_graph_token(), time.time()
        try:
            r = await client.get(url, headers={"Authorization": f"Bearer {token_box['t']}"}, follow_redirects=True)
        except httpx.TransportError:
            # A dropped connection (ReadError) ended a whole pass on 2026-10-25.
            if attempt == 3:
                raise
            await asyncio.sleep(2 ** attempt * 3)
            continue
        if r.status_code == 429 or r.status_code >= 500:
            await asyncio.sleep(float(r.headers.get("Retry-After") or 2 ** attempt * 3))
            continue
        if r.status_code == 401:
            token_box["t"] = None
            continue
        return r
    return r


async def harvest(db, seconds: int = HARVEST_SECONDS) -> Dict[str, Any]:
    """Remember new or changed files of the AP library (text of PDFs)."""
    import httpx
    t0, stats = time.time(), collections.Counter()
    box: Dict[str, Any] = {}
    await db.document_memory.create_index("item_id")
    await db.document_memory.create_index("source")
    known = {m["item_id"]: m.get("modified") async for m in db.document_memory.find({"source": "sharepoint_ap"}, {"_id": 0, "item_id": 1, "modified": 1})}
    async with httpx.AsyncClient(timeout=120) as c:
        site = (await _graph(c, f"https://graph.microsoft.com/v1.0/sites/{SP_HOST}:{SP_SITE}:", box)).json()
        drives = (await _graph(c, f"https://graph.microsoft.com/v1.0/sites/{site['id']}/drives", box)).json()["value"]
        drive = next(d for d in drives if d["name"] in ("Documents", "Shared Documents"))
        base = f"https://graph.microsoft.com/v1.0/drives/{drive['id']}"
        queue = [SP_ROOT]
        while queue and time.time() - t0 < seconds:
            path = queue.pop()
            url = f"{base}/root:/{path}:/children?$top=999&$select=id,name,folder,file,size,createdDateTime,lastModifiedDateTime,webUrl"
            while url and time.time() - t0 < seconds:
                r = await _graph(c, url, box)
                if r.status_code != 200:
                    stats["list_errors"] += 1
                    break
                j = r.json()
                for x in j.get("value", []):
                    if x.get("folder"):
                        queue.append(f"{path}/{x['name']}")
                        continue
                    stats["files"] += 1
                    if known.get(x["id"]) == x.get("lastModifiedDateTime"):
                        continue
                    rel = path[len(SP_ROOT):].strip("/")
                    ext = x["name"].rsplit(".", 1)[-1].lower() if "." in x["name"] else ""
                    text = ""
                    if ext in READ_EXT and (x.get("size") or 0) <= MAX_BYTES:
                        try:
                            rr = await _graph(c, f"{base}/items/{x['id']}/content", box)
                        except httpx.TransportError:
                            stats["read_errors"] += 1
                            continue
                        if rr.status_code == 200:
                            text = await asyncio.get_running_loop().run_in_executor(None, pdf_text, rr.content)
                        stats["read" if text else "no_text"] += 1
                    await db.document_memory.update_one({"item_id": x["id"]}, {"$set": {
                        "source": "sharepoint_ap", "item_id": x["id"], "name": x["name"], "ext": ext,
                        **_labels(rel), "created": x.get("createdDateTime"), "modified": x.get("lastModifiedDateTime"),
                        "web_url": x.get("webUrl"), "text": text, "harvested_at": _now()}}, upsert=True)
                    stats["remembered"] += 1
                url = j.get("@odata.nextLink")
    stats["complete"] = int(not queue)
    stats["seconds"] = int(time.time() - t0)
    await db.learning_state.update_one({"_id": "document_memory"}, {"$set": {"harvested_at": _now(), "last": dict(stats)}}, upsert=True)
    _INDEX.clear()
    return dict(stats)


# ------------------------------------------------------------- retrieval
_WORD = re.compile(r"[A-Za-z][A-Za-z&'-]{2,}|\d{3,}")
_INDEX: Dict[str, Any] = {}
INDEX_SECONDS = 1800


def _toks(s: str) -> List[str]:
    out = []
    for w in _WORD.findall(s or ""):
        w = w.upper()
        out.append("#" + re.sub(r"\d", "9", w) if w[0].isdigit() else w)
    return out


def _vec(toks: List[str], idf: Dict[str, float]) -> Dict[str, float]:
    tf = collections.Counter(t for t in toks if t in idf)
    v = {t: (1 + math.log(n)) * idf[t] for t, n in tf.items()}
    norm = math.sqrt(sum(x * x for x in v.values())) or 1.0
    return {t: x / norm for t, x in v.items()}


async def _index(db) -> Dict[str, Any]:
    if _INDEX and time.time() - _INDEX["at"] < INDEX_SECONDS:
        return _INDEX
    docs = [m async for m in db.document_memory.find({"text": {"$ne": ""}}, {"_id": 0, "item_id": 1, "name": 1, "folder": 1,
                                                                            "kind": 1, "top": 1, "created": 1, "text": 1, "source": 1})]
    toks = [_toks(m["name"] + " " + m["text"]) for m in docs]
    dfc = collections.Counter(t for ts in toks for t in set(ts))
    n = len(docs) or 1
    idf = {t: math.log(n / c) for t, c in dfc.items() if 2 <= c <= n * 0.5}
    post: Dict[str, List[Tuple[int, float]]] = collections.defaultdict(list)
    for i, ts in enumerate(toks):
        for t, w in _vec(ts, idf).items():
            post[t].append((i, w))
    for m in docs:
        m.pop("text", None)
    _INDEX.clear()
    _INDEX.update({"at": time.time(), "docs": docs, "idf": idf, "post": post})
    return _INDEX


async def similar(db, text: str, name: str = "", k: int = 5, exclude: Optional[set] = None) -> List[Dict[str, Any]]:
    """The k remembered documents most like this one (cosine over IDF-
    weighted words of name + first pages), most similar first."""
    ix = await _index(db)
    q = _vec(_toks((name or "") + " " + (text or "")), ix["idf"])
    score: Dict[int, float] = collections.defaultdict(float)
    for t, w in q.items():
        for i, x in ix["post"].get(t, ()):
            score[i] += w * x
    out = []
    for i, s in sorted(score.items(), key=lambda kv: -kv[1]):
        m = ix["docs"][i]
        if exclude and m["item_id"] in exclude:
            continue
        out.append({**m, "similarity": round(s, 3)})
        if len(out) >= k:
            break
    return out


MEMORY_MINUTES = 60


async def document_memory_scheduler() -> None:
    """Keep document memory current: the first full read of the AP library
    runs over several passes (it resumes where it stopped); after that each
    hourly pass lists the library and reads only new or changed files."""
    import os
    if os.environ.get("DOCUMENT_MEMORY_ENABLED", "true").strip().lower() == "false":
        return
    await asyncio.sleep(900)
    while True:
        from deps import get_db
        r: Dict[str, Any] = {}
        for name, step in (("sharepoint", lambda: harvest(get_db(), seconds=3000)), ("hub", lambda: harvest_hub(get_db())),
                           ("outcomes_refreshed", lambda: refresh_hub_outcomes(get_db()))):
            try:
                r[name] = await step()
            except Exception as e:
                r[name] = {"error": repr(e)[:200]}
        logger.info("[DocumentMemory] %s", r)
        await asyncio.sleep(MEMORY_MINUTES * 60)


async def harvest_hub(db, limit: int = 0) -> Dict[str, Any]:
    """The Hub's own documents, with what became of each: the Hub's type,
    where staff filed it (folder_filings) and whether AP entered it in BC
    (bc_link). Text from the stored file; incremental by document id."""
    import base64
    stats = collections.Counter()
    filed = {f["hub_doc_id"]: (f.get("top") or "") + ("/" + f["subpath"] if f.get("subpath") else "")
             async for f in db.folder_filings.find({}, {"_id": 0, "hub_doc_id": 1, "top": 1, "subpath": 1})}
    have = set(await db.document_memory.distinct("item_id", {"source": "hub"}))
    q = {"file_content_b64": {"$exists": True, "$ne": None}}
    async for d in db.hub_documents.find(q, {"_id": 0, "id": 1}).sort("created_utc", 1):
        if d["id"] in have:
            continue
        full = await db.hub_documents.find_one({"id": d["id"]}, {"_id": 0, "id": 1, "file_name": 1, "file_content_b64": 1, "document_type": 1,
                                                                "vendor_canonical": 1, "created_utc": 1, "bc_link.bc_document_no": 1,
                                                                "email_subject": 1, "content_type": 1})
        name = full.get("file_name") or ""
        text = ""
        if name.lower().endswith(".pdf") or "pdf" in str(full.get("content_type") or ""):
            try:
                data = base64.b64decode(full.get("file_content_b64") or "")
                text = await asyncio.get_running_loop().run_in_executor(None, pdf_text, data)
            except Exception:
                text = ""
        folder = filed.get(d["id"], "")
        await db.document_memory.update_one({"item_id": d["id"]}, {"$set": {
            "source": "hub", "item_id": d["id"], "name": name, "text": text, "created": full.get("created_utc"),
            "folder": folder, "top": folder.split("/")[0] if folder else "", "kind": folder,
            "doc_type": full.get("document_type"), "vendor": full.get("vendor_canonical"),
            "subject": str(full.get("email_subject") or "")[:200],
            "bc_entered": (full.get("bc_link") or {}).get("bc_document_no"), "harvested_at": _now()}}, upsert=True)
        stats["remembered"] += 1
        stats["text" if text else "no_text"] += 1
        if limit and stats["remembered"] >= limit:
            break
    _INDEX.clear()
    return dict(stats)


async def refresh_hub_outcomes(db) -> int:
    """Outcomes arrive after the document: staff file it, AP enters it."""
    filed = {f["hub_doc_id"]: (f.get("top") or "") + ("/" + f["subpath"] if f.get("subpath") else "")
             async for f in db.folder_filings.find({}, {"_id": 0, "hub_doc_id": 1, "top": 1, "subpath": 1})}
    n = 0
    async for d in db.hub_documents.find({"bc_link.bc_document_no": {"$exists": True}}, {"_id": 0, "id": 1, "bc_link.bc_document_no": 1}):
        r = await db.document_memory.update_one({"item_id": d["id"], "source": "hub", "bc_entered": {"$ne": d["bc_link"]["bc_document_no"]}},
                                                {"$set": {"bc_entered": d["bc_link"]["bc_document_no"]}})
        n += r.modified_count
    for hid, folder in filed.items():
        r = await db.document_memory.update_one({"item_id": hid, "source": "hub", "folder": {"$ne": folder}},
                                                {"$set": {"folder": folder, "top": folder.split("/")[0], "kind": folder}})
        n += r.modified_count
    return n
