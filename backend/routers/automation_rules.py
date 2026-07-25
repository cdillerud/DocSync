"""GPI Document Hub - Automation Rules Router"""

from fastapi import APIRouter, Body, Depends, HTTPException
from motor.motor_asyncio import AsyncIOMotorDatabase
from typing import Dict

from hub_platform.bootstrap import get_platform_database
from services.automation_rules_service import get_automation_rules_service

router = APIRouter(prefix="/automation-rules", tags=["Automation Rules"])


@router.get("")
async def list_automation_rules():
    svc = get_automation_rules_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Rules engine not initialized")
    rules = await svc.list_rules()
    return {"rules": rules, "total": len(rules)}


@router.post("")
async def create_automation_rule(rule: Dict = Body(...)):
    svc = get_automation_rules_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Rules engine not initialized")
    return await svc.create_rule(rule)


@router.get("/suggestions")
async def get_rule_suggestions():
    svc = get_automation_rules_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Rules engine not initialized")
    suggestions = await svc.generate_suggestions()
    return {"suggestions": suggestions, "total": len(suggestions)}


@router.get("/{rule_id}")
async def get_automation_rule(rule_id: str):
    svc = get_automation_rules_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Rules engine not initialized")
    rule = await svc.get_rule(rule_id)
    if not rule:
        raise HTTPException(status_code=404, detail="Rule not found")
    return rule


@router.put("/{rule_id}")
async def update_automation_rule(rule_id: str, updates: Dict = Body(...)):
    svc = get_automation_rules_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Rules engine not initialized")
    result = await svc.update_rule(rule_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="Rule not found")
    return result


@router.delete("/{rule_id}")
async def delete_automation_rule(rule_id: str):
    svc = get_automation_rules_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Rules engine not initialized")
    deleted = await svc.delete_rule(rule_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="Rule not found")
    return {"status": "deleted", "rule_id": rule_id}


@router.post("/{rule_id}/toggle")
async def toggle_automation_rule(rule_id: str):
    svc = get_automation_rules_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Rules engine not initialized")
    result = await svc.toggle_rule(rule_id)
    if not result:
        raise HTTPException(status_code=404, detail="Rule not found")
    return result


@router.post("/evaluate/{doc_id}")
async def evaluate_rules_for_document(
    doc_id: str,
    database: AsyncIOMotorDatabase = Depends(get_platform_database),
):
    doc = await database.hub_documents.find_one(
        {"id": doc_id}, {"_id": 0}
    )
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    svc = get_automation_rules_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Rules engine not initialized")
    result = await svc.evaluate(doc)
    return result or {"matched": False, "message": "No matching rule found"}
