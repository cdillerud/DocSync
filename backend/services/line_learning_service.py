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
from datetime import datetime, timedelta, timezone
from typing import Any, Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

LEARNED_CODING = True
HARVEST_FROM = "2026-04-01"
MIN_N = 10            # invoices the vendor's score is measured on
MIN_ACC = 0.90        # leave-one-out exact share needed to be promoted
MIN_CONF = 0.5        # every line of a learned draft must be at least this sure
K = 5
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


def tokens(desc: str, ctx: List[str]) -> frozenset:
    """Words, 4-letter pieces of longer words, word shapes (AAAA9999999 =
    a container number) and the context features."""
    up = str(desc or "").upper()
    raw = re.findall(r"[A-Z0-9][A-Z0-9&/.\-]*", up)
    out = set(ctx)
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
    return ctx


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
                         "ap_lines": len(ap), "pdf_lines": len(items)})
    await db.line_coding_examples.delete_many({})
    if rows:
        await db.line_coding_examples.insert_many(rows)
    return {**stats, "examples": len(rows)}


# ------------------------------------------------------------------ model
FEATURES = ("text", "code_in_desc", "amount", "price", "history", "receipt_x_vendor_rate", "receipt_x_other_rate", "not_on_receipt")


def _close(a: Optional[float], b: Optional[float], scale: float) -> float:
    if not a or not b or (a > 0) != (b > 0):
        return 0.0
    return math.exp(-abs(math.log(abs(a) / abs(b))) * scale)


class Coder:
    def __init__(self, examples: List[Dict[str, Any]], receipts: Optional[Dict[str, List[Dict[str, Any]]]] = None):
        self.receipts = receipts or {}
        self.ex = examples
        for e in self.ex:
            e["_t"] = tokens(e["description"], e.get("context") or [])
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

    def votes(self, desc: str, ctx: List[str], vendor: str, exclude_doc: Optional[str]) -> Tuple[Dict[str, float], float]:
        q = tokens(desc, ctx)
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
        scored.sort(reverse=True)
        top = scored[:K]
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
        hist, best = self.votes(line.get("description"), ctx, vendor, exclude_doc)
        cands = self.candidates(po)
        have = {c["code"] for c in cands}
        cands = cands + [{"code": c, "unit_cost": None} for c in hist if c not in have]
        vrate = self.receipt_rate.get(vendor, 0.5)
        return [(c, self.features(line, c, hist, best, vrate)) for c in cands]

    def _train(self, epochs: int = 300, lr: float = 0.5):
        """Softmax over each past line's candidates: which features point to
        the code AP chose. Plain numpy gradient ascent."""
        import numpy as np
        rows = []
        for e in self.ex:
            if not self.receipts.get(e.get("po") or ""):
                continue
            line = {"description": e["description"], "amount": e["amount"], "unit_price": e.get("unit_price")}
            opts = self.options(line, e.get("context") or [], e["vendor"], e["po"], e["bc_document_no"])
            ys = [i for i, (c, _) in enumerate(opts) if c["code"] == e["code"]]
            if len(opts) < 2 or not ys:
                continue
            rows.append((np.array([f for _, f in opts]), ys[0]))
        w = np.zeros(len(FEATURES))
        if not rows:
            return w
        for _ in range(epochs):
            g = np.zeros_like(w)
            for X, y in rows:
                s = X @ w
                p = np.exp(s - s.max())
                p /= p.sum()
                g += X[y] - p @ X
            w += lr * g / len(rows)
        self.train_rows = len(rows)
        return w

    def pick(self, line: Dict[str, Any], ctx: List[str], vendor: str, po: str, exclude_doc: Optional[str]) -> Tuple[Optional[str], float]:
        import numpy as np
        opts = self.options(line, ctx, vendor, po, exclude_doc)
        if not opts:
            return None, 0.0
        X = np.array([f for _, f in opts])
        s = X @ self.weights
        p = np.exp(s - s.max())
        p /= p.sum()
        i = int(p.argmax())
        self.last_pick = opts[i][0]
        return opts[i][0]["code"], float(p[i])

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
        scored.sort(reverse=True)
        top = scored[:K]
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
            uc = lp.get("unit_cost")
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
async def evaluate(db, scores: str = "line_learning_scores") -> Dict[str, Any]:
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
        ok = tv["attempted"] >= MIN_N and acc >= MIN_ACC and (cur is None or lcur is None or lcur >= cur)
        if ok:
            promoted.append(v)
        await db[scores].update_one({"vendor": v}, {"$set": {
            "vendor": v, "invoices": tv["n"], "attempted": tv["attempted"], "exact": tv["exact"],
            "accuracy": round(acc, 3), "coverage": round(tv["attempted"] / tv["n"], 3) if tv["n"] else 0,
            "current_method_accuracy": round(cur, 3) if cur is not None else None,
            "learned_on_same_invoices": round(lcur, 3) if lcur is not None else None,
            "promoted": ok, "updated_at": now}}, upsert=True)
    tot = sum((tv for tv in t.values()), collections.Counter())
    if scores == "line_learning_scores":
        await db.line_learning_state.update_one({"_id": "model"}, {"$set": {
            "weights": dict(zip(FEATURES, [round(float(x), 3) for x in C.weights])), "trained_on": getattr(C, "train_rows", 0),
            "examples": len(C.ex), "attempted": tot["attempted"], "exact": tot["exact"], "abstain": tot["abstain"],
            "promoted": len(promoted), "evaluated_at": now}}, upsert=True)
    return {"weights": dict(zip(FEATURES, [round(float(x), 2) for x in C.weights])), "trained_on": getattr(C, "train_rows", 0),
            "vendors": len(t), "promoted": len(promoted), "attempted": tot["attempted"], "exact": tot["exact"],
            "abstain": tot["abstain"], "promoted_vendors": sorted(promoted)[:40]}


# ------------------------------------------------------------------- plan
async def plan(db, d: Dict[str, Any]) -> Optional[Dict[str, Any]]:
    """Learned lines for a promoted vendor's invoice, else None."""
    if not LEARNED_CODING:
        return None
    v = d.get("vendor_canonical")
    s = await db.line_learning_scores.find_one({"vendor": v, "promoted": True}, {"_id": 0, "accuracy": 1})
    if not s:
        return None
    C = await coder(db)
    lines, why = C.lines(d, await context(db, d))
    if not lines:
        return None
    return {"lines": lines, "source": "learned_coding", "accuracy": s.get("accuracy")}


async def run(db) -> Dict[str, Any]:
    out: Dict[str, Any] = {}
    try:
        out["harvest"] = await harvest(db)
    except Exception as e:
        out["harvest"] = {"error": repr(e)[:200]}
    out["examples"] = await build_examples(db)
    out["evaluate"] = await evaluate(db)
    return out
