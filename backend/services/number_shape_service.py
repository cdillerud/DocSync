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
        shapes[v] = {"lengths": ok_lens, "prefixes": None, "n": len(nums),
                     "digits_share": sum(1 for n in nums if n.isdigit()) / len(nums)}
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


async def _recent_numbers(db, vendor: Any) -> list:
    recent = []
    async for b in db.bc_reference_cache.find(
            {"bc_vendor_no": str(vendor or "").upper(),
             "bc_entity_type": {"$in": ["draft_purchase_invoice", "posted_purchase_invoice"]}},
            {"_id": 0, "bc_external_document_no": 1}).sort("bc_posting_date", -1).limit(30):
        n_ = _norm(b.get("bc_external_document_no"))
        if n_.isdigit():
            recent.append(int(n_))
    return recent


def _in_range(recent: list, c: str) -> bool:
    # Within the same-length series (Dayton has 9- and 10-digit series;
    # mixing them accepted anything).
    same = [r for r in recent if len(str(r)) == len(c)]
    if len(same) < 3:
        return False
    lo, hi = min(same), max(same)
    span = max(hi - lo, 50)
    return lo - span <= int(c) <= hi + 2 * span


_SUFFIX_CACHE: Dict[tuple, bool] = {}


async def _suffix_dropped(db, vendor: Any, suffix: str) -> bool:
    """Earlier invoices of this vendor numbered '<digits> <suffix>' that AP
    entered are in BC as <digits> at the same amount: at least 3, and 80% of
    the entered ones."""
    v = str(vendor or "").upper()
    if (v, suffix) in _SUFFIX_CACHE:
        return _SUFFIX_CACHE[(v, suffix)]
    same = n = 0
    seen = set()
    rx = r"^\s*\d{5,12}\s*" + re.escape(suffix) + r"\s*$"
    async for d in db.hub_documents.find({"vendor_canonical": v, "invoice_number_raw": {"$regex": rx, "$options": "i"},
                                          "amount_float": {"$gt": 0}}, {"_id": 0, "invoice_number_raw": 1, "amount_float": 1}).limit(400):
        dig = re.sub(r"\D", "", d["invoice_number_raw"])
        if dig in seen:
            continue
        seen.add(dig)
        bs = [b async for b in db.bc_reference_cache.find(
            {"bc_vendor_no": v, "normalized_external_ref": {"$in": [dig, dig.lstrip("0")]},
             "bc_entity_type": {"$in": ["draft_purchase_invoice", "posted_purchase_invoice"]}}, {"_id": 0, "bc_amount": 1})]
        if not bs:
            continue
        n += 1
        same += any(abs(float(b.get("bc_amount") or 0) - float(d["amount_float"])) <= 0.02 for b in bs)
    ok = same >= 3 and same >= 0.8 * n
    _SUFFIX_CACHE[(v, suffix)] = ok
    return ok


async def correct_recent(db, days: int = 30, apply: bool = True) -> Dict[str, Any]:
    from services.non_ap_reclassifier import NUMBER_IN_TEXT
    shapes = await vendor_shapes(db)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    stats = {"checked": 0, "misfit": 0, "corrected": 0}
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "mailbox_category": "AP", "document_type": {"$in": ["AP_Invoice", "Credit_Memo"]},
             "bc_link": {"$exists": False}, "invoice_number_clean": {"$nin": [None, ""]}},
            {"_id": 1, "vendor_canonical": 1, "invoice_number_clean": 1, "email_subject": 1, "file_name": 1, "po_number_clean": 1, "amount_float": 1}):
        shape = shapes.get(str(d.get("vendor_canonical") or "").upper())
        stats["checked"] += 1
        if fits(shape, d["invoice_number_clean"]) is not False:
            continue
        stats["misfit"] += 1
        # A letter prefix BC drops (Boyer "SINV0021577" is BC 21577 for the
        # same $86,322.33), for vendors whose BC numbers are digits (80%+). Only
        # a prefix: Anchor's "4906610RI" suffix marks a re-invoice of 4906610.
        m = re.fullmatch(r"[A-Z]{2,5}0*(\d{3,12})", _norm(d["invoice_number_clean"]))
        if m and shape and shape.get("digits_share", 0) >= 0.8 and fits(shape, m.group(1)):
            clash = await db.bc_reference_cache.find_one(
                {"bc_vendor_no": str(d.get("vendor_canonical") or "").upper(), "normalized_external_ref": m.group(1),
                 "bc_entity_type": {"$in": ["draft_purchase_invoice", "posted_purchase_invoice"]},
                 "bc_amount": {"$nin": [d.get("amount_float")]}}, {"_id": 1}) if d.get("amount_float") else None
            if not clash:
                stats["corrected"] += 1
                if apply:
                    await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {
                        "invoice_number_clean": m.group(1), "invoice_number_shape_previous": d["invoice_number_clean"],
                        "invoice_number_source": "vendor's BC number form (letter prefix dropped)", "invoice_number_filled_at": now}})
                continue
        # A letter suffix AP drops: Anchor "4884617 RI" is BC 4884617 at the
        # same amount on 356 of 393 earlier RI invoices; "RH" never is (0/9),
        # so it is learned per vendor and suffix from what AP entered.
        m = re.fullmatch(r"(\d{5,12})([A-Z]{1,3})", _norm(d["invoice_number_clean"]))
        if m and shape and fits(shape, m.group(1)) and await _suffix_dropped(db, d.get("vendor_canonical"), m.group(2)):
            stats["corrected"] += 1
            if apply:
                await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {
                    "invoice_number_clean": m.group(1), "invoice_number_shape_previous": d["invoice_number_clean"],
                    "invoice_number_source": f"vendor's BC number form (suffix {m.group(2)} dropped, as AP enters it)",
                    "invoice_number_filled_at": now}})
            continue
        candidates = []
        for text in (d.get("email_subject") or "", d.get("file_name") or ""):
            for m in NUMBER_IN_TEXT.finditer(text):
                candidates.append((m.group(1) or m.group(2) or "").strip("-").upper())
            candidates += re.findall(r"(?<![A-Za-z0-9])([A-Za-z]{0,4}\d{4,12})(?![A-Za-z0-9])", text)
        po = _norm(d.get("po_number_clean"))
        good = [c for c in dict.fromkeys(candidates) if fits(shape, c) and _norm(c) != po]
        src = "subject_or_file_name (vendor number shape)"
        recent = await _recent_numbers(db, d.get("vendor_canonical")) if shape and len(good) != 1 else []
        if len(good) > 1 and len(recent) >= 8:
            # Two numbers of the right shape (Tapi "PO 120023 - Invoice 40284";
            # a forwarder's bill number in a Vidrala subject): keep the one in
            # the range of this vendor's recent BC invoice numbers.
            # Compared on the digits; the full form is kept (Fillmore BC
            # numbers are "INV0559551", not "0559551").
            digits = lambda c: re.sub(r"\D", "", c).lstrip("0")
            good = [c for c in good if digits(c) and _in_range(recent, digits(c))]
            best = {}
            for c in good:
                if len(c) > len(best.get(digits(c), "")):
                    best[digits(c)] = c
            good = list(best.values())
            src = "subject_or_file_name (in the range of this vendor's recent BC invoice numbers)"
        if not good and len(recent) >= 8:
            # The PDF text, for vendors whose BC numbers are sequential: a
            # number in the range of their recent invoices (Progressive
            # 'ORIGINAL INVOICE 00133270' next to 132024..132983; the item
            # number 138978 on the same page is out of range).
            from services.amount_recovery_service import _pdf_text
            full = await db.hub_documents.find_one({"_id": d["_id"]})
            text = _pdf_text(full or {})
            cands = {_norm(t) for t in re.findall(r"(?<![A-Za-z0-9.,/-])(\d{4,12})(?![A-Za-z0-9.,/-])", text)}
            good = [c for c in cands if c.isdigit() and c != po and fits(shape, c) and _in_range(recent, c)]
            src = "PDF text (in the range of this vendor's recent BC invoice numbers)"
        if len(good) == 1:
            stats["corrected"] += 1
            if apply:
                await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {
                    "invoice_number_clean": good[0].upper(), "invoice_number_shape_previous": d["invoice_number_clean"],
                    "invoice_number_source": src, "invoice_number_filled_at": now}})
    return stats

