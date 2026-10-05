"""Per-document reconciliation of AP documents with Business Central.

Business Central is the ground truth for AP: once AP enters an invoice,
BC knows its vendor number, total, status and (for about half of the
invoices) the Gamer purchase order. This service links each recent
AP-lane Hub document to the BC purchase invoice it became and learns
from it:

* bc_link on the document: BC document number, entity (draft/posted),
  status, vendor, amount, order number, how it matched.
* vendor_canonical := BC vendor number when the match is exact
  (invoice number + amount); previous value kept in
  vendor_canonical_backfill.
* document_type := AP_Invoice / Credit_Memo when BC has the invoice and
  the Hub typed it as something else (shipping document, warehouse
  receipt, unknown); previous value kept.
* bc_amount_mismatch when the invoice number and vendor agree but the
  amounts differ (never overwritten: AP may have short-paid or adjusted).
* Every correction is logged to bc_learning_events; each run's metrics to
  bc_reconciliation_runs. Routing reads bc_link.bc_order_number as an
  order number (warehouse vs dropship by prefix).

Matching: normalized vendor invoice number, a 1-2 letter suffix stripped
(1101621742A), and an 8-digit tail for OCR prefix errors (R+L
I848946897 read as 1848946897). A match needs the amount or the vendor to
agree, or a 7+ character number. Runs hourly (learning_cycle_service).
"""
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

LINKABLE_TYPES = {"AP_Invoice", "Credit_Memo", "Unknown", "Unknown_Document", "Shipping_Document",
                  "Warehouse_Receipt", "Freight_Document", "Freight_Invoice", "Order_Confirmation", "Statement"}
RETYPE_FROM = {"Unknown", "Unknown_Document", "Shipping_Document", "Warehouse_Receipt", "Freight_Document",
               "Order_Confirmation"}


def _norm(x: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(x or "").upper()).lstrip("0")


def _keys(number: Any) -> List[str]:
    """Exact key first; then loose keys (suffix stripped, 8-digit tail) that
    only count when the amount agrees: Tumalo 0311459A is a separate invoice
    from 0311459, and an unentered A-invoice must not link to its base."""
    n = _norm(number)
    if len(n) < 4:
        return []
    keys = [n]
    m = re.fullmatch(r"(?:[A-Z]{1,3})?(\d{5,})[A-Z]{0,2}", n)
    keys.append("L:" + (m.group(1) if m else n))
    digits = re.sub(r"\D", "", n)
    if len(digits) >= 8:
        keys.append("D:" + digits[-8:])
    return keys


def _index_keys(number: Any) -> List[str]:
    """Keys for a BC external document number. A combined entry
    ("9406216478/9406216480", G3) is indexed under each number; a BC
    letter prefix ("CI154790", Shorr) is stripped for the loose key."""
    keys: List[str] = []
    for part in re.split(r"[/,;&]", str(number or "")):
        n = _norm(part)
        if len(n) < 4:
            continue
        keys.append(n)
        m = re.fullmatch(r"(?:[A-Z]{1,3})?(\d{5,})[A-Z]{0,2}", n)
        keys.append("L:" + (m.group(1) if m else n))
        digits = re.sub(r"\D", "", n)
        if len(digits) >= 8:
            keys.append("D:" + digits[-8:])
    return keys


async def reconcile_recent(db, days: int = 45, bc_days: int = 120, apply: bool = True) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    bc_since = (now - timedelta(days=bc_days)).date().isoformat()
    index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    for entity in ("posted_purchase_invoice", "draft_purchase_invoice"):
        async for b in db.bc_reference_cache.find(
                {"bc_entity_type": entity, "bc_posting_date": {"$gte": bc_since}, "bc_status": {"$ne": "Canceled"}},
                {"_id": 0, "bc_entity_type": 1, "bc_document_no": 1, "bc_external_document_no": 1, "bc_vendor_no": 1,
                 "bc_vendor_name": 1, "bc_amount": 1, "bc_status": 1, "bc_order_number": 1, "bc_posting_date": 1}):
            for k in _index_keys(b.get("bc_external_document_no")):
                index[k].append(b)

    stats: Counter = Counter()
    since = (now - timedelta(days=days)).isoformat()

    # Learn which vendors print a formatting suffix BC does not store
    # (Anchor "4902167RI" = BC "4902167"): 3+ amount-exact matches that only
    # work with the suffix stripped. For those vendors a suffix-stripped
    # number plus the same vendor is a match even when AP adjusted the
    # amount; elsewhere (Tumalo "0311459A" is its own invoice) it is not.
    suffix_hits: Counter = Counter()
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "mailbox_category": "AP", "is_duplicate": {"$ne": True},
             "amount_float": {"$ne": None}, "invoice_number_clean": {"$regex": "[0-9][A-Za-z]{1,2}$"}},
            {"_id": 0, "invoice_number_clean": 1, "amount_float": 1, "vendor_canonical": 1}):
        n = _norm(d.get("invoice_number_clean"))
        m = re.fullmatch(r"(\d{5,})([A-Z]{1,2})", n)
        if not m or index.get(n):
            continue
        for b in index.get("L:" + m.group(1), []):
            if b.get("bc_amount") is not None and abs(abs(float(d["amount_float"])) - abs(float(b["bc_amount"]))) < 0.02:
                suffix_hits[(str(b.get("bc_vendor_no") or "").upper(), m.group(2))] += 1
    format_suffix = {k for k, v in suffix_hits.items() if v >= 3}
    # Learned knowledge must persist: once numbers are corrected the
    # evidence above disappears, so stored vendor rules count too.
    async for r in db.vendor_invoice_number_rules.find({"rule": {"$regex": "^strip_suffix:"}}, {"_id": 0, "vendor": 1, "rule": 1}):
        format_suffix.add((str(r["vendor"]).upper(), r["rule"].split(":", 1)[1]))
    cursor = db.hub_documents.find(
        {"created_utc": {"$gte": since}, "mailbox_category": "AP", "is_duplicate": {"$ne": True},
         "status": {"$nin": ["batch_parent"]}, "document_type": {"$in": sorted(LINKABLE_TYPES)},
         "fraud_risk.flagged": {"$ne": True}},
        {"_id": 1, "id": 1, "document_type": 1, "invoice_number_clean": 1, "amount_float": 1,
         "vendor_canonical": 1, "file_name": 1, "bc_link": 1, "invoice_number_extracted_previous": 1,
         "vendor_canonical_backfill": 1})
    async for d in cursor:
        stats["documents"] += 1
        hub_amt = d.get("amount_float")
        hub_vendor = str(d.get("vendor_canonical") or "").upper()
        best, how, credit_of, via_loose = None, None, None, False
        for k in _keys(d.get("invoice_number_clean")):
            loose = k.startswith(("L:", "D:"))
            for b in index.get(k, []):
                bc_amt = b.get("bc_amount")
                amt_ok = (hub_amt is not None and bc_amt is not None
                          and abs(abs(float(hub_amt)) - abs(float(bc_amt))) < 0.02)
                vend_ok = bool(hub_vendor) and hub_vendor == str(b.get("bc_vendor_no") or "").upper()
                if amt_ok:
                    best, how = b, "number+amount"
                    via_loose = loose
                    break
                if loose:
                    sfx = re.fullmatch(r"\d{5,}([A-Z]{1,2})", _norm(d.get("invoice_number_clean")) or "")
                    if (k.startswith("L:") and vend_ok and sfx
                            and (hub_vendor, sfx.group(1)) in format_suffix and how != "number+vendor"):
                        best, how = b, "number+vendor"
                    continue
                # A credit memo cites the invoice it credits (Ball -1,670
                # against invoice 6437590 of 22,414.18): not that invoice.
                if hub_amt is not None and bc_amt is not None and float(hub_amt) < 0 < float(bc_amt):
                    credit_of = b
                    continue
                if vend_ok and how != "number+vendor":
                    best, how = b, "number+vendor"
                elif best is None and len(k) >= 7:
                    best, how = b, "number"
            if how == "number+amount":
                break
        if best is None:
            if apply and (d.get("bc_link") or credit_of):
                upd = {"$unset": {"bc_link": "", "bc_amount_mismatch": ""}}
                if credit_of:
                    upd["$set"] = {"bc_credit_of": {"bc_document_no": credit_of.get("bc_document_no"),
                                                    "bc_external_document_no": credit_of.get("bc_external_document_no"),
                                                    "bc_vendor_no": credit_of.get("bc_vendor_no"), "at": stamp}}
                await db.hub_documents.update_one({"_id": d["_id"]}, upd)
            stats["credit_of_invoice" if credit_of else "unlinked"] += 1
            continue
        stats["linked:" + how] += 1
        link = {"bc_document_no": best.get("bc_document_no"), "bc_entity": best.get("bc_entity_type"),
                "bc_status": best.get("bc_status"), "bc_vendor_no": best.get("bc_vendor_no"),
                "bc_vendor_name": best.get("bc_vendor_name"), "bc_amount": best.get("bc_amount"),
                "bc_order_number": best.get("bc_order_number") or "", "bc_posting_date": best.get("bc_posting_date"),
                "match": how, "linked_at": stamp}
        # First-pass accuracy: were the values intake produced already what BC
        # says, before any correction? Measured once, at the first link, so the
        # trend shows whether extraction itself is learning.
        prev_link = d.get("bc_link") or {}
        if prev_link.get("first_pass"):
            link["first_pass"] = prev_link["first_pass"]
        elif how == "number+amount":
            raw_inv = d.get("invoice_number_extracted_previous") or d.get("invoice_number_clean")
            vb = d.get("vendor_canonical_backfill") or {}
            raw_vendor = vb.get("previous") if str(vb.get("from", "")).startswith("bc_") else d.get("vendor_canonical")
            link["first_pass"] = {
                "invoice_number_ok": _norm(raw_inv) == _norm(best.get("bc_external_document_no")),
                "vendor_ok": str(raw_vendor or "").upper() == str(best.get("bc_vendor_no") or "").upper(),
                "amount_ok": True,
                "measured_at": stamp,
            }
        update: Dict[str, Any] = {"bc_link": link}
        events = []
        bc_vendor = str(best.get("bc_vendor_no") or "")
        if how == "number+amount" and bc_vendor and hub_vendor != bc_vendor.upper():
            update["vendor_canonical"] = bc_vendor
            update["vendor_canonical_backfill"] = {"at": stamp, "previous": d.get("vendor_canonical"),
                                                   "from": "bc_reconciliation"}
            events.append({"kind": "vendor", "from": d.get("vendor_canonical"), "to": bc_vendor})
        # Matched only on a loose key (OCR "1848946897" for R+L "I848946897",
        # formatting suffix "4898677RI") but to the cent: BC's number is the
        # invoice number.
        bc_ext = str(best.get("bc_external_document_no") or "").strip()
        if (how == "number+amount" and via_loose and bc_ext and "/" not in bc_ext
                and _norm(bc_ext) != _norm(d.get("invoice_number_clean"))):
            update["invoice_number_clean"] = bc_ext.upper()
            update["invoice_number_extracted_previous"] = d.get("invoice_number_clean")
            events.append({"kind": "invoice_number", "from": d.get("invoice_number_clean"), "to": bc_ext.upper()})
        if how in ("number+amount", "number+vendor") and d.get("document_type") in RETYPE_FROM:
            new_type = "Credit_Memo" if float(best.get("bc_amount") or 0) < 0 else "AP_Invoice"
            update.update({"document_type": new_type, "suggested_job_type": new_type,
                           "document_type_previous": d.get("document_type"),
                           "document_type_corrected": {"at": stamp, "reason": "BC has this invoice"}})
            events.append({"kind": "doc_type", "from": d.get("document_type"), "to": new_type})
        unset = {}
        if how == "number+vendor" and hub_amt is not None and best.get("bc_amount") is not None:
            update["bc_amount_mismatch"] = {"hub": hub_amt, "bc": best.get("bc_amount"), "at": stamp}
            stats["amount_mismatch"] += 1
        else:
            unset["bc_amount_mismatch"] = ""
        for e in events:
            stats["corrected:" + e["kind"]] += 1
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": update, **({"$unset": unset} if unset else {})})
            for e in events:
                await db.bc_learning_events.insert_one({**e, "document_id": d.get("id"), "file_name": d.get("file_name"),
                                                        "bc_document_no": link["bc_document_no"], "match": how, "at": stamp})
    linked = sum(v for k, v in stats.items() if k.startswith("linked:"))
    stats.pop("unlinked", None)
    result = {"at": stamp, "documents": stats["documents"], "linked": linked,
              "link_rate_pct": round(100 * linked / stats["documents"], 1) if stats["documents"] else None}
    result.update({k: v for k, v in stats.items() if k != "documents"})
    result["format_suffixes"] = sorted(f"{v}:{x}" for v, x in format_suffix)
    if apply:
        await db.bc_reconciliation_runs.insert_one(dict(result))
    logger.info("[BCReconcile] %s", result)
    return result
