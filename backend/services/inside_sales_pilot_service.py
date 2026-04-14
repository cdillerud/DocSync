"""
GPI Document Hub — Inside Sales Pilot Ingestion Service

Controlled ingest-only pilot for two Inside Sales mailboxes:
  - mkoch@gamerpackaging.com
  - nhannover@gamerpackaging.com

Business intent:
  Ingest relevant sales/order-related emails and attachments,
  classify and store the documents, extract structured data,
  and make the results reviewable.  NO BC writes, NO auto-create
  sales orders, NO downstream automation.

Feature flag: INSIDE_SALES_PILOT_ENABLED (default false)
"""

import asyncio
import base64
import hashlib
import logging
import os
import re
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, List, Optional

import httpx

from deps import get_db

logger = logging.getLogger(__name__)

# ─────────────────────────────────────────────────────────────
# CONFIGURATION (all from env vars for easy on/off)
# ─────────────────────────────────────────────────────────────

INSIDE_SALES_PILOT_ENABLED = os.environ.get(
    "INSIDE_SALES_PILOT_ENABLED", "false"
).lower() in ("true", "1", "yes")

INSIDE_SALES_PILOT_MAILBOXES = [
    m.strip()
    for m in os.environ.get(
        "INSIDE_SALES_PILOT_MAILBOXES",
        "mkoch@gamerpackaging.com,nhannover@gamerpackaging.com",
    ).split(",")
    if m.strip()
]

INSIDE_SALES_PILOT_INTERVAL_MINUTES = int(
    os.environ.get("INSIDE_SALES_PILOT_INTERVAL_MINUTES", "10")
)

INSIDE_SALES_PILOT_LOOKBACK_MINUTES = int(
    os.environ.get("INSIDE_SALES_PILOT_LOOKBACK_MINUTES", "120")
)

INSIDE_SALES_PILOT_MAX_MESSAGES = int(
    os.environ.get("INSIDE_SALES_PILOT_MAX_MESSAGES", "50")
)

# ─────────────────────────────────────────────────────────────
# RELEVANCE FILTERS
# ─────────────────────────────────────────────────────────────

# Subject / body keywords that indicate a sales/order document
_RELEVANCE_KEYWORDS = [
    r"\bpo\b", r"\bpurchase\s*order\b", r"\border\b", r"\bcustomer\s*order\b",
    r"\bquote\b", r"\brelease\b", r"\bshipment\s*request\b", r"\bship\s*to\b",
    r"\bdelivery\b", r"\binvoice\b", r"\bconfirmation\b", r"\bsku\b",
    r"\bqty\b", r"\bquantity\b", r"\bpallet\b", r"\bcase\b",
    r"\bbill\s*to\b", r"\bbol\b", r"\bbill\s*of\s*lading\b",
    r"\bforecast\b", r"\brma\b", r"\breturn\b",
]
_RELEVANCE_RE = re.compile("|".join(_RELEVANCE_KEYWORDS), re.IGNORECASE)

# Attachment extensions considered relevant
_RELEVANT_EXTENSIONS = {
    ".pdf", ".xlsx", ".xls", ".csv", ".doc", ".docx",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff",
}

# Inline / noise skip rules
SKIP_CONTENT_TYPES = {"image/gif", "image/x-icon", "image/bmp"}
SKIP_FILENAME_PATTERNS = [
    r"^image\d+\.(png|jpg|gif)$",
    r"^signature",
    r"^logo",
    r"\.vcf$",
]
_skip_re_compiled = [re.compile(p, re.IGNORECASE) for p in SKIP_FILENAME_PATTERNS]


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _is_relevant_message(subject: str, body_preview: str) -> bool:
    """Check whether the subject or body contains order-related signals."""
    text = f"{subject} {body_preview}"
    return bool(_RELEVANCE_RE.search(text))


def _has_relevant_filename(filenames: list) -> bool:
    """Check if any attachment filename contains order-related signals."""
    if not filenames:
        return False
    # Use looser matching for filenames (no trailing \b — underscores are common)
    _FILENAME_KEYWORDS = re.compile(
        r"(?:^|[\s_\-.])(po|order|invoice|quote|release|bol|confirmation"
        r"|shipment|packing|forecast|rma|return|contract|pricing)",
        re.IGNORECASE,
    )
    for fn in filenames:
        if _FILENAME_KEYWORDS.search(fn or ""):
            return True
    return False


def _is_relevant_attachment(filename: str, content_type: str, size_bytes: int, is_inline: bool) -> tuple:
    """Return (keep, skip_reason). keep=True means we should ingest."""
    if is_inline:
        return False, "inline_attachment"
    if content_type and content_type.lower() in SKIP_CONTENT_TYPES:
        return False, f"skip_content_type:{content_type}"
    if filename:
        for pat in _skip_re_compiled:
            if pat.match(filename):
                return False, f"skip_filename_pattern:{filename}"
    if size_bytes < 500:
        return False, f"too_small:{size_bytes}B"
    ext = os.path.splitext(filename or "")[1].lower()
    if ext and ext not in _RELEVANT_EXTENSIONS:
        return False, f"irrelevant_extension:{ext}"
    return True, None


def _is_internal_sender(sender: str) -> bool:
    """Check if the sender is from gamerpackaging.com (internal)."""
    return sender and sender.lower().endswith("@gamerpackaging.com")


# ─────────────────────────────────────────────────────────────
# CORE POLLER
# ─────────────────────────────────────────────────────────────

async def poll_inside_sales_pilot_mailbox(mailbox_address: str) -> Dict[str, Any]:
    """
    Poll a single Inside Sales pilot mailbox for relevant sales documents.

    Steps:
      1. Fetch recent messages (with attachments) from Graph API.
      2. Apply relevance filter (subject/body keywords, external sender pref).
      3. Skip duplicates (by message_id + attachment hash).
      4. Ingest via _internal_intake_document into hub_documents.
      5. Stamp the resulting doc with pilot metadata.
      6. Run structured sales extraction on the document.
      7. Log everything for observability.
    """
    db = get_db()
    run_id = uuid.uuid4().hex[:8]

    stats: Dict[str, Any] = {
        "run_id": run_id,
        "mailbox": mailbox_address,
        "started_at": datetime.now(timezone.utc).isoformat(),
        "messages_scanned": 0,
        "messages_with_attachments": 0,
        "messages_skipped_no_attachments": 0,
        "messages_skipped_relevance": 0,
        "attachments_ingested": 0,
        "attachments_skipped_duplicate": 0,
        "attachments_skipped_noise": 0,
        "attachments_failed": 0,
        "extraction_success": 0,
        "extraction_failed": 0,
        "classified_types": {},
        "errors": [],
    }

    logger.info(
        "[InsideSalesPilot:%s] Starting poll for %s", run_id, mailbox_address
    )

    try:
        from services.config_service import get_email_token
        token = await get_email_token()
        if not token:
            stats["errors"].append("Failed to get email token")
            return stats

        lookback = datetime.now(timezone.utc) - timedelta(
            minutes=INSIDE_SALES_PILOT_LOOKBACK_MINUTES
        )
        filter_query = f"receivedDateTime ge {lookback.isoformat()}"

        async with httpx.AsyncClient(timeout=60.0) as client:
            msg_resp = await client.get(
                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/mailFolders/Inbox/messages",
                headers={"Authorization": f"Bearer {token}"},
                params={
                    "$filter": filter_query,
                    "$select": "id,subject,from,receivedDateTime,internetMessageId,hasAttachments,bodyPreview",
                    "$top": INSIDE_SALES_PILOT_MAX_MESSAGES,
                    "$orderby": "receivedDateTime asc",
                },
            )
            if msg_resp.status_code != 200:
                err = f"Graph API error {msg_resp.status_code}: {msg_resp.text[:300]}"
                logger.error("[InsideSalesPilot:%s] %s", run_id, err)
                stats["errors"].append(err)
                return stats

            messages = msg_resp.json().get("value", [])
            stats["messages_scanned"] = len(messages)

            for msg in messages:
                subject = msg.get("subject", "")
                body_preview = msg.get("bodyPreview", "")
                sender = (
                    msg.get("from", {})
                    .get("emailAddress", {})
                    .get("address", "unknown")
                )
                msg_id = msg["id"]
                internet_msg_id = msg.get("internetMessageId", msg_id)

                # --- Gate 1: Must have attachments ---
                if not msg.get("hasAttachments"):
                    stats["messages_skipped_no_attachments"] += 1
                    continue
                stats["messages_with_attachments"] += 1

                # --- Gate 2: Relevance filter ---
                # Require at least one order-related signal:
                #   a) keywords in subject/body, OR
                #   b) keywords in attachment filename
                # External sender alone is NOT enough (too much noise).
                has_keywords = _is_relevant_message(subject, body_preview)
                if not has_keywords:
                    # Peek at attachment names before fetching content
                    try:
                        _peek_resp = await client.get(
                            f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{msg_id}/attachments",
                            headers={"Authorization": f"Bearer {token}"},
                            params={"$select": "name"},
                        )
                        _peek_names = [
                            a.get("name", "")
                            for a in (_peek_resp.json().get("value", []) if _peek_resp.status_code == 200 else [])
                        ]
                        has_filename_signal = _has_relevant_filename(_peek_names)
                    except Exception:
                        has_filename_signal = False

                    if not has_filename_signal:
                        stats["messages_skipped_relevance"] += 1
                        await _log_pilot_event(db, run_id, mailbox_address, msg_id,
                                               "skipped_relevance",
                                               {"subject": subject, "sender": sender})
                        continue

                # --- Fetch attachments ---
                try:
                    att_resp = await client.get(
                        f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{msg_id}/attachments",
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$select": "id,name,contentType,size,isInline"},
                    )
                    if att_resp.status_code != 200:
                        stats["errors"].append(f"Failed attachments for msg {msg_id[:12]}")
                        continue

                    attachments = att_resp.json().get("value", [])
                    for att in attachments:
                        att_id = att.get("id")
                        filename = att.get("name", "unknown")
                        content_type = att.get("contentType", "")
                        is_inline = att.get("isInline", False)
                        size_bytes = att.get("size", 0)

                        # --- Gate 3: Attachment relevance ---
                        keep, skip_reason = _is_relevant_attachment(
                            filename, content_type, size_bytes, is_inline
                        )
                        if not keep:
                            stats["attachments_skipped_noise"] += 1
                            await _log_pilot_event(
                                db, run_id, mailbox_address, msg_id,
                                "skipped_attachment",
                                {"filename": filename, "reason": skip_reason},
                            )
                            continue

                        # --- Gate 4: Duplicate check ---
                        existing_dup = await db.inside_sales_pilot_log.find_one({
                            "internet_message_id": internet_msg_id,
                            "attachment_name": filename,
                            "status": {"$in": ["ingested", "skipped_duplicate"]},
                        })
                        if existing_dup:
                            stats["attachments_skipped_duplicate"] += 1
                            continue

                        # --- Fetch attachment content ---
                        try:
                            att_content_resp = await client.get(
                                f"https://graph.microsoft.com/v1.0/users/{mailbox_address}/messages/{msg_id}/attachments/{att_id}",
                                headers={"Authorization": f"Bearer {token}"},
                            )
                            if att_content_resp.status_code != 200:
                                stats["attachments_failed"] += 1
                                continue
                            content_b64 = att_content_resp.json().get("contentBytes", "")
                            content_bytes = base64.b64decode(content_b64)
                            content_hash = hashlib.sha256(content_bytes).hexdigest()
                        except Exception as e:
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Fetch failed {filename}: {e}")
                            continue

                        # --- Content-hash dedup ---
                        hash_dup = await db.hub_documents.find_one(
                            {"sha256_hash": content_hash, "is_duplicate": {"$ne": True}},
                            {"_id": 0, "id": 1},
                        )
                        if hash_dup:
                            await _log_pilot_intake(
                                db, run_id, mailbox_address, internet_msg_id,
                                filename, content_hash, "skipped_duplicate",
                                document_id=hash_dup["id"],
                            )
                            stats["attachments_skipped_duplicate"] += 1
                            continue

                        # --- INGEST via unified pipeline ---
                        try:
                            from server import _internal_intake_document

                            result = await _internal_intake_document(
                                file_content=content_bytes,
                                filename=filename,
                                content_type=content_type or "application/octet-stream",
                                source="inside_sales_pilot",
                                sender=sender,
                                subject=subject,
                                email_id=internet_msg_id,
                                mailbox_category="SALES",
                            )

                            doc_id = result.get("document_id") or result.get("document", {}).get("id")
                            skipped = result.get("skipped_duplicate", False)

                            if skipped:
                                stats["attachments_skipped_duplicate"] += 1
                                await _log_pilot_intake(
                                    db, run_id, mailbox_address, internet_msg_id,
                                    filename, content_hash, "skipped_duplicate",
                                    document_id=doc_id,
                                )
                                continue

                            # --- Stamp pilot metadata on the new document ---
                            pilot_metadata = {
                                "ingestion_source": "inside_sales_pilot",
                                "pilot_group": "inside_sales",
                                "pilot_mailbox": mailbox_address,
                                "pilot_run_id": run_id,
                                "pilot_ingested_utc": datetime.now(timezone.utc).isoformat(),
                                "inside_sales_pilot": True,
                                "bc_write_blocked": True,
                                "auto_create_so_blocked": True,
                            }
                            await db.hub_documents.update_one(
                                {"id": doc_id},
                                {"$set": pilot_metadata},
                            )

                            # --- Run structured sales extraction ---
                            extraction = await _extract_sales_fields(
                                db, doc_id, filename, subject, body_preview, sender
                            )
                            if extraction:
                                stats["extraction_success"] += 1
                            else:
                                stats["extraction_failed"] += 1

                            # --- Run BC Production cross-validation ---
                            try:
                                from services.bc_prod_validator import validate_document_against_bc
                                await validate_document_against_bc(doc_id)
                            except Exception as val_err:
                                logger.warning(
                                    "[InsideSalesPilot:%s] BC validation failed for %s: %s",
                                    run_id, doc_id, val_err,
                                )

                            # --- Track classified type ---
                            doc_rec = await db.hub_documents.find_one(
                                {"id": doc_id}, {"_id": 0, "doc_type": 1}
                            )
                            dtype = (doc_rec or {}).get("doc_type", "Unknown")
                            stats["classified_types"][dtype] = (
                                stats["classified_types"].get(dtype, 0) + 1
                            )

                            await _log_pilot_intake(
                                db, run_id, mailbox_address, internet_msg_id,
                                filename, content_hash, "ingested",
                                document_id=doc_id,
                                extra={
                                    "sender": sender,
                                    "subject": subject,
                                    "doc_type": dtype,
                                    "has_extraction": bool(extraction),
                                },
                            )
                            stats["attachments_ingested"] += 1
                            logger.info(
                                "[InsideSalesPilot:%s] Ingested %s -> %s (type=%s)",
                                run_id, filename, doc_id, dtype,
                            )

                        except Exception as e:
                            stats["attachments_failed"] += 1
                            stats["errors"].append(f"Intake failed {filename}: {e}")
                            await _log_pilot_intake(
                                db, run_id, mailbox_address, internet_msg_id,
                                filename, content_hash, "error",
                                error=str(e),
                            )

                except Exception as e:
                    stats["errors"].append(f"Message processing error {msg_id[:12]}: {e}")

    except Exception as e:
        stats["errors"].append(f"Poll run failed: {e}")
        logger.error("[InsideSalesPilot:%s] Run failed: %s", run_id, e)

    stats["completed_at"] = datetime.now(timezone.utc).isoformat()

    # Persist run stats
    run_doc = {**stats}
    await db.inside_sales_pilot_runs.insert_one(run_doc)

    logger.info(
        "[InsideSalesPilot:%s] Complete: scanned=%d, ingested=%d, dup=%d, noise=%d, failed=%d",
        run_id,
        stats["messages_scanned"],
        stats["attachments_ingested"],
        stats["attachments_skipped_duplicate"],
        stats["attachments_skipped_noise"],
        stats["attachments_failed"],
    )
    return stats


# ─────────────────────────────────────────────────────────────
# STRUCTURED SALES EXTRACTION
# ─────────────────────────────────────────────────────────────

async def _extract_sales_fields(
    db, doc_id: str, filename: str,
    email_subject: str, email_body: str, sender: str,
) -> Optional[Dict[str, Any]]:
    """
    Extract structured sales fields from the document's already-extracted data
    plus email context.  Persists as `sales_pilot_extraction` on the document.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return None

    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    combined_text = f"{email_subject} {email_body} {filename}".lower()

    extraction: Dict[str, Any] = {
        "customer_name": (
            ef.get("customer") or ef.get("customer_name")
            or nf.get("customer") or _guess_from_text(combined_text, "customer")
        ),
        "po_number": (
            ef.get("po_number") or ef.get("purchase_order")
            or nf.get("customer_po") or nf.get("po_number")
            or _guess_from_text(combined_text, "po_number")
        ),
        "order_number": (
            ef.get("order_number") or ef.get("sales_order_number")
            or nf.get("order_number")
        ),
        "requested_ship_date": (
            ef.get("requested_ship_date") or ef.get("ship_date")
            or nf.get("requested_ship_date")
        ),
        "ship_to": (
            ef.get("ship_to") or ef.get("ship_to_address")
            or nf.get("ship_to")
        ),
        "item_numbers": ef.get("items") or ef.get("item_numbers") or [],
        "quantities": ef.get("quantities") or [],
        "document_type": doc.get("doc_type") or doc.get("suggested_job_type"),
        "sender": sender,
        "mailbox_source": doc.get("pilot_mailbox"),
        "email_subject": email_subject,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
    }

    # Remove None values for cleanliness
    extraction = {k: v for k, v in extraction.items() if v is not None}

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {"sales_pilot_extraction": extraction}},
    )
    return extraction


def _guess_from_text(text: str, field: str) -> Optional[str]:
    """Very light regex extraction from email subject/body."""
    if field == "po_number":
        m = re.search(r"(?:po|purchase\s*order)[#:\s]*(\S+)", text, re.IGNORECASE)
        return m.group(1) if m else None
    if field == "customer":
        # Can't reliably guess customer from subject alone
        return None
    return None


# ─────────────────────────────────────────────────────────────
# LOGGING HELPERS
# ─────────────────────────────────────────────────────────────

async def _log_pilot_event(
    db, run_id: str, mailbox: str, message_id: str,
    event_type: str, details: Dict[str, Any] = None,
):
    """Log a pilot observability event."""
    await db.inside_sales_pilot_log.insert_one({
        "run_id": run_id,
        "mailbox": mailbox,
        "message_id": message_id,
        "event_type": event_type,
        "details": details or {},
        "timestamp": datetime.now(timezone.utc).isoformat(),
    })


async def _log_pilot_intake(
    db, run_id: str, mailbox: str, internet_message_id: str,
    filename: str, content_hash: str, status: str,
    document_id: str = None, error: str = None, extra: dict = None,
):
    """Log an attachment intake attempt (for idempotency + audit)."""
    entry = {
        "run_id": run_id,
        "mailbox": mailbox,
        "internet_message_id": internet_message_id,
        "attachment_name": filename,
        "attachment_hash": content_hash,
        "status": status,
        "document_id": document_id,
        "error": error,
        "timestamp": datetime.now(timezone.utc).isoformat(),
    }
    if extra:
        entry.update(extra)
    await db.inside_sales_pilot_log.insert_one(entry)


# ─────────────────────────────────────────────────────────────
# BACKGROUND WORKER
# ─────────────────────────────────────────────────────────────

async def inside_sales_pilot_worker():
    """Background worker — polls all pilot mailboxes at the configured interval."""
    logger.info(
        "[InsideSalesPilot] Worker started — enabled=%s, mailboxes=%s, interval=%dm",
        INSIDE_SALES_PILOT_ENABLED,
        INSIDE_SALES_PILOT_MAILBOXES,
        INSIDE_SALES_PILOT_INTERVAL_MINUTES,
    )
    # Initial delay to let server finish startup
    await asyncio.sleep(45)

    while True:
        try:
            if INSIDE_SALES_PILOT_ENABLED:
                for mailbox in INSIDE_SALES_PILOT_MAILBOXES:
                    try:
                        await poll_inside_sales_pilot_mailbox(mailbox)
                    except Exception as e:
                        logger.error(
                            "[InsideSalesPilot] Error polling %s: %s", mailbox, e
                        )
        except asyncio.CancelledError:
            logger.info("[InsideSalesPilot] Worker cancelled")
            break
        except Exception as e:
            logger.error("[InsideSalesPilot] Worker error: %s", e)

        await asyncio.sleep(INSIDE_SALES_PILOT_INTERVAL_MINUTES * 60)


# ─────────────────────────────────────────────────────────────
# QUERY HELPERS (used by router)
# ─────────────────────────────────────────────────────────────

async def get_pilot_documents(
    db, mailbox: str = None, doc_type: str = None,
    skip: int = 0, limit: int = 50,
) -> Dict[str, Any]:
    """Fetch documents ingested by this pilot."""
    query: Dict[str, Any] = {"inside_sales_pilot": True}
    if mailbox:
        query["pilot_mailbox"] = mailbox
    if doc_type:
        query["doc_type"] = doc_type

    total = await db.hub_documents.count_documents(query)
    docs = (
        await db.hub_documents.find(
            query,
            {
                "_id": 0,
                "id": 1,
                "file_name": 1,
                "doc_type": 1,
                "email_sender": 1,
                "email_subject": 1,
                "pilot_mailbox": 1,
                "pilot_ingested_utc": 1,
                "sales_pilot_extraction": 1,
                "ai_confidence": 1,
                "workflow_status": 1,
                "created_utc": 1,
            },
        )
        .sort("created_utc", -1)
        .skip(skip)
        .limit(limit)
        .to_list(limit)
    )
    return {"total": total, "documents": docs}


async def get_pilot_run_history(db, limit: int = 20) -> List[Dict[str, Any]]:
    """Fetch recent polling run summaries."""
    runs = (
        await db.inside_sales_pilot_runs.find({}, {"_id": 0})
        .sort("started_at", -1)
        .limit(limit)
        .to_list(limit)
    )
    return runs


async def get_pilot_status_summary(db) -> Dict[str, Any]:
    """Build a status dashboard for the Inside Sales pilot."""
    total_docs = await db.hub_documents.count_documents({"inside_sales_pilot": True})

    by_mailbox_pipeline = [
        {"$match": {"inside_sales_pilot": True}},
        {"$group": {"_id": "$pilot_mailbox", "count": {"$sum": 1}}},
    ]
    by_mailbox = {
        r["_id"]: r["count"]
        for r in await db.hub_documents.aggregate(by_mailbox_pipeline).to_list(10)
    }

    by_type_pipeline = [
        {"$match": {"inside_sales_pilot": True}},
        {"$group": {"_id": {"$ifNull": ["$doc_type", "Unknown"]}, "count": {"$sum": 1}}},
    ]
    by_type = {
        r["_id"]: r["count"]
        for r in await db.hub_documents.aggregate(by_type_pipeline).to_list(30)
    }

    # Extraction coverage
    with_extraction = await db.hub_documents.count_documents(
        {"inside_sales_pilot": True, "sales_pilot_extraction": {"$exists": True, "$ne": None}}
    )

    # Recent runs
    recent_runs = (
        await db.inside_sales_pilot_runs.find({}, {"_id": 0})
        .sort("started_at", -1)
        .limit(5)
        .to_list(5)
    )

    return {
        "enabled": INSIDE_SALES_PILOT_ENABLED,
        "mailboxes": INSIDE_SALES_PILOT_MAILBOXES,
        "interval_minutes": INSIDE_SALES_PILOT_INTERVAL_MINUTES,
        "total_documents": total_docs,
        "by_mailbox": by_mailbox,
        "by_doc_type": by_type,
        "extraction_coverage": f"{with_extraction}/{total_docs}" if total_docs else "0/0",
        "recent_runs": recent_runs,
    }


# ─────────────────────────────────────────────────────────────
# INDEX SETUP
# ─────────────────────────────────────────────────────────────

async def ensure_pilot_indexes(db):
    """Create indexes for pilot collections."""
    await db.inside_sales_pilot_log.create_index("run_id")
    await db.inside_sales_pilot_log.create_index("internet_message_id")
    await db.inside_sales_pilot_log.create_index("status")
    await db.inside_sales_pilot_log.create_index("timestamp")
    await db.inside_sales_pilot_runs.create_index("started_at")
    # Compound index for dedup lookups
    await db.inside_sales_pilot_log.create_index(
        [("internet_message_id", 1), ("attachment_name", 1), ("status", 1)]
    )
    # Index on hub_documents for pilot queries
    await db.hub_documents.create_index("inside_sales_pilot")
    await db.hub_documents.create_index("pilot_mailbox")
