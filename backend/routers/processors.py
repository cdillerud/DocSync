"""
GPI Document Hub — Document Processor Router

Endpoints for processor management, testing, and diagnostics.
"""

from fastapi import APIRouter, Query
from typing import Optional
import logging

from processors.processor_registry import (
    get_registered_processors,
    detect_processor,
    run_processor,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/processors", tags=["Document Processors"])


@router.get("/registry")
async def list_processors():
    """List all registered document processors."""
    return {
        "processors": get_registered_processors(),
        "count": len(get_registered_processors()),
    }


@router.post("/test-detect")
async def test_processor_detection(body: dict):
    """
    Test which processor would match a given document text.

    Body: {
        "document_text": "...",
        "layout_fingerprint": { ... } (optional),
        "ai_classification": { ... } (optional)
    }
    """
    text = body.get("document_text", "")
    layout_fp = body.get("layout_fingerprint")
    ai_class = body.get("ai_classification")

    proc = detect_processor(text, layout_fp, ai_class)

    if proc:
        result = run_processor(proc, text, layout_fp)
        return {
            "matched": True,
            "processor_name": proc.name,
            "priority": proc.priority,
            "result": result,
        }
    else:
        return {
            "matched": False,
            "processor_name": None,
            "message": "No processor matched the document text",
        }


@router.get("/document/{doc_id}/processor-result")
async def get_processor_result_for_document(doc_id: str):
    """
    Get the processor result stored on a document (if any).
    """
    from deps import get_db
    db = get_db()
    doc = await db.hub_documents.find_one(
        {"id": doc_id},
        {"_id": 0, "id": 1, "processor_result": 1, "extracted_fields": 1}
    )
    if not doc:
        return {"error": "Document not found"}

    proc_result = doc.get("processor_result")
    proc_fields = (doc.get("extracted_fields") or {}).get("_processor_fields")

    return {
        "document_id": doc_id,
        "has_processor_result": proc_result is not None,
        "processor_result": proc_result,
        "processor_fields_in_extraction": proc_fields,
    }
