"""Retype AP-mailbox correspondence that intake classified as AP_Invoice.

Found 2026-10-06: 236 of 253 CertCapture (Avalara) e-mails "Request for
Sales & Use Tax Exemption Documentation" from Berry Global entities were
typed AP_Invoice; none ever matched a BC invoice and staff never file them
as AP work. Account statements, price-change / resin announcements and
test e-mails showed the same pattern. They inflate AP counts, feed vendor
learning with non-invoices and could reach the posting queue.

Hourly (learning cycle), idempotent: an AP_Invoice that is not linked to
BC, has no amount, and whose sender/subject marks it as one of the kinds
below is retyped; the previous type and the reason are kept.
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)

RULES = [
    # (kind, new document_type, sender regex, subject regex)
    ("tax_exemption_request", "Unknown_Document", r"certcapture|avalara",
     r"tax exemption|exemption (?:certificate|documentation)|resale certificate"),
    ("account_statement", "Statement", None,
     r"statement of account|account statement|\bstatement\b.*\bas of\b|past due statement"),
    ("price_notice", "Unknown_Document", None,
     r"price (?:change|increase) notification|resin announcement|price increase"),
    ("test_message", "Unknown_Document", None, r"^\s*test\s*\d*\s*$"),
]

# Rules on the file name (and subject) for documents that DO carry an amount
# but no invoice number: statements of account list a balance; vendor forms.
# 2026-10-06: Fast Track / Triumbari / Phoenix / Pano statements and W-9s,
# ACH instructions, an SOP were AP_Invoice in the staff queue.
FILE_RULES = [
    ("account_statement", "Statement",
     # word-bounded: "aging" inside "packaging" retyped Citi Cargo invoices
     r"statement|^cs [a-z0-9]+ \d|customer statement|account summary|\bar aging\b|\baging (?:report|detail)"),
    ("vendor_form", "Unknown_Document",
     r"(?<![a-z])w-?9(?![0-9])|ach[ _-]?(?:instruction|form|authori|payment set ?up)|bank (?:letter|details)|\bsop\b|credit application|certificate of insurance|\bcoi\b"),
]


def classify_file(file_name: str, subject: str):
    text = f"{file_name or ''} | {subject or ''}".lower()
    for kind, new_type, rx in FILE_RULES:
        # "Your Account Statement & Invoices" carries real invoices: a
        # statement needs the file itself to say so when the subject
        # mentions invoices.
        if (kind == "account_statement" and "invoice" in (subject or "").lower()
                and not re.search(rx, (file_name or "").lower())):
            continue
        if re.search(rx, text):
            return kind, new_type
    return None


# Invoice / credit number stated in the e-mail subject or file name when
# extraction found none ("MRP Credit Memo #3039489-10", "Inv00026759",
# "Sales Credit Memo SCMP0001007.pdf").
NUMBER_IN_TEXT = re.compile(
    # whole words only: "XPOLogisticsinvoices09012026" is a date, not a number
    r"(?:\binvoice\b|\binv(?=[\s#:.]|\d)|\bcredit memo\b|\bcredit note\b|\bcm\b|\bbill\b)\s*(?:no\.?|number|#)?\s*[:#]?\s*([A-Z]{0,6}\d[A-Z0-9-]{3,20})"
    r"|\b((?:SINV|SCMP|INV|CM)\d{4,12})\b", re.I)


def number_from_text(file_name: str, subject: str):
    # A file named just by its number ("0313645.pdf", "3039489.pdf").
    stem = re.sub(r"\.[A-Za-z0-9]{2,4}$", "", (file_name or "").strip())
    if re.fullmatch(r"[A-Z]{0,4}\d{5,12}", stem, re.I):
        return stem.upper()
    for text in (subject or "", file_name or ""):
        m = NUMBER_IN_TEXT.search(text)
        if m:
            num = (m.group(1) or m.group(2) or "").strip("-").upper()
            if len(re.sub(r"\D", "", num)) >= 4:
                return num
    return None


def classify(sender: str, subject: str):
    sender, subject = (sender or "").lower(), (subject or "").lower()
    for kind, new_type, snd, subj in RULES:
        if (snd and re.search(snd, sender)) or (subj and re.search(subj, subject)):
            return kind, new_type
    return None


async def reclassify_recent(db, days: int = 120, apply: bool = True) -> Dict[str, Any]:
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    stats: Dict[str, int] = {}
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "document_type": {"$in": ["AP_Invoice", "AP_INVOICE"]},
             "bc_link": {"$exists": False}, "amount_float": {"$in": [None, 0, 0.0]},
             "status": {"$ne": "Posted"}},
            {"_id": 1, "email_sender": 1, "email_subject": 1, "document_type": 1, "invoice_number_clean": 1}):
        hit = classify(d.get("email_sender"), d.get("email_subject"))
        if not hit:
            continue
        kind, new_type = hit
        # Statement / notice e-mails also carry real invoices ("Your Account
        # Statement & Invoices"): only retype when no invoice number either.
        if kind != "tax_exemption_request" and d.get("invoice_number_clean"):
            continue
        stats[kind] = stats.get(kind, 0) + 1
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {
                "document_type": new_type, "suggested_job_type": new_type,
                "document_type_previous": d.get("document_type"),
                "non_ap_kind": kind,
                "document_type_corrected": {"at": now, "reason": f"non-AP correspondence: {kind}"}}})
    # Statements / vendor forms with an amount but no invoice number.
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "document_type": {"$in": ["AP_Invoice", "AP_INVOICE"]},
             "bc_link": {"$exists": False}, "invoice_number_clean": {"$in": [None, ""]},
             "status": {"$ne": "Posted"}},
            {"_id": 1, "file_name": 1, "email_subject": 1, "document_type": 1}):
        hit = classify_file(d.get("file_name"), d.get("email_subject"))
        if not hit:
            continue
        kind, new_type = hit
        stats[kind] = stats.get(kind, 0) + 1
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {
                "document_type": new_type, "suggested_job_type": new_type,
                "document_type_previous": d.get("document_type"), "non_ap_kind": kind,
                "document_type_corrected": {"at": now, "reason": f"non-AP document (file/subject): {kind}"}}})
    # A label word read as the invoice number ("AND", "INVOICE", "DATE": 133
    # documents, 2026-10-06) is no number: kept for audit, cleared, and the
    # false invoice-identity duplicates it caused are restored (Tumalo
    # 0313644 / 0313645 both "AND" at 1,970.00 were merged into one).
    rejected = restored = 0
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "invoice_number_clean": {"$nin": [None, ""], "$not": {"$regex": "[0-9]"}}},
            {"_id": 1, "invoice_number_clean": 1, "is_duplicate": 1, "duplicate_reason": 1}):
        rejected += 1
        upd = {"$set": {"invoice_number_rejected": {"value": d["invoice_number_clean"], "at": now, "reason": "no digit (label word)"}},
               "$unset": {"invoice_number_clean": ""}}
        if d.get("is_duplicate") and d.get("duplicate_reason") == "invoice_identity":
            restored += 1
            upd["$set"].update({"is_duplicate": False, "duplicate_unmarked": {"at": now, "reason": "identity used a label word as the invoice number"}})
            upd["$unset"].update({"duplicate_reason": "", "duplicate_of_document_id": ""})
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, upd)
    stats["label_word_numbers_cleared"] = rejected
    stats["false_duplicates_restored"] = restored
    # Invoice numbers stated in the subject / file name.
    filled = 0
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "document_type": {"$in": ["AP_Invoice", "AP_INVOICE", "Credit_Memo"]},
             "bc_link": {"$exists": False}, "invoice_number_clean": {"$in": [None, ""]},
             "batch_parent_id": {"$exists": False}, "non_ap_kind": {"$exists": False}},
            {"_id": 1, "file_name": 1, "email_subject": 1}):
        num = number_from_text(d.get("file_name"), d.get("email_subject"))
        if not num:
            continue
        filled += 1
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {
                "invoice_number_clean": num, "invoice_number_source": "subject_or_file_name",
                "invoice_number_filled_at": now}})
    stats["invoice_number_from_text"] = filled
    logger.info("[NonAP] %s", stats)
    return stats
