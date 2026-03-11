"""GPI Document Hub - Freight G/L Routing Router"""

from fastapi import APIRouter, HTTPException, Query, Body
from typing import Dict
from services.freight_gl_routing_service import get_freight_gl_service

router = APIRouter(prefix="/freight-routing", tags=["Freight Routing"])


@router.get("/accounts")
async def list_freight_gl_accounts():
    svc = get_freight_gl_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Freight G/L routing not initialized")
    accounts = await svc.list_accounts()
    return {"accounts": accounts, "total": len(accounts)}


@router.get("/accounts/{account_id}")
async def get_freight_gl_account(account_id: str):
    svc = get_freight_gl_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Freight G/L routing not initialized")
    account = await svc.get_account(account_id)
    if not account:
        raise HTTPException(status_code=404, detail="G/L account not found")
    return account


@router.post("/accounts")
async def create_freight_gl_account(account: Dict = Body(...)):
    svc = get_freight_gl_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Freight G/L routing not initialized")
    return await svc.create_account(account)


@router.put("/accounts/{account_id}")
async def update_freight_gl_account(account_id: str, updates: Dict = Body(...)):
    svc = get_freight_gl_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Freight G/L routing not initialized")
    result = await svc.update_account(account_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="G/L account not found")
    return result


@router.delete("/accounts/{account_id}")
async def delete_freight_gl_account(account_id: str):
    svc = get_freight_gl_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Freight G/L routing not initialized")
    deleted = await svc.delete_account(account_id)
    if not deleted:
        raise HTTPException(status_code=404, detail="G/L account not found")
    return {"status": "deleted", "account_id": account_id}


@router.post("/classify/{doc_id}")
async def classify_freight_gl(doc_id: str):
    svc = get_freight_gl_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Freight G/L routing not initialized")
    result = await svc.classify_and_save(doc_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/override/{doc_id}")
async def override_freight_gl(doc_id: str, body: Dict = Body(...)):
    svc = get_freight_gl_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Freight G/L routing not initialized")
    gl_account_id = body.get("gl_account_id")
    reason = body.get("reason", "")
    if not gl_account_id:
        raise HTTPException(status_code=400, detail="gl_account_id is required")
    result = await svc.override_classification(doc_id, gl_account_id, reason)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.get("/stats")
async def get_freight_routing_stats():
    svc = get_freight_gl_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Freight G/L routing not initialized")
    return await svc.get_stats()


@router.get("/recent")
async def get_recent_freight_classifications(limit: int = Query(20, le=100)):
    svc = get_freight_gl_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Freight G/L routing not initialized")
    return await svc.get_recent_classifications(limit=limit)


@router.post("/batch-classify")
async def batch_classify_freight(body: Dict = Body(...)):
    """Batch-classify freight documents. Read-only: only writes to local MongoDB, never to BC."""
    svc = get_freight_gl_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Freight G/L routing not initialized")
    document_ids = body.get("document_ids")
    confidence_threshold = body.get("confidence_threshold", 0.5)
    skip_overrides = body.get("skip_overrides", True)
    result = await svc.batch_classify(
        document_ids=document_ids,
        confidence_threshold=confidence_threshold,
        skip_overrides=skip_overrides,
    )
    return result
