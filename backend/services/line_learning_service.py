"""Learned line coding: how AP codes each invoice line, learned from AP's own
entries in Production BC instead of hand-written vendor rules.

1. harvest   - AP's posted purchase invoices (lines) from Production BC,
               read-only, cached in bc_purchase_invoice_lines.
2. examples  - each Hub invoice linked to a BC invoice: its PDF lines are
               matched to AP's lines by amount (which PDF lines add up to
               which AP line) -> labeled (vendor, description, context) ->
               code examples in line_coding_examples. Every invoice AP
               enters becomes training data on the next cycle.
3. evaluate  - every BC invoice is re-coded with its own examples hidden
               (leave-one-out) and compared with what AP entered; per vendor
               scores go to line_learning_scores. A vendor is "promoted"
               (its drafts use the learned coder) only when its score is at
               least MIN_ACC and at least the current method's score on the
               same vendor; demotion is automatic when it falls behind.
4. plan      - a promoted vendor's new invoice: each PDF line gets the code
               of its nearest past lines (text + context), lines of the same
               code added up when that is how AP enters this vendor.
Context (rebilled freight, warehouse PO, no PO) is given to the model as
features; how much each matters is learned from AP's history.
"""
import collections
import logging
import math
import re
import time
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

LEARNED_CODING = True
HARVEST_FROM = "2026-04-01"
MIN_N = 10            # invoices the vendor's score is measured on
MIN_ACC = 0.90        # leave-one-out exact share needed to be promoted
MIN_CONF = 0.5        # every line of a learned draft must be at least this sure
K = 5
PREPAID_ACCOUNTS = {"14500", "14400"}   # BC prepaid-expense / deposit accounts (data for a context feature)
VENDOR_WEIGHT, OTHER_WEIGHT = 1.0, 0.6
MAX_ALIGN_LINES = 14


def _bc_amount(l: Dict[str, Any]) -> float:
    # Posted BC lines report amountExcludingTax 0: quantity x unit cost.
    return round(float(l.get("amountExcludingTax") or 0) or
                 float(l.get("quantity") or 0) * float(l.get("unitCost") or 0), 2)


def _pdf_amount(e: Dict[str, Any]) -> float:
    from services.vendor_line_coding_service import _line_amount
    return round(_line_amount(e), 2)


def _num(x) -> Optional[float]:
    try:
        v = float(str(x).replace(",", "").replace("$", ""))
        return v if v else None
    except (TypeError, ValueError):
        return None


def _shape(w: str) -> str:
    s = re.sub(r"[A-Z]", "A", w)
    s = re.sub(r"\d", "9", s)
    return re.sub(r"(.)\1{2,}", r"\1\1\1", s)


def tokens(desc: str, ctx: List[str], unit_price: Optional[float] = None) -> frozenset:
    """Words, word pairs (so one-letter words count: "S PAL" vs "H PAL"),
    4-letter pieces of longer words, word shapes (AAAA9999999 = a container
    number), the line's unit price and the context features."""
    up = str(desc or "").upper()
    raw = re.findall(r"[A-Z0-9][A-Z0-9&/.\-]*", up)
    out = set(ctx)
    plain = [re.sub(r"\d", "9", w.strip(".-/")) for w in raw if w.strip(".-/")]
    out.update("^" + a + "_" + b for a, b in zip(plain, plain[1:]))
    if unit_price:
        out.add("$%g" % round(float(unit_price), 2))
    for w in raw:
        w = w.strip(".-/")
        if len(w) < 2:
            continue
        if re.search(r"\d", w):
            out.add("#" + _shape(w))
            letters = re.sub(r"[^A-Z]", "", w)
            if len(letters) >= 2:
                out.add(letters)
            continue
        out.add(w)
        if len(w) > 4:
            out.update("~" + w[i:i + 4] for i in range(len(w) - 3))
    return frozenset(out)


async def context(db, d: Dict[str, Any]) -> List[str]:
    from services.sandbox_draft_service import rebill_order
    po = str(d.get("po_number_clean") or "").strip().upper()
    ctx = []
    if not po:
        ctx.append("@NOPO")
    elif re.match(r"^W", po):
        ctx.append("@POW")
    try:
        if await rebill_order(db, d):
            ctx.append("@REBILL")
    except Exception:
        pass
    if po:
        # An earlier AP entry for this PO went to a prepaid account: what that
        # means for this invoice's lines is learned from AP's history.
        if (await _prepaid_by_po(db)).get(po, set()) - {d.get("id")}:
            ctx.append("@PO_PREPAID")
    ctx.extend(_invoice_words(d))
    return ctx


INVOICE_CONTEXT = True
INVOICE_WORDS = 12


def _invoice_words(d: Dict[str, Any]) -> List[str]:
    """What else is on the invoice, as context for each line: a container
    line next to chassis rental and pre-pull fees is drayage, the same words
    next to a plate-trailer run are freight. Which co-occurring words matter
    (and how) is learned from AP's history; IDF weighting keeps common ones
    from dominating."""
    if not INVOICE_CONTEXT:
        return []
    out: List[str] = []
    for e in (d.get("extracted_fields") or {}).get("line_items") or []:
        for w in re.findall(r"[A-Z0-9][A-Z0-9]*", str(e.get("description") or "").upper()):
            t = "@I:" + (("#" + _shape(w)) if re.search(r"\d", w) else w)
            if (len(w) >= 4 or re.search(r"\d", w)) and t not in out:
                out.append(t)
            if len(out) >= INVOICE_WORDS:
                return out
    return out


_PREPAID: Optional[Tuple[float, Dict[str, set]]] = None


async def _prepaid_by_po(db) -> Dict[str, set]:
    """PO -> hub documents whose AP entry went to a prepaid account (one pass, cached 10 min)."""
    global _PREPAID
    if _PREPAID and time.time() - _PREPAID[0] < 600:
        return _PREPAID[1]
    nos = set()
    async for inv in db.bc_purchase_invoice_lines.find({"purchaseInvoiceLines.lineObjectNumber": {"$in": sorted(PREPAID_ACCOUNTS)}},
                                                       {"_id": 0, "number": 1}):
        nos.add(inv.get("number"))
    out: Dict[str, set] = collections.defaultdict(set)
    if nos:
        async for o in db.hub_documents.find({"bc_link.bc_document_no": {"$in": sorted(nos)}},
                                             {"_id": 0, "id": 1, "po_number_clean": 1}):
            p = str(o.get("po_number_clean") or "").strip().upper()
            if p:
                out[p].add(o.get("id"))
    _PREPAID = (time.time(), out)
    return out


# ---------------------------------------------------------------- harvest
async def _pull(c, H, url, params, coll, key="number") -> int:
    n = 0
    while url:
        try:
            r = await c.get(url, headers=H, params=params)
        except Exception as e:
            logger.warning("[LineLearning] %s: %r", coll.name, e)
            break
        if r.status_code != 200:
            logger.warning("[LineLearning] %s: HTTP %s %s", coll.name, r.status_code, r.text[:150])
            break
        j = r.json()
        for x in j.get("value", []):
            x.pop("@odata.etag", None)
            await coll.update_one({key: x[key]}, {"$set": {**x, "cached_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
            n += 1
        url, params = j.get("@odata.nextLink"), None
    return n


async def harvest(db) -> Dict[str, Any]:
    """AP's posted purchase invoices and receipts changed since the last
    harvest (one query each, all vendors), Production BC read-only."""
    import httpx
    import services.bc_catalog_sync_service as bc
    token = await bc.get_bc_token(environment="Production")
    cid = await bc.get_bc_company_id(environment="Production")
    base = f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/Production/api/{bc.BC_API_VERSION}/companies({cid})"
    H = {"Authorization": f"Bearer {token}"}
    state = await db.line_learning_state.find_one({"_id": "harvest"}) or {}
    since = state.get("since") or HARVEST_FROM + "T00:00:00Z"
    started = (datetime.now(timezone.utc) - timedelta(hours=2)).strftime("%Y-%m-%dT%H:%M:%SZ")
    out = {"since": since}
    async with httpx.AsyncClient(timeout=180) as c:
        out["invoices"] = await _pull(c, H, f"{base}/purchaseInvoices", {
            "$filter": f"lastModifiedDateTime ge {since} and status ne 'Draft'",
            "$select": "number,vendorNumber,vendorInvoiceNumber,postingDate,totalAmountExcludingTax,status",
            "$expand": "purchaseInvoiceLines($select=sequence,lineType,lineObjectNumber,description,quantity,unitCost,amountExcludingTax)"},
            db.bc_purchase_invoice_lines)
        out["receipts"] = await _pull(c, H, f"{base}/purchaseReceipts", {
            "$filter": f"postingDate ge {since[:10]}",
            "$select": "number,orderNumber,vendorNumber,postingDate",
            "$expand": "purchaseReceiptLines($select=sequence,lineType,lineObjectNumber,description,quantity,unitCost,unitOfMeasureCode)"},
            db.bc_purchase_receipts)
        out["credit_memos"] = await _pull(c, H, f"{base}/purchaseCreditMemos", {
            "$filter": f"lastModifiedDateTime ge {since} and status ne 'Draft'",
            "$select": "number,vendorNumber,vendorCreditMemoNumber,creditMemoDate,postingDate,totalAmountExcludingTax,status,invoiceNumber"},
            db.bc_purchase_credit_memos)
    await db.line_learning_state.update_one({"_id": "harvest"}, {"$set": {"since": started}}, upsert=True)
    return out


# --------------------------------------------------------------- examples
def align(pdf: List[float], ap: List[float]) -> Optional[List[int]]:
    """Which AP line each PDF line went into, when exactly one way of adding
    the PDF lines up gives AP's lines; else None."""
    if not pdf or not ap or len(pdf) > MAX_ALIGN_LINES:
        return None
    rem = [round(a, 2) for a in ap]
    order = sorted(range(len(pdf)), key=lambda i: -abs(pdf[i]))
    assign: List[Optional[int]] = [None] * len(pdf)
    sols: List[List[int]] = []

    def bt(k: int):
        if len(sols) > 1:
            return
        if k == len(order):
            if all(abs(x) <= 0.02 for x in rem):
                sols.append(list(assign))
            return
        i = order[k]
        for j in range(len(rem)):
            if len(ap) == 1 or abs(pdf[i]) <= abs(rem[j]) + 0.02:
                rem[j] = round(rem[j] - pdf[i], 2)
                assign[i] = j
                bt(k + 1)
                rem[j] = round(rem[j] + pdf[i], 2)

    bt(0)
    return sols[0] if len(sols) == 1 else None


async def build_examples(db) -> Dict[str, Any]:
    stats = collections.Counter()
    seen = set()
    rows = []
    async for d in db.hub_documents.find({"bc_link.bc_document_no": {"$exists": True}},
                                         {"_id": 0, "id": 1, "vendor_canonical": 1, "bc_link": 1, "po_number_clean": 1,
                                          "extracted_fields.line_items": 1, "extracted_fields.po_number": 1,
                                          "extracted_fields.bol_number": 1}):
        no = d["bc_link"]["bc_document_no"]
        if no in seen:
            continue
        inv = await db.bc_purchase_invoice_lines.find_one({"number": no}, {"_id": 0})
        if not inv:
            stats["no_bc"] += 1
            continue
        ap = [l for l in inv.get("purchaseInvoiceLines", []) if l.get("lineObjectNumber") and _bc_amount(l)]
        items = [e for e in (d.get("extracted_fields") or {}).get("line_items") or [] if _pdf_amount(e)]
        sol = align([_pdf_amount(e) for e in items], [_bc_amount(l) for l in ap]) if ap and items else None
        if sol is None:
            stats["no_fit" if ap and items else "empty"] += 1
            continue
        seen.add(no)
        stats["aligned"] += 1
        ctx = await context(db, d)
        for e, j in zip(items, sol):
            l = ap[j]
            rows.append({"vendor": d.get("vendor_canonical") or inv.get("vendorNumber"), "document_id": d.get("id"),
                         "bc_document_no": no, "posting_date": inv.get("postingDate"),
                         "description": str(e.get("description") or "")[:200], "context": ctx, "amount": _pdf_amount(e),
                         "po": str(d.get("po_number_clean") or "").strip().upper(),
                         "unit_price": _num(e.get("unit_price")), "quantity": _num(e.get("quantity")),
                         "code": str(l["lineObjectNumber"]).upper(), "line_type": l.get("lineType"), "ap_group": j,
                         "ap_qty": float(l.get("quantity") or 0),
                         "ap_lines": len(ap), "pdf_lines": len(items)})
    await db.line_coding_examples.delete_many({})
    if rows:
        await db.line_coding_examples.insert_many(rows)
    return {**stats, "examples": len(rows)}


# ------------------------------------------------------------------ model
FEATURES = ("s1_bias", "s1_vendor_receipt_rate", "s1_best_text", "s1_best_code_in_desc", "s1_best_amount", "s1_best_price",
            "s1_history_on_receipt", "s1_history_other", "s1_has_receipt",
            "s2_text", "s2_code_in_desc", "s2_amount", "s2_price", "s2_history")


def _close(a: Optional[float], b: Optional[float], scale: float) -> float:
    if not a or not b or (a > 0) != (b > 0):
        return 0.0
    return math.exp(-abs(math.log(abs(a) / abs(b))) * scale)


def _nearest(scored: List[Tuple[float, str]]) -> List[Tuple[float, str]]:
    """The K most similar past lines plus every one tied with the K-th.
    Sorting (score, code) pairs and keeping K let the code name break ties:
    with 192 identical past lines, 5 FREIGHT (reverse-alphabetically first)
    outvoted 187 CUSTOMS (StraitLink "Entry Fee / Brokerage", 2026-10-24)."""
    scored = sorted(scored, key=lambda x: -x[0])
    cut = scored[min(K, len(scored)) - 1][0]
    return [x for x in scored if x[0] >= cut]


class Coder:
    def __init__(self, examples: List[Dict[str, Any]], receipts: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        self.receipts = receipts or {}
        self.ex = examples
        for e in self.ex:
            e["_t"] = tokens(e["description"], e.get("context") or [], e.get("unit_price"))
        df = collections.Counter(t for e in self.ex for t in e["_t"])
        n = max(len(self.ex), 1)
        self.idf = {t: math.log((n + 1) / (c + 0.5)) for t, c in df.items()}
        self.by_vendor: Dict[str, List[int]] = collections.defaultdict(list)
        self.index: Dict[Tuple[str, str], List[int]] = collections.defaultdict(list)
        for i, e in enumerate(self.ex):
            self.by_vendor[e["vendor"]].append(i)
            for t in e["_t"]:
                self.index[(e["vendor"], t)].append(i)
        self.vendors = list(self.by_vendor)
        self.gindex: Dict[str, List[int]] = collections.defaultdict(list)
        for i, e in enumerate(self.ex):
            for tk in e["_t"]:
                self.gindex[tk].append(i)
        # Does AP add same-code PDF lines into one line for this vendor?
        self.separate: Dict[str, bool] = {}
        for v, idx in self.by_vendor.items():
            docs = collections.defaultdict(list)
            for i in idx:
                docs[self.ex[i]["bc_document_no"]].append(self.ex[i])
            agg = sep = 0
            for ls in docs.values():
                groups = collections.defaultdict(set)
                count = collections.Counter()
                for e in ls:
                    groups[e["code"]].add(e["ap_group"])
                    count[e["code"]] += 1
                for c, g in groups.items():
                    if count[c] > 1:
                        sep += len(g) > 1
                        agg += len(g) == 1
            self.separate[v] = sep > agg
        # Does AP enter this vendor's code as 1 x the amount (a charge: FREIGHT,
        # STORAGE) or at a real quantity (a stocked item)? Learned per code.
        q1, qn = collections.Counter(), collections.Counter()
        for e in self.ex:
            if e.get("ap_qty"):
                qn[(e["vendor"], e["code"])] += 1
                q1[(e["vendor"], e["code"])] += abs(float(e["ap_qty"]) - 1.0) < 1e-9
        self.qty_one = {k: q1[k] / n for k, n in qn.items() if n}
        self.line_type: Dict[Tuple[str, str], str] = {}
        lt = collections.defaultdict(collections.Counter)
        for e in self.ex:
            lt[(e["vendor"], e["code"])][e.get("line_type") or "Item"] += 1
        for k, c in lt.items():
            self.line_type[k] = c.most_common(1)[0][0]

        # How often AP's code for this vendor is an item on the PO's receipt
        # (Owens ~1.0: product; StraitLink ~0: its W-PO receipt is someone
        # else's goods). Learned per vendor, used as an input below.
        hit, tot = collections.Counter(), collections.Counter()
        for e in self.ex:
            rc = {str(l.get("lineObjectNumber") or "").upper() for l in self.receipts.get(e.get("po") or "", [])}
            if rc:
                tot[e["vendor"]] += 1
                hit[e["vendor"]] += e["code"] in rc
        self.receipt_rate = {v: hit[v] / tot[v] for v in tot}
        self.weights = self._train()

    # ---- candidates and features (a product line's item comes from its PO)
    def candidates(self, po: str) -> List[Dict[str, Any]]:
        if not po:
            return []           # no PO: receipts without an order number are not this invoice's
        seen, out = set(), []
        for l in self.receipts.get(po or "", []):
            code = str(l.get("lineObjectNumber") or "").upper()
            q, uc = float(l.get("quantity") or 0), float(l.get("unitCost") or 0)
            if not code or not q:
                continue
            k = (code, round(uc, 4))
            if k in seen:
                continue
            seen.add(k)
            out.append({"code": code, "desc": str(l.get("description") or ""), "unit_cost": uc, "qty": q,
                        "amount": round(q * uc, 2), "lt": l.get("lineType")})
        return out

    def votes(self, desc: str, ctx: List[str], vendor: str, exclude_doc: Optional[str], unit_price: Optional[float] = None) -> Tuple[Dict[str, float], float]:
        q = tokens(desc, ctx, unit_price)
        cand = set()
        for tk in q:
            cand.update(self.index.get((vendor, tk), ()))
        scored = []
        for i in cand:
            e = self.ex[i]
            if e["bc_document_no"] == exclude_doc:
                continue
            s = self._sim(q, e["_t"])
            if s > 0.15:
                scored.append((s, e["code"]))
        if not scored:
            return {}, 0.0
        top = _nearest(scored)
        v = collections.Counter()
        for s, c in top:
            v[c] += s
        tot = sum(v.values())
        return {c: x / tot for c, x in v.items()}, top[0][0]

    def features(self, line: Dict[str, Any], cand: Dict[str, Any], hist: Dict[str, float], best: float, vrate: float = 0.5) -> List[float]:
        desc = str(line.get("description") or "")
        alnum = re.sub(r"[^A-Z0-9]", "", desc.upper())
        code = re.sub(r"[^A-Z0-9]", "", cand["code"])
        on_rec = 1.0 if cand.get("unit_cost") is not None else 0.0
        price = 0.0
        up = line.get("unit_price")
        if on_rec and up and cand["unit_cost"]:
            price = max(_close(up, cand["unit_cost"] * f, 20) for f in (1, 1000, 0.001))
        return [self._sim(tokens(desc, []), tokens(cand.get("desc", "") + " " + cand["code"], [])),
                1.0 if len(code) >= 4 and code in alnum else 0.0,
                _close(line.get("amount"), cand.get("amount"), 10) if on_rec else 0.0,
                price,
                hist.get(cand["code"], 0.0) * best,
                on_rec * vrate, on_rec * (1.0 - vrate), 1.0 - on_rec]

    def options(self, line: Dict[str, Any], ctx: List[str], vendor: str, po: str, exclude_doc: Optional[str]):
        hist, best = self.votes(line.get("description"), ctx, vendor, exclude_doc, line.get("unit_price"))
        cands = self.candidates(po)
        have = {c["code"] for c in cands}
        cands = cands + [{"code": c, "unit_cost": None} for c in hist if c not in have]
        vrate = self.receipt_rate.get(vendor, 0.5)
        return [(c, self.features(line, c, hist, best, vrate)) for c in cands]

    def as_charge(self, vendor: str, code: str) -> bool:
        return self.qty_one.get((vendor, code), 0.0) >= 0.8

    # ---- two stages: (1) is this line one of the PO's received items, or a
    # charge? (2) which item / which charge code. Each stage is learned from
    # AP's past invoices; the number of unrelated receipt lines on a W-PO no
    # longer dilutes the answer.
    def _stage1(self, opts, vrate: float) -> List[float]:
        rec = [f for c, f in opts if c.get("unit_cost") is not None]
        his = [(c, f) for c, f in opts if c.get("unit_cost") is None]
        m = [max((f[i] for f in rec), default=0.0) for i in range(4)]
        hist_other = max((f[4] for _, f in his), default=0.0)
        hist_rec = max((f[4] for f in rec), default=0.0)
        return [1.0, vrate, m[0], m[1], m[2], m[3], hist_rec, hist_other, 1.0 if rec else 0.0]

    def _train(self, epochs: int = 300, lr: float = 0.5):
        import numpy as np
        s1, s2 = [], []
        for e in self.ex:
            if not self.receipts.get(e.get("po") or ""):
                continue
            line = {"description": e["description"], "amount": e["amount"], "unit_price": e.get("unit_price")}
            opts = self.options(line, e.get("context") or [], e["vendor"], e["po"], e["bc_document_no"])
            if not opts:
                continue
            rec = [(c, f) for c, f in opts if c.get("unit_cost") is not None]
            is_rec = any(c["code"] == e["code"] for c, _ in rec)
            s1.append((self._stage1(opts, self.receipt_rate.get(e["vendor"], 0.5)), 1.0 if is_rec else 0.0))
            if is_rec and len(rec) > 1:
                y = next(i for i, (c, _) in enumerate(rec) if c["code"] == e["code"])
                s2.append((np.array([f[:5] for _, f in rec]), y))
        w1 = np.zeros(9)
        if s1:
            X = np.array([x for x, _ in s1]); Y = np.array([y for _, y in s1])
            for _ in range(epochs * 2):
                p = 1 / (1 + np.exp(-(X @ w1)))
                w1 += lr * (X.T @ (Y - p)) / len(Y)
        w2 = np.zeros(5)
        for _ in range(epochs):
            g = np.zeros_like(w2)
            for X2, y in s2:
                s = X2 @ w2
                p = np.exp(s - s.max()); p /= p.sum()
                g += X2[y] - p @ X2
            if s2:
                w2 += lr * g / len(s2)
        self.w1, self.w2 = w1, w2
        self.train_rows = len(s1)
        return np.concatenate([w1, w2])

    def pick(self, line: Dict[str, Any], ctx: List[str], vendor: str, po: str, exclude_doc: Optional[str]) -> Tuple[Optional[str], float]:
        import numpy as np
        opts = self.options(line, ctx, vendor, po, exclude_doc)
        if not opts:
            return None, 0.0
        rec = [(c, f) for c, f in opts if c.get("unit_cost") is not None]
        his = [(c, f) for c, f in opts if c.get("unit_cost") is None]
        p_rec = 0.0
        if rec:
            z = float(np.array(self._stage1(opts, self.receipt_rate.get(vendor, 0.5))) @ self.w1)
            p_rec = 1 / (1 + math.exp(-max(-30.0, min(30.0, z))))
        best_rec, q_rec = None, 0.0
        if rec:
            s = np.array([f[:5] for _, f in rec]) @ self.w2
            q = np.exp(s - s.max()); q /= q.sum()
            i = int(q.argmax())
            best_rec, q_rec = rec[i][0], float(q[i])
        best_his, q_his = None, 0.0
        if his:
            # history vote share among the codes that are not on the receipt
            tot = sum(f[4] for _, f in his) or 1.0
            c, f = max(his, key=lambda x: x[1][4])
            best_his, q_his = c, f[4] / tot
        if best_rec is not None and (best_his is None or p_rec * q_rec >= (1 - p_rec) * q_his):
            self.last_pick = best_rec
            return best_rec["code"], p_rec * q_rec
        if best_his is not None:
            self.last_pick = best_his
            return best_his["code"], (1 - p_rec) * q_his if rec else q_his
        return None, 0.0

    def _w(self, t: str) -> float:
        return self.idf.get(t, 3.0)

    def _sim(self, a: frozenset, b: frozenset) -> float:
        inter = sum(self._w(t) for t in a & b)
        if not inter:
            return 0.0
        return inter / sum(self._w(t) for t in a | b)

    def code(self, desc: str, ctx: List[str], vendor: str, exclude_doc: Optional[str] = None) -> Tuple[Optional[str], float]:
        q = tokens(desc, ctx)
        cand = set()
        for t in q:
            cand.update(self.index.get((vendor, t), ()))
        scored = []
        for i in cand:
            e = self.ex[i]
            if e["bc_document_no"] == exclude_doc:
                continue
            s = self._sim(q, e["_t"]) * VENDOR_WEIGHT
            if s > 0.15:
                scored.append((s, e["code"]))
        if not scored:
            return None, 0.0
        top = _nearest(scored)
        votes = collections.Counter()
        for s, c in top:
            votes[c] += s
        c, v = votes.most_common(1)[0]
        return c, min(1.0, v / sum(votes.values()) * top[0][0] * 1.5)

    def lines(self, d: Dict[str, Any], ctx: List[str], exclude_doc: Optional[str] = None) -> Tuple[Optional[List[Dict[str, Any]]], str]:
        v = d.get("vendor_canonical")
        items = [e for e in (d.get("extracted_fields") or {}).get("line_items") or [] if _pdf_amount(e)]
        if not items:
            return None, "no invoice lines were read"
        total = round(abs(float(d.get("amount_float") or 0)), 2)
        if abs(sum(_pdf_amount(e) for e in items) - total) > 0.02:
            return None, "the invoice's lines do not add up to its total"
        out = []
        po = str(d.get("po_number_clean") or "").strip().upper()
        for e in items:
            line = {"description": e.get("description"), "amount": _pdf_amount(e), "unit_price": _num(e.get("unit_price"))}
            c, p = self.pick(line, ctx, v, po, exclude_doc)
            if not c or p < MIN_CONF:
                return None, f"not sure how AP codes '{str(e.get('description'))[:60]}'"
            lp = getattr(self, "last_pick", None) or {}
            uc = None if self.as_charge(v, c) else lp.get("unit_cost")
            if uc:
                # The quantity BC gets must be one the documents show: the
                # invoice's (in pieces or thousands) or the receipt line's.
                qty = _pdf_amount(e) / uc
                seen_q = [x for x in (_num(e.get("quantity")), lp.get("qty")) if x]
                seen_q += [x / 1000 for x in seen_q] + [x * 1000 for x in seen_q]
                if not any(abs(qty - x) <= max(0.01 * abs(x), 0.001) for x in seen_q):
                    return None, f"the quantity for '{str(e.get('description'))[:50]}' does not match the invoice or the receipt"
            out.append((c, _pdf_amount(e), str(e.get("description") or ""), p, uc))
        if not self.separate.get(v):
            agg: Dict[Tuple[str, Any], List[Any]] = {}
            for c, a, desc, p, uc in out:
                k = (c, uc)
                if k in agg:
                    agg[k][1] = round(agg[k][1] + a, 2)
                    agg[k][3] = min(agg[k][3], p)
                else:
                    agg[k] = [c, a, desc, p, uc]
            out = [tuple(x) for x in agg.values()]
        lines = []
        for c, a, desc, p, uc in out:
            lt = self.line_type.get((v, c), "Item")
            qty, cost = 1.0, round(a, 2)
            if uc:
                # An item from the PO's receipt: BC needs its real quantity at
                # the receipt's unit cost, not 1 x the line total.
                qty = round(a / uc, 5)
                if abs(qty * uc - a) > 0.02:
                    return None, f"the amount of '{desc[:50]}' is not a whole quantity at the receipt's unit cost"
                cost = uc
            lines.append({"lineType": "Account" if lt == "Account" else "Item", "lineObjectNumber": c,
                          "description": desc[:100], "quantity": qty, "unitCost": cost,
                          "source": f"learned from AP's coding of this vendor's past invoices ({int(p * 100)}% sure)"})
        return lines, ""


AI_CODING = True
AI_MIN_CONF = 0.5        # its stated confidence barely separates right from wrong: gate per vendor
AI_PER_VENDOR = 15       # replayed invoices per vendor
AI_VENDORS = 20          # vendors replayed per run (most invoices the learner abstains on)
AI_MIN_N = 7
AI_MIN_ACC = 0.95
AI_EVAL_DAYS = 7


AI_INVOICES = 6
AI_CROSS_VENDOR = 4


def _past_invoices(C: "Coder", idx: List[int]) -> Dict[str, List[Dict[str, Any]]]:
    inv: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
    for i in idx:
        inv[C.ex[i]["bc_document_no"]].append(C.ex[i])
    return inv


def _show_invoice(lines: List[Dict[str, Any]], vendor_label: str = "") -> str:
    """One past invoice: its lines and how AP grouped them into BC lines."""
    rows = [f"  {n}. \"{e['description'][:80]}\" {e['amount']}" + (f" @ {e.get('unit_price')}" if e.get("unit_price") else "")
            for n, e in enumerate(lines, 1)]
    when = str(lines[0].get("posting_date") or "")[:10]
    groups: Dict[int, List[int]] = collections.defaultdict(list)
    for n, e in enumerate(lines, 1):
        groups[e["ap_group"]].append(n)
    ap = []
    for g, ns in groups.items():
        e = lines[ns[0] - 1]
        tot = round(sum(lines[n - 1]["amount"] for n in ns), 2)
        ap.append(f"{e['code']} = line{'s' if len(ns) > 1 else ''} {'+'.join(map(str, ns))} ({tot})")
    ctx = lines[0].get("context") or []
    head = ("Past invoice" + (f" from {vendor_label}" if vendor_label else "") + (f", entered {when}" if when else "")
            + (" [freight rebilled to a customer]" if "@REBILL" in ctx else "")
            + (" [an earlier invoice on its PO went to a prepaid account]" if "@PO_PREPAID" in ctx else ""))
    return head + ":\n" + "\n".join(rows) + "\n  AP entered: " + "; ".join(ap)


async def ai_lines(db, C: "Coder", d: Dict[str, Any], ctx: List[str], exclude_doc: Optional[str] = None,
                   provider=None, raw_out: Optional[Dict[str, Any]] = None) -> Tuple[Optional[List[Dict[str, Any]]], str]:
    """The AI model codes an invoice the similarity learner is unsure of.
    It is shown whole past invoices of this vendor (nearest first) with how
    AP coded and grouped their lines into BC lines - plus similar invoices of
    other vendors when this one has little history - and must answer with
    codes AP uses for this vendor (or the PO's received items), grouping the
    lines the way AP would."""
    import json as _json
    v = d.get("vendor_canonical")
    items = [e for e in (d.get("extracted_fields") or {}).get("line_items") or [] if _pdf_amount(e)]
    total = round(abs(float(d.get("amount_float") or 0)), 2)
    if not items or abs(sum(_pdf_amount(e) for e in items) - total) > 0.02:
        return None, "the invoice's lines do not add up to its total"
    qs = [tokens(e.get("description"), ctx, _num(e.get("unit_price"))) for e in items]
    def rank(invs):
        # most similar first, newest first among equally similar; identical invoices once
        def key(kv):
            sim = round(max(C._sim(q, x["_t"]) for q in qs for x in kv[1]), 2)
            return (-sim, -int(re.sub(r"\D", "", str(kv[1][0].get("posting_date") or "")) or 0))
        out, sigs = [], set()
        for no, ls in sorted(invs.items(), key=key):
            sig = tuple((e["description"][:40], e["amount"], e["code"], e["ap_group"]) for e in ls)
            if sig not in sigs:
                sigs.add(sig)
                out.append((no, ls))
        return out
    own = _past_invoices(C, [i for i in C.by_vendor.get(v, []) if C.ex[i]["bc_document_no"] != exclude_doc])
    shown = [_show_invoice(ls) for _, ls in rank(own)[:AI_INVOICES]]
    allowed = {e["code"] for ls in own.values() for e in ls}
    coding = await db.vendor_line_coding.find_one({"vendor": str(v or "").upper()}, {"_id": 0, "codes_used": 1}) or {}
    allowed |= set(coding.get("codes_used") or [])
    if len(own) < 3:
        # Little history: similar invoices of other vendors, labelled as such.
        cand = set()
        for q in qs:
            for tk in q:
                cand.update(i for i in C.gindex.get(tk, [])[:300] if C.ex[i]["vendor"] != v)
        other = _past_invoices(C, [i for i in cand if C.ex[i]["bc_document_no"] != exclude_doc])
        for no, ls in rank(other)[:AI_CROSS_VENDOR]:
            shown.append(_show_invoice(ls, vendor_label=f"another vendor ({ls[0]['vendor']})"))
        if not allowed:
            allowed |= {e["code"] for _, ls in rank(other)[:AI_CROSS_VENDOR] for e in ls}
    if not shown or not allowed:
        return None, "too little history for this vendor"
    po = str(d.get("po_number_clean") or "").strip().upper()
    rec = C.candidates(po)
    allowed |= {r["code"] for r in rec}
    allowed = sorted(allowed)
    receipt = "\n".join(f"- {r['code']}: \"{r['desc'][:60]}\" unit cost {r['unit_cost']} qty {r.get('qty')}" for r in rec[:15]) or "(none)"
    lines = "\n".join(f"{n}. \"{str(e.get('description') or '')[:120]}\" {_pdf_amount(e)}" + (f" @ {e.get('unit_price')}" if e.get("unit_price") else "")
                      for n, e in enumerate(items, 1))
    system = ("You enter vendor invoices into Business Central exactly the way this company's AP team does. "
              "Learn the pattern only from the past invoices shown: which code AP gives each kind of line, and which lines AP adds "
              "together into one BC line. AP's practice can change over time: where past invoices disagree, follow the most "
              "recently entered ones. Use only the allowed codes. Reply with JSON only.")
    user = (f"Vendor: {v}\nThis invoice's context: {', '.join(c for c in ctx if not c.startswith('@I:')) or 'none'} (@REBILL = freight rebilled to a customer, @POW = warehouse PO, @NOPO = no PO, @PO_PREPAID = an earlier invoice on this PO went to a prepaid account)\n\n"
            + "\n\n".join(shown) + f"\n\nThe PO's received items:\n{receipt}\n\nAllowed codes: {', '.join(allowed)}\n\n"
            f"New invoice (total {total}):\n{lines}\n\n"
            'For each line give the code and a group number; lines AP would add together into one BC line share a group. '
            'Reply as {"lines": [{"n": 1, "code": "...", "group": 1, "confidence": 0.0-1.0}, ...]}')
    try:
        if provider is None:
            from services.llm_router import get_provider
            provider = get_provider("classification")
        import asyncio as _aio
        raw = await _aio.wait_for(provider.complete(system, user, f"line-coding-{d.get('id')}", expect_json=True), 60)
        j = _json.loads(raw[raw.find("{"):raw.rfind("}") + 1])
    except Exception as e:
        return None, f"AI coding failed: {e!r}"[:300]
    got = {int(x.get("n")): x for x in j.get("lines") or [] if str(x.get("n", "")).isdigit()}
    conf_min = 1.0
    groups: Dict[Any, List[Any]] = {}
    for n, e in enumerate(items, 1):
        x = got.get(n) or {}
        c = str(x.get("code") or "").upper()
        conf = float(x.get("confidence") or 0)
        conf_min = min(conf_min, conf)
        if c not in allowed:
            return None, f"the AI gave a code AP does not use for this vendor ('{str(e.get('description'))[:40]}')"
        g = (x.get("group"), c)
        groups.setdefault(g, []).append(e)
    if raw_out is not None:
        raw_out["confidence"] = conf_min
    if conf_min < AI_MIN_CONF:
        return None, f"the AI was not sure ({conf_min:.2f})"
    res = []
    for (g, c), es in groups.items():
        a = round(sum(_pdf_amount(e) for e in es), 2)
        r = None if C.as_charge(v, c) else next((r for r in rec if r["code"] == c), None)
        qty, cost = 1.0, a
        if r and r.get("unit_cost"):
            qty = round(a / r["unit_cost"], 5)
            seen_q = [x for x in ([_num(e.get("quantity")) for e in es] + [r.get("qty")]) if x]
            if len(es) > 1:
                seen_q.append(sum(_num(e.get("quantity")) or 0 for e in es))
            seen_q += [x / 1000 for x in seen_q] + [x * 1000 for x in seen_q]
            if not any(abs(qty - x) <= max(0.01 * abs(x), 0.001) for x in seen_q):
                return None, f"the quantity for '{str(es[0].get('description'))[:50]}' does not match the invoice or the receipt"
            cost = r["unit_cost"]
        lt = C.line_type.get((v, c), "Item")
        res.append({"lineType": "Account" if lt == "Account" else "Item", "lineObjectNumber": c,
                    "description": str(es[0].get("description") or "")[:100], "quantity": qty, "unitCost": cost,
                    "source": f"AI, from AP's coding of this vendor's past invoices ({int(conf_min * 100)}% sure)"})
    return res, ""


_CODER: Optional[Coder] = None


async def coder(db, refresh: bool = False) -> Coder:
    global _CODER
    if _CODER is None or refresh:
        receipts: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
        async for r in db.bc_purchase_receipts.find({}, {"_id": 0, "orderNumber": 1, "purchaseReceiptLines": 1}):
            receipts[str(r.get("orderNumber") or "").upper()].extend(r.get("purchaseReceiptLines") or [])
        _CODER = Coder([e async for e in db.line_coding_examples.find({}, {"_id": 0})], receipts)
    return _CODER


def _same(pred: List[Tuple[str, float]], ap: List[Tuple[str, float]]) -> bool:
    if len(pred) != len(ap):
        return False
    a, b = sorted(pred), sorted(ap)
    return all(x[0] == y[0] and abs(x[1] - y[1]) <= 0.02 for x, y in zip(a, b))


# --------------------------------------------------------------- evaluate
OOT_MONTHS = 3           # out-of-time test window (calendar months, current included)
MIN_ACC_LOW_VOLUME = 0.95  # leave-one-out bar for vendors with too few recent invoices to test on time


async def _out_of_time(db, months: int = OOT_MONTHS) -> Dict[str, collections.Counter]:
    """Per vendor: each of the last `months` months coded by a model trained
    only on AP's entries posted before that month, with the receipts that
    existed when the invoice was posted - how the coder does on invoices it
    has not seen, the way it meets them live. Leave-one-out reads ~3 points
    better than this (2026-10-24: 98% vs 95%)."""
    ex = [e async for e in db.line_coding_examples.find({}, {"_id": 0})]
    receipts: Dict[str, List[Dict[str, Any]]] = collections.defaultdict(list)
    async for r in db.bc_purchase_receipts.find({}, {"_id": 0, "orderNumber": 1, "postingDate": 1, "purchaseReceiptLines": 1}):
        for l in r.get("purchaseReceiptLines") or []:
            receipts[str(r.get("orderNumber") or "").upper()].append(dict(l, _posted=str(r.get("postingDate") or "")))
    now = datetime.now(timezone.utc)
    starts = []
    y, m = now.year, now.month
    for _ in range(months):
        starts.append(f"{y:04d}-{m:02d}")
        y, m = (y, m - 1) if m > 1 else (y - 1, 12)
    by_month: Dict[str, List[Any]] = collections.defaultdict(list)
    seen = set()
    async for d in db.hub_documents.find({"bc_link.bc_document_no": {"$exists": True}},
                                         {"_id": 0, "vendor_canonical": 1, "bc_link": 1, "po_number_clean": 1, "amount_float": 1, "id": 1,
                                          "extracted_fields.line_items": 1, "extracted_fields.po_number": 1, "extracted_fields.bol_number": 1}):
        no = d["bc_link"]["bc_document_no"]
        if no in seen or not d.get("vendor_canonical"):
            continue
        seen.add(no)
        inv = await db.bc_purchase_invoice_lines.find_one({"number": no}, {"_id": 0, "postingDate": 1, "purchaseInvoiceLines": 1})
        if inv and str(inv.get("postingDate") or "")[:7] in starts:
            by_month[str(inv["postingDate"])[:7]].append((d, inv))
    out: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    for mo in starts:
        start = mo + "-01"
        past = [dict(e) for e in ex if str(e.get("posting_date") or "") < start]
        if not past:
            continue
        C = Coder(past, {po: [l for l in ls if l["_posted"] < start] for po, ls in receipts.items()})
        for d, inv in by_month[mo]:
            ap = [(str(l["lineObjectNumber"]).upper(), _bc_amount(l)) for l in inv.get("purchaseInvoiceLines", [])
                  if l.get("lineObjectNumber") and _bc_amount(l)]
            if not ap:
                continue
            po = str(d.get("po_number_clean") or "").strip().upper()
            C.receipts = {po: [l for l in receipts.get(po, []) if l["_posted"] <= str(inv.get("postingDate") or "")]} if po else {}
            lines, _ = C.lines(d, await context(db, d), exclude_doc=d["bc_link"]["bc_document_no"])
            if lines is None:
                continue
            o = out[d["vendor_canonical"]]
            o["attempted"] += 1
            o["exact"] += _same([(l["lineObjectNumber"], round(l["quantity"] * l["unitCost"], 2)) for l in lines], ap)
    return out


async def evaluate(db, scores: str = "line_learning_scores") -> Dict[str, Any]:
    oot = await _out_of_time(db)
    C = await coder(db, refresh=True)
    t: Dict[str, collections.Counter] = collections.defaultdict(collections.Counter)
    seen = set()
    async for d in db.hub_documents.find({"bc_link.bc_document_no": {"$exists": True}},
                                         {"_id": 0, "vendor_canonical": 1, "bc_link": 1, "po_number_clean": 1, "amount_float": 1,
                                          "extracted_fields.line_items": 1, "extracted_fields.po_number": 1,
                                          "extracted_fields.bol_number": 1, "ap_draft_vs_bc": 1}):
        no = d["bc_link"]["bc_document_no"]
        if no in seen:
            continue
        seen.add(no)
        v = d.get("vendor_canonical")
        if not v or v not in C.by_vendor:
            continue
        inv = await db.bc_purchase_invoice_lines.find_one({"number": no}, {"_id": 0, "purchaseInvoiceLines": 1})
        if not inv:
            continue
        ap = [(str(l["lineObjectNumber"]).upper(), _bc_amount(l)) for l in inv.get("purchaseInvoiceLines", [])
              if l.get("lineObjectNumber") and _bc_amount(l)]
        if not ap:
            continue
        tv = t[v]
        tv["n"] += 1
        g = d.get("ap_draft_vs_bc") or {}
        if "exact" in g:
            tv["cur_graded"] += 1
            tv["cur_exact"] += bool(g.get("exact"))
        lines, _ = C.lines(d, await context(db, d), exclude_doc=no)
        if lines is None:
            tv["abstain"] += 1
            continue
        ok = _same([(l["lineObjectNumber"], round(l["quantity"] * l["unitCost"], 2)) for l in lines], ap)
        tv["attempted"] += 1
        tv["exact"] += ok
        if "exact" in g:
            tv["learned_on_cur"] += ok
            tv["attempted_on_cur"] += 1
    now = datetime.now(timezone.utc).isoformat()
    promoted = []
    for v, tv in t.items():
        acc = tv["exact"] / tv["attempted"] if tv["attempted"] else 0.0
        cur = tv["cur_exact"] / tv["cur_graded"] if tv["cur_graded"] >= 5 else None
        lcur = tv["learned_on_cur"] / tv["attempted_on_cur"] if tv["attempted_on_cur"] >= 5 else None
        o = oot.get(v) or collections.Counter()
        oacc = o["exact"] / o["attempted"] if o["attempted"] else None
        beats_current = cur is None or lcur is None or lcur >= cur
        if o["attempted"] >= MIN_N:
            # Enough recent invoices: judged on time, as it will meet them live.
            ok = oacc >= MIN_ACC and acc >= MIN_ACC and beats_current
        else:
            ok = tv["attempted"] >= MIN_N and acc >= MIN_ACC_LOW_VOLUME and beats_current
        if ok:
            promoted.append(v)
        await db[scores].update_one({"vendor": v}, {"$set": {
            "vendor": v, "invoices": tv["n"], "attempted": tv["attempted"], "exact": tv["exact"],
            "accuracy": round(acc, 3), "coverage": round(tv["attempted"] / tv["n"], 3) if tv["n"] else 0,
            "oot_attempted": o["attempted"], "oot_exact": o["exact"],
            "oot_accuracy": round(oacc, 3) if oacc is not None else None,
            "current_method_accuracy": round(cur, 3) if cur is not None else None,
            "learned_on_same_invoices": round(lcur, 3) if lcur is not None else None,
            "promoted": ok, "updated_at": now}}, upsert=True)
    tot = sum((tv for tv in t.values()), collections.Counter())
    po = sum((oot[v] for v in promoted if v in oot), collections.Counter())
    oot_promoted = {"attempted": po["attempted"], "exact": po["exact"],
                    "accuracy": round(po["exact"] / po["attempted"], 4) if po["attempted"] else None}
    if scores == "line_learning_scores":
        await db.line_learning_state.update_one({"_id": "model"}, {"$set": {
            "weights": dict(zip(FEATURES, [round(float(x), 3) for x in C.weights])), "trained_on": getattr(C, "train_rows", 0),
            "examples": len(C.ex), "attempted": tot["attempted"], "exact": tot["exact"], "abstain": tot["abstain"],
            "promoted": len(promoted), "oot_promoted": oot_promoted, "evaluated_at": now}}, upsert=True)
    return {"weights": dict(zip(FEATURES, [round(float(x), 2) for x in C.weights])), "trained_on": getattr(C, "train_rows", 0),
            "vendors": len(t), "promoted": len(promoted), "attempted": tot["attempted"], "exact": tot["exact"],
            "abstain": tot["abstain"], "oot_promoted": oot_promoted, "promoted_vendors": sorted(promoted)[:60]}


async def evaluate_ai(db, force: bool = False) -> Dict[str, Any]:
    """Replay the AI step on each vendor's most recent invoices the learner
    abstains on (AP's answer hidden) and turn it on per vendor where it is
    at least AI_MIN_ACC exact on AI_MIN_N or more. Weekly; ~250 model calls."""
    import asyncio as _aio
    if not AI_CODING:
        return {"disabled": True}
    st = await db.line_learning_state.find_one({"_id": "ai_eval"}) or {}
    if not force and st.get("at") and st["at"] > (datetime.now(timezone.utc) - timedelta(days=AI_EVAL_DAYS)).isoformat():
        return {"skipped": "evaluated " + st["at"]}
    C = await coder(db, refresh=True)
    prom = set(await db.line_learning_scores.distinct("vendor", {"promoted": True}))
    pool: Dict[str, List[Any]] = collections.defaultdict(list)
    seen = set()
    async for d in db.hub_documents.find({"bc_link.bc_document_no": {"$exists": True}}, {"_id": 0, "file_content_b64": 0}).sort("created_utc", -1):
        no = d["bc_link"]["bc_document_no"]
        v = d.get("vendor_canonical")
        if no in seen or not v or v in prom or len(pool[v]) >= AI_PER_VENDOR:
            continue
        seen.add(no)
        inv = await db.bc_purchase_invoice_lines.find_one({"number": no}, {"_id": 0, "purchaseInvoiceLines": 1})
        if not inv:
            continue
        ctx = await context(db, d)
        lines, why = C.lines(d, ctx, exclude_doc=no)
        if lines is None and "add up" not in why:
            pool[v].append((d, inv, ctx))
    from services.llm_router import get_provider
    prov = get_provider("classification")
    out, now = {}, datetime.now(timezone.utc).isoformat()
    for v in sorted(pool, key=lambda x: -len(pool[x]))[:AI_VENDORS]:
        n = att = ok = 0
        for d, inv, ctx in pool[v]:
            no = d["bc_link"]["bc_document_no"]
            ap = [(str(l["lineObjectNumber"]).upper(), _bc_amount(l)) for l in inv.get("purchaseInvoiceLines", [])
                  if l.get("lineObjectNumber") and _bc_amount(l)]
            lines, _ = await ai_lines(db, C, d, ctx, exclude_doc=no, provider=prov)
            await _aio.sleep(2)
            n += 1
            if lines is None:
                continue
            att += 1
            ok += _same([(l["lineObjectNumber"], round(l["quantity"] * l["unitCost"], 2)) for l in lines], ap)
        acc = ok / att if att else 0.0
        on = att >= AI_MIN_N and acc >= AI_MIN_ACC
        out[v] = {"n": n, "attempted": att, "exact": ok, "on": on}
        await db.line_learning_scores.update_one({"vendor": v}, {"$set": {
            "ai_replayed": n, "ai_attempted": att, "ai_exact": ok, "ai_accuracy": round(acc, 3),
            "ai_promoted": on, "ai_evaluated_at": now}}, upsert=True)
    await db.line_learning_state.update_one({"_id": "ai_eval"}, {"$set": {"at": now, "result": out}}, upsert=True)
    return {"vendors": len(out), "ai_promoted": sorted(v for v, r in out.items() if r["on"])}


# ------------------------------------------------------------------- plan
async def plan(db, d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Learned lines for a promoted vendor's invoice, else None."""
    if not LEARNED_CODING:
        return None
    v = d.get("vendor_canonical")
    s = await db.line_learning_scores.find_one({"vendor": v}, {"_id": 0, "accuracy": 1, "promoted": 1,
                                                                 "ai_promoted": 1, "ai_accuracy": 1})
    if not s or not (s.get("promoted") or s.get("ai_promoted")):
        return None
    C = await coder(db)
    ctx = await context(db, d)
    if s.get("promoted"):
        lines, why = C.lines(d, ctx)
        if lines:
            return {"lines": lines, "source": "learned_coding", "accuracy": s.get("accuracy")}
    if AI_CODING and s.get("ai_promoted"):
        lines, why = await ai_lines(db, C, d, ctx)
        if lines:
            return {"lines": lines, "source": "learned_coding_ai", "accuracy": s.get("ai_accuracy")}
    return None


async def run(db) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        out["harvest"] = await harvest(db)
    except Exception as e:
        out["harvest"] = {"error": repr(e)[:200]}
    out["examples"] = await build_examples(db)
    out["evaluate"] = await evaluate(db)
    try:
        out["ai"] = await evaluate_ai(db)
    except Exception as e:
        out["ai"] = {"error": repr(e)[:200]}
    return out
