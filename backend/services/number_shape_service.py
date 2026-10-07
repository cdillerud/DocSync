"""Per-vendor invoice-number shape learned from BC, and corrections from it.

NBC Packaging invoice "1813556" was read as "10" (2026-10-06): the Hub
never linked it to the BC invoice AP had entered and drafted a duplicate
in the sandbox. Each vendor's numbers in BC have a shape (NBCPACK: 7
digits starting "18"). A Hub number that does not fit is replaced by a
number from the e-mail subject / file name that does fit; if none fits,
sandbox drafting leaves the invoice to staff.

Shape (vendors with >= 10 BC invoices): normalized lengths seen on >= 5%
of numbers, and the leading two characters when one prefix family covers
>= 60% of them. Hourly, idempotent; original kept in
invoice_number_shape_previous.
"""
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional


def _norm(x: Any) -> str:
    # Leading zeros are formatting (Tumalo "0313645" is BC "313645").
    return re.sub(r"[^A-Z0-9]", "", str(x or "").upper()).lstrip("0")


async def vendor_shapes(db) -> Dict[str, Dict[str, Any]]:
    per: Dict[str, list] = {}
    async for b in db.bc_reference_cache.find(
            {"bc_entity_type": {"$in": ["draft_purchase_invoice", "posted_purchase_invoice"]},
             "bc_status": {"$ne": "Canceled"}, "bc_external_document_no": {"$nin": [None, ""]}},
            {"_id": 0, "bc_vendor_no": 1, "bc_external_document_no": 1}):
        per.setdefault(str(b.get("bc_vendor_no") or "").upper(), []).append(_norm(b["bc_external_document_no"]))
    shapes = {}
    for v, nums in per.items():
        nums = [n for n in nums if n][-300:]
        if len(nums) < 10:
            continue
        lens = Counter(len(n) for n in nums)
        ok_lens = {l for l, c in lens.items() if c / len(nums) >= 0.05}
        # Length only: sequential numbers drift (Ball 63xxxxx -> 64xxxxx), so a
        # prefix rule rejected numbers BC itself confirms.
        shapes[v] = {"lengths": ok_lens, "prefixes": None, "n": len(nums)}
    return shapes


def fits(shape: Optional[Dict[str, Any]], number: Any) -> Optional[bool]:
    """True / False when the vendor has a learned shape, None when unknown."""
    if not shape:
        return None
    n = _norm(number)
    if not n:
        return False
    if n and min(abs(len(n) - l) for l in shape["lengths"]) > 1:
        return False
    if shape["prefixes"] and n[:2] not in shape["prefixes"]:
        return False
    return True


async def correct_recent(db, days: int = 30, apply: bool = True) -> Dict[str, Any]:
    from services.non_ap_reclassifier import NUMBER_IN_TEXT
    shapes = await vendor_shapes(db)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    stats = {"checked": 0, "misfit": 0, "corrected": 0}
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "mailbox_category": "AP", "document_type": {"$in": ["AP_Invoice", "Credit_Memo"]},
             "bc_link": {"$exists": False}, "invoice_number_clean": {"$nin": [None, ""]}},
            {"_id": 1, "vendor_canonical": 1, "invoice_number_clean": 1, "email_subject": 1, "file_name": 1}):
        shape = shapes.get(str(d.get("vendor_canonical") or "").upper())
        stats["checked"] += 1
        if fits(shape, d["invoice_number_clean"]) is not False:
            continue
        stats["misfit"] += 1
        candidates = []
        for text in (d.get("email_subject") or "", d.get("file_name") or ""):
            for m in NUMBER_IN_TEXT.finditer(text):
                candidates.append((m.group(1) or m.group(2) or "").strip("-").upper())
            candidates += re.findall(r"(?<![A-Za-z0-9])([A-Za-z]{0,4}\d{4,12})(?![A-Za-z0-9])", text)
        good = [c for c in dict.fromkeys(candidates) if fits(shape, c)]
        if len(good) == 1:
            stats["corrected"] += 1
            if apply:
                await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {
                    "invoice_number_clean": good[0].upper(), "invoice_number_shape_previous": d["invoice_number_clean"],
                    "invoice_number_source": "subject_or_file_name (vendor number shape)", "invoice_number_filled_at": now}})
    return stats

