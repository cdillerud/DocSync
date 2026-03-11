"""GPI Document Hub - Vendor Matching Router"""

from fastapi import APIRouter, HTTPException, Body, Form
from deps import get_db
from services.unified_vendor_matcher import match_vendor_unified

router = APIRouter(prefix="/vendors", tags=["Vendors"])


@router.post("/match")
async def unified_vendor_match(
    vendor_name: str = Form(...),
    min_score: float = Form(0.7)
):
    """Match a vendor name using all available sources."""
    result = await match_vendor_unified(vendor_name, min_score=min_score)
    return result


@router.get("/match-stats")
async def vendor_match_stats():
    """Get statistics about vendor matching sources."""
    db = get_db()
    spiro_count = await db.spiro_companies.count_documents({})
    cached_matches = await db.vendor_matches.count_documents({})
    docs_with_vendors = await db.hub_documents.count_documents({
        "vendor_canonical": {"$exists": True, "$ne": None}
    })

    pipeline = [
        {"$match": {"source": {"$exists": True}}},
        {"$group": {"_id": "$source", "count": {"$sum": 1}}}
    ]
    by_source = await db.vendor_matches.aggregate(pipeline).to_list(20)

    return {
        "sources": {
            "spiro_companies": spiro_count,
            "cached_matches": cached_matches,
            "documents_with_vendors": docs_with_vendors
        },
        "matches_by_source": {item["_id"]: item["count"] for item in by_source if item["_id"]}
    }
