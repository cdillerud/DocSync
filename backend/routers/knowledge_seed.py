"""
GPI Document Hub — Knowledge Seed Router

Endpoints to trigger bulk knowledge seeding from BC Cache, Spiro, and
historical documents.  Safe to call multiple times (idempotent upserts).
"""

import logging
from fastapi import APIRouter
from deps import get_db

from services.knowledge_seed_service import (
    run_full_knowledge_seed,
    seed_vendor_aliases_from_bc_cache,
    seed_sender_domain_mappings,
    seed_vendor_profiles_from_bc_cache,
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/knowledge-seed", tags=["Knowledge Seed"])


@router.post("/run-all")
async def run_full_seed():
    """Run all Phase 1 knowledge seeders (aliases, domains, profiles)."""
    db = get_db()
    results = await run_full_knowledge_seed(db)
    return {"success": True, "results": results}


@router.post("/vendor-aliases")
async def seed_aliases():
    """Seed vendor aliases from BC cache + Spiro cross-reference."""
    db = get_db()
    result = await seed_vendor_aliases_from_bc_cache(db)
    return {"success": True, "result": result}


@router.post("/sender-domains")
async def seed_domains():
    """Seed sender-domain → vendor mappings."""
    db = get_db()
    result = await seed_sender_domain_mappings(db)
    return {"success": True, "result": result}


@router.post("/vendor-profiles")
async def seed_profiles():
    """Seed vendor invoice profiles from BC cache history."""
    db = get_db()
    result = await seed_vendor_profiles_from_bc_cache(db)
    return {"success": True, "result": result}


@router.get("/status")
async def seed_status():
    """Get current knowledge base status — how much intelligence is loaded."""
    db = get_db()

    alias_count = await db.vendor_aliases.count_documents({})
    alias_by_source = {}
    pipeline = [{"$group": {"_id": "$source", "count": {"$sum": 1}}}]
    async for r in db.vendor_aliases.aggregate(pipeline):
        alias_by_source[r["_id"] or "unknown"] = r["count"]

    domain_count = await db.sender_vendor_map.count_documents({})
    domain_by_source = {}
    pipeline = [{"$group": {"_id": "$source", "count": {"$sum": 1}}}]
    async for r in db.sender_vendor_map.aggregate(pipeline):
        domain_by_source[r["_id"] or "unknown"] = r["count"]

    profile_count = await db.vendor_invoice_profiles.count_documents({})
    bc_cache_count = await db.bc_reference_cache.count_documents({})

    # Classification feedback
    corrections = await db.classification_corrections.count_documents({})
    feedback_examples = await db.classification_feedback.count_documents({})
    vendor_type_patterns = await db.vendor_type_patterns.count_documents({})

    # Auto-confirm feedback count
    auto_confirms = await db.classification_corrections.count_documents({"source": "auto_confirm"})

    # Last BC cache sync time
    cache_meta = await db.bc_reference_cache_meta.find_one({"_id": "last_sync"}, {"_id": 0})
    last_bc_sync = cache_meta.get("timestamp") if cache_meta else None
    last_bc_records = cache_meta.get("records_synced") if cache_meta else None

    return {
        "knowledge_base": {
            "vendor_aliases": {"total": alias_count, "by_source": alias_by_source},
            "sender_domain_mappings": {"total": domain_count, "by_source": domain_by_source},
            "vendor_invoice_profiles": profile_count,
            "bc_reference_cache": bc_cache_count,
            "classification_corrections": corrections,
            "auto_confirm_feedback": auto_confirms,
            "classification_feedback_examples": feedback_examples,
            "vendor_type_patterns": vendor_type_patterns,
        },
        "health": {
            "aliases_healthy": alias_count >= 50,
            "domains_healthy": domain_count >= 5,
            "profiles_healthy": profile_count >= 20,
            "overall": "good" if (alias_count >= 50 and profile_count >= 20) else "needs_seeding",
        },
        "scheduler": {
            "auto_seed": "enabled",
            "seed_frequency": "every 6 hours + after BC cache sync",
            "last_bc_sync": last_bc_sync,
            "last_bc_sync_records": last_bc_records,
        }
    }
