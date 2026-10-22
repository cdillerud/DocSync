"""Draft (never release or ship) BC sales orders in the PRE sandbox from
customer POs, for inside sales to review. Agreed 2026-10-07 (same model
as AP drafting).

Only documents whose sales_stage is "ready": customer linked to BC, a
customer PO, and every product line matched to a Gamer item (learned
cross-reference, item number on the PO or the customer's own items).
Before writing: Production BC must not already hold an order with this
customer PO for this customer (inside sales may have entered it since).
After writing: the draft is read back; a draft whose lines or total do
not match what was planned is deleted and the PO goes to a rep.

Guards: the same as AP sandbox drafting (PRE only, BC_WRITE_ENABLED,
never Production) plus SALES_DRAFTING_PAUSED (default "true").
"""
import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)


def refusal() -> str:
    from services.sandbox_draft_service import refusal as ap_refusal, ALLOWED_ENVIRONMENT, write_target
    if os.environ.get("SALES_DRAFTING_PAUSED", "true").strip().lower() == "true":
        return "Sales drafting is paused (SALES_DRAFTING_PAUSED)"
    if os.environ.get("BC_WRITE_ENABLED", "false").strip().lower() != "true":
        return "BC writes are disabled (BC_WRITE_ENABLED is not true)"
    if write_target() != ALLOWED_ENVIRONMENT or "prod" in write_target().lower():
        return f"Write environment is '{write_target()}', drafting is only allowed in '{ALLOWED_ENVIRONMENT}'"
    return ""


async def _bc(env: str):
    import services.bc_catalog_sync_service as bc
    import httpx
    token = await bc.get_bc_token(environment=env)
    async with httpx.AsyncClient(timeout=60) as c:
        comps = (await c.get(f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/{env}/api/v2.0/companies",
                             headers={"Authorization": f"Bearer {token}"})).json().get("value", [])
    cid = next((x["id"] for x in comps if "gamer" in str(x.get("name", "")).lower()), comps[0]["id"] if comps else None)
    return f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/{env}/api/v2.0/companies({cid})", {"Authorization": f"Bearer {token}", "Content-Type": "application/json"}


# Customers whose POs inside sales enters as one BC order per PO line
# ("P0028021-1/W118463", "-2", ...): learned from BC, not listed.
SPLIT_PER_LINE = True
_SPLIT_EXT = None


async def splits_per_line(db, customer_no: str) -> bool:
    """>= 80% of the customer's recent orders are numbered PO-n with the PO
    on 2+ orders, and >= 80% carry a single product line (Horseshoe 95% /
    97%; Millennium splits by delivery but keeps 3 lines: not this)."""
    import re
    from datetime import timedelta
    from services.sales_item_xref_service import is_product
    since = (datetime.now(timezone.utc) - timedelta(days=180)).date().isoformat()
    orders = [o async for o in db.bc_sales_orders.find({"customer_no": customer_no, "order_date": {"$gte": since}},
                                                       {"_id": 0, "external_doc_no": 1, "lines": 1})]
    if len(orders) < 5:
        return False
    rx = re.compile(r"^\s*([A-Z0-9]+?)\s*-\s*(\d{1,3})(?:\s*/.*)?$", re.I)
    bases: Dict[str, int] = {}
    for o in orders:
        m = rx.match(str(o.get("external_doc_no") or ""))
        if m:
            bases[m.group(1).upper()] = bases.get(m.group(1).upper(), 0) + 1
    split_share = sum(n for n in bases.values() if n >= 2) / len(orders)
    single = sum(1 for o in orders if sum(1 for l in o.get("lines") or []
                                          if l.get("lineType") == "Item" and is_product(l.get("lineObjectNumber"))) == 1) / len(orders)
    return split_share >= 0.8 and single >= 0.8


def _split_base(sl: Dict[str, Any], po_text: str) -> str:
    """The PO as inside sales writes it before "-n": the customer_po token
    with its letter prefix (P0030199, not "P0030199, Rev. 1" or 30199)."""
    import re
    toks = [str(t).upper() for t in sl.get("customer_po") or [] if t]
    lettered = [t for t in toks if re.match(r"^[A-Z]", t)]
    return (max(lettered, key=len) if lettered else (max(toks, key=len) if toks else re.split(r"[,\s]", po_text)[0]))


def _ship_to(d: Dict[str, Any], history: List[Dict[str, Any]]) -> Optional[Dict[str, Any]]:
    """A ship-to this customer has used in BC whose postal code / city is on the PO."""
    text = str((d.get("extracted_fields") or {}).get("ship_to") or "").upper()
    if not text:
        return None
    for st in history:
        pc = str(st.get("shipToPostCode") or "").upper()[:5]
        if pc and pc in text and str(st.get("shipToCity") or "").upper() in text:
            return st
    return None


async def candidates(db, limit: int = 10, per_customer: int = 3) -> List[Dict[str, Any]]:
    """Newest first, at most `per_customer` per customer per run (Giovanni
    sends one PO per truck and would otherwise fill every run)."""
    ready = [d async for d in db.hub_documents.find(
        {"sales_stage": "ready", "sales_draft.bc_order_no": {"$exists": False}, "sales_draft_skipped": {"$exists": False}},
        {"_id": 0, "file_content_b64": 0}).sort([("created_utc", -1)])]
    out, per = [], {}
    for d in ready:                      # every customer gets a turn first
        c = (d.get("sales_link") or {}).get("bc_customer_no")
        if per.get(c, 0) < per_customer:
            per[c] = per.get(c, 0) + 1
            out.append(d)
    out += [d for d in ready if d not in out]   # then fill the run
    return out[:limit]


async def draft(db, limit: int = 5) -> Dict[str, Any]:
    import httpx
    from services.sandbox_draft_service import ALLOWED_ENVIRONMENT
    reason = refusal()
    if reason:
        return {"drafted": 0, "refused": reason}
    now = lambda: datetime.now(timezone.utc).isoformat()
    base, h = await _bc(ALLOWED_ENVIRONMENT)
    results = []

    async def skip(d, why):
        await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"sales_draft_skipped": {"reason": why, "at": now()}}})
        results.append({"document_id": d["id"], "skipped": why})

    async with httpx.AsyncClient(timeout=90) as c:
        for d in await candidates(db, limit * 2):
            if len([r for r in results if r.get("bc_order_no")]) >= limit:
                break
            sl, res = d["sales_link"], d.get("sales_resolution") or {}
            cust = sl["bc_customer_no"]
            po_text = str((d.get("extracted_fields") or {}).get("po_number") or sl["customer_po"][0])[:35]
            # Inside sales may have entered it since the last link run.
            tokens = list(sl.get("customer_po") or [])
            prod = await db.bc_sales_orders.find_one({"customer_no": cust, "ext_tokens": {"$in": tokens}}, {"_id": 0, "order_no": 1})
            if prod:
                await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"sales_link.order_no": prod["order_no"], "sales_link.match": "customer_po", "sales_stage": "in_bc"}})
                continue
            prods = [l for l in res.get("lines") or [] if l.get("item")]
            lines = prods + list(res.get("charges") or [])
            if not lines or any(not l.get("quantity") for l in lines):
                await skip(d, "a line has no quantity")
                continue
            hist = [o.get("ship_to") or {} async for o in db.bc_sales_orders.find({"customer_no": cust}, {"_id": 0, "ship_to": 1}).sort([("order_no", -1)]).limit(40)]
            st = _ship_to(d, hist)
            # One order per PO line for a customer inside sales enters that
            # way (Horseshoe: P0028021-1 ... -13, one can line each, 140 of
            # 144 orders), each with its own charges.
            groups = [(po_text, lines)]
            if SPLIT_PER_LINE and len(prods) > 1 and await splits_per_line(db, cust):
                from services.sales_charge_service import charge_lines
                base_po = _split_base(sl, po_text)
                el = (d.get("extracted_fields") or {}).get("line_items") or []
                groups = [(f"{base_po}-{n}"[:35], [l] + await charge_lines(db, cust, [l], el)) for n, l in enumerate(prods, 1)]
            made, failed = [], None
            for ext, glines in groups:
                header = {"customerNumber": cust, "externalDocumentNumber": ext}
                od = str((d.get("extracted_fields") or {}).get("order_date") or "")[:10]
                if len(od) == 10 and od[4] == "-":
                    header["orderDate"] = od
                if st:
                    header.update({k: v for k, v in st.items() if v})
                r = await c.post(f"{base}/salesOrders", headers=h, json=header)
                if r.status_code not in (200, 201):
                    failed = f"BC refused the order header: {r.text[:200]}"
                    break
                so = r.json()
                sid, sno = so["id"], so["number"]
                made.append({"bc_order_no": sno, "bc_system_id": sid, "external_document_no": ext, "lines": glines})
                errors = []
                for l in glines:
                    body = {"lineType": "Item", "lineObjectNumber": l["item"], "quantity": float(l["quantity"])}
                    if l.get("unit_price") is not None:
                        body["unitPrice"] = float(l["unit_price"])
                    if l.get("unit_of_measure"):
                        body["unitOfMeasureCode"] = l["unit_of_measure"]
                    lr = await c.post(f"{base}/salesOrders({sid})/salesOrderLines", headers=h, json=body)
                    if lr.status_code not in (200, 201):
                        errors.append(f"{l['item']}: {lr.text[:160]}")
                # What the rep still has to add (dunnage, irregular charges): a
                # comment line on the draft, where they finish the order in BC.
                gitems = {str(l.get("item")).upper() for l in glines}
                checks = [f"{l['item']}: {l['price_check']}" for l in res.get("lines") or [] if l.get("price_check") and str(l.get("item")).upper() in gitems]
                if checks:
                    note = "HUB: check price - " + "; ".join(dict.fromkeys(checks))
                    for chunk in [note[i:i + 100] for i in range(0, min(len(note), 300), 100)]:
                        await c.post(f"{base}/salesOrders({sid})/salesOrderLines", headers=h, json={"lineType": "Comment", "description": chunk})
                todo = [t for t in res.get("to_complete") or [] if str(t.get("item")).upper() not in gitems]
                if todo:
                    note = "HUB: usually also on this customer's orders: " + ", ".join(
                        f"{t['item']} ({int(t['rate'] * 100)}%{', at shipping' if t.get('when') == 'shipping / invoicing' else ''})" for t in todo)
                    for chunk in [note[i:i + 100] for i in range(0, min(len(note), 300), 100)]:
                        await c.post(f"{base}/salesOrders({sid})/salesOrderLines", headers=h, json={"lineType": "Comment", "description": chunk})
                # Read back: every planned line present with its quantity.
                rb = await c.get(f"{base}/salesOrders({sid})", headers=h, params={"$expand": "salesOrderLines"})
                got = [x for x in (rb.json().get("salesOrderLines") or []) if x.get("lineObjectNumber")] if rb.status_code == 200 else []
                ok = not errors and len(got) == len(glines) and all(
                    any(str(g["lineObjectNumber"]).upper() == str(l["item"]).upper() and abs(float(g["quantity"]) - float(l["quantity"])) < 0.001
                        and (l.get("unit_price") is None or abs(float(g.get("unitPrice") or 0) - float(l["unit_price"])) < 0.005) for g in got)
                    for l in glines)
                if not ok:
                    failed = f"draft did not come out as planned ({'; '.join(errors)[:200] or 'lines differ'})"
                    break
                made[-1]["total"] = rb.json().get("totalAmountExcludingTax")
            if failed:
                # All or nothing: a PO half drafted is worse than none.
                codes = []
                for m in made:
                    dr = await c.delete(f"{base}/salesOrders({m['bc_system_id']})", headers={**h, "If-Match": "*"})
                    codes.append(str(dr.status_code))
                await skip(d, f"{failed}; removed ({', '.join(codes) or 'nothing created'})")
                continue
            first = made[0]
            total = round(sum(float(m.get("total") or 0) for m in made), 2)
            draft_rec = {"environment": ALLOWED_ENVIRONMENT, "bc_order_no": first["bc_order_no"], "bc_system_id": first["bc_system_id"],
                         "customer_no": cust, "external_document_no": first["external_document_no"], "ship_to_from_history": bool(st),
                         "lines": lines if len(made) == 1 else [l for m in made for l in m["lines"]],
                         "to_complete": res.get("to_complete") or [], "total": total, "created_at": now(), "status": "Draft"}
            if len(made) > 1:
                draft_rec["orders"] = [{k: m.get(k) for k in ("bc_order_no", "bc_system_id", "external_document_no", "total")} for m in made]
                draft_rec["split_per_line"] = True
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {"sales_draft": draft_rec, "sales_stage": "drafted"}})
            await db.ap_workflow_events.insert_one({"document_id": d["id"], "action": "sales_order_draft", "by": "hub", "at": now(),
                                                    "environment": ALLOWED_ENVIRONMENT, "bc_record_no": first["bc_order_no"],
                                                    "detail": {"customer": cust, "customer_po": po_text, "lines": len(draft_rec["lines"]), "total": total,
                                                               "orders": [m["bc_order_no"] for m in made]}})
            results.append({"document_id": d["id"], "bc_order_no": first["bc_order_no"], "orders": [m["bc_order_no"] for m in made],
                            "customer": cust, "customer_po": po_text, "lines": len(draft_rec["lines"]), "total": total})
    return {"drafted": sum(1 for r in results if r.get("bc_order_no")), "results": results}

