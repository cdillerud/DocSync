"""Find the Gamer order on an invoice when the PO field holds something else.

Measured against BC (orders AP entered, 2026-09-06..10-06): the Hub's PO
matched BC's order only 75% of the time. 121 misses had the right order
glued to other text ("1144792060699" = 114479 + a customer number,
"116780CELLAR", "115207GB052926"); 46 read a vendor's own reference
(Canpack "81063374") while the Gamer order was elsewhere on the invoice.

For an invoice / credit whose PO is not a known Gamer order, candidates
are Gamer-shaped orders in the PO value (including a leading order glued
to more digits) and in the PDF text. Only orders BC knows (open or closed
purchase / sales orders, sharepoint_service._is_known_gamer_order) count,
and only a single surviving candidate is used (PO-field candidates win
over text). Hourly, idempotent:
* before AP enters it: po_number_clean := the order; the original stays
  in po_number_before_text;
* in either case po_from_text records the Hub's own answer, so the
  draft-readiness metric can score it (BC's correction is never touched).
"""
import logging
import re
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

ORDER_TOKEN = re.compile(r"(?<![A-Z0-9])(WA\d{4}|(?:WTR|WR|W)-?1?\d{5}|PR\d{5}|1\d{5})(?![0-9])", re.I)
LEADING_GLUED = re.compile(r"^((?:WTR|WR|W)-?1\d{5}|1\d{5})(?=[0-9A-Z])", re.I)


# Several known orders in the text (O-I prints the Giovanni ship-to 116687,
# also a Gamer order number, beside "Cust Release No:120400/63209"): the
# label before each is learned from invoices whose BC order is known.
# Replay on 2,117 entered invoices: 117 of 118 picked right (O-I 9/9), the
# miss on a two-letter "label" - single words under 3 letters are skipped.
LABEL_MIN_VENDOR, LABEL_MIN_ALL, LABEL_PRECISION = 3, 10, 0.95


def order_labels(text: str, cand: str) -> set:
    out = set()
    for m in re.finditer(r"(?<![A-Z0-9])" + re.escape(cand) + r"(?![0-9])", text, re.I):
        words = re.findall(r"[a-z]+", text[max(0, m.start() - 40): m.start()].lower())[-3:]
        if words:
            if len(words) > 1:
                out.add(" ".join(words))
            if len(words[-1]) >= 3:
                out.add(words[-1])
    return out


async def _text_orders(db, d: Dict[str, Any], known) -> tuple:
    from services.folder_routing_service import _pdf_text
    text = _pdf_text(d)[:20000]
    txt: List[str] = []
    for c in candidates_from(text):
        if c not in txt and await known(c):
            txt.append(c)
    return text, txt


async def learn_labels(db, known, limit: int = 400) -> int:
    """Count, per vendor and across vendors, how often each label stands
    before the order BC put the invoice on (po_order_labels). Each entered
    invoice is counted once."""
    n = 0
    async for d in db.hub_documents.find(
            {"bc_link.bc_order_number": {"$nin": [None, ""]}, "po_labels_learned": {"$exists": False}, "mailbox_category": "AP",
             "document_type": {"$in": ["AP_Invoice", "Credit_Memo"]}, "is_duplicate": {"$ne": True}, "status": {"$ne": "batch_parent"}},
            {"_id": 1, "vendor_canonical": 1, "bc_link.bc_order_number": 1, "file_content_b64": 1, "file_name": 1}).limit(limit):
        truth = str(d["bc_link"]["bc_order_number"]).strip().upper()
        text, txt = await _text_orders(db, d, known)
        v = str(d.get("vendor_canonical") or "")
        for c in txt:
            for lab in order_labels(text, c):
                for key, vend in ((f"{v}|{lab}", v), (f"*|{lab}", "*")):
                    await db.po_order_labels.update_one({"_id": key}, {"$set": {"vendor": vend, "label": lab},
                                                                       "$inc": {"tot": 1, "hit": int(c == truth)}}, upsert=True)
        await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {"po_labels_learned": datetime.now(timezone.utc).isoformat()}})
        n += 1
    return n


def _trusted_label(table: Dict[str, Any], vendor: str, labs: set):
    for lab in sorted(labs):
        for key, need in ((f"{vendor}|{lab}", LABEL_MIN_VENDOR), (f"*|{lab}", LABEL_MIN_ALL)):
            t = table.get(key)
            if t and t["tot"] >= need and t["hit"] >= LABEL_PRECISION * t["tot"]:
                return lab
    return None


def candidates_from(value: str) -> List[str]:
    v = str(value or "").strip().upper()
    out: List[str] = []
    m = LEADING_GLUED.match(v)
    if m:
        out.append(m.group(1).replace("-", ""))
    for t in ORDER_TOKEN.findall(v):
        t = t.upper().replace("-", "")
        if t not in out:
            out.append(t)
    return out


async def correct_recent(db, days: int = 14, apply: bool = True) -> Dict[str, Any]:
    from services.sharepoint_service import _is_known_gamer_order
    from services.folder_routing_service import _pdf_text
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    stats = {"checked": 0, "already_gamer_order": 0, "fixed_from_po_field": 0, "fixed_from_text": 0,
             "ambiguous": 0, "none_found": 0, "fixed_from_sibling": 0, "fixed_by_label": 0}
    known_cache: Dict[str, bool] = {}

    async def known(o: str) -> bool:
        if o not in known_cache:
            known_cache[o] = await _is_known_gamer_order(db, o)
        return known_cache[o]

    try:
        stats["labels_learned_from"] = await learn_labels(db, known)
    except Exception as e:
        logger.warning("[POCorrection] label learning failed: %r", e)
    labels = {x["_id"]: x async for x in db.po_order_labels.find({})}

    async for d in db.hub_documents.find(
            {"created_utc": {"$gte": since}, "mailbox_category": "AP", "is_duplicate": {"$ne": True},
             "document_type": {"$in": ["AP_Invoice", "Credit_Memo"]}, "po_from_text": {"$exists": False},
             "status": {"$ne": "batch_parent"}},
            {"_id": 1, "po_number_clean": 1, "po_number_previous": 1, "bc_link": 1, "file_content_b64": 1,
             "file_name": 1, "extracted_fields.po_number": 1, "batch_parent_id": 1, "invoice_number_clean": 1, "vendor_canonical": 1}):
        raw = d.get("po_number_previous") or d.get("po_number_clean") or (d.get("extracted_fields") or {}).get("po_number") or ""
        stats["checked"] += 1
        if raw and await known(str(raw).strip().upper()):
            stats["already_gamer_order"] += 1
            continue
        field = [c for c in candidates_from(raw) if await known(c)]
        found, source = None, None
        if len(set(field)) == 1:
            found, source = field[0], "po_field"
        elif not field:
            text = _pdf_text(d)[:20000]
            txt = []
            for c in candidates_from(text):
                if c not in txt and await known(c):
                    txt.append(c)
            if len(txt) == 1:
                found, source = txt[0], "pdf_text"
            elif len(txt) > 1:
                v = str(d.get("vendor_canonical") or "")
                picked = [(c, lab) for c in txt for lab in [_trusted_label(labels, v, order_labels(text, c))] if lab]
                if len(picked) == 1:
                    found, source = picked[0][0], f"pdf_text (label '{picked[0][1]}')"
                else:
                    stats["ambiguous"] += 1
        else:
            stats["ambiguous"] += 1
        if not found and not raw and d.get("batch_parent_id") and d.get("invoice_number_clean"):
            # Page 2 of a split invoice ("Invoice 1101621600_doc2"): the order
            # is on its sibling piece of the same invoice.
            sib = await db.hub_documents.find_one(
                {"batch_parent_id": d["batch_parent_id"], "invoice_number_clean": d["invoice_number_clean"],
                 "_id": {"$ne": d["_id"]}, "po_number_clean": {"$nin": [None, ""]}},
                {"_id": 0, "po_number_clean": 1})
            if sib and await known(str(sib["po_number_clean"]).strip().upper()):
                found, source = str(sib["po_number_clean"]).strip().upper(), "split_sibling"
        if not found:
            stats["none_found"] += 0 if (field or source) else 1
            continue
        stats["fixed_from_po_field" if source == "po_field" else ("fixed_from_sibling" if source == "split_sibling"
                                                                  else "fixed_by_label" if source.startswith("pdf_text (label") else "fixed_from_text")] += 1
        upd: Dict[str, Any] = {"po_from_text": {"value": found, "source": source, "raw": raw, "at": now}}
        if not d.get("bc_link"):
            upd.update({"po_number_clean": found, "po_number_before_text": raw})
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": upd})
    logger.info("[POCorrection] %s", stats)
    return stats

