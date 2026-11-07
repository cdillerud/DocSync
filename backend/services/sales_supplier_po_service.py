"""Supplier POs for bulk orders: the purchase side of a split customer PO.

Horseshoe, as BC shows it: each Horseshoe PO line becomes one Ball PO
(W119331 ... - 254 entered by hand on 2026-10-19, about 3 hours), shipped to
the Horseshoe Consignment location; Ball ships into consignment, the receipt
is posted, and the sales order is entered as "P0028016-47/W118789" - the PO
line it draws from. Nothing here is listed per customer:

- the supplier: the vendor on the receipts of the W numbers this customer's
  sales orders name (HORSESH -> BALLCOR on 561 receipts);
- the PO template, per item: the supplier's latest Production PO carrying
  the item (ship-to, location, department, payment terms, shipment method,
  comment lines, DUNNAGEMGMT 0, cost). Graded on 213 of ASAUM's 10-19 POs:
  quantity, comments, charge lines and location equal on all 213; cost is
  the one thing the buyer confirms (130.53 -> 132.98 on 10-19).

SANDBOX ONLY, with the same guards as sales drafting. Production reads
(GET) only, to learn the template.
"""
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

_HEADER_COPY = ("shipToName", "shipToContact", "shipToAddressLine1", "shipToAddressLine2", "shipToCity", "shipToState",
                "shipToCountry", "shipToPostCode", "shortcutDimension1Code", "shortcutDimension2Code", "paymentTermsId",
                "shipmentMethodId", "currencyCode")
# Set after the lines: BC refills these from the location as the PO is built
# (contact "Receiving"). The buy-from address is not set: the buyer's PO
# orders from Ball's Pittston order address, which API v2.0 cannot select,
# and writing the address copies it into the read-only pay-to address (where
# Ball is paid, Westminster) - the review screen tells the buyer instead.
_HEADER_AFTER = ("shipToContact", "purchaser")
_W = re.compile(r"/\s*(W\d+)")


async def supplier_of(db, customer_no: str) -> Optional[Dict[str, Any]]:
    """The vendor whose receipts carry the PO numbers this customer's sales orders name."""
    ws = set()
    async for o in db.bc_sales_orders.find({"customer_no": customer_no, "external_doc_no": {"$regex": r"/\s*W\d+"}},
                                           {"_id": 0, "external_doc_no": 1}):
        m = _W.search(o["external_doc_no"])
        if m:
            ws.add(m.group(1))
    if not ws:
        return None
    c = Counter()
    async for r in db.bc_purchase_receipts.find({"orderNumber": {"$in": list(ws)}}, {"_id": 0, "vendorNumber": 1}):
        c[r["vendorNumber"]] += 1
    if not c:
        return None
    v, n = c.most_common(1)[0]
    if n / sum(c.values()) < 0.8:
        return None
    return {"vendor_no": v, "receipts": n, "linked_orders": len(ws)}


def _prod_lines(p):
    from services.sales_item_xref_service import is_product
    return [l for l in p.get("purchaseOrderLines") or [] if l.get("lineType") == "Item" and is_product(str(l.get("lineObjectNumber") or ""))]


async def _vendor_pos(vendor_no: str) -> List[Dict[str, Any]]:
    """The supplier's open Production POs with lines (GET only)."""
    import httpx
    from services.sales_draft_service import _bc
    base, h = await _bc("Production")
    out, url = [], f"{base}/purchaseOrders"
    params = {"$filter": f"vendorNumber eq '{vendor_no}'", "$expand": "purchaseOrderLines"}
    async with httpx.AsyncClient(timeout=120) as c:
        while url:
            r = await c.get(url, headers={"Authorization": h["Authorization"]}, params=params)
            r.raise_for_status()
            j = r.json()
            out += j.get("value") or []
            url, params = j.get("@odata.nextLink"), None
    return out


def _template_from(pos: List[Dict[str, Any]], item: str) -> Optional[Dict[str, Any]]:
    from services.sales_item_xref_service import load_item_categories  # noqa: F401 (categories loaded by caller)
    cand = []
    for p in pos:
        pl = _prod_lines(p)
        if len(pl) == 1 and str(pl[0]["lineObjectNumber"]).upper() == item.upper():
            cand.append((p, pl[0]))
    if not cand:
        return None
    # How this item is usually bought (ship-to, location): one-off POs
    # (a drop shipment made from a sales order, a test) don't set the pattern.
    kind = Counter((p.get("shipToName"), l.get("locationId")) for p, l in cand).most_common(1)[0][0]
    best = None
    for p, l in cand:
        if (p.get("shipToName"), l.get("locationId")) != kind:
            continue
        pl = [l]
        key = (p.get("orderDate") or "", p.get("lastModifiedDateTime") or "", p["number"])
        if best is None or key > best[0]:
            best = (key, p, pl[0])
    if not best:
        return None
    _, p, prod = best
    ls = p["purchaseOrderLines"]
    return {"po_no": p["number"], "order_date": p.get("orderDate"), "header": {k: p[k] for k in _HEADER_COPY if p.get(k) not in (None, "")},
            "header_after": {k: p[k] for k in _HEADER_AFTER if p.get(k) not in (None, "")},
            "order_address": (f"{p.get('vendorName')}, {p.get('buyFromAddressLine1')}, {p.get('buyFromCity')} {p.get('buyFromState')}"
                              if p.get("buyFromAddressLine1") and p.get("buyFromAddressLine1") != p.get("payToAddressLine1") else None),
            "cost": float(prod.get("directUnitCost") or 0), "unit_of_measure": prod.get("unitOfMeasureCode") or None,
            "location_id": prod.get("locationId"),
            "comments": [str(l.get("description") or "") for l in ls if l.get("lineType") == "Comment" and str(l.get("description") or "").strip()],
            "charges": [{"item": l["lineObjectNumber"], "quantity": float(l.get("quantity") or 0), "cost": float(l.get("directUnitCost") or 0),
                         "unit_of_measure": l.get("unitOfMeasureCode") or None, "location_id": l.get("locationId")}
                        for l in ls if l.get("lineType") == "Item" and l is not prod and l.get("lineObjectNumber")]}


async def plan(db, doc_id: str) -> Dict[str, Any]:
    from services.sales_bulk_order_service import plan as sales_plan
    from services.sales_item_xref_service import load_item_categories
    await load_item_categories(db)
    p = await sales_plan(db, doc_id)
    if p.get("error"):
        return {"error": p["error"]}
    sup = await supplier_of(db, p["customer_no"])
    if not sup:
        return {"error": "No supplier learned: this customer's sales orders name no received supplier POs"}
    pos = await _vendor_pos(sup["vendor_no"])
    linked = set()
    async for o in db.bc_sales_orders.find({"customer_no": p["customer_no"], "external_doc_no": {"$regex": r"/\s*W\d+"}}, {"_id": 0, "external_doc_no": 1}):
        linked.add(_W.search(o["external_doc_no"]).group(1))
    templates, problems, orders = {}, list(p.get("problems") or []), []
    for o in p["orders"]:
        it = o["item"]
        if it not in templates:
            templates[it] = _template_from(pos, it)
            if not templates[it]:
                problems.append(f"no {sup['vendor_no']} PO in BC carries {it}")
        if templates[it]:
            orders.append({"line": o["line"], "external_document_no": o["external_document_no"], "item": it, "quantity": o["quantity"]})
    open_unlinked = Counter()
    for po in pos:
        pl = _prod_lines(po)
        if len(pl) == 1 and po["number"] not in linked and not any(float(l.get("receivedQuantity") or 0) for l in pl):
            open_unlinked[str(pl[0]["lineObjectNumber"]).upper()] += 1
    items = sorted(templates)
    return {"document_id": doc_id, "customer_no": p["customer_no"], "customer_po": p["customer_po"], "supplier": sup,
            "orders": orders, "items": items, "problems": problems,
            "costs": {it: {"template": (templates[it] or {}).get("cost"), "template_po": (templates[it] or {}).get("po_no"),
                           "template_date": (templates[it] or {}).get("order_date")} for it in items},
            "templates": templates,
            # Supplier POs for these items already open and not yet drawn by a
            # sales order: the buyer may have entered this PO already.
            "open_unreceived_supplier_pos": {it: open_unlinked.get(it.upper(), 0) for it in items}}


async def _set_cost(c, base, h, pid, line, cost) -> Optional[str]:
    r = await c.patch(f"{base}/purchaseOrders({pid})/purchaseOrderLines({line['id']})", headers={**h, "If-Match": "*"},
                      json={"directUnitCost": cost})
    return None if r.status_code < 300 else r.text[:160]


async def _link(c, base, h, so, pno) -> Dict[str, Any]:
    """The sales order names the supplier PO it draws from: "P0030198-1/W119643"."""
    new_ext = f"{so['external_document_no']}/{pno}"[:35]
    pr = await c.patch(f"{base}/salesOrders({so['bc_system_id']})", headers={**h, "If-Match": "*"},
                       json={"externalDocumentNumber": new_ext})
    return {"bc_order_no": so.get("bc_order_no"), "external_document_no": new_ext,
            "ok": pr.status_code < 300, "error": None if pr.status_code < 300 else pr.text[:160]}


async def create(db, doc_id: str, costs: Dict[str, float], user: Optional[Dict[str, Any]] = None,
                 link_sales_orders: bool = True) -> Dict[str, Any]:
    """One supplier PO per PO line in the PRE sandbox, then the sandbox sales
    order made for that line is linked as "<ext>/<PO no>". Never Production."""
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
        v = costs.get(it)
        if v is None or float(v) <= 0:
            return {"created": 0, "refused": f"confirm a cost for {it}"}
    d = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "sales_supplier_pos": 1, "sales_bulk_orders": 1})
    done = {o["po_line_no"]: o for o in ((d or {}).get("sales_supplier_pos") or {}).get("orders") or [] if o.get("ok")}
    so_by_line = {o["po_line_no"]: o for o in ((d or {}).get("sales_bulk_orders") or {}).get("orders") or []}
    base, h = await _bc(ALLOWED_ENVIRONMENT)
    now = datetime.now(timezone.utc).isoformat()
    made, failed = list(done.values()), []
    async with httpx.AsyncClient(timeout=90) as c:
        for o in p["orders"]:
            if o["external_document_no"] in done:
                # idempotent: this line's supplier PO was made already; link
                # its sales order if that was not done then.
                rec0 = done[o["external_document_no"]]
                so = so_by_line.get(o["external_document_no"])
                if link_sales_orders and so and not (rec0.get("linked_sales_order") or {}).get("ok"):
                    rec0["linked_sales_order"] = await _link(c, base, h, so, rec0["bc_po_no"])
                continue
            t = p["templates"][o["item"]]
            r = await c.post(f"{base}/purchaseOrders", headers=h, json={"vendorNumber": p["supplier"]["vendor_no"], **t["header"]})
            if r.status_code not in (200, 201):
                failed.append({"po_line_no": o["external_document_no"], "error": r.text[:200]})
                break
            po = r.json()
            pid, pno = po["id"], po["number"]
            loc = {"locationId": t["location_id"]} if t.get("location_id") else {}
            lines = [{"lineType": "Item", "lineObjectNumber": o["item"], "quantity": float(o["quantity"]), "directUnitCost": float(costs[o["item"]]),
                      **({"unitOfMeasureCode": t["unit_of_measure"]} if t.get("unit_of_measure") else {}), **loc}]
            lines += [{"lineType": "Comment", "description": cm[:100]} for cm in t["comments"]]
            lines += [{"lineType": "Item", "lineObjectNumber": ch["item"], "quantity": ch["quantity"], "directUnitCost": ch["cost"],
                       **({"unitOfMeasureCode": ch["unit_of_measure"]} if ch.get("unit_of_measure") else {}),
                       **({"locationId": ch["location_id"]} if ch.get("location_id") else {})} for ch in t["charges"]]
            errors = []
            for body in lines:
                lr = await c.post(f"{base}/purchaseOrders({pid})/purchaseOrderLines", headers=h, json=body)
                if lr.status_code not in (200, 201):
                    errors.append(f"{body.get('lineObjectNumber') or 'comment'}: {lr.text[:160]}")
                elif "directUnitCost" in body and abs(float(lr.json().get("directUnitCost") or 0) - body["directUnitCost"]) >= 0.005:
                    # BC reprices from the vendor's price list as the line is
                    # validated (132.95, DUNNAGEMGMT 0.45); the buyer overtypes
                    # it with the confirmed cost (132.98, 0), so does the Hub.
                    pr = await _set_cost(c, base, h, pid, lr.json(), body["directUnitCost"])
                    if pr:
                        errors.append(f"{body['lineObjectNumber']} cost: {pr}")
            if t.get("header_after"):
                hr = await c.patch(f"{base}/purchaseOrders({pid})", headers={**h, "If-Match": "*"}, json=t["header_after"])
                if hr.status_code >= 300:
                    errors.append(f"header: {hr.text[:160]}")
            rb = await c.get(f"{base}/purchaseOrders({pid})", headers=h, params={"$expand": "purchaseOrderLines"})
            got = [x for x in (rb.json().get("purchaseOrderLines") or []) if x.get("lineObjectNumber")] if rb.status_code == 200 else []
            if rb.status_code == 200 and any(rb.json().get(k) != v for k, v in (t.get("header_after") or {}).items()):
                errors.append("header differs on read back")
            want = [b for b in lines if b["lineType"] == "Item"]
            ok = not errors and len(got) == len(want) and all(
                any(str(g["lineObjectNumber"]).upper() == str(b["lineObjectNumber"]).upper() and abs(float(g["quantity"]) - b["quantity"]) < 0.001
                    and abs(float(g.get("directUnitCost") or 0) - b["directUnitCost"]) < 0.005
                    and (not b.get("locationId") or g.get("locationId") == b["locationId"]) for g in got) for b in want)
            rec = {"po_line_no": o["external_document_no"], "item": o["item"], "bc_po_no": pno, "bc_system_id": pid, "ok": ok,
                   "errors": errors, "total": rb.json().get("totalAmountExcludingTax") if rb.status_code == 200 else None,
                   "template_po": t["po_no"], "linked_sales_order": None}
            # Link the sandbox sales order for this line the way inside sales does.
            so = so_by_line.get(o["external_document_no"])
            if ok and link_sales_orders and so and so.get("bc_system_id"):
                rec["linked_sales_order"] = await _link(c, base, h, so, pno)
            made.append(rec)
            if not ok:
                failed.append({"po_line_no": o["external_document_no"], "error": "; ".join(errors)[:200] or "lines differ on read back"})
                break
    rec = {"environment": ALLOWED_ENVIRONMENT, "at": now, "by": (user or {}).get("email"), "supplier": p["supplier"]["vendor_no"],
           "costs": costs, "orders": made, "failed": failed}
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {"sales_supplier_pos": rec}})
    await db.ap_workflow_events.insert_one({"document_id": doc_id, "action": "sales_supplier_pos", "by": rec["by"] or "hub", "at": now,
                                            "environment": ALLOWED_ENVIRONMENT,
                                            "detail": {"customer": p["customer_no"], "customer_po": p["customer_po"], "supplier": rec["supplier"],
                                                       "created": len(made) - len(done), "failed": failed[:3]}})
    logger.info("[SalesSupplierPOs] %s %s %s created=%d failed=%d", p["customer_no"], p["customer_po"], rec["supplier"], len(made) - len(done), len(failed))
    return {"created": len(made) - len(done), "already": len(done), "failed": failed, "orders": made, "environment": ALLOWED_ENVIRONMENT}
