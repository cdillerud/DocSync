"""Link every sales-mailbox document to Gamer's BC sales history, and say
what it is (role) - BC is the ground truth, as on the AP side.

Roles:
  customer_po       a customer's purchase order / order request (the work:
                    becomes a BC sales order)
  customer_other    other mail from a customer (artwork, quality, forecasts)
  gamer_order_copy  Gamer's own order confirmation / pick ticket / invoice
                    for an order already in BC (evidence, not work)
  supplier          a supplier's document about a Gamer purchase order
                    (purchasing, not sales)
  ap_invoice / ar_invoice / shipping / other

Link (sales_link.order_no): the BC sales order whose customer PO
(externalDocumentNumber) equals the document's customer PO, else a Gamer
order number named in the subject / file name / extracted fields.
Counterparty from the sender's e-mail domain: BC customer e-mail domains,
domains learned from linked customer POs, vendor domains from AP mail.
"""
import logging
import re
from collections import Counter, defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set

logger = logging.getLogger(__name__)

GAMER_DOMAIN = "gamerpackaging.com"
_FREE_MAIL = {"gmail.com", "yahoo.com", "outlook.com", "hotmail.com", "aol.com", "icloud.com", "comcast.net", "msn.com"}
_ORDER_NO = re.compile(r"(?<![A-Z0-9])(1\d{5})(?![0-9])")
_GAMER_PO = re.compile(r"(?<![A-Z0-9])(W1\d{5}|WR1\d{5}|WA\d{4,6})(?![0-9])", re.I)
_NOT_ORDER = re.compile(r"\b(scar|rejection|reject|damage|damaged|spec|specification|sample|samples|complaint|issue|recycl|rma|vrma|quality|coa|certificate)\b", re.I)
_PO_WORDS = re.compile(r"\b(purchase\s*order|p\.?\s?o\.?\s*#|\bPO\b|order\s+request|blanket|release)", re.I)


def norm(x: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(x or "").upper()).lstrip("0")


def po_variants(x: Any) -> Set[str]:
    """A document's PO as match keys: "PO-63612", "P0029666, Rev. 3",
    "PO26-1809" -> the PO itself, without its PO prefix and without a
    short suffix / revision (same keys as BC's ext_tokens)."""
    from services.bc_sales_history_service import ext_tokens
    first = re.split(r",|\brev\b|\brevision\b", str(x or ""), flags=re.I)[0]
    return set(ext_tokens(first))


def domain(sender: Any) -> str:
    s = str(sender or "").lower().strip()
    return s.split("@")[-1] if "@" in s else ""


async def counterparty_maps(db) -> Dict[str, Dict[str, Any]]:
    """domain -> {"customer": no} | {"vendor": no}."""
    cust = defaultdict(Counter)
    async for c in db.bc_reference_cache.find({"bc_entity_type": "customer", "email": {"$nin": [None, ""]}},
                                              {"_id": 0, "bc_customer_no": 1, "email": 1}):
        for e in re.split(r"[;, ]+", str(c["email"])):
            dm = domain(e)
            if dm and dm not in _FREE_MAIL and not dm.endswith(GAMER_DOMAIN):
                cust[dm][c["bc_customer_no"]] += 1
    async for x in db.sales_customer_domains.find({}, {"_id": 0}):
        cust[x["domain"]][x["customer_no"]] += 5 * int(x.get("n") or 1)
    vend = defaultdict(Counter)
    async for x in db.hub_documents.aggregate([
            {"$match": {"mailbox_category": "AP", "vendor_canonical": {"$nin": [None, ""]}, "email_sender": {"$type": "string"}}},
            {"$project": {"dom": {"$arrayElemAt": [{"$split": [{"$toLower": "$email_sender"}, "@"]}, 1]}, "v": "$vendor_canonical"}},
            {"$group": {"_id": {"d": "$dom", "v": "$v"}, "n": {"$sum": 1}}}]):
        vend[x["_id"]["d"]][x["_id"]["v"]] += x["n"]
    out = {}
    for dm, cn in vend.items():
        v, n = cn.most_common(1)[0]
        if dm and n >= 3 and n / sum(cn.values()) >= 0.8 and not dm.endswith(GAMER_DOMAIN):
            out[dm] = {"vendor": v}
    for dm, cn in cust.items():
        c, n = cn.most_common(1)[0]
        out[dm] = {**out.get(dm, {}), "customer": c, "customers": [k for k, _ in cn.most_common(5)]}
    return out


def _texts(d: Dict[str, Any]) -> str:
    ef = d.get("extracted_fields") or {}
    return " ".join(str(x or "") for x in (d.get("email_subject"), d.get("file_name"), ef.get("order_number"),
                                           ef.get("po_number"), ef.get("reference")))


async def link_one(db, d: Dict[str, Any], maps: Dict[str, Dict[str, Any]]) -> Dict[str, Any]:
    ef = d.get("extracted_fields") or {}
    sender_dom = domain(d.get("email_sender"))
    internal = sender_dom.endswith(GAMER_DOMAIN)
    cp = maps.get(sender_dom, {}) if not internal else {}
    text = _texts(d)
    dt = d.get("document_type") or ""

    # Customer PO -> BC order with that externalDocumentNumber.
    pos = set()
    for x in (ef.get("po_number"), d.get("po_number_raw"), d.get("po_number_clean")):
        pos |= po_variants(x)
    order, match = None, None
    if pos:
        cands = [o async for o in db.bc_sales_orders.find({"ext_tokens": {"$in": list(pos)}},
                                                          {"_id": 0, "order_no": 1, "customer_no": 1, "ext_norm": 1, "status": 1})]
        if cands:
            pref = set(cp.get("customers") or [])
            best = [o for o in cands if o["customer_no"] in pref] or cands
            if len({o["customer_no"] for o in best}) == 1:
                order, match = best[0], "customer_po"
    # Gamer order number named on the document.
    nums = set(_ORDER_NO.findall(text.upper()))
    if not order and nums:
        found = [o async for o in db.bc_sales_orders.find({"order_no": {"$in": list(nums)}},
                                                          {"_id": 0, "order_no": 1, "customer_no": 1, "status": 1})]
        if len(found) == 1:
            order, match = found[0], "gamer_order_no"
    gamer_pos = {m.upper() for m in _GAMER_PO.findall(text)}
    if not gamer_pos and nums:
        known_po = await db.bc_reference_cache.find_one({"bc_entity_type": "purchase_order", "bc_document_no": {"$in": list(nums)}}, {"_id": 1})
        if known_po and not order:
            gamer_pos = nums

    # A "customer PO" number that is one of Gamer's own purchase orders (O-I
    # is customer and supplier: "Purchase Order 119900" is Gamer's PO to O-I).
    if pos and not order:
        if await db.bc_reference_cache.find_one({"bc_entity_type": "purchase_order", "bc_document_no": {"$in": [p for p in pos if p.isdigit() or p.startswith("W")]}}, {"_id": 1}):
            gamer_pos |= {p for p in pos}
            pos = set()
    has_lines = bool((ef.get("line_items") or []))
    # Role.
    po_words = bool(_PO_WORDS.search(f"{d.get('file_name')} {d.get('email_subject')}"))
    if dt == "AP_Invoice" and internal:
        # Gamer's own invoice / export paperwork forwarded by staff.
        role = "gamer_order_copy" if (order or nums) else "internal_other"
    elif dt == "AP_Invoice" and cp.get("customer") and not cp.get("vendor") and (pos or po_words or has_lines) and not gamer_pos:
        # A customer's PO the classifier called an invoice (Sun Bum PO010716).
        role = "customer_po"
    elif dt == "AP_Invoice":
        role = "ap_invoice"
    elif dt == "AR_Invoice":
        role = "ar_invoice"
    elif internal:
        role = "gamer_order_copy" if order else ("supplier" if gamer_pos else "internal_other")
    elif cp.get("vendor") and not cp.get("customer"):
        role = "supplier"
    elif gamer_pos and not order and (not cp.get("customer") or not pos):
        role = "supplier"
    elif dt in ("Shipping_Document", "Warehouse_Receipt") and not (order and match == "customer_po") \
            and not _PO_WORDS.search(f"{d.get('file_name')} {d.get('email_subject')}"):
        role = "shipping"
    elif cp.get("customer") or order or dt in ("Sales_Order", "Sales_Quote") or _PO_WORDS.search(f"{d.get('file_name')} {d.get('email_subject')}"):
        # A customer PO carries a PO number or order lines; complaints, specs,
        # samples and rejections that mention a PO are customer mail.
        role = "customer_po" if (dt in ("Sales_Order", "Sales_Quote", "Order_Confirmation", "Shipping_Document", "Unknown_Document")
                                 and (order or ((pos or has_lines) and not _NOT_ORDER.search(f"{d.get('file_name')} {d.get('email_subject')}"))
                                      and (pos or has_lines))) else "customer_other"
    else:
        role = "other"
    return {"role": role, "order_no": (order or {}).get("order_no"), "match": match,
            "bc_customer_no": (order or {}).get("customer_no") or cp.get("customer"),
            "counterparty": "gamer" if internal else ("customer" if cp.get("customer") else ("vendor" if cp.get("vendor") else "unknown")),
            "sender_domain": sender_dom, "customer_po": sorted(pos)[:3], "gamer_order_refs": sorted(nums)[:5],
            "gamer_po_refs": sorted(gamer_pos)[:5]}


async def run(db, days: int = 30, apply: bool = True) -> Dict[str, Any]:
    maps = await counterparty_maps(db)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    stats = Counter()
    learned = Counter()
    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "mailbox_category": {"$in": ["SALES", "Sales"]}, "status": {"$ne": "batch_parent"}},
            {"_id": 1, "id": 1, "document_type": 1, "email_sender": 1, "email_subject": 1, "file_name": 1,
             "extracted_fields": 1, "po_number_raw": 1, "po_number_clean": 1}):
        r = await link_one(db, d, maps)
        stats["role:" + r["role"]] += 1
        if r["order_no"]:
            stats["linked:" + r["role"]] += 1
        if r["role"] == "customer_po" and r["match"] == "customer_po" and r["sender_domain"] and r["counterparty"] != "gamer" \
                and r["sender_domain"] not in _FREE_MAIL:
            learned[(r["sender_domain"], r["bc_customer_no"])] += 1
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {"sales_link": {**r, "linked_at": now}}})
    if apply:
        for (dm, cust), n in learned.items():
            await db.sales_customer_domains.update_one({"domain": dm, "customer_no": cust},
                                                       {"$set": {"domain": dm, "customer_no": cust, "n": n, "updated_at": now}}, upsert=True)
    return dict(stats)

