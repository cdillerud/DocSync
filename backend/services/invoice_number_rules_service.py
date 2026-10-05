"""Per-vendor invoice-number rules learned from BC corrections.

bc_reconciliation_service corrects a document's invoice number to BC's
when they match to the cent only after normalization (bc_learning_events
kind "invoice_number"). When a vendor shows the same correction shape 3+
times, that shape becomes a rule for the vendor and is applied to recent
documents BC has not seen yet, so their numbers are clean before AP enters
them (duplicate detection, matching, later posting):

  strip_suffix:<S>   "4902103RI" -> "4902103"       (Anchor prints RI)
  prefix:<F>-><T>    "1848887704" -> "I848887704"   (R+L "I" OCR'd as "1")

Rules are stored in vendor_invoice_number_rules; applied values keep the
extracted number in invoice_number_extracted_previous.
"""
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, Optional

logger = logging.getLogger(__name__)
MIN_EVIDENCE = 3


def _shape(old: str, new: str) -> Optional[str]:
    old, new = str(old or "").upper(), str(new or "").upper()
    m = re.fullmatch(r"(\d{5,})([A-Z]{1,2})", old)
    if m and m.group(1).lstrip("0") == new.lstrip("0"):
        return f"strip_suffix:{m.group(2)}"
    if len(old) == len(new) and old[1:] == new[1:] and old[:1] != new[:1]:
        return f"prefix:{old[:1]}->{new[:1]}"
    return None


def apply_rule(rule: str, number: str) -> Optional[str]:
    n = str(number or "").upper()
    if rule.startswith("strip_suffix:"):
        sfx = rule.split(":", 1)[1]
        if re.fullmatch(r"\d{5,}" + re.escape(sfx), n):
            return n[: -len(sfx)]
    elif rule.startswith("prefix:"):
        frm, to = rule.split(":", 1)[1].split("->")
        if n.startswith(frm) and len(n) >= 8:
            return to + n[1:]
    return None


async def learn_and_apply(db, days: int = 30) -> Dict[str, Any]:
    shapes: Dict[str, Counter] = defaultdict(Counter)
    async for e in db.bc_learning_events.find({"kind": "invoice_number"}, {"_id": 0, "from": 1, "to": 1, "document_id": 1}):
        doc = await db.hub_documents.find_one({"id": e.get("document_id")}, {"_id": 0, "vendor_canonical": 1})
        shape = _shape(e.get("from"), e.get("to"))
        if doc and shape and doc.get("vendor_canonical"):
            shapes[str(doc["vendor_canonical"]).upper()][shape] += 1
    rules = {v: s for v, c in shapes.items() for s, n in c.items() if n >= MIN_EVIDENCE}
    now = datetime.now(timezone.utc).isoformat()
    for v, rule in rules.items():
        await db.vendor_invoice_number_rules.update_one(
            {"vendor": v}, {"$set": {"vendor": v, "rule": rule, "evidence": shapes[v][rule], "updated_at": now}}, upsert=True)
    applied = 0
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    for v, rule in rules.items():
        async for d in db.hub_documents.find(
                {"vendor_canonical": v, "created_utc": {"$gte": since}, "bc_link": {"$exists": False},
                 "invoice_number_clean": {"$nin": [None, ""]}, "is_duplicate": {"$ne": True}},
                {"_id": 1, "id": 1, "invoice_number_clean": 1, "file_name": 1}):
            new = apply_rule(rule, d["invoice_number_clean"])
            if new and new != str(d["invoice_number_clean"]).upper():
                await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {
                    "invoice_number_clean": new, "invoice_number_extracted_previous": d["invoice_number_clean"],
                    "invoice_number_rule": rule}})
                await db.bc_learning_events.insert_one({"kind": "invoice_number_rule", "from": d["invoice_number_clean"],
                                                        "to": new, "rule": rule, "vendor": v, "document_id": d.get("id"),
                                                        "file_name": d.get("file_name"), "at": now})
                applied += 1
    result = {"rules": {v: r for v, r in rules.items()}, "applied": applied}
    logger.info("[InvoiceNumberRules] %s", result)
    return result
