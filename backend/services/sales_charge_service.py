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
# Whether a charge goes on the order follows the product as well as the
# customer: Berk PALLET is on 47% of their orders, but on ~all or ~none of
# a given product's. Learned per customer x product x charge from BC
# (presence predicted 66% -> 83% on 13,104 orders, earlier orders only).
CUST_PRODUCT_PRESENCE = True
CP_MIN_ORDERS = 5
# A customer's open orders are its orders as entered: Horseshoe FREIGHT on
# 98 of 99 open orders (swapped for WHSEFRT at invoicing, 30% overall);
# FRTSURCHARGE on 0 of 99 open, 361 of 1307 invoiced (added at invoicing).
OPEN_PRESENCE = True
OPEN_MIN_ORDERS = 10


async def _cp_vote(db, cust: str, prods: List[Dict[str, Any]], charge: str) -> Optional[bool]:
    """True: a product on the order carries this charge for this customer on
    80%+ of its orders. False: every product carries it on 20% or less.
    None: not known for every product."""
    if not prods:
        return None
    ps = []
    for p in prods:
        x = await db.sales_charge_product_rules.find_one({"scope": "cust_presence", "customer_no": cust, "product": str(p["item"]).upper(),
                                                          "charge": charge}, {"_id": 0, "presence": 1})
        if not x:
            return None
        ps.append(x["presence"])
    if any(v >= MIN_RATE for v in ps):
        return True
    if all(v <= 1 - MIN_RATE for v in ps):
        return False
    return None
DUNNAGE_BY_SIZE = True
ITEM_CHARGES = True
ITEM_RATIO = True
ITEM_RULES_INVOICED_ONLY = False   # replay switch: learn item charges from invoiced orders only
# An item's charge rule also weighs the orders it shares with other products.
# A charge line whose quantity is another product's quantity belongs to that
# product. Berk B02372R: 3 solo 2025 orders had TARIFF 1 + PALLET; its next 4
# orders (with J110CT, whose TARIFF matched J110CT's qty) had neither.
ITEM_MULTI_EVIDENCE = True
# Customer x product charge ratios learn from multi-product orders too (a
# charge line whose quantity is exactly one product's quantity is that
# product's), and when the customer changed how it bills the charge the
# latest steady run (3+ orders) is the ratio. Berk TARIFF: 1 per order in
# 2025, then TARIFF qty = J110CT qty on its last 5 lines.
MULTI_CP_RATIO = True
# An item's charge as of its latest orders: TARIFF started on imported items
# in 2026 (29 of their 41 latest orders, 25% of the product's price), so the
# all-history 90% test never fires. The item's latest RECENT_N orders decide,
# and a steady charge price / product price share prices it.
RECENT_ITEM_CHARGES = True
RECENT_N = 5


UNIT_EACH = True
# Customer charge rules learned from the customer's latest orders, not all
# history: Horseshoe's DUNNAGEMGMT is on 98 of 101 open orders but 46% of
# 1,331 invoiced ones, and its FREIGHT at 1970 on 98 open orders - an
# all-history rate (50%) never reached the 80% bar. 0 = all history.
RECENT_ORDERS = 40
# Size a ratio charge from each item's own learned ratio when every product
# has one (Giovanni: one O-I pallet per 2,821 24oz jars, per 4,725 of
# C-500733); the customer-wide ratio drafted 32 pallets where BC had 19.
ITEM_RATIO_FIRST = True


def _each(q: float, uom: Any) -> float:
    """Quantity in single units: Giovanni's 24oz jar was ordered by the M
    (thousand) for years and by the each since, so pallets per M (2.8) and
    per each (1/2,821) looked like no steady ratio at all."""
    return q * 1000 if UNIT_EACH and str(uom or "").upper() == "M" else q


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


CUSTOMER_ENTRY_TIME = True


async def customer_entry_charges(db, excluded: set) -> set:
    """(customer, charge) pairs where a charge most customers get at
    invoicing is on this customer's orders from entry: O-I pallets / tier
    sheets / top frames are on 7% of all open orders and 16% of invoiced
    ones, but on every open Giovanni order (one pallet per 2,821 jars)."""
    if not CUSTOMER_ENTRY_TIME or not excluded:
        return set()
    open_n, inv_n, tot = Counter(), Counter(), Counter()
    async for o in db.bc_sales_orders.find({"status": {"$in": ["open", "invoiced"]}}, {"_id": 0, "status": 1, "customer_no": 1, "lines": 1}):
        ls = _lines(o)
        if not any(is_product(l["lineObjectNumber"]) for l in ls):
            continue
        cust = o.get("customer_no")
        tot[(cust, o["status"])] += 1
        for c in {str(l["lineObjectNumber"]).upper() for l in ls} & excluded:
            (open_n if o["status"] == "open" else inv_n)[(cust, c)] += 1
    return {(cust, c) for (cust, c), k in open_n.items()
            if tot[(cust, "open")] >= 5 and k / tot[(cust, "open")] >= MIN_RATE
            and (not inv_n[(cust, c)] or (k / tot[(cust, "open")]) / (inv_n[(cust, c)] / tot[(cust, "invoiced")]) >= 0.6)}


async def learn(db) -> Dict[str, Any]:
    await load_item_categories(db)
    excluded = await invoice_time_charges(db)
    entry = await customer_entry_charges(db, excluded)
    obs = defaultdict(lambda: defaultdict(list))      # cust -> charge -> [dict]
    prod_ratio = defaultdict(list)                    # (cust, product, charge) -> [ratio]
    prod_seq = defaultdict(list)                      # (cust, product, charge) -> [(seq, ratio, price)]
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
    multi_orders = Counter()                          # item -> multi-product orders with it
    item_hist = defaultdict(list)                     # item -> [(seq, {charge: (kind, qty, price, share)})]
    multi_has = Counter()                             # (item, charge) -> of those, charge possibly its
    cust_seqs = defaultdict(list)                     # cust -> order sequence numbers
    cp_orders = Counter()                             # (cust, product) -> orders
    open_orders = Counter()                           # cust -> open orders
    readbacks = Counter()                             # cust -> sandbox readbacks counted as orders
    cp_charge = Counter()                             # (cust, product, charge) -> orders with the charge
    reviewed = 10 ** 9                                # sandbox drafts a rep completed: newest
    async for o in db.bc_sales_orders.find({}, {"_id": 0, "customer_no": 1, "lines": 1, "status": 1, "order_no": 1}):
        ls = _lines(o)
        prods = [l for l in ls if is_product(l["lineObjectNumber"]) and float(l.get("quantity") or 0) > 0]
        if not prods:
            continue
        if RECENT_ITEM_CHARGES and not (ITEM_RULES_INVOICED_ONLY and o.get("status") == "open"):
            by_it = defaultdict(list)
            for l in prods:
                by_it[str(l["lineObjectNumber"]).upper()].append(l)
            qs_of = {i: {round(float(x["quantity"]), 6) for x in pl} for i, pl in by_it.items()}
            for it_r, pls in by_it.items():
                got = {}
                for l in ls:
                    c = str(l["lineObjectNumber"]).upper()
                    if is_product(c) or float(l.get("quantity") or 0) <= 0:
                        continue
                    q = round(float(l["quantity"]), 6)
                    owners = {i for i, qs in qs_of.items() if q in qs}
                    if owners and it_r not in owners:
                        continue
                    kind = "same" if q in qs_of[it_r] else ("one" if q == 1 else "other")
                    pr = float(l.get("unitPrice") or 0)
                    base = float(pls[0].get("unitPrice") or 0)
                    if c not in got or pr > got[c][2]:
                        got[c] = (kind, q, pr, pr / base if base and kind == "same" else None)
                item_hist[it_r].append((_order_seq(o.get("order_no")), got))
        if (ITEM_MULTI_EVIDENCE and len({str(l["lineObjectNumber"]).upper() for l in prods}) > 1
                and not (ITEM_RULES_INVOICED_ONLY and o.get("status") == "open")):
            pq_of = defaultdict(set)
            for l in prods:
                pq_of[str(l["lineObjectNumber"]).upper()].add(round(float(l["quantity"]), 6))
            for it_m in pq_of:
                multi_orders[it_m] += 1
                mine = set()
                for l in ls:
                    c = str(l["lineObjectNumber"]).upper()
                    if is_product(c) or float(l.get("quantity") or 0) <= 0:
                        continue
                    q = round(float(l["quantity"]), 6)
                    owners = {i for i, qs in pq_of.items() if q in qs}
                    if not owners or it_m in owners:
                        mine.add(c)
                for c in mine:
                    multi_has[(it_m, c)] += 1
        if len(prods) == 1 and not (ITEM_RULES_INVOICED_ONLY and o.get("status") == "open"):
            it1 = str(prods[0]["lineObjectNumber"]).upper()
            item_orders[it1] += 1
            pq1 = float(prods[0]["quantity"])
            for l in ls:
                c = str(l["lineObjectNumber"]).upper()
                if not is_product(c) and float(l.get("quantity") or 0) > 0:
                    q = float(l["quantity"])
                    kind = "same" if abs(q - pq1) < 1e-6 else ("one" if q == 1 else "other")
                    item_charge[(it1, c)].append((_order_seq(o.get("order_no")), kind, q, float(l.get("unitPrice") or 0),
                                                 q / _each(pq1, prods[0].get("unitOfMeasureCode")) if pq1 else 0))
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
        seq = _order_seq(o.get("order_no"))
        cust_seqs[cust].append(seq)
        if o.get("status") == "open":
            open_orders[cust] += 1
        its = {str(l["lineObjectNumber"]).upper() for l in prods}
        for it in its:
            cp_orders[(cust, it)] += 1
        pq = sum(_each(float(l["quantity"]), l.get("unitOfMeasureCode")) for l in prods)
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
            if c in excluded and (cust, c) not in entry:
                continue
            obs[cust][c].append({"q": a["q"], "p": a["p"], "pq": pq, "pv": pv, "open": o.get("status") == "open", "seq": seq})
            for it in its:
                cp_charge[(cust, it, c)] += 1
            if len(prods) == 1 and a["q"] > 0:
                it = str(prods[0]["lineObjectNumber"]).upper()
                prod_ratio[(cust, it, c)].append(a["q"] / _each(float(prods[0]["quantity"]), prods[0].get("unitOfMeasureCode")))
                prod_price[(cust, it, c)].append(round(a["p"], 4))
                prod_seq[(cust, it, c)].append((seq, prod_ratio[(cust, it, c)][-1], round(a["p"], 4)))
            elif MULTI_CP_RATIO and len(its) > 1:
                owned = set()
                for l in ls:
                    if str(l["lineObjectNumber"]).upper() == c and float(l.get("quantity") or 0) > 0:
                        own_ = {str(p["lineObjectNumber"]).upper() for p in prods if abs(float(p["quantity"]) - float(l["quantity"])) < 1e-6}
                        owned |= own_ if own_ else set(its)
                for it0 in its - owned:
                    prod_seq[(cust, it0, c)].append((seq, 0.0, None))     # the charge was another product's
                for l in ls:
                    if str(l["lineObjectNumber"]).upper() != c or float(l.get("quantity") or 0) <= 0:
                        continue
                    q = float(l["quantity"])
                    own = [p for p in prods if abs(float(p["quantity"]) - q) < 1e-6]
                    if len({str(p["lineObjectNumber"]).upper() for p in own}) != 1:
                        continue
                    it = str(own[0]["lineObjectNumber"]).upper()
                    r_ = q / _each(q, own[0].get("unitOfMeasureCode"))
                    prod_ratio[(cust, it, c)].append(r_)
                    prod_price[(cust, it, c)].append(round(float(l.get("unitPrice") or 0), 4))
                    prod_seq[(cust, it, c)].append((seq, r_, round(float(l.get("unitPrice") or 0), 4)))
                glob_ratio[(it, c)].append(a["q"] / _each(float(prods[0]["quantity"]), prods[0].get("unitOfMeasureCode")))
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
        readbacks[cust] += 1
        reviewed += 1
        pq = sum(_each(float(l["quantity"]), l.get("unitOfMeasureCode")) for l in prods)
        pv = sum(float(l["quantity"]) * float(l.get("unitPrice") or 0) for l in prods)
        for l in ls:
            c = str(l["lineObjectNumber"]).upper()
            if not is_product(c) and (c not in excluded or (cust, c) in entry):
                obs[cust][c].append({"q": float(l.get("quantity") or 0), "p": float(l.get("unitPrice") or 0), "pq": pq, "pv": pv, "open": True,
                                     "seq": reviewed, "readback": True})
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
                              "typical_qty": qs[len(qs) // 2], "when": "shipping / invoicing" if c in excluded and (cust, c) not in entry else "order entry",
                              "updated_at": now})
    await db.sales_charge_usual.delete_many({})
    if usual:
        await db.sales_charge_usual.insert_many(usual)
    await db.sales_charge_usual.create_index("customer_no")
    rules, product_rules = [], []
    for key in set(prod_ratio) | set(prod_seq):
        cust, it, c = key
        rs = prod_ratio[key]
        ss0 = sorted(prod_seq[key], key=lambda t: t[0])
        if MULTI_CP_RATIO and len(ss0) >= 3 and all(t[1] == 0 for t in ss0[-3:]):
            product_rules.append({"scope": "customer_product", "customer_no": cust, "product": it, "charge": c,
                                  "ratio": 0.0, "zero": True, "price": None, "n": len(ss0)})
            continue
        r = _steady(rs)
        recent_price = None
        if r is None and MULTI_CP_RATIO and len(prod_seq[(cust, it, c)]) >= 3:
            ss = sorted(prod_seq[(cust, it, c)], key=lambda t: t[0])
            for k in range(len(ss), 2, -1):
                r = _steady([t[1] for t in ss[-k:]])
                if r:
                    rs = [t[1] for t in ss[-k:]]
                    prod_price[(cust, it, c)] = [t[2] for t in ss[-k:]]
                    recent_price = ss[-1][2]
                    break
        pc = Counter(prod_price[(cust, it, c)])
        p_top, p_k = pc.most_common(1)[0] if pc else (None, 0)
        price = p_top if pc and p_k / sum(pc.values()) >= MIN_RATE and len(rs) >= 3 else None
        if price is None and recent_price is not None:
            price = recent_price        # a changed pattern: its latest price
        if r or price is not None:
            product_rules.append({"scope": "customer_product", "customer_no": cust, "product": it, "charge": c,
                                  "ratio": r, "price": price, "n": len(rs)})
    for (it, c), obs_ in item_charge.items():
        n_it = item_orders[it]
        if n_it < 3 or c in excluded:
            continue
        pres = len(obs_) / n_it
        if ITEM_MULTI_EVIDENCE and multi_orders[it]:
            pres = (len(obs_) + multi_has[(it, c)]) / (n_it + multi_orders[it])
        kinds = Counter(t[1] for t in obs_)
        kind, kk = kinds.most_common(1)[0]
        last = max(obs_, key=lambda t: t[0])
        if pres < 0.9:
            continue
        if kind in ("same", "one") and kk / len(obs_) >= 0.8:
            product_rules.append({"scope": "item_charge", "product": it, "charge": c, "presence": round(pres, 3), "n": n_it,
                                  "qty_kind": kind, "price": last[3]})
        elif ITEM_RATIO:
            # Dunnage scales with the order: pallets per M of this item.
            r = _steady([t[4] for t in obs_])
            if r:
                product_rules.append({"scope": "item_charge", "product": it, "charge": c, "presence": round(pres, 3), "n": n_it,
                                      "qty_kind": "ratio", "ratio": r, "price": last[3]})
    if RECENT_ITEM_CHARGES:
        have_ic = {(r["product"], r["charge"]) for r in product_rules if r.get("scope") == "item_charge"}
        for it, hist in item_hist.items():
            if len(hist) < 3:
                continue
            last = sorted(hist, key=lambda h: h[0])[-RECENT_N:]
            for c in set().union(*[set(h[1]) for h in last]):
                if c in excluded or (it, c) in have_ic:
                    continue
                obs_r = [h[1][c] for h in last if c in h[1]]
                pres = len(obs_r) / len(last)
                if pres < 0.8 or len(obs_r) < 3:
                    continue
                kind, kk = Counter(t[0] for t in obs_r).most_common(1)[0]
                if kind != "same" or kk / len(obs_r) < 0.8:
                    continue          # order-level charges (freight, fuel) are not the item's
                share = _steady([t[3] for t in obs_r if t[3]]) if kind == "same" else None
                if share and abs(round(share * 400) / 400 - share) < 0.0005:
                    share = round(share * 400) / 400     # BC prices are rounded; staff set a whole share (25%)
                product_rules.append({"scope": "item_charge", "product": it, "charge": c, "presence": round(pres, 3),
                                      "n": len(last), "qty_kind": kind, "price": obs_r[-1][2], "recent": True,
                                      "price_share": share})
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
    cond = set()
    if CUST_PRODUCT_PRESENCE:
        for (cust, it), n_cp in cp_orders.items():
            if n_cp < CP_MIN_ORDERS:
                continue
            for c in (obs.get(cust) or {}):
                pres = cp_charge.get((cust, it, c), 0) / n_cp
                if pres >= MIN_RATE or pres <= 1 - MIN_RATE:
                    product_rules.append({"scope": "cust_presence", "customer_no": cust, "product": it, "charge": c,
                                          "presence": round(pres, 3), "n": n_cp})
                    if pres >= MIN_RATE:
                        cond.add((cust, c))
    for cust, charges in obs.items():
        n = orders[cust]
        if n < MIN_ORDERS:
            continue
        # Whether the charge is on the customer's orders today: its latest
        # Production orders. How it is sized and priced: all of them.
        recent = set(sorted(cust_seqs[cust])[-RECENT_ORDERS:]) if RECENT_ORDERS and len(cust_seqs[cust]) > RECENT_ORDERS else None
        for c, xs in charges.items():
            rate = len(xs) / n
            if recent is not None:
                rate = max(rate, sum(1 for x in xs if x["seq"] in recent) / len(recent))
            entry_rate = None
            if OPEN_PRESENCE and open_orders[cust] >= OPEN_MIN_ORDERS:
                # BC open orders only: a readback can hold the Hub's own drafted
                # charge (Horseshoe FRTSURCHARGE on 8 readbacks, all drafted).
                k_open = sum(1 for x in xs if x["open"] and not x.get("readback"))
                entry_rate = min(1.0, k_open / open_orders[cust])
                closed = n - open_orders[cust] - readbacks[cust]
                later_rate = sum(1 for x in xs if not x["open"]) / closed if closed > 0 else 0.0
                if entry_rate <= 1 - MIN_RATE and later_rate >= 3 * entry_rate + 0.05:
                    continue      # this customer gets it after entry (shipping / invoicing)
                rate = max(rate, entry_rate)
            if rate < MIN_RATE and (cust, c) not in cond:
                continue
            latest = recent is not None and rate > len(xs) / n
            rule = {"customer_no": cust, "charge": c, "orders": len(recent) if latest else n, "rate": round(rate, 2), "updated_at": now,
                    "latest": latest, "conditional": rate < MIN_RATE}
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
    return {"rules": len(rules), "product_rules": len(product_rules), "usual": len(usual), "invoice_time_excluded": sorted(excluded),
            "entry_time_for_customer": sorted(f"{a}:{b}" for a, b in entry)}


def po_freight(extracted_lines: List[Dict[str, Any]], product_desc: frozenset = frozenset()) -> Optional[float]:
    total = 0.0
    for e in extracted_lines or []:
        if str(e.get("description") or "")[:120] in product_desc:
            continue    # a product line ("OUAF BOTTLE; requested delivery date 2026-12-18")
        if _FREIGHT_WORDS.search(str(e.get("description") or "")):
            v = num(e.get("total")) or ((num(e.get("unit_price")) or 0) * (num(e.get("quantity")) or 1))
            total += v or 0
    return round(total, 2) if total > 0 else None


_KEPT: Dict[tuple, tuple] = {}
_KEPT_AT = {"t": 0.0}
FREIGHT_KEPT_LEARNED = True


async def po_freight_kept(db, customer_no: str, charge: str) -> tuple:
    """(kept, entered otherwise, the usual other entry) on this customer's
    linked POs that show freight: did inside sales put the PO's freight on
    the BC order? Hearthside's POs say 675; the order says 0 on 12 of 14,
    priced when it ships."""
    import time
    if time.time() - _KEPT_AT["t"] > 3600:
        _KEPT.clear()
        _KEPT_AT["t"] = time.time()
    key = (customer_no, charge)
    if key in _KEPT:
        return _KEPT[key]
    kept, others, seen = 0, Counter(), set()
    async for d in db.hub_documents.find({"sales_link.role": "customer_po", "sales_link.bc_customer_no": customer_no, "sales_link.order_no": {"$ne": None}},
                                         {"_id": 0, "sales_link.order_no": 1, "extracted_fields.line_items": 1}):
        on = d["sales_link"]["order_no"]
        if on in seen:
            continue
        seen.add(on)
        el = (d.get("extracted_fields") or {}).get("line_items") or []
        # Only a line that is freight alone, not a product line naming a delivery date.
        f = po_freight([e for e in el if len(str(e.get("description") or "")) <= 40])
        if f is None:
            continue
        o = await db.bc_sales_orders.find_one({"order_no": on}, {"_id": 0, "lines": 1})
        vs = [float(l.get("unitPrice") or 0) * float(l.get("quantity") or 0) for l in (o or {}).get("lines") or []
              if str(l.get("lineObjectNumber") or "").upper() == charge]
        if not vs:
            continue
        v = round(sum(vs), 2)
        if abs(v - f) < 0.01:
            kept += 1
        else:
            others[v] += 1
    n = sum(others.values())
    top = others.most_common(1)[0] if others else None
    _KEPT[key] = (kept, n, top[0] if top and top[1] / n >= MIN_RATE else None)
    return _KEPT[key]


async def charge_lines(db, customer_no: str, product_lines: List[Dict[str, Any]],
                       extracted_lines: List[Dict[str, Any]], all_products: Optional[List[Dict[str, Any]]] = None) -> List[Dict[str, Any]]:
    prods = [l for l in product_lines if l.get("item")]
    pq = sum(_each(float(l.get("quantity") or 0), l.get("unit_of_measure")) for l in prods)
    pv = sum(float(l.get("quantity") or 0) * float(l.get("unit_price") or 0) for l in prods)
    pdesc = frozenset(str(l.get("po_description") or "")[:120] for l in (all_products or prods) if l.get("po_description"))
    freight = po_freight(extracted_lines, pdesc)
    out = []
    async for r in db.sales_charge_rules.find({"customer_no": customer_no}, {"_id": 0}):
        vote = await _cp_vote(db, customer_no, prods, r["charge"]) if CUST_PRODUCT_PRESENCE else None
        if r.get("conditional") and vote is not True:
            continue          # an occasional charge, not one this product carries
        if vote is False:
            continue          # a usual charge this product does not carry
        if r["qty_mode"] == "fixed":
            qty = r["qty"]
        elif r["qty_mode"] == "ratio":
            qty = r["ratio"] * pq
            if ITEM_RATIO_FIRST and prods:
                q_items = 0.0
                for p in prods:
                    cp = await db.sales_charge_product_rules.find_one(
                        {"scope": "customer_product", "customer_no": customer_no, "product": str(p["item"]).upper(), "charge": r["charge"]},
                        {"_id": 0, "ratio": 1})
                    if (cp or {}).get("zero"):
                        continue
                    if not (cp or {}).get("ratio"):
                        q_items = None
                        break
                    q_items += cp["ratio"] * _each(float(p.get("quantity") or 0), p.get("unit_of_measure"))
                if q_items:
                    qty = q_items
        else:
            qty, known, prices = 0.0, True, set()
            for p in prods:
                cp = await db.sales_charge_product_rules.find_one(
                    {"scope": "customer_product", "customer_no": customer_no, "product": str(p["item"]).upper(), "charge": r["charge"]}, {"_id": 0})
                if (cp or {}).get("zero"):
                    continue          # this customer's charge goes on its other products
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
                qty += ratio * _each(float(p["quantity"]), p.get("unit_of_measure"))
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
            kept, other, entry = await po_freight_kept(db, customer_no, r["charge"]) if FREIGHT_KEPT_LEARNED else (0, 0, None)
            if entry is not None and other >= 3 and other > 2 * kept:
                # Inside sales does not enter this customer's PO freight.
                price = entry
                r = {**r, "price_basis": f"{entry:g}, as inside sales entered it on {other} of {kept + other} of this customer's POs "
                                        f"that showed freight (PO shows {freight:g})"}
        elif r["price_mode"] == "po_freight" and FREIGHT_PLACEHOLDER:
            # No freight on the PO: the line inside sales enters on open
            # orders - 1 at 0, priced when it ships (501 of 760 open orders).
            price, qty = 0.0, 1.0
            r = {**r, "price_basis": "placeholder at 0, as inside sales enters it; priced when the order ships"}
        else:
            continue
        out.append({"item": r["charge"], "quantity": qty, "unit_price": price, "charge": True,
                    "how": ("on 80%+ of this customer's BC orders for this product" if r.get("conditional") else
                            f"on {int(r['rate'] * 100)}% of this customer's {'latest ' if r.get('latest') else ''}{r['orders']} BC orders")
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
                if ic.get("recent"):
                    cpv = await db.sales_charge_product_rules.find_one(
                        {"scope": "cust_presence", "customer_no": customer_no, "product": str(p["item"]).upper(), "charge": ic["charge"]},
                        {"_id": 0, "presence": 1})
                    if cpv and cpv.get("presence", 1) <= 0.2:
                        continue      # this customer's orders for it do not carry the charge
                have.add(ic["charge"])
                if ic["qty_kind"] == "ratio":
                    q = float(max(1, round(ic["ratio"] * _each(float(p.get("quantity") or 0), p.get("unit_of_measure")))))
                else:
                    q = float(p.get("quantity") or 0) if ic["qty_kind"] == "same" else 1.0
                price, src = ic["price"], "this item's latest price"
                if ic.get("price_share") and float(p.get("unit_price") or 0) > 0:
                    price = round(ic["price_share"] * float(p["unit_price"]), 4)
                    src = f"{ic['price_share'] * 100:g}% of the product's price, as on this item's latest BC orders"
                out.append({"item": ic["charge"], "quantity": q, "unit_price": price, "charge": True,
                            "how": (f"on {int(ic['presence'] * 100)}% of this item's latest {ic['n']} BC orders" if ic.get("recent")
                                    else f"on {int(ic['presence'] * 100)}% of this item's {ic['n']} BC orders"),
                            "price_source": src})
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
