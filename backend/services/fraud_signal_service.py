"""Payment-fraud (business email compromise) signal for incoming documents.

Found 2026-10-05: the AP inbox received a campaign of fake invoices and
payment requests from unrelated or compromised domains impersonating
consultancies and services (Protiviti from a French joinery domain,
"LinkedIn" from lectrosalt.us, Didlake $101,750 and "Della Laira"
$137,500/$275,000, "Executive Coaching Bureau" $75,000, "Vistage
coaching" $9,980 ...). None were in BC. The Hub learned sender mappings
for them and filed them like vendor invoices.

A document is flagged when all three hold:
  * the vendor is not a BC vendor number (unknown to Gamer's books),
  * the sender's domain does not carry the vendor's name,
  * the subject/file name uses service or payment-pressure wording.
A large amount adds to the score. On February-October 2026 history the
rule flagged 21 AP documents, all of the campaign. Flagged documents route
to DO NOT PAY for a person to check; the flag never blocks anything else.
"""
import re
from typing import Any, Dict, Optional

SERVICE_WORDING = re.compile(
    r"advisory|coaching|consult|engagement|payment (?:transfer|filing|status)|not settled|overdue"
    r"|outstanding balance|resilience|leadership|strategic|internal controls|risk structure"
    r"|vendor update|bank(?:ing)? (?:details|information|change)|remittance change|w-?9\b"
    r"|approach to|future development|clearer path",
    re.I,
)
_GENERIC = {"inc", "llc", "corp", "company", "group", "services", "service", "international",
            "packaging", "solutions", "the", "and", "global", "usa", "america"}
_INTERNAL_DOMAINS = ("gamerpackaging.com",)
_LOOKALIKE = re.compile(r"\b[A-Z]+l[A-Z]{2,}")


def _brand_tokens(name: str):
    return {t for t in re.findall(r"[a-z]{4,}", str(name or "").lower()) if t not in _GENERIC}


async def assess_fraud_risk(db, doc: Dict[str, Any]) -> Dict[str, Any]:
    sender = str(doc.get("email_sender") or "").strip().lower()
    domain = sender.split("@")[-1] if "@" in sender else ""
    if not domain or domain.endswith(_INTERNAL_DOMAINS):
        return {"flagged": False}
    # Shared billing platforms send on behalf of many companies (a Bill.com
    # W-9 request is routine); their domain never matches a vendor name.
    from services.vendor_matching import SHARED_SENDER_DOMAINS
    if any(domain == d or domain.endswith("." + d) for d in SHARED_SENDER_DOMAINS):
        return {"flagged": False}
    ef = doc.get("extracted_fields") or {}
    vendor_name = ef.get("vendor") or doc.get("vendor_raw") or doc.get("vendor_canonical") or ""
    vendor_no = str(doc.get("vendor_canonical") or "").strip()
    name_mismatch = None
    in_bc = bool(vendor_no) and await db.hub_bc_vendors.find_one({"number": vendor_no}, {"_id": 1}) is not None
    if in_bc:
        # A vendor Gamer has never paid, or one blocked in BC, is not "known"
        # ("Becparts LLC" fuzzy-matched to blocked CHANGE, $34,117 "Advisory
        # Overview" from bbaja.es, 2026-10-07).
        cat = await db.bc_catalog_vendors.find_one({"vendor_no": vendor_no}, {"_id": 0, "blocked": 1, "name": 1})
        paid = await db.bc_reference_cache.find_one({"bc_vendor_no": vendor_no, "bc_entity_type": "posted_purchase_invoice"}, {"_id": 1})
        in_bc = not (cat or {}).get("blocked") and paid is not None
        # The vendor number only counts when the invoice's own name shares a
        # word with it: the 2026-09 campaign's "Lavonta Walker", "Bluecrest
        # Storage LLC" and "Stephen Conroy" bills were later matched to OWENS
        # and ARDAGHM, which hid them.
        own = _brand_tokens(ef.get("vendor") or doc.get("vendor_raw") or "")
        bc_name = _brand_tokens(f"{(cat or {}).get('name') or ''} {vendor_no}")
        if in_bc and own and bc_name and not (own & bc_name) and not any(o[:5] in b or b[:5] in o for o in own for b in bc_name):
            in_bc = False
            name_mismatch = (cat or {}).get("name") or vendor_no
    domain_flat = domain.replace("-", "")
    domain_matches = any(t in domain_flat for t in _brand_tokens(vendor_name))
    wording = f"{doc.get('email_subject') or ''} {doc.get('file_name') or ''}"
    # A look-alike letter in a capitalised word ("BlLL-B83748.pdf": a small L
    # for the I of BILL) - both 2026-09 "James Lucky" / "Lavonta Walker" bills.
    wording_hit = SERVICE_WORDING.search(wording) or _LOOKALIKE.search(doc.get("file_name") or "")
    amount = abs(float(doc.get("amount_float") or 0))
    reasons = []
    if name_mismatch:
        reasons.append(f"invoice name {vendor_name!r} is not BC vendor {name_mismatch!r}")
    elif not in_bc:
        reasons.append("vendor not in BC")
    if not domain_matches:
        reasons.append(f"sender domain {domain} does not match vendor {vendor_name!r}" if vendor_name else f"unknown vendor from {domain}")
    if wording_hit:
        reasons.append(f"payment/service wording: {wording_hit.group(0)!r}")
    if amount >= 5000:
        reasons.append(f"amount {amount:,.2f}")
    flagged = (not in_bc) and (not domain_matches) and bool(wording_hit)
    return {"flagged": flagged, "score": len(reasons), "reasons": reasons, "sender_domain": domain}


async def reassess_recent(db, days: int = 60, apply: bool = True) -> Dict[str, Any]:
    """Hourly: unlinked AP documents are re-assessed with the current rule
    and current vendor data. Only adds flags (a document resolved to a real
    vendor later must not lose one): "James Lucky" BlLL-B83748 arrived
    2026-09-23, before the rule knew its wording, and was never re-checked."""
    from datetime import datetime, timedelta, timezone
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    flagged = []
    async for d in db.hub_documents.find({"created_utc": {"$gte": since}, "mailbox_category": "AP", "bc_link": {"$exists": False},
                                          "fraud_risk.flagged": {"$ne": True}, "email_sender": {"$nin": [None, ""]}},
                                         {"_id": 1, "id": 1, "email_sender": 1, "email_subject": 1, "file_name": 1, "extracted_fields.vendor": 1,
                                          "vendor_raw": 1, "vendor_canonical": 1, "amount_float": 1}):
        r = await assess_fraud_risk(db, d)
        if r.get("flagged"):
            flagged.append((d.get("id"), r.get("reasons")))
            if apply:
                await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {"fraud_risk": {**r, "assessed_at": now, "source": "hourly_reassess"}}})
    return {"flagged": len(flagged), "examples": flagged[:5]}


PURGE_AFTER_DAYS = 30
_LINKED_FIELDS = ("document_id", "hub_doc_id", "doc_id")


async def purge(db, ids, reason: str) -> Dict[str, Any]:
    """Permanently delete documents (owner's decision 2026-10-09: suspected
    fraud is not shown to staff and is deleted): the document, its stored
    file, and every row that refers to it. Only a one-line note per document
    is kept (purge_log: sender domain, printed vendor, amount, why)."""
    from datetime import datetime, timezone
    from pathlib import Path
    from paths import UPLOAD_DIR
    ids = [i for i in ids if i]
    if not ids:
        return {"purged": 0}
    now = datetime.now(timezone.utc).isoformat()
    async for d in db.hub_documents.find({"id": {"$in": ids}}, {"_id": 0, "id": 1, "email_sender": 1, "vendor_raw": 1,
                                                               "extracted_fields.vendor": 1, "amount_float": 1, "created_utc": 1}):
        await db.purge_log.insert_one({"document_id": d["id"], "sender_domain": str(d.get("email_sender") or "").split("@")[-1],
                                       "vendor_printed": d.get("vendor_raw") or (d.get("extracted_fields") or {}).get("vendor"),
                                       "amount": d.get("amount_float"), "received": d.get("created_utc"), "reason": reason, "purged_at": now})
    files = 0
    for i in ids:
        for p in Path(UPLOAD_DIR).glob(f"{i}*"):
            if p.is_file():
                p.unlink()
                files += 1
    related = 0
    for c in await db.list_collection_names():
        if c in ("hub_documents", "purge_log"):
            continue
        try:
            r = await db[c].delete_many({"$or": [{f: {"$in": ids}} for f in _LINKED_FIELDS]})
            related += r.deleted_count
        except Exception:
            pass
    r = await db.hub_documents.delete_many({"id": {"$in": ids}})
    return {"purged": r.deleted_count, "files": files, "related_rows": related}


async def purge_expired(db, days: int = PURGE_AFTER_DAYS) -> Dict[str, Any]:
    """Hourly: suspected-fraud documents are hidden from staff when flagged
    and deleted PURGE_AFTER_DAYS later (time to notice a false positive)."""
    from datetime import datetime, timedelta, timezone
    cutoff = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    ids = [d["id"] async for d in db.hub_documents.find(
        {"fraud_risk.flagged": True, "bc_link": {"$exists": False},
         "$or": [{"fraud_risk.assessed_at": {"$lt": cutoff}},
                 {"fraud_risk.assessed_at": {"$exists": False}, "created_utc": {"$lt": cutoff}}]}, {"_id": 0, "id": 1})]
    return await purge(db, ids, f"suspected fraud, hidden {days} days")
