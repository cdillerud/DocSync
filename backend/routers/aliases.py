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



@router.get("/vendors/search-bc")
async def search_bc_vendors(q: str = Query(..., min_length=2)):
    """
    Search BC vendors by name or vendor number.
    Used by the UI for manual vendor resolution when auto-suggestions are wrong.
    """
    import re
    from difflib import SequenceMatcher
    db = get_db()

    q_lower = q.strip().lower()
    q_pattern = re.escape(q_lower)

    # Search in BC reference cache
    bc_vendors = []
    try:
        cached = await db.bc_reference_cache.find(
            {
                "bc_entity_type": "vendor",
                "$or": [
                    {"bc_vendor_name": {"$regex": q_pattern, "$options": "i"}},
                    {"bc_vendor_no": {"$regex": q_pattern, "$options": "i"}},
                ],
            },
            {"_id": 0, "bc_vendor_no": 1, "bc_vendor_name": 1}
        ).limit(20).to_list(20)
        for v in cached:
            if v.get("bc_vendor_no"):
                bc_vendors.append({
                    "vendor_no": v["bc_vendor_no"],
                    "vendor_name": v.get("bc_vendor_name", v["bc_vendor_no"]),
                    "source": "bc_cache",
                })
    except Exception:
        pass

    # Also search vendor profiles
    try:
        profiles = await db.vendor_invoice_profiles.find(
            {
                "$or": [
                    {"vendor_name": {"$regex": q_pattern, "$options": "i"}},
                    {"vendor_no": {"$regex": q_pattern, "$options": "i"}},
                ],
            },
            {"_id": 0, "vendor_no": 1, "vendor_name": 1}
        ).limit(20).to_list(20)
        existing_nos = {v["vendor_no"] for v in bc_vendors}
        for p in profiles:
            if p.get("vendor_no") and p["vendor_no"] not in existing_nos:
                bc_vendors.append({
                    "vendor_no": p["vendor_no"],
                    "vendor_name": p.get("vendor_name", p["vendor_no"]),
                    "source": "profile",
                })
    except Exception:
        pass

    # Score by relevance
    for v in bc_vendors:
        name_lower = (v.get("vendor_name") or "").lower()
        no_lower = (v.get("vendor_no") or "").lower()
        seq = SequenceMatcher(None, q_lower, name_lower).ratio()
        exact_no = 1.0 if q_lower == no_lower else 0
        contains = 0.8 if q_lower in name_lower or q_lower in no_lower else 0
        v["score"] = round(max(seq, exact_no, contains), 3)

    bc_vendors.sort(key=lambda x: x["score"], reverse=True)

    return {"results": bc_vendors[:15], "query": q}


@router.post("/vendors/dismiss-unmatched")
async def dismiss_unmatched_vendor(body: dict):
    """
    Dismiss an unmatched vendor — marks its docs as 'vendor_dismissed' so they
    stop appearing in the vendor match gap list. The docs stay in their current
    state but the gap is acknowledged as "not a real vendor" or "new vendor not in BC".
    """
    vendor_name = body.get("vendor_name", "").strip()
    reason = body.get("reason", "dismissed_by_user")

    if not vendor_name:
        raise HTTPException(status_code=400, detail="vendor_name required")

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Update all docs with this vendor name — mark the vendor_match check as dismissed
    result = await db.hub_documents.update_many(
        {
            "$or": [
                {"extracted_fields.vendor": vendor_name},
                {"extracted_fields.vendor_name": vendor_name},
                {"normalized_fields.vendor": vendor_name},
            ],
            "validation_results.checks": {
                "$elemMatch": {"check_name": "vendor_match", "passed": False}
            },
        },
        {"$set": {
            "vendor_dismissed": True,
            "vendor_dismiss_reason": reason,
            "vendor_dismiss_at": now,
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "vendor_dismissed",
        }},
    )

    return {
        "vendor_name": vendor_name,
        "docs_dismissed": result.modified_count,
        "reason": reason,
    }



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
    Normalizes vendor names to merge duplicates (e.g., "SC Warehouses, LLC" = "SC Warehouses, LLC.").
    Uses improved fuzzy matching with word overlap and abbreviation handling.
    """
    import re
    from difflib import SequenceMatcher

    db = get_db()

    # Include Exception/Completed in exclusion to avoid showing already-processed docs
    DONE_STATUSES = ["Completed", "Posted", "Deleted", "Archived", "Exception",
                     "completed", "posted", "archived", "exception"]

    gap_docs = await db.hub_documents.aggregate([
        {"$match": {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "vendor_match", "passed": False}
            },
            "status": {"$nin": DONE_STATUSES},
            "is_duplicate": {"$ne": True},
            "auto_cleared": {"$ne": True},
        }},
        {"$group": {
            "_id": {
                "vendor_name": {"$ifNull": [
                    "$normalized_fields.vendor",
                    {"$ifNull": ["$extracted_fields.vendor", "$extracted_fields.vendor_name"]}
                ]},
            },
            "count": {"$sum": 1},
            "sample_files": {"$push": "$file_name"},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 50},
    ]).to_list(50)

    # Normalize function for grouping variants
    def _normalize_for_group(name):
        if not name:
            return ""
        n = name.strip().lower()
        # Remove trailing punctuation, normalize LLC/Inc variants
        n = re.sub(r'[.,;:]+$', '', n)
        n = re.sub(r'\s+(llc|inc|ltd|corp|co|pte|usa)\b\.?', '', n)
        n = re.sub(r'[^a-z0-9\s]', '', n)
        n = re.sub(r'\s+', ' ', n).strip()
        return n

    # Merge duplicate vendor name variants
    merged = {}
    for gap in gap_docs:
        raw_name = gap["_id"].get("vendor_name") or ""
        if not raw_name:
            continue
        normalized_key = _normalize_for_group(raw_name)
        if not normalized_key:
            continue
        if normalized_key in merged:
            merged[normalized_key]["count"] += gap["count"]
            merged[normalized_key]["variants"].append(raw_name)
            merged[normalized_key]["sample_files"].extend(gap.get("sample_files", [])[:3])
        else:
            merged[normalized_key] = {
                "display_name": raw_name,
                "variants": [raw_name],
                "count": gap["count"],
                "sample_files": gap.get("sample_files", [])[:3],
            }

    # Load ALL BC vendors from cache + profiles
    bc_vendors = []
    try:
        cached = await db.bc_reference_cache.find(
            {"bc_entity_type": "vendor"},
            {"_id": 0, "bc_vendor_no": 1, "bc_vendor_name": 1}
        ).to_list(1000)
        for v in cached:
            if v.get("bc_vendor_no"):
                bc_vendors.append({
                    "vendor_no": v["bc_vendor_no"],
                    "name": v.get("bc_vendor_name", v["bc_vendor_no"]),
                })
    except Exception:
        pass

    try:
        profiles = await db.vendor_invoice_profiles.find(
            {}, {"_id": 0, "vendor_no": 1, "vendor_name": 1}
        ).to_list(500)
        existing_nos = {v["vendor_no"] for v in bc_vendors}
        for p in profiles:
            if p.get("vendor_no") and p["vendor_no"] not in existing_nos:
                bc_vendors.append({
                    "vendor_no": p["vendor_no"],
                    "name": p.get("vendor_name", p["vendor_no"]),
                })
    except Exception:
        pass

    results = []

    for norm_key, group in sorted(merged.items(), key=lambda x: x[1]["count"], reverse=True):
        vendor_name = group["display_name"]
        vn_lower = vendor_name.strip().lower()
        vn_normalized = _normalize_for_group(vendor_name)
        vn_words = set(vn_normalized.split())

        # Score each BC vendor with improved algorithm
        scored = []
        for bv in bc_vendors:
            bc_name = bv.get("name", "").strip().lower()
            bc_no = bv.get("vendor_no", "").strip()
            bc_normalized = _normalize_for_group(bc_name)
            bc_words = set(bc_normalized.split())

            # 1. Sequence matcher on normalized names (better than raw)
            seq_score = SequenceMatcher(None, vn_normalized, bc_normalized).ratio()

            # 2. Word overlap (intersection / union for Jaccard)
            if vn_words and bc_words:
                jaccard = len(vn_words & bc_words) / len(vn_words | bc_words)
            else:
                jaccard = 0

            # 3. First word match bonus (important for company names)
            first_word_bonus = 0.15 if vn_words and bc_words and list(sorted(vn_words))[0] == list(sorted(bc_words))[0] else 0

            # 4. Vendor number exact match
            no_score = 0.95 if vn_lower == bc_no.lower() else (0.85 if bc_no.lower() in vn_lower or vn_lower in bc_no.lower() else 0)

            # 5. Abbreviation handling — check if vendor_no is an abbreviation of the name
            abbrev_score = 0
            if len(bc_no) >= 3 and bc_no.upper() in vendor_name.upper():
                abbrev_score = 0.8

            best = max(seq_score, jaccard + first_word_bonus, no_score, abbrev_score)
            if best >= 0.40:
                scored.append({
                    "vendor_no": bv["vendor_no"],
                    "vendor_name": bv["name"],
                    "score": round(best, 3),
                })

        scored.sort(key=lambda x: x["score"], reverse=True)

        results.append({
            "vendor_name": vendor_name,
            "variants": group["variants"] if len(group["variants"]) > 1 else [],
            "gap_count": group["count"],
            "sample_files": group["sample_files"][:3],
            "candidates": scored[:5],
        })

    return {"unmatched_vendors": results, "total": len(results)}


@router.post("/vendors/accept-suggestion")
async def accept_vendor_suggestion(body: dict):
    """
    Accept a vendor match suggestion and create an alias.
    Also creates aliases for all name variants and re-validates all affected docs.
    """
    from services.vendor_name_helpers import normalize_vendor_name, VENDOR_ALIAS_MAP

    alias_string = body.get("alias_string", "")
    vendor_no = body.get("vendor_no", "")
    vendor_name = body.get("vendor_name", "")
    variants = body.get("variants", [])

    if not alias_string or not vendor_no:
        raise HTTPException(status_code=400, detail="alias_string and vendor_no required")

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Create aliases for the main name + all variants
    all_names = [alias_string] + [v for v in variants if v != alias_string]
    aliases_created = 0

    for name in all_names:
        alias_id = str(uuid.uuid4())
        normalized = normalize_vendor_name(name)

        existing = await db.vendor_aliases.find_one({
            "$or": [{"alias_string": name}, {"normalized_alias": normalized}]
        })
        if not existing:
            await db.vendor_aliases.insert_one({
                "alias_id": alias_id,
                "alias_string": name,
                "normalized_alias": normalized,
                "vendor_no": vendor_no,
                "vendor_name": vendor_name,
                "created_by": "monitor_suggestion",
                "created_at": now,
                "usage_count": 0,
            })
            VENDOR_ALIAS_MAP[name] = vendor_name or vendor_no
            VENDOR_ALIAS_MAP[normalized] = vendor_name or vendor_no
            aliases_created += 1

    # Re-validate all docs with any of the vendor name variants
    updated = 0
    name_conditions = []
    for name in all_names:
        name_conditions.extend([
            {"extracted_fields.vendor": name},
            {"extracted_fields.vendor_name": name},
            {"normalized_fields.vendor": name},
        ])

    gap_docs = await db.hub_documents.find(
        {
            "validation_results.checks": {
                "$elemMatch": {"check_name": "vendor_match", "passed": False}
            },
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
            "$or": name_conditions,
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
        "aliases_created": aliases_created,
        "all_variants": all_names,
        "docs_updated": updated,
    }


@router.post("/vendors/batch-resolve")
async def batch_resolve_vendor_aliases(body: dict):
    """
    Batch-create vendor aliases and re-validate all affected documents.
    
    Input: {"mappings": [{"alias_string": "SC Warehouses, LLC", "vendor_no": "GROUPWA", "vendor_name": "Group Warehousing"}]}
    
    For each mapping:
    1. Creates the alias (if it doesn't exist)
    2. Re-validates all documents matching that vendor name
    3. Updates vendor_canonical and bc_vendor_number on affected docs
    """
    from services.vendor_name_helpers import normalize_vendor_name, VENDOR_ALIAS_MAP

    mappings = body.get("mappings", [])
    if not mappings:
        raise HTTPException(status_code=400, detail="No mappings provided")

    db = get_db()
    results = []
    total_docs_updated = 0

    for mapping in mappings:
        alias_string = mapping.get("alias_string", "").strip()
        vendor_no = mapping.get("vendor_no", "").strip()
        vendor_name = mapping.get("vendor_name", "").strip()

        if not alias_string or not vendor_no:
            results.append({
                "alias_string": alias_string,
                "status": "skipped",
                "reason": "missing alias_string or vendor_no",
            })
            continue

        normalized = normalize_vendor_name(alias_string)
        now = datetime.now(timezone.utc).isoformat()

        # Create alias if not exists
        existing = await db.vendor_aliases.find_one({
            "$or": [{"alias_string": alias_string}, {"normalized_alias": normalized}]
        })
        alias_created = False
        if not existing:
            alias_id = str(uuid.uuid4())
            await db.vendor_aliases.insert_one({
                "alias_id": alias_id,
                "alias_string": alias_string,
                "normalized_alias": normalized,
                "vendor_no": vendor_no,
                "vendor_name": vendor_name,
                "created_by": "batch_resolve",
                "created_at": now,
                "usage_count": 0,
            })
            VENDOR_ALIAS_MAP[alias_string] = vendor_name or vendor_no
            VENDOR_ALIAS_MAP[normalized] = vendor_name or vendor_no
            alias_created = True

        # Find and update all docs with this vendor name (broader matching)
        doc_query = {
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
            "$or": [
                {"extracted_fields.vendor": {"$regex": f"^{alias_string}$", "$options": "i"}},
                {"extracted_fields.vendor_name": {"$regex": f"^{alias_string}$", "$options": "i"}},
                {"normalized_fields.vendor": {"$regex": f"^{alias_string}$", "$options": "i"}},
                {"vendor_canonical": {"$regex": f"^{alias_string}$", "$options": "i"}},
            ],
        }
        gap_docs = await db.hub_documents.find(
            doc_query, {"_id": 0, "id": 1, "validation_results": 1}
        ).to_list(500)

        docs_updated = 0
        for doc in gap_docs:
            doc_id = doc.get("id", "")
            validation = doc.get("validation_results") or {}
            new_checks = [ch for ch in validation.get("checks", []) if ch.get("check_name") != "vendor_match"]
            new_checks.append({
                "check_name": "vendor_match",
                "passed": True,
                "details": f"Matched via batch alias: {vendor_name} ({vendor_no})",
                "required": True,
                "match_method": "batch_alias",
                "score": 1.0,
            })
            all_passed = all(ch.get("passed", True) for ch in new_checks)
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "validation_results.checks": new_checks,
                    "validation_results.all_passed": all_passed,
                    "bc_vendor_number": vendor_no,
                    "vendor_canonical": vendor_name or vendor_no,
                    "vendor_resolved_via": "batch_alias",
                    "vendor_match_method": "alias_match",
                }}
            )
            docs_updated += 1

        total_docs_updated += docs_updated
        results.append({
            "alias_string": alias_string,
            "vendor_no": vendor_no,
            "alias_created": alias_created,
            "docs_updated": docs_updated,
            "status": "resolved",
        })

    return {
        "mappings_processed": len(results),
        "total_docs_updated": total_docs_updated,
        "results": results,
    }