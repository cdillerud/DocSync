"""
GPI Document Hub - New Item Requests (items@gamerpackaging.com -> Packaging Catalog)

OFF BY DEFAULT. Reps request new items on the Inside Sales "New Item Template"
(an .xlsx with an Instructions tab and one "New Item Request Form" tab per
item type: Vessel, Closure, Cans, Can End, Carriers, Other) and send it to
items@gamerpackaging.com, where Sales Ops approves it and sets the item up in
Business Central.

When ``NEW_ITEM_REQUESTS_ENABLED=true`` the Hub reads each request form it
ingests (from items@ once that mailbox is a mailbox source, or from any other
mailbox it watches) cell by cell, one record per filled tab, and posts the
fields to the Commercial AI catalog intake (``/api/v70/catalog/intake/new-items``).
The catalog keeps them until the BC item exists and then proposes the item's
Packaging Catalog row from them; it also checks the vendor against BC.

The form is read by its layout, never by AI: the label is in column A, the
value in column B. A tab whose Item No. is blank is an unused tab.

Design rules (as the catalog forward):
  * The ingestion hook never raises and never blocks the poller.
  * Every decision is stored on the ``hub_documents`` record under
    ``new_item_request`` and in the ``new_item_request_log`` collection.
  * A form is sent at most once (claimed atomically; ``new_item_request_sent_utc``).
  * The intake key is never logged or stored.

Settings (environment, read on every call):
  NEW_ITEM_REQUESTS_ENABLED   true/false, default false
  NEW_ITEM_REQUESTS_DRY_RUN   true/false, default false: read and record, send nothing
  NEW_ITEM_REQUESTS_URL       default: CATALOG_FORWARD_URL with /submit -> /new-items
  NEW_ITEM_REQUESTS_KEY       default: CATALOG_FORWARD_KEY
"""

from __future__ import annotations

import asyncio
import io
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

from deps import get_db

logger = logging.getLogger(__name__)

LOG_COLLECTION = "new_item_request_log"
EXTENSIONS = {".xlsx", ".xlsm"}
MAX_FILE_BYTES = 10 * 1024 * 1024
MAX_ROWS_PER_TAB = 80
POST_TIMEOUT_SECONDS = 60.0
BC_DESCRIPTION_MAX = 100
BC_ITEM_NO_MAX = 20

FORM_TITLE_RE = re.compile(r"new\s+item\s+request\s+form", re.IGNORECASE)
ITEMS_MAILBOX_RE = re.compile(r"items@gamerpackaging\.com", re.IGNORECASE)
PAGE_SPLIT_RE = re.compile(r"_doc\d+\.[A-Za-z0-9]+$", re.IGNORECASE)
FILE_HINT_RE = re.compile(r"new[\s_-]*item|item[\s_-]*request|item[\s_-]*template", re.IGNORECASE)

# Header labels (normalized) -> record keys. Everything between the "Attributes"
# row and the "Final Extended Text View" row is an attribute, kept by its label.
HEADER_FIELDS = {
    "item no": "item_no",
    "item category": "item_category",
    "item classification": "item_classification",
    "bc vendor no": "bc_vendor_no",
    "vendor item no": "vendor_item_no",
    "bc customer no": "bc_customer_no",
    "customer item no": "customer_item_no",
    "unit of measure": "unit_of_measure",
    "sales uom": "sales_uom",
    "purchase uom": "purchase_uom",
    "warehouse uom": "warehouse_uom",
    "ea/case (only if case packed)": "ea_per_case",
    "ea/case": "ea_per_case",
    "ea/pallet": "ea_per_pallet",
    "pallets/truck": "pallets_per_truck",
    "pallets/container": "pallets_per_container",
    "packout extended text": "packout_text",
    "dims & wt extended text": "dims_weight_text",
}
FINAL_FIELDS = {
    "description": "description",
    "packout extended text": "packout_text",
    "dims & wt extended text": "dims_weight_text",
}
SKIP_SHEETS = {"instructions", "dropdown options"}
ERROR_VALUES = {"#VALUE!", "#REF!", "#N/A", "#NAME?", "#DIV/0!", "#NUM!", "#NULL!"}

_background_tasks: "set[asyncio.Task]" = set()


# =============================================================================
# Settings
# =============================================================================

def _env_flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class NewItemRequestSettings:
    enabled: bool
    url: str
    key: str
    dry_run: bool

    def public(self) -> Dict[str, Any]:
        return {"enabled": self.enabled, "dry_run": self.dry_run, "url": self.url, "key_configured": bool(self.key)}


def get_settings() -> NewItemRequestSettings:
    url = os.environ.get("NEW_ITEM_REQUESTS_URL", "").strip()
    if not url:
        forward = os.environ.get("CATALOG_FORWARD_URL", "").strip()
        url = re.sub(r"/submit/?$", "/new-items", forward) if forward.rstrip("/").endswith("/submit") else ""
    key = (os.environ.get("NEW_ITEM_REQUESTS_KEY", "").strip()
           or os.environ.get("CATALOG_FORWARD_KEY", "").strip())
    return NewItemRequestSettings(enabled=_env_flag("NEW_ITEM_REQUESTS_ENABLED"), url=url, key=key,
                                  dry_run=_env_flag("NEW_ITEM_REQUESTS_DRY_RUN"))


# =============================================================================
# Reading the form (pure functions)
# =============================================================================

def _label(value: Any) -> str:
    text = re.sub(r"\s+", " ", str(value or "")).strip().lower()
    return text.rstrip(".: ").replace(" .", ".")


def _cell(value: Any) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        return str(int(value))
    if isinstance(value, datetime):
        return value.date().isoformat()
    return re.sub(r"\s+", " ", str(value)).strip()


def _is_form_sheet(rows: List[Tuple[Any, ...]]) -> bool:
    return any(FORM_TITLE_RE.search(_cell(r[0] if r else "")) for r in rows[:3])


def read_form_sheet(title: str, rows: List[Tuple[Any, ...]]) -> Optional[Dict[str, Any]]:
    """One tab of the form -> a record, or None for an unused tab (no Item No.)."""
    rec: Dict[str, Any] = {"sheet": title, "attributes": {}, "issues": []}
    section = "header"
    notes: List[str] = []
    for row in rows[:MAX_ROWS_PER_TAB]:
        if not row:
            continue
        label = _label(row[0])
        value = _cell(row[1] if len(row) > 1 else None)
        if not label:
            continue
        if label == "attributes":
            section = "attributes"
            continue
        if label.startswith("final extended text"):
            section = "final"
            continue
        if value in ERROR_VALUES:
            rec["issues"].append(f"{_cell(row[0])} shows {value} on the form")
            continue
        if label == "additional notes":
            if value and value not in ("0",):
                notes.append(value)
            continue
        if section == "header":
            key = HEADER_FIELDS.get(label)
            if key and value and not rec.get(key):
                rec[key] = value
        elif section == "attributes":
            if value:
                rec["attributes"][_cell(row[0]).strip()] = value
        else:
            key = FINAL_FIELDS.get(label)
            if key and value and value not in ("0", ",", ", ,") and not rec.get(key):
                rec[key] = value
    if not rec.get("item_no"):
        return None
    if notes:
        rec["additional_notes"] = notes[-1]
    desc = rec.get("description", "")
    if desc:
        rec["description"] = re.sub(r"(?:,\s*)+$", "", desc).strip()
        if len(rec["description"]) > BC_DESCRIPTION_MAX:
            rec["issues"].append(f"Description is {len(rec['description'])} characters (BC allows {BC_DESCRIPTION_MAX})")
    if len(rec["item_no"]) > BC_ITEM_NO_MAX:
        rec["issues"].append(f"Item No. '{rec['item_no']}' is {len(rec['item_no'])} characters (BC allows {BC_ITEM_NO_MAX})")
    if not rec.get("item_classification"):
        rec["issues"].append("Item Classification is blank")
    return rec


def parse_workbook(data: bytes) -> Tuple[bool, List[Dict[str, Any]], List[str]]:
    """(is a New Item Template, records, issues about the whole file)."""
    import openpyxl

    try:
        wb = openpyxl.load_workbook(io.BytesIO(data), read_only=True, data_only=True)
    except Exception as exc:  # noqa: BLE001
        return False, [], [f"could not open the workbook: {type(exc).__name__}"]
    is_form = False
    records: List[Dict[str, Any]] = []
    issues: List[str] = []
    try:
        for ws in wb.worksheets:
            rows = [tuple(r) for r in ws.iter_rows(min_row=1, max_row=MAX_ROWS_PER_TAB, max_col=3, values_only=True)]
            title = str(ws.title or "")
            if title.strip().lower() in SKIP_SHEETS:
                if title.strip().lower() == "instructions" and any(
                        ITEMS_MAILBOX_RE.search(_cell(c)) for r in rows for c in r if c is not None):
                    is_form = True
                continue
            if not _is_form_sheet(rows):
                continue
            is_form = True
            rec = read_form_sheet(title, rows)
            if rec:
                records.append(rec)
    finally:
        try:
            wb.close()
        except Exception:  # noqa: BLE001
            pass
    if is_form and not records:
        issues.append("no tab has an Item No. filled in")
    seen: Dict[str, str] = {}
    for rec in records:
        no = rec["item_no"].upper()
        if no in seen:
            issues.append(f"Item No. {rec['item_no']} is on two tabs ({seen[no]} and {rec['sheet']}); the last one counts")
        seen[no] = rec["sheet"]
    return is_form, records, issues


def might_be_request(doc: Dict[str, Any]) -> Tuple[bool, str]:
    """Cheap filter before the file is opened."""
    if doc.get("new_item_request_sent_utc"):
        return False, "already_sent"
    if doc.get("is_duplicate"):
        return False, "duplicate_copy"
    file_name = str(doc.get("file_name") or "")
    if PAGE_SPLIT_RE.search(file_name) or doc.get("parent_document_id") or doc.get("split_parent_id"):
        return False, "page_split_copy"
    ext = os.path.splitext(file_name)[1].lower()
    if ext not in EXTENSIONS:
        return False, f"not_a_workbook:{ext or 'none'}"
    size = doc.get("file_size")
    if isinstance(size, (int, float)) and size > MAX_FILE_BYTES:
        return False, "file_too_large"
    return True, "workbook"


# =============================================================================
# Recording, sending
# =============================================================================

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _record(db, doc: Dict[str, Any], status: str, reason: str, extra: Optional[Dict[str, Any]] = None,
                  log: bool = True) -> None:
    entry = {"status": status, "reason": reason, "decided_utc": _now(), **(extra or {})}
    try:
        update: Dict[str, Any] = {"new_item_request": entry}
        if status == "sent":
            update["new_item_request_sent_utc"] = entry["decided_utc"]
        await db.hub_documents.update_one({"id": doc.get("id")}, {"$set": update})
        if log:
            await db[LOG_COLLECTION].insert_one({"document_id": doc.get("id"), "file_name": doc.get("file_name"),
                                                 "email_subject": doc.get("email_subject"),
                                                 "sender": doc.get("email_sender") or doc.get("sender"), **entry})
    except Exception as exc:  # noqa: BLE001
        logger.warning("[NewItemRequests] could not record decision for %s: %s", doc.get("id"), exc)
    logger.info("[NewItemRequests] %s %s (%s) %s", status, doc.get("file_name"), doc.get("id"), reason)


async def _claim(db, doc_id: str) -> bool:
    result = await db.hub_documents.update_one(
        {"id": doc_id, "new_item_request_sent_utc": {"$in": [None, ""]},
         "new_item_request.status": {"$ne": "sending"}},
        {"$set": {"new_item_request": {"status": "sending", "reason": "claimed", "decided_utc": _now()}}},
    )
    return bool(getattr(result, "modified_count", 0))


async def _post(settings: NewItemRequestSettings, payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=POST_TIMEOUT_SECONDS) as client:
        resp = await client.post(settings.url, json=payload,
                                 headers={"X-GPI-Intake-Key": settings.key, "Content-Type": "application/json"})
    if resp.status_code >= 400:
        raise RuntimeError(f"catalog intake returned HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {}
    status = str((body or {}).get("status") or "").upper()
    if status and status != "ACCEPTED":
        raise RuntimeError(f"catalog intake answered status {status}")
    return body or {}


async def _load_bytes(doc: Dict[str, Any]) -> Optional[bytes]:
    from services.catalog_forward import load_document_bytes
    return await load_document_bytes(doc)


def _payload(doc: Dict[str, Any], records: List[Dict[str, Any]], issues: List[str]) -> Dict[str, Any]:
    return {
        "source": "gpi_hub",
        "document_id": doc.get("id"),
        "file_name": doc.get("file_name"),
        "email_subject": doc.get("email_subject"),
        "sender": doc.get("email_sender") or doc.get("sender") or "",
        "received_utc": doc.get("email_received_utc") or doc.get("created_utc") or _now(),
        "document_url": doc.get("sharepoint_web_url") or doc.get("sharepoint_url") or "",
        "records": records,
        "issues": issues,
    }


async def process_document(db, doc: Dict[str, Any], settings: NewItemRequestSettings) -> str:
    """Read one document; send it when it is a request form. Returns the status recorded."""
    ok, reason = might_be_request(doc)
    if not ok:
        if reason != "already_sent":
            await _record(db, doc, "skipped", reason, log=False)
        return "skipped"
    try:
        data = await _load_bytes(doc)
    except Exception as exc:  # noqa: BLE001
        await _record(db, doc, "failed", f"file_unreadable:{type(exc).__name__}")
        return "failed"
    if not data:
        await _record(db, doc, "failed", "file_unavailable")
        return "failed"
    is_form, records, issues = parse_workbook(data)
    if not is_form:
        await _record(db, doc, "skipped", "not_a_new_item_request", log=False)
        return "skipped"
    summary = {"records": len(records), "items": [r["item_no"] for r in records][:50],
               "issues": issues + [f"{r['item_no']}: {i}" for r in records for i in r.get("issues") or []]}
    if not records:
        await _record(db, doc, "failed", "form_without_items", summary)
        return "failed"
    if settings.dry_run:
        await _record(db, doc, "dry_run", "new_item_request", summary)
        return "dry_run"
    if not (settings.url and settings.key):
        await _record(db, doc, "failed", "not_configured:NEW_ITEM_REQUESTS_URL/KEY missing", summary)
        return "failed"
    if not await _claim(db, doc.get("id")):
        return "skipped"
    try:
        answer = await _post(settings, _payload(doc, records, issues))
    except Exception as exc:  # noqa: BLE001
        await _record(db, doc, "failed", f"send_failed:{exc}"[:200], summary)
        return "failed"
    await _record(db, doc, "sent", "new_item_request",
                  {**summary, "stored": answer.get("stored"), "skipped_by_catalog": answer.get("skipped")})
    return "sent"


async def process_documents(doc_ids: Iterable[str], settings: Optional[NewItemRequestSettings] = None) -> Dict[str, Any]:
    settings = settings or get_settings()
    out: Dict[str, Any] = {"enabled": settings.enabled, "dry_run": settings.dry_run, "counts": {}}
    if not settings.enabled:
        out["reason"] = "disabled"
        return out
    db = get_db()
    for doc_id in [i for i in dict.fromkeys(doc_ids or []) if i]:
        doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "file_content_b64": 0})
        if not doc:
            continue
        if not os.path.splitext(str(doc.get("file_name") or ""))[1].lower() in EXTENSIONS:
            continue  # most attachments: not a workbook, nothing to record
        status = await process_document(db, doc, settings)
        out["counts"][status] = out["counts"].get(status, 0) + 1
    return out


async def process_documents_safely(doc_ids: Iterable[str]) -> Optional[Dict[str, Any]]:
    try:
        return await process_documents(list(doc_ids or []))
    except Exception as exc:  # noqa: BLE001
        logger.error("[NewItemRequests] error (ingestion unaffected): %r", exc)
        return None


def schedule_for_email(doc_ids: Iterable[str]) -> None:
    """Hook for the email pollers: the documents just ingested from one email. Returns at once; never raises."""
    try:
        if not get_settings().enabled:
            return
        ids = [i for i in (doc_ids or []) if i]
        if not ids:
            return
        task = asyncio.get_running_loop().create_task(process_documents_safely(ids))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except Exception as exc:  # noqa: BLE001
        logger.error("[NewItemRequests] hook error (ingestion unaffected): %r", exc)


# =============================================================================
# Backfill and status (admin)
# =============================================================================

async def backfill(days: int = 120, limit: int = 500, dry_run: Optional[bool] = None) -> Dict[str, Any]:
    """Send the request forms the Hub already holds (workbooks whose name looks like a new item request, received in
    the last ``days`` days, not sent yet), oldest first so the newest request for an item wins."""
    settings = get_settings()
    if dry_run:  # a dry run reads and records even while sending is off
        settings = NewItemRequestSettings(enabled=True, url=settings.url, key=settings.key, dry_run=True)
    elif not settings.enabled:
        return {"enabled": False, "reason": "disabled (a dry run works while it is off)"}
    elif dry_run is False:
        settings = NewItemRequestSettings(enabled=True, url=settings.url, key=settings.key, dry_run=False)
    db = get_db()
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(int(days), 1100)))).isoformat()
    query = {"file_name": {"$regex": r"\.xls[xm]$", "$options": "i"},
             "new_item_request_sent_utc": {"$in": [None, ""]},
             "created_utc": {"$gte": since}}
    docs = await db.hub_documents.find(query, {"_id": 0, "file_content_b64": 0}).sort("created_utc", 1) \
        .to_list(max(1, min(int(limit), 2000)) * 4)
    candidates = [d for d in docs if FILE_HINT_RE.search(str(d.get("file_name") or ""))][: max(1, min(int(limit), 2000))]
    counts: Dict[str, int] = {}
    for doc in candidates:
        status = await process_document(db, doc, settings)
        counts[status] = counts.get(status, 0) + 1
    return {"enabled": True, "dry_run": settings.dry_run, "since": since, "candidates": len(candidates), "counts": counts}


async def get_status(limit: int = 50) -> Dict[str, Any]:
    limit = max(1, min(int(limit or 50), 500))
    db = get_db()
    recent = await db[LOG_COLLECTION].find({}, {"_id": 0}).sort("decided_utc", -1).limit(limit).to_list(limit)
    counts: Dict[str, int] = {}
    for row in recent:
        counts[row.get("status", "unknown")] = counts.get(row.get("status", "unknown"), 0) + 1
    return {"settings": get_settings().public(), "counts_in_recent": counts, "recent": recent}


__all__ = ["NewItemRequestSettings", "backfill", "get_settings", "get_status", "might_be_request", "parse_workbook",
           "process_document", "process_documents", "read_form_sheet", "schedule_for_email"]
