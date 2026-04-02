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
    vep_count = await db.vendor_extraction_profiles.count_documents({})
    bc_cache_count = await db.bc_reference_cache.count_documents({})

    # Classification feedback
    corrections = await db.classification_corrections.count_documents({})
    corrections_with_snippet = await db.classification_corrections.count_documents({"text_snippet": {"$nin": [None, ""]}})
    feedback_examples = await db.classification_feedback.count_documents({})
    vendor_type_patterns = await db.vendor_type_patterns.count_documents({})

    # Feedback events
    fe_total = await db.feedback_events.count_documents({})
    fe_applied = await db.feedback_events.count_documents({"applied": True})

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
            "vendor_extraction_profiles": vep_count,
            "bc_reference_cache": bc_cache_count,
            "classification_corrections": corrections,
            "classification_corrections_with_snippet": corrections_with_snippet,
            "auto_confirm_feedback": auto_confirms,
            "classification_feedback_examples": feedback_examples,
            "vendor_type_patterns": vendor_type_patterns,
            "feedback_events": {"total": fe_total, "applied": fe_applied, "rate": f"{(fe_applied/max(fe_total,1)*100):.0f}%"},
        },
        "health": {
            "aliases_healthy": alias_count >= 50,
            "domains_healthy": domain_count >= 5,
            "profiles_healthy": profile_count >= 20,
            "vep_healthy": vep_count >= 10,
            "feedback_healthy": fe_total > 0 and fe_applied / max(fe_total, 1) > 0.9,
            "corrections_enriched": corrections_with_snippet > 0,
            "overall": "good" if (alias_count >= 50 and profile_count >= 20 and vep_count >= 10) else "needs_seeding",
        },
        "scheduler": {
            "auto_seed": "enabled",
            "seed_frequency": "every 6 hours + after BC cache sync",
            "last_bc_sync": last_bc_sync,
            "last_bc_sync_records": last_bc_records,
        }
    }


@router.post("/close-all-gaps")
async def close_all_gaps():
    """
    One-shot fix: Run ALL learning pipeline gap closers.
    1. Backfill classification corrections with missing text/vendor data
    2. Re-seed sender domain mappings (fixed field name)
    3. Seed VEP profiles from BC cache for uncovered vendors
    4. Replay unapplied feedback events
    5. Run full knowledge seed
    """
    db = get_db()
    results = {}

    # 1. Backfill classification corrections
    try:
        from services.classification_feedback_service import backfill_classification_corrections
        results["backfill_corrections"] = await backfill_classification_corrections()
    except Exception as e:
        results["backfill_corrections"] = {"error": str(e)}

    # 2. Re-seed sender domain mappings (now checks 'sender' field too)
    try:
        results["sender_domains"] = await seed_sender_domain_mappings(db)
    except Exception as e:
        results["sender_domains"] = {"error": str(e)}

    # 3. Seed VEP profiles from BC cache
    try:
        from services.vendor_extraction_profile_service import get_vep_service
        vep = get_vep_service()
        if vep:
            results["vep_bc_seed"] = await vep.seed_from_bc_cache()
        else:
            results["vep_bc_seed"] = {"error": "VEP service not initialized"}
    except Exception as e:
        results["vep_bc_seed"] = {"error": str(e)}

    # 4. Replay unapplied feedback events
    try:
        from services.feedback_loop_service import replay_unapplied_events
        results["feedback_replay"] = await replay_unapplied_events(db)
    except Exception as e:
        results["feedback_replay"] = {"error": str(e)}

    # 5. Run full knowledge seed (aliases, domains, profiles)
    try:
        results["knowledge_seed"] = await run_full_knowledge_seed(db)
    except Exception as e:
        results["knowledge_seed"] = {"error": str(e)}

    return {"success": True, "results": results}


@router.get("/learning-proof/{vendor_id}")
async def show_learning_proof(vendor_id: str, doc_type: str = "AP_Invoice"):
    """
    PROOF endpoint: Shows exactly what the LLM sees when processing a document
    for a given vendor. This is the injected context from ALL learning sources.
    
    Usage: GET /api/knowledge-seed/learning-proof/TUMALOC?doc_type=AP_Invoice
    """
    db = get_db()
    result = {"vendor_id": vendor_id, "doc_type": doc_type, "learning_sources": {}}

    # 1. Feedback context (what gets injected into the LLM prompt)
    from services.feedback_loop_service import build_feedback_context_for_prompt
    feedback_context = await build_feedback_context_for_prompt(db, vendor_id=vendor_id, doc_type=doc_type)
    result["learning_sources"]["feedback_prompt_injection"] = {
        "chars": len(feedback_context),
        "content": feedback_context if feedback_context else "(empty — no corrections for this vendor yet)",
    }

    # 2. VEP profile (vendor extraction profile)
    from services.vendor_extraction_profile_service import get_vep_service
    vep_svc = get_vep_service()
    vep_profile = None
    if vep_svc:
        vep_profile = await vep_svc.get_profile(vendor_id)
    if vep_profile:
        result["learning_sources"]["vendor_extraction_profile"] = {
            "enabled": vep_profile.get("enabled"),
            "reference_priority": vep_profile.get("reference_priority_order"),
            "doc_type_bias": vep_profile.get("document_type_bias"),
            "po_expected": vep_profile.get("po_expected"),
            "amount_stats": vep_profile.get("amount_stats"),
            "learning_source": vep_profile.get("learning_source"),
        }
    else:
        result["learning_sources"]["vendor_extraction_profile"] = "(no VEP profile for this vendor)"

    # 3. Vendor invoice profile (BC historical data)
    vip = await db.vendor_invoice_profiles.find_one(
        {"$or": [{"vendor_no": vendor_id}, {"vendor_no": vendor_id.upper()}]},
        {"_id": 0}
    )
    if vip:
        result["learning_sources"]["bc_invoice_history"] = {
            "invoice_count": vip.get("bc_invoice_count"),
            "po_expected": vip.get("po_expected"),
            "external_ref_rate": vip.get("external_ref_rate"),
            "amount_stats": vip.get("amount_stats"),
            "posting_frequency": vip.get("posting_frequency"),
            "po_patterns": vip.get("po_patterns"),
        }
    else:
        result["learning_sources"]["bc_invoice_history"] = "(no BC invoice history for this vendor)"

    # 4. Vendor aliases
    aliases = await db.vendor_aliases.find(
        {"$or": [{"vendor_no": vendor_id}, {"vendor_no": vendor_id.upper()},
                 {"canonical_vendor_id": vendor_id}, {"canonical_vendor_id": vendor_id.upper()}]},
        {"_id": 0, "alias_string": 1, "alias": 1, "vendor_name": 1, "source": 1}
    ).limit(20).to_list(20)
    result["learning_sources"]["vendor_aliases"] = [
        {"name": a.get("alias_string") or a.get("alias", "?"), "source": a.get("source", "?")}
        for a in aliases
    ] if aliases else "(no aliases for this vendor)"

    # 5. Classification corrections for this vendor
    corrections = await db.classification_corrections.find(
        {"$or": [
            {"vendor_canonical": {"$regex": f"^{vendor_id}$", "$options": "i"}},
            {"vendor_no": {"$regex": f"^{vendor_id}$", "$options": "i"}},
        ]},
        {"_id": 0, "original_type": 1, "corrected_type": 1, "file_name": 1, "text_snippet": 1}
    ).sort("corrected_at", -1).limit(10).to_list(10)
    result["learning_sources"]["classification_corrections"] = [
        {"from": c.get("original_type"), "to": c.get("corrected_type"),
         "file": c.get("file_name", "?"), "has_text": bool(c.get("text_snippet"))}
        for c in corrections
    ] if corrections else "(no corrections for this vendor)"

    # 6. Few-shot examples that would be included
    from services.classification_feedback_service import get_few_shot_examples
    few_shot = await get_few_shot_examples(vendor_no=vendor_id)
    result["learning_sources"]["few_shot_examples"] = [
        {"from": ex.get("original_type"), "to": ex.get("corrected_type"),
         "file": ex.get("file_name", "?"), "has_text": bool(ex.get("text_snippet"))}
        for ex in few_shot
    ] if few_shot else "(no few-shot examples available)"

    # Summary
    active_sources = sum(1 for v in result["learning_sources"].values()
                         if not isinstance(v, str) or not v.startswith("("))
    result["summary"] = {
        "active_learning_sources": f"{active_sources}/6",
        "verdict": "LEARNING" if active_sources >= 2 else "MINIMAL" if active_sources >= 1 else "NOT LEARNING",
    }

    return result
