"""Open BC sales orders whose quantity is clearly a typing slip.

2026-10-22: 39 open Horseshoe orders (P0030200-1..8, P0030205-1..15,
P0030210-1..16, entered 2026-10-19) carried 202,400 M of 6069966 instead of
202.4 M - $31.5M each, $1.23B in all. A line is flagged when its quantity is
at least 300x this customer's median for the item in that unit (3+ orders)
and the line is worth over $100,000. Read-only: the Hub never edits BC; the
list is for inside sales (Today page, /sales-inbox/order-checks).
"""
import statistics
from collections import defaultdict
from datetime import datetime, timezone
from typing import Any, Dict

RATIO = 300
MIN_VALUE = 100_000
MIN_HISTORY = 3


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
                flags.append({"order_no": o["order_no"], "customer_no": o["customer_no"], "customer_name": o.get("customer_name"),
                              "external_doc_no": o.get("external_doc_no"), "order_date": o.get("order_date"),
                              "item": l["lineObjectNumber"], "quantity": q, "unit": l.get("unitOfMeasureCode"),
                              "usual_quantity": usual, "unit_price": float(l.get("unitPrice") or 0), "line_value": round(value, 2),
                              "why": f"{q:,.4g} {l.get('unitOfMeasureCode') or ''} of {l['lineObjectNumber']}; this customer usually orders "
                                     f"{usual:,.4g} {l.get('unitOfMeasureCode') or ''}", "checked_at": now})
    await db.bc_order_checks.delete_many({})
    if flags:
        await db.bc_order_checks.insert_many([dict(f) for f in flags])
    return {"open_orders": len(open_orders), "flagged": len(flags), "value": round(sum(f["line_value"] for f in flags), 2)}
