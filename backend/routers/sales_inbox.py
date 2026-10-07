"""Sales Inbox API: one stage per sales-mailbox document (sales_stage_service)."""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter

from deps import get_db
from services.sales_stage_service import REASONS

router = APIRouter(prefix="/sales-inbox", tags=["Sales Inbox"])

ORDER = ["needs_rep", "ready", "drafted", "in_bc", "duplicate", "purchasing", "to_ap", "filed"]


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@router.get("/summary")
async def summary(days: int = 45):
    db = get_db()
    counts = {s: 0 for s in ORDER}
    async for x in db.hub_documents.aggregate([
            {"$match": {"created_utc": {"$gte": _since(days)}, "sales_stage": {"$exists": True}}},
            {"$group": {"_id": "$sales_stage", "n": {"$sum": 1}}}]):
        counts[x["_id"]] = x["n"]
    reasons = {}
    async for x in db.hub_documents.aggregate([
            {"$match": {"created_utc": {"$gte": _since(days)}, "sales_stage": "needs_rep"}},
            {"$group": {"_id": "$sales_stage_reason", "n": {"$sum": 1}}}]):
        reasons[x["_id"] or "other"] = x["n"]
    cpo = await db.hub_documents.count_documents({"created_utc": {"$gte": _since(days)}, "sales_link.role": "customer_po",
                                                  "sales_stage": {"$ne": "duplicate"}})
    linked = await db.hub_documents.count_documents({"created_utc": {"$gte": _since(days)}, "sales_link.role": "customer_po",
                                                     "sales_link.order_no": {"$ne": None}})
    from services.sales_draft_readback_service import metrics
    return {"days": days, "draft_accuracy": await metrics(db), "stages": counts, "needs_rep_reasons": reasons, "reason_text": REASONS,
            "customer_pos": cpo, "customer_pos_in_bc": linked}


@router.get("/list")
async def list_docs(stage: str = "needs_rep", q: str = "", days: int = 45, skip: int = 0, limit: int = 50):
    db = get_db()
    flt = {"created_utc": {"$gte": _since(days)}, "sales_stage": stage}
    if q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        flt["$or"] = [{"file_name": rx}, {"email_subject": rx}, {"email_sender": rx}, {"sales_link.bc_customer_no": rx},
                      {"extracted_fields.po_number": rx}, {"extracted_fields.customer": rx}, {"sales_link.order_no": rx}]
    total = await db.hub_documents.count_documents(flt)
    rows, custs = [], set()
    async for d in db.hub_documents.find(flt, {
            "_id": 0, "id": 1, "file_name": 1, "email_subject": 1, "email_sender": 1, "created_utc": 1, "document_type": 1,
            "sales_link": 1, "sales_stage": 1, "sales_stage_reason": 1, "sales_stage_detail": 1, "sales_resolution": 1,
            "sales_draft": 1, "sales_draft_readback": 1, "duplicate_of": 1, "extracted_fields.po_number": 1, "extracted_fields.customer": 1,
            "amount_float": 1}).sort([("created_utc", -1)]).skip(skip).limit(limit):
        sl = d.get("sales_link") or {}
        if sl.get("bc_customer_no"):
            custs.add(sl["bc_customer_no"])
        rows.append({
            "id": d["id"], "file_name": d.get("file_name"), "subject": d.get("email_subject"), "sender": d.get("email_sender"),
            "received": d.get("created_utc"), "role": sl.get("role"), "customer_no": sl.get("bc_customer_no"),
            "customer_on_doc": (d.get("extracted_fields") or {}).get("customer"),
            "customer_po": (d.get("extracted_fields") or {}).get("po_number") or (sl.get("customer_po") or [None])[0],
            "stage": d.get("sales_stage"), "reason": d.get("sales_stage_reason"),
            "reason_text": REASONS.get(d.get("sales_stage_reason") or "") or d.get("sales_stage_reason"),
            "detail": d.get("sales_stage_detail"), "bc_order_no": sl.get("order_no"), "match": sl.get("match"),
            "draft": {k: (d.get("sales_draft") or {}).get(k) for k in ("bc_order_no", "environment", "total", "created_at", "to_complete")} if d.get("sales_draft") else None,
            "readback": {k: (d.get("sales_draft_readback") or {}).get(k) for k in ("state", "edits", "checked_at")} if d.get("sales_draft_readback") else None,
            "resolution": d.get("sales_resolution"), "po_total": d.get("amount_float"), "duplicate_of": d.get("duplicate_of")})
    names = {}
    if custs:
        async for c in db.bc_reference_cache.find({"bc_entity_type": "customer", "bc_customer_no": {"$in": list(custs)}},
                                                  {"_id": 0, "bc_customer_no": 1, "bc_customer_name": 1}):
            names[c["bc_customer_no"]] = c["bc_customer_name"]
    for r in rows:
        r["customer_name"] = names.get(r["customer_no"])
    return {"total": total, "rows": rows}

