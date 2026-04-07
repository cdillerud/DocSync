"""GPI Document Hub - Vendor Aliases Router (Domain 2)

Extracted from server.py. Manages vendor alias CRUD operations.
"""

import logging
import uuid
from datetime import datetime, timezone
from typing import Optional

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/aliases", tags=["Vendor Aliases"])


class VendorAlias(BaseModel):
    alias_string: str
    vendor_no: str
    vendor_name: Optional[str] = None
    confidence_override: Optional[float] = None
    notes: Optional[str] = None


@router.get("/vendors")
async def get_vendor_aliases(
    vendor_id: Optional[str] = Query(None),
    source: Optional[str] = Query(None),
    limit: int = Query(100, ge=1, le=500),
):
    """Get all vendor aliases, optionally filtered by vendor_id or source."""
    db = get_db()
    query = {}
    if vendor_id:
        query["$or"] = [
            {"vendor_id": vendor_id},
            {"canonical_vendor_id": vendor_id},
            {"vendor_no": vendor_id},
        ]
    if source:
        query["source"] = source
    aliases = await db.vendor_aliases.find(query, {"_id": 0}).sort("usage_count", -1).limit(limit).to_list(limit)
    return {"aliases": aliases, "count": len(aliases)}


@router.post("/vendors")
async def create_vendor_alias(alias: VendorAlias):
    """Create a new vendor alias mapping."""
    from services.vendor_name_helpers import normalize_vendor_name, VENDOR_ALIAS_MAP

    db = get_db()
    alias_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()

    normalized = normalize_vendor_name(alias.alias_string)

    existing = await db.vendor_aliases.find_one({
        "$or": [
            {"alias_string": alias.alias_string},
            {"normalized_alias": normalized}
        ]
    })

    if existing:
        raise HTTPException(status_code=400, detail=f"Alias already exists for '{alias.alias_string}'")

    alias_doc = {
        "alias_id": alias_id,
        "alias_string": alias.alias_string,
        "normalized_alias": normalized,
        "vendor_no": alias.vendor_no,
        "vendor_name": alias.vendor_name,
        "confidence_override": alias.confidence_override,
        "notes": alias.notes,
        "created_by": "system",
        "created_at": now,
        "usage_count": 0,
        "last_used_at": None
    }

    await db.vendor_aliases.insert_one(alias_doc)

    VENDOR_ALIAS_MAP[alias.alias_string] = alias.vendor_name or alias.vendor_no
    VENDOR_ALIAS_MAP[normalized] = alias.vendor_name or alias.vendor_no

    return {"alias_id": alias_id, "message": "Alias created successfully"}


@router.delete("/vendors/{alias_id}")
async def delete_vendor_alias(alias_id: str):
    """Delete a vendor alias."""
    db = get_db()
    result = await db.vendor_aliases.delete_one({"alias_id": alias_id})
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail="Alias not found")
    return {"message": "Alias deleted"}


@router.get("/vendors/suggest")
async def suggest_alias_creation(
    vendor_name: str = Query(...),
    resolved_vendor_no: str = Query(...),
    resolved_vendor_name: str = Query(...)
):
    """
    Called when user manually resolves a vendor match.
    Returns suggestion to save as alias.
    """
    from services.vendor_name_helpers import normalize_vendor_name

    db = get_db()
    normalized = normalize_vendor_name(vendor_name)

    existing = await db.vendor_aliases.find_one({
        "$or": [
            {"alias_string": vendor_name},
            {"normalized_alias": normalized}
        ]
    }, {"_id": 0})

    if existing:
        return {
            "suggest_alias": False,
            "reason": "Alias already exists",
            "existing_alias": existing
        }

    return {
        "suggest_alias": True,
        "suggested_alias": {
            "alias_string": vendor_name,
            "normalized_alias": normalized,
            "vendor_no": resolved_vendor_no,
            "vendor_name": resolved_vendor_name
        },
        "message": f"Would you like to save '{vendor_name}' as an alias for '{resolved_vendor_name}'?"
    }


async def record_alias_usage(alias_string: str):
    """Record when an alias is used for matching."""
    db = get_db()
    await db.vendor_aliases.update_one(
        {"alias_string": alias_string},
        {
            "$inc": {"usage_count": 1},
            "$set": {"last_used_at": datetime.now(timezone.utc).isoformat()}
        }
    )


@router.get("/metrics")
async def get_alias_metrics():
    """Get vendor alias learning metrics for the dashboard."""
    from services.vendor_alias_learning_service import get_alias_metrics as _get_metrics
    return await _get_metrics()


@router.delete("/vendors/by-alias/{alias}")
async def delete_vendor_alias_by_name(alias: str):
    """Delete a vendor alias by its normalized alias string."""
    from services.vendor_name_helpers import normalize_vendor_name
    db = get_db()
    normalized = normalize_vendor_name(alias)
    result = await db.vendor_aliases.delete_one({
        "$or": [
            {"normalized_alias": normalized},
            {"alias_string": alias},
        ]
    })
    if result.deleted_count == 0:
        raise HTTPException(status_code=404, detail=f"Alias '{alias}' not found")
    return {"message": f"Alias '{alias}' deleted"}


@router.get("/vendors/unmatched-gaps")
async def get_unmatched_vendor_gaps():
    """
    Get vendor match gap docs with their closest match candidates.
    Powers the alias suggestion UI on the Monitor dashboard.
    """
    db = get_db()
    from services.unified_vendor_matcher import get_unified_vendor_matcher

    gap_docs = await db.hub_documents.aggregate([
        {"$match": {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "vendor_match", "passed": False}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        }},
        {"$group": {
            "_id": {
                "vendor_name": {"$ifNull": [
                    "$normalized_fields.vendor",
                    {"$ifNull": ["$extracted_fields.vendor", "$extracted_fields.vendor_name"]}
                ]},
            },
            "count": {"$sum": 1},
            "sample_ids": {"$push": "$id"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 20},
    ]).to_list(20)

    matcher = get_unified_vendor_matcher(db)
    results = []

    for gap in gap_docs:
        vendor_name = gap["_id"].get("vendor_name") or ""
        if not vendor_name:
            continue

        # Get top candidates with scores
        candidates = []
        try:
            match_result = await matcher.match_vendor(vendor_name, threshold=0.40)
            if match_result.get("candidates"):
                for cand in match_result["candidates"][:3]:
                    candidates.append({
                        "vendor_no": cand.get("vendor_id") or cand.get("vendor_number", ""),
                        "vendor_name": cand.get("display_name") or cand.get("name", ""),
                        "score": round(cand.get("score", 0), 3),
                        "source": cand.get("source", ""),
                    })
            elif match_result.get("best_match"):
                bm = match_result["best_match"]
                candidates.append({
                    "vendor_no": bm.get("vendor_id") or bm.get("vendor_number", ""),
                    "vendor_name": bm.get("display_name") or bm.get("name", ""),
                    "score": round(bm.get("score", 0), 3),
                    "source": match_result.get("source", ""),
                })
        except Exception:
            pass

        results.append({
            "vendor_name": vendor_name,
            "gap_count": gap["count"],
            "candidates": candidates,
        })

    return {"unmatched_vendors": results, "total": len(results)}


@router.post("/vendors/accept-suggestion")
async def accept_vendor_suggestion(body: dict):
    """
    Accept a vendor match suggestion and create an alias.
    Also re-validates all docs with this vendor name.
    """
    from services.vendor_name_helpers import normalize_vendor_name, VENDOR_ALIAS_MAP

    alias_string = body.get("alias_string", "")
    vendor_no = body.get("vendor_no", "")
    vendor_name = body.get("vendor_name", "")

    if not alias_string or not vendor_no:
        raise HTTPException(status_code=400, detail="alias_string and vendor_no required")

    db = get_db()
    alias_id = str(uuid.uuid4())
    now = datetime.now(timezone.utc).isoformat()
    normalized = normalize_vendor_name(alias_string)

    # Create alias (skip if exists)
    existing = await db.vendor_aliases.find_one({
        "$or": [{"alias_string": alias_string}, {"normalized_alias": normalized}]
    })
    if not existing:
        await db.vendor_aliases.insert_one({
            "alias_id": alias_id,
            "alias_string": alias_string,
            "normalized_alias": normalized,
            "vendor_no": vendor_no,
            "vendor_name": vendor_name,
            "created_by": "monitor_suggestion",
            "created_at": now,
            "usage_count": 0,
        })
        VENDOR_ALIAS_MAP[alias_string] = vendor_name or vendor_no
        VENDOR_ALIAS_MAP[normalized] = vendor_name or vendor_no

    # Re-validate all docs with this vendor name
    updated = 0
    gap_docs = await db.hub_documents.find(
        {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "vendor_match", "passed": False}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
            "$or": [
                {"extracted_fields.vendor": alias_string},
                {"extracted_fields.vendor_name": alias_string},
                {"normalized_fields.vendor": alias_string},
            ],
        },
        {"_id": 0, "id": 1, "validation_results": 1}
    ).to_list(500)

    for doc in gap_docs:
        doc_id = doc.get("id", "")
        validation = doc.get("validation_results") or {}
        new_checks = [ch for ch in validation.get("checks", []) if ch.get("check_name") != "vendor_match"]
        new_checks.append({
            "check_name": "vendor_match",
            "passed": True,
            "details": f"Matched via manual alias: {vendor_name} ({vendor_no})",
            "required": True,
            "match_method": "manual_alias",
            "score": 1.0,
        })
        all_passed = all(ch.get("passed", True) for ch in new_checks)
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "validation_results.checks": new_checks,
                "validation_results.all_passed": all_passed,
                "bc_vendor_number": vendor_no,
                "vendor_resolved_via": "manual_alias",
            }}
        )
        updated += 1

    return {
        "alias_created": not bool(existing),
        "alias_id": alias_id if not existing else existing.get("alias_id"),
        "docs_updated": updated,
    }
