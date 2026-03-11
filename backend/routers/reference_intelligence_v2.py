"""
GPI Document Hub — Reference Intelligence v2 Router

New endpoints for enhanced diagnostics, cross-document correlation,
and learning feedback.
"""

from fastapi import APIRouter, Query
from typing import Optional
import logging

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/reference-intelligence/v2", tags=["Reference Intelligence v2"])


def _get_db():
    from deps import get_db
    return get_db()


def _get_correlation_service():
    from services.cross_document_correlation import CrossDocumentCorrelationService
    return CrossDocumentCorrelationService(_get_db())


def _get_ref_intel_service():
    from services.reference_intelligence_service import get_reference_intelligence_service
    return get_reference_intelligence_service()


def _get_vendor_intel_service():
    from services.vendor_intelligence_service import get_vendor_intelligence_service
    return get_vendor_intelligence_service()


# =========================================================================
# DIAGNOSTICS
# =========================================================================

@router.get("/diagnostics/{doc_id}")
async def get_enhanced_diagnostics(doc_id: str):
    """
    Enhanced diagnostics for a document's reference resolution.
    Shows v2 signals: fuzzy matching, contextual scoring, cluster info.
    """
    db = _get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found"}

    ref_intel = doc.get("reference_intelligence") or {}
    diagnostics = ref_intel.get("diagnostics") or {}

    # Fetch cluster info
    correlation_svc = _get_correlation_service()
    cluster = await correlation_svc.get_cluster_for_document(doc_id)
    related_docs = await correlation_svc.find_related_documents(doc_id)

    # Fetch vendor behavioral info
    vendor_hints = {}
    vendor_name = doc.get("vendor_raw") or doc.get("matched_vendor_name") or ""
    vendor_intel = _get_vendor_intel_service()
    if vendor_intel and vendor_name:
        vendor_hints = await vendor_intel.get_resolver_hints(vendor_name)

    return {
        "document_id": doc_id,
        "document_type": doc.get("document_type"),
        "vendor": vendor_name,
        "resolution_result": {
            "match_outcome": ref_intel.get("match_outcome"),
            "best_match": ref_intel.get("best_match"),
            "candidate_count": len(ref_intel.get("reference_candidates", [])),
        },
        "v2_signals": diagnostics.get("v2_signals", {}),
        "scoring_breakdown": diagnostics.get("candidate_scores", []),
        "cluster": {
            "cluster_id": cluster.get("cluster_id") if cluster else None,
            "cluster_size": cluster.get("document_count", 0) if cluster else 0,
            "related_document_ids": related_docs[:10],
            "reference_signals": cluster.get("reference_signals", []) if cluster else [],
        },
        "vendor_behavior": {
            "has_hints": vendor_hints.get("has_hints", False),
            "preferred_search_order": vendor_hints.get("preferred_search_order", []),
            "common_match_targets": vendor_hints.get("common_match_targets", []),
            "reference_patterns": vendor_hints.get("reference_patterns", {}),
        },
    }


# =========================================================================
# CLUSTERS
# =========================================================================

@router.get("/clusters/{doc_id}")
async def get_document_cluster(doc_id: str):
    """Get the reference cluster for a specific document."""
    correlation_svc = _get_correlation_service()
    cluster = await correlation_svc.get_cluster_for_document(doc_id)
    if not cluster:
        return {"cluster": None, "message": "Document not in any cluster"}

    # Enrich with document summaries
    db = _get_db()
    doc_summaries = []
    for did in cluster.get("document_ids", [])[:20]:
        d = await db.hub_documents.find_one(
            {"id": did},
            {"_id": 0, "id": 1, "document_type": 1, "vendor_raw": 1, "status": 1,
             "po_number_clean": 1, "invoice_number_clean": 1, "bol_number": 1}
        )
        if d:
            doc_summaries.append(d)

    return {
        "cluster": cluster,
        "document_summaries": doc_summaries,
    }


@router.get("/clusters")
async def list_clusters(
    limit: int = Query(20, ge=1, le=100),
    skip: int = Query(0, ge=0),
    vendor: Optional[str] = None,
):
    """List reference clusters with optional vendor filter."""
    correlation_svc = _get_correlation_service()
    query = {}
    if vendor:
        query["vendor_name"] = {"$regex": vendor, "$options": "i"}

    clusters = await correlation_svc.clusters.find(
        query, {"_id": 0}
    ).sort("updated_at", -1).skip(skip).limit(limit).to_list(limit)

    total = await correlation_svc.clusters.count_documents(query)

    return {
        "clusters": clusters,
        "total": total,
        "limit": limit,
        "skip": skip,
    }


@router.get("/cluster-stats")
async def get_cluster_stats():
    """Aggregate statistics about reference clusters."""
    correlation_svc = _get_correlation_service()
    return await correlation_svc.get_cluster_stats()


# =========================================================================
# LEARNING FEEDBACK
# =========================================================================

@router.post("/feedback")
async def submit_resolution_feedback(feedback: dict):
    """
    Submit correction feedback for a reference resolution.

    Captures:
    - Reference pattern learning
    - Vendor behavioral model updates
    - Cluster relationship updates

    Body: {
        "document_id": str,
        "correction_type": "reference_match" | "label_correction" | "entity_type_correction",
        "predicted_label": str (optional),
        "correct_label": str (optional),
        "predicted_bc_match": str (optional),
        "correct_bc_match": str (optional),
        "correct_entity_type": str (optional),
        "actor": str (optional)
    }
    """
    db = _get_db()
    doc_id = feedback.get("document_id", "")
    correction_type = feedback.get("correction_type", "")

    if not doc_id or not correction_type:
        return {"error": "document_id and correction_type are required"}

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found"}

    vendor_name = doc.get("vendor_raw") or doc.get("matched_vendor_name") or ""
    actions_taken = []

    # 1. Update vendor behavioral model with correction
    vendor_intel = _get_vendor_intel_service()
    if vendor_intel and vendor_name:
        if correction_type == "label_correction":
            await vendor_intel.update_label_correction_patterns(
                vendor_name, feedback
            )
            actions_taken.append("vendor_label_pattern_updated")

        if correction_type in ("reference_match", "entity_type_correction"):
            # Trigger profile re-evaluation
            await vendor_intel.update_from_document(doc)
            actions_taken.append("vendor_profile_refreshed")

    # 2. Update cluster with corrected information
    correlation_svc = _get_correlation_service()
    if feedback.get("correct_bc_match"):
        cluster = await correlation_svc.get_cluster_for_document(doc_id)
        if cluster:
            await correlation_svc.clusters.update_one(
                {"cluster_id": cluster["cluster_id"]},
                {"$addToSet": {"reference_signals": {
                    "type": "corrected_bc_match",
                    "value": feedback["correct_bc_match"],
                    "source": "manual_correction",
                }}}
            )
            actions_taken.append("cluster_signal_added")

    # 3. Store correction in event log
    from services.event_service import get_event_service
    event_svc = get_event_service()
    if event_svc:
        from datetime import datetime, timezone
        await event_svc.emit(
            event_type="reference.correction.submitted",
            document_id=doc_id,
            source_service="reference_intelligence_v2",
            payload={
                "correction_type": correction_type,
                "vendor_name": vendor_name,
                "actor": feedback.get("actor", "system"),
                "predicted_label": feedback.get("predicted_label"),
                "correct_label": feedback.get("correct_label"),
                "predicted_bc_match": feedback.get("predicted_bc_match"),
                "correct_bc_match": feedback.get("correct_bc_match"),
            }
        )
        actions_taken.append("event_logged")

    return {
        "status": "accepted",
        "document_id": doc_id,
        "correction_type": correction_type,
        "actions_taken": actions_taken,
    }


# =========================================================================
# FUZZY MATCH TESTING (diagnostic utility)
# =========================================================================

@router.get("/fuzzy-test")
async def test_fuzzy_match(
    ref1: str = Query(..., description="First reference"),
    ref2: str = Query(..., description="Second reference to compare"),
):
    """
    Test the fuzzy matching algorithm with two reference strings.
    Useful for debugging why a match did or didn't score.
    """
    from services.fuzzy_matching import compute_fuzzy_match
    result = compute_fuzzy_match(ref1, ref2)
    return {
        "ref1": ref1,
        "ref2": ref2,
        "result": result,
    }
