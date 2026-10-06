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
    logger.info("[NonAP] %s", stats)
    return stats
