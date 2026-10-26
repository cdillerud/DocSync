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
Every order whose earlier paperwork shares a number with the document is a
candidate. Which evidence to believe is learned, not listed: walking forward
in time, each candidate is described by its evidence - the number's shape
(letters/digits runs, a container is "A4N7") and vendor, how many orders and
how many numbers of that kind the evidence names (a forwarder invoice listing
three containers says little about each), whether the two documents disagree
on another number of the same kind (two Tumalo bills on one bill of lading
but different containers are sibling orders), age, sources - and a logistic
model trained on ~1M past candidates weighs them. An answer needs P_MIN and a
MARGIN over the runner-up, and the whole thing turns itself on only if, on
the latest SPLIT_DAYS of documents that do not print their order, it is right
>= GATE of the time. (The hand-tuned shape-trust vote it replaced, 2026-10-26:
115 right of 144; this: 164 of 167 on the same documents.)

Nothing is overwritten: the result is kept on the document as order_flow
{order, orders, via, from, shape, p} for routing and the AI to use as evidence.
"""
from __future__ import annotations

import asyncio
import collections
import logging
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Set, Tuple

logger = logging.getLogger("order_flow")

TOK = re.compile(r"\b[A-Z0-9][A-Z0-9\-/]{4,24}[A-Z0-9]\b")
ORD = re.compile(r"\b((?:WR|W)?\d{6})[A-Z]?\b")
_LEAD = re.compile(r"(?:WR|W)?\d{6}[A-Z]?")
_WORDER = re.compile(r"WR?\d{6}[A-Z]?")   # warehouse POs: a printed W-number is unambiguous
ORDER_RECORDS = {"Purchase Order", "Sales Order", "Posted Purchase Receipt"}
_NAMED = re.compile(r"[A-Z]{1,3}\d{4,6}[A-Z]?")   # any order of ours staff wrote in a file name (WA2328, W118658A)
WINDOW_DAYS = 365          # older evidence is weighed by the model (age is a feature), not cut off at 120 days
MAX_SETS = 12              # a number on paperwork of more order groups identifies none of them
P_MIN = 0.9
MARGIN = 0.05              # siblings of one shipment score alike: no answer without a lead
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

    # Zetadocs keeps a warehouse PO under its bare number ("Purchase Order
    # 115092", Vidrala) where BC calls it WR115092: one order, two spellings,
    # and every link between them was scored wrong (7 of 29 misses, 2026-10-26).
    alias = {o[2:]: o for o in known if o.startswith("WR")}

    def row(day, key, o, text, vendor, name, src):
        if src != "zetadocs_sales":
            o = set(o) | {t for t in _NAMED.findall((name or "").upper()) if t in known}
            o = {alias.get(x, x) for x in o}
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
            out.append((_day(m.get("created")), m["_id"], o, m.get("text", ""), m.get("company_no") or "", m.get("name", ""),
                           "zetadocs_sales" if str(m.get("record_type", "")).startswith("Sales") else "zetadocs"))
    async for m in db.document_memory.find({"source": "sharepoint_ap", "folder": {"$regex": "^Temp Folder/"}, "text": {"$ne": ""}},
                                           {"_id": 0, "item_id": 1, "folder": 1, "name": 1, "created": 1, "text": 1}):
        o = orders_in("/".join(m["folder"].split("/")[2:]) + " " + m.get("name", ""))
        if o and len(o) <= 12:
            out.append((_day(m.get("created")), m["item_id"], o, m["text"], "", m.get("name", ""), "ap_folder"))
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
            out.append((_day(d.get("created_utc")), d["id"], o, m["text"], d.get("vendor_canonical") or "", d.get("file_name", ""),
                           "hub_zetadocs" if d.get("_orders") else "hub"))
    # Reading numbers out of ~100k texts is CPU work: off the event loop, or
    # the API stops answering for minutes (health check failed 2026-10-25).
    out = await asyncio.to_thread(lambda: sorted((row(*r) for r in out), key=lambda x: x[0]))
    return out


def _byshape(toks: Set[str]) -> Dict[str, Set[str]]:
    m: Dict[str, Set[str]] = collections.defaultdict(set)
    for t in toks:
        m[shape(t)].add(t)
    return m


def _candidates(idx, meta, day: int, toks: Set[str], bs: Dict[str, Set[str]], vendor: str, exclude: Set[str],
                stem: str, key: str) -> Dict[str, Tuple[Dict[str, float], str, str]]:
    """Every order the document's numbers are shared with: {order: (what
    its evidence looks like, the number, the evidence document)}."""
    cand: Dict[str, List[Tuple[str, int, int]]] = collections.defaultdict(list)
    for t in toks - exclude:
        hits = [e for e in idx.get(t, ()) if day - WINDOW_DAYS <= meta[e][0] < day and meta[e][3] != key and meta[e][2] != stem]
        sets = {meta[e][1] for e in hits}
        if not sets or len(sets) > MAX_SETS:
            continue
        for e in hits:
            for x in meta[e][1]:
                cand[x].append((t, e, len(sets)))
    if not cand:
        return {}
    score = {x: sum(1.0 / len(meta[e][1]) / ns for _, e, ns in hs) for x, hs in cand.items()}
    tot = sum(score.values())
    ranked = sorted(score, key=lambda x: -score[x])
    out = {}
    for x, hs in cand.items():
        share = score[x] / tot
        other = score[ranked[1]] / tot if x == ranked[0] and len(ranked) > 1 else score[ranked[0]] / tot if x != ranked[0] else 0.0
        f = {"bias": 1.0, "share": share, "top": float(x == ranked[0]), "margin": share - other,
             "nc:" + str(min(len(cand), 6)): 1.0}
        toks_x = {t for t, _, _ in hs}
        f["ntok"] = min(len(toks_x), 6) / 6
        for t in toks_x:
            f["sh:" + shape(t)] = 1.0
            f["vsh:" + vendor + ":" + shape(t)] = 1.0
        f["minsets"] = 1.0 / min(ns for _, _, ns in hs)
        f["spec"] = max(1.0 / len(meta[e][1]) for _, e, _ in hs)
        f["single"] = float(any(len(meta[e][1]) == 1 for _, e, _ in hs))
        # how many numbers of the linking kind the evidence lists (a forwarder invoice naming 3 containers)
        f["csame"] = max(1.0 / max(1, len(meta[e][7].get(shape(t), ()))) for t, e, _ in hs)
        best = max({e for _, e, _ in hs}, key=lambda e: len(toks & meta[e][6]))
        eb = meta[best]
        f["jac"] = len(toks & eb[6]) / max(1, len(toks | eb[6]))
        f["evsrc:" + eb[5]] = 1.0
        f["evv:" + (eb[4] or "?")] = 1.0
        f["samev"] = float(bool(vendor) and vendor == eb[4])
        for s, ts in bs.items():
            es = eb[7].get(s)
            if es:
                agree = bool(ts & es)
                f[("agr:" if agree else "dis:") + s] = 1.0
                if not agree:
                    f["vdis:" + vendor + ":" + s] = 1.0
        gap = day - max(meta[e][0] for _, e, _ in hs)
        f["gap:" + str(min(gap // 30, 6))] = 1.0
        via = next(t for t, e, _ in hs if e == best)
        out[x] = (f, via, eb[2])
    return out


def _fit(R, C, V, y, ncols: int, iters: int = 400, lam: float = 1e-4):
    """Logistic regression, sparse rows (R row, C column, V value), AdaGrad."""
    import numpy as np
    n = len(y)
    w = np.zeros(ncols)
    G = np.zeros(ncols) + 1e-8
    for _ in range(iters):
        p = 1 / (1 + np.exp(-np.bincount(R, weights=V * w[C], minlength=n)))
        g = np.bincount(C, weights=V * (p - y)[R], minlength=ncols) / n + lam * w
        G += g * g
        w -= 0.5 * g / np.sqrt(G)
    return w


def _prob(f: Dict[str, float], cols: Dict[str, int], w) -> float:
    import math
    z = sum(w[cols[k]] * v for k, v in f.items() if k in cols)
    return 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))


def _decide(scored: List[Tuple[float, str]]) -> Optional[Tuple[float, str]]:
    scored = sorted(scored, reverse=True)
    if not scored or scored[0][0] < P_MIN:
        return None
    if len(scored) > 1 and scored[0][0] - scored[1][0] < MARGIN:
        return None
    return scored[0]


async def learn(db) -> Dict[str, Any]:
    """Walk all order-tied documents forward in time, describing every
    candidate order by its evidence; train on the candidates before the
    split, test on the documents after it that do not print their order;
    then train on everything for use."""
    import array
    import numpy as np
    t0 = time.time()
    known = await _known_orders(db)
    docs = await _documents(db, known)
    split = (datetime.now(timezone.utc) - timedelta(days=SPLIT_DAYS)).toordinal()

    def walk():
        idx: Dict[str, List[int]] = collections.defaultdict(list)
        meta: List[Tuple] = []     # (day, orders, stem, key, vendor, src, numbers, numbers by shape)
        interned: Dict[str, str] = {}
        cols: Dict[str, int] = {}
        R, C, V = array.array("i"), array.array("i"), array.array("f")
        rows: List[Tuple[int, str, int, int]] = []    # (document no, order, label, 0 train / 1 test / 2 later)
        for n, (day, key, orders, toks, vendor, stem, src, prints) in enumerate(docs):
            toks = {interned.setdefault(t, t) for t in toks}
            bs = _byshape(toks)
            kind = 0 if day < split else 1 if not prints and src not in ("hub", "zetadocs_sales") else 2
            # Tested on what it is for: documents whose order was not known
            # otherwise. A Hub document is in memory with an order because the
            # Hub already had it (email subject, file name), so it trains the
            # model but is no test of it; sales paperwork likewise.
            for x, (f, _, _) in _candidates(idx, meta, day, toks, bs, vendor, set(orders), stem, key).items():
                r = len(rows)
                for k, v in f.items():
                    R.append(r)
                    C.append(cols.setdefault(k, len(cols)))
                    V.append(v)
                rows.append((n, x, int(x in orders), kind))
            meta.append((day, orders, stem, key, vendor, src, toks, bs))
            for t in toks - orders:
                idx[t].append(n)
        return idx, meta, cols, np.frombuffer(R, dtype=np.int32), np.frombuffer(C, dtype=np.int32), \
            np.frombuffer(V, dtype=np.float32).astype(np.float64), rows

    idx, meta, cols, R, C, V, rows = await asyncio.to_thread(walk)
    kind = np.array([r[3] for r in rows])
    y = np.array([r[2] for r in rows], dtype=np.float64)

    def subset(mask):
        keep = mask[R]
        new = np.cumsum(mask) - 1
        return new[R[keep]], C[keep], V[keep], y[mask]

    w = await asyncio.to_thread(lambda: _fit(*subset(kind == 0), len(cols)))
    # test: the held-out documents, one answer per document
    z = np.bincount(R, weights=V * w[C], minlength=len(rows))
    p = 1 / (1 + np.exp(-z))
    bydoc: Dict[int, List[Tuple[float, str]]] = collections.defaultdict(list)
    for i, (n, x, lab, k) in enumerate(rows):
        if k == 1:
            bydoc[n].append((float(p[i]), x))
    res = collections.Counter()
    by_source: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    examples = []
    tested = 0
    for n, d in enumerate(docs):
        day, key, orders, toks, vendor, stem, src, prints = d
        if day < split or prints or src in ("hub", "zetadocs_sales"):
            continue
        tested += 1
        v = _decide(bydoc.get(n, []))
        r = "abstain" if not v else "right" if v[1] in orders else "wrong"
        res[r] += 1
        by_source[src][r] += 1
        if v and len(examples) < 12 and (r == "wrong" or len(examples) < 6):
            examples.append(f"{r}: {src} {stem[:60]} -> {v[1]} p={v[0]:.2f} truth {sorted(orders)}")
    n_ans = res["right"] + res["wrong"]
    precision = res["right"] / n_ans if n_ans else 0.0
    on = n_ans >= GATE_MIN and precision >= GATE
    inv = {j: k for k, j in cols.items()}
    top = [f"{inv[j]} {w[j]:+.2f}" for j in np.argsort(-np.abs(w))[:20]]
    if on:
        w = await asyncio.to_thread(lambda: _fit(R, C, V, y, len(cols)))
    out = {"_id": STATE_ID, "at": _now(), "documents": len(docs), "numbers": len(idx), "test_days": SPLIT_DAYS,
           "method": "ranker", "candidates_trained": int((kind == 0).sum()), "features": len(cols),
           "right": res["right"], "wrong": res["wrong"], "abstain": res["abstain"], "precision": round(precision, 4),
           "coverage": round(n_ans / tested, 4) if tested else 0.0, "on": on, "p_min": P_MIN, "margin": MARGIN,
           "by_source": {k: dict(v) for k, v in by_source.items()}, "top_weights": top, "examples": examples,
           "seconds": int(time.time() - t0)}
    await db.learning_state.replace_one({"_id": STATE_ID}, out, upsert=True)
    _IDX.clear()
    _IDX.update({"at": time.time(), "idx": idx, "meta": meta, "cols": cols, "w": w, "on": on, "known": known})
    logger.info("[OrderFlow] %s", {k: v for k, v in out.items() if k not in ("examples", "top_weights")})
    return out


async def link(db, text: str, vendor: str = "", created: str = "", key: str = "", name: str = "") -> Optional[Dict[str, Any]]:
    """The order a document's numbers tie it to, or None."""
    if not _IDX or time.time() - _IDX["at"] > 6 * 3600:
        await learn(db)
    if not _IDX.get("on"):
        return None
    day = (_day(created) or datetime.now(timezone.utc).toordinal()) + 1
    toks = _clean(tokens(text), _IDX["known"])
    cand = _candidates(_IDX["idx"], _IDX["meta"], day, toks, _byshape(toks), vendor, set(), _stem(name), key)
    v = _decide([(_prob(f, _IDX["cols"], _IDX["w"]), x) for x, (f, _, _) in cand.items()])
    if not v:
        return None
    _, via, frm = cand[v[1]]
    return {"order": v[1], "orders": [v[1]], "via": via, "from": frm, "shape": shape(via), "p": round(v[0], 3)}


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


async def run_isolated(timeout: int = 2400) -> Dict[str, Any]:
    """apply_recent in its own process. Learning walks ~130k documents in
    pure Python; even in a thread it held the interpreter lock long enough for
    the backend's health checks to time out (2026-10-25 21:20 and 22:06 UTC).
    A separate process leaves the API untouched; results go to the database."""
    import json
    import sys
    proc = await asyncio.create_subprocess_exec(
        sys.executable, "-m", "services.order_flow_service",
        stdout=asyncio.subprocess.PIPE, stderr=asyncio.subprocess.DEVNULL)
    try:
        out, _ = await asyncio.wait_for(proc.communicate(), timeout)
    except asyncio.TimeoutError:
        proc.kill()
        return {"error": f"timed out after {timeout}s"}
    line = (out or b"").decode(errors="replace").strip().splitlines()
    try:
        return json.loads(line[-1]) if line else {"error": f"no output, exit {proc.returncode}"}
    except ValueError:
        return {"error": line[-1][:200]}


if __name__ == "__main__":
    import json
    import os
    from motor.motor_asyncio import AsyncIOMotorClient

    async def _main():
        db = AsyncIOMotorClient(os.environ["MONGO_URL"])[os.environ["DB_NAME"]]
        import deps
        deps.set_db(db)
        r = await apply_recent(db)
        print(json.dumps(r, default=str))

    logging.disable(logging.WARNING)
    asyncio.run(_main())
