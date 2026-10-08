"""Customer item cross-reference learned from BC: the customer's own item
code / description on their PO -> the Gamer item inside sales put on the
BC order, with the quantity ratio (customer units -> BC unit of measure)
and the customer's last BC price.

Customers order with their own codes (Westrock "PG-100671" = BC 6075072,
Ortho "118X30" = S-TSLOGO-118X30, Create "430105" = 60756): only 35% of
BC items appear on the PO (2026-10-07). Each customer PO linked to its BC
order (sales_link_service) is a labelled pair; extracted lines are paired
with BC item lines by quantity (same or per-thousand), else one main line
each, and the pairing is counted per customer.

resolve_lines(db, customer_no, extracted_lines) -> draft lines with item,
quantity in BC units, unit price (last BC price), and how each was found.
"""
import re
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Tuple

_AUX = {"PALLET", "FREIGHT", "Z-POP", "BALLPALLET", "BALLTIERSHEET", "CANPACKPALLET", "WHSESTORAGE", "WHSEHANDLING", "MISC"}
# Sizes / dimensions are not item codes: 1000CC, 128OZ, 32G, 56X44IN, 110MM.
_SIZE = re.compile(r"^(?:\d+(?:CC|OZ|G|GR|ML|MM|L|LB|LBS|IN|CT|PK|X\d+(?:IN|MM)?)|\d{1,4}|20\d{6}|\d{2,3}[48]\d{2})$")
_CODE = re.compile(r"(?<![A-Z0-9])([A-Z]{0,4}-?\d[A-Z0-9-]{2,24}|\d{3,}X\d{2,})(?![A-Z0-9])", re.I)


_CATEGORY: Dict[str, str] = {}
_ITEM_BY_NORM: Dict[str, str] = {}
_SOLD: Counter = Counter()


async def load_sold(db) -> Counter:
    """How often each item was on a BC sales order in the last year."""
    if not _SOLD:
        async for o in db.bc_sales_orders.find({}, {"_id": 0, "lines.lineObjectNumber": 1}):
            for it in {str(l.get("lineObjectNumber") or "").upper() for l in o.get("lines") or []}:
                if it:
                    _SOLD[it] += 1
    return _SOLD


async def load_item_categories(db) -> Dict[str, str]:
    if not _CATEGORY:
        async for i in db.bc_reference_cache.find({"bc_entity_type": "item"}, {"_id": 0, "bc_document_no": 1, "item_category_code": 1}):
            _CATEGORY[str(i["bc_document_no"]).upper()] = str(i.get("item_category_code") or "")
            _ITEM_BY_NORM[n(i["bc_document_no"])] = str(i["bc_document_no"]).upper()
            _ITEM_BY_NORM.setdefault(o0(i["bc_document_no"]), str(i["bc_document_no"]).upper())
    return _CATEGORY


def is_product(item: Any) -> bool:
    """A product line (bottle, cap, can...) - not a charge line inside sales
    adds (TARIFF, CUSTOMS, AMORT, SMALL, Z-COA, PALLET, FREIGHT)."""
    code = str(item or "").upper()
    if code in _AUX or not code:
        return False
    cat = _CATEGORY.get(code)
    # Dunnage (item category PALLET: O-I pallets / tier sheets / top frames,
    # Ball, Canpack, Vulcan) is added by inside sales like a charge.
    if cat == "PALLET":
        return False
    return bool(cat) if cat is not None else True


def o0(x: Any) -> str:
    """Letter O and zero are one character for matching codes (VetsPlus
    writes OPA-8OZ53MMCL for BC 0PA-...)."""
    return re.sub(r"[^A-Z0-9]", "", str(x or "").upper()).replace("O", "0")


def n(x: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(x or "").upper())


def num(x: Any) -> Optional[float]:
    try:
        v = float(str(x).replace(",", "").replace("$", "").strip())
        return v if v == v else None
    except Exception:
        return None


def customer_codes(line: Dict[str, Any]) -> List[str]:
    """Codes on an extracted line: explicit item fields, then code-like
    tokens in the description ("PG-100671 - Can 11oz ...")."""
    out = []
    for k in ("item_code", "sku", "customer_item", "part_number", "item_number"):
        if line.get(k):
            out.append(n(line[k]))
    desc = str(line.get("description") or "")
    head = re.split(r"\s[-–—]\s|;", desc)[0]
    desc = re.sub(r"\b\d{2,3}-\d{3}\b", " ", desc)          # neck finishes 20-410, 53-485
    desc = re.sub(r"\b\d+\.\d+\b", " ", desc)               # 294.9 ml
    out += [n(m) for m in _CODE.findall(head.upper())]
    out += [n(m) for m in _CODE.findall(desc.upper())][:4]
    return [c for c in dict.fromkeys(out) if len(c) >= 3 and not _SIZE.match(c)]


def desc_key(line: Dict[str, Any]) -> str:
    words = re.findall(r"[A-Z0-9]+", str(line.get("description") or "").upper())
    return " ".join(w for w in words if len(w) > 1)[:80]


def _bc_item_lines(order: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [l for l in order.get("lines") or [] if l.get("lineType") == "Item" and float(l.get("quantity") or 0) > 0
            and is_product(l.get("lineObjectNumber"))]


def pair(extracted: List[Dict[str, Any]], bc_lines: List[Dict[str, Any]]) -> List[Tuple[Dict[str, Any], Dict[str, Any], float]]:
    """(extracted line, BC line, BC qty / extracted qty)."""
    out, used = [], set()
    items = {n(b["lineObjectNumber"]): b for b in bc_lines}
    for e in extracted:
        eq = num(e.get("quantity"))
        txt = n(e.get("description")) + " ".join(customer_codes(e))
        hit = next((b for code, b in items.items() if code and code in txt and id(b) not in used), None)
        if not hit and eq:
            for b in bc_lines:
                bq = float(b["quantity"])
                if id(b) not in used and any(abs(bq - eq * f) <= max(0.01, 0.001 * bq) for f in (1, 0.001)):
                    hit = b
                    break
        if hit:
            used.add(id(hit))
            out.append((e, hit, (float(hit["quantity"]) / eq) if eq else None))
    # Same number of product lines on both sides: pair the rest in order
    # (Fiesta C2700 / C2701 -> 10142 / 10169).
    left_e = [e for e in extracted if not any(e is p[0] for p in out) and not _charge_text(e)]
    left_b = [b for b in bc_lines if id(b) not in used]
    if left_e and len(left_e) == len(left_b):
        for e, b in zip(left_e, left_b):
            eq = num(e.get("quantity"))
            out.append((e, b, (float(b["quantity"]) / eq) if eq else None))
    return out


_STOP = {"THE", "AND", "FOR", "WITH", "PER", "EA", "EACH", "CS", "CASE", "PLT", "PALLET", "GAMER", "ITEM", "BTL", "BOTTLE", "CAP", "CT"}
_CHARGE_WORDS = re.compile(r"\b(freight|pallet|tariff|customs|fee|charge|shipping|setup|set up|deposit|surcharge)\b", re.I)


def _charge_text(e: Dict[str, Any]) -> bool:
    return bool(_CHARGE_WORDS.search(str(e.get("description") or ""))) and not re.search(r"\d{4,}", str(e.get("description") or ""))


async def learn(db) -> Dict[str, Any]:
    await load_item_categories(db)
    now = datetime.now(timezone.utc).isoformat()
    xref = defaultdict(Counter)       # (customer, code or desc) -> item counts
    ratio = defaultdict(list)          # (customer, item) -> qty ratios
    stats = Counter()
    async for d in db.hub_documents.find({"sales_link.role": "customer_po", "sales_link.order_no": {"$ne": None}},
                                         {"_id": 0, "extracted_fields.line_items": 1, "sales_link": 1}):
        o = await db.bc_sales_orders.find_one({"order_no": d["sales_link"]["order_no"]}, {"_id": 0, "customer_no": 1, "lines": 1})
        el = (d.get("extracted_fields") or {}).get("line_items") or []
        if not o or not el:
            continue
        cust = o["customer_no"]
        for e, b, r in pair(el, _bc_item_lines(o)):
            item = str(b["lineObjectNumber"]).upper()
            for code in customer_codes(e):
                if code != n(item):
                    xref[(cust, "code:" + code)][item] += 1
            dk = desc_key(e)
            if dk:
                xref[(cust, "desc:" + dk)][item] += 1
            if r:
                ratio[(cust, item)].append(round(r, 6))
            stats["pairs"] += 1
    # Drafts a reviewer corrected in the sandbox: what they left is the truth.
    async for d in db.hub_documents.find({"sales_draft_readback.edits.0": {"$exists": True}, "sales_draft_readback.lines": {"$exists": True}},
                                         {"_id": 0, "extracted_fields.line_items": 1, "sales_link": 1, "sales_draft_readback": 1}):
        cust = (d.get("sales_link") or {}).get("bc_customer_no")
        el = (d.get("extracted_fields") or {}).get("line_items") or []
        rl = [{"lineType": "Item", **l} for l in d["sales_draft_readback"]["lines"]]
        if not cust or not el:
            continue
        for e, b, r in pair(el, _bc_item_lines({"lines": rl})):
            item = str(b["lineObjectNumber"]).upper()
            for code in customer_codes(e):
                if code != n(item):
                    xref[(cust, "code:" + code)][item] += 3
            dk = desc_key(e)
            if dk:
                xref[(cust, "desc:" + dk)][item] += 3
            stats["reviewed_draft_pairs"] += 1
    await db.sales_item_xref.delete_many({})
    docs = []
    for (cust, key), items in xref.items():
        item, k = items.most_common(1)[0]
        docs.append({"customer_no": cust, "key": key, "item": item, "n": k, "share": round(k / sum(items.values()), 2), "updated_at": now})
    for (cust, item), rs in ratio.items():
        r = Counter(rs).most_common(1)[0][0]
        docs.append({"customer_no": cust, "key": "ratio:" + item, "item": item, "ratio": r, "n": len(rs), "updated_at": now})
    if docs:
        await db.sales_item_xref.insert_many(docs)
    await db.sales_item_xref.create_index([("customer_no", 1), ("key", 1)])
    stats["xref_rows"] = len(docs)
    return dict(stats)


def _order_seq(order_no: Any) -> int:
    """Gamer order numbers are sequential: the number is when it was
    ordered (invoiced BC orders carry no order date, and prices are set
    when the order is created: Ball cans 116373 at 155.49 invoiced Oct 5,
    new order 120149 at 153.94)."""
    digits = re.sub(r"\D", "", str(order_no or ""))
    return int(digits) if digits and len(digits) <= 8 else 0


async def customer_history(db, customer_no: str, as_of: Optional[str] = None,
                           before_order: Optional[str] = None) -> Dict[str, Dict[str, Any]]:
    """item -> {last_price, uom, n, last_seq, description, prices} from BC
    orders; "last" = the latest ORDERED (highest order number). Replays use
    before_order (orders created before it) or as_of (a date)."""
    hist = {}
    limit_seq = _order_seq(before_order) if before_order else 0
    async for o in db.bc_sales_orders.find({"customer_no": customer_no}, {"_id": 0, "order_no": 1, "lines": 1, "order_date": 1, "first_invoice_date": 1}):
        seq = _order_seq(o.get("order_no"))
        if limit_seq and (not seq or seq >= limit_seq):
            continue
        od = o.get("order_date") if o.get("order_date") and not str(o.get("order_date")).startswith("0001") else (o.get("first_invoice_date") or "")
        if as_of and not limit_seq and str(od or "") >= as_of:
            continue
        for l in o.get("lines") or []:
            if l.get("lineType") != "Item" or not l.get("lineObjectNumber"):
                continue
            it = str(l["lineObjectNumber"]).upper()
            h = hist.setdefault(it, {"n": 0, "last_seq": -1, "last_date": "", "description": l.get("description"), "prices": set()})
            h["n"] += 1
            if float(l.get("unitPrice") or 0) > 0:
                h["prices"].add(float(l["unitPrice"]))
                if seq > h["last_seq"] or (seq == h["last_seq"] and str(od) > h["last_date"]):
                    h.update(last_seq=seq, last_date=str(od or ""), last_price=float(l["unitPrice"]),
                             uom=l.get("unitOfMeasureCode"), description=l.get("description"))
    return hist


def _code_tokens(desc: Any, min_len: int = 4) -> List[str]:
    """Code-like tokens of a PO line, normalized: dots kept inside codes
    (Sun Bum 20-20750.002444104A) and each token also joined with the next
    one (20-20755.002 R444103 = 20-20755.002R444103)."""
    raw = re.findall(r"[A-Z0-9][A-Z0-9.\-]{%d,}" % (min_len - 1), str(desc or "").upper())
    raw = [t.rstrip(".-") for t in raw]
    out = [n(t) for t in raw]
    out += [n(a + b) for a, b in zip(raw, raw[1:])]
    return [t for t in dict.fromkeys(out) if len(t) >= min_len]


def _newer_revision(item: str, hist: Dict[str, Dict[str, Any]]) -> Optional[str]:
    """A revision of `item` (same number + a letter / -A) the customer bought
    more recently than `item` itself."""
    base = re.sub(r"(-?[A-Z])$", "", str(item).upper()) if re.search(r"\d-?[A-Z]$", str(item).upper()) else str(item).upper()
    fam = [i for i in hist if i != item and is_product(i) and re.fullmatch(re.escape(base) + r"-?[A-Z]", i)]
    if not fam:
        return None
    last = (hist.get(item) or {}).get("last_date") or ""
    best = max(fam, key=lambda i: hist[i].get("last_date") or "")
    return best if (hist[best].get("last_date") or "") > last else None


async def _candidates(db, e: Dict[str, Any], hist: Dict[str, Dict[str, Any]], rows: Dict[str, Dict[str, Any]]) -> List[tuple]:
    """(item, how, strong) in priority order for one PO line."""
    out: List[tuple] = []
    txt = n(e.get("description"))
    known = {n(i): i for i in hist}
    # 1. A Gamer item number this customer buys, written on the PO.
    desc_u = re.sub(r"(?<=\d),(?=\d{3})", "", str(e.get("description") or "").upper())   # 48,000/plt -> 48000/plt
    txt0 = txt.replace("O", "0")
    hits = sorted({orig for code, orig in known.items() if len(code) >= 4 and (code in txt or code.replace("O", "0") in txt0)
                   # pack counts are not item numbers: "48000/plt", "58,240/TL"
                   and not re.search(re.escape(orig) + r"\s*/\s*(PLT|PALLET|CS|CASE|TL|TRUCK|LAYER)", desc_u)}, key=len, reverse=True)
    if hits and all(n(h) in n(hits[0]) for h in hits[1:]):
        h0 = hits[0]
        # A bare number (48000) is an item number only where the PO labels it
        # one; anywhere else it may be a pack count or size: needs confirming.
        labelled = not h0.isdigit() or bool(re.search(r"(^|ITEM\s*#?:?\s*|PART\s*(?:NO\.?|#)?:?\s*|STOCK\s*CODE\s*:?\s*|SKU\s*:?\s*|P/N\s*:?\s*|#\s*)" + re.escape(h0) + r"\b", desc_u.strip()))
        out.append((h0, "item number on the PO", labelled))
    # 2. The customer's own item code, learned from their BC orders.
    for code in customer_codes(e):
        r = rows.get("code:" + code)
        if r and r["share"] >= 0.6:
            out.append((r["item"], f"customer item {code} (learned from {r['n']} order{'s' if r['n'] > 1 else ''})", r["n"] >= 2))
            break
    # 3. Any Gamer item number written on the PO (new item for this customer).
    if not _charge_text(e):
        desc_up = str(e.get("description") or "").upper()
        for tok in _code_tokens(desc_up, 5):
            if tok not in _ITEM_BY_NORM and tok.replace("O", "0") in _ITEM_BY_NORM:
                tok = tok.replace("O", "0")
            if tok in _ITEM_BY_NORM and _CATEGORY.get(_ITEM_BY_NORM[tok]) and not _SIZE.match(tok) and re.search(r"\d", tok):
                # A full alphanumeric Gamer item number printed on the PO
                # (VetsPlus 0PA-5OZCAP) is the customer using Gamer's number;
                # a bare number (48000) may be anything and must be confirmed.
                # A bare number the PO labels as the item ("Item 612000046") counts too.
                labelled = bool(re.search(r"(ITEM|PART|SKU|STOCK\s*CODE|P/N)\s*(NO\.?|#)?\s*:?\s*" + re.escape(_ITEM_BY_NORM[tok]), desc_up))
                strong = (bool(re.search(r"[A-Z]", tok)) and len(tok) >= 6 or labelled) and is_product(_ITEM_BY_NORM[tok])
                out.append((_ITEM_BY_NORM[tok], "Gamer item number on the PO (new for this customer)", strong))
                break
    # 4. The customer's description, learned.
    r = rows.get("desc:" + desc_key(e))
    if r and r["share"] >= 0.6:
        out.append((r["item"], f"customer description (learned from {r['n']} order{'s' if r['n'] > 1 else ''})", r["n"] >= 2))
    if _charge_text(e):
        return out
    # 5. A maker's code that starts one Gamer item number (C-8479 -> C-8479-10000229).
    for tok in _code_tokens(e.get("description"), 4):
        if len(tok) < 4 or _SIZE.match(tok) or not re.search(r"\d", tok):
            continue
        own = [i for i in hist if n(i).startswith(tok) and is_product(i)]
        pool = own or [i for i in _CATEGORY if _CATEGORY[i] and n(i).startswith(tok)]
        if len(pool) > 1:
            # Several revisions (C-503003-12033484 / -12033922): the one that
            # clearly dominates BC sales, else a person decides.
            sold = await load_sold(db)
            ranked = sorted(pool, key=lambda i: sold.get(i, 0), reverse=True)
            top, rest = sold.get(ranked[0], 0), sum(sold.get(i, 0) for i in ranked[1:])
            pool = [ranked[0]] if top >= 3 and top >= 4 * rest else pool
        if len(pool) == 1:
            out.append((pool[0], f"{tok} starts Gamer item {pool[0]}" + ("" if own else " (new item for this customer)"), bool(own)))
            break
    # 6. The customer's own items by shared size / finish / colour words.
    words = set(re.findall(r"[A-Z0-9]+", str(e.get("description") or "").upper())) - _STOP
    if DESC_IDF:
        # Words weighted by how rare they are among this customer's items:
        # "20-400 FLINT BOSTON ROUND" is every Apex bottle, "2OZ" picks one.
        import math
        items = {it: set(re.findall(r"[A-Z0-9]+", str(h.get("description") or "").upper())) - _STOP
                 for it, h in hist.items() if is_product(it)}
        df = Counter(w for ws in items.values() for w in ws)
        N = len(items)
        scored = sorted(((sum(math.log((N + 1) / (df[w] + 0.5)) for w in words & ws), it) for it, ws in items.items() if ws), reverse=True)
        if scored and scored[0][0] >= DESC_T and (len(scored) == 1 or scored[0][0] >= scored[1][0] + DESC_M):
            sure = DESC_STRONG and scored[0][0] >= DESC_STRONG and (len(scored) == 1 or scored[0][0] >= 1.25 * scored[1][0])
            out.append((scored[0][1], "description matches an item this customer buys", bool(sure)))
    else:
        scored = []
        for it, h in hist.items():
            if not is_product(it):
                continue
            hw = set(re.findall(r"[A-Z0-9]+", str(h.get("description") or "").upper())) - _STOP
            common = words & hw
            if hw:
                scored.append((len(common) + 0.5 * sum(1 for w in common if any(c.isdigit() for c in w)), it))
        scored.sort(reverse=True)
        if scored and scored[0][0] >= 3 and (len(scored) == 1 or scored[0][0] >= scored[1][0] + 1.5):
            out.append((scored[0][1], "description matches an item this customer buys", False))
    seen, uniq = {}, []
    for c in out:
        if c[0] not in seen:
            seen[c[0]] = len(uniq)
            uniq.append(c)
        elif AGREE_STRONG and not uniq[seen[c[0]]][2]:
            # Two independent signals name the same item: as good as strong.
            i = seen[c[0]]
            uniq[i] = (c[0], uniq[i][1] + " · " + c[1], True)
    return uniq


# Honest replay 2026-10-08 (items/precision/orders fully right):
# 75/89/68 -> 76/92/70 with IDF descriptions (T 4, margin 1.5, strong 8),
# items confirmed on BC's price only, and no rule-out by value for
# customers whose PO prices BC replaces. PRINTED_FIRST and AGREE_STRONG
# measured no change: off.
DESC_IDF = True
DESC_T = 4.0
DESC_M = 1.5
DESC_STRONG = 8.0
AGREE_STRONG = False
PRINTED_FIRST = False
NO_RULEOUT_WHEN_OVERRIDDEN = True
FIT_ON_BC = True
_ITEM_UOM: Dict[str, str] = {}
_HONOR_CACHE: Dict[Tuple[str, str], Tuple[int, int]] = {}
_CACHE_AT = {"t": 0.0}


def _expire_caches() -> None:
    import time
    if time.time() - _CACHE_AT["t"] > 3600:     # live server: new orders and items count within the hour
        _ITEM_UOM.clear()
        _HONOR_CACHE.clear()
        _CACHE_AT["t"] = time.time()
HONOR_MIN_IGNORED = 1       # replay 2026-10-08: min 1 -> 87% prices, 2 -> 84%, 3 -> 82%, off -> 72%
HONOR_MAX_RATE = 0.5


async def item_uom(db, item: str) -> Optional[str]:
    """The unit BC usually sells this item in, across all customers."""
    _expire_caches()
    if not _ITEM_UOM:
        c: Dict[str, Counter] = {}
        async for o in db.bc_sales_orders.find({}, {"_id": 0, "lines.lineObjectNumber": 1, "lines.unitOfMeasureCode": 1}):
            for l in o.get("lines") or []:
                if l.get("lineObjectNumber") and l.get("unitOfMeasureCode"):
                    c.setdefault(str(l["lineObjectNumber"]).upper(), Counter())[str(l["unitOfMeasureCode"]).upper()] += 1
        _ITEM_UOM.update({k: v.most_common(1)[0][0] for k, v in c.items()})
        _ITEM_UOM["__loaded__"] = "1"
    return _ITEM_UOM.get(str(item).upper())


async def po_price_honor(db, customer_no: str, before_order: Optional[str] = None) -> Tuple[int, int]:
    """(honored, overridden): on this customer's earlier POs, how often BC
    kept the PO's unit price vs entered another. Sun Bum and Hearthside PO
    prices are their own list; BC keeps Gamer's (replay 2026-10-08)."""
    _expire_caches()
    key = (customer_no, before_order or "")
    if key in _HONOR_CACHE:
        return _HONOR_CACHE[key]
    limit = _order_seq(before_order) if before_order else 0
    honored = overridden = 0
    seen = set()
    async for d in db.hub_documents.find({"sales_link.role": "customer_po", "sales_link.bc_customer_no": customer_no,
                                          "sales_link.order_no": {"$ne": None}},
                                         {"_id": 0, "extracted_fields.line_items": 1, "sales_link.order_no": 1}):
        on = d["sales_link"]["order_no"]
        seq = _order_seq(on)
        if on in seen or (limit and (not seq or seq >= limit)):
            continue
        seen.add(on)
        o = await db.bc_sales_orders.find_one({"order_no": on}, {"_id": 0, "lines": 1})
        el = (d.get("extracted_fields") or {}).get("line_items") or []
        bl = _bc_item_lines(o or {})
        for e, b, _ in pair(el, bl):
            pp, bp = num(e.get("unit_price")), float(b.get("unitPrice") or 0)
            if not pp or bp <= 0:
                continue
            c = min((pp, pp * 1000), key=lambda v: abs(v - bp))
            if abs(c - bp) <= 0.005 * bp:
                honored += 1
            elif abs(c - bp) <= 0.5 * bp:
                overridden += 1
    _HONOR_CACHE[key] = (honored, overridden)
    return honored, overridden


def _value(e: Dict[str, Any], item: str, h: Dict[str, Any], rr: Optional[Dict[str, Any]],
           ctx: Optional[Dict[str, Any]] = None) -> Dict[str, Any]:
    """Quantity in BC units and price for one candidate; fits = the PO line's
    value agrees (None when the PO shows no value). ctx: item_uom (usual BC
    unit of the item), overrides_po (BC rarely keeps this customer's PO price)."""
    ctx = ctx or {}
    eq = num(e.get("quantity"))
    price, uom = h.get("last_price"), h.get("uom") or ctx.get("item_uom")
    if eq and rr:
        qty = round(eq * rr["ratio"], 4)
    elif eq and str(uom or "").upper() == "M" and eq >= 1000:
        qty = round(eq / 1000, 4)       # BC sells per thousand; the PO counts units
    else:
        qty = eq
    po_price = num(e.get("unit_price"))
    price_source = "last BC price for this customer" if price else None
    fit_price = None
    if po_price:
        for f in (1, 1000):
            cand = round(po_price * f, 6)
            if price and abs(cand - price) <= 0.005 * price:
                break                   # the PO shows BC's price rounded: keep BC's exact figure
            if price and abs(cand - price) <= 0.5 * price and ctx.get("overrides_po"):
                price_source = f"last BC price (this customer's PO prices are usually replaced; PO shows {cand:g})"
                fit_price = cand          # item/unit judged as before; only the price shown changes
                break
            if price and abs(cand - price) <= 0.5 * price:
                # The customer's PO price (a new price list, a quote): BC's
                # exact figure when they have paid it before, else the PO's,
                # with BC's last price shown so the rep sees the change.
                exact = [p for p in h.get("prices") or () if abs(p - cand) <= 0.005 * p]
                last = price
                price = min(exact, key=lambda p: abs(p - cand)) if exact else cand
                price_source = "PO price" + ("" if exact or abs(price - last) <= 0.005 * last else f" (BC last {last:g})")
                break
            if not price and f == 1:
                # No history: a per-each PO price on an item BC sells per
                # thousand (0.08614 -> 86.14 per M).
                if str(uom or "").upper() == "M" and po_price < 5:
                    cand = round(po_price * 1000, 4)
                price, price_source = cand, "PO price"
    fits = None
    line_value = num(e.get("total")) or ((po_price or 0) * (eq or 0))
    # Only a BC price can confirm or rule out the item: a price taken from
    # the PO itself always "agrees" (Litehouse bottle 48000 on a Giovanni cap PO).
    if eq and line_value and price and h.get("last_price"):
        # The PO line's value decides the unit (192,000 x 0.12572 = 24,138 ->
        # 192 M at 125.72) and checks the item itself.
        cands = {eq, round(eq / 1000, 4)} | ({round(eq * rr["ratio"], 4)} if rr else set())
        # Confirm against BC's own price: the PO price (or one derived from
        # it) always "agrees" with itself (Sun Bum .001 vs .002, 2026-10-08).
        fp = h.get("last_price") if FIT_ON_BC else (fit_price or price)
        best = min(cands, key=lambda q: abs(q * fp - line_value))
        off = abs(best * fp - line_value) / line_value
        if off <= 0.03:
            fits, qty = True, best
        elif off > 0.25:
            fits = False                # clearly not this item (or unit)
        # 3-25%: a price change; inconclusive
    # Price risk (replay 2026-10-08: lines with none of these signals were
    # wrong 12% of the time; PO differs 66%, no history 75%, stale 38%).
    checks = []
    if price and not h.get("last_price"):
        checks.append("no BC price for this customer yet")
    elif price_source and price_source.startswith("PO price"):
        checks.append(f"PO price differs from the last BC price {h.get('last_price'):g}")
    elif price_source and price_source.startswith("last BC price (this customer's"):
        checks.append(price_source.split("(", 1)[1].rstrip(")"))
    if h.get("last_price") and h.get("last_date"):
        try:
            age = (datetime.now(timezone.utc).date() - datetime.fromisoformat(str(h["last_date"])[:10]).date()).days
            if age > 120:
                checks.append(f"last BC price is from {str(h['last_date'])[:10]}")
        except Exception:
            pass
    return {"quantity": qty, "unit_price": price, "unit_of_measure": uom, "price_source": price_source, "fits": fits,
            "price_check": "; ".join(checks) or None}


async def resolve_lines(db, customer_no: str, extracted: List[Dict[str, Any]], as_of: Optional[str] = None,
                        before_order: Optional[str] = None) -> List[Dict[str, Any]]:
    await load_item_categories(db)
    hist = await customer_history(db, customer_no, as_of=as_of, before_order=before_order)
    rows = {r["key"]: r async for r in db.sales_item_xref.find({"customer_no": customer_no}, {"_id": 0})}
    hon, ovr = await po_price_honor(db, customer_no, before_order)
    overrides_po = ovr >= HONOR_MIN_IGNORED and ovr / max(1, hon + ovr) >= HONOR_MAX_RATE
    out = []
    for e in extracted:
        chosen = None
        cands = await _candidates(db, e, hist, rows)
        valued = [(item, how, _value(e, item, hist.get(item) or {}, rows.get("ratio:" + item),
                                     {"item_uom": await item_uom(db, item), "overrides_po": overrides_po})) for item, how, _ in cands]
        # The first candidate the PO line's value confirms; else the first not
        # ruled out, in priority order.
        strong = {item: st for item, _, st in cands}
        if overrides_po and NO_RULEOUT_WHEN_OVERRIDDEN:
            # This customer's PO prices are their own list (Sun Bum 25-36%
            # under BC): a value mismatch says nothing about the item.
            for c in valued:
                if c[2]["fits"] is False:
                    c[2]["fits"] = None
        printed = next((c for c in valued if PRINTED_FIRST and strong[c[0]]
                        and (c[1].startswith("Gamer item number on the PO") or c[1].startswith("item number on the PO"))
                        and c[2]["fits"] is not False), None)
        pick = printed or next((c for c in valued if c[2]["fits"] is True), None) or \
            next((c for c in valued if c[2]["fits"] is None and strong[c[0]]), None)
        if pick:
            item, how, v = pick
            # The customer has since moved to a newer revision of this item
            # (Watkins FX60510A -> FX60510B, VetsPlus 120125 -> 120125-A).
            newer = _newer_revision(item, hist)
            if newer:
                item, how = newer, how + f" · newer revision {newer} the customer now buys"
                v = _value(e, item, hist.get(item) or {}, rows.get("ratio:" + item),
                           {"item_uom": await item_uom(db, item), "overrides_po": overrides_po})
            chosen = {"item": item, "how": how + (" · PO value agrees" if v["fits"] else ""), **v}
        chosen = chosen or {"item": None, "how": None, "quantity": None, "unit_price": None, "unit_of_measure": None, "price_source": None}
        chosen.pop("fits", None)
        out.append({"source": e, **chosen})
    return out

