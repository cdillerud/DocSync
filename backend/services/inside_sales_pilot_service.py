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
    r"\bpo\b", r"\bpurchase\s*order\b", r"\bcustomer\s*order\b",
    r"\bquote\s*request\b", r"\brelease\s*order\b",
    r"\bshipment\s*request\b", r"\bship\s*to\b",
    r"\bsku\b", r"\bqty\b", r"\bquantity\b",
    r"\bbill\s*to\b",
    r"\bforecast\b", r"\brma\b",
    # PO patterns commonly seen: W-prefixed, WR-prefixed, numeric 5+ digit
    r"\bW\d{5,}\b", r"\bWR\d{5,}\b",
]
_RELEVANCE_RE = re.compile("|".join(_RELEVANCE_KEYWORDS), re.IGNORECASE)

# Negative signals — subjects/bodies that are clearly NOT sales orders
_NOISE_SUBJECT_PATTERNS = [
    r"\bcertificate\b", r"\bcertification\b", r"\bISO[\s\-]", r"\bSQF\b",
    r"\baccess\s*issue", r"\bpassword\b", r"\blogin\b",
    r"\bdunnage\s*return\b", r"\bdunnage\s*request\b",
    r"\bmeeting\s*notes?\b", r"\bcalendar\b", r"\bschedule\s*call\b",
    r"\bout\s*of\s*office\b", r"\bOOO\b",
    r"\bnewsletter\b", r"\bwebinar\b", r"\btraining\b",
    r"\bsurvey\b", r"\bfeedback\s*form\b",
]
_NOISE_RE = re.compile("|".join(_NOISE_SUBJECT_PATTERNS), re.IGNORECASE)

# Filename patterns that are clearly NOT sales orders
_NOISE_FILENAME_PATTERNS = [
    r"(?i)certificate", r"(?i)certification", r"(?i)\bISO[\s\-_]", r"(?i)\bSQF\b",
    r"(?i)information\s*sheet", r"(?i)info\s*sheet",
    r"(?i)dunnage.*return", r"(?i)dunnage.*request", r"(?i)dunnage.*tracking",
    r"(?i)communication.*realignment", r"(?i)CSR.*realignment",
    r"(?i)^logo", r"(?i)^signature", r"(?i)^banner",
]
_NOISE_FILENAME_RE = [re.compile(p) for p in _NOISE_FILENAME_PATTERNS]

# Attachment extensions considered relevant
_RELEVANT_EXTENSIONS = {
    ".pdf", ".xlsx", ".xls", ".csv", ".doc", ".docx",
    ".png", ".jpg", ".jpeg", ".tif", ".tiff",
}

# Inline / noise skip rules
SKIP_CONTENT_TYPES = {"image/gif", "image/x-icon", "image/bmp", "image/svg+xml"}
SKIP_FILENAME_PATTERNS = [
    r"^image\d+\.(png|jpg|gif)$",
    r"^CID_",
    r"^signature",
    r"^logo",
    r"logo[_\s\-]?\d*\.(png|jpg|jpeg|gif|bmp|svg|webp)$",
    r"^(img|photo|pic|banner|icon)[_\s\-]?\d*\.(png|jpg|jpeg|gif)$",
    r"\.vcf$",
]
_skip_re_compiled = [re.compile(p, re.IGNORECASE) for p in SKIP_FILENAME_PATTERNS]


# ─────────────────────────────────────────────────────────────
# HELPERS
# ─────────────────────────────────────────────────────────────

def _is_relevant_message(subject: str, body_preview: str) -> bool:
    """Check whether the subject or body contains order-related signals."""
    text = f"{subject} {body_preview}"
    # Positive signal required
    if not _RELEVANCE_RE.search(text):
        return False
    # Reject if strong negative signal present
    if _NOISE_RE.search(text):
        return False
    return True


def _is_noise_filename(filename: str) -> bool:
    """Check if a filename is clearly not a sales order."""
    for pat in _NOISE_FILENAME_RE:
        if pat.search(filename or ""):
            return True
    return False


def _has_relevant_filename(filenames: list) -> bool:
    """Check if any attachment filename contains order-related signals."""
    if not filenames:
        return False
    _FILENAME_KEYWORDS = re.compile(
        r"(?:^|[\s_\-.])(po|order|invoice|quote|release|confirmation"
        r"|shipment|packing|forecast|rma|purchase|openorder)",
        re.IGNORECASE,
    )
    # Also match W-prefixed PO patterns in filenames (W117579, WR112624)
    _PO_PATTERN = re.compile(r"\bW[R]?\d{5,}\b", re.IGNORECASE)
    for fn in filenames:
        if _is_noise_filename(fn):
            continue
        if _FILENAME_KEYWORDS.search(fn or ""):
            return True
        if _PO_PATTERN.search(fn or ""):
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
    # Reject filenames that are clearly not sales documents
    if _is_noise_filename(filename):
        return False, f"noise_filename:{filename}"
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

                            # --- Run Spiro CRM match ---
                            try:
                                from services.spiro_service import match_document_to_spiro, SPIRO_ENABLED
                                if SPIRO_ENABLED:
                                    await match_document_to_spiro(doc_id)
                            except Exception as spiro_err:
                                logger.warning(
                                    "[InsideSalesPilot:%s] Spiro match failed for %s: %s",
                                    run_id, doc_id, spiro_err,
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
    Build a sales pilot summary from the MAIN PIPELINE's already-extracted data.

    This is NOT a duplicate extraction — it reads from the fields that
    _internal_intake_document already populated (extracted_fields,
    normalized_fields, vendor_canonical, matched_customer_no, line_items,
    po_resolution_number, etc.) and adds a quality score + pilot context.

    The main pipeline has 2-3 months of learned classification,
    vendor matching, customer resolution, and PO resolution.
    We leverage all of it.
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return None

    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    line_items = nf.get("line_items") or doc.get("line_items") or []
    combined_text = f"{email_subject} {email_body} {filename}"

    # ── Customer: resolve the BUYER (who sent the order), not the ship-to ──
    # The main pipeline's "vendor_canonical" is the doc sender — for Inside Sales,
    # this IS the customer (the entity ordering from Gamer). However, sometimes
    # the main pipeline incorrectly resolves "Gamer" as the vendor because Gamer
    # appears in the Ship-To address. In that case, fall back to email sender-
    # derived customer or extracted fields.
    raw_vendor = doc.get("vendor_canonical") or ""
    is_gamer_resolved = "gamer" in raw_vendor.lower()

    # Derive customer from email sender domain (e.g., orders@giovannis.com → Giovanni's)
    sender_domain = ""
    if sender and "@" in sender:
        sender_domain = sender.split("@")[1].split(".")[0]  # e.g., "giovannis"

    if is_gamer_resolved:
        # Gamer is the seller, not the customer. Use sender or extracted fields.
        customer_name = (
            ef.get("customer") or ef.get("customer_name") or ef.get("bill_to")
            or ef.get("vendor_name")  # On inbound POs, AI sometimes puts buyer in vendor_name
            or nf.get("customer")
            or (sender_domain.replace("-", " ").replace("_", " ").title() if sender_domain and sender_domain.lower() not in ("gamerpackaging", "gamer", "gmail", "outlook", "hotmail", "yahoo") else None)
        )
    else:
        customer_name = (
            raw_vendor  # Main pipeline's resolved entity (correct when not Gamer)
            or ef.get("customer") or ef.get("customer_name")
            or nf.get("customer")
        )

    customer_no = (
        doc.get("matched_customer_no") or doc.get("customer_no")
        or nf.get("customer_no")
    )
    # If customer_no resolved to a Gamer number but we know it's wrong, clear it
    if customer_no and customer_no.upper() in ("GAMER", "GAMERPA", "GAMER1"):
        customer_no = None

    # Flag if Gamer is the "customer" — means this is inbound, not a sales order
    is_gamer_customer = "gamer" in (customer_name or "").lower()

    # ── PO: use main pipeline's resolution, validate, fall back to text ──
    po_from_pipeline = (
        doc.get("po_resolution_number")  # Main pipeline's PO resolution
        or ef.get("po_number") or ef.get("purchase_order")
        or nf.get("customer_po") or nf.get("po_number")
    )
    po_from_text = _extract_po_number(combined_text)
    po_number = _validate_po(po_from_pipeline) or po_from_text

    # ── Order number ──
    order_from_pipeline = (
        ef.get("order_number") or ef.get("sales_order_number")
        or nf.get("order_number")
    )
    order_number = _validate_order_number(order_from_pipeline) or _extract_order_number(combined_text)

    # ── Ship-to ──
    ship_to = ef.get("ship_to") or ef.get("ship_to_address") or nf.get("ship_to")

    # ── Amount: main pipeline stores as "amount_float" (top-level), NOT "total_amount" ──
    amount = (
        doc.get("amount_float")  # Main pipeline's top-level amount field
        or doc.get("total_amount")  # Fallback if set by SO-specific paths
        or nf.get("amount_float") or nf.get("amount")
        or ef.get("total_amount") or ef.get("amount") or ef.get("grand_total")
        or ef.get("invoice_total") or ef.get("net_amount")
        or ef.get("amount_raw")
    )
    # Try to parse if it's a string
    if isinstance(amount, str):
        try:
            amount = float(amount.replace(",", "").replace("$", "").strip())
        except (ValueError, AttributeError):
            amount = None

    # ── Lines: use main pipeline's extracted line items ──
    extracted_lines = []
    for li in line_items:
        line = {}
        for key in ("description", "item_description", "quantity", "ordered_qty",
                     "unit_price", "price", "item_no", "item_number", "total",
                     "uom", "location_code", "drop_shipment"):
            val = li.get(key)
            if val is not None:
                line[key] = val
        if line:
            extracted_lines.append(line)

    # ── Classification: use main pipeline's AI classification ──
    doc_type = doc.get("doc_type") or doc.get("suggested_job_type")
    classification_method = doc.get("classification_method") or ef.get("classification_method")
    ai_confidence = doc.get("ai_confidence")

    # ── Vendor matching: use main pipeline's vendor intelligence ──
    vendor_canonical = doc.get("vendor_canonical")
    vendor_match_method = doc.get("vendor_match_method")
    vendor_match_score = doc.get("vendor_match_score")

    extraction: Dict[str, Any] = {
        # Core fields
        "customer_name": customer_name,
        "customer_no": customer_no,
        "is_gamer_customer": is_gamer_customer,
        "po_number": po_number,
        "order_number": order_number,
        "requested_ship_date": ef.get("requested_ship_date") or ef.get("ship_date") or nf.get("requested_ship_date"),
        "ship_to": ship_to,
        "total_amount": amount,
        "line_count": len(extracted_lines) or None,
        "extracted_lines": extracted_lines if extracted_lines else None,

        # Main pipeline intelligence (leveraged, not duplicated)
        "document_type": doc_type,
        "classification_method": classification_method,
        "ai_confidence": ai_confidence,
        "vendor_canonical": vendor_canonical,
        "vendor_match_method": vendor_match_method,
        "vendor_match_score": vendor_match_score,

        # Pilot context
        "sender": sender,
        "mailbox_source": doc.get("pilot_mailbox"),
        "email_subject": email_subject,
        "extracted_at": datetime.now(timezone.utc).isoformat(),
        "pipeline_source": "unified",  # Confirms we're using main pipeline data
    }

    # ── Quality score: how much useful data did the main pipeline extract? ──
    quality_fields = ["customer_name", "po_number", "ship_to", "total_amount"]
    filled = sum(1 for f in quality_fields if extraction.get(f))
    extraction["extraction_quality"] = f"{filled}/{len(quality_fields)}"
    extraction["extraction_quality_pct"] = round(filled / len(quality_fields) * 100)

    # ── Extended quality: include vendor + lines + classification ──
    extended_fields = ["vendor_canonical", "line_count", "ai_confidence", "order_number"]
    ext_filled = filled + sum(1 for f in extended_fields if extraction.get(f))
    ext_total = len(quality_fields) + len(extended_fields)
    extraction["extended_quality_pct"] = round(ext_filled / ext_total * 100)

    # Remove None values for cleanliness
    extraction = {k: v for k, v in extraction.items() if v is not None}

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {"sales_pilot_extraction": extraction}},
    )
    return extraction


# ── PO / Order Number validation and extraction ──

# Real PO patterns seen at GPI: W117579, WR112624, 67697-04, 21103-01, 110826409
_PO_PATTERNS = [
    re.compile(r"\bW[R]?\d{5,}\b"),                  # W117579, WR112624
    re.compile(r"\b\d{5,9}\b"),                        # 110826409, 67697
    re.compile(r"\b\d{4,6}[-]\d{1,3}\b"),             # 67697-04, 21103-01
    re.compile(r"\b[A-Z]{2,4}[-]?\d{4,}\b"),          # PO-12345, ETB-2024-0042
]

_GARBAGE_PO = {
    "rate", "intment", "number", "number.", "rt", "logies", "the", "and",
    "for", "from", "with", "this", "that", "please", "thanks", "order",
    "re", "fw", "fwd", "ext", "external",
}


def _validate_po(po: Optional[str]) -> Optional[str]:
    """Validate an AI-extracted PO number — reject garbage."""
    if not po:
        return None
    po = po.strip().strip("#:").strip()
    if len(po) < 4:
        return None
    if po.lower() in _GARBAGE_PO:
        return None
    # Must contain at least one digit
    if not re.search(r"\d", po):
        return None
    # Reject if it's just a common word fragment
    if re.match(r"^[a-z]+$", po, re.IGNORECASE) and len(po) < 6:
        return None
    return po


def _validate_order_number(order_no: Optional[str]) -> Optional[str]:
    """Validate an AI-extracted order number."""
    if not order_no:
        return None
    order_no = order_no.strip()
    if len(order_no) < 3:
        return None
    if order_no.lower() in _GARBAGE_PO:
        return None
    if not re.search(r"\d", order_no):
        return None
    return order_no


def _extract_po_number(text: str) -> Optional[str]:
    """Extract PO number from email subject/body/filename using known patterns."""
    # Try explicit "PO" or "Purchase Order" prefix first
    m = re.search(
        r"(?:po|purchase\s*order)[#:\s]+([A-Z0-9][\w\-]{3,})",
        text, re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip()
        if _validate_po(candidate):
            return candidate

    # Try W-prefixed patterns (very common at GPI)
    m = re.search(r"\b(W[R]?\d{5,})\b", text)
    if m:
        return m.group(1)

    return None


def _extract_order_number(text: str) -> Optional[str]:
    """Extract order number from email text."""
    m = re.search(
        r"(?:order|order\s*(?:no|num|number|#))[#:\s]+([A-Z0-9][\w\-]{3,})",
        text, re.IGNORECASE,
    )
    if m:
        candidate = m.group(1).strip()
        if _validate_order_number(candidate):
            return candidate
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
                "so_rules_evaluation": 1,
                "bc_prod_validation": 1,
                "spiro_match": 1,
                "reclassified_from": 1,
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
    """Build a comprehensive progress dashboard for the Inside Sales pilot."""
    base_q = {"inside_sales_pilot": True}
    total_docs = await db.hub_documents.count_documents(base_q)

    # ── Docs by mailbox ──
    by_mailbox_pipeline = [
        {"$match": base_q},
        {"$group": {"_id": "$pilot_mailbox", "count": {"$sum": 1}}},
    ]
    by_mailbox = {
        r["_id"]: r["count"]
        for r in await db.hub_documents.aggregate(by_mailbox_pipeline).to_list(10)
    }

    # ── Docs by type ──
    by_type_pipeline = [
        {"$match": base_q},
        {"$group": {"_id": {"$ifNull": ["$doc_type", "Unknown"]}, "count": {"$sum": 1}}},
    ]
    by_type = {
        r["_id"]: r["count"]
        for r in await db.hub_documents.aggregate(by_type_pipeline).to_list(30)
    }

    # ── Extraction quality ──
    with_extraction = await db.hub_documents.count_documents(
        {**base_q, "sales_pilot_extraction": {"$exists": True, "$ne": None}}
    )
    quality_pipeline = [
        {"$match": {**base_q, "sales_pilot_extraction.extraction_quality_pct": {"$exists": True}}},
        {"$group": {
            "_id": None,
            "avg_quality": {"$avg": "$sales_pilot_extraction.extraction_quality_pct"},
            "high_quality": {"$sum": {"$cond": [{"$gte": ["$sales_pilot_extraction.extraction_quality_pct", 50]}, 1, 0]}},
            "has_po": {"$sum": {"$cond": [{"$and": [
                {"$ne": ["$sales_pilot_extraction.po_number", None]},
                {"$ne": ["$sales_pilot_extraction.po_number", ""]},
            ]}, 1, 0]}},
            "has_customer": {"$sum": {"$cond": [{"$and": [
                {"$ne": ["$sales_pilot_extraction.customer_name", None]},
                {"$ne": ["$sales_pilot_extraction.customer_name", ""]},
            ]}, 1, 0]}},
            "has_ship_to": {"$sum": {"$cond": [{"$and": [
                {"$ne": ["$sales_pilot_extraction.ship_to", None]},
                {"$ne": ["$sales_pilot_extraction.ship_to", ""]},
            ]}, 1, 0]}},
            "has_amount": {"$sum": {"$cond": [{"$and": [
                {"$ne": ["$sales_pilot_extraction.total_amount", None]},
                {"$gt": ["$sales_pilot_extraction.total_amount", 0]},
            ]}, 1, 0]}},
        }},
    ]
    quality_result = await db.hub_documents.aggregate(quality_pipeline).to_list(1)
    qr = quality_result[0] if quality_result else {}

    # ── BC Validation scores ──
    with_validation = await db.hub_documents.count_documents(
        {**base_q, "bc_prod_validation": {"$exists": True, "$ne": None}}
    )
    bc_pipeline = [
        {"$match": {**base_q, "bc_prod_validation.overall_score": {"$exists": True}}},
        {"$group": {
            "_id": None,
            "avg_score": {"$avg": "$bc_prod_validation.overall_score"},
            "customer_found": {"$sum": {"$cond": [
                {"$eq": ["$bc_prod_validation.customer_match.found", True]}, 1, 0
            ]}},
            "order_found": {"$sum": {"$cond": [
                {"$eq": ["$bc_prod_validation.order_lookup.found", True]}, 1, 0
            ]}},
        }},
    ]
    bc_result = await db.hub_documents.aggregate(bc_pipeline).to_list(1)
    br = bc_result[0] if bc_result else {}

    # ── Polling stats (last 24h) ──
    from datetime import timedelta
    cutoff_24h = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    recent_runs = (
        await db.inside_sales_pilot_runs.find(
            {"started_at": {"$gte": cutoff_24h}}, {"_id": 0}
        ).sort("started_at", -1).to_list(50)
    )
    total_scanned = sum(r.get("messages_scanned", 0) for r in recent_runs)
    total_ingested = sum(r.get("attachments_ingested", 0) for r in recent_runs)
    total_skipped_relevance = sum(r.get("messages_skipped_relevance", 0) for r in recent_runs)
    total_skipped_noise = sum(r.get("attachments_skipped_noise", 0) for r in recent_runs)
    total_skipped_dup = sum(r.get("attachments_skipped_duplicate", 0) for r in recent_runs)

    return {
        "enabled": INSIDE_SALES_PILOT_ENABLED,
        "version": "2.1.0",
        "mailboxes": INSIDE_SALES_PILOT_MAILBOXES,
        "interval_minutes": INSIDE_SALES_PILOT_INTERVAL_MINUTES,

        # ── Progress headline ──
        "total_documents": total_docs,
        "by_mailbox": by_mailbox,
        "by_doc_type": by_type,

        # ── Extraction quality ──
        "extraction": {
            "coverage": f"{with_extraction}/{total_docs}",
            "avg_quality_pct": round(qr.get("avg_quality", 0)),
            "high_quality_count": qr.get("high_quality", 0),
            "field_hit_rates": {
                "customer_name": f"{qr.get('has_customer', 0)}/{total_docs}",
                "po_number": f"{qr.get('has_po', 0)}/{total_docs}",
                "ship_to": f"{qr.get('has_ship_to', 0)}/{total_docs}",
                "total_amount": f"{qr.get('has_amount', 0)}/{total_docs}",
            } if total_docs else {},
        },

        # ── BC Production validation ──
        "bc_validation": {
            "validated": f"{with_validation}/{total_docs}",
            "avg_score_pct": round(br.get("avg_score", 0)),
            "customer_match_rate": f"{br.get('customer_found', 0)}/{with_validation}" if with_validation else "0/0",
            "order_match_rate": f"{br.get('order_found', 0)}/{with_validation}" if with_validation else "0/0",
        },

        # ── Last 24h polling activity ──
        "last_24h": {
            "poll_runs": len(recent_runs),
            "messages_scanned": total_scanned,
            "attachments_ingested": total_ingested,
            "skipped_relevance": total_skipped_relevance,
            "skipped_noise": total_skipped_noise,
            "skipped_duplicate": total_skipped_dup,
            "signal_to_noise": (
                f"{total_ingested}:{total_skipped_noise + total_skipped_relevance}"
                if (total_skipped_noise + total_skipped_relevance) > 0
                else f"{total_ingested}:0"
            ),
        },

        # ── Latest 3 runs ──
        "recent_runs": recent_runs[:3],
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
