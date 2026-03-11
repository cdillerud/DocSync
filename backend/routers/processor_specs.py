"""
GPI Document Hub — Processor Spec API Router

CRUD, generation, and status management for processor implementation specs.
"""

from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from typing import Optional, List, Dict, Any
import logging

from services.processor_spec_service import get_processor_spec_service

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/processor-specs", tags=["Processor Specs"])


def _svc():
    svc = get_processor_spec_service()
    if not svc:
        raise HTTPException(status_code=503, detail="Processor Spec service not initialized")
    return svc


# ─── Request Models ────────────────────────────────────────────────────

class CreateSpecRequest(BaseModel):
    processor_name: str
    layout_family_id: str = ""
    doc_type: str = ""
    description: str = ""
    sample_document_ids: List[str] = []
    detection_patterns: Optional[Dict] = None
    field_mappings: List[Dict] = []
    vendor_hints: List[str] = []
    reference_hints: List[Dict] = []
    notes: str = ""


class UpdateSpecRequest(BaseModel):
    processor_name: Optional[str] = None
    layout_family_id: Optional[str] = None
    doc_type: Optional[str] = None
    description: Optional[str] = None
    sample_document_ids: Optional[List[str]] = None
    detection_patterns: Optional[Dict] = None
    field_mappings: Optional[List[Dict]] = None
    vendor_hints: Optional[List[str]] = None
    reference_hints: Optional[List[Dict]] = None
    notes: Optional[str] = None


class SetStatusRequest(BaseModel):
    status: str


class GenerateFromCandidateRequest(BaseModel):
    processor_name: str
    layout_family_id: str = ""
    doc_type: str = ""
    description: str = ""
    sample_document_ids: List[str] = []
    detected_keywords: List[str] = []
    detected_vendor_patterns: List[str] = []
    layout_hints: List[str] = []
    detected_fields: Dict[str, Any] = {}
    reference_patterns: List[Dict] = []
    vendor_hints: List[str] = []
    source: str = "manual"


# ─── Endpoints ─────────────────────────────────────────────────────────

@router.get("/stats")
async def spec_stats():
    """Get processor spec statistics."""
    return await _svc().get_stats()


@router.get("/list")
async def list_specs(
    status: Optional[str] = None,
    limit: int = Query(50, ge=1, le=500),
    skip: int = Query(0, ge=0),
):
    """List all processor specs with optional status filter."""
    return await _svc().list_specs(status=status, limit=limit, skip=skip)


@router.post("/create")
async def create_spec(req: CreateSpecRequest):
    """Create a new processor spec."""
    return await _svc().create_spec(
        processor_name=req.processor_name,
        layout_family_id=req.layout_family_id,
        doc_type=req.doc_type,
        description=req.description,
        sample_document_ids=req.sample_document_ids,
        detection_patterns=req.detection_patterns,
        field_mappings=req.field_mappings,
        vendor_hints=req.vendor_hints,
        reference_hints=req.reference_hints,
        notes=req.notes,
    )


@router.get("/{spec_id}")
async def get_spec(spec_id: str):
    """Get a single processor spec."""
    spec = await _svc().get_spec(spec_id)
    if not spec:
        raise HTTPException(status_code=404, detail="Spec not found")
    return spec


@router.put("/{spec_id}")
async def update_spec(spec_id: str, req: UpdateSpecRequest):
    """Update a processor spec."""
    updates = {k: v for k, v in req.dict().items() if v is not None}
    if not updates:
        raise HTTPException(status_code=400, detail="No updates provided")
    result = await _svc().update_spec(spec_id, updates)
    if not result:
        raise HTTPException(status_code=404, detail="Spec not found")
    return result


@router.delete("/{spec_id}")
async def delete_spec(spec_id: str):
    """Delete a processor spec."""
    success = await _svc().delete_spec(spec_id)
    if not success:
        raise HTTPException(status_code=404, detail="Spec not found")
    return {"deleted": True, "spec_id": spec_id}


@router.post("/{spec_id}/set-status")
async def set_status(spec_id: str, req: SetStatusRequest):
    """Change the status of a processor spec."""
    result = await _svc().set_status(spec_id, req.status)
    if not result:
        raise HTTPException(status_code=400, detail="Invalid status or spec not found")
    return result


@router.post("/{spec_id}/generate")
async def generate_outputs(spec_id: str):
    """Generate brief, JSON spec, and implementation prompt from spec data."""
    result = await _svc().generate_outputs(spec_id)
    if result.get("error"):
        raise HTTPException(status_code=404, detail=result["error"])
    return result


@router.post("/generate-from-candidate")
async def generate_from_candidate(req: GenerateFromCandidateRequest):
    """Generate a full spec from a processor discovery candidate."""
    return await _svc().generate_from_candidate(req.dict())
