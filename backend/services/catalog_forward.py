"""
GPI Document Hub - Catalog Forward (supplier pricing -> Commercial AI catalog inbox)

OFF BY DEFAULT. When ``CATALOG_FORWARD_ENABLED=true``, supplier pricing
documents that the Hub has just ingested (supplier price lists, supplier
quotes, price-increase / surcharge letters, stock / availability lists) are
sent to the Commercial AI "catalog inbox" so the catalog reviewers get the
usual review email for the Packaging Catalog.

Design rules:
  * The ingestion hook (``schedule_forward_for_email``) never raises and never
    blocks the poller: it starts a background task and logs any failure.
  * Every decision (qualified / skipped + reason, sent / dry run / failed) is
    stored on the ``hub_documents`` record under ``catalog_forward`` and in the
    small ``catalog_forward_log`` collection (read by the admin status route).
  * A document is sent at most once: it is claimed atomically before sending
    and ``catalog_forwarded_utc`` is set after the inbox accepts it.
  * All qualifying attachments of one email go in one submit (split only when
    the request would get too large). Files over 15 MB are skipped.
  * The intake key is never logged or stored.

Settings (environment, read on every call so a container restart picks them up):
  CATALOG_FORWARD_ENABLED   true/false, default false
  CATALOG_FORWARD_URL       the catalog inbox submit URL
  CATALOG_FORWARD_KEY       the X-GPI-Intake-Key value (secret)
  CATALOG_FORWARD_DRY_RUN   true/false, default false: decide and log, send nothing
"""

from __future__ import annotations

import asyncio
import base64
import logging
import os
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, Iterable, List, Optional, Tuple

import httpx

from deps import get_db

logger = logging.getLogger(__name__)

LOG_COLLECTION = "catalog_forward_log"

# The catalog inbox accepts these file types.
FORWARD_EXTENSIONS = {".xlsx", ".xlsm", ".csv", ".pdf", ".msg", ".eml"}
MAX_FILE_BYTES = 15 * 1024 * 1024
# The inbox takes ~40 MB per request; base64 adds a third, so keep the raw
# bytes of one submit under 28 MB.
MAX_REQUEST_RAW_BYTES = 28 * 1024 * 1024
POST_TIMEOUT_SECONDS = 300.0
GAMER_DOMAIN = "gamerpackaging.com"

# Classifier labels (models/document_types.py job types and the
# workflows.core.engine.DocType enum) that may hold a supplier pricing
# document. Every other label (AP_Invoice, Statement, Remittance,
# Purchase_Order, Sales_PO, Sales_Order, Order_Confirmation, ...) is excluded.
ALLOWED_JOB_TYPES = {
    "", "sales_quote", "inventory_report", "price_list",
    "unknown_document", "unknown", "other",
}
ALLOWED_DOC_TYPES = {"", "other", "unknown"}

# Pricing signals, matched on a normalized file name / subject
# (lower case; "_", "-", "." turned into spaces).
PRICING_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("price_increase", re.compile(r"\bprice\s*increases?\b|\bincrease\s+notice\b|\bprice\s*adjustments?\b")),
    ("surcharge", re.compile(r"\bsurcharges?\b")),
    ("price_list", re.compile(r"\bprice\s*lists?\b|\bpricelists?\b|\bprice\s*sheets?\b|\bpricing\b|\bprices?\b")),
    ("quote", re.compile(r"\bquot(e|es|ed|ation|ations)\b")),
    ("rfq_response", re.compile(r"\brfq\s+(response|reply)\b|\b(response|reply)\s+to\s+rfq\b")),
    ("availability", re.compile(r"\bavailability\b")),
    ("stock_list", re.compile(r"\bshelf\s*stock\b|\bstock\s*(list|report|sheet|position|levels?)\b|\bstock\b")),
    ("open_inventory", re.compile(r"\bopen\s+inventory\b")),
]

# Signals of a transactional / AP document; a file name with one of these is
# never forwarded, and a subject with one does not count as a pricing signal.
EXCLUDE_PATTERNS: List[Tuple[str, re.Pattern]] = [
    ("invoice", re.compile(r"\binvoices?\b|\binv\b|\binv\s*#|\binv\d")),
    ("statement", re.compile(r"\bstatements?\b|\bstmt\b")),
    ("remittance", re.compile(r"\bremit(tance)?\b|\bpayment\s+advice\b")),
    ("credit_memo", re.compile(r"\b(credit|debit)\s+memo\b")),
    ("purchase_order", re.compile(r"\bpurchase\s+order\b|\bp\s?o\s*#|\bpo\s*\d")),
    ("packing_or_bol", re.compile(r"\bpacking\s+(slip|list)\b|\bbill\s+of\s+lading\b|\bbol\b")),
]

# Gamer's own Spiro quote numbers to customers, e.g. "QUO-1234-".
GAMER_QUOTE_RE = re.compile(r"\bQUO-\d+", re.IGNORECASE)
# Page-split copies made by the Hub, e.g. "scan_doc1.pdf".
PAGE_SPLIT_RE = re.compile(r"_doc\d+\.[A-Za-z0-9]+$", re.IGNORECASE)
EMAIL_RE = re.compile(r"[\w.+'-]+@([\w-]+(?:\.[\w-]+)+)")

# Strong references to background tasks so they are not garbage collected.
_background_tasks: "set[asyncio.Task]" = set()


# =============================================================================
# Settings
# =============================================================================

def _env_flag(name: str, default: str = "false") -> bool:
    return os.environ.get(name, default).strip().lower() in ("1", "true", "yes", "on")


@dataclass(frozen=True)
class CatalogForwardSettings:
    enabled: bool
    url: str
    key: str
    dry_run: bool

    def public(self) -> Dict[str, Any]:
        """Settings safe to show (the key is reduced to set / not set)."""
        return {
            "enabled": self.enabled,
            "dry_run": self.dry_run,
            "url": self.url,
            "key_configured": bool(self.key),
        }


def get_settings() -> CatalogForwardSettings:
    return CatalogForwardSettings(
        enabled=_env_flag("CATALOG_FORWARD_ENABLED"),
        url=os.environ.get("CATALOG_FORWARD_URL", "").strip(),
        key=os.environ.get("CATALOG_FORWARD_KEY", "").strip(),
        dry_run=_env_flag("CATALOG_FORWARD_DRY_RUN"),
    )


# =============================================================================
# Qualification (pure functions)
# =============================================================================

def _norm(text: Any) -> str:
    return re.sub(r"[_\-.()\[\]]+", " ", str(text or "").lower())


def _first_match(patterns: List[Tuple[str, re.Pattern]], text: str) -> Optional[str]:
    for name, pattern in patterns:
        if pattern.search(text):
            return name
    return None


def _sender_address(doc: Dict[str, Any]) -> str:
    return str(doc.get("email_sender") or doc.get("sender") or "").strip()


def _sender_domain(sender: str) -> str:
    match = EMAIL_RE.search(sender or "")
    return match.group(1).lower() if match else ""


def _is_gamer_domain(domain: str) -> bool:
    return domain == GAMER_DOMAIN or domain.endswith("." + GAMER_DOMAIN)


def _vendor_name(doc: Dict[str, Any]) -> str:
    fields = doc.get("extracted_fields") or {}
    if not isinstance(fields, dict):
        fields = {}
    for value in (
        doc.get("vendor_canonical"),
        doc.get("extracted_vendor"),
        doc.get("vendor_raw"),
        doc.get("matched_vendor_name"),
        fields.get("vendor"),
        fields.get("vendor_name"),
        fields.get("supplier"),
    ):
        if value and str(value).strip():
            return str(value).strip()
    return ""


def evaluate_document(doc: Dict[str, Any]) -> Tuple[bool, str]:
    """Decide whether one hub_documents record should go to the catalog inbox.

    Returns ``(qualifies, reason)``. ``reason`` is a short code, e.g.
    ``supplier_pricing:price_list`` or ``excluded_type:AP_Invoice``.
    """
    if doc.get("catalog_forwarded_utc"):
        return False, "already_forwarded"
    if doc.get("is_duplicate"):
        return False, "duplicate_copy"

    file_name = str(doc.get("file_name") or "")
    subject = str(doc.get("email_subject") or "")

    if PAGE_SPLIT_RE.search(file_name) or doc.get("parent_document_id") or doc.get("split_parent_id"):
        return False, "page_split_copy"

    ext = os.path.splitext(file_name)[1].lower()
    if ext not in FORWARD_EXTENSIONS:
        return False, f"unsupported_file_type:{ext or 'none'}"

    size = doc.get("file_size")
    if isinstance(size, (int, float)) and size > MAX_FILE_BYTES:
        return False, "file_too_large"

    if GAMER_QUOTE_RE.search(file_name) or GAMER_QUOTE_RE.search(subject):
        return False, "gamer_quote_to_customer"

    job_type = str(doc.get("document_type") or doc.get("suggested_job_type") or "")
    if job_type.lower() not in ALLOWED_JOB_TYPES:
        return False, f"excluded_type:{job_type}"
    doc_type = str(doc.get("doc_type") or "")
    if doc_type.lower() not in ALLOWED_DOC_TYPES:
        return False, f"excluded_type:{doc_type}"

    name_text = _norm(os.path.splitext(file_name)[0])
    subject_text = _norm(subject)

    name_exclusion = _first_match(EXCLUDE_PATTERNS, name_text)
    if name_exclusion:
        return False, f"looks_like_{name_exclusion}"

    signal = _first_match(PRICING_PATTERNS, name_text)
    if not signal and not _first_match(EXCLUDE_PATTERNS, subject_text):
        signal = _first_match(PRICING_PATTERNS, subject_text)
    if not signal:
        return False, "no_pricing_signal"

    vendor = _vendor_name(doc)
    if vendor and "gamer" in vendor.lower():
        return False, "gamer_letterhead"
    domain = _sender_domain(_sender_address(doc))
    external_sender = bool(domain) and not _is_gamer_domain(domain)
    if not external_sender and not vendor:
        return False, "internal_sender_no_supplier" if domain else "no_supplier_signal"

    return True, f"supplier_pricing:{signal}"


# =============================================================================
# File bytes
# =============================================================================

async def _graph_token() -> str:
    from services.config_service import get_graph_token
    return await get_graph_token()


async def load_document_bytes(doc: Dict[str, Any]) -> Optional[bytes]:
    """Read a document's bytes the way the Hub serves files: local upload copy,
    then the MongoDB base64 backup, then SharePoint through Microsoft Graph."""
    doc_id = doc.get("id") or ""
    try:
        from paths import UPLOAD_DIR
        local = UPLOAD_DIR / doc_id
        if doc_id and local.is_file():
            return local.read_bytes()
    except Exception as exc:  # noqa: BLE001
        logger.debug("[CatalogForward] no local copy for %s: %s", doc_id, exc)

    b64 = doc.get("file_content_b64")
    if b64:
        try:
            return base64.b64decode(b64)
        except Exception:  # noqa: BLE001
            pass

    drive_id, item_id = doc.get("sharepoint_drive_id"), doc.get("sharepoint_item_id")
    link = doc.get("sharepoint_web_url") or doc.get("sharepoint_share_link_url") or doc.get("sharepoint_url")
    if drive_id and item_id:
        url = f"https://graph.microsoft.com/v1.0/drives/{drive_id}/items/{item_id}/content"
    elif link:
        share = "u!" + base64.urlsafe_b64encode(str(link).encode()).decode().rstrip("=")
        url = f"https://graph.microsoft.com/v1.0/shares/{share}/driveItem/content"
    else:
        return None
    token = await _graph_token()
    if not token or token.startswith("mock-"):
        return None
    async with httpx.AsyncClient(follow_redirects=True, timeout=120.0) as client:
        resp = await client.get(url, headers={"Authorization": f"Bearer {token}"})
    if resp.status_code != 200:
        raise RuntimeError(f"SharePoint returned HTTP {resp.status_code}")
    return resp.content


# =============================================================================
# Recording decisions
# =============================================================================

def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def _record(db, doc: Dict[str, Any], status: str, reason: str,
                  batch_id: Optional[str] = None, extra: Optional[Dict[str, Any]] = None) -> None:
    entry = {
        "status": status,
        "reason": reason,
        "decided_utc": _now(),
        "batch_id": batch_id,
        **(extra or {}),
    }
    try:
        update: Dict[str, Any] = {"catalog_forward": entry}
        if status == "sent":
            update["catalog_forwarded_utc"] = entry["decided_utc"]
        await db.hub_documents.update_one({"id": doc.get("id")}, {"$set": update})
        await db[LOG_COLLECTION].insert_one({
            "document_id": doc.get("id"),
            "file_name": doc.get("file_name"),
            "email_id": doc.get("email_id"),
            "email_subject": doc.get("email_subject"),
            "sender": _sender_address(doc),
            "document_type": doc.get("document_type"),
            **entry,
        })
    except Exception as exc:  # noqa: BLE001
        logger.warning("[CatalogForward] could not record decision for %s: %s", doc.get("id"), exc)
    logger.info("[CatalogForward] %s %s (%s) %s", status, doc.get("file_name"), doc.get("id"), reason)


async def _claim(db, doc_id: str) -> bool:
    """Atomically mark a document as being sent; False if it was sent or is
    being sent already (so two workers never send the same file)."""
    result = await db.hub_documents.update_one(
        {
            "id": doc_id,
            "catalog_forwarded_utc": {"$in": [None, ""]},
            "catalog_forward.status": {"$ne": "sending"},
        },
        {"$set": {"catalog_forward": {"status": "sending", "reason": "claimed", "decided_utc": _now()}}},
    )
    return bool(getattr(result, "modified_count", 0))


# =============================================================================
# Sending
# =============================================================================

async def _post_submit(settings: CatalogForwardSettings, payload: Dict[str, Any]) -> Dict[str, Any]:
    async with httpx.AsyncClient(timeout=POST_TIMEOUT_SECONDS) as client:
        resp = await client.post(
            settings.url,
            json=payload,
            headers={"X-GPI-Intake-Key": settings.key, "Content-Type": "application/json"},
        )
    if resp.status_code >= 400:
        raise RuntimeError(f"catalog inbox returned HTTP {resp.status_code}")
    try:
        body = resp.json()
    except Exception:  # noqa: BLE001
        body = {}
    status = str((body or {}).get("status") or "").upper()
    if status and status != "ACCEPTED":
        raise RuntimeError(f"catalog inbox answered status {status}")
    return body or {}


def _chunks(files: List[Tuple[Dict[str, Any], bytes]]) -> List[List[Tuple[Dict[str, Any], bytes]]]:
    chunks: List[List[Tuple[Dict[str, Any], bytes]]] = []
    current: List[Tuple[Dict[str, Any], bytes]] = []
    size = 0
    for doc, data in files:
        if current and size + len(data) > MAX_REQUEST_RAW_BYTES:
            chunks.append(current)
            current, size = [], 0
        current.append((doc, data))
        size += len(data)
    if current:
        chunks.append(current)
    return chunks


async def _send_email_group(db, settings: CatalogForwardSettings, docs: List[Dict[str, Any]]) -> None:
    """Download and submit the qualifying documents of one source email."""
    ready: List[Tuple[Dict[str, Any], bytes]] = []
    for doc in docs:
        if not await _claim(db, doc["id"]):
            await _record_log_only(db, doc, "skipped", "already_forwarded")
            continue
        try:
            data = await load_document_bytes(doc)
        except Exception as exc:  # noqa: BLE001
            await _record(db, doc, "failed", f"download_failed:{type(exc).__name__}")
            continue
        if not data:
            await _record(db, doc, "failed", "file_not_available")
            continue
        if len(data) > MAX_FILE_BYTES:
            await _record(db, doc, "skipped", "file_too_large")
            continue
        ready.append((doc, data))

    for chunk in _chunks(ready):
        batch_id = uuid.uuid4().hex[:12]
        first = chunk[0][0]
        names = [d.get("file_name") for d, _ in chunk]
        payload = {
            "subject": first.get("email_subject") or "Supplier pricing from GPI Hub",
            "sender": _sender_address(first) or "GPI Hub",
            "files": [
                {"name": d.get("file_name") or f"{d['id']}.bin", "content_b64": base64.b64encode(b).decode("ascii")}
                for d, b in chunk
            ],
            "note": (
                "Forwarded automatically by GPI Hub (catalog forward). "
                f"Hub document ids: {', '.join(d['id'] for d, _ in chunk)}"
            ),
        }
        try:
            body = await _post_submit(settings, payload)
        except Exception as exc:  # noqa: BLE001
            logger.warning("[CatalogForward] submit failed for %s: %s", names, exc)
            for doc, _ in chunk:
                await _record(db, doc, "failed", f"submit_failed:{str(exc)[:200]}", batch_id)
            continue
        extra = {"intake_response": {k: body.get(k) for k in ("status", "id", "intake_id", "review_id") if k in body}}
        for doc, _ in chunk:
            await _record(db, doc, "sent", "accepted", batch_id, extra)


async def _record_log_only(db, doc: Dict[str, Any], status: str, reason: str) -> None:
    """Log a decision without touching the document's own forward state."""
    try:
        await db[LOG_COLLECTION].insert_one({
            "document_id": doc.get("id"), "file_name": doc.get("file_name"),
            "email_id": doc.get("email_id"), "status": status, "reason": reason,
            "decided_utc": _now(),
        })
    except Exception:  # noqa: BLE001
        pass
    logger.info("[CatalogForward] %s %s (%s) %s", status, doc.get("file_name"), doc.get("id"), reason)


async def forward_documents(doc_ids: Iterable[str], settings: Optional[CatalogForwardSettings] = None) -> Dict[str, Any]:
    """Evaluate the given hub_documents and send the qualifying ones,
    grouped by source email. Safe to call more than once for the same ids."""
    settings = settings or get_settings()
    summary: Dict[str, Any] = {"enabled": settings.enabled, "dry_run": settings.dry_run,
                               "qualified": 0, "skipped": 0, "sent_groups": 0}
    if not settings.enabled:
        summary["reason"] = "disabled"
        return summary

    ids = [i for i in dict.fromkeys(doc_ids or []) if i]
    if not ids:
        return summary
    db = get_db()

    send_ready = bool(settings.url and settings.key)
    groups: Dict[str, List[Dict[str, Any]]] = {}
    for doc_id in ids:
        doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        if not doc:
            continue
        qualifies, reason = evaluate_document(doc)
        if not qualifies:
            summary["skipped"] += 1
            if reason == "already_forwarded":
                await _record_log_only(db, doc, "skipped", reason)
            else:
                await _record(db, doc, "skipped", reason)
            continue
        summary["qualified"] += 1
        if settings.dry_run:
            await _record(db, doc, "dry_run", reason)
            continue
        if not send_ready:
            await _record(db, doc, "failed", "not_configured:CATALOG_FORWARD_URL/KEY missing")
            continue
        groups.setdefault(str(doc.get("email_id") or doc_id), []).append(doc)

    for group in groups.values():
        await _send_email_group(db, settings, group)
        summary["sent_groups"] += 1
    return summary


# =============================================================================
# Ingestion hook (never raises)
# =============================================================================

async def forward_documents_safely(doc_ids: Iterable[str]) -> Optional[Dict[str, Any]]:
    try:
        return await forward_documents(list(doc_ids or []))
    except Exception as exc:  # noqa: BLE001
        logger.error("[CatalogForward] error (ingestion unaffected): %r", exc)
        return None


def schedule_forward_for_email(doc_ids: Iterable[str]) -> None:
    """Hook for the email pollers: called once per email with the ids of the
    documents just ingested from it. Returns at once; never raises."""
    try:
        if not get_settings().enabled:
            return
        ids = [i for i in (doc_ids or []) if i]
        if not ids:
            return
        task = asyncio.get_running_loop().create_task(forward_documents_safely(ids))
        _background_tasks.add(task)
        task.add_done_callback(_background_tasks.discard)
    except Exception as exc:  # noqa: BLE001
        logger.error("[CatalogForward] hook error (ingestion unaffected): %r", exc)


# =============================================================================
# Status (read-only)
# =============================================================================

async def get_status(limit: int = 50) -> Dict[str, Any]:
    """Settings (without the key) plus the most recent forward decisions."""
    limit = max(1, min(int(limit or 50), 500))
    db = get_db()
    recent = await db[LOG_COLLECTION].find({}, {"_id": 0}).sort("decided_utc", -1).limit(limit).to_list(limit)
    counts: Dict[str, int] = {}
    for row in recent:
        counts[row.get("status", "unknown")] = counts.get(row.get("status", "unknown"), 0) + 1
    return {"settings": get_settings().public(), "counts_in_recent": counts, "recent": recent}


__all__ = [
    "CatalogForwardSettings",
    "evaluate_document",
    "forward_documents",
    "forward_documents_safely",
    "get_settings",
    "get_status",
    "load_document_bytes",
    "schedule_forward_for_email",
]
