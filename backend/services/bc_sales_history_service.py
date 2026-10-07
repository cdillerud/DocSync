"""Gamer's sales history from Production BC (read-only): the ground truth
for the sales module.

One record per BC sales order in `bc_sales_orders`, keyed by order number:
customer, customer PO (externalDocumentNumber), ship-to, salesperson, order
date and lines (item, quantity, unit of measure, unit price, location).
Open orders come from salesOrders; shipped/invoiced orders from posted
salesInvoices (each invoice carries its orderNumber and customer PO), so a
customer PO e-mailed to sales can be linked to the order inside sales
entered, and customer items / prices / ship-tos learned from what BC holds.

Full load: open orders + invoices of the last `days` days. Then hourly,
incremental by lastModifiedDateTime.
"""
import logging
import re
from datetime import date, datetime, timedelta, timezone
from typing import Any, Dict, List

logger = logging.getLogger(__name__)

_LINE_KEYS = ("lineType", "lineObjectNumber", "description", "quantity", "unitOfMeasureCode", "unitPrice",
              "discountPercent", "amountExcludingTax", "locationId", "shipmentDate")


def norm(x: Any) -> str:
    return re.sub(r"[^A-Z0-9]", "", str(x or "").upper()).lstrip("0")


def ext_tokens(x: Any) -> List[str]:
    """Match keys of a customer PO as BC holds it: "24511797-A",
    "PO26-2013-4", "P0028021-12/W118480", "103083, 103086, 103087" ->
    each part, with and without a short suffix and a PO prefix."""
    out = set()
    for part in re.split(r"[,;/&]+|\s+(?=\S)", str(x or "")):
        part = part.strip()
        if not part:
            continue
        bases = {part, re.sub(r"-[A-Z0-9]{1,2}$", "", part, flags=re.I)}
        for b in bases:
            n = norm(b)
            if len(n) >= 3:
                out.add(n)
                for p in ("PO", "P0"):
                    if n.startswith(p) and len(n) - len(p) >= 3:
                        out.add(n[len(p):].lstrip("0"))
    return sorted(out)


def _lines(ls: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    out = []
    for l in ls or []:
        if not l.get("lineObjectNumber") and l.get("lineType") != "Comment":
            continue
        out.append({k: l.get(k) for k in _LINE_KEYS})
    return out


def _ship_to(v: Dict[str, Any]) -> Dict[str, Any]:
    return {k: v.get(k) for k in ("shipToName", "shipToContact", "shipToAddressLine1", "shipToAddressLine2",
                                  "shipToCity", "shipToState", "shipToPostCode", "shipToCountry")}


async def _pages(client, url, headers, params):
    while url:
        r = await client.get(url, headers=headers, params=params)
        if r.status_code != 200:
            raise RuntimeError(f"BC {r.status_code}: {r.text[:200]}")
        j = r.json()
        for v in j.get("value", []):
            yield v
        url, params = j.get("@odata.nextLink"), None


async def sync(db, days: int = 365, full: bool = False) -> Dict[str, Any]:
    import httpx
    import services.bc_catalog_sync_service as bc
    token = await bc.get_bc_token(environment="Production")
    cid = await bc.get_bc_company_id(environment="Production")
    base = f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/Production/api/{bc.BC_API_VERSION}/companies({cid})"
    # Server-driven paging: $top would return one page with no nextLink.
    h = {"Authorization": f"Bearer {token}", "Prefer": "odata.maxpagesize=200"}
    state = await db.bc_sales_sync_state.find_one({"_id": "state"}) or {}
    now = datetime.now(timezone.utc).isoformat()
    stats = {"open_orders": 0, "invoices": 0}
    await db.bc_sales_orders.create_index("order_no", unique=True)
    await db.bc_sales_orders.create_index("ext_norm")
    await db.bc_sales_orders.create_index("ext_tokens")
    await db.bc_sales_orders.create_index("customer_no")

    async with httpx.AsyncClient(timeout=120) as c:
        # Open orders: always a full pass (1-2k), so closed/deleted ones can be marked.
        open_nos = set()
        async for v in _pages(c, f"{base}/salesOrders", h, {"$expand": "salesOrderLines"}):
            ls = v.pop("salesOrderLines", [])
            open_nos.add(v["number"])
            await db.bc_sales_orders.update_one({"order_no": v["number"]}, {"$set": {
                "order_no": v["number"], "status": "open", "customer_no": v.get("customerNumber"),
                "customer_name": v.get("customerName"), "external_doc_no": v.get("externalDocumentNumber"),
                "ext_norm": norm(v.get("externalDocumentNumber")),
                "ext_tokens": ext_tokens(v.get("externalDocumentNumber")), "order_date": v.get("orderDate"),
                "requested_delivery_date": v.get("requestedDeliveryDate"), "ship_to": _ship_to(v),
                "salesperson": v.get("salesperson"), "currency": v.get("currencyCode") or "USD",
                "total": v.get("totalAmountExcludingTax"), "lines": _lines(ls),
                "bc_modified": v.get("lastModifiedDateTime"), "synced_at": now}}, upsert=True)
            stats["open_orders"] += 1
        await db.bc_sales_orders.update_many({"status": "open", "order_no": {"$nin": list(open_nos)}},
                                             {"$set": {"status": "closed_or_invoiced", "synced_at": now}})

        # Posted invoices: incremental.
        since_mod = None if full else state.get("invoices_modified")
        flt = (f"lastModifiedDateTime gt {since_mod}" if since_mod
               else f"postingDate ge {(date.today() - timedelta(days=days)).isoformat()}")
        newest = since_mod
        async for v in _pages(c, f"{base}/salesInvoices", h, {"$filter": flt, "$expand": "salesInvoiceLines"}):
            ls = v.pop("salesInvoiceLines", [])
            key = v.get("orderNumber") or f"INV-{v['number']}"
            inv = {"invoice_no": v["number"], "posting_date": v.get("postingDate"), "total": v.get("totalAmountExcludingTax"),
                   "lines": _lines(ls)}
            existing = await db.bc_sales_orders.find_one({"order_no": key}, {"_id": 0, "status": 1, "lines": 1, "invoices": 1})
            invoices = [i for i in (existing or {}).get("invoices") or [] if i.get("invoice_no") != v["number"]] + [inv]
            upd = {"order_no": key, "customer_no": v.get("customerNumber"), "customer_name": v.get("customerName"),
                   "external_doc_no": v.get("externalDocumentNumber"), "ext_norm": norm(v.get("externalDocumentNumber")),
                   "ext_tokens": ext_tokens(v.get("externalDocumentNumber")), "ship_to": _ship_to(v), "salesperson": v.get("salesperson"), "currency": v.get("currencyCode") or "USD",
                   "invoices": invoices, "first_invoice_date": min(i["posting_date"] for i in invoices if i.get("posting_date")),
                   "synced_at": now}
            if not existing or existing.get("status") != "open":
                # Lines of an invoiced order: all its invoices' lines together.
                upd["status"] = "invoiced"
                upd["lines"] = [l for i in invoices for l in i["lines"]]
            await db.bc_sales_orders.update_one({"order_no": key}, {"$set": upd}, upsert=True)
            stats["invoices"] += 1
            if not newest or str(v.get("lastModifiedDateTime")) > str(newest):
                newest = v.get("lastModifiedDateTime")
        await db.bc_sales_sync_state.update_one({"_id": "state"}, {"$set": {
            "invoices_modified": newest, "synced_at": now}}, upsert=True)
    stats["orders_total"] = await db.bc_sales_orders.estimated_document_count()
    logger.info("[BCSalesHistory] %s", stats)
    return stats

