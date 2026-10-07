"""One clear stage per sales-mailbox document (like ap_stage on AP).

  in_bc        the customer PO is on a BC sales order (inside sales entered it)
  drafted      the Hub drafted the sales order in the BC sandbox (PRE)
  ready        customer and every product line known: the Hub drafts it
  needs_rep    a person must decide (sales_stage_reason says why)
  duplicate    another copy / page of a customer PO already counted
  filed        evidence, not work: Gamer's own order copies, AR invoices,
               other customer mail
  purchasing   a supplier's document about a Gamer purchase order
  to_ap        an AP invoice that came to sales
"""
import re
from collections import Counter
from datetime import datetime, timedelta, timezone
from typing import Any, Dict

from services.sales_item_xref_service import resolve_lines, is_product, load_item_categories, _charge_text

REASONS = {
    "customer_unknown": "Which customer is this? The sender is not linked to a BC customer.",
    "customer_po_missing": "No customer PO number was read from the document.",
    "items_unknown": "Some lines could not be matched to a Gamer item.",
    "no_lines": "No order lines were read from the document.",
    "draft_problem": "The Hub could not draft this order in BC.",
    "price_unknown": "No price for some lines (the customer has not bought these items before).",
    "totals_differ": "The lines the Hub would draft do not add up to the PO total.",
}


def _key(customer: str, pos) -> str:
    return f"{customer}|{sorted(pos)[0] if pos else ''}"


async def stage_of(db, d: Dict[str, Any]) -> Dict[str, Any]:
    sl = d.get("sales_link") or {}
    role = sl.get("role")
    if d.get("status") == "batch_parent":
        return {"sales_stage": "filed", "sales_stage_reason": "split into pages"}
    if role == "ap_invoice":
        return {"sales_stage": "to_ap"}
    if role == "supplier":
        return {"sales_stage": "purchasing"}
    if role != "customer_po":
        return {"sales_stage": "filed", "sales_stage_reason": role or "other"}
    if sl.get("order_no"):
        return {"sales_stage": "in_bc", "bc_order_no": sl["order_no"]}
    sd = d.get("sales_draft") or {}
    if sd.get("bc_order_no") and sd.get("environment"):
        return {"sales_stage": "drafted", "bc_draft_no": sd["bc_order_no"]}
    if d.get("sales_draft_skipped"):
        return {"sales_stage": "needs_rep", "sales_stage_reason": "draft_problem",
                "sales_stage_detail": d["sales_draft_skipped"].get("reason")}
    cust = sl.get("bc_customer_no")
    if not cust:
        return {"sales_stage": "needs_rep", "sales_stage_reason": "customer_unknown"}
    if not sl.get("customer_po"):
        return {"sales_stage": "needs_rep", "sales_stage_reason": "customer_po_missing"}
    el = [e for e in ((d.get("extracted_fields") or {}).get("line_items") or []) if not _charge_text(e)]
    if not el:
        return {"sales_stage": "needs_rep", "sales_stage_reason": "no_lines"}
    res = await resolve_lines(db, cust, el)
    lines = [{"item": r["item"], "quantity": r["quantity"], "unit_of_measure": r["unit_of_measure"],
              "unit_price": r["unit_price"], "how": r["how"], "price_source": r["price_source"],
              "po_description": str(r["source"].get("description") or "")[:120], "po_quantity": r["source"].get("quantity")}
             for r in res]
    unresolved = [l for l in lines if not l["item"]]
    out = {"sales_resolution": {"customer_no": cust, "lines": lines, "resolved": len(lines) - len(unresolved), "total": len(lines)}}
    if unresolved:
        return {**out, "sales_stage": "needs_rep", "sales_stage_reason": "items_unknown"}
    # Entered by inside sales under a customer PO written differently: an
    # order for this customer, dated around receipt, with the same items
    # and quantities.
    recv = str(d.get("created_utc") or "")[:10]
    if recv:
        lo = (datetime.fromisoformat(recv) - timedelta(days=5)).date().isoformat()
        want = {(l["item"], round(float(l["quantity"] or 0), 3)) for l in lines}
        async for o in db.bc_sales_orders.find({"customer_no": cust, "$or": [{"order_date": {"$gte": lo}}, {"first_invoice_date": {"$gte": lo}}]},
                                               {"_id": 0, "order_no": 1, "lines": 1, "ext_tokens": 1}):
            # Only an order entered without a PO number of its own (Giovanni
            # sends one PO per truck, all for the same jar and quantity), and
            # only one Hub PO per order.
            if any(len(re.sub(r"\D", "", t)) >= 4 for t in o.get("ext_tokens") or []):
                continue
            if await db.hub_documents.count_documents({"sales_link.order_no": o["order_no"], "_id": {"$ne": d["_id"]}}, limit=1):
                continue
            have = {(str(l.get("lineObjectNumber") or "").upper(), round(float(l.get("quantity") or 0), 3)) for l in o.get("lines") or []}
            if want and want <= have:
                await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {"sales_link.order_no": o["order_no"], "sales_link.match": "items_and_quantities"}})
                return {**out, "sales_stage": "in_bc", "bc_order_no": o["order_no"]}
    if any(l["unit_price"] is None or not l["quantity"] for l in lines):
        return {**out, "sales_stage": "needs_rep", "sales_stage_reason": "price_unknown"}
    from services.sales_charge_service import charge_lines
    charges = await charge_lines(db, cust, lines, (d.get("extracted_fields") or {}).get("line_items") or [])
    out["sales_resolution"]["charges"] = charges
    planned = round(sum(float(l["quantity"]) * float(l["unit_price"]) for l in lines), 2)
    with_charges = round(planned + sum(float(c["quantity"]) * float(c["unit_price"]) for c in charges), 2)
    out["sales_resolution"]["planned_total"] = planned
    out["sales_resolution"]["planned_total_with_charges"] = with_charges
    po_total = d.get("amount_float")
    if po_total and float(po_total) > 0:
        out["sales_resolution"]["po_total"] = float(po_total)
        tol = max(1.0, 0.02 * float(po_total))
        if abs(planned - float(po_total)) > tol and abs(with_charges - float(po_total)) > tol:
            return {**out, "sales_stage": "needs_rep", "sales_stage_reason": "totals_differ",
                    "sales_stage_detail": f"lines {planned:,.2f} vs PO {float(po_total):,.2f}"}
    return {**out, "sales_stage": "ready"}


async def refresh(db, days: int = 45) -> Dict[str, Any]:
    await load_item_categories(db)
    since = (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()
    now = datetime.now(timezone.utc).isoformat()
    stats = Counter()
    seen: Dict[str, str] = {}
    docs = [d async for d in db.hub_documents.find(
        {"created_utc": {"$gte": since}, "mailbox_category": {"$in": ["SALES", "Sales"]}, "sales_link": {"$exists": True}},
        {"_id": 1, "id": 1, "status": 1, "sales_link": 1, "sales_draft": 1, "sales_draft_skipped": 1,
         "extracted_fields.line_items": 1, "created_utc": 1, "amount_float": 1}).sort([("created_utc", 1)])]
    # Several copies / pages of one customer PO: the one with the most lines counts.
    best: Dict[str, Any] = {}
    for d in docs:
        sl = d.get("sales_link") or {}
        if sl.get("role") == "customer_po" and sl.get("bc_customer_no") and sl.get("customer_po"):
            k = _key(sl["bc_customer_no"], sl["customer_po"])
            nl = len((d.get("extracted_fields") or {}).get("line_items") or [])
            if (d.get("sales_draft") or {}).get("bc_order_no"):
                nl += 1000
            if k not in best or nl > best[k][0]:
                best[k] = (nl, d["id"])
    for d in docs:
        sl = d.get("sales_link") or {}
        k = _key(sl.get("bc_customer_no") or "", sl.get("customer_po") or []) if sl.get("role") == "customer_po" else None
        if k and k in best and best[k][1] != d["id"] and not sl.get("order_no"):
            st = {"sales_stage": "duplicate", "sales_stage_reason": "another copy of this customer PO", "duplicate_of": best[k][1]}
        else:
            st = await stage_of(db, d)
        stats[st["sales_stage"]] += 1
        unset = {k2: "" for k2 in ("sales_stage_reason", "sales_stage_detail", "sales_resolution", "bc_order_no", "bc_draft_no", "duplicate_of") if k2 not in st}
        await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {**st, "sales_stage_at": now}, **({"$unset": unset} if unset else {})})
    return dict(stats)

