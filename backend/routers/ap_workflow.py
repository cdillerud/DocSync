"""AP workflow API: holds, approvals, people, audit trail (Hub database only)."""
from typing import Optional

from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

from deps import get_db
import services.ap_workflow_service as wf

router = APIRouter(prefix="/ap-workflow", tags=["AP Workflow"])


class HoldRequest(BaseModel):
    reason: str = Field(..., min_length=2, max_length=500)
    until: Optional[str] = Field(default=None, description="ISO date the hold should be reviewed")
    by: str = Field(default="", max_length=100)


class NoteRequest(BaseModel):
    by: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=1000)


class ApprovalRequest(BaseModel):
    approver: str = Field(..., min_length=1, max_length=100)
    by: str = Field(default="", max_length=100)
    notes: str = Field(default="", max_length=1000)


class PersonRequest(BaseModel):
    name: str = Field(..., min_length=1, max_length=100)
    roles: list = Field(default_factory=lambda: ["approver"])
    active: bool = True


async def _doc(doc_id: str):
    d = await get_db().hub_documents.find_one({"id": doc_id}, {"_id": 0, "id": 1, "vendor_canonical": 1})
    if not d:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    return d


@router.get("/people")
async def list_people():
    return {"people": [p async for p in get_db().ap_people.find({}, {"_id": 0}).sort("name", 1)]}


@router.post("/people")
async def upsert_person(req: PersonRequest):
    await get_db().ap_people.update_one({"name": req.name.strip()},
                                        {"$set": {"name": req.name.strip(), "roles": req.roles, "active": req.active,
                                                  "updated_at": wf._now()}}, upsert=True)
    return {"ok": True}


@router.get("/queue")
async def queue(view: str = "approvals", approver: Optional[str] = None, limit: int = 200):
    db = get_db()
    if view == "holds":
        q = {"ap_hold": {"$exists": True}}
    else:
        q = {"ap_stage": "awaiting_approval"}
        if approver:
            q["$or"] = [{"ap_approval.approver": approver}, {"suggested_approver": approver}]
    fields = {"_id": 0, "id": 1, "file_name": 1, "vendor_canonical": 1, "vendor_raw": 1, "invoice_number_clean": 1,
              "amount_float": 1, "created_utc": 1, "suggested_folder": 1, "ap_hold": 1, "ap_approval": 1,
              "suggested_approver": 1, "document_type": 1, "po_number_clean": 1}
    items = [d async for d in db.hub_documents.find(q, fields).sort([("created_utc", -1)]).limit(limit)]
    by_approver = {}
    async for g in db.hub_documents.aggregate([{"$match": {"ap_stage": "awaiting_approval"}},
                                               {"$group": {"_id": {"$ifNull": ["$ap_approval.approver", "$suggested_approver"]},
                                                           "n": {"$sum": 1}}}]):
        by_approver[g["_id"] or "unassigned"] = g["n"]
    holds = await db.hub_documents.count_documents({"ap_hold": {"$exists": True}})
    return {"view": view, "items": items, "awaiting_by_approver": by_approver, "holds": holds}


@router.post("/document/{doc_id}/hold")
async def hold(doc_id: str, req: HoldRequest):
    await _doc(doc_id)
    return {"hold": await wf.put_on_hold(get_db(), doc_id, req.reason, req.until, req.by)}


@router.post("/document/{doc_id}/release")
async def release(doc_id: str, req: NoteRequest):
    await _doc(doc_id)
    await wf.release_hold(get_db(), doc_id, req.by, req.notes)
    return {"ok": True}


@router.post("/document/{doc_id}/request-approval")
async def request_approval(doc_id: str, req: ApprovalRequest):
    await _doc(doc_id)
    return {"approval": await wf.request_approval(get_db(), doc_id, req.approver, req.by, req.notes)}


@router.post("/document/{doc_id}/approve")
async def approve(doc_id: str, req: NoteRequest):
    await _doc(doc_id)
    return {"approval": await wf.decide_approval(get_db(), doc_id, True, req.by, req.notes)}


@router.post("/document/{doc_id}/reject")
async def reject(doc_id: str, req: NoteRequest):
    await _doc(doc_id)
    return {"approval": await wf.decide_approval(get_db(), doc_id, False, req.by, req.notes)}


@router.get("/document/{doc_id}/history")
async def history(doc_id: str):
    db = get_db()
    events = [e async for e in db.ap_workflow_events.find({"document_id": doc_id}, {"_id": 0}).sort("at", 1)]
    routing = [r async for r in db.human_routing_decisions.find({"document_id": doc_id}, {"_id": 0}).sort("created_at", 1)]
    return {"events": events, "routing_decisions": routing}


@router.get("/document/{doc_id}/suggested-approver")
async def suggested_approver(doc_id: str):
    d = await _doc(doc_id)
    return {"approver": await wf.suggest_approver(get_db(), d)}


STAGE_LABELS = {
    "needs_staff": "Needs staff", "ready": "Ready for AP", "in_bc": "In BC", "in_bc_check": "In BC, check",
    "paid": "Paid", "no_action": "No action", "container": "Split into pieces", "filed_by_staff": "Filed by staff",
    "file_only": "File only", "on_hold": "On hold", "awaiting_approval": "Awaiting approval",
    "drafted": "Drafted in BC (sandbox)",
}


@router.get("/document/{doc_id}/ap-summary")
async def ap_summary(doc_id: str):
    """Everything that explains how the Hub handled one AP document: stage,
    BC link, each automatic correction with its source, and every person's
    decision, hold and approval (audit view)."""
    db = get_db()
    d = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "file_content_b64": 0})
    if not d:
        raise HTTPException(status_code=404, detail=f"Document {doc_id} not found")
    corrections = []

    def add(when, what, detail, source):
        corrections.append({"at": when, "what": what, "detail": detail, "source": source})

    vb = d.get("vendor_canonical_backfill") or {}
    if vb:
        add(vb.get("at"), "Vendor", f"{vb.get('previous') or 'none'} -> {d.get('vendor_canonical')}", vb.get("from") or "learning")
    if d.get("invoice_number_rejected"):
        r = d["invoice_number_rejected"]
        add(r.get("at"), "Invoice number", f"rejected '{r.get('value')}' ({r.get('reason')})", "validation")
    if d.get("invoice_number_source"):
        add(d.get("invoice_number_filled_at"), "Invoice number", f"{d.get('invoice_number_clean')} read from the {d['invoice_number_source'].replace('_', ' ')}", "intake correction")
    if d.get("invoice_number_extracted_previous"):
        add(None, "Invoice number", f"{d.get('invoice_number_extracted_previous')} -> {d.get('invoice_number_clean')}", "BC")
    if d.get("po_from_text"):
        pf = d["po_from_text"]
        add(pf.get("at"), "PO", f"{pf.get('raw') or 'none'} -> {pf.get('value')} (found in {pf.get('source', '').replace('_', ' ')}, confirmed by BC orders)", "PO correction")
    if d.get("po_number_previous") and d.get("po_number_source") == "bc_order_number":
        add(None, "PO", f"{d.get('po_number_previous')} -> {d.get('po_number_clean')}", "BC")
    if d.get("document_type_corrected"):
        dc = d["document_type_corrected"]
        add(dc.get("at"), "Document type", f"{d.get('document_type_previous')} -> {d.get('document_type')} ({dc.get('reason')})", "classification")
    if d.get("mailbox_from_bc"):
        mb = d["mailbox_from_bc"]
        add(mb.get("at"), "Lane", f"{mb.get('previous')} -> AP (matches BC document {mb.get('bc_document_no')})", "BC")
    for k, label in (("amount_from_cfdi", "CFDI e-invoice"), ("amount_from_bc", "BC")):
        if d.get(k):
            add(d[k].get("at"), "Amount", f"{d[k].get('previous')} -> {d.get('amount_float')}", label)
    if d.get("duplicate_unmarked"):
        add(d["duplicate_unmarked"].get("at"), "Duplicate", "restored: " + str(d["duplicate_unmarked"].get("reason")), "validation")
    async for e in db.bc_learning_events.find({"document_id": doc_id}, {"_id": 0}):
        add(e.get("at"), str(e.get("kind", "")).replace("_", " ").title(), f"{e.get('from')} -> {e.get('to')} (BC {e.get('bc_document_no')}, {e.get('match')})", "BC")
    events = [e async for e in db.ap_workflow_events.find({"document_id": doc_id}, {"_id": 0}).sort("at", 1)]
    for r in [r async for r in db.human_routing_decisions.find({"document_id": doc_id}, {"_id": 0}).sort("created_at", 1)]:
        events.append({"at": r.get("created_at"), "action": "folder_decision", "by": r.get("source"),
                       "folder": r.get("selected_folder"), "hub_suggested": r.get("suggested_folder"), "notes": r.get("notes")})
    if d.get("non_transactional"):
        events.append({"at": d.get("non_transactional_at") or d.get("updated_utc"), "action": "excluded",
                       "by": d.get("non_transactional_by"), "notes": d.get("non_transactional_notes")})
    events.sort(key=lambda e: str(e.get("at") or ""))
    bl = d.get("bc_link") or {}
    return {
        "stage": d.get("ap_stage"), "stage_label": STAGE_LABELS.get(d.get("ap_stage"), d.get("ap_stage")),
        "staff_reason": d.get("staff_reason"), "no_action_reason": d.get("no_action_reason") or d.get("non_ap_kind"),
        "suggested_folder": d.get("suggested_folder"), "routing_reason": d.get("routing_reason"),
        "routing_path_accuracy": d.get("routing_path_accuracy"), "suggested_approver": d.get("suggested_approver"),
        "staff_decision": d.get("staff_decision"), "hold": d.get("ap_hold"), "approval": d.get("ap_approval"),
        "bc": {k: bl.get(k) for k in ("bc_document_no", "bc_entity", "bc_status", "bc_vendor_no", "bc_amount",
                                      "bc_order_number", "match", "bc_location_lane", "linked_at")} if bl else None,
        "bc_number_typo_suspect": d.get("bc_number_typo_suspect"), "bc_amount_mismatch": d.get("bc_amount_mismatch"),
        "bc_draft_readback": d.get("bc_draft_readback"),
        "bc_draft": ({k: (d.get("bc_purchase_invoice") or {}).get(k) for k in ("bc_record_no", "environment", "status", "created_at", "lines_added", "lines_total")}
                     if (d.get("bc_purchase_invoice") or {}).get("environment") else None),
        "duplicate_of": d.get("duplicate_of_document_id") if d.get("is_duplicate") else None,
        "corrections": sorted(corrections, key=lambda c: str(c.get("at") or "")),
        "events": events,
        "updated_at": d.get("ap_stage_updated_at"),
    }


@router.get("/worklist")
async def worklist(stage: str = "needs_staff", q: str = "", days: int = 30, skip: int = 0, limit: int = 50):
    """AP Inbox: documents by ap_stage with counts per stage and search over
    vendor, invoice number, PO and file name."""
    import re as _re
    from datetime import datetime, timedelta, timezone
    db = get_db()
    since = (datetime.now(timezone.utc) - timedelta(days=max(1, min(days, 365)))).isoformat()
    base = {"created_utc": {"$gte": since}, "mailbox_category": "AP", "ap_stage": {"$exists": True}}
    counts = {}
    async for g in db.hub_documents.aggregate([{"$match": base}, {"$group": {"_id": "$ap_stage", "n": {"$sum": 1}}}]):
        counts[g["_id"]] = g["n"]
    query = dict(base)
    if stage and stage != "all":
        query["ap_stage"] = stage
    if q.strip():
        rx = {"$regex": _re.escape(q.strip()), "$options": "i"}
        query["$or"] = [{"vendor_canonical": rx}, {"vendor_raw": rx}, {"invoice_number_clean": rx},
                        {"po_number_clean": rx}, {"file_name": rx}, {"bc_link.bc_document_no": rx}]
    total = await db.hub_documents.count_documents(query)
    fields = {"_id": 0, "id": 1, "file_name": 1, "created_utc": 1, "vendor_canonical": 1, "vendor_raw": 1,
              "invoice_number_clean": 1, "amount_float": 1, "currency": 1, "po_number_clean": 1, "document_type": 1,
              "ap_stage": 1, "staff_reason": 1, "suggested_folder": 1, "suggested_approver": 1, "ap_hold": 1,
              "ap_approval": 1, "no_action_reason": 1, "check_reason": 1, "bc_link.bc_document_no": 1,
              "bc_link.bc_status": 1, "staff_decided": 1, "bc_draft_no": 1, "bc_draft_environment": 1}
    items = [d async for d in db.hub_documents.find(query, fields).sort([("created_utc", -1)])
             .skip(max(0, skip)).limit(max(1, min(limit, 200)))]
    return {"stage": stage, "q": q, "days": days, "total": total, "counts": counts, "items": items}
