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
async def harvest(db) -> Dict[str, Any]:
    """New posted BC purchase invoices since the last harvest, per vendor."""
    import httpx
    import services.bc_catalog_sync_service as bc
    token = await bc.get_bc_token(environment="Production")
    cid = await bc.get_bc_company_id(environment="Production")
    base = f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/Production/api/{bc.BC_API_VERSION}/companies({cid})"
    H = {"Authorization": f"Bearer {token}"}
    vendors = [v for v in await db.hub_documents.distinct("bc_link.bc_vendor_no", {"bc_link.bc_document_no": {"$exists": True}}) if v]
    n = 0
    async with httpx.AsyncClient(timeout=120) as c:
        for v in vendors:
            last = await db.bc_purchase_invoice_lines.find_one({"vendorNumber": v}, {"postingDate": 1}, sort=[("postingDate", -1)])
            since = HARVEST_FROM
            if last and last.get("postingDate"):
                since = (datetime.fromisoformat(last["postingDate"]) - timedelta(days=5)).date().isoformat()
            url, params = f"{base}/purchaseInvoices", {
                "$filter": f"vendorNumber eq '{v}' and postingDate ge {since}",
                "$select": "number,vendorNumber,vendorInvoiceNumber,postingDate,totalAmountExcludingTax,status",
                "$expand": "purchaseInvoiceLines($select=sequence,lineType,lineObjectNumber,description,quantity,unitCost,amountExcludingTax)"}
            while url:
                try:
                    r = await c.get(url, headers=H, params=params)
                except Exception as e:
                    logger.warning("[LineLearning] harvest %s: %r", v, e)
                    break
                if r.status_code != 200:
                    break
                j = r.json()
                for inv in j.get("value", []):
                    inv.pop("@odata.etag", None)
                    await db.bc_purchase_invoice_lines.update_one({"number": inv["number"]}, {"$set": {
                        **inv, "cached_at": datetime.now(timezone.utc).isoformat()}}, upsert=True)
                    n += 1
                url, params = j.get("@odata.nextLink"), None
    return {"vendors": len(vendors), "invoices": n}


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
                         "code": str(l["lineObjectNumber"]).upper(), "line_type": l.get("lineType"), "ap_group": j,
                         "ap_lines": len(ap), "pdf_lines": len(items)})
    await db.line_coding_examples.delete_many({})
    if rows:
        await db.line_coding_examples.insert_many(rows)
    return {**stats, "examples": len(rows)}


# ------------------------------------------------------------------ model
class Coder:
    def __init__(self, examples: List[Dict[str, Any]]):
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
        for e in items:
            c, p = self.code(e.get("description"), ctx, v, exclude_doc)
            if not c or p < MIN_CONF:
                return None, f"not sure how AP codes '{str(e.get('description'))[:60]}'"
            out.append((c, _pdf_amount(e), str(e.get("description") or ""), p))
        if not self.separate.get(v):
            agg: Dict[str, List[Any]] = {}
            for c, a, desc, p in out:
                if c in agg:
                    agg[c][1] = round(agg[c][1] + a, 2)
                    agg[c][3] = min(agg[c][3], p)
                else:
                    agg[c] = [c, a, desc, p]
            out = [tuple(x) for x in agg.values()]
        lines = []
        for c, a, desc, p in out:
            lt = self.line_type.get((v, c), "Item")
            lines.append({"lineType": "Account" if lt == "Account" else "Item", "lineObjectNumber": c,
                          "description": desc[:100], "quantity": 1.0, "unitCost": round(a, 2),
                          "source": f"learned from AP's coding of this vendor's past invoices ({int(p * 100)}% sure)"})
        return lines, ""


_CODER: Optional[Coder] = None


async def coder(db, refresh: bool = False) -> Coder:
    global _CODER
    if _CODER is None or refresh:
        _CODER = Coder([e async for e in db.line_coding_examples.find({}, {"_id": 0})])
    return _CODER


def _same(pred: List[Tuple[str, float]], ap: List[Tuple[str, float]]) -> bool:
    if len(pred) != len(ap):
        return False
    a, b = sorted(pred), sorted(ap)
    return all(x[0] == y[0] and abs(x[1] - y[1]) <= 0.02 for x, y in zip(a, b))


# --------------------------------------------------------------- evaluate
async def evaluate(db) -> Dict[str, Any]:
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
        ok = _same([(l["lineObjectNumber"], l["unitCost"]) for l in lines], ap)
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
        await db.line_learning_scores.update_one({"vendor": v}, {"$set": {
            "vendor": v, "invoices": tv["n"], "attempted": tv["attempted"], "exact": tv["exact"],
            "accuracy": round(acc, 3), "coverage": round(tv["attempted"] / tv["n"], 3) if tv["n"] else 0,
            "current_method_accuracy": round(cur, 3) if cur is not None else None,
            "learned_on_same_invoices": round(lcur, 3) if lcur is not None else None,
            "promoted": ok, "updated_at": now}}, upsert=True)
    tot = sum((tv for tv in t.values()), collections.Counter())
    return {"vendors": len(t), "promoted": len(promoted), "attempted": tot["attempted"], "exact": tot["exact"],
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
