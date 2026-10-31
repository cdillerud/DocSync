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
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

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


def compare(planned: List[Dict[str, Any]], actual: List[Dict[str, Any]], later: frozenset = frozenset()) -> Dict[str, Any]:
    """later: charges this customer gets at shipping / invoicing (Giovanni's
    O-I pallets on 100% of invoiced orders): a draft is the order as entered,
    so their absence is not a miss."""
    p, a = _norm_lines(planned), _norm_lines(actual)
    a_later = sorted(it for it in a if it in later and it not in p)
    a = {it: x for it, x in a.items() if it not in a_later}
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
    if a_later:
        out["added_at_shipping"] = a_later
    return out


async def _later_charges(db, customer_no: Any) -> frozenset:
    return frozenset([u["charge"] async for u in db.sales_charge_usual.find(
        {"customer_no": customer_no, "when": "shipping / invoicing"}, {"_id": 0, "charge": 1})])


def _merge(gs: List[Dict[str, Any]]) -> Dict[str, Any]:
    out: Dict[str, Any] = Counter()
    for g in gs:
        for k, v in g.items():
            if isinstance(v, int) and not isinstance(v, bool):
                out[k] += v
    out = dict(out)
    for k in ("missing", "extra", "added_at_shipping"):
        out[k] = sorted({x for g in gs for x in g.get(k) or []})
    out["exact"] = all(g.get("exact") for g in gs)
    return out


async def readback(db, env: Optional[str] = None) -> Dict[str, Any]:
    import httpx
    from services.sales_draft_service import _bc
    if env is None:
        from services.draft_readback_service import sandbox_envs
        out = {}
        for e in await sandbox_envs(db, "sales_draft.environment"):
            try:
                out[e] = await readback(db, e)
            except Exception as x:    # one sandbox down does not stop the others
                out[e] = {"error": repr(x)[:200]}
        return out
    ALLOWED_ENVIRONMENT = env
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
            later = await _later_charges(db, sd.get("customer_no"))
            if sd.get("orders") and all(x.get("lines") for x in sd["orders"]):
                # One draft per PO line (Horseshoe P0030240-3): graded against
                # the rep's order for that line ("P0030240-3/W118465").
                gs, nos = [], []
                for x in sd["orders"]:
                    ext = str(x.get("external_document_no") or "")
                    o = await db.bc_sales_orders.find_one({"customer_no": sd.get("customer_no"), "external_doc_no": {"$regex": "^" + re.escape(ext) + r"(\s*/|$)"},
                                                           "order_no": {"$nin": nos}},
                                                          {"_id": 0, "order_no": 1, "lines": 1})
                    if o:
                        gs.append(compare(x["lines"], [l for l in o.get("lines") or [] if l.get("lineType") == "Item"], later))
                        nos.append(o["order_no"])
                if gs:
                    g = _merge(gs)
                    upd["sales_draft_vs_bc"] = {**g, "bc_order_no": nos[0], "bc_orders": nos, "orders_graded": len(gs),
                                                "orders_drafted": len(sd["orders"]), "graded_at": now}
                    stats["graded"] += 1
                    stats["graded_exact"] += bool(g["exact"])
            elif order_no:
                o = await db.bc_sales_orders.find_one({"order_no": order_no}, {"_id": 0, "lines": 1})
                if o:
                    g = compare(sd.get("lines") or [], [l for l in o.get("lines") or [] if l.get("lineType") == "Item"], later)
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

