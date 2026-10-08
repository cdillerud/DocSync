"""Read the Hub's sandbox drafts back from BC (BC -> Hub direction).

Hourly, read-only GETs against the draft environment: for every Hub
document drafted there, is the draft still in BC, still a Draft or has
AP posted / reopened it, and do header (vendor, vendor invoice number,
total) and lines still match what the Hub drafted? Differences are AP's
edits: they are recorded on the document (bc_draft_readback) and summed
per vendor (draft_edit_stats) so drafting can learn from them.
"""
import logging
import re
from collections import Counter
from datetime import datetime, timezone
from typing import Any, Dict

logger = logging.getLogger(__name__)


async def readback(db, limit: int = 200) -> Dict[str, Any]:
    import httpx
    import services.bc_catalog_sync_service as bc
    from services.sandbox_draft_service import ALLOWED_ENVIRONMENT
    env = ALLOWED_ENVIRONMENT
    token = await bc.get_bc_token(environment=env)
    now = datetime.now(timezone.utc).isoformat()
    stats = Counter()
    docs = [d async for d in db.hub_documents.find(
        {"bc_purchase_invoice.environment": env},
        {"_id": 1, "id": 1, "vendor_canonical": 1, "invoice_number_clean": 1, "amount_float": 1,
         "bc_purchase_invoice": 1, "draft_lines_planned": 1}).limit(limit)]
    if not docs:
        return {"drafts": 0}
    async with httpx.AsyncClient(timeout=60) as c:
        comps = (await c.get(f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/{env}/api/v2.0/companies",
                             headers={"Authorization": f"Bearer {token}"})).json().get("value", [])
        cid = next((x["id"] for x in comps if "gamer" in str(x.get("name", "")).lower()), comps[0]["id"] if comps else None)
        url = f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/{env}/api/v2.0/companies({cid})/purchaseInvoices"
        for d in docs:
            no = (d.get("bc_purchase_invoice") or {}).get("bc_record_no")
            if not no:
                continue
            r = await c.get(url, headers={"Authorization": f"Bearer {token}"}, params={
                "$filter": f"number eq '{no}'",
                "$expand": "purchaseInvoiceLines($select=lineType,lineObjectNumber,quantity,unitCost)",
                "$select": "number,status,vendorNumber,vendorInvoiceNumber,totalAmountIncludingTax"})
            if r.status_code != 200:
                stats["read_error"] += 1
                continue
            vals = r.json().get("value", [])
            stats["drafts"] += 1
            if not vals:
                # Not among unposted purchase invoices: deleted, or posted by AP.
                state = {"state": "gone", "note": "not found as an unposted purchase invoice (deleted or posted in BC)"}
                stats["gone"] += 1
            else:
                v = vals[0]
                lines = [l for l in v.get("purchaseInvoiceLines", []) if l.get("lineObjectNumber")]
                planned = d.get("draft_lines_planned") or []
                edits = []
                if str(v.get("vendorNumber") or "").upper() != str(d.get("vendor_canonical") or "").upper():
                    edits.append(f"vendor {d.get('vendor_canonical')} -> {v.get('vendorNumber')}")
                if str(v.get("vendorInvoiceNumber") or "").upper() != str(d.get("invoice_number_clean") or "").upper():
                    edits.append(f"invoice number {d.get('invoice_number_clean')} -> {v.get('vendorInvoiceNumber')}")
                if d.get("amount_float") is not None and abs(float(v.get("totalAmountIncludingTax") or 0) - abs(float(d["amount_float"]))) >= 0.02:
                    edits.append(f"total {d.get('amount_float')} -> {v.get('totalAmountIncludingTax')}")
                if planned:
                    p_items = Counter(str(l.get("lineObjectNumber") or "").upper() for l in planned if l.get("lineObjectNumber"))
                    b_items = Counter(str(l.get("lineObjectNumber") or "").upper() for l in lines)
                    if p_items != b_items:
                        edits.append(f"line items {dict(p_items)} -> {dict(b_items)}")
                state = {"state": str(v.get("status") or "").lower() or "unknown", "edits": edits,
                         "lines": [{k: l.get(k) for k in ("lineType", "lineObjectNumber", "quantity", "unitCost")} for l in lines]}
                stats["status_" + state["state"]] += 1
                stats["edited" if edits else "unchanged"] += 1
                if edits:
                    await db.draft_edit_stats.update_one(
                        {"vendor": d.get("vendor_canonical")},
                        {"$inc": {"edited": 1}, "$set": {"last_edit": edits, "updated_at": now}}, upsert=True)
            state["checked_at"] = now
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {"bc_draft_readback": state}})
    logger.info("[DraftReadback] %s", dict(stats))
    return dict(stats)




def _lines_by_item(ls):
    out = {}
    for l in ls or []:
        it = str(l.get("lineObjectNumber") or "").upper()
        if not it:
            continue
        a = out.setdefault(it, {"q": 0.0, "c": float(l.get("unitCost") or 0)})
        a["q"] += float(l.get("quantity") or 0)
    return out


async def grade_against_production(db) -> Dict[str, Any]:
    """Hub sandbox drafts that AP has since entered in Production BC: the
    draft's lines vs AP's (items, quantities, costs, total) - the real
    accuracy of AP drafting. Stored as ap_draft_vs_bc on the document."""
    import httpx
    import services.bc_catalog_sync_service as bc
    from services.sandbox_draft_service import ALLOWED_ENVIRONMENT
    now = datetime.now(timezone.utc).isoformat()
    docs = [d async for d in db.hub_documents.find(
        {"$or": [{"bc_purchase_invoice.environment": ALLOWED_ENVIRONMENT}, {"bc_purchase_invoice_removed.environment": ALLOWED_ENVIRONMENT}],
         "bc_link.bc_document_no": {"$exists": True}, "ap_draft_vs_bc": {"$exists": False}},
        {"_id": 1, "draft_lines_planned": 1, "bc_draft_readback": 1, "bc_link": 1, "amount_float": 1, "bc_purchase_invoice": 1,
         "bc_purchase_invoice_removed": 1})]
    if not docs:
        return {"graded": 0}
    token = await bc.get_bc_token(environment="Production")
    cid = await bc.get_bc_company_id(environment="Production")
    base = f"{bc.BC_API_BASE}/{bc.BC_TENANT_ID}/Production/api/{bc.BC_API_VERSION}/companies({cid})"
    stats = Counter()
    async with httpx.AsyncClient(timeout=60) as c:
        for d in docs:
            removed = d.get("bc_purchase_invoice_removed") or {}
            draft_lines = (d.get("bc_draft_readback") or {}).get("lines") or d.get("draft_lines_planned")
            if not d.get("bc_purchase_invoice"):
                # A draft removed because AP then entered the invoice in
                # Production is exactly what to grade (its lines were kept);
                # one removed for being wrong before AP saw it is not.
                if not (removed.get("lines") and re.search(r"Production BC already has|BC already has invoice", str(removed.get("reason") or ""))):
                    continue
                draft_lines = removed["lines"]
            no = d["bc_link"]["bc_document_no"]
            r = await c.get(f"{base}/purchaseInvoices", headers={"Authorization": f"Bearer {token}"}, params={
                "$filter": f"number eq '{no}'", "$expand": "purchaseInvoiceLines($select=lineObjectNumber,quantity,unitCost)",
                "$select": "number,status,totalAmountIncludingTax"})
            vals = r.json().get("value", []) if r.status_code == 200 else []
            if not vals:
                continue
            ap = _lines_by_item(vals[0].get("purchaseInvoiceLines"))
            hub = _lines_by_item(draft_lines)
            g = {"bc_document_no": no, "ap_items": len(ap), "items_right": len(set(ap) & set(hub)),
                 "missing": sorted(set(ap) - set(hub)), "extra": sorted(set(hub) - set(ap)),
                 "qty_right": sum(1 for it in set(ap) & set(hub) if abs(ap[it]["q"] - hub[it]["q"]) <= max(0.01, 0.002 * abs(ap[it]["q"]))),
                 "cost_right": sum(1 for it in set(ap) & set(hub) if abs(ap[it]["c"] - hub[it]["c"]) <= max(0.005, 0.005 * abs(ap[it]["c"]))),
                 "total_right": d.get("amount_float") is not None and abs(float(vals[0].get("totalAmountIncludingTax") or 0) - abs(float(d["amount_float"]))) < 0.02,
                 "graded_at": now}
            g["exact"] = not g["missing"] and not g["extra"] and g["qty_right"] == g["items_right"] and g["cost_right"] == g["items_right"]
            await db.hub_documents.update_one({"_id": d["_id"]}, {"$set": {"ap_draft_vs_bc": g}})
            stats["graded"] += 1
            stats["exact"] += bool(g["exact"])
    return dict(stats)


async def ap_draft_metrics(db) -> Dict[str, Any]:
    c = Counter()
    async for d in db.hub_documents.find({"ap_draft_vs_bc.graded_at": {"$exists": True}}, {"_id": 0, "ap_draft_vs_bc": 1}):
        g = d["ap_draft_vs_bc"]
        c["drafts"] += 1
        c["exact"] += bool(g.get("exact"))
        c["total_right"] += bool(g.get("total_right"))
        for k in ("ap_items", "items_right", "qty_right", "cost_right"):
            c[k] += int(g.get(k) or 0)
    return dict(c)
