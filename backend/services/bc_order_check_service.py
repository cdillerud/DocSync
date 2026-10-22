"""Open BC sales orders whose quantity is clearly a typing slip.

2026-10-22: 39 open Horseshoe orders (P0030200-1..8, P0030205-1..15,
P0030210-1..16, entered 2026-10-19) carried 202,400 M of 6069966 instead of
202.4 M - $31.5M each, $1.23B in all. A line is flagged when its quantity is
at least 300x this customer's median for the item in that unit (3+ orders)
and the line is worth over $100,000. Read-only: the Hub never edits BC; the
list is for inside sales (Today page, /sales-inbox/order-checks).

Price check (kind "price"): an open order line whose unit price differs from
the linked customer PO's price for that line - e.g. six AMERPOP orders at
350/M while PO 16834-16839 say 0.33333/ea (333.33/M). The customer is likely
to pay the PO price, so either the PO or the order needs correcting. PO lines
are tied to BC lines only through the Hub's own draft (po_description); an
item-number match alone gave 127 flags, mostly misread units. Prices compare
per BC unit (each vs M by quantity), within a 0.8-1.25 ratio.
"""
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict

RATIO = 300
MIN_VALUE = 100_000
MIN_HISTORY = 3
PRICE_TOL = 0.01      # 1% - rounding of 0.33333/ea is far inside this
PRICE_MIN_GAP = 50    # dollars over the whole line
PRICE_BAND = (0.8, 1.25)  # outside this the PO price was misread, not a price change


def _per_bc_unit(po_line: dict, bc_qty: float):
    """PO unit price converted to the BC line's unit, or None when the two
    quantities are not the same amount in each or thousands."""
    try:
        pq, pp = float(po_line.get("quantity") or 0), float(po_line.get("unit_price") or 0)
    except (TypeError, ValueError):
        return None
    if pq <= 0 or pp <= 0 or bc_qty <= 0:
        return None
    r = pq / bc_qty
    for f in (1, 1000):
        if abs(r - f) / f <= 0.02:
            return pp * f
    return None


async def _price_flags(db, open_by_no: dict, now: str) -> list:
    flags = []
    cur = db.hub_documents.find({"sales_link.order_no": {"$in": list(open_by_no)}, "line_items.0": {"$exists": True}},
                                {"sales_link": 1, "line_items": 1, "sales_draft.lines": 1, "file_name": 1})
    seen = set()
    async for d in cur:
        o = open_by_no.get(d["sales_link"].get("order_no"))
        if not o:
            continue
        drafted = {l.get("item"): l for l in (d.get("sales_draft") or {}).get("lines") or [] if not l.get("charge")}
        for l in o.get("lines") or []:
            item, bq, bp = l.get("lineObjectNumber"), float(l.get("quantity") or 0), float(l.get("unitPrice") or 0)
            if l.get("lineType") != "Item" or not item or bq <= 0 or bp <= 0 or (o["order_no"], item) in seen:
                continue
            m = drafted.get(item)
            if not (m and m.get("po_description")):
                continue
            cands = [x for x in d["line_items"] if (x.get("description") or "").startswith(m["po_description"][:100])]
            if len(cands) != 1:
                continue
            pp = _per_bc_unit(cands[0], bq)
            if pp is None or not PRICE_BAND[0] <= pp / bp <= PRICE_BAND[1]:
                continue
            gap = (bp - pp) * bq
            if abs(bp - pp) / bp > PRICE_TOL and abs(gap) > PRICE_MIN_GAP:
                seen.add((o["order_no"], item))
                u = l.get("unitOfMeasureCode") or ""
                flags.append({"kind": "price", "order_no": o["order_no"], "customer_no": o["customer_no"], "customer_name": o.get("customer_name"),
                              "external_doc_no": o.get("external_doc_no"), "order_date": o.get("order_date"),
                              "item": item, "quantity": bq, "unit": u, "unit_price": bp, "po_unit_price": round(pp, 5),
                              "line_value": round(gap, 2),
                              "why": f"{item} at {bp:,.2f}/{u} in BC; the customer's PO says {pp:,.2f}/{u}", "checked_at": now})
    return flags


def _qty(x: float) -> str:
    """202,400 / 202.4 - never 2.024e+05."""
    return f"{x:,.0f}" if abs(x - round(x)) < 1e-9 else f"{x:,.4f}".rstrip("0").rstrip(".")


async def check(db) -> Dict[str, Any]:
    hist = defaultdict(list)
    open_orders = []
    async for o in db.bc_sales_orders.find({}, {"_id": 0, "order_no": 1, "customer_no": 1, "customer_name": 1, "external_doc_no": 1,
                                                 "status": 1, "order_date": 1, "lines": 1}):
        for l in o.get("lines") or []:
            q = float(l.get("quantity") or 0)
            if l.get("lineObjectNumber") and q > 0:
                hist[(o["customer_no"], l["lineObjectNumber"], l.get("unitOfMeasureCode"))].append(q)
        if o.get("status") == "open":
            open_orders.append(o)
    now = datetime.now(timezone.utc).isoformat()
    flags = []
    for o in open_orders:
        for l in o.get("lines") or []:
            q = float(l.get("quantity") or 0)
            if q <= 0 or not l.get("lineObjectNumber"):
                continue
            qs = hist[(o["customer_no"], l["lineObjectNumber"], l.get("unitOfMeasureCode"))]
            if len(qs) < MIN_HISTORY:
                continue
            usual = statistics.median(qs)
            value = q * float(l.get("unitPrice") or 0)
            if usual > 0 and q >= RATIO * usual and value > MIN_VALUE:
                flags.append({"kind": "quantity", "order_no": o["order_no"], "customer_no": o["customer_no"], "customer_name": o.get("customer_name"),
                              "external_doc_no": o.get("external_doc_no"), "order_date": o.get("order_date"),
                              "item": l["lineObjectNumber"], "quantity": q, "unit": l.get("unitOfMeasureCode"),
                              "usual_quantity": usual, "unit_price": float(l.get("unitPrice") or 0), "line_value": round(value, 2),
                              "why": f"{_qty(q)} {l.get('unitOfMeasureCode') or ''} of {l['lineObjectNumber']}; this customer usually orders "
                                     f"{_qty(usual)} {l.get('unitOfMeasureCode') or ''}", "checked_at": now})
    flags += await _price_flags(db, {o["order_no"]: o for o in open_orders}, now)
    await db.bc_order_checks.delete_many({})
    if flags:
        await db.bc_order_checks.insert_many([dict(f) for f in flags])
    q = [f for f in flags if f["kind"] == "quantity"]
    return {"open_orders": len(open_orders), "flagged": len(q), "value": round(sum(f["line_value"] for f in q), 2),
            "price_flagged": len(flags) - len(q), "price_gap": round(sum(f["line_value"] for f in flags if f["kind"] == "price"), 2)}
