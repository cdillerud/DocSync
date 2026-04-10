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


@router.get("/verify-business-rules")
async def verify_business_rules(
    vendor_filter: str = Query(None, description="Filter by vendor (e.g. TUMALOC, CARGOMO)"),
    limit: int = Query(10, le=50),
):
    """
    Verify controller business rules against real production documents.
    Shows how each document would be classified by the freight business rules engine.
    Use this after deployment to confirm rules are working correctly.
    """
    from services.freight_business_rules import classify_freight_document
    db = get_db()

    query = {"is_duplicate": {"$ne": True}}
    if vendor_filter:
        query["$or"] = [
            {"bc_vendor_number": vendor_filter.upper()},
            {"vendor_canonical": {"$regex": vendor_filter, "$options": "i"}},
        ]

    docs = await db.hub_documents.find(
        query,
        {"_id": 0, "id": 1, "file_name": 1, "bc_vendor_number": 1, "vendor_canonical": 1,
         "extracted_fields": 1, "normalized_fields": 1, "bc_location_code": 1,
         "external_document_no": 1, "bc_reference_freight_amount": 1,
         "freight_gl_classification": 1, "status": 1, "doc_type": 1},
    ).sort("created_utc", -1).limit(limit).to_list(limit)

    results = []
    for doc in docs:
        classification = classify_freight_document(doc)
        existing_gl = doc.get("freight_gl_classification") or {}
        results.append({
            "doc_id": doc.get("id", "")[:12],
            "file_name": doc.get("file_name", ""),
            "vendor": doc.get("bc_vendor_number") or doc.get("vendor_canonical", "?"),
            "status": doc.get("status", ""),
            "doc_type": doc.get("doc_type", ""),
            "business_rules": {
                "direction": classification.get("direction"),
                "order_type": classification.get("order_type"),
                "is_international": classification.get("is_international"),
                "is_drop_ship": classification.get("is_drop_ship"),
                "freight_treatment": classification.get("freight_treatment"),
                "rules_applied": classification.get("rules_applied", []),
                "review_flags": [f.get("type") for f in classification.get("review_flags", [])],
                "confidence": classification.get("confidence"),
            },
            "existing_gl": {
                "direction": existing_gl.get("direction"),
                "gl_account": existing_gl.get("gl_number"),
                "confidence": existing_gl.get("confidence"),
                "has_controller_rules": "controller_rules" in existing_gl,
            },
        })

    return {
        "verified": len(results),
        "filter": vendor_filter,
        "documents": results,
    }
