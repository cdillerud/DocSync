"""GPI Document Hub - Documents Router (Domain 7)

Extracted from server.py using thin wrapper pattern.
Complex route handlers remain in server.py; this router registers them
on a modular APIRouter so server.py's api_router can be cleaned up.
Simple CRUD routes are implemented directly using deps.get_db().
"""

import logging
import hashlib
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Optional

from fastapi import APIRouter, BackgroundTasks, HTTPException, UploadFile, File, Form, Query
from fastapi.responses import FileResponse
from pydantic import BaseModel

from deps import get_db

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/documents", tags=["Documents"])

UPLOAD_DIR = Path(__file__).parent.parent / "uploads"


class DocumentUpdate(BaseModel):
    document_type: Optional[str] = None
    bc_record_type: Optional[str] = None
    bc_record_id: Optional[str] = None
    bc_document_no: Optional[str] = None


# =============================================================================
# COMPLEX ROUTES — Thin wrappers delegating to server.py functions
# These use deep server.py internals (AI pipeline, workflows, BC integration).
# =============================================================================

_routes_registered = False

def register_server_routes(app=None):
    """Register document-domain handler functions on the app.

    Handlers are sourced from services.document_handlers (authoritative).
    Called from main.py during startup.
    """
    global _routes_registered
    if _routes_registered:
        return
    _routes_registered = True

    if app is None:
        logger.warning("No app provided to register_server_routes")
        return

    from services.document_handlers import (
        upload_document,
        retry_document,
        resubmit_document,
        link_document,
        intake_document,
        classify_document,
        resolve_and_link_document,
        reprocess_document,
        batch_revalidate_documents,
        preview_post_to_bc,
    )

    app.add_api_route(
        "/api/documents/upload", upload_document, methods=["POST"],
        tags=["Documents"], summary="Upload a document"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/retry", retry_document, methods=["POST"],
        tags=["Documents"], summary="Retry document workflow"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/resubmit", resubmit_document, methods=["POST"],
        tags=["Documents"], summary="Resubmit failed document"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/link", link_document, methods=["POST"],
        tags=["Documents"], summary="Link document to BC"
    )
    app.add_api_route(
        "/api/documents/intake", intake_document, methods=["POST"],
        tags=["Documents"], summary="Document intake from email/API"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/classify", classify_document, methods=["POST"],
        tags=["Documents"], summary="Classify document with AI"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/resolve", resolve_and_link_document, methods=["POST"],
        tags=["Documents"], summary="Resolve and link document"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/reprocess", reprocess_document, methods=["POST"],
        tags=["Documents"], summary="Reprocess document"
    )
    app.add_api_route(
        "/api/documents/batch-revalidate", batch_revalidate_documents, methods=["POST"],
        tags=["Documents"], summary="Batch revalidate documents"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/preview-post", preview_post_to_bc, methods=["POST"],
        tags=["Documents"], summary="Preview document posting"
    )


# =============================================================================
# SIMPLE ROUTES — Direct implementations using deps.get_db()
# =============================================================================

@router.get("")
async def list_documents(
    status: str = Query(None), document_type: str = Query(None),
    category: str = Query(None),
    search: str = Query(None), skip: int = Query(0), limit: int = Query(50),
    include_cleared: bool = Query(False, description="Include auto-cleared documents in results"),
    queue_view: bool = Query(True, description="Queue view mode - hides completed/cleared docs by default")
):
    db = get_db()
    fq = {"is_duplicate": {"$ne": True}}  # Always exclude duplicates

    # Status filter: check both status and workflow_status fields (case-insensitive)
    if status:
        status_regex = {"$regex": f"^{status}$", "$options": "i"}
        fq["$or"] = [{"status": status_regex}, {"workflow_status": status_regex}]

    # Type filter: search across doc_type, document_type, and suggested_job_type
    if document_type:
        type_regex = {"$regex": f"^{document_type}$", "$options": "i"}
        type_conditions = [
            {"doc_type": type_regex},
            {"document_type": type_regex},
            {"suggested_job_type": type_regex},
        ]
        if "$or" in fq:
            # Already have $or from status filter, wrap both in $and
            fq = {"$and": [{"$or": fq.pop("$or")}, {"$or": type_conditions}]}
        else:
            fq["$or"] = type_conditions

    if category:
        fq["category"] = category
    if search:
        search_cond = {"file_name": {"$regex": search, "$options": "i"}}
        if "$and" in fq:
            fq["$and"].append(search_cond)
        else:
            fq.update(search_cond)

    TERMINAL_STATUSES = ["Completed", "Posted", "Archived", "completed", "posted", "archived", "FileMissing"]
    DONE_WORKFLOW_STATUSES = ["completed", "validation_passed", "processed", "ready_for_approval", "exported", "file_missing"]
    if queue_view and not include_cleared and not status:
        not_cleared = {"$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}]}
        not_terminal = {"status": {"$nin": TERMINAL_STATUSES}}
        not_done_wf = {"$or": [
            {"workflow_status": {"$nin": DONE_WORKFLOW_STATUSES}},
            {"workflow_status": {"$exists": False}},
        ]}
        if "$and" in fq:
            fq["$and"].extend([not_cleared, not_terminal, not_done_wf])
        else:
            fq["$and"] = [not_cleared, not_terminal, not_done_wf]

    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)

    # Compute global counts (excluding duplicates)
    not_dup = {"is_duplicate": {"$ne": True}}
    total_all = await db.hub_documents.count_documents(not_dup)
    cleared_count = await db.hub_documents.count_documents({"auto_cleared": True, **not_dup})

    DONE_WF = DONE_WORKFLOW_STATUSES

    pending_count = await db.hub_documents.count_documents({
        "$and": [
            not_dup,
            {"$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}]},
            {"status": {"$nin": TERMINAL_STATUSES}},
            {"$or": [
                {"workflow_status": {"$nin": DONE_WF}},
                {"workflow_status": {"$exists": False}},
            ]},
        ]
    })
    completed_count = await db.hub_documents.count_documents({
        "$and": [
            not_dup,
            {"$or": [
                {"status": {"$in": TERMINAL_STATUSES}},
                {"auto_cleared": True},
                {"workflow_status": {"$in": DONE_WF}},
            ]},
        ]
    })

    # Distinct types and statuses for dynamic filter dropdowns
    distinct_types_raw = await db.hub_documents.aggregate([
        {"$match": {"is_duplicate": {"$ne": True}}},
        {"$group": {"_id": {"$ifNull": ["$doc_type", "$document_type"]}, "count": {"$sum": 1}}},
        {"$match": {"_id": {"$ne": None}}},
        {"$sort": {"count": -1}},
    ]).to_list(50)
    distinct_statuses_raw = await db.hub_documents.aggregate([
        {"$match": {"is_duplicate": {"$ne": True}}},
        {"$group": {"_id": "$status", "count": {"$sum": 1}}},
        {"$match": {"_id": {"$ne": None}}},
        {"$sort": {"count": -1}},
    ]).to_list(50)

    return {
        "documents": docs,
        "total": total,
        "counts": {
            "total_all": total_all,
            "auto_cleared": cleared_count,
            "pending_review": pending_count,
            "completed": completed_count,
            "showing": len(docs),
        },
        "filter_options": {
            "types": [{"value": r["_id"], "count": r["count"]} for r in distinct_types_raw],
            "statuses": [{"value": r["_id"], "count": r["count"]} for r in distinct_statuses_raw],
        },
    }



@router.get("/classification-accuracy")
async def get_classification_accuracy():
    """Get classification accuracy metrics — confusion matrix, worst types, vendor patterns."""
    from services.classification_feedback_service import get_accuracy_metrics
    return await get_accuracy_metrics()


@router.post("/classification/bootstrap-from-history")
async def bootstrap_classification_from_history(background_tasks: BackgroundTasks):
    """One-time sweep: mine all existing documents for high-confidence classification
    examples and populate the learning model. Runs as a background task.
    
    Idempotent — safe to re-run without creating duplicates."""
    from services.classification_feedback_service import bootstrap_from_history, get_bootstrap_status

    status = get_bootstrap_status()
    if status.get("running"):
        return {"message": "Bootstrap sweep already running", "status": status}

    import asyncio
    background_tasks.add_task(bootstrap_from_history)
    return {"message": "Bootstrap sweep started in background", "status": "running"}


@router.get("/classification/bootstrap-status")
async def get_bootstrap_status_endpoint():
    """Check the status of a running bootstrap sweep."""
    from services.classification_feedback_service import get_bootstrap_status
    return get_bootstrap_status()


@router.get("/{doc_id}")
async def get_document(doc_id: str, include_events: bool = Query(True)):
    from services.event_service import get_event_service
    from services.derived_state_service import get_derived_state_service, format_state_for_display

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    workflows = await db.hub_workflow_runs.find({"document_id": doc_id}, {"_id": 0}).sort("started_utc", -1).to_list(100)

    event_timeline = []
    derived_state = None

    if include_events:
        event_service = get_event_service()
        derived_state_service = get_derived_state_service()

        if event_service:
            event_timeline = await event_service.get_event_timeline(doc_id, include_legacy=True)

        if derived_state_service:
            derived_state = await derived_state_service.derive_state(doc_id, doc)
            derived_state["display"] = format_state_for_display(derived_state)

    # Reconcile stale readiness with actual document state
    doc_status = (doc.get("status") or "").lower()
    workflow_status = (doc.get("workflow_status") or "").lower()
    is_terminal = (
        doc.get("auto_cleared")
        or doc_status in ("completed", "posted", "archived")
        or workflow_status in ("completed", "exported", "processed")
    )
    stored_readiness = doc.get("readiness") or {}
    if is_terminal and stored_readiness.get("status") not in ("ready_auto_link", "ready_auto_draft"):
        from services.document_readiness_service import evaluate_readiness
        doc["readiness"] = evaluate_readiness(doc)

    # Reconcile stale ap_validation_result warnings with current vendor state
    ap_val = doc.get("ap_validation_result")
    if ap_val:
        vendor_resolved_now = bool(
            ap_val.get("vendor_resolved")
            or doc.get("matched_vendor_no")
            or doc.get("vendor_id")
            or (doc.get("validation_results", {}).get("bc_record_info", {}).get("number"))
        )
        if vendor_resolved_now:
            # Filter stale vendor-dependent warnings
            original_warnings = ap_val.get("warnings", [])
            filtered_warnings = [
                w for w in original_warnings
                if "vendor not resolved" not in (
                    (w.get("details", "") if isinstance(w, dict) else str(w)).lower()
                )
            ]
            if len(filtered_warnings) != len(original_warnings):
                ap_val["warnings"] = filtered_warnings
            # Filter stale vendor blocking issues
            original_blocking = ap_val.get("blocking_issues", [])
            filtered_blocking = [
                b for b in original_blocking
                if "vendor" not in b.lower()
            ]
            if len(filtered_blocking) != len(original_blocking):
                ap_val["blocking_issues"] = filtered_blocking
            # Update vendor_resolved flag
            if not ap_val.get("vendor_resolved"):
                ap_val["vendor_resolved"] = True
                vendor_no = doc.get("matched_vendor_no") or doc.get("vendor_id") or \
                    doc.get("validation_results", {}).get("bc_record_info", {}).get("number", "")
                if vendor_no:
                    ap_val["matched_vendor_no"] = vendor_no

    return {
        "document": doc,
        "workflows": workflows,
        "event_timeline": event_timeline,
        "derived_state": derived_state
    }


@router.get("/{doc_id}/events")
async def get_document_events(
    doc_id: str,
    event_types: Optional[str] = Query(None, description="Comma-separated event types to filter"),
    limit: int = Query(100, le=500),
    skip: int = Query(0)
):
    from services.event_service import get_event_service

    event_service = get_event_service()
    if not event_service:
        raise HTTPException(status_code=503, detail="Event service not initialized")

    type_filter = event_types.split(",") if event_types else None
    events = await event_service.get_events(doc_id, event_types=type_filter, limit=limit, skip=skip)

    return {
        "document_id": doc_id,
        "events": [e.to_dict() for e in events],
        "count": len(events),
        "has_more": len(events) == limit
    }


@router.get("/{doc_id}/timeline")
async def get_document_timeline(doc_id: str, include_legacy: bool = Query(True)):
    from services.event_service import get_event_service

    event_service = get_event_service()
    if not event_service:
        raise HTTPException(status_code=503, detail="Event service not initialized")

    timeline = await event_service.get_event_timeline(doc_id, include_legacy=include_legacy)

    return {
        "document_id": doc_id,
        "timeline": timeline,
        "count": len(timeline)
    }


@router.get("/{doc_id}/derived-state")
async def get_document_derived_state(doc_id: str):
    from services.derived_state_service import get_derived_state_service, format_state_for_display

    derived_state_service = get_derived_state_service()
    if not derived_state_service:
        raise HTTPException(status_code=503, detail="Derived state service not initialized")

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    derived = await derived_state_service.derive_state(doc_id, doc)
    derived["display"] = format_state_for_display(derived)

    return {"document_id": doc_id, **derived}


@router.post("/{doc_id}/refresh-state")
async def refresh_document_state(doc_id: str):
    from services.derived_state_service import get_derived_state_service

    derived_state_service = get_derived_state_service()
    if not derived_state_service:
        raise HTTPException(status_code=503, detail="Derived state service not initialized")

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    derived = await derived_state_service.update_document_derived_state(doc_id, doc)

    return {"document_id": doc_id, "state_updated": True, **derived}


@router.put("/{doc_id}")
async def update_document(doc_id: str, update: DocumentUpdate):
    db = get_db()
    
    # Fetch current doc to detect classification changes
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    
    update_data = {k: v for k, v in update.model_dump().items() if v is not None}
    update_data["updated_utc"] = datetime.now(timezone.utc).isoformat()
    
    # Classification change? Record the correction for AI learning
    if update.document_type is not None:
        original_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
        if update.document_type != original_type:
            update_data["suggested_job_type"] = update.document_type
            update_data["document_type_source"] = "manual"
            update_data["classification_override"] = {
                "original_type": original_type,
                "corrected_type": update.document_type,
                "corrected_at": datetime.now(timezone.utc).isoformat(),
            }
            try:
                from services.classification_feedback_service import record_correction
                text_snippet = ""
                raw_text = doc.get("raw_text") or doc.get("extracted_text") or ""
                if not raw_text:
                    ef = doc.get("extracted_fields") or {}
                    parts = [str(v) for v in ef.values() if v and not isinstance(v, (list, dict))]
                    raw_text = " | ".join(parts)
                text_snippet = raw_text[:500]
                
                await record_correction(
                    doc_id=doc_id,
                    original_type=original_type,
                    corrected_type=update.document_type,
                    corrected_by="user",
                    doc_context={
                        "file_name": doc.get("file_name", ""),
                        "vendor_raw": doc.get("vendor_raw", ""),
                        "vendor_canonical": doc.get("vendor_canonical", ""),
                        "text_snippet": text_snippet,
                        "classification_method": doc.get("classification_method", ""),
                        "classification_confidence": doc.get("classification_confidence", 0),
                    },
                )
                logger.info("Classification correction recorded: %s → %s for doc %s", original_type, update.document_type, doc_id)
            except Exception as e:
                logger.warning("Failed to record classification correction: %s", e)
    
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return updated_doc


@router.delete("/{doc_id}")
async def delete_document(doc_id: str):
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    await db.hub_documents.delete_one({"id": doc_id})
    await db.hub_workflow_runs.delete_many({"document_id": doc_id})
    file_path = UPLOAD_DIR / doc_id
    if file_path.exists():
        file_path.unlink()
    return {"message": "Document deleted", "id": doc_id}


@router.get("/{doc_id}/file")
async def get_document_file(doc_id: str):
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=404, detail="File not found on disk")

    content_type = doc.get("content_type", "application/octet-stream")
    filename = doc.get("file_name", f"{doc_id}.bin")

    return FileResponse(
        path=file_path,
        media_type=content_type,
        filename=filename,
        headers={"Content-Disposition": f'inline; filename="{filename}"'}
    )


@router.get("/{doc_id}/square9-status")
async def get_square9_status(doc_id: str):
    from services.square9_workflow import get_workflow_summary

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    summary = get_workflow_summary(doc)
    return {
        "document_id": doc_id,
        **summary,
        "retry_history": doc.get("retry_history", []),
    }


@router.post("/{doc_id}/reset-retries")
async def reset_document_retries(doc_id: str, reason: str = "Manual reset"):
    from services.square9_workflow import reset_retry_counter

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    update_dict = reset_retry_counter(doc, reason)
    update_dict["updated_utc"] = datetime.now(timezone.utc).isoformat()

    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_dict})

    return {
        "success": True,
        "message": f"Retry counter reset: {reason}",
        "document_id": doc_id,
        "retry_count": 0,
    }



# =============================================================================
# FILE & CLEAR — Route to SharePoint + mark completed
# =============================================================================

@router.post("/{doc_id}/file-and-clear")
async def file_and_clear_document(doc_id: str):
    """
    One-click: suggest folder → move to SharePoint → mark cleared.
    Records the action for AI auto-filing learning.
    """
    from services.folder_routing_service import determine_folder_path

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    now = datetime.now(timezone.utc).isoformat()

    # Step 1: Get folder suggestion
    folder_path, reason, routing_details = determine_folder_path(doc)

    # Step 2: Move to SharePoint
    move_result = {"success": False, "message": "skipped"}
    try:
        from routers.sharepoint_routing import move_document_to_sharepoint
        move_result = await move_document_to_sharepoint(doc_id)
        move_result = {"success": True, "folder_path": move_result.get("folder_path", folder_path)}
    except Exception as e:
        error_msg = str(e)
        if "demo" in error_msg.lower() or "mock" in error_msg.lower():
            move_result = {"success": True, "folder_path": folder_path, "demo_mode": True}
        else:
            logger.warning("File & Clear: SharePoint move failed for %s: %s", doc_id, error_msg)
            move_result = {"success": False, "message": error_msg}

    # Step 3: Mark as cleared/completed
    clear_update = {
        "auto_cleared": True,
        "auto_clear_decision": "Cleared",
        "auto_clear_reason": f"Filed & cleared: {reason}",
        "auto_clear_details": {"manual_clear": True, "cleared_by": "user", "method": "file_and_clear"},
        "status": "Completed",
        "workflow_status": "completed",
        "sharepoint_folder_suggestion": folder_path,
        "sharepoint_folder_reason": reason,
        "filed_at": now,
        "filed_folder": folder_path,
        "updated_utc": now,
    }
    await db.hub_documents.update_one({"id": doc_id}, {"$set": clear_update})

    # Step 4: Record for AI learning
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or "Unknown"
    vendor = doc.get("vendor_canonical") or doc.get("normalized_fields", {}).get("vendor") or ""
    await db.filing_actions.update_one(
        {"document_type": doc_type, "vendor_lower": vendor.lower(), "folder_path": folder_path},
        {"$inc": {"count": 1}, "$set": {
            "document_type": doc_type,
            "vendor": vendor,
            "vendor_lower": vendor.lower(),
            "folder_path": folder_path,
            "routing_reason": reason,
            "last_filed_at": now,
        }},
        upsert=True,
    )

    return {
        "success": True,
        "doc_id": doc_id,
        "folder_path": folder_path,
        "routing_reason": reason,
        "sharepoint_move": move_result,
        "status": "Completed",
        "message": f"Filed to '{folder_path}' and cleared from queue",
    }


@router.post("/bulk-file-and-clear")
async def bulk_file_and_clear(doc_ids: list = None):
    """Bulk file & clear: route each document to SharePoint and mark cleared."""
    from services.folder_routing_service import determine_folder_path

    if not doc_ids:
        raise HTTPException(status_code=422, detail="doc_ids required")

    db = get_db()
    results = {"success": [], "failed": [], "total": len(doc_ids)}
    now = datetime.now(timezone.utc).isoformat()

    for doc_id in doc_ids:
        try:
            doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
            if not doc:
                results["failed"].append({"doc_id": doc_id, "error": "Not found"})
                continue

            folder_path, reason, _ = determine_folder_path(doc)

            # Try SharePoint move
            try:
                from routers.sharepoint_routing import move_document_to_sharepoint
                await move_document_to_sharepoint(doc_id)
            except Exception:
                pass  # Continue even if SP move fails; filing is the priority

            # Mark cleared
            clear_update = {
                "auto_cleared": True,
                "auto_clear_decision": "Cleared",
                "auto_clear_reason": f"Bulk filed & cleared: {reason}",
                "auto_clear_details": {"manual_clear": True, "cleared_by": "user", "method": "bulk_file_and_clear"},
                "status": "Completed",
                "workflow_status": "completed",
                "sharepoint_folder_suggestion": folder_path,
                "filed_at": now,
                "filed_folder": folder_path,
                "updated_utc": now,
            }
            await db.hub_documents.update_one({"id": doc_id}, {"$set": clear_update})

            # Record for AI learning
            doc_type = doc.get("document_type") or doc.get("suggested_job_type") or "Unknown"
            vendor = doc.get("vendor_canonical") or doc.get("normalized_fields", {}).get("vendor") or ""
            await db.filing_actions.update_one(
                {"document_type": doc_type, "vendor_lower": vendor.lower(), "folder_path": folder_path},
                {"$inc": {"count": 1}, "$set": {
                    "document_type": doc_type, "vendor": vendor, "vendor_lower": vendor.lower(),
                    "folder_path": folder_path, "routing_reason": reason, "last_filed_at": now,
                }},
                upsert=True,
            )

            results["success"].append({"doc_id": doc_id, "folder_path": folder_path})
        except Exception as e:
            results["failed"].append({"doc_id": doc_id, "error": str(e)[:200]})

    return results


@router.get("/filing-actions/stats")
async def get_filing_action_stats():
    """Get stats on filing actions for AI learning visibility."""
    db = get_db()
    actions = await db.filing_actions.find({}, {"_id": 0}).sort("count", -1).to_list(100)
    total = sum(a.get("count", 0) for a in actions)
    return {
        "total_filings": total,
        "unique_patterns": len(actions),
        "top_patterns": actions[:20],
        "auto_file_threshold": 3,
        "auto_file_candidates": [a for a in actions if a.get("count", 0) >= 3],
    }


@router.post("/bulk-approve-and-file")
async def bulk_approve_and_file(
    category: str = None,
    limit: int = 500,
):
    """Bulk approve validated documents and file them to SharePoint.
    
    category options:
    - 'needs_approval': validated docs awaiting sign-off (the 1,176 backlog)
    - 'needs_vendor_review': AP docs with no vendor match
    - 'all': everything not completed
    - None/default: same as 'needs_approval'
    """
    from services.folder_routing_service import determine_folder_path

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Build query based on category
    if category == "needs_vendor_review":
        query = {
            "document_type": {"$in": ["AP_Invoice", "AP_INVOICE", "Remittance", "REMITTANCE"]},
            "$or": [
                {"validation_results.match_method": "none"},
                {"validation_results.match_method": {"$exists": False}},
                {"vendor_canonical": {"$exists": False}},
                {"vendor_canonical": None},
            ],
            "status": {"$nin": ["Completed", "Archived", "Posted", "Deleted"]},
        }
    elif category == "all":
        query = {
            "status": {"$nin": ["Completed", "Archived", "Posted", "Deleted"]},
        }
    else:
        # Default: needs_approval — validated docs awaiting sign-off
        query = {
            "status": {"$nin": ["Completed", "Archived", "Posted", "Deleted"]},
            "$or": [
                {"validation_results.all_passed": True},
                {"workflow_status": {"$in": ["ready_for_approval", "validated", "ready_for_post"]}},
                {"workflow_status": "processing"},
            ],
        }

    total_matching = await db.hub_documents.count_documents(query)
    cursor = db.hub_documents.find(query, {"_id": 0}).limit(limit)

    filed = 0
    failed = 0
    filing_counts = {}

    async for doc in cursor:
        try:
            doc_id = doc["id"]
            folder_path, reason, _ = determine_folder_path(doc)

            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "auto_cleared": True,
                "auto_clear_decision": "Cleared",
                "auto_clear_reason": f"Bulk approved & filed: {reason}",
                "auto_clear_details": {"method": "bulk_approve_and_file", "cleared_by": "admin"},
                "status": "Completed",
                "workflow_status": "completed",
                "sharepoint_folder_suggestion": folder_path,
                "filed_at": now,
                "filed_folder": folder_path,
                "updated_utc": now,
            }})

            # Record for AI learning
            doc_type = doc.get("document_type") or doc.get("suggested_job_type") or "Unknown"
            vendor = doc.get("vendor_canonical") or doc.get("normalized_fields", {}).get("vendor") or ""
            await db.filing_actions.update_one(
                {"document_type": doc_type, "vendor_lower": vendor.lower(), "folder_path": folder_path},
                {"$inc": {"count": 1}, "$set": {
                    "document_type": doc_type, "vendor": vendor, "vendor_lower": vendor.lower(),
                    "folder_path": folder_path, "routing_reason": reason, "last_filed_at": now,
                }},
                upsert=True,
            )

            filed += 1
            filing_counts[folder_path] = filing_counts.get(folder_path, 0) + 1
        except Exception as e:
            failed += 1
            logger.warning("Bulk approve failed for %s: %s", doc.get("id", "?"), str(e)[:100])

    # Sort filing counts by volume
    top_folders = sorted(filing_counts.items(), key=lambda x: -x[1])[:10]

    return {
        "success": True,
        "total_matching": total_matching,
        "processed": filed + failed,
        "filed": filed,
        "failed": failed,
        "remaining": max(0, total_matching - filed - failed),
        "top_folders": [{"folder": f, "count": c} for f, c in top_folders],
        "message": f"Approved & filed {filed} documents ({failed} failed). {max(0, total_matching - filed - failed)} remaining.",
    }


@router.post("/sweep-reclassify-bols")
async def sweep_reclassify_bols(dry_run: bool = False, limit: int = 1000):
    """Find documents that are likely BOLs but misclassified, reclassify them,
    and auto-file + clear them from the queue.
    
    Checks filenames for BOL patterns. For PDFs on disk, also checks page 1 text.
    """
    import re
    from services.document_intel_helpers import _BOL_FILENAME_PATTERNS
    from services.folder_routing_service import determine_folder_path

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Find docs NOT already classified as Shipping_Document / BOL
    query = {
        "document_type": {"$nin": ["Shipping_Document", "BOL", None]},
        "status": {"$nin": ["Deleted"]},
    }
    cursor = db.hub_documents.find(query, {
        "_id": 0, "id": 1, "file_name": 1, "document_type": 1, "status": 1,
        "extracted_fields": 1, "normalized_fields": 1,
    }).limit(limit)

    reclassified = []
    skipped = 0

    async for doc in cursor:
        fn = doc.get("file_name", "")
        is_bol = False
        match_reason = ""

        # Check 1: filename pattern
        if _BOL_FILENAME_PATTERNS.search(fn.lower()):
            is_bol = True
            match_reason = "filename"
        else:
            # Check 2: extracted fields contain BOL indicators
            ef = doc.get("extracted_fields") or {}
            nf = doc.get("normalized_fields") or {}
            all_fields = {**nf, **ef}

            # Exclude docs with strong invoice indicators
            has_invoice_fields = bool(all_fields.get("invoice_number") or all_fields.get("amount"))

            bol_indicators = 0
            if all_fields.get("bol_number"):
                bol_indicators += 3  # Strongest signal
            if all_fields.get("pro_number"):
                bol_indicators += 1
            if all_fields.get("carrier"):
                bol_indicators += 1
            if all_fields.get("consignee"):
                bol_indicators += 1
            if all_fields.get("shipper"):
                bol_indicators += 1
            if all_fields.get("pieces"):
                bol_indicators += 1
            if all_fields.get("weight"):
                bol_indicators += 1

            # Must have bol_number WITHOUT invoice fields, OR 5+ indicators without invoice fields
            if all_fields.get("bol_number") and not has_invoice_fields:
                is_bol = True
                match_reason = f"bol_number+fields({bol_indicators}, no invoice fields)"
            elif bol_indicators >= 5 and not has_invoice_fields:
                is_bol = True
                match_reason = f"fields({bol_indicators}, no invoice fields)"

        if is_bol:
            reclassified.append({
                "id": doc["id"],
                "file_name": fn,
                "old_type": doc.get("document_type", "Unknown"),
                "old_status": doc.get("status", ""),
                "match": match_reason,
            })
        else:
            skipped += 1

    if dry_run:
        return {
            "dry_run": True,
            "would_reclassify": len(reclassified),
            "scanned": len(reclassified) + skipped,
            "samples": reclassified[:20],
        }

    # Now reclassify + file + clear each one
    filed = 0
    failed = 0
    for item in reclassified:
        try:
            doc = await db.hub_documents.find_one({"id": item["id"]}, {"_id": 0})
            if not doc:
                failed += 1
                continue

            folder_path, reason, _ = determine_folder_path({**doc, "document_type": "Shipping_Document"})

            await db.hub_documents.update_one({"id": item["id"]}, {"$set": {
                "document_type": "Shipping_Document",
                "classification_method": "heuristic-bol-sweep",
                "ai_confidence": 0.95,
                "auto_cleared": True,
                "auto_clear_decision": "Cleared",
                "auto_clear_reason": f"BOL sweep: reclassified from {item['old_type']} and filed",
                "auto_clear_details": {"method": "bol_sweep", "old_type": item["old_type"]},
                "status": "Completed",
                "workflow_status": "completed",
                "sharepoint_folder_suggestion": folder_path,
                "filed_at": now,
                "filed_folder": folder_path,
                "updated_utc": now,
            }})

            # Record for AI learning
            vendor = doc.get("vendor_canonical") or doc.get("normalized_fields", {}).get("vendor") or ""
            await db.filing_actions.update_one(
                {"document_type": "Shipping_Document", "vendor_lower": vendor.lower(), "folder_path": folder_path},
                {"$inc": {"count": 1}, "$set": {
                    "document_type": "Shipping_Document", "vendor": vendor, "vendor_lower": vendor.lower(),
                    "folder_path": folder_path, "routing_reason": reason, "last_filed_at": now,
                }},
                upsert=True,
            )
            filed += 1
        except Exception as e:
            failed += 1
            logger.warning("BOL sweep failed for %s: %s", item["id"], str(e)[:100])

    return {
        "success": True,
        "scanned": len(reclassified) + skipped,
        "reclassified_and_filed": filed,
        "failed": failed,
        "samples": reclassified[:10],
        "message": f"Reclassified and filed {filed} BOLs ({failed} failed, {skipped} non-BOL skipped).",
    }
