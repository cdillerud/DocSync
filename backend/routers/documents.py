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

from fastapi import APIRouter, HTTPException, UploadFile, File, Form, Query
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
    """Register complex server.py handler functions directly on the app.
    Called from main.py during startup after server module is fully loaded.
    Must receive the FastAPI app instance since include_router copies routes
    at registration time, not dynamically.
    """
    global _routes_registered
    if _routes_registered:
        return
    _routes_registered = True

    if app is None:
        logger.warning("No app provided to register_server_routes")
        return

    import server

    app.add_api_route(
        "/api/documents/upload", server.upload_document, methods=["POST"],
        tags=["Documents"], summary="Upload a document"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/retry", server.retry_document, methods=["POST"],
        tags=["Documents"], summary="Retry document workflow"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/resubmit", server.resubmit_document, methods=["POST"],
        tags=["Documents"], summary="Resubmit failed document"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/link", server.link_document, methods=["POST"],
        tags=["Documents"], summary="Link document to BC"
    )
    app.add_api_route(
        "/api/documents/intake", server.intake_document, methods=["POST"],
        tags=["Documents"], summary="Document intake from email/API"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/classify", server.classify_document, methods=["POST"],
        tags=["Documents"], summary="Classify document with AI"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/resolve", server.resolve_and_link_document, methods=["POST"],
        tags=["Documents"], summary="Resolve and link document"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/reprocess", server.reprocess_document, methods=["POST"],
        tags=["Documents"], summary="Reprocess document"
    )
    app.add_api_route(
        "/api/documents/batch-revalidate", server.batch_revalidate_documents, methods=["POST"],
        tags=["Documents"], summary="Batch revalidate documents"
    )
    app.add_api_route(
        "/api/documents/{doc_id}/preview-post", server.preview_post_to_bc, methods=["POST"],
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
    fq = {}
    if status:
        fq["status"] = status
    if document_type:
        fq["document_type"] = document_type
    if category:
        fq["category"] = category
    if search:
        fq["file_name"] = {"$regex": search, "$options": "i"}

    if queue_view and not include_cleared and not status:
        fq["$and"] = [
            {"$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}]},
            {"status": {"$nin": ["Completed", "Posted", "Archived"]}}
        ]

    total = await db.hub_documents.count_documents(fq)
    docs = await db.hub_documents.find(fq, {"_id": 0}).sort("created_utc", -1).skip(skip).limit(limit).to_list(limit)

    total_all = await db.hub_documents.count_documents({})
    cleared_count = await db.hub_documents.count_documents({"auto_cleared": True})
    pending_count = await db.hub_documents.count_documents({
        "$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}],
        "status": {"$nin": ["Completed", "Posted", "Archived"]}
    })

    return {
        "documents": docs,
        "total": total,
        "counts": {
            "total_all": total_all,
            "auto_cleared": cleared_count,
            "pending_review": pending_count,
            "showing": len(docs)
        }
    }


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
    update_data = {k: v for k, v in update.model_dump().items() if v is not None}
    update_data["updated_utc"] = datetime.now(timezone.utc).isoformat()
    result = await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
    if result.matched_count == 0:
        raise HTTPException(status_code=404, detail="Document not found")
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return doc


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
