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
            lines = [l for l in res.get("lines") or [] if l.get("item")] + list(res.get("charges") or [])
            if not lines or any(not l.get("quantity") for l in lines):
                await skip(d, "a line has no quantity")
                continue
            hist = [o.get("ship_to") or {} async for o in db.bc_sales_orders.find({"customer_no": cust}, {"_id": 0, "ship_to": 1}).sort([("order_no", -1)]).limit(40)]
            st = _ship_to(d, hist)
            header = {"customerNumber": cust, "externalDocumentNumber": po_text}
            od = str((d.get("extracted_fields") or {}).get("order_date") or "")[:10]
            if len(od) == 10 and od[4] == "-":
                header["orderDate"] = od
            if st:
                header.update({k: v for k, v in st.items() if v})
            r = await c.post(f"{base}/salesOrders", headers=h, json=header)
            if r.status_code not in (200, 201):
                await skip(d, f"BC refused the order header: {r.text[:200]}")
                continue
            so = r.json()
            sid, sno = so["id"], so["number"]
            errors = []
            for l in lines:
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
            todo = res.get("to_complete") or []
            if todo:
                note = "HUB: usually also on this customer's orders: " + ", ".join(
                    f"{t['item']} ({int(t['rate'] * 100)}%{', at shipping' if t.get('when') == 'shipping / invoicing' else ''})" for t in todo)
                for chunk in [note[i:i + 100] for i in range(0, min(len(note), 300), 100)]:
                    await c.post(f"{base}/salesOrders({sid})/salesOrderLines", headers=h, json={"lineType": "Comment", "description": chunk})
            # Read back: every planned line present with its quantity.
            rb = await c.get(f"{base}/salesOrders({sid})", headers=h, params={"$expand": "salesOrderLines"})
            got = [x for x in (rb.json().get("salesOrderLines") or []) if x.get("lineObjectNumber")] if rb.status_code == 200 else []
            ok = not errors and len(got) == len(lines) and all(
                any(str(g["lineObjectNumber"]).upper() == str(l["item"]).upper() and abs(float(g["quantity"]) - float(l["quantity"])) < 0.001
                    and (l.get("unit_price") is None or abs(float(g.get("unitPrice") or 0) - float(l["unit_price"])) < 0.005) for g in got)
                for l in lines)
            if not ok:
                dr = await c.delete(f"{base}/salesOrders({sid})", headers={**h, "If-Match": "*"})
                await skip(d, f"draft did not come out as planned ({'; '.join(errors)[:200] or 'lines differ'}); removed ({dr.status_code})")
                continue
            total = rb.json().get("totalAmountExcludingTax")
            await db.hub_documents.update_one({"id": d["id"]}, {"$set": {
                "sales_draft": {"environment": ALLOWED_ENVIRONMENT, "bc_order_no": sno, "bc_system_id": sid,
                                "customer_no": cust, "external_document_no": po_text, "ship_to_from_history": bool(st),
                                "lines": lines, "to_complete": res.get("to_complete") or [], "total": total, "created_at": now(), "status": "Draft"},
                "sales_stage": "drafted"}})
            await db.ap_workflow_events.insert_one({"document_id": d["id"], "action": "sales_order_draft", "by": "hub", "at": now(),
                                                    "environment": ALLOWED_ENVIRONMENT, "bc_record_no": sno,
                                                    "detail": {"customer": cust, "customer_po": po_text, "lines": len(lines), "total": total}})
            results.append({"document_id": d["id"], "bc_order_no": sno, "customer": cust, "customer_po": po_text, "lines": len(lines), "total": total})
    return {"drafted": sum(1 for r in results if r.get("bc_order_no")), "results": results}

