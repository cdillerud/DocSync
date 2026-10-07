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


async def customer_history(db, customer_no: str) -> Dict[str, Dict[str, Any]]:
    """item -> {last_price, uom, n, last_date, description} from BC orders."""
    hist = {}
    async for o in db.bc_sales_orders.find({"customer_no": customer_no}, {"_id": 0, "lines": 1, "order_date": 1, "first_invoice_date": 1}):
        when = o.get("first_invoice_date") or o.get("order_date") or ""
        for l in o.get("lines") or []:
            if l.get("lineType") != "Item" or not l.get("lineObjectNumber"):
                continue
            it = str(l["lineObjectNumber"]).upper()
            h = hist.setdefault(it, {"n": 0, "last_date": "", "description": l.get("description"), "prices": set()})
            h["n"] += 1
            if float(l.get("unitPrice") or 0) > 0:
                h["prices"].add(float(l["unitPrice"]))
            if when >= h["last_date"] and float(l.get("unitPrice") or 0) > 0:
                h.update(last_date=when, last_price=float(l["unitPrice"]), uom=l.get("unitOfMeasureCode"), description=l.get("description"))
    return hist


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
    hits = sorted({orig for code, orig in known.items() if len(code) >= 4 and code in txt
                   # pack counts are not item numbers: "48000/plt", "58,240/TL"
                   and not re.search(re.escape(orig) + r"\s*/\s*(PLT|PALLET|CS|CASE|TL|TRUCK|LAYER)", desc_u)}, key=len, reverse=True)
    if hits and all(n(h) in n(hits[0]) for h in hits[1:]):
        h0 = hits[0]
        # A bare number (48000) is an item number only where the PO labels it
        # one; anywhere else it may be a pack count or size: needs confirming.
        labelled = not h0.isdigit() or bool(re.search(r"(^|ITEM\s*#?:?\s*|PART\s*#?:?\s*|#\s*)" + re.escape(h0) + r"\b", desc_u.strip()))
        out.append((h0, "item number on the PO", labelled))
    # 2. The customer's own item code, learned from their BC orders.
    for code in customer_codes(e):
        r = rows.get("code:" + code)
        if r and r["share"] >= 0.6:
            out.append((r["item"], f"customer item {code} (learned from {r['n']} order{'s' if r['n'] > 1 else ''})", r["n"] >= 2))
            break
    # 3. Any Gamer item number written on the PO (new item for this customer).
    if not _charge_text(e):
        for tok in dict.fromkeys(n(t) for t in re.findall(r"[A-Z0-9][A-Z0-9-]{4,}", str(e.get("description") or "").upper())):
            if tok in _ITEM_BY_NORM and _CATEGORY.get(_ITEM_BY_NORM[tok]) and not _SIZE.match(tok) and re.search(r"\d", tok):
                out.append((_ITEM_BY_NORM[tok], "Gamer item number on the PO (new for this customer)", False))
                break
    # 4. The customer's description, learned.
    r = rows.get("desc:" + desc_key(e))
    if r and r["share"] >= 0.6:
        out.append((r["item"], f"customer description (learned from {r['n']} order{'s' if r['n'] > 1 else ''})", r["n"] >= 2))
    if _charge_text(e):
        return out
    # 5. A maker's code that starts one Gamer item number (C-8479 -> C-8479-10000229).
    for tok in dict.fromkeys(n(t) for t in re.findall(r"[A-Z0-9][A-Z0-9-]{3,}", str(e.get("description") or "").upper())):
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
    seen, uniq = set(), []
    for c in out:
        if c[0] not in seen:
            seen.add(c[0])
            uniq.append(c)
    return uniq


def _value(e: Dict[str, Any], item: str, h: Dict[str, Any], rr: Optional[Dict[str, Any]]) -> Dict[str, Any]:
    """Quantity in BC units and price for one candidate; fits = the PO line's
    value agrees (None when the PO shows no value)."""
    eq = num(e.get("quantity"))
    price, uom = h.get("last_price"), h.get("uom")
    if eq and rr:
        qty = round(eq * rr["ratio"], 4)
    elif eq and str(uom or "").upper() == "M" and eq >= 1000:
        qty = round(eq / 1000, 4)       # BC sells per thousand; the PO counts units
    else:
        qty = eq
    po_price = num(e.get("unit_price"))
    price_source = "last BC price for this customer" if price else None
    if po_price:
        for f in (1, 1000):
            cand = round(po_price * f, 6)
            if price and abs(cand - price) <= 0.005 * price:
                break                   # the PO shows BC's price rounded: keep BC's exact figure
            if price and abs(cand - price) <= 0.15 * price:
                exact = [p for p in h.get("prices") or () if abs(p - cand) <= 0.005 * p]
                price = min(exact, key=lambda p: abs(p - cand)) if exact else cand
                price_source = "PO price"
                break
            if not price and f == 1:
                price, price_source = cand, "PO price"
    fits = None
    line_value = num(e.get("total")) or ((po_price or 0) * (eq or 0))
    # Only a BC price can confirm or rule out the item: a price taken from
    # the PO itself always "agrees" (Litehouse bottle 48000 on a Giovanni cap PO).
    if eq and line_value and price and h.get("last_price"):
        # The PO line's value decides the unit (192,000 x 0.12572 = 24,138 ->
        # 192 M at 125.72) and checks the item itself.
        cands = {eq, round(eq / 1000, 4)} | ({round(eq * rr["ratio"], 4)} if rr else set())
        best = min(cands, key=lambda q: abs(q * price - line_value))
        off = abs(best * price - line_value) / line_value
        if off <= 0.03:
            fits, qty = True, best
        elif off > 0.25:
            fits = False                # clearly not this item (or unit)
        # 3-25%: a price change; inconclusive
    return {"quantity": qty, "unit_price": price, "unit_of_measure": uom, "price_source": price_source, "fits": fits}


async def resolve_lines(db, customer_no: str, extracted: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    await load_item_categories(db)
    hist = await customer_history(db, customer_no)
    rows = {r["key"]: r async for r in db.sales_item_xref.find({"customer_no": customer_no}, {"_id": 0})}
    out = []
    for e in extracted:
        chosen = None
        cands = await _candidates(db, e, hist, rows)
        valued = [(item, how, _value(e, item, hist.get(item) or {}, rows.get("ratio:" + item))) for item, how, _ in cands]
        # The first candidate the PO line's value confirms; else the first not
        # ruled out, in priority order.
        strong = {item: st for item, _, st in cands}
        pick = next((c for c in valued if c[2]["fits"] is True), None) or \
            next((c for c in valued if c[2]["fits"] is None and strong[c[0]]), None)
        if pick:
            item, how, v = pick
            # The customer has since moved to a newer revision of this item
            # (Watkins FX60510A -> FX60510B, VetsPlus 120125 -> 120125-A).
            newer = _newer_revision(item, hist)
            if newer:
                item, how = newer, how + f" · newer revision {newer} the customer now buys"
                v = _value(e, item, hist.get(item) or {}, rows.get("ratio:" + item))
            chosen = {"item": item, "how": how + (" · PO value agrees" if v["fits"] else ""), **v}
        chosen = chosen or {"item": None, "how": None, "quantity": None, "unit_price": None, "unit_of_measure": None, "price_source": None}
        chosen.pop("fits", None)
        out.append({"source": e, **chosen})
    return out

