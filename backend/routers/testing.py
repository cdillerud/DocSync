"""AP tester script inside the Hub: the drafts to review (live) and each
tester's pass / problem / notes, saved under their signed-in account.

GET  /api/testing/drafts      current sandbox drafts AP should review
GET  /api/testing/my-results  this tester's answers
PUT  /api/testing/my-results  save this tester's answers (whole set)
GET  /api/testing/results     everyone's answers (for the project)
"""
from datetime import datetime, timezone
from typing import Any, Dict

from fastapi import APIRouter, Depends
from pydantic import BaseModel, Field

from deps import get_db
from services.auth_deps import get_current_user

router = APIRouter(prefix="/testing", tags=["AP testing"])
ROUND = 1


class Results(BaseModel):
    tests: Dict[str, Dict[str, Any]] = Field(default_factory=dict)


def _clean(tests: Dict[str, Dict[str, Any]]) -> Dict[str, Dict[str, str]]:
    out = {}
    for k, v in list(tests.items())[:200]:
        status = str((v or {}).get("status") or "")
        out[str(k)[:60]] = {"status": status if status in ("pass", "problem", "unsure", "skipped", "") else "",
                            "notes": str((v or {}).get("notes") or "")[:4000]}
    return out


@router.get("/drafts")
async def drafts(limit: int = 14):
    """Untouched sandbox drafts, one or two per vendor, varied line sources."""
    from services.sandbox_draft_service import ALLOWED_ENVIRONMENT
    db = get_db()
    names = {}
    rows, per_vendor = [], {}
    async for d in db.hub_documents.find(
            {"bc_purchase_invoice.environment": ALLOWED_ENVIRONMENT},
            {"_id": 0, "id": 1, "vendor_canonical": 1, "invoice_number_clean": 1, "amount_float": 1, "po_number_clean": 1,
             "bc_purchase_invoice.bc_record_no": 1, "draft_lines_source": 1, "is_international": 1, "suggested_folder": 1,
             "bc_draft_readback": 1}).sort([("bc_purchase_invoice.bc_record_no", -1)]):
        v = d.get("vendor_canonical")
        if per_vendor.get(v, 0) >= 2:
            continue
        per_vendor[v] = per_vendor.get(v, 0) + 1
        if v not in names:
            x = await db.bc_catalog_vendors.find_one({"vendor_no": v}, {"_id": 0, "name": 1})
            names[v] = (x or {}).get("name") or v
        rb = d.get("bc_draft_readback") or {}
        rows.append({"bc_draft_no": d["bc_purchase_invoice"].get("bc_record_no"), "document_id": d["id"],
                     "vendor_no": v, "vendor_name": names[v], "invoice_number": d.get("invoice_number_clean"),
                     "amount": d.get("amount_float"), "po": d.get("po_number_clean"),
                     "lines_from": {"bc_receipt": "BC receipt", "vendor_coding": "how AP codes this vendor",
                                                                 "vendor_profile": "vendor profile"}.get(
                         d.get("draft_lines_source") or "", "—"),
                     "international": bool(d.get("is_international")), "folder": d.get("suggested_folder"),
                     "edited_in_bc": bool(rb.get("edits"))})
    # Spread across vendors first, then fill.
    first = [r for i, r in enumerate(rows) if [x["vendor_no"] for x in rows].index(r["vendor_no"]) == i]
    rest = [r for r in rows if r not in first]
    return {"environment": ALLOWED_ENVIRONMENT, "drafts": (first + rest)[:limit]}


@router.get("/my-results")
async def my_results(user=Depends(get_current_user)):
    r = await get_db().tester_results.find_one({"email": user["email"], "round": ROUND}, {"_id": 0})
    return r or {"email": user["email"], "round": ROUND, "tests": {}}


@router.put("/my-results")
async def save_my_results(body: Results, user=Depends(get_current_user)):
    now = datetime.now(timezone.utc).isoformat()
    await get_db().tester_results.update_one(
        {"email": user["email"], "round": ROUND},
        {"$set": {"email": user["email"], "name": user.get("display_name") or user["email"], "round": ROUND,
                  "tests": _clean(body.tests), "updated_at": now},
         "$setOnInsert": {"created_at": now}}, upsert=True)
    return {"ok": True, "updated_at": now}


@router.get("/results")
async def all_results(_user=Depends(get_current_user)):
    return {"results": [r async for r in get_db().tester_results.find({"round": ROUND}, {"_id": 0}).sort("updated_at", -1)]}

