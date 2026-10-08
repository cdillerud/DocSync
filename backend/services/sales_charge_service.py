"""Charge lines inside sales adds to a customer's sales orders, learned
from BC (pallets, tier sheets, freight, tariffs, customs, set-up fees).

Measured 2026-10-07 on a year of BC orders: FREIGHT on 56% of orders,
Ball pallets / tier sheets 12-17%, Canpack pallets 10%, tariffs 8-13%.
A draft is an order as ENTERED: charges added at invoicing (ENERGY: 9% of
open orders vs 22% of invoiced; WHSEFRT; freight surcharges) are left
out, and freight is entered at 0 and priced at invoicing for most
customers (Hearthside: PO says 675, the open BC order says 0).

Rules (sales_charge_rules), only for what is regular:
  presence  on >= 80% of the customer's product orders (>= 5 orders)
  quantity  fixed; or a steady ratio to the order's product quantity;
            or, per product item, a steady ratio (pallets / tier sheets
            per thousand of that can or end) for this customer, else
            across all customers
  price     the customer's entry price on open orders when constant
            (freight 0); constant on all orders; a steady percentage of
            the product value (tariff 50%); or the PO's freight amount
Anything less regular is left for the rep.
"""
import re
import statistics
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from services.sales_item_xref_service import _CATEGORY, _order_seq, is_product, load_item_categories, num

MIN_ORDERS = 5
MIN_RATE = 0.8
MAX_SPREAD = 0.15
_FREIGHT = {"FREIGHT", "Z-FREIGHT"}
_FREIGHT_WORDS = re.compile(r"\b(freight|shipping|delivery|p-freight)\b", re.I)


_ITEM_DESC: Dict[str, str] = {}


async def _load_item_desc(db) -> Dict[str, str]:
    if not _ITEM_DESC:
        async for i in db.bc_reference_cache.find({"bc_entity_type": "item"}, {"_id": 0, "bc_document_no": 1, "description": 1}):
            _ITEM_DESC[str(i["bc_document_no"]).upper()] = str(i.get("description") or "")
    return _ITEM_DESC


def size_signature(item: str, uom: Any = None) -> Optional[str]:
    """'12oz, 202, Sleek, Printed, ...' -> '12OZ,202,SLEEK|M': dunnage per
    unit is steady per container size (Ball 12oz sleek 0.1235 pallets per M
    on 100% of 596 orders, O-I 24oz jar 4.96 tier sheets per M), not per
    item number - every new can design is a new item."""
    d = _ITEM_DESC.get(str(item).upper()) or ""
    parts = [x.strip().upper().replace(" ", "") for x in d.split(",")[:3]]
    if len(parts) < 2 or not re.match(r"^\d+(\.\d+)?(OZ|ML|L|G|CC|GAL)$", parts[0]):
        return None          # not a container (artwork, tooling, charges)
    return ",".join(parts) + "|" + str(uom or "").upper()


SIZE_FALLBACK = True
FREIGHT_PLACEHOLDER = True
DUNNAGE_BY_SIZE = True
ITEM_CHARGES = True
ITEM_RULES_INVOICED_ONLY = False   # replay switch: learn item charges from invoiced orders only


def _lines(o: Dict[str, Any]) -> List[Dict[str, Any]]:
    return [l for l in o.get("lines") or [] if l.get("lineType") == "Item" and l.get("lineObjectNumber")]


def _steady(xs: List[float]) -> Optional[float]:
    xs = [v for v in xs if v and v > 0]
    if len(xs) < 3:
        return None
    m = statistics.mean(xs)
    return statistics.median(xs) if m and statistics.pstdev(xs) / m <= MAX_SPREAD else None


async def invoice_time_charges(db) -> set:
    open_n, inv_n = Counter(), Counter()
    tot = Counter()
    async for o in db.bc_sales_orders.find({"status": {"$in": ["open", "invoiced"]}}, {"_id": 0, "status": 1, "lines": 1}):
        ls = _lines(o)
        if not any(is_product(l["lineObjectNumber"]) for l in ls):
            continue
        tot[o["status"]] += 1
        for c in {str(l["lineObjectNumber"]).upper() for l in ls if not is_product(l["lineObjectNumber"])}:
            (open_n if o["status"] == "open" else inv_n)[c] += 1
    return {c for c, k in inv_n.items()
            if k >= 50 and tot["open"] and (open_n[c] / tot["open"]) / (k / tot["invoiced"]) < 0.6}


async def learn(db) -> Dict[str, Any]:
    await load_item_categories(db)
    excluded = await invoice_time_charges(db)
    obs = defaultdict(lambda: defaultdict(list))      # cust -> charge -> [dict]
    prod_ratio = defaultdict(list)                    # (cust, product, charge) -> [ratio]
    prod_price = defaultdict(list)                    # (cust, product, charge) -> [unit price]
    glob_ratio = defaultdict(list)                    # (product, charge) -> [ratio]
    orders = Counter()
    seen_any = defaultdict(Counter)                   # cust -> charge -> orders (incl. invoicing-time)
    all_q = defaultdict(lambda: defaultdict(list))
    await _load_item_desc(db)
    size_ratio = defaultdict(list)                    # (size signature, charge) -> [ratio]
    size_price = defaultdict(Counter)                 # (size signature, charge) -> unit prices
    size_orders = Counter()                           # size signature -> single-size orders
    item_orders = Counter()                           # item -> orders
    item_charge = defaultdict(list)                   # (item, charge) -> [(seq, qty_kind, qty, price)]
    async for o in db.bc_sales_orders.find({}, {"_id": 0, "customer_no": 1, "lines": 1, "status": 1, "order_no": 1}):
        ls = _lines(o)
        prods = [l for l in ls if is_product(l["lineObjectNumber"]) and float(l.get("quantity") or 0) > 0]
        if not prods:
            continue
        if len(prods) == 1 and not (ITEM_RULES_INVOICED_ONLY and o.get("status") == "open"):
            it1 = str(prods[0]["lineObjectNumber"]).upper()
            item_orders[it1] += 1
            pq1 = float(prods[0]["quantity"])
            for l in ls:
                c = str(l["lineObjectNumber"]).upper()
                if not is_product(c) and float(l.get("quantity") or 0) > 0:
                    q = float(l["quantity"])
                    kind = "same" if abs(q - pq1) < 1e-6 else ("one" if q == 1 else "other")
                    item_charge[(it1, c)].append((_order_seq(o.get("order_no")), kind, q, float(l.get("unitPrice") or 0)))
        sigs = {size_signature(l["lineObjectNumber"], l.get("unitOfMeasureCode")) for l in prods}
        if len(sigs) == 1 and None not in sigs:
            sig = sigs.pop()
            size_orders[sig] += 1
            pq_ = sum(float(l["quantity"]) for l in prods)
            for l in ls:
                c = str(l["lineObjectNumber"]).upper()
                if not is_product(c) and float(l.get("quantity") or 0) > 0 and pq_:
                    size_ratio[(sig, c)].append(float(l["quantity"]) / pq_)
                    size_price[(sig, c)][round(float(l.get("unitPrice") or 0), 4)] += 1
        cust = o["customer_no"]
        orders[cust] += 1
        pq = sum(float(l["quantity"]) for l in prods)
        pv = sum(float(l["quantity"]) * float(l.get("unitPrice") or 0) for l in prods)
        agg = {}
        for l in ls:
            c = str(l["lineObjectNumber"]).upper()
            if is_product(c):
                continue
            a = agg.setdefault(c, {"q": 0.0, "p": float(l.get("unitPrice") or 0)})
            a["q"] += float(l.get("quantity") or 0)
        for c, a in agg.items():
            seen_any[cust][c] += 1
            all_q[cust][c].append(a["q"])
            if c in excluded:
                continue
            obs[cust][c].append({"q": a["q"], "p": a["p"], "pq": pq, "pv": pv, "open": o.get("status") == "open"})
            if len(prods) == 1 and a["q"] > 0:
                it = str(prods[0]["lineObjectNumber"]).upper()
                prod_ratio[(cust, it, c)].append(a["q"] / float(prods[0]["quantity"]))
                prod_price[(cust, it, c)].append(round(a["p"], 4))
                glob_ratio[(it, c)].append(a["q"] / float(prods[0]["quantity"]))
    # Sandbox drafts a rep completed (lines added in BC) count as orders too:
    # what reps add is what the Hub should learn to add.
    async for d in db.hub_documents.find({"sales_draft_readback.edits.0": {"$exists": True}, "sales_draft_readback.lines.0": {"$exists": True}},
                                         {"_id": 0, "sales_link.bc_customer_no": 1, "sales_draft_readback.lines": 1}):
        cust = (d.get("sales_link") or {}).get("bc_customer_no")
        ls = [{"lineType": "Item", **l} for l in d["sales_draft_readback"]["lines"]]
        prods = [l for l in ls if is_product(l["lineObjectNumber"]) and float(l.get("quantity") or 0) > 0]
        if not cust or not prods:
            continue
        orders[cust] += 1
        pq = sum(float(l["quantity"]) for l in prods)
        pv = sum(float(l["quantity"]) * float(l.get("unitPrice") or 0) for l in prods)
        for l in ls:
            c = str(l["lineObjectNumber"]).upper()
            if not is_product(c) and c not in excluded:
                obs[cust][c].append({"q": float(l.get("quantity") or 0), "p": float(l.get("unitPrice") or 0), "pq": pq, "pv": pv, "open": True})
    now = datetime.now(timezone.utc).isoformat()
    usual = []
    for cust, charges in seen_any.items():
        if orders[cust] < 3:
            continue
        for c, k in charges.items():
            rate = k / orders[cust]
            if rate >= 0.3:
                qs = sorted(all_q[cust][c]) or [None]
                usual.append({"customer_no": cust, "charge": c, "rate": round(min(rate, 1.0), 2), "orders": orders[cust],
                              "typical_qty": qs[len(qs) // 2], "when": "shipping / invoicing" if c in excluded else "order entry",
                              "updated_at": now})
    await db.sales_charge_usual.delete_many({})
    if usual:
        await db.sales_charge_usual.insert_many(usual)
    await db.sales_charge_usual.create_index("customer_no")
    rules, product_rules = [], []
    for (cust, it, c), rs in prod_ratio.items():
        r = _steady(rs)
        pc = Counter(prod_price[(cust, it, c)])
        p_top, p_k = pc.most_common(1)[0] if pc else (None, 0)
        price = p_top if pc and p_k / sum(pc.values()) >= MIN_RATE and len(rs) >= 3 else None
        if r or price is not None:
            product_rules.append({"scope": "customer_product", "customer_no": cust, "product": it, "charge": c,
                                  "ratio": r, "price": price, "n": len(rs)})
    for (it, c), obs_ in item_charge.items():
        n_it = item_orders[it]
        if n_it < 3 or c in excluded:
            continue
        pres = len(obs_) / n_it
        kinds = Counter(k for _, k, _, _ in obs_)
        kind, kk = kinds.most_common(1)[0]
        if pres >= 0.9 and kind in ("same", "one") and kk / len(obs_) >= 0.8:
            last = max(obs_, key=lambda t: t[0])
            product_rules.append({"scope": "item_charge", "product": it, "charge": c, "presence": round(pres, 3), "n": n_it,
                                  "qty_kind": kind, "price": last[3]})
    for (sig, c), rs in size_ratio.items():
        r = _steady(rs)
        if r and len(rs) >= 5:
            p_top, p_k = size_price[(sig, c)].most_common(1)[0]
            product_rules.append({"scope": "size", "size": sig, "charge": c, "ratio": r, "n": len(rs),
                                  "presence": round(len(rs) / max(1, size_orders[sig]), 3),
                                  "price": p_top if p_k / len(rs) >= 0.8 else None,
                                  "dunnage": _CATEGORY.get(c) == "PALLET"})
    for (it, c), rs in glob_ratio.items():
        r = _steady(rs)
        if r and len(rs) >= 5:
            product_rules.append({"scope": "product", "product": it, "charge": c, "ratio": r, "n": len(rs)})
    for cust, charges in obs.items():
        n = orders[cust]
        if n < MIN_ORDERS:
            continue
        for c, xs in charges.items():
            rate = len(xs) / n
            if rate < MIN_RATE:
                continue
            rule = {"customer_no": cust, "charge": c, "orders": n, "rate": round(rate, 2), "updated_at": now}
            qs = Counter(round(x["q"], 4) for x in xs)
            q_top, q_k = qs.most_common(1)[0]
            ratio = _steady([x["q"] / x["pq"] for x in xs if x["pq"]])
            if q_k / len(xs) >= MIN_RATE and q_top > 0:
                rule.update(qty_mode="fixed", qty=q_top)
            elif ratio:
                rule.update(qty_mode="ratio", ratio=ratio)
            else:
                rule.update(qty_mode="per_product")    # resolved from product rules at draft time
            rule["integer"] = all(float(x["q"]).is_integer() for x in xs)
            opens = [x for x in xs if x["open"]]
            op = Counter(round(x["p"], 4) for x in opens)
            ps = Counter(round(x["p"], 4) for x in xs)
            pct = _steady([x["p"] * x["q"] / x["pv"] for x in xs if x["pv"] and x["q"]])
            if len(opens) >= 3 and op.most_common(1)[0][1] / len(opens) >= MIN_RATE:
                rule.update(price_mode="constant", price=op.most_common(1)[0][0], price_basis="entry price on open orders")
            elif ps.most_common(1)[0][1] / len(xs) >= MIN_RATE:
                rule.update(price_mode="constant", price=ps.most_common(1)[0][0], price_basis="same price on every order")
            elif pct and rule["qty_mode"] == "fixed" and rule["qty"] == 1:
                rule.update(price_mode="pct_of_products", pct=pct, price_basis=f"{pct:.1%} of the product value")
            elif c in _FREIGHT:
                rule.update(price_mode="po_freight", price_basis="PO freight line")
            elif rule["qty_mode"] == "per_product":
                rule.update(price_mode="per_product", price_basis="this customer's price for this product")
            else:
                continue
            rules.append(rule)
    await db.sales_charge_rules.delete_many({})
    await db.sales_charge_product_rules.delete_many({})
    if rules:
        await db.sales_charge_rules.insert_many(rules)
    if product_rules:
        await db.sales_charge_product_rules.insert_many(product_rules)
    await db.sales_charge_rules.create_index("customer_no")
    await db.sales_charge_product_rules.create_index([("product", 1), ("charge", 1)])
    await db.sales_charge_product_rules.create_index([("size", 1), ("charge", 1)])
    return {"rules": len(rules), "product_rules": len(product_rules), "usual": len(usual), "invoice_time_excluded": sorted(excluded)}


def po_freight(extracted_lines: List[Dict[str, Any]]) -> Optional[float]:
    total = 0.0
    for e in extracted_lines or []:
        if _FREIGHT_WORDS.search(str(e.get("description") or "")):
            v = num(e.get("total")) or ((num(e.get("unit_price")) or 0) * (num(e.get("quantity")) or 1))
            total += v or 0
    return round(total, 2) if total > 0 else None


async def charge_lines(db, customer_no: str, product_lines: List[Dict[str, Any]],
                       extracted_lines: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    prods = [l for l in product_lines if l.get("item")]
    pq = sum(float(l.get("quantity") or 0) for l in prods)
    pv = sum(float(l.get("quantity") or 0) * float(l.get("unit_price") or 0) for l in prods)
    freight = po_freight(extracted_lines)
    out = []
    async for r in db.sales_charge_rules.find({"customer_no": customer_no}, {"_id": 0}):
        if r["qty_mode"] == "fixed":
            qty = r["qty"]
        elif r["qty_mode"] == "ratio":
            qty = r["ratio"] * pq
        else:
            qty, known, prices = 0.0, True, set()
            for p in prods:
                cp = await db.sales_charge_product_rules.find_one(
                    {"scope": "customer_product", "customer_no": customer_no, "product": str(p["item"]).upper(), "charge": r["charge"]}, {"_id": 0})
                gp = await db.sales_charge_product_rules.find_one({"scope": "product", "product": str(p["item"]).upper(), "charge": r["charge"]}, {"_id": 0})
                ratio = (cp or {}).get("ratio") or (gp or {}).get("ratio")
                if not ratio and SIZE_FALLBACK:
                    await _load_item_desc(db)
                    sig = size_signature(p["item"], p.get("unit_of_measure") or "M")
                    sp = await db.sales_charge_product_rules.find_one({"scope": "size", "size": sig, "charge": r["charge"]}, {"_id": 0}) if sig else None
                    ratio = (sp or {}).get("ratio")
                if not ratio:
                    known = False
                    break
                qty += ratio * float(p["quantity"])
                if (cp or {}).get("price") is not None:
                    prices.add(cp["price"])
            if not known or qty <= 0:
                continue
            if r["price_mode"] == "per_product":
                if len(prices) != 1:
                    continue
                r = {**r, "price_mode": "constant", "price": prices.pop()}
        if r.get("integer"):
            qty = float(max(1, round(qty)))
        else:
            qty = round(qty, 4)
        if r["price_mode"] == "constant":
            price = r["price"]
        elif r["price_mode"] == "pct_of_products" and pv:
            price = round(r["pct"] * pv / qty, 2)
        elif r["price_mode"] == "po_freight" and freight is not None:
            price, qty = freight, 1.0
        elif r["price_mode"] == "po_freight" and FREIGHT_PLACEHOLDER:
            # No freight on the PO: the line inside sales enters on open
            # orders - 1 at 0, priced when it ships (501 of 760 open orders).
            price, qty = 0.0, 1.0
            r = {**r, "price_basis": "placeholder at 0, as inside sales enters it; priced when the order ships"}
        else:
            continue
        out.append({"item": r["charge"], "quantity": qty, "unit_price": price, "charge": True,
                    "how": f"on {int(r['rate'] * 100)}% of this customer's {r['orders']} BC orders"
                           + ("; quantity per product" if r["qty_mode"] in ("ratio", "per_product") else ""),
                    "price_source": r.get("price_basis")})
    if ITEM_CHARGES:
        # Charges that follow the item, whoever buys it: imported items carry
        # TARIFF (qty = product qty) / CUSTOMS on 90%+ of their orders (69
        # items always, 476 never).
        have = {o["item"] for o in out}
        for p in prods:
            async for ic in db.sales_charge_product_rules.find({"scope": "item_charge", "product": str(p["item"]).upper()}, {"_id": 0}):
                if ic["charge"] in have:
                    continue
                have.add(ic["charge"])
                q = float(p.get("quantity") or 0) if ic["qty_kind"] == "same" else 1.0
                out.append({"item": ic["charge"], "quantity": q, "unit_price": ic["price"], "charge": True,
                            "how": f"on {int(ic['presence'] * 100)}% of this item's {ic['n']} BC orders",
                            "price_source": "this item's latest price"})
    if DUNNAGE_BY_SIZE:
        # Dunnage comes with the container, whoever buys it: Ball 12oz cans
        # ship on Ball pallets / tier sheets / top frames on 80%+ of orders.
        have = {o["item"] for o in out}
        await _load_item_desc(db)
        need: Dict[str, float] = {}
        price_of: Dict[str, Any] = {}
        for p in prods:
            sig = size_signature(p["item"], p.get("unit_of_measure") or "M")
            if not sig:
                continue
            # Only for a new item (an established one has its own history,
            # and one size can come from two glass makers with their own
            # dunnage: O-I vs Ardagh 24oz jars).
            if await db.bc_sales_orders.count_documents({"lines.lineObjectNumber": p["item"]}, limit=3) >= 3:
                continue
            async for sp in db.sales_charge_product_rules.find({"scope": "size", "size": sig, "dunnage": True,
                                                                "presence": {"$gte": 0.9}, "n": {"$gte": 10}}, {"_id": 0}):
                if sp["charge"] in have or sp.get("price") is None:
                    continue
                need[sp["charge"]] = need.get(sp["charge"], 0) + sp["ratio"] * float(p.get("quantity") or 0)
                price_of[sp["charge"]] = sp["price"]
        for c, q in need.items():
            if q > 0:
                out.append({"item": c, "quantity": float(max(1, round(q))), "unit_price": price_of[c], "charge": True,
                            "how": "dunnage that ships with this container size (90%+ of its BC orders)",
                            "price_source": "usual price for this dunnage"})
    return out




async def to_complete(db, customer_no: str, drafted: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """Charges / dunnage this customer usually gets that the draft does not
    carry (the Hub could not size or price them reliably): the rep's list."""
    have = {str(l.get("item") or "").upper() for l in drafted}
    out = []
    async for u in db.sales_charge_usual.find({"customer_no": customer_no}, {"_id": 0}).sort([("rate", -1)]):
        if u["charge"] in have:
            continue
        it = await db.bc_reference_cache.find_one({"bc_entity_type": "item", "bc_document_no": u["charge"]}, {"_id": 0, "description": 1})
        out.append({"item": u["charge"], "description": (it or {}).get("description"), "rate": u["rate"], "orders": u["orders"],
                    "typical_qty": u["typical_qty"], "when": u.get("when")})
    return out[:6]
