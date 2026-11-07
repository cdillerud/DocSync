"""Bulk orders: one BC sales order per customer PO line, the way inside
sales enters customers that split (Horseshoe: P0030203-1 ... -20, one can
line each, entered by hand one at a time - 64 POs became 1,322 orders).

The rep reviews one screen per PO (orders, item, quantity, ship dates),
confirms the price once, and the Hub creates every order. SANDBOX ONLY
(PRE): the same guards as sales drafting (refusal(), verify_sandbox,
never a Production environment). Production needs Chad's explicit OK and
is not built.

Template, learned, per item: the customer's latest open BC order carrying
the item (as entered when the Hub saw it entered). Inside sales copies the
previous order; so does the Hub: its charge lines (DUNNAGEMGMT, FREIGHT
1970), its comment lines (pack, pallet size, graphics number) and its price
as the default. The PO gives the quantity, the line numbers and the
delivery dates; the ship date defaults to the delivery date less this
customer's usual lead (Horseshoe 1-2 days on 55 of 61 lines) and the rep
can change it.
"""
import logging
import re
from collections import Counter
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_DELIVERY = re.compile(r"delivery (\d{4}-\d{2}-\d{2})", re.I)


def _lines_of(o: Dict[str, Any]) -> List[Dict[str, Any]]:
    return (o.get("entered_lines") or None) or o.get("lines") or []


async def template(db, customer_no: str, item: str, before: Optional[str] = None) -> Optional[Dict[str, Any]]:
    """The customer's latest open order of this item (else latest of any
    status) with the item as its only product."""
    from services.sales_item_xref_service import is_product, _order_seq, load_item_categories
    await load_item_categories(db)
    best = None
    async for o in db.bc_sales_orders.find({"customer_no": customer_no, "lines.lineObjectNumber": item},
                                           {"_id": 0, "order_no": 1, "status": 1, "lines": 1, "entered_lines": 1, "external_doc_no": 1}):
        if before and _order_seq(o["order_no"]) >= _order_seq(before):
            continue
        ls = _lines_of(o)
        prods = [l for l in ls if l.get("lineType") == "Item" and is_product(str(l.get("lineObjectNumber") or ""))]
        if len(prods) != 1 or str(prods[0].get("lineObjectNumber")).upper() != item.upper():
            continue
        # Open orders first: an order first seen invoiced carries what was
        # added at invoicing (WHSEFRT 2550 on 121428), not what was entered.
        key = (o.get("status") == "open", _order_seq(o["order_no"]))
        if best is None or key > best[0]:
            best = (key, o, ls, prods[0])
    if not best:
        return None
    _, o, ls, prod = best
    # Charges this customer gets at shipping / invoicing are not entered.
    later = {u["charge"] async for u in db.sales_charge_usual.find({"customer_no": customer_no, "when": "shipping / invoicing"},
                                                                   {"_id": 0, "charge": 1})}
    charges = [{"item": l["lineObjectNumber"], "quantity": float(l.get("quantity") or 0), "unit_price": float(l.get("unitPrice") or 0),
                "unit_of_measure": l.get("unitOfMeasureCode") or None, "description": l.get("description")}
               for l in ls if l.get("lineType") == "Item" and l is not prod and l.get("lineObjectNumber")
               and str(l["lineObjectNumber"]).upper() not in later]
    charges_from = "template order"
    entered = await _entered_charges(db, customer_no, item) if o.get("status") != "open" else None
    if entered:
        # No open order of this item: the charges this customer's open orders
        # are entered with (Horseshoe 98 of 98: DUNNAGEMGMT 0 + FREIGHT 1970).
        # The item's invoiced orders carry FRTSURCHARGE 220, added at invoicing.
        charges, charges_from = entered["charges"], f"as entered on {entered['n']} of this customer's {entered['of']} open orders"
    elif o.get("status") != "open":
        # An invoiced order carries what was added at invoicing (Horseshoe
        # FRTSURCHARGE 220 for the FREIGHT 1970 entered): use the charges
        # the Hub learned this customer's orders are entered with.
        from services.sales_charge_service import charge_lines
        learned = await charge_lines(db, customer_no, [{"item": item, "quantity": float(prod.get("quantity") or 0),
                                                        "unit_of_measure": prod.get("unitOfMeasureCode"),
                                                        "unit_price": float(prod.get("unitPrice") or 0)}], [])
        if learned:
            charges = [{"item": c["item"], "quantity": float(c["quantity"]), "unit_price": float(c["unit_price"] or 0),
                        "unit_of_measure": None, "description": None} for c in learned]
            charges_from = "learned entry charges (template order is invoiced)"
    comments = [str(l.get("description") or "") for l in ls if l.get("lineType") == "Comment" and str(l.get("description") or "").strip()]
    return {"order_no": o["order_no"], "external_doc_no": o.get("external_doc_no"), "price": float(prod.get("unitPrice") or 0),
            "charges_from": charges_from,
            "unit_of_measure": prod.get("unitOfMeasureCode"), "quantity": float(prod.get("quantity") or 0),
            "charges": charges, "comments": comments}


async def _entered_charges(db, customer_no: str, item: str) -> Optional[Dict[str, Any]]:
    """The charge lines this customer's open (as entered) one-product orders
    carry, when 80%+ of them (5+) carry the same set - for an item whose own
    orders are all invoiced, and only when those invoiced orders end up with
    the charges the open items' invoiced orders end up with (6074456:
    DUNNAGEMGMT + WHSEFRT + FRTSURCHARGE, like 6069966; not the 6072005
    ends, invoiced with WHSEFRT 1695 alone)."""
    from services.sales_item_xref_service import is_product, _order_seq
    sets, open_items = Counter(), set()
    inv_sets = {}                                        # product -> [(seq, invoiced charge-item set)]

    def split(o):
        its = [l for l in _lines_of(o) if l.get("lineType") == "Item" and l.get("lineObjectNumber")]
        prods = [l for l in its if is_product(str(l["lineObjectNumber"]))]
        return (str(prods[0]["lineObjectNumber"]).upper() if len(prods) == 1 else None), [l for l in its if l not in prods]

    async for o in db.bc_sales_orders.find({"customer_no": customer_no}, {"_id": 0, "order_no": 1, "status": 1, "lines": 1, "entered_lines": 1}):
        p, ch = split(o)
        if not p:
            continue
        if o.get("status") == "open":
            open_items.add(p)
            sets[tuple(sorted((str(l["lineObjectNumber"]).upper(), float(l.get("quantity") or 0), round(float(l.get("unitPrice") or 0), 4),
                               l.get("unitOfMeasureCode") or None) for l in ch))] += 1
        else:
            inv_sets.setdefault(p, []).append((_order_seq(o.get("order_no")), frozenset(str(l["lineObjectNumber"]).upper() for l in ch)))
    n_all = sum(sets.values())
    if n_all < 5 or not inv_sets.get(item.upper()):
        return None
    # As of now: the item's latest invoiced order ends up with charges that
    # 2+ of the latest 40 invoiced orders of the open items end up with
    # (invoicing varies: FUELSUR or FRTSURCHARGE 220, WHSEFRT 1800-2550).
    mine = max(inv_sets[item.upper()], key=lambda t: t[0])[1]
    recent = sorted((t for p in open_items for t in inv_sets.get(p) or []), key=lambda t: t[0])[-40:]
    if sum(1 for t in recent if t[1] == mine) < 2:
        return None
    top, n = sets.most_common(1)[0]
    if n / n_all < 0.8:
        return None
    return {"n": n, "of": n_all, "charges": [{"item": it, "quantity": q, "unit_price": p, "unit_of_measure": u, "description": None} for it, q, p, u in top]}


async def lead_days(db, customer_no: str) -> Optional[int]:
    """Usual days between a PO line's delivery date and the BC order's
    shipment date for this customer (most common, >= 5 lines)."""
    c = Counter()
    async for d in db.hub_documents.find({"sales_link.role": "customer_po", "sales_link.bc_customer_no": customer_no,
                                          "extracted_fields.line_items.1": {"$exists": True}},
                                         {"_id": 0, "sales_link.customer_po": 1, "extracted_fields.line_items": 1}):
        pos = [str(p).upper() for p in d["sales_link"].get("customer_po") or [] if re.match(r"^[A-Z]", str(p))]
        if not pos:
            continue
        base = max(pos, key=len)
        for i, e in enumerate(d["extracted_fields"]["line_items"], 1):
            m = _DELIVERY.search(str(e.get("description") or ""))
            if not m:
                continue
            o = await db.bc_sales_orders.find_one({"customer_no": customer_no, "external_doc_no": {"$regex": "^" + re.escape(base) + f"-{i}" + r"(\s*/|$)"}},
                                                  {"_id": 0, "lines": 1, "entered_lines": 1})
            sd = next((str(l.get("shipmentDate")) for l in _lines_of(o or {}) if l.get("lineType") == "Item"
                       and str(l.get("shipmentDate") or "")[:4] not in ("", "0001")), None)
            if sd:
                days = (date.fromisoformat(m.group(1)) - date.fromisoformat(sd[:10])).days
                if 0 <= days <= 14:
                    c[days] += 1
    if sum(c.values()) < 5:
        return None
    return c.most_common(1)[0][0]


async def trucks_per_day(db, customer_no: str) -> Optional[int]:
    """How many of one split PO's orders inside sales ships on the same day
    (Horseshoe: 3 a day from two days before the first delivery, on 3 of 5
    POs; 4 on one). The most common count over the latest split POs."""
    groups = Counter()
    async for o in db.bc_sales_orders.find({"customer_no": customer_no, "external_doc_no": {"$regex": r"^[A-Z0-9]+-\d+$"}},
                                           {"_id": 0, "order_no": 1, "external_doc_no": 1, "lines": 1, "entered_lines": 1}).sort([("order_no", -1)]).limit(300):
        sd = next((str(l.get("shipmentDate"))[:10] for l in _lines_of(o) if l.get("lineType") == "Item"
                   and str(l.get("shipmentDate") or "")[:4] not in ("", "0001")), None)
        if sd:
            groups[(o["external_doc_no"].rsplit("-", 1)[0], sd)] += 1
    per = Counter(n for (_, _), n in groups.items())
    if sum(per.values()) < 5:
        return None
    return per.most_common(1)[0][0]


async def plan(db, doc_id: str, before: Optional[str] = None) -> Dict[str, Any]:
    """before: an order number; only orders entered before it are used
    (replays against what inside sales entered)."""
    from services.sales_item_xref_service import resolve_lines, _charge_text
    from services.sales_draft_service import splits_per_line, _split_base
    d = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "file_content_b64": 0})
    if not d:
        return {"error": "Document not found"}
    sl = d.get("sales_link") or {}
    cust = sl.get("bc_customer_no")
    if not cust or not sl.get("customer_po"):
        return {"error": "No customer or customer PO on this document"}
    if not await splits_per_line(db, cust):
        return {"error": "This customer's POs are not entered as one BC order per PO line"}
    po_text = str((d.get("extracted_fields") or {}).get("po_number") or sl["customer_po"][0])
    base = _split_base(sl, po_text)
    el = [e for e in (d.get("extracted_fields") or {}).get("line_items") or [] if not _charge_text(e)]
    if not el:
        return {"error": "No PO lines read from the document"}
    res = await resolve_lines(db, cust, el, before_order=before)
    lead = await lead_days(db, cust)
    per_day = await trucks_per_day(db, cust)
    orders, templates, problems = [], {}, []
    first_delivery = min((m.group(1) for e in el for m in [_DELIVERY.search(str(e.get("description") or ""))] if m), default=None)
    start = (date.fromisoformat(first_delivery) - timedelta(days=lead)).isoformat() if first_delivery and lead is not None else None
    for n, (e, r) in enumerate(zip(el, res), 1):
        item = r.get("item")
        if not item:
            problems.append(f"line {n}: no Gamer item for \"{str(e.get('description') or '')[:60]}\"")
            continue
        if item not in templates:
            templates[item] = await template(db, cust, item, before)
        t = templates[item]
        m = _DELIVERY.search(str(e.get("description") or ""))
        delivery = m.group(1) if m else None
        if start and per_day:
            # Spread like inside sales: per_day trucks a day from the start date.
            ship = (date.fromisoformat(start) + timedelta(days=(n - 1) // per_day)).isoformat()
        else:
            ship = (date.fromisoformat(delivery) - timedelta(days=lead)).isoformat() if delivery and lead is not None else delivery
        orders.append({"line": n, "external_document_no": f"{base}-{n}"[:35], "item": item, "quantity": r.get("quantity"),
                       "unit_of_measure": r.get("unit_of_measure"), "delivery_date": delivery, "shipment_date": ship,
                       "po_price": r.get("unit_price") if str(r.get("price_source") or "").startswith("PO price") else None,
                       "hub_price": r.get("unit_price"), "price_source": r.get("price_source")})
    items = sorted({o["item"] for o in orders})
    prices = {it: {"template": (templates.get(it) or {}).get("price"), "hub": next((o["hub_price"] for o in orders if o["item"] == it), None),
                   "template_order": (templates.get(it) or {}).get("order_no")} for it in items}
    existing = sorted([o["external_doc_no"] async for o in db.bc_sales_orders.find(
        {"customer_no": cust, "external_doc_no": {"$regex": "^" + re.escape(base) + r"-\d+(\s*/|$)"}}, {"_id": 0, "external_doc_no": 1})])
    return {"document_id": doc_id, "customer_no": cust, "customer_po": base, "orders": orders, "items": items, "prices": prices,
            "templates": {it: t for it, t in templates.items()}, "lead_days": lead, "trucks_per_day": per_day, "ship_start": start,
            "problems": problems,
            "already_in_production": existing, "bulk": d.get("sales_bulk_orders")}


TEST_PREFIX = "T-"


async def create(db, doc_id: str, prices: Dict[str, float], ship_dates: Optional[Dict[str, str]] = None,
                 user: Optional[Dict[str, Any]] = None, test_copy: bool = False) -> Dict[str, Any]:
    """Create the planned orders in the PRE sandbox. Never Production.
    test_copy: the sandbox (a Production copy) already holds inside sales'
    orders for this PO; the Hub's are made beside them as "T-P0030203-1" so
    the rep compares the two in BC (Horseshoe test, phase 1)."""
    import httpx
    from services.sandbox_draft_service import ALLOWED_ENVIRONMENT
    from services.gpi_integration_service import verify_sandbox, production_name
    from services.sales_draft_service import refusal, _bc
    await verify_sandbox(ALLOWED_ENVIRONMENT)
    why = refusal()
    if why or production_name(ALLOWED_ENVIRONMENT):
        return {"created": 0, "refused": why or "not a sandbox"}
    p = await plan(db, doc_id)
    if p.get("error"):
        return {"created": 0, "refused": p["error"]}
    if p["problems"]:
        return {"created": 0, "refused": "; ".join(p["problems"])}
    for it in p["items"]:
        v = prices.get(it)
        if v is None or float(v) <= 0:
            return {"created": 0, "refused": f"confirm a price for {it}"}
    now = datetime.now(timezone.utc).isoformat()
    base, h = await _bc(ALLOWED_ENVIRONMENT)
    made, skipped, failed = [], [], []
    async with httpx.AsyncClient(timeout=90) as c:
        for o in p["orders"]:
            ext = (TEST_PREFIX + o["external_document_no"])[:35] if test_copy else o["external_document_no"]
            # Idempotent: an order with this PO line number already in the sandbox is kept.
            r = await c.get(f"{base}/salesOrders", headers=h, params={
                "$filter": f"customerNumber eq '{p['customer_no']}' and externalDocumentNumber eq '{ext}'", "$select": "number"})
            if r.status_code == 200 and r.json().get("value"):
                skipped.append({"external_document_no": ext, "bc_order_no": r.json()["value"][0]["number"]})
                continue
            t = p["templates"].get(o["item"]) or {"charges": [], "comments": []}
            ship = (ship_dates or {}).get(ext) or o.get("shipment_date")
            r = await c.post(f"{base}/salesOrders", headers=h, json={"customerNumber": p["customer_no"], "externalDocumentNumber": ext})
            if r.status_code not in (200, 201):
                failed.append({"external_document_no": ext, "error": r.text[:200]})
                break
            so = r.json()
            sid, sno = so["id"], so["number"]
            lines = [{"lineType": "Item", "lineObjectNumber": o["item"], "quantity": float(o["quantity"]),
                      "unitPrice": float(prices[o["item"]]), **({"unitOfMeasureCode": o["unit_of_measure"]} if o.get("unit_of_measure") else {}),
                      **({"shipmentDate": ship} if ship else {})}]
            lines += [{"lineType": "Comment", "description": cm[:100]} for cm in t["comments"]]
            lines += [{"lineType": "Item", "lineObjectNumber": ch["item"], "quantity": ch["quantity"], "unitPrice": ch["unit_price"],
                       **({"unitOfMeasureCode": ch["unit_of_measure"]} if ch.get("unit_of_measure") else {}),
                       **({"shipmentDate": ship} if ship else {})} for ch in t["charges"]]
            errors = []
            for body in lines:
                lr = await c.post(f"{base}/salesOrders({sid})/salesOrderLines", headers=h, json=body)
                if lr.status_code not in (200, 201):
                    errors.append(f"{body.get('lineObjectNumber') or 'comment'}: {lr.text[:160]}")
            rb = await c.get(f"{base}/salesOrders({sid})", headers=h, params={"$expand": "salesOrderLines"})
            got = [x for x in (rb.json().get("salesOrderLines") or []) if x.get("lineObjectNumber")] if rb.status_code == 200 else []
            want = [b for b in lines if b["lineType"] == "Item"]
            ok = not errors and len(got) == len(want) and all(
                any(str(g["lineObjectNumber"]).upper() == str(b["lineObjectNumber"]).upper() and abs(float(g["quantity"]) - b["quantity"]) < 0.001
                    and abs(float(g.get("unitPrice") or 0) - b["unitPrice"]) < 0.005 for g in got) for b in want)
            made.append({"external_document_no": ext, "po_line_no": o["external_document_no"], "lines": lines,
                         "bc_order_no": sno, "bc_system_id": sid, "ok": ok, "errors": errors,
                         "total": rb.json().get("totalAmountExcludingTax") if rb.status_code == 200 else None, "shipment_date": ship})
            if not ok:
                failed.append({"external_document_no": ext, "error": "; ".join(errors)[:200] or "lines differ on read back"})
                break
    rec = {"environment": ALLOWED_ENVIRONMENT, "at": now, "by": (user or {}).get("email"), "prices": prices, "test_copy": test_copy,
           "orders": made, "skipped": skipped, "failed": failed}
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {"sales_bulk_orders": rec}})
    await db.ap_workflow_events.insert_one({"document_id": doc_id, "action": "sales_bulk_orders", "by": rec["by"] or "hub", "at": now,
                                            "environment": ALLOWED_ENVIRONMENT,
                                            "detail": {"customer": p["customer_no"], "customer_po": p["customer_po"], "created": len(made),
                                                       "skipped": len(skipped), "failed": failed[:3]}})
    logger.info("[SalesBulkOrders] %s %s created=%d skipped=%d failed=%d", p["customer_no"], p["customer_po"], len(made), len(skipped), len(failed))
    return {"created": len(made), "skipped": len(skipped), "failed": failed, "orders": made, "environment": ALLOWED_ENVIRONMENT}


def _diff(want: List[Dict[str, Any]], got: List[Dict[str, Any]]) -> List[str]:
    """What differs between the order the Hub made and the one inside sales
    entered: item, quantity, price, ship date, charges, comment lines."""
    from services.sales_item_xref_service import is_product
    wp = [b for b in want if b.get("lineType") == "Item" and is_product(str(b.get("lineObjectNumber") or ""))]
    gp = [l for l in got if l.get("lineType") == "Item" and is_product(str(l.get("lineObjectNumber") or ""))]
    out = []
    if not wp or not gp or str(wp[0]["lineObjectNumber"]).upper() != str(gp[0].get("lineObjectNumber") or "").upper():
        return ["item"]
    w, g = wp[0], gp[0]
    if abs(float(w["quantity"]) - float(g.get("quantity") or 0)) > 0.001:
        out.append("quantity")
    if abs(float(w["unitPrice"]) - float(g.get("unitPrice") or 0)) > 0.005:
        out.append("price")
    gs = str(g.get("shipmentDate") or "")[:10]
    if w.get("shipmentDate") and gs[:4] not in ("", "0001") and gs != w["shipmentDate"]:
        out.append("ship date")
    wc = sorted((str(b["lineObjectNumber"]).upper(), float(b["quantity"]), round(float(b["unitPrice"]), 2)) for b in want
                if b.get("lineType") == "Item" and b is not w)
    gc = sorted((str(l["lineObjectNumber"]).upper(), float(l.get("quantity") or 0), round(float(l.get("unitPrice") or 0), 2)) for l in got
                if l.get("lineType") == "Item" and l is not g and l.get("lineObjectNumber"))
    if wc != gc:
        out.append("charges")
    if [b["description"] for b in want if b.get("lineType") == "Comment"] != \
            [str(l.get("description") or "") for l in got if l.get("lineType") == "Comment" and str(l.get("description") or "").strip()]:
        out.append("comments")
    return out


async def grade(db) -> Dict[str, Any]:
    """Hourly: each bulk run's orders against the orders inside sales
    entered in Production for the same PO lines (as entered when the Hub
    saw them entered). sales_bulk_orders.vs_bc."""
    stats = Counter()
    async for d in db.hub_documents.find({"sales_bulk_orders.orders.0": {"$exists": True}},
                                         {"_id": 1, "sales_link.bc_customer_no": 1, "sales_bulk_orders": 1}):
        cust = (d.get("sales_link") or {}).get("bc_customer_no")
        rows, c = [], Counter()
        for m in d["sales_bulk_orders"]["orders"]:
            if not m.get("lines"):
                continue
            ext = m.get("po_line_no") or m["external_document_no"]
            prod = await db.bc_sales_orders.find_one({"customer_no": cust, "external_doc_no": {"$regex": "^" + re.escape(ext) + r"(\s*/|$)"}},
                                                     {"_id": 0, "order_no": 1, "lines": 1, "entered_lines": 1})
            if not prod:
                c["not_entered_yet"] += 1
                continue
            diffs = _diff(m["lines"], _lines_of(prod))
            c["orders"] += 1
            c["exact"] += not diffs
            for x in diffs:
                c[x] += 1
            rows.append({"external_document_no": m["external_document_no"], "bc_order_no": m.get("bc_order_no"),
                         "production_order_no": prod["order_no"], "diffs": diffs})
        if c["orders"]:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {"sales_bulk_orders.vs_bc": {
                **dict(c), "orders_detail": rows, "graded_at": datetime.now(timezone.utc).isoformat()}}})
            stats["runs"] += 1
            stats.update({k: v for k, v in c.items()})
    return dict(stats)


async def compare_with_production(db, doc_id: str) -> Dict[str, Any]:
    """Sandbox proof: the planned orders (with the template's price) against
    the orders inside sales entered in Production for the same PO lines."""
    d = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "sales_link": 1, "extracted_fields.po_number": 1})
    from services.sales_draft_service import _split_base
    from services.sales_item_xref_service import _order_seq
    sl = (d or {}).get("sales_link") or {}
    base = _split_base(sl, str(((d or {}).get("extracted_fields") or {}).get("po_number") or (sl.get("customer_po") or [""])[0]))
    first = sorted([o["order_no"] async for o in db.bc_sales_orders.find(
        {"customer_no": sl.get("bc_customer_no"), "external_doc_no": {"$regex": "^" + re.escape(base) + r"-\d+(\s*/|$)"}}, {"_id": 0, "order_no": 1})],
        key=_order_seq)
    p = await plan(db, doc_id, before=first[0] if first else None)
    if p.get("error"):
        return p
    out, c = [], Counter()
    for o in p["orders"]:
        t = p["templates"].get(o["item"]) or {"charges": [], "comments": [], "price": None}
        prod = await db.bc_sales_orders.find_one({"customer_no": p["customer_no"], "external_doc_no": {"$regex": "^" + re.escape(o["external_document_no"]) + r"(\s*/|$)"}},
                                                 {"_id": 0, "order_no": 1, "lines": 1, "entered_lines": 1, "status": 1})
        if not prod:
            c["not_in_production"] += 1
            continue
        ls = _lines_of(prod)
        pi = next((l for l in ls if str(l.get("lineObjectNumber") or "").upper() == o["item"].upper()), None)
        diffs = []
        if not pi:
            diffs.append("item")
        else:
            if abs(float(pi.get("quantity") or 0) - float(o["quantity"] or 0)) > 0.001:
                diffs.append("quantity")
            if t["price"] is None or abs(float(pi.get("unitPrice") or 0) - t["price"]) > 0.005:
                diffs.append("price")
            sd = str(pi.get("shipmentDate") or "")[:10]
            if o.get("shipment_date") and sd and sd != o["shipment_date"]:
                diffs.append("ship date")
        want_ch = sorted((ch["item"], ch["quantity"], round(ch["unit_price"], 2)) for ch in t["charges"])
        got_ch = sorted((l["lineObjectNumber"], float(l.get("quantity") or 0), round(float(l.get("unitPrice") or 0), 2)) for l in ls
                        if l.get("lineType") == "Item" and l is not pi and l.get("lineObjectNumber"))
        if want_ch != got_ch:
            diffs.append("charges")
        if [cm for cm in t["comments"]] != [str(l.get("description") or "") for l in ls if l.get("lineType") == "Comment" and str(l.get("description") or "").strip()]:
            diffs.append("comments")
        c["orders"] += 1
        c["exact"] += not diffs
        for x in diffs:
            c[x] += 1
        out.append({"external_document_no": o["external_document_no"], "bc_order_no": prod["order_no"], "diffs": diffs})
    return {"customer_po": p["customer_po"], "summary": dict(c), "orders": out}
