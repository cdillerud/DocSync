"""GPI Document Hub - Vendor Extraction Profiles Router"""

from fastapi import APIRouter, HTTPException, Query
from services.vendor_extraction_profile_service import get_vep_service
from deps import get_db

router = APIRouter(prefix="/vendor-extraction-profiles", tags=["Vendor Extraction Profiles"])


@router.post("/seed-top-vendors")
async def seed_top_vendors(min_docs: int = Query(5, ge=1)):
    """Seed profiles for top vendors by document count from production data."""
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")

    db = get_db()
    pipeline = [
        {"$match": {"vendor_canonical": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$vendor_canonical", "count": {"$sum": 1}}},
        {"$match": {"count": {"$gte": min_docs}}},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]
    top_vendors = []
    async for doc in db.hub_documents.aggregate(pipeline):
        top_vendors.append({"vendor_id": doc["_id"], "doc_count": doc["count"]})

    seeded = []
    skipped = []
    for v in top_vendors:
        vid = v["vendor_id"]
        existing = await svc.get_profile(vid)
        if existing:
            skipped.append(vid)
            continue
        profile = await svc.generate_profile(vid)
        if profile:
            seeded.append(vid)
        else:
            skipped.append(vid)

    return {
        "seeded": len(seeded),
        "skipped": len(skipped),
        "vendors": seeded,
        "skipped_vendors": skipped,
        "total_candidates": len(top_vendors),
    }


@router.get("/coverage")
async def get_profile_coverage():
    """Coverage report: how many vendors have profiles vs don't."""
    db = get_db()

    # All vendors with docs
    vendor_pipeline = [
        {"$match": {"vendor_canonical": {"$nin": [None, ""]}}},
        {"$group": {"_id": "$vendor_canonical", "doc_count": {"$sum": 1}}},
        {"$sort": {"doc_count": -1}},
    ]
    all_vendors = {}
    async for doc in db.hub_documents.aggregate(vendor_pipeline):
        all_vendors[doc["_id"]] = doc["doc_count"]

    # Vendors with profiles
    profiled = set()
    async for p in db.vendor_extraction_profiles.find({}, {"_id": 0, "vendor_no": 1, "vendor_name": 1}):
        profiled.add(p.get("vendor_no") or p.get("vendor_name", ""))

    vendors_with = [v for v in all_vendors if v in profiled]
    vendors_without = [v for v in all_vendors if v not in profiled]

    top_unprofiled = [
        {"vendor_id": v, "doc_count": all_vendors[v]}
        for v in vendors_without[:10]
    ]

    return {
        "total_vendors": len(all_vendors),
        "vendors_with_profiles": len(vendors_with),
        "vendors_without_profiles": len(vendors_without),
        "coverage_pct": round(len(vendors_with) / max(len(all_vendors), 1) * 100, 1),
        "top_unprofiled": top_unprofiled,
    }


@router.get("")
async def get_all_extraction_profiles():
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    return await svc.get_all_profiles()


@router.get("/stats")
async def get_extraction_profile_stats():
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    return await svc.get_profile_stats()


@router.get("/{vendor_id}")
async def get_vendor_extraction_profile(vendor_id: str):
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    profile = await svc.get_profile(vendor_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Profile not found")
    return profile


@router.post("/{vendor_id}/generate")
async def generate_vendor_profile(vendor_id: str):
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    profile = await svc.generate_profile(vendor_id)
    if not profile:
        raise HTTPException(status_code=404, detail="Insufficient data to generate profile")
    return profile


@router.post("/generate-all")
async def generate_all_profiles():
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    return await svc.generate_all_profiles()


@router.post("/{vendor_id}/toggle")
async def toggle_vendor_profile(vendor_id: str, enabled: bool = True):
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    ok = await svc.toggle_profile(vendor_id, enabled)
    if not ok:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"vendor_id": vendor_id, "enabled": enabled}


@router.post("/{vendor_id}/reset")
async def reset_vendor_profile(vendor_id: str):
    svc = get_vep_service()
    if not svc:
        raise HTTPException(status_code=503, detail="VEP service not initialized")
    ok = await svc.reset_profile(vendor_id)
    if not ok:
        raise HTTPException(status_code=404, detail="Profile not found")
    return {"vendor_id": vendor_id, "status": "reset"}
