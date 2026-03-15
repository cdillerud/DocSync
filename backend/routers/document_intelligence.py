"""
GPI Document Hub - Document Intelligence Router

Exposes the document intelligence pipeline as a coherent API:
  POST /api/document-intelligence/process/{doc_id}
  GET  /api/document-intelligence/review-queue
  GET  /api/document-intelligence/{doc_id}
  PATCH /api/document-intelligence/{doc_id}
  GET  /api/document-intelligence/summary
"""

import logging
from typing import Optional, Dict, Any, List

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel

from services.document_intelligence_service import (
    process_document,
    get_intelligence_result,
    get_review_queue,
    apply_correction,
    get_intelligence_summary,
    create_auto_draft,
    get_automation_action,
    DuplicateDraftError,
)
from services.entity_resolution_service import (
    resolve_entities,
    get_resolutions,
    correct_resolution,
)
from services.transaction_matching_service import (
    match_transactions,
    get_transaction_matches,
    auto_link,
    confirm_match,
)
from services.document_bundle_service import (
    detect_bundles,
    get_bundle,
    list_bundles,
    update_bundle,
    get_bundle_review_queue,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/document-intelligence", tags=["Document Intelligence"])


# ── Request/Response Models ──────────────────────────────────────────────────

class CorrectionRequest(BaseModel):
    corrected_type: Optional[str] = None
    corrected_fields: Optional[Dict[str, Any]] = None
    corrected_by: str = "admin"
    notes: str = ""


# ── Endpoints ────────────────────────────────────────────────────────────────

@router.post("/process/{doc_id}")
async def api_process_document(doc_id: str):
    """
    Run the full document intelligence pipeline on a document.
    Classify → Extract → Validate → Derive Automation Readiness → Store.
    Can be called multiple times to re-process.
    """
    try:
        result = await process_document(doc_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Document intelligence processing failed for %s: %s", doc_id, e)
        raise HTTPException(status_code=500, detail=f"Processing failed: {str(e)}")


@router.get("/review-queue")
async def api_get_review_queue(
    status: Optional[str] = Query(None, description="Filter: needs_review, blocked, ready"),
    doc_type: Optional[str] = Query(None, description="Filter by document type"),
    sort_by: str = Query("readiness_score", description="Sort field"),
    sort_order: int = Query(1, description="1=asc, -1=desc"),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """
    Get documents requiring human review.
    Returns items with automation_readiness = needs_review or blocked.
    """
    return await get_review_queue(
        status_filter=status,
        doc_type_filter=doc_type,
        sort_by=sort_by,
        sort_order=sort_order,
        limit=limit,
        offset=offset,
    )


@router.get("/summary")
async def api_get_summary():
    """Get summary statistics for the intelligence pipeline."""
    return await get_intelligence_summary()


# ── Document Bundle Endpoints ─────────────────────────────────────────────────

class DetectBundlesRequest(BaseModel):
    document_ids: Optional[List[str]] = None
    days_back: int = 7


class UpdateBundleRequest(BaseModel):
    bundle_type: Optional[str] = None
    bundle_status: Optional[str] = None
    notes: Optional[str] = None
    add_document_ids: Optional[List[str]] = None
    remove_document_ids: Optional[List[str]] = None
    updated_by: str = "admin"


@router.post("/detect-bundles")
async def api_detect_bundles(body: DetectBundlesRequest = DetectBundlesRequest()):
    """
    Detect document bundles from recently processed documents or specified IDs.
    Groups related documents by shared references, entities, and transactions.
    """
    try:
        result = await detect_bundles(
            document_ids=body.document_ids,
            days_back=body.days_back,
        )
        return result
    except Exception as e:
        logger.error("Bundle detection failed: %s", e)
        raise HTTPException(status_code=500, detail=f"Bundle detection failed: {str(e)}")


@router.get("/bundles")
async def api_list_bundles(
    bundle_type: Optional[str] = Query(None),
    bundle_status: Optional[str] = Query(None),
    completeness_status: Optional[str] = Query(None),
    linked_entity_type: Optional[str] = Query(None),
    linked_entity_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """List document bundles with optional filters."""
    return await list_bundles(
        bundle_type=bundle_type,
        bundle_status=bundle_status,
        completeness_status=completeness_status,
        linked_entity_type=linked_entity_type,
        linked_entity_id=linked_entity_id,
        limit=limit,
        offset=offset,
    )


@router.get("/bundle-review-queue")
async def api_bundle_review_queue(
    limit: int = Query(50, ge=1, le=200),
    offset: int = Query(0, ge=0),
):
    """Get bundles needing review — needs_review or incomplete."""
    return await get_bundle_review_queue(limit=limit, offset=offset)


@router.get("/bundles/{bundle_id}")
async def api_get_bundle(bundle_id: str):
    """Get full bundle detail with member documents and completeness analysis."""
    result = await get_bundle(bundle_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"Bundle not found: {bundle_id}")
    return result


@router.patch("/bundles/{bundle_id}")
async def api_update_bundle(bundle_id: str, body: UpdateBundleRequest):
    """
    Update a bundle — reclassify type, change status, add/remove documents.
    Preserves original detection for auditability.
    """
    try:
        result = await update_bundle(
            bundle_id=bundle_id,
            bundle_type=body.bundle_type,
            bundle_status=body.bundle_status,
            notes=body.notes,
            add_document_ids=body.add_document_ids,
            remove_document_ids=body.remove_document_ids,
            updated_by=body.updated_by,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Bundle update failed for %s: %s", bundle_id, e)
        raise HTTPException(status_code=500, detail=f"Bundle update failed: {str(e)}")


# ── Catch-all document routes (must be LAST) ────────────────────────────────

@router.get("/{doc_id}")
async def api_get_intelligence(doc_id: str):
    """Get the latest intelligence result for a document."""
    result = await get_intelligence_result(doc_id)
    if not result:
        raise HTTPException(status_code=404, detail=f"No intelligence result for document: {doc_id}")
    return result


@router.patch("/{doc_id}")
async def api_correct_intelligence(doc_id: str, body: CorrectionRequest):
    """
    Apply manual corrections to classification and/or extracted fields.
    Re-derives automation readiness after correction.
    """
    try:
        result = await apply_correction(
            doc_id=doc_id,
            corrected_type=body.corrected_type,
            corrected_fields=body.corrected_fields,
            corrected_by=body.corrected_by,
            correction_notes=body.notes,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Correction failed for %s: %s", doc_id, e)
        raise HTTPException(status_code=500, detail=f"Correction failed: {str(e)}")


# ── Auto-Draft Endpoints ─────────────────────────────────────────────────────

@router.post("/auto-draft/{doc_id}")
async def api_create_auto_draft(doc_id: str):
    """
    Create a downstream draft record from an automation-ready document.

    Validates readiness, maps doc type → draft type, creates draft only.
    Does NOT finalize, submit, or call BC APIs.
    Returns 409 if a draft was already created from this document.
    """
    try:
        result = await create_auto_draft(doc_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except DuplicateDraftError as e:
        return {
            "status": "duplicate",
            "message": str(e),
            "existing_action": e.existing_action,
        }
    except Exception as e:
        logger.error("Auto-draft creation failed for %s: %s", doc_id, e)
        raise HTTPException(status_code=500, detail=f"Auto-draft failed: {str(e)}")


@router.get("/auto-draft/{doc_id}")
async def api_get_automation_action(doc_id: str):
    """Get the latest automation action for a document."""
    action = await get_automation_action(doc_id)
    if not action:
        raise HTTPException(status_code=404, detail=f"No automation action for document: {doc_id}")
    return action


# ── Entity Resolution Endpoints ──────────────────────────────────────────────

class ResolutionCorrectionRequest(BaseModel):
    matched_entity_id: Optional[str] = None
    matched_entity_name: Optional[str] = None
    corrected_by: str = "admin"
    notes: str = ""
    mark_unmatched: bool = False


@router.post("/resolve-entities/{doc_id}")
async def api_resolve_entities(doc_id: str):
    """
    Resolve extracted entities (customer, vendor, PO#, invoice#) for a document.
    Returns resolution results with confidence and candidate matches.
    """
    try:
        result = await resolve_entities(doc_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Entity resolution failed for %s: %s", doc_id, e)
        raise HTTPException(status_code=500, detail=f"Entity resolution failed: {str(e)}")


@router.get("/resolution/{doc_id}")
async def api_get_resolutions(doc_id: str):
    """Get all stored entity resolution results for a document."""
    results = await get_resolutions(doc_id)
    return {"document_id": doc_id, "resolutions": results, "total": len(results)}


@router.patch("/resolution/{resolution_id}")
async def api_correct_resolution(resolution_id: str, body: ResolutionCorrectionRequest):
    """
    Manually correct an entity resolution result.
    Choose a different match, confirm a candidate, or mark unmatched.
    """
    try:
        result = await correct_resolution(
            resolution_id=resolution_id,
            matched_entity_id=body.matched_entity_id,
            matched_entity_name=body.matched_entity_name,
            corrected_by=body.corrected_by,
            notes=body.notes,
            mark_unmatched=body.mark_unmatched,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Resolution correction failed for %s: %s", resolution_id, e)
        raise HTTPException(status_code=500, detail=f"Correction failed: {str(e)}")


# ── Transaction Matching Endpoints ────────────────────────────────────────────

class MatchConfirmRequest(BaseModel):
    confirmed: bool = True
    selected_by: str = "admin"
    notes: str = ""


@router.post("/match-transactions/{doc_id}")
async def api_match_transactions(doc_id: str):
    """
    Search existing drafts/transactions for matches to this document.
    Returns candidates ranked by confidence.
    """
    try:
        result = await match_transactions(doc_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Transaction matching failed for %s: %s", doc_id, e)
        raise HTTPException(status_code=500, detail=f"Matching failed: {str(e)}")


@router.get("/transaction-matches/{doc_id}")
async def api_get_transaction_matches(doc_id: str):
    """Get all stored transaction match candidates for a document."""
    matches = await get_transaction_matches(doc_id)
    return {"document_id": doc_id, "matches": matches, "total": len(matches)}


@router.post("/auto-link/{doc_id}")
async def api_auto_link(doc_id: str):
    """
    Auto-link document to the best matched transaction.
    Only works with a single high-confidence match or a manually confirmed one.
    Ambiguous matches are rejected — must be confirmed first.
    """
    try:
        result = await auto_link(doc_id)
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except PermissionError as e:
        raise HTTPException(status_code=422, detail=str(e))
    except Exception as e:
        logger.error("Auto-link failed for %s: %s", doc_id, e)
        raise HTTPException(status_code=500, detail=f"Auto-link failed: {str(e)}")


@router.patch("/transaction-matches/{match_id}")
async def api_confirm_match(match_id: str, body: MatchConfirmRequest):
    """
    Manually confirm or reject a transaction match candidate.
    Confirming a match deselects all other candidates.
    """
    try:
        result = await confirm_match(
            match_id=match_id,
            confirmed=body.confirmed,
            selected_by=body.selected_by,
            notes=body.notes,
        )
        return result
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except Exception as e:
        logger.error("Match confirmation failed for %s: %s", match_id, e)
        raise HTTPException(status_code=500, detail=f"Confirmation failed: {str(e)}")
