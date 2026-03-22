"""GPI Document Hub - Freight G/L Routing Router"""

from fastapi import APIRouter, HTTPException, Query, Body
from typing import Dict
from services.freight_gl_routing_service import get_freight_gl_service, DEFAULT_GL_ACCOUNTS
from deps import get_db

router = APIRouter(prefix="/freight-routing", tags=["Freight Routing"])


@router.get("/validate-gl")
async def validate_gl_accounts():
    """Cross-reference freight GL accounts against BC catalog cache."""
    db = get_db()
    svc = get_freight_gl_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Freight G/L routing not initialized")

    # Fetch all BC GL accounts from catalog cache
    bc_accounts = {}
    async for acct in db.bc_catalog_gl_accounts.find({}, {"_id": 0}):
        bc_accounts[acct.get("account_no", "")] = acct

    # Get live freight accounts from MongoDB (may have been updated via update-gl-account)
    live_accounts = await svc.list_accounts()

    validated = []
    invalid_accounts = []
    for acct in live_accounts:
        gl_num = acct.get("gl_number", "")
        bc_match = gl_num in bc_accounts
        entry = {
            "account_id": acct.get("account_id", ""),
            "gl_number": gl_num,
            "gl_name": acct.get("gl_name", ""),
            "bc_match": bc_match,
            "bc_description": bc_accounts[gl_num].get("name", "") if bc_match else None,
        }
        validated.append(entry)
        if not bc_match:
            invalid_accounts.append({
                "account_id": acct.get("account_id", ""),
                "gl_number": gl_num,
                "gl_name": acct.get("gl_name", ""),
            })

    valid_count = sum(1 for v in validated if v["bc_match"])
    invalid_count = len(invalid_accounts)

    recommendation = (
        "All GL accounts valid"
        if invalid_count == 0
        else f"{invalid_count} accounts need updating before auto-posting"
    )

    # Cache validation result in hub_config for auto-post checks
    invalid_gl_numbers = [a["gl_number"] for a in invalid_accounts]
    await db.hub_config.update_one(
        {"key": "freight_gl_validation"},
        {"$set": {
            "key": "freight_gl_validation",
            "valid_count": valid_count,
            "invalid_count": invalid_count,
            "invalid_gl_numbers": invalid_gl_numbers,
            "catalog_size": len(bc_accounts),
        }},
        upsert=True,
    )

    return {
        "validated": validated,
        "valid_count": valid_count,
        "invalid_count": invalid_count,
        "invalid_accounts": invalid_accounts,
        "catalog_size": len(bc_accounts),
        "recommendation": recommendation,
    }


@router.post("/update-gl-account")
async def update_gl_account_number(body: Dict = Body(...)):
    """Update the GL number for a freight account. Human-confirmed correction."""
    account_id = body.get("account_id")
    gl_number = body.get("gl_number")
    if not account_id or not gl_number:
        raise HTTPException(status_code=400, detail="account_id and gl_number required")

    svc = get_freight_gl_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Freight G/L routing not initialized")

    result = await svc.update_account(account_id, {"gl_number": gl_number})
    if not result:
        raise HTTPException(status_code=404, detail=f"Account {account_id} not found")
    return result


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
