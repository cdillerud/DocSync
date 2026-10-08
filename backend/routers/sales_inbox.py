"""Sales Inbox API: one stage per sales-mailbox document (sales_stage_service)."""
import re
from datetime import datetime, timedelta, timezone
from typing import Optional

from fastapi import APIRouter, Depends, HTTPException
from pydantic import BaseModel

from deps import get_db
from services.sales_stage_service import REASONS
from services.auth_deps import get_current_user

router = APIRouter(prefix="/sales-inbox", tags=["Sales Inbox"])

ORDER = ["needs_rep", "ready", "drafted", "in_bc", "duplicate", "purchasing", "to_ap", "filed"]


def _since(days: int) -> str:
    return (datetime.now(timezone.utc) - timedelta(days=days)).isoformat()


@router.get("/summary")
async def summary(days: int = 45, rep: str = ""):
    db = get_db()
    counts = {s: 0 for s in ORDER}
    rep_match = {"sales_rep.email": None} if rep == "unassigned" else ({"sales_rep.email": rep.lower()} if rep else {})
    async for x in db.hub_documents.aggregate([
            {"$match": {"created_utc": {"$gte": _since(days)}, "sales_stage": {"$exists": True}, **rep_match}},
            {"$group": {"_id": "$sales_stage", "n": {"$sum": 1}}}]):
        counts[x["_id"]] = x["n"]
    reasons = {}
    async for x in db.hub_documents.aggregate([
            {"$match": {"created_utc": {"$gte": _since(days)}, "sales_stage": "needs_rep", **rep_match}},
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
async def list_docs(stage: str = "needs_rep", q: str = "", rep: str = "", days: int = 45, skip: int = 0, limit: int = 50):
    db = get_db()
    flt = {"created_utc": {"$gte": _since(days)}, "sales_stage": stage}
    if rep == "unassigned":
        flt["sales_rep.email"] = None
    elif rep:
        flt["sales_rep.email"] = rep.lower()
    if q.strip():
        rx = {"$regex": re.escape(q.strip()), "$options": "i"}
        flt["$or"] = [{"file_name": rx}, {"email_subject": rx}, {"email_sender": rx}, {"sales_link.bc_customer_no": rx},
                      {"extracted_fields.po_number": rx}, {"extracted_fields.customer": rx}, {"sales_link.order_no": rx}]
    total = await db.hub_documents.count_documents(flt)
    rows, custs = [], set()
    async for d in db.hub_documents.find(flt, {
            "_id": 0, "id": 1, "file_name": 1, "email_subject": 1, "email_sender": 1, "created_utc": 1, "document_type": 1,
            "sales_link": 1, "sales_stage": 1, "sales_stage_reason": 1, "sales_stage_detail": 1, "sales_resolution": 1,
            "sales_draft": 1, "sales_draft_readback": 1, "duplicate_of": 1, "sales_rep": 1, "extracted_fields.po_number": 1, "extracted_fields.customer": 1,
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
            "resolution": d.get("sales_resolution"), "po_total": d.get("amount_float"), "duplicate_of": d.get("duplicate_of"),
            "rep": d.get("sales_rep")})
    names = {}
    if custs:
        async for c in db.bc_reference_cache.find({"bc_entity_type": "customer", "bc_customer_no": {"$in": list(custs)}},
                                                  {"_id": 0, "bc_customer_no": 1, "bc_customer_name": 1}):
            names[c["bc_customer_no"]] = c["bc_customer_name"]
    for r in rows:
        r["customer_name"] = names.get(r["customer_no"])
    return {"total": total, "rows": rows}



ACTIVE = ["needs_rep", "ready", "drafted"]


@router.get("/reps")
async def reps(days: int = 45, user=Depends(get_current_user)):
    """One queue per inside sales rep: active work (needs a rep, ready,
    drafted) per rep, and which queue is the signed-in person's."""
    from services.sales_rep_service import rep_mailboxes, context, _name
    db = get_db()
    ctx = await context(db)
    out = {}
    for m in rep_mailboxes():
        out[m] = {"email": m, "name": _name(m, ctx["users"]), "counts": {k: 0 for k in ACTIVE}}
    out["unassigned"] = {"email": "unassigned", "name": "Unassigned", "counts": {k: 0 for k in ACTIVE}}
    async for x in db.hub_documents.aggregate([
            {"$match": {"created_utc": {"$gte": _since(days)}, "sales_stage": {"$in": ACTIVE}}},
            {"$group": {"_id": {"r": "$sales_rep.email", "n": "$sales_rep.name", "s": "$sales_stage"}, "n": {"$sum": 1}}}]):
        key = x["_id"].get("r") or "unassigned"
        row = out.setdefault(key, {"email": key, "name": x["_id"].get("n"), "counts": {k: 0 for k in ACTIVE}})
        row["name"] = row["name"] or x["_id"].get("n")
        row["counts"][x["_id"]["s"]] = x["n"]
    me = str((user or {}).get("email") or "").lower()
    return {"reps": list(out.values()), "me": me if me in out else None}


class AssignRequest(BaseModel):
    rep_email: str = ""
    scope: str = "document"          # document | customer


@router.post("/document/{doc_id}/assign")
async def assign_rep(doc_id: str, req: AssignRequest, user=Depends(get_current_user)):
    from services.sales_rep_service import set_override, rep_mailboxes, context, assign
    db = get_db()
    d = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "id": 1, "pilot_mailbox": 1, "sales_link": 1})
    if not d:
        raise HTTPException(status_code=404, detail="Document not found")
    if req.rep_email and req.rep_email.lower() not in rep_mailboxes():
        raise HTTPException(status_code=400, detail="Not an inside sales rep")
    if req.scope == "customer":
        cust = (d.get("sales_link") or {}).get("bc_customer_no")
        if not cust:
            raise HTTPException(status_code=400, detail="This document has no customer to assign")
        await set_override(db, "customer", cust, req.rep_email, user or {})
        ctx = await context(db, fresh=True)
        n = 0
        async for x in db.hub_documents.find({"sales_link.bc_customer_no": cust, "sales_stage": {"$exists": True}}, {"_id": 0, "id": 1, "pilot_mailbox": 1, "sales_link": 1}):
            await db.hub_documents.update_one({"id": x["id"]}, {"$set": {"sales_rep": assign(x, ctx)}})
            n += 1
        return {"ok": True, "updated": n}
    await set_override(db, "document", doc_id, req.rep_email, user or {})
    ctx = await context(db, fresh=True)
    rep = assign(d, ctx)
    await db.hub_documents.update_one({"id": doc_id}, {"$set": {"sales_rep": rep}})
    return {"ok": True, "rep": rep}
