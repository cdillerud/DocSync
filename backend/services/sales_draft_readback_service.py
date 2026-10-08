"""Sales drafts, read back (BC -> Hub), and graded against what inside
sales actually entered.

Hourly, read-only:
1. Every Hub sales-order draft in the PRE sandbox is read back: still a
   draft, deleted / shipped, and what a reviewer changed (customer,
   customer PO, lines added / removed / item, quantity or price changed).
   sales_draft_readback {state, edits, lines}; a reviewed draft is a
   labelled example the item cross-reference learns from
   (sales_item_xref_service.learn).
2. When inside sales has entered the same customer PO in Production BC,
   the Hub's draft is compared line by line with that order:
   sales_draft_vs_bc {products_right, products, qty_right, price_right,
   charges_right, charges, missing, extra} - the real accuracy of drafting.
"""
import logging
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List

from services.sales_item_xref_service import is_product, load_item_categories

logger = logging.getLogger(__name__)


def _norm_lines(ls: List[Dict[str, Any]]) -> Dict[str, Dict[str, float]]:
    out: Dict[str, Dict[str, float]] = {}
    for l in ls or []:
        it = str(l.get("lineObjectNumber") or l.get("item") or "").upper()
        if not it:
            continue
        a = out.setdefault(it, {"q": 0.0, "p": float(l.get("unitPrice", l.get("unit_price")) or 0)})
        a["q"] += float(l.get("quantity") or 0)
    return out


def compare(planned: List[Dict[str, Any]], actual: List[Dict[str, Any]]) -> Dict[str, Any]:
    p, a = _norm_lines(planned), _norm_lines(actual)
    c = Counter()
    for it, x in a.items():
        kind = "products" if is_product(it) else "charges"
        c[kind] += 1
        if it in p:
            c[kind + "_right"] += 1
            if kind == "products":
                c["qty_right"] += abs(p[it]["q"] - x["q"]) <= max(0.01, 0.002 * x["q"])
                c["price_right"] += abs(p[it]["p"] - x["p"]) <= max(0.005, 0.005 * x["p"])
    out = dict(c)
    out["missing"] = sorted(it for it in a if it not in p)
    out["extra"] = sorted(it for it in p if it not in a)
    out["exact"] = not out["missing"] and not out["extra"] and c["qty_right"] == c["products"] and c["price_right"] == c["products"]
    return out


async def readback(db) -> Dict[str, Any]:
    import httpx
    from services.sandbox_draft_service import ALLOWED_ENVIRONMENT
    from services.sales_draft_service import _bc
    await load_item_categories(db)
    now = datetime.now(timezone.utc).isoformat()
    stats = Counter()
    docs = [d async for d in db.hub_documents.find({"sales_draft.environment": ALLOWED_ENVIRONMENT},
                                                  {"_id": 1, "id": 1, "sales_draft": 1, "sales_link": 1})]
    if not docs:
        return {"drafts": 0}
    base, h = await _bc(ALLOWED_ENVIRONMENT)
    async with httpx.AsyncClient(timeout=60) as c:
        for d in docs:
            sd = d["sales_draft"]
            stats["drafts"] += 1
            r = await c.get(f"{base}/salesOrders", headers=h, params={
                "$filter": f"number eq '{sd['bc_order_no']}'", "$expand": "salesOrderLines",
                "$select": "number,status,customerNumber,externalDocumentNumber,totalAmountExcludingTax"})
            if r.status_code != 200:
                stats["read_error"] += 1
                continue
            vals = r.json().get("value", [])
            if not vals:
                state = {"state": "gone", "note": "no longer an open sales order in the sandbox (deleted, or shipped and invoiced)"}
                stats["gone"] += 1
            else:
                v = vals[0]
                lines = [{k: l.get(k) for k in ("lineObjectNumber", "quantity", "unitPrice", "unitOfMeasureCode")}
                         for l in v.get("salesOrderLines") or [] if l.get("lineObjectNumber")]
                edits = []
                if str(v.get("customerNumber") or "").upper() != str(sd.get("customer_no") or "").upper():
                    edits.append(f"customer {sd.get('customer_no')} -> {v.get('customerNumber')}")
                if str(v.get("externalDocumentNumber") or "") != str(sd.get("external_document_no") or ""):
                    edits.append(f"customer PO {sd.get('external_document_no')} -> {v.get('externalDocumentNumber')}")
                cmp = compare(sd.get("lines") or [], lines)
                for it in cmp["missing"]:
                    edits.append(f"line added: {it}")
                for it in cmp["extra"]:
                    edits.append(f"line removed: {it}")
                pl, al = _norm_lines(sd.get("lines") or []), _norm_lines(lines)
                for it in set(pl) & set(al):
                    if abs(pl[it]["q"] - al[it]["q"]) > 0.001:
                        edits.append(f"{it} quantity {pl[it]['q']:g} -> {al[it]['q']:g}")
                    if abs(pl[it]["p"] - al[it]["p"]) > 0.005:
                        edits.append(f"{it} price {pl[it]['p']:g} -> {al[it]['p']:g}")
                state = {"state": str(v.get("status") or "").lower() or "draft", "edits": edits, "lines": lines,
                         "total": v.get("totalAmountExcludingTax")}
                stats["edited" if edits else "unchanged"] += 1
            state["checked_at"] = now
            upd = {"sales_draft_readback": state}
            # Graded against the order inside sales entered in Production.
            order_no = (d.get("sales_link") or {}).get("order_no")
            if order_no:
                o = await db.bc_sales_orders.find_one({"order_no": order_no}, {"_id": 0, "lines": 1})
                if o:
                    g = compare(sd.get("lines") or [], [l for l in o.get("lines") or [] if l.get("lineType") == "Item"])
                    upd["sales_draft_vs_bc"] = {**g, "bc_order_no": order_no, "graded_at": now}
                    stats["graded"] += 1
                    stats["graded_exact"] += bool(g["exact"])
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": upd})
    logger.info("[SalesDraftReadback] %s", dict(stats))
    return dict(stats)


async def metrics(db) -> Dict[str, Any]:
    """Drafting accuracy against inside sales' own Production orders."""
    c = Counter()
    async for d in db.hub_documents.find({"sales_draft_vs_bc.graded_at": {"$exists": True}}, {"_id": 0, "sales_draft_vs_bc": 1}):
        g = d["sales_draft_vs_bc"]
        c["orders"] += 1
        c["exact"] += bool(g.get("exact"))
        for k in ("products", "products_right", "qty_right", "price_right", "charges", "charges_right"):
            c[k] += int(g.get(k) or 0)
    return dict(c)

