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


_DUNNAGE_WORDS = re.compile(r"\b(TIER\s*SHEETS?|TOP\s*FRAMES?|SLIP\s*SHEETS?|DUNNAGE|PALLETS?)\b", re.I)


def _dunnage(e: Dict[str, Any]) -> bool:
    """Pallets, tier sheets, top frames: Gamer items of category PALLET that
    inside sales adds like a charge - not a product line to match (O-I
    OITIERSHEET / OITOPFRAME on a PO were reported as 'new items')."""
    from services.sales_item_xref_service import _code_tokens, _ITEM_BY_NORM, _CATEGORY
    desc = str(e.get("description") or "")
    for tok in _code_tokens(desc.upper(), 4):
        it = _ITEM_BY_NORM.get(tok)
        if it:
            return _CATEGORY.get(it) == "PALLET"
    return bool(_DUNNAGE_WORDS.search(desc)) and len(desc) < 90


def plain_bc_error(reason: Any) -> Any:
    """BC's validation errors in words a rep can act on."""
    r = str(reason or "")
    m = re.search(r"must be equal to 'No'\s+in Item: No\.=([^.]+)\. Current value is 'Yes'", r)
    if m:
        return (f"Item {m.group(1).strip()} is blocked in BC (Blocked or Sales Blocked): pick the item that "
                "replaces it, or have it unblocked.")
    m = re.search(r"\(([A-Z0-9][\w.-]*): .*Item does not exist", r)
    if m:
        # Production has the item (FX60503B, set up 2026-09-28); the test copy
        # of BC the Hub drafts in is older and does not.
        return (f"Item {m.group(1)} is newer than the test copy of BC the Hub drafts in, so the Hub could not "
                "draft this order: enter it in BC as usual.")
    m = re.search(r"Customer (\S+) is blocked", r)
    if m:
        return f"Customer {m.group(1)} is blocked in BC: have it unblocked, or use the customer account that replaced it."
    return reason


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
    # The sender is not linked to a customer (Carlsbad Gourmet writes from a
    # yahoo.com address) but the document was: use that customer, and look
    # for its PO on that customer's BC orders (PO 1026 = SO 120147).
    cust = sl.get("bc_customer_no") or d.get("customer_canonical")
    if cust and not sl.get("bc_customer_no"):
        pos = {t for p in sl.get("customer_po") or [] for t in (str(p).upper(), re.sub(r"[^A-Z0-9]", "", str(p).upper())) if t}
        o = await db.bc_sales_orders.find_one({"customer_no": cust, "ext_norm": {"$in": sorted(pos)}}, {"_id": 0, "order_no": 1}) if pos else None
        if o:
            return {"sales_stage": "in_bc", "bc_order_no": o["order_no"]}
    sd = d.get("sales_draft") or {}
    if sd.get("bc_order_no") and sd.get("environment"):
        return {"sales_stage": "drafted", "bc_draft_no": sd["bc_order_no"]}
    if d.get("sales_draft_skipped"):
        return {"sales_stage": "needs_rep", "sales_stage_reason": "draft_problem",
                "sales_stage_detail": plain_bc_error(d["sales_draft_skipped"].get("reason"))}
    if not cust:
        return {"sales_stage": "needs_rep", "sales_stage_reason": "customer_unknown"}
    if not sl.get("customer_po"):
        return {"sales_stage": "needs_rep", "sales_stage_reason": "customer_po_missing"}
    el = [e for e in ((d.get("extracted_fields") or {}).get("line_items") or []) if not _charge_text(e) and not _dunnage(e)]
    if not el:
        return {"sales_stage": "needs_rep", "sales_stage_reason": "no_lines"}
    res = await resolve_lines(db, cust, el)
    lines = [{"item": r["item"], "quantity": r["quantity"], "unit_of_measure": r["unit_of_measure"],
              "unit_price": r["unit_price"], "how": r["how"], "price_source": r["price_source"],
              "po_description": str(r["source"].get("description") or "")[:120], "po_quantity": r["source"].get("quantity"),
              "price_check": r.get("price_check")}
             for r in res]
    unresolved = [l for l in lines if not l["item"]]
    out = {"sales_resolution": {"customer_no": cust, "lines": lines, "resolved": len(lines) - len(unresolved), "total": len(lines),
                                "price_checks": sum(1 for l in lines if l.get("price_check"))}}
    if unresolved:
        # Name the codes: a customer code with no Gamer item is usually a new
        # item to set up in BC (VetsPlus 0PA-5OZCAP).
        codes = []
        for l in unresolved:
            desc = re.sub(r"^\s*(ITEM|PART|SKU|STOCK\s*CODE|P/N)\s*(NO\.?|#)?\s*:?\s*", "", str(l.get("po_description") or "").upper())
            m = re.match(r"\s*([A-Z0-9][A-Z0-9-]{3,})\b", desc)
            codes.append(m.group(1) if m else str(l.get("po_description") or "")[:30])
        # A line with only a word ("BOTTLE", "GLASS") has no code to set up:
        # the rep picks which of the customer's items it is.
        named = [c for c in codes if re.search(r"\d", c)]
        bare = [c for c in codes if not re.search(r"\d", c)]
        parts = []
        if named:
            parts.append("no Gamer item for " + ", ".join(named[:4]) + " (new item to set up in BC?)")
        if bare:
            parts.append("the PO line" + ("s" if len(bare) > 1 else "") + " " + ", ".join(f'"{b}"' for b in bare[:4])
                         + (" give" if len(bare) > 1 else " gives") + " no item number: pick the Gamer item")
        return {**out, "sales_stage": "needs_rep", "sales_stage_reason": "items_unknown",
                "sales_stage_detail": "; ".join(parts)}
    # An item BC has blocked (Giovanni's PO still names AA012014, blocked
    # since 2024): BC refuses the line, so the rep picks today's item.
    items = [l["item"] for l in lines if l["item"]]
    blocked = [x["item_no"] async for x in db.bc_catalog_items.find({"item_no": {"$in": items}, "blocked": True}, {"_id": 0, "item_no": 1})] if items else []
    if blocked:
        return {**out, "sales_stage": "needs_rep", "sales_stage_reason": "items_unknown",
                "sales_stage_detail": "item " + ", ".join(blocked[:4]) + " is blocked in BC (replaced by another item?)"}
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
    from services.sales_charge_service import to_complete
    out["sales_resolution"]["to_complete"] = await to_complete(db, cust, lines + charges)
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
    from services.sales_rep_service import context as rep_context, assign as rep_assign
    rctx = await rep_context(db)
    docs = [d async for d in db.hub_documents.find(
        {"created_utc": {"$gte": since}, "mailbox_category": {"$in": ["SALES", "Sales"]}, "sales_link": {"$exists": True}},
        {"_id": 1, "id": 1, "status": 1, "pilot_mailbox": 1, "sales_link": 1, "sales_draft": 1, "sales_draft_skipped": 1,
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
        st["sales_rep"] = rep_assign(d, rctx)
        stats[st["sales_stage"]] += 1
        unset = {k2: "" for k2 in ("sales_stage_reason", "sales_stage_detail", "sales_resolution", "bc_order_no", "bc_draft_no", "duplicate_of") if k2 not in st}
        await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {**st, "sales_stage_at": now}, **({"$unset": unset} if unset else {})})
    return dict(stats)




async def move_ap_invoices(db, days: int = 45, apply: bool = True) -> Dict[str, Any]:
    """Supplier invoices that reached the sales mailboxes go to AP, where the
    AP Inbox stages, drafts and routes them (the move is recorded)."""
    now = datetime.now(timezone.utc).isoformat()
    moved = 0
    async for d in db.hub_documents.find({"created_utc": {"$gte": (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()},
                                          "mailbox_category": {"$in": ["SALES", "Sales"]}, "sales_link.role": "ap_invoice"},
                                         {"_id": 1, "mailbox_category": 1}):
        moved += 1
        if apply:
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {
                "mailbox_category": "AP", "mailbox_category_previous": d["mailbox_category"],
                "mailbox_moved": {"from": d["mailbox_category"], "to": "AP", "at": now,
                                  "reason": "supplier invoice sent to a sales mailbox (sales_link role ap_invoice)"}}})
    return {"moved_to_ap": moved}
