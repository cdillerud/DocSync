"""Order flow: the order a document belongs to when it does not print ours.

Freight bills, customs entries, broker and forwarder invoices rarely carry
our order number; they carry the container, the ocean bill of lading or the
forwarder's shipment reference. Staff still know the order - they file the
bill in the order's folder and attach it to the order in Zetadocs - because
the same numbers are on the order's other paperwork (shipment information,
commercial invoice, packing list).

This learns that from the documents already tied to an order:
  - Zetadocs files on purchase/sales orders (record no. = the order) and
    files staff renamed with their orders,
  - the AP library's order folders (Temp Folder/.../W118530),
  - Hub documents whose order BC knows.
A number shared with earlier documents of one or two orders is a link.
Which kinds of numbers to believe is learned, not listed: walking forward in
time, each link's number shape (letters/digits pattern, e.g. a container
"A4N7"), per vendor where there is enough, is scored by whether it named the
document's real order. Only shapes that were right >= TRUST of the time are
used, and the whole thing turns itself on only if, on the latest SPLIT_DAYS
of documents that do not print their order, it is right >= GATE of the time.

Nothing is overwritten: the result is kept on the document as order_flow
{orders, via, from, shape} for routing and the AI to use as evidence.
"""
from __future__ import annotations

import collections
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, FrozenSet, List, Optional, Set, Tuple

logger = logging.getLogger("order_flow")

TOK = re.compile(r"\b[A-Z0-9][A-Z0-9\-/]{4,24}[A-Z0-9]\b")
ORD = re.compile(r"\b((?:WR|W)?\d{6})[A-Z]?\b")
_LEAD = re.compile(r"(?:WR|W)?\d{6}[A-Z]?")
_WORDER = re.compile(r"WR?\d{6}[A-Z]?")   # warehouse POs: a printed W-number is unambiguous
ORDER_RECORDS = {"Purchase Order", "Sales Order", "Posted Purchase Receipt"}
WINDOW_DAYS = 120          # containers and bills are reused; links are only to recent paperwork
MAX_ORDERS = 2             # a number shared by more orders identifies none of them
MIN_N = 15                 # observations before a shape's record counts
TRUST = 0.9
GATE = 0.95
GATE_MIN = 40
SPLIT_DAYS = 60
STATE_ID = "order_flow"

_IDX: Dict[str, Any] = {}


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def tokens(text: str) -> Set[str]:
    out = set()
    for t in TOK.findall((text or "").upper()):
        t = t.replace("-", "").replace("/", "")
        if 6 <= len(t) <= 20 and sum(ch.isdigit() for ch in t) >= 4:
            out.add(t)
    return out


def _clean(toks: Set[str], known: Set[str]) -> Set[str]:
    """Numbers that begin with one of our orders ("W11901932OZ") are the
    order printed on the document - the order-number reader's job, not a
    shared shipment number."""
    out = set()
    for t in toks:
        m = _LEAD.match(t)
        if m and (m.group(0) in known or m.group(0)[:-1] in known):
            continue
        out.add(t)
    return out


def _prints_order(toks: Set[str], orders) -> bool:
    return any(t.startswith(o) for t in toks for o in orders)


def shape(t: str) -> str:
    """Letter/digit runs: a container "YMMU7142196" -> "A4N7"."""
    return "".join(("A" if r[0].isalpha() else "N") + str(len(r)) for r in re.findall(r"[A-Z]+|[0-9]+", t))


def _stem(name: str) -> str:
    n = re.sub(r"\(\d+\)", "", (name or "").lower())
    return re.sub(r"\.[a-z0-9]+$", "", n).strip()


def _day(s: str) -> int:
    try:
        return datetime.fromisoformat(str(s)[:10]).toordinal()
    except Exception:
        return 0


async def _known_orders(db) -> Set[str]:
    """Order numbers only: BC orders, the order a receipt/shipment is for,
    and every purchase/sales order Zetadocs has files on (back to 2018; the
    BC cache holds only recent orders). Receipt and shipment document numbers
    are not orders - with them, the date "240223" in "w114318 tumalo 240223"
    was taken for an order (2026-10-25)."""
    known: Set[str] = set()
    async for r in db.bc_reference_cache.find({}, {"_id": 0, "normalized_document_no": 1, "bc_order_number": 1, "bc_entity_type": 1}):
        e = str(r.get("bc_entity_type"))
        if "order" in e and r.get("normalized_document_no"):
            known.add(str(r["normalized_document_no"]).upper())
        if r.get("bc_order_number"):
            known.add(str(r["bc_order_number"]).upper())
    async for r in db.bc_purchase_receipts.find({}, {"_id": 0, "orderNumber": 1}):
        if r.get("orderNumber"):
            known.add(str(r["orderNumber"]).upper())
    for no in await db.zetadocs_memory.distinct("record_no", {"record_type": {"$in": sorted(ORDER_RECORDS)}}):
        if no and len(no) >= 5:
            known.add(str(no).upper())
    return known


_YYMMDD = re.compile(r"(1[7-9]|2[0-9])(0[1-9]|1[0-2])(0[1-9]|[12][0-9]|3[01])")


def _date_like(o: str) -> bool:
    return len(o) == 6 and bool(_YYMMDD.fullmatch(o))


async def _documents(db, known: Set[str]) -> List[Tuple]:
    """(day, key, orders, numbers, vendor, stem, source, prints_its_order)
    for every document tied to an order."""
    def orders_in(s: str) -> Set[str]:
        # Staff's file names carry orders and dates ("w114318 tumalo 240223
        # 267593"): a bare yymmdd is the date; a W-number is always an order.
        out = set()
        for o in ORD.findall((s or "").upper().replace("_", " ")):   # "PO_W118530", "po_114948 + _114949"
            if o.startswith("W") or (o in known and not _date_like(o)):
                out.add(o)
        return out

    def row(day, key, o, text, vendor, name, src):
        raw = tokens(text)
        prints = _prints_order(raw, o)
        # Paperwork of a consolidated shipment names all its orders (an entry
        # summary filed as "115648" listing W118672-W118679): the document
        # belongs to all of them, so a number on it is no evidence for one.
        # Only W-orders: a bare 6-digit number is as often a receipt or zip.
        also = {t for t in raw if _WORDER.fullmatch(t) and t in known}
        if also - set(o) and len(set(o) | also) <= 12:
            o = set(o) | also
        return (day, key, frozenset(o), _clean(raw, known), vendor, _stem(name), src, prints)
    out = []
    # AP routes by purchase order. A sales order shares its number with the
    # purchase order only on dropship orders; a warehouse order's sales order
    # (120361) is a different number from its PO (W118658) and taught the
    # learner that the shared container was misleading (2026-10-25).
    pos: Set[str] = set()
    async for r in db.bc_reference_cache.find({"bc_entity_type": {"$in": ["purchase_order", "posted_purchase_receipt"]}},
                                              {"_id": 0, "normalized_document_no": 1, "bc_order_number": 1}):
        for k in ("normalized_document_no", "bc_order_number"):
            if r.get(k):
                pos.add(str(r[k]).upper())
    async for r in db.bc_purchase_receipts.find({}, {"_id": 0, "orderNumber": 1}):
        if r.get("orderNumber"):
            pos.add(str(r["orderNumber"]).upper())
    async for m in db.zetadocs_memory.find({"has_text": True}, {"_id": 1, "name": 1, "record_type": 1, "record_no": 1,
                                                               "company_no": 1, "created": 1, "text": 1}):
        sales = str(m.get("record_type", "")).startswith("Sales")
        if sales and m.get("record_no") not in pos:
            continue
        o = orders_in(m.get("name", ""))
        if m.get("record_type") in ORDER_RECORDS and m.get("record_no") in known:
            o.add(m["record_no"])
        if o and len(o) <= 12:
            out.append(row(_day(m.get("created")), m["_id"], o, m.get("text", ""), m.get("company_no") or "", m.get("name", ""),
                           "zetadocs_sales" if str(m.get("record_type", "")).startswith("Sales") else "zetadocs"))
    async for m in db.document_memory.find({"source": "sharepoint_ap", "folder": {"$regex": "^Temp Folder/"}, "text": {"$ne": ""}},
                                           {"_id": 0, "item_id": 1, "folder": 1, "name": 1, "created": 1, "text": 1}):
        o = orders_in("/".join(m["folder"].split("/")[2:]) + " " + m.get("name", ""))
        if o and len(o) <= 12:
            out.append(row(_day(m.get("created")), m["item_id"], o, m["text"], "", m.get("name", ""), "ap_folder"))
    # Freight bills staff attached in Zetadocs and renamed with their orders
    # ("W118604 W118607_TUMALO_0314238_10162026.pdf"): the Hub's own copy of
    # the same bill (vendor + invoice number) gets those orders as its label.
    # Staff attach a carrier's bill to the product order's record, so the
    # record's vendor is the supplier: match on the invoice number plus the
    # carrier's name in the file name ("..._TUMALO_0314238_...").
    renamed: Dict[str, List[Tuple[str, Set[str]]]] = {}
    async for m in db.zetadocs_memory.find({"record_type": {"$in": ["Purchase Invoice", "Posted Purchase Invoice", "Purchase Order"]},
                                            "name": {"$regex": r"\d{6}"}}, {"_id": 0, "name": 1}):
        o = orders_in(m.get("name", ""))
        if not o or len(o) > 6:
            continue
        up = m["name"].upper()
        for t in re.findall(r"[A-Z0-9]{5,}", up):
            if t not in o and sum(ch.isdigit() for ch in t) >= 5:
                renamed.setdefault(t.lstrip("0"), []).append((re.sub(r"[^A-Z]", "", up), o))
    pos = {}
    async for d in db.hub_documents.find({"invoice_number_clean": {"$nin": [None, ""]}, "vendor_canonical": {"$nin": [None, ""]},
                                          "po_number_clean": {"$in": [None, ""]}},
                                         {"_id": 0, "id": 1, "invoice_number_clean": 1, "vendor_canonical": 1, "created_utc": 1, "file_name": 1}):
        v4 = re.sub(r"[^A-Z]", "", str(d["vendor_canonical"]).upper())[:4]
        hits = [o for letters, o in renamed.get(str(d["invoice_number_clean"]).upper().lstrip("0"), []) if len(v4) == 4 and v4 in letters]
        o = set().union(*hits) if hits else set()
        if o and len(o) <= 6:
            pos[d["id"]] = {**d, "po_number_clean": " ".join(sorted(o)), "_orders": o}
    async for d in db.hub_documents.find({"po_number_clean": {"$nin": [None, ""]}}, {"_id": 0, "id": 1, "po_number_clean": 1,
                                                                                    "created_utc": 1, "vendor_canonical": 1, "file_name": 1}):
        po = str(d["po_number_clean"]).strip().upper()
        if po in known:
            pos[d["id"]] = d
    async for m in db.document_memory.find({"source": "hub", "text": {"$ne": ""}}, {"_id": 0, "item_id": 1, "text": 1}):
        d = pos.get(m["item_id"])
        if d:
            o = d.get("_orders") or {str(d["po_number_clean"]).strip().upper()}
            out.append(row(_day(d.get("created_utc")), d["id"], o, m["text"], d.get("vendor_canonical") or "", d.get("file_name", ""),
                           "hub_zetadocs" if d.get("_orders") else "hub"))
    out.sort(key=lambda x: x[0])
    return out


def _links(idx, day: int, toks: Set[str], exclude: Set[str], stem: str, key: str) -> List[Tuple[str, Set[FrozenSet[str]], str, Set[str]]]:
    """(number, the order sets it is on, an evidence file, the evidence documents' vendors)."""
    out = []
    same = hash(frozenset(toks))
    for t in toks - exclude:
        hits = [(o, s, v) for d, o, s, k, h, v in idx.get(t, ()) if day - WINDOW_DAYS <= d < day and k != key and s != stem and h != same]
        distinct = {o for o, _, _ in hits}
        if distinct and len({x for o in distinct for x in o}) <= MAX_ORDERS * 3 and len(distinct) <= MAX_ORDERS:
            out.append((t, distinct, hits[-1][1], {v for _, _, v in hits}))
    return out


def _rate(c) -> Optional[float]:
    return (c[0] + 1) / (c[0] + c[1] + 2) if c and c[0] + c[1] >= MIN_N else None


def _trusted(stats, vendor: str, sh: str, evidence: Set[str] = frozenset()) -> Optional[float]:
    """How far to believe a shared number of this shape: the shape's record
    for this vendor (else overall), and - where there is a record - the
    record of links drawn from the evidence documents' vendors (a
    forwarder's consolidated invoice labelled with one of its orders is poor
    evidence for any one of them)."""
    p = _rate(stats.get((vendor, sh)))
    if p is None:
        p = _rate(stats.get(("", sh)))
    if p is None or p < TRUST:
        return None
    for ev in evidence:
        q = _rate(stats.get(("@" + ev, "")))
        if q is not None and q < TRUST:
            return None
    return p


def _vote(links, stats, vendor: str):
    votes: Dict[str, float] = collections.defaultdict(float)
    ev: Dict[str, Tuple[str, str, str]] = {}
    for t, distinct, frm, evv in links:
        p = _trusted(stats, vendor, shape(t), evv)
        if p is None:
            continue
        for o in distinct:
            for x in o:
                # paperwork naming five orders says less about each than a
                # document of one order does
                votes[x] += p / len(distinct) / len(o)
                ev.setdefault(x, (t, frm, shape(t)))
    if not votes:
        return None
    ranked = sorted(votes.items(), key=lambda kv: -kv[1])
    if len(ranked) > 1 and ranked[1][1] >= ranked[0][1] * 0.999:
        # A consolidated shipment's orders tie: the numbers do not say which.
        # (Answering with the whole group was tried 2026-10-25: 13 of 23.)
        return None
    best = ranked[0][0]
    group = sorted({x for t, distinct, _, evv in links if _trusted(stats, vendor, shape(t), evv) for o in distinct if best in o for x in o})
    return {"order": best, "orders": group, "via": ev[best][0], "from": ev[best][1], "shape": ev[best][2]}


async def learn(db) -> Dict[str, Any]:
    """Walk all order-tied documents forward in time: learn which number
    shapes link to the right order (before the split), test on the rest."""
    t0 = time.time()
    known = await _known_orders(db)
    docs = await _documents(db, known)
    split = (datetime.now(timezone.utc) - timedelta(days=SPLIT_DAYS)).toordinal()
    idx: Dict[str, List[Tuple[int, FrozenSet[str], str, str, int]]] = collections.defaultdict(list)
    stats: Dict[Tuple[str, str], List[int]] = collections.defaultdict(lambda: [0, 0])
    res = collections.Counter()
    by_source = collections.defaultdict(collections.Counter)
    examples = []
    for day, key, orders, toks, vendor, stem, src, prints in docs:
        links = _links(idx, day, toks, set(orders), stem, key)
        if day < split:
            for t, distinct, _, evv in links:
                ok = int(any(orders & o for o in distinct))
                # evidence vendors are judged only on links that would be believed
                ev_keys = [("@" + ev, "") for ev in evv] if _trusted(stats, vendor, shape(t)) else []
                for k in [(vendor, shape(t)), ("", shape(t))] + ev_keys:
                    stats[k][0 if ok else 1] += 1
        elif not prints and src not in ("hub", "zetadocs_sales"):
            # Tested on what it is for: documents whose order was not known
            # otherwise. A Hub document is in memory with an order because the
            # Hub already had it (email subject, file name), so it trains the
            # index but is no test of it. Sales-order paperwork (BOLs, pick
            # tickets) trains it too, but it is applied to AP documents only.
            v = _vote(links, stats, vendor)
            r = "abstain" if not v else ("right" if (set(v["orders"]) <= orders if v.get("group") else v["order"] in orders) else "wrong")
            if v and v.get("group"):
                res["group_" + r] += 1
            res[r] += 1
            by_source[src][r] += 1
            if v and len(examples) < 12 and (r == "wrong" or len(examples) < 6):
                examples.append(f"{r}: {src} {stem[:60]} -> {v['order']} via {v['via']} ({v['shape']}) truth {sorted(orders)}")
        for t in toks - orders:
            idx[t].append((day, orders, stem, key, hash(frozenset(toks)), vendor))
    n = res["right"] + res["wrong"]
    precision = res["right"] / n if n else 0.0
    on = n >= GATE_MIN and precision >= GATE
    trusted = sorted(((k[0] or "*", k[1], v[0], v[1]) for k, v in stats.items() if _trusted(stats, k[0], k[1]) and k[0] in ("",)),
                     key=lambda x: -x[2])[:25]
    out = {"_id": STATE_ID, "at": _now(), "documents": len(docs), "numbers": len(idx), "test_days": SPLIT_DAYS,
           "right": res["right"], "wrong": res["wrong"], "abstain": res["abstain"], "precision": round(precision, 4),
           "group_right": res["group_right"], "group_wrong": res["group_wrong"],
           "coverage": round(n / (n + res["abstain"]), 4) if n + res["abstain"] else 0.0, "on": on,
           "by_source": {k: dict(v) for k, v in by_source.items()}, "trusted_shapes": trusted,
           "distrusted_evidence": sorted(((k[0][1:] or "?", v[0], v[1]) for k, v in stats.items()
                                          if k[0].startswith("@") and (_rate(v) or 1) < TRUST), key=lambda x: -x[2])[:15], "examples": examples,
           "seconds": int(time.time() - t0)}
    await db.learning_state.replace_one({"_id": STATE_ID}, out, upsert=True)
    _IDX.clear()
    _IDX.update({"at": time.time(), "idx": idx, "stats": dict(stats), "on": on, "known": known})
    logger.info("[OrderFlow] %s", {k: v for k, v in out.items() if k not in ("examples", "trusted_shapes")})
    return out


async def link(db, text: str, vendor: str = "", created: str = "", key: str = "", name: str = "") -> Optional[Dict[str, Any]]:
    """The order a document's numbers tie it to, or None."""
    if not _IDX or time.time() - _IDX["at"] > 6 * 3600:
        await learn(db)
    if not _IDX.get("on"):
        return None
    day = _day(created) or datetime.now(timezone.utc).toordinal()
    links = _links(_IDX["idx"], day + 1, _clean(tokens(text), _IDX["known"]), set(), _stem(name), key)
    return _vote(links, _IDX["stats"], vendor)


async def apply_recent(db, days: int = 30) -> Dict[str, Any]:
    """Note the linked order on recent AP documents with no order BC knows."""
    st = await learn(db)
    if not st.get("on"):
        return {"skipped": f"off: precision {st.get('precision')} on {st.get('right', 0) + st.get('wrong', 0)}"}
    from services.sharepoint_service import _is_known_gamer_order
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    stats = collections.Counter()
    async for d in db.hub_documents.find({"created_utc": {"$gte": since}, "mailbox_category": "AP", "is_duplicate": {"$ne": True},
                                          "status": {"$ne": "batch_parent"}},
                                         {"_id": 1, "id": 1, "po_number_clean": 1, "po_from_text": 1, "vendor_canonical": 1,
                                          "created_utc": 1, "file_name": 1, "order_flow": 1}):
        po = str((d.get("po_from_text") or {}).get("value") or d.get("po_number_clean") or "").strip().upper()
        if po and await _is_known_gamer_order(db, po):
            continue
        stats["checked"] += 1
        m = await db.document_memory.find_one({"item_id": d.get("id")}, {"_id": 0, "text": 1})
        if not m or not m.get("text"):
            continue
        v = await link(db, m["text"], d.get("vendor_canonical") or "", str(d.get("created_utc") or ""), d.get("id") or "", d.get("file_name") or "")
        if not v:
            continue
        stats["linked"] += 1
        if (d.get("order_flow") or {}).get("order") != v["order"]:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {"order_flow": {**v, "at": _now()}}})
            stats["noted"] += 1
    return dict(stats)
