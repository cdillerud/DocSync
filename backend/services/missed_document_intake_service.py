"""
missed_document_intake_service.py
=================================
Safety net for AP documents that never reach Hub by email.

Two channels, both feeding the normal intake pipeline
(document_bytes_intake_service.intake_document_from_bytes):

1. Square9 gap backfill (transition period). The cutover triage resolver
   lists Square9 AP documents Hub never received ("Bucket C"). Each one is
   downloaded from the production AP library and ingested with
   source="square9_backfill". Only Bucket C rows are used: Buckets A/B/D are
   documents Hub already holds, and re-ingesting them would duplicate them.

2. Hub Drop Folder (permanent). Anyone can drop a missed document into a
   SharePoint folder; Hub ingests new files with source="drop_folder".

Every file is recorded in missed_document_intake_log by SharePoint item id,
so a file is never ingested twice. Only PDFs and images are ingested.

Backfilled documents are excluded from the Square9 cutover match rate (they
are copies of Square9's own file) and reported separately.
"""

import asyncio
import csv
import logging
import mimetypes
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional
from urllib.parse import quote

import httpx

logger = logging.getLogger(__name__)

LOG_COLLECTION = "missed_document_intake_log"
GRAPH = "https://graph.microsoft.com/v1.0"

PROD_HOST = os.environ.get("SHAREPOINT_PROD_HOST", "gamerpackaging1.sharepoint.com")
PROD_SITE_PATH = os.environ.get("SHAREPOINT_PROD_SITE_PATH", "/sites/GamerAccounting")
PROD_LIBRARY = os.environ.get("SHAREPOINT_PROD_LIBRARY", "Shared Documents")
AP_ROOT = "General/Accounting/Accounts Payable"
# Square9 files AP work under Temp Folder; triage parent paths are relative to it.
SQUARE9_ROOT = f"{AP_ROOT}/Temp Folder"
DROP_FOLDER_PATH = os.environ.get("HUB_DROP_FOLDER_PATH", f"{AP_ROOT}/Hub Drop Folder")
TRIAGE_CSV = os.environ.get("SQUARE9_TRIAGE_RESOLVED_CSV", "prod_reports/square9_only_triage_resolved.csv")

INGESTIBLE_EXTENSIONS = {".pdf", ".png", ".jpg", ".jpeg", ".tif", ".tiff"}
SOURCE_SQUARE9_BACKFILL = "square9_backfill"
SOURCE_DROP_FOLDER = "drop_folder"


async def _token() -> str:
    from services.config_service import get_graph_token
    return await get_graph_token()


async def _prod_drive_id(client: httpx.AsyncClient, headers: Dict[str, str]) -> str:
    site = (await client.get(f"{GRAPH}/sites/{PROD_HOST}:{PROD_SITE_PATH}:", headers=headers)).json()
    if "id" not in site:
        raise RuntimeError(f"SharePoint site not resolvable: {PROD_HOST}{PROD_SITE_PATH}")
    drives = (await client.get(f"{GRAPH}/sites/{site['id']}/drives", headers=headers)).json().get("value", [])
    wanted = {PROD_LIBRARY.lower(), {"documents": "shared documents", "shared documents": "documents"}.get(PROD_LIBRARY.lower(), "")}
    drive = next((d for d in drives if (d.get("name") or "").lower() in wanted), None)
    if not drive:
        raise RuntimeError(f"Library {PROD_LIBRARY!r} not found; available: {[d.get('name') for d in drives]}")
    return drive["id"]


def _db():
    from deps import get_db
    return get_db()


async def _already_ingested(item_id: str) -> bool:
    return bool(await _db()[LOG_COLLECTION].find_one({"item_id": item_id, "status": "ingested"}, {"_id": 1}))


async def _log(item_id: str, **fields: Any) -> None:
    await _db()[LOG_COLLECTION].update_one(
        {"item_id": item_id},
        {"$set": {"item_id": item_id, "updated_at": datetime.now(timezone.utc).isoformat(), **fields}},
        upsert=True,
    )


async def _ingest_item(client: httpx.AsyncClient, headers: Dict[str, str], drive_id: str,
                       item: Dict[str, Any], source: str, origin_path: str) -> Dict[str, Any]:
    """Download one drive item and run it through normal intake."""
    item_id, name = item["id"], item.get("name", "")
    if os.path.splitext(name)[1].lower() not in INGESTIBLE_EXTENSIONS:
        return {"name": name, "status": "skipped_file_type"}
    if await _already_ingested(item_id):
        return {"name": name, "status": "already_ingested"}

    resp = await client.get(f"{GRAPH}/drives/{drive_id}/items/{item_id}/content",
                            headers=headers, follow_redirects=True)
    if resp.status_code != 200:
        await _log(item_id, name=name, source=source, origin_path=origin_path,
                   status="download_failed", error=f"HTTP {resp.status_code}")
        return {"name": name, "status": "download_failed", "http": resp.status_code}

    from services.document_bytes_intake_service import intake_document_from_bytes
    content_type = mimetypes.guess_type(name)[0] or "application/octet-stream"
    try:
        result = await intake_document_from_bytes(
            resp.content, name, content_type,
            source=source,
            subject=f"{source}: {origin_path}",
            mailbox_category="AP",
        )
    except Exception as e:  # e.g. sha256 duplicate backstop: identical bytes already in Hub
        status = "duplicate" if "duplicate" in repr(e).lower() else "intake_failed"
        await _log(item_id, name=name, source=source, origin_path=origin_path,
                   status=status, error=repr(e)[:300])
        return {"name": name, "status": status, "error": repr(e)[:120]}

    doc_id = ((result or {}).get("document") or {}).get("id")
    await _log(item_id, name=name, source=source, origin_path=origin_path,
               status="ingested", doc_id=doc_id, drive_id=drive_id,
               ingested_at=datetime.now(timezone.utc).isoformat())
    logger.info("[MissedIntake] %s ingested %s -> doc %s", source, name, doc_id)
    return {"name": name, "status": "ingested", "doc_id": doc_id}


async def backfill_square9_gaps(triage_csv: str = TRIAGE_CSV, limit: int = 50) -> Dict[str, Any]:
    """Ingest Square9 AP documents Hub never received (triage Bucket C)."""
    try:
        with open(triage_csv, newline="", encoding="utf-8") as f:
            rows = [r for r in csv.DictReader(f) if r.get("bucket") == "C"]
    except FileNotFoundError:
        return {"status": "no_triage_csv", "path": triage_csv}

    headers = {"Authorization": f"Bearer {await _token()}"}
    results: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=120) as client:
        drive_id = await _prod_drive_id(client, headers)
        for row in rows[:limit]:
            rel = "/".join(p for p in (SQUARE9_ROOT, row.get("square9_parent_path", "").strip("/"),
                                       row.get("square9_name", "")) if p)
            meta = await client.get(f"{GRAPH}/drives/{drive_id}/root:/{quote(rel, safe='/')}?$select=id,name",
                                    headers=headers)
            if meta.status_code != 200 or "id" not in meta.json():
                results.append({"name": row.get("square9_name"), "status": "not_found_in_square9"})
                continue
            results.append(await _ingest_item(client, headers, drive_id, meta.json(),
                                              SOURCE_SQUARE9_BACKFILL, row.get("square9_parent_path", "")))
    return _summary(results, bucket_c=len(rows))


async def poll_drop_folder(limit: int = 100) -> Dict[str, Any]:
    """Ingest new files in the Hub Drop Folder (non-recursive)."""
    headers = {"Authorization": f"Bearer {await _token()}"}
    results: List[Dict[str, Any]] = []
    async with httpx.AsyncClient(timeout=120) as client:
        drive_id = await _prod_drive_id(client, headers)
        url = (f"{GRAPH}/drives/{drive_id}/root:/{quote(DROP_FOLDER_PATH, safe='/')}:/children"
               f"?$select=id,name,file&$top=200")
        resp = await client.get(url, headers=headers)
        if resp.status_code == 404:
            return {"status": "drop_folder_missing", "path": DROP_FOLDER_PATH}
        resp.raise_for_status()
        files = [i for i in resp.json().get("value", []) if "file" in i][:limit]
        for item in files:
            results.append(await _ingest_item(client, headers, drive_id, item,
                                              SOURCE_DROP_FOLDER, DROP_FOLDER_PATH))
    return _summary(results)


def _summary(results: List[Dict[str, Any]], **extra: Any) -> Dict[str, Any]:
    counts: Dict[str, int] = {}
    for r in results:
        counts[r["status"]] = counts.get(r["status"], 0) + 1
    return {"status": "ok", "counts": counts, "results": results, **extra}


# -- Background runs and schedule ------------------------------------------------
# Runs take ~1 min per document (classification + extraction), far longer than
# the frontend proxy's request timeout, so they always run in the background.
RUNS: Dict[str, Dict[str, Any]] = {}


def start_background_run(name: str, coro) -> Dict[str, Any]:
    """Start a run unless one with the same name is already in progress."""
    current = RUNS.get(name)
    if current and current.get("state") == "running":
        return {"status": "already_running", **current}
    RUNS[name] = {"state": "running", "started_at": datetime.now(timezone.utc).isoformat()}

    async def _runner():
        try:
            result = await coro
            RUNS[name].update(state="done", result={k: v for k, v in result.items() if k != "results"})
        except Exception as e:
            logger.exception("[MissedIntake] %s run failed", name)
            RUNS[name].update(state="failed", error=repr(e)[:300])
        RUNS[name]["finished_at"] = datetime.now(timezone.utc).isoformat()

    asyncio.create_task(_runner())
    return {"status": "started", **RUNS[name]}


def _flag(name: str, default: str = "true") -> bool:
    return os.environ.get(name, default).strip().lower() in {"1", "true", "yes", "on"}


async def _drop_folder_loop() -> None:
    await asyncio.sleep(600)
    while True:
        if _flag("MISSED_INTAKE_DROP_FOLDER_ENABLED"):
            try:
                result = await poll_drop_folder()
                if result.get("counts"):
                    logger.info("[MissedIntake] drop folder poll: %s", result.get("counts"))
            except Exception as e:
                logger.warning("[MissedIntake] drop folder poll failed: %r", e)
        await asyncio.sleep(1800)


async def _square9_backfill_loop() -> None:
    await asyncio.sleep(1800)
    while True:
        if _flag("MISSED_INTAKE_SQUARE9_BACKFILL_ENABLED"):
            start_background_run("square9_backfill", backfill_square9_gaps())
        await asyncio.sleep(24 * 3600)


def start_missed_intake_tasks() -> None:
    """Start the drop-folder poll (30 min) and daily Square9 gap backfill."""
    asyncio.create_task(_drop_folder_loop())
    asyncio.create_task(_square9_backfill_loop())
    logger.info("[MissedIntake] safety-net schedulers started")
