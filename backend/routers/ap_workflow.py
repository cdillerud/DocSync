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

