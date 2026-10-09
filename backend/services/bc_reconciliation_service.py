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



def _osa(a: str, b: str) -> int:
    """Edit distance with adjacent transpositions (optimal string alignment)."""
    d = [[0] * (len(b) + 1) for _ in range(len(a) + 1)]
    for i in range(len(a) + 1):
        d[i][0] = i
    for j in range(len(b) + 1):
        d[0][j] = j
    for i in range(1, len(a) + 1):
        for j in range(1, len(b) + 1):
            cost = 0 if a[i - 1] == b[j - 1] else 1
            d[i][j] = min(d[i - 1][j] + 1, d[i][j - 1] + 1, d[i - 1][j - 1] + cost)
            if i > 1 and j > 1 and a[i - 1] == b[j - 2] and a[i - 2] == b[j - 1]:
                d[i][j] = min(d[i][j], d[i - 2][j - 2] + 1)
    return d[len(a)][len(b)]


def near_number(hub: Any, bc: Any) -> bool:
    """Same invoice number up to one OCR/typing slip: one edit or adjacent
    transposition (Priority 19608487 / 19068487, TD Lines 19428 / 119428),
    or one number inside the other (Boyer SINV0021272 / 21272)."""
    a, b = _norm(hub), _norm(bc)
    if not a or not b or a == b:
        return False
    short, long_ = sorted((a, b), key=len)
    if len(short) >= 5 and short in long_:
        return True
    return min(len(a), len(b)) >= 5 and _osa(a, b) <= 1

async def reconcile_recent(db, days: int = 45, bc_days: int = 120, apply: bool = True) -> Dict[str, Any]:
    now = datetime.now(timezone.utc)
    stamp = now.isoformat()
    bc_since = (now - timedelta(days=bc_days)).date().isoformat()
    index: Dict[str, List[Dict[str, Any]]] = defaultdict(list)
    # Purchase credit memos are readable since 2026-10-06 (API Data Upgrade):
    # a document that is a BC credit memo links to it (BC stores the credit
    # total as a positive amount).
    for entity in ("posted_purchase_invoice", "draft_purchase_invoice", "purchase_credit_memo"):
        async for b in db.bc_reference_cache.find(
                {"bc_entity_type": entity, "bc_posting_date": {"$gte": bc_since}, "bc_status": {"$ne": "Canceled"}},
                {"_id": 0, "bc_entity_type": 1, "bc_document_no": 1, "bc_external_document_no": 1, "bc_vendor_no": 1,
                 "bc_vendor_name": 1, "bc_amount": 1, "bc_status": 1, "bc_order_number": 1, "bc_posting_date": 1}):
            for k in _index_keys(b.get("bc_external_document_no")):
                index[k].append(b)

    # AP splits one vendor invoice into one BC invoice per PO ("HH-150605B"
    # and "HH-150605B-1", Hwa Hsia): group BC rows by vendor and base number.
    parts_by_base: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    seen_rows = set()
    for rows in index.values():
        for b in rows:
            rid = (b.get("bc_entity_type"), b.get("bc_document_no"))
            if rid in seen_rows or b.get("bc_entity_type") == "purchase_credit_memo":
                continue
            seen_rows.add(rid)
            base = re.sub(r"-\d{1,2}$", "", str(b.get("bc_external_document_no") or "").strip().upper())
            if base:
                parts_by_base[(str(b.get("bc_vendor_no") or "").upper(), _norm(base))].append(b)
    invoice_by_amount: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for rows in parts_by_base.values():
        for b in rows:
            if b.get("bc_amount") is not None:
                invoice_by_amount[(str(b.get("bc_vendor_no") or "").upper(), round(abs(float(b["bc_amount"])) * 100))].append(b)
    credit_by_amount: Dict[Any, List[Dict[str, Any]]] = defaultdict(list)
    for rows in index.values():
        for b in rows:
            if b.get("bc_entity_type") == "purchase_credit_memo" and b.get("bc_amount") is not None:
                key = (str(b.get("bc_vendor_no") or "").upper(), round(abs(float(b["bc_amount"])) * 100))
                if b not in credit_by_amount[key]:
                    credit_by_amount[key].append(b)

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
    # Every mailbox: AP invoices also reach Operations / Sales (LSI,
    # Progressive, Rotondo, Happyann ...); only an exact BC match counts there,
    # and it moves the document to the AP lane.
    cursor = db.hub_documents.find(
        {"created_utc": {"$gte": since}, "is_duplicate": {"$ne": True},
         "status": {"$nin": ["batch_parent"]}, "document_type": {"$in": sorted(LINKABLE_TYPES)},
         "fraud_risk.flagged": {"$ne": True}},
        {"_id": 1, "id": 1, "document_type": 1, "invoice_number_clean": 1, "amount_float": 1, "mailbox_category": 1,
         "vendor_canonical": 1, "file_name": 1, "bc_link": 1, "invoice_number_extracted_previous": 1,
         "vendor_canonical_backfill": 1, "po_number_clean": 1, "po_number_previous": 1, "batch_parent_id": 1,
         "created_utc": 1, "bc_combined_entry": 1})
    async for d in cursor:
        is_ap = d.get("mailbox_category") == "AP"
        stats["documents" if is_ap else "non_ap_documents"] += 1
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
                if (b.get("bc_entity_type") != "purchase_credit_memo"
                        and hub_amt is not None and bc_amt is not None and float(hub_amt) < 0 < float(bc_amt)):
                    credit_of = b
                    continue
                if vend_ok and how != "number+vendor":
                    best, how = b, "number+vendor"
                elif best is None and len(k) >= 7:
                    best, how = b, "number"
            if how == "number+amount":
                break
        if best is None and not d.get("invoice_number_clean") and hub_vendor and not d.get("batch_parent_id"):
            # No invoice number extracted (Canpack credit memos "Invoice
            # 1111600262.PDF"): the number in the file name, when BC has it
            # for the same vendor and the amount agrees or was not read.
            for num in re.findall(r"(?<![0-9])[0-9]{6,12}(?![0-9])", str(d.get("file_name") or "")):
                for b in index.get(_norm(num), []):
                    if str(b.get("bc_vendor_no") or "").upper() != hub_vendor:
                        continue
                    if await db.hub_documents.count_documents({"bc_link.bc_document_no": b.get("bc_document_no"),
                                                                "bc_link.bc_entity": b.get("bc_entity_type"),
                                                                "_id": {"$ne": d["_id"]}}, limit=1):
                        continue
                    bc_amt = b.get("bc_amount")
                    if hub_amt in (None, 0, 0.0) or (bc_amt is not None and abs(abs(float(hub_amt)) - abs(float(bc_amt))) < 0.02):
                        best, how = b, "filename+vendor"
                        break
                if best is not None:
                    break
        if (best is None and hub_vendor and hub_amt not in (None, 0, 0.0) and not d.get("batch_parent_id")
                and (d.get("document_type") == "Credit_Memo" or float(hub_amt) < 0)):
            # Vendors reformat credit numbers in BC ("126370RMA",
            # "3038980-10-RMA", "311435A CM"): the one BC credit memo of the
            # same vendor and exact amount, within 60 days, not taken.
            cands = [b for b in credit_by_amount.get((hub_vendor, round(abs(float(hub_amt)) * 100)), [])
                     if abs((datetime.fromisoformat(str(b.get("bc_posting_date"))[:10])
                             - datetime.fromisoformat(str(d.get("created_utc") or stamp)[:10])).days) <= 60]
            if len(cands) == 1 and not await db.hub_documents.count_documents(
                    {"bc_link.bc_document_no": cands[0].get("bc_document_no"), "bc_link.bc_entity": "purchase_credit_memo",
                     "_id": {"$ne": d["_id"]}}, limit=1):
                best, how = cands[0], "amount+vendor(credit)"
        if (best is None and hub_vendor and hub_amt not in (None, 0, 0.0) and d.get("invoice_number_clean")
                and not d.get("batch_parent_id")):
            # Same vendor and amount, number off by one slip: an extraction
            # error BC corrects (and invoice_number_rules learns from).
            cands = [b for b in invoice_by_amount.get((hub_vendor, round(abs(float(hub_amt)) * 100)), [])
                     if near_number(d.get("invoice_number_clean"), b.get("bc_external_document_no"))
                     and abs((datetime.fromisoformat(str(b.get("bc_posting_date"))[:10])
                              - datetime.fromisoformat(str(d.get("created_utc") or stamp)[:10])).days) <= 60]
            if len(cands) == 1 and not await db.hub_documents.count_documents(
                    {"bc_link.bc_document_no": cands[0].get("bc_document_no"), "_id": {"$ne": d["_id"]}}, limit=1):
                best, how = cands[0], "near-number+amount"
        if best is None:
            if apply and (d.get("bc_link") or credit_of):
                upd = {"$unset": {"bc_link": "", "bc_amount_mismatch": ""}}
                if credit_of:
                    upd["$set"] = {"bc_credit_of": {"bc_document_no": credit_of.get("bc_document_no"),
                                                    "bc_external_document_no": credit_of.get("bc_external_document_no"),
                                                    "bc_vendor_no": credit_of.get("bc_vendor_no"), "at": stamp}}
                await db.hub_documents.update_one({"_id": d["_id"]}, upd)
            stats["credit_of_invoice" if credit_of else ("unlinked" if is_ap else "non_ap_unlinked")] += 1
            continue
        parts = []
        if how != "number+amount" and hub_amt is not None:
            group = parts_by_base.get((str(best.get("bc_vendor_no") or "").upper(),
                                       _norm(re.sub(r"-\d{1,2}$", "", str(best.get("bc_external_document_no") or "").strip().upper()))), [])
            if len(group) > 1 and abs(abs(float(hub_amt)) - sum(abs(float(g.get("bc_amount") or 0)) for g in group)) < 0.05:
                parts = sorted(group, key=lambda g: str(g.get("bc_external_document_no")))
                best, how = parts[0], "number+amount(parts)"
        stats["linked:" + how] += 1
        link = {"bc_document_no": best.get("bc_document_no"), "bc_entity": best.get("bc_entity_type"),
                "bc_status": best.get("bc_status"), "bc_vendor_no": best.get("bc_vendor_no"),
                "bc_vendor_name": best.get("bc_vendor_name"), "bc_amount": best.get("bc_amount"),
                "bc_order_number": best.get("bc_order_number") or "", "bc_posting_date": best.get("bc_posting_date"),
                "match": how, "linked_at": stamp}
        if parts:
            link["bc_parts"] = [{"bc_document_no": g.get("bc_document_no"), "bc_external_document_no": g.get("bc_external_document_no"),
                                 "bc_amount": g.get("bc_amount"), "bc_order_number": g.get("bc_order_number") or ""} for g in parts]
            link["bc_amount"] = round(sum(float(g.get("bc_amount") or 0) for g in parts), 2)
            link["bc_order_numbers"] = [g.get("bc_order_number") for g in parts if g.get("bc_order_number")]
        # First-pass accuracy: were the values intake produced already what BC
        # says, before any correction? Measured once, at the first link, so the
        # trend shows whether extraction itself is learning.
        prev_link = d.get("bc_link") or {}
        if prev_link.get("bc_document_no") == best.get("bc_document_no"):
            for k in ("bc_ship_to", "bc_ship_to_city", "bc_ship_to_lane", "bc_location_codes", "bc_location_lane"):
                if k in prev_link:
                    link[k] = prev_link[k]
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
                "po_ok": (_norm(d.get("po_number_previous") or d.get("po_number_clean")) == _norm(best.get("bc_order_number"))
                          if best.get("bc_order_number") else None),
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
        keep_hub_number = False
        if how == "near-number+amount" and bc_ext:
            # Which side slipped? A formatting difference (one number inside
            # the other: Boyer SINV0021272 / 21272) -> BC's form. Otherwise
            # the vendor's file name decides: when it carries the Hub number
            # and not BC's, AP mistyped it in BC (Ball 6328664 entered as
            # 60328664, ATS 10606122 as 1060122) -> keep ours, flag for AP.
            hn, bn, fn = _norm(d.get("invoice_number_clean")), _norm(bc_ext), _norm(d.get("file_name"))
            short, long_ = sorted((hn, bn), key=len)
            if not (len(short) >= 5 and short in long_) and not (bn and bn in fn):
                keep_hub_number = True
                update["bc_number_typo_suspect"] = {"hub": d.get("invoice_number_clean"), "bc": bc_ext,
                                                    "bc_document_no": best.get("bc_document_no"),
                                                    "file_supports_hub": bool(hn and hn in fn), "at": stamp}
                stats["bc_number_typo_suspect"] += 1
        if how in ("filename+vendor", "amount+vendor(credit)", "near-number+amount") and bc_ext and not keep_hub_number:
            update["invoice_number_clean"] = bc_ext.upper()
            update["invoice_number_extracted_previous"] = d.get("invoice_number_clean")
            events.append({"kind": "invoice_number", "from": d.get("invoice_number_clean"), "to": bc_ext.upper()})
            if hub_amt in (None, 0, 0.0) and best.get("bc_amount") is not None:
                sign = -1 if best.get("bc_entity_type") == "purchase_credit_memo" else 1
                update["amount_float"] = sign * abs(float(best["bc_amount"]))
                update["amount_from_bc"] = {"at": stamp, "previous": hub_amt}
                events.append({"kind": "amount", "from": hub_amt, "to": update["amount_float"]})
        if (how == "number+amount" and via_loose and bc_ext and "/" not in bc_ext
                and _norm(bc_ext) != _norm(d.get("invoice_number_clean"))):
            update["invoice_number_clean"] = bc_ext.upper()
            update["invoice_number_extracted_previous"] = d.get("invoice_number_clean")
            events.append({"kind": "invoice_number", "from": d.get("invoice_number_clean"), "to": bc_ext.upper()})
        # The Gamer order on the BC invoice is the PO: glued lists
        # ("117751/42221" stored as 11775142221), the order in second place
        # ("P0028017-40/116355"), labels ("Multi-Trucks").
        bc_order = str(best.get("bc_order_number") or "").strip()
        if how == "number+amount" and bc_order and _norm(bc_order) != _norm(d.get("po_number_clean")):
            update["po_number_clean"] = bc_order.upper()
            update["po_number_previous"] = d.get("po_number_previous") or d.get("po_number_clean")
            update["po_number_source"] = "bc_order_number"
            events.append({"kind": "po", "from": d.get("po_number_clean"), "to": bc_order.upper()})
        is_bc_credit = best.get("bc_entity_type") == "purchase_credit_memo"
        if how in ("number+amount", "filename+vendor", "amount+vendor(credit)") and (
                (is_bc_credit and d.get("document_type") != "Credit_Memo")
                or (not is_bc_credit and d.get("document_type") == "Credit_Memo" and float(best.get("bc_amount") or 0) > 0)):
            # BC says which it is: a credit memo, or an invoice the Hub typed
            # as a credit (Canpack 1111600287/88).
            new_type = "Credit_Memo" if is_bc_credit else "AP_Invoice"
            update.update({"document_type": new_type, "suggested_job_type": new_type,
                           "document_type_previous": d.get("document_type"),
                           "document_type_corrected": {"at": stamp, "reason": "BC document type"}})
            events.append({"kind": "doc_type", "from": d.get("document_type"), "to": new_type})
        elif how in ("number+amount", "number+vendor") and d.get("document_type") in RETYPE_FROM:
            new_type = "Credit_Memo" if float(best.get("bc_amount") or 0) < 0 else "AP_Invoice"
            update.update({"document_type": new_type, "suggested_job_type": new_type,
                           "document_type_previous": d.get("document_type"),
                           "document_type_corrected": {"at": stamp, "reason": "BC has this invoice"}})
            events.append({"kind": "doc_type", "from": d.get("document_type"), "to": new_type})
        if d.get("mailbox_category") != "AP":
            if how != "number+amount":
                stats["non_ap_mailbox_not_exact"] += 1
                continue
            update.update({"mailbox_category": "AP", "mailbox_from_bc": {
                "at": stamp, "previous": d.get("mailbox_category"), "bc_document_no": best.get("bc_document_no")}})
            events.append({"kind": "mailbox", "from": d.get("mailbox_category"), "to": "AP"})
        unset = {}
        combined = (d.get("bc_combined_entry") or {}).get("bc_document_no") == best.get("bc_document_no")
        if how == "number+vendor" and hub_amt is not None and best.get("bc_amount") is not None and not combined:
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


SHIP_TO_BATCH = 15
SHIP_TO_PER_RUN = 600


def location_lane(codes: List[str]) -> str:
    """BC location code on the invoice lines decides the lane (per AP):
    "00" is dropship, any other location is a warehouse; no location (freight
    and charge lines) says nothing."""
    codes = [c for c in codes if c]
    if not codes:
        return ""
    return "dropship" if all(c == "00" for c in codes) else "warehouse"


def ship_to_lane(name: Any) -> str:
    """Lane implied by the BC invoice ship-to: a Gamer warehouse or
    consignment stock -> warehouse; Gamer head office -> unknown (freight
    carriers bill to it); anyone else (the customer) -> dropship."""
    n = str(name or "").strip().lower()
    if not n:
        return ""
    if "warehouse" in n or "consignment" in n or "c/o" in n or " wh " in f" {n} ":
        return "warehouse"
    if "gamer" in n:
        return ""
    return "dropship"


async def fetch_ship_to(db, limit: int = SHIP_TO_PER_RUN) -> Dict[str, Any]:
    """Fill bc_link.bc_ship_to for linked documents (read-only BC GET,
    SHIP_TO_BATCH invoice numbers per request)."""
    import httpx
    import services.bc_catalog_sync_service as bc
    todo = []
    async for d in db.hub_documents.find(
            {"bc_link.bc_document_no": {"$exists": True}, "bc_link.bc_location_lane": {"$exists": False}},
            {"_id": 1, "bc_link.bc_document_no": 1}).limit(limit):
        todo.append((d["_id"], d["bc_link"]["bc_document_no"]))
    if not todo:
        return {"fetched": 0}
    token = await bc.get_bc_token(environment="Production")
    cid = await bc.get_bc_company_id(environment="Production")
    url = f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/Production/api/{bc.BC_API_VERSION}/companies({cid})/purchaseInvoices"
    got = 0
    async with httpx.AsyncClient(timeout=60) as c:
        lr = await c.get(f"{url.rsplit('/', 1)[0]}/locations", headers={"Authorization": f"Bearer {token}"},
                         params={"$select": "id,code"})
        loc_code = {l["id"]: l["code"] for l in lr.json().get("value", [])} if lr.status_code == 200 else {}
        for i in range(0, len(todo), SHIP_TO_BATCH):
            chunk = todo[i:i + SHIP_TO_BATCH]
            nums = sorted({str(n) for _, n in chunk if n})
            flt = " or ".join(f"number eq '{n}'" for n in nums)
            r = await c.get(url, headers={"Authorization": f"Bearer {token}"},
                            params={"$filter": flt, "$select": "number,shipToName,shipToCity,shipToState",
                                    "$expand": "purchaseInvoiceLines($select=locationId)"})
            if r.status_code != 200:
                continue
            by_no = {v["number"]: v for v in r.json().get("value", [])}
            for oid, n in chunk:
                v = by_no.get(str(n))
                ship = (v or {}).get("shipToName") or ""
                codes = sorted({loc_code.get(l.get("locationId"), "") for l in (v or {}).get("purchaseInvoiceLines") or []
                                if l.get("locationId") and not str(l["locationId"]).startswith("00000000")} - {""})
                await db.hub_documents.update_one({"_id": oid}, {"$set": {
                    "bc_link.bc_ship_to": ship,
                    "bc_link.bc_ship_to_city": (v or {}).get("shipToCity") or "",
                    "bc_link.bc_ship_to_lane": ship_to_lane(ship),
                    "bc_link.bc_location_codes": codes,
                    "bc_link.bc_location_lane": location_lane(codes)}})
                got += 1
    return {"fetched": got}



async def link_by_vendor_amount(db, days: int = 45, apply: bool = True) -> Dict[str, Any]:
    """Invoices whose number could not be read (scans, multi-invoice PDFs)
    linked to the BC invoice AP entered, by vendor + exact amount - only when
    BC holds exactly one invoice from that vendor for that amount around
    receipt and no other Hub document claims it (Amcor repeats amounts:
    7 x 29,439.15 stays with staff). The BC invoice's number is filled in."""
    from datetime import timedelta
    now = datetime.now(timezone.utc)
    since = (now - timedelta(days=days)).isoformat()
    stats = {"checked": 0, "linked": 0}
    async for d in db.hub_documents.find({
            "created_utc": {"$gte": since}, "mailbox_category": "AP", "bc_link": {"$exists": False},
            "document_type": {"$in": ["AP_Invoice", "Credit_Memo"]}, "status": {"$ne": "batch_parent"},
            "is_duplicate": {"$ne": True},
            "vendor_canonical": {"$nin": [None, ""]}, "amount_float": {"$nin": [None, 0, 0.0]},
            "$or": [{"invoice_number_clean": None}, {"invoice_number_clean": ""}, {"invoice_number_clean": {"$exists": False}}]},
            {"_id": 1, "id": 1, "vendor_canonical": 1, "amount_float": 1, "created_utc": 1}):
        stats["checked"] += 1
        recv = datetime.fromisoformat(str(d["created_utc"])[:19])
        lo, hi = (recv - timedelta(days=30)).date().isoformat(), (recv + timedelta(days=45)).date().isoformat()
        a = abs(float(d["amount_float"]))
        hits = [b async for b in db.bc_reference_cache.find(
            {"bc_vendor_no": d["vendor_canonical"], "bc_entity_type": {"$in": ["posted_purchase_invoice", "draft_purchase_invoice", "purchase_credit_memo"]},
             "bc_status": {"$ne": "Canceled"}, "bc_amount": {"$gte": a - 0.01, "$lte": a + 0.01}, "bc_posting_date": {"$gte": lo, "$lte": hi}},
            {"_id": 0})]
        if len(hits) != 1:
            continue
        b = hits[0]
        if await db.hub_documents.count_documents({"bc_link.bc_document_no": b["bc_document_no"]}, limit=1):
            continue
        stats["linked"] += 1
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {
                "bc_link": {"bc_document_no": b["bc_document_no"], "bc_entity": b["bc_entity_type"], "bc_status": b.get("bc_status"),
                            "bc_vendor_no": b.get("bc_vendor_no"), "bc_vendor_name": b.get("bc_vendor_name"), "bc_amount": b.get("bc_amount"),
                            "bc_order_number": b.get("bc_order_number"), "bc_posting_date": b.get("bc_posting_date"),
                            "match": "vendor+amount (no number on the document)", "linked_at": now.isoformat()},
                "invoice_number_clean": b.get("bc_external_document_no"),
                "invoice_number_source": "BC invoice AP entered (vendor + exact amount)"}})
    return stats


async def resolve_combined_entries(db, apply: bool = True) -> Dict[str, Any]:
    """AP often enters two invoices as one BC entry (external number
    "88530/88531", amount = their sum). Each Hub invoice then links with an
    amount 'mismatch' and sat in "Entered in BC, check" - Vpet, Aptar,
    WestRock, Canpack, Ball (12 of 35 on 2026-10-08). When the Hub invoices
    of that vendor named in BC's number add up to BC's amount, they are all
    that entry: linked, no mismatch."""
    import re as _re
    stamp = datetime.now(timezone.utc).isoformat()
    out = {"bc_entries": 0, "resolved_entries": 0, "documents": 0, "examples": []}
    bc_nos = await db.hub_documents.distinct("bc_link.bc_document_no", {"bc_amount_mismatch": {"$exists": True}})
    for bc_no in bc_nos:
        bc = await db.bc_reference_cache.find_one({"bc_document_no": bc_no, "bc_entity_type": {"$in": ["purchase_invoice", "posted_purchase_invoice", "purchase_credit_memo"]}},
                                                  {"_id": 0, "bc_external_document_no": 1, "bc_amount": 1, "bc_vendor_no": 1})
        bc = bc or await db.bc_reference_cache.find_one({"bc_document_no": bc_no}, {"_id": 0, "bc_external_document_no": 1, "bc_amount": 1, "bc_vendor_no": 1})
        if not bc or bc.get("bc_amount") is None:
            continue
        out["bc_entries"] += 1
        parts = [p for p in _re.split(r"[/,&]+", str(bc.get("bc_external_document_no") or "")) if _norm(p)]
        q = {"is_duplicate": {"$ne": True}, "document_type": {"$in": ["AP_Invoice", "Credit_Memo"]}, "amount_float": {"$ne": None},
             "$or": [{"bc_link.bc_document_no": bc_no}]}
        if len(parts) >= 2 and bc.get("bc_vendor_no"):
            q["$or"].append({"vendor_canonical": bc["bc_vendor_no"], "invoice_number_clean": {"$in": [p.strip() for p in parts]}})
        docs, copies, seen = [], [], set()
        async for d in db.hub_documents.find(q, {"_id": 1, "id": 1, "invoice_number_clean": 1, "amount_float": 1, "bc_link": 1, "vendor_canonical": 1}):
            copies.append(d)
            key = (_norm(d.get("invoice_number_clean")), round(abs(float(d["amount_float"])), 2))
            if key in seen:
                continue          # the same invoice twice (resent) counts once
            seen.add(key)
            docs.append(d)
        if len(docs) < 2:
            continue
        total = sum(abs(float(d["amount_float"])) for d in docs)
        if abs(total - abs(float(bc["bc_amount"]))) > 0.01 * len(docs):
            continue
        out["resolved_entries"] += 1
        out["documents"] += len(docs)
        if len(out["examples"]) < 10:
            out["examples"].append((bc_no, bc.get("bc_external_document_no"), bc["bc_amount"], [(d.get("invoice_number_clean"), d["amount_float"]) for d in docs]))
        if apply:
            first = next((d["bc_link"] for d in docs if d.get("bc_link")), None)
            for d in copies:      # every copy, linked or not
                upd = {"bc_combined_entry": {"bc_document_no": bc_no, "with": [x.get("id") for x in docs if x["_id"] != d["_id"]],
                                             "bc_amount": bc["bc_amount"], "at": stamp}}
                if not d.get("bc_link") and first:
                    upd["bc_link"] = {**first, "match": "combined_entry", "linked_at": stamp}
                await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": upd, "$unset": {"bc_amount_mismatch": ""}})
    return out


async def resolve_split_entries(db, days: int = 180, apply: bool = True) -> Dict[str, Any]:
    """The reverse of combined entries: AP splits one invoice across POs or
    receipts as several BC entries, the invoice number with a letter suffix
    (Canpack 1101622017 = 1101622017A..D: 8,254.52 + 11,006.02 + 1,834.34 +
    1,834.34 = 22,929.22; Ark 173961 = 173961 + 173961A surcharge). An
    unlinked Hub invoice whose vendor's BC entries "<number>" and
    "<number><letter>" add up to its amount is that entry set: linked to the
    first part, every part kept in bc_split_entries (65 found 2026-10-09)."""
    import re as _re
    stamp = datetime.now(timezone.utc).isoformat()
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    out = {"checked": 0, "linked": 0, "examples": []}
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "bc_link": {"$exists": False}, "is_duplicate": {"$ne": True},
             "document_type": {"$in": ["AP_Invoice", "Credit_Memo"]}, "vendor_canonical": {"$nin": [None, ""]},
             "invoice_number_clean": {"$nin": [None, ""]}, "amount_float": {"$nin": [None, 0]}},
            {"_id": 1, "id": 1, "vendor_canonical": 1, "invoice_number_clean": 1, "amount_float": 1}):
        base = _norm(d["invoice_number_clean"])
        if len(base) < 4:
            continue
        out["checked"] += 1
        parts = [b async for b in db.bc_reference_cache.find(
            {"bc_vendor_no": str(d["vendor_canonical"]).upper(), "normalized_external_ref": {"$regex": f"^{_re.escape(base)}[A-Z]?$"},
             "bc_entity_type": {"$in": ["posted_purchase_invoice", "draft_purchase_invoice", "purchase_credit_memo"]},
             "bc_status": {"$ne": "Canceled"}},
            {"_id": 0, "bc_document_no": 1, "bc_external_document_no": 1, "normalized_external_ref": 1, "bc_amount": 1,
             "bc_entity_type": 1, "bc_status": 1, "bc_vendor_no": 1, "bc_vendor_name": 1, "bc_order_number": 1, "bc_posting_date": 1})]
        if not any(p["normalized_external_ref"] != base for p in parts) or any(p.get("bc_amount") is None for p in parts):
            continue      # no suffixed part: the ordinary match handles it
        total = sum(abs(float(p["bc_amount"])) for p in parts)
        if abs(total - abs(float(d["amount_float"]))) > 0.01 * len(parts):
            continue
        parts.sort(key=lambda p: p["normalized_external_ref"])
        first = parts[0]
        out["linked"] += 1
        if len(out["examples"]) < 10:
            out["examples"].append((d["vendor_canonical"], base, d["amount_float"], [(p["normalized_external_ref"], p["bc_amount"]) for p in parts]))
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {
                "bc_link": {"bc_document_no": first["bc_document_no"], "bc_entity": first["bc_entity_type"], "bc_status": first.get("bc_status"),
                            "bc_vendor_no": first.get("bc_vendor_no"), "bc_vendor_name": first.get("bc_vendor_name"),
                            "bc_amount": round(total, 2), "bc_order_number": first.get("bc_order_number"),
                            "bc_posting_date": first.get("bc_posting_date"), "match": "split_entries", "linked_at": stamp},
                "bc_split_entries": [{"bc_document_no": p["bc_document_no"], "bc_external_document_no": p.get("bc_external_document_no"),
                                      "bc_amount": p["bc_amount"], "bc_order_number": p.get("bc_order_number")} for p in parts]}})
    return out
