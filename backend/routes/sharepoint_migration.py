"""
SharePoint Migration API Routes

REST API endpoints for the OneGamer to One_Gamer-Flat-Test SharePoint migration POC.
"""

import logging
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query
from pydantic import BaseModel
from motor.motor_asyncio import AsyncIOMotorDatabase

from services.sharepoint_migration_service import (
    SharePointMigrationService,
    DEFAULT_SOURCE_SITE,
    DEFAULT_SOURCE_LIBRARY,
    DEFAULT_SOURCE_FOLDER,
    DEFAULT_TARGET_SITE,
    DEFAULT_TARGET_LIBRARY
)

logger = logging.getLogger(__name__)

router = APIRouter(prefix="/migration/sharepoint", tags=["SharePoint Migration"])

# Will be set by server.py when mounting the router
db: AsyncIOMotorDatabase = None


def get_service() -> SharePointMigrationService:
    """Get the migration service instance."""
    if db is None:
        raise HTTPException(status_code=500, detail="Database not initialized")
    return SharePointMigrationService(db)


# Request/Response Models

class DiscoverRequest(BaseModel):
    """Request body for discovery endpoint."""
    sourceSiteUrl: str = DEFAULT_SOURCE_SITE
    sourceLibraryName: str = DEFAULT_SOURCE_LIBRARY
    sourceFolderPath: str = DEFAULT_SOURCE_FOLDER


class DiscoverResponse(BaseModel):
    """Response from discovery endpoint."""
    total_discovered: int
    new_candidates: int
    existing_candidates: int


class ClassifyRequest(BaseModel):
    """Request body for classification endpoint."""
    maxCount: int = 25


class ClassifyResponse(BaseModel):
    """Response from classification endpoint."""
    processed: int
    updated: int
    high_confidence: int
    low_confidence: int


class MigrateRequest(BaseModel):
    """Request body for migration endpoint."""
    targetSiteUrl: str = DEFAULT_TARGET_SITE
    targetLibraryName: str = DEFAULT_TARGET_LIBRARY
    maxCount: int = 20
    onlyIds: Optional[List[str]] = None


class MigrateResponse(BaseModel):
    """Response from migration endpoint."""
    attempted: int
    migrated: int
    errors: int


class CandidateUpdate(BaseModel):
    """Request body for updating a candidate - aligned with Excel metadata structure."""
    # NEW: Excel metadata fields
    acct_type: Optional[str] = None
    acct_name: Optional[str] = None
    document_type: Optional[str] = None
    document_sub_type: Optional[str] = None
    document_status: Optional[str] = None
    # Legacy fields
    doc_type: Optional[str] = None
    department: Optional[str] = None
    customer_name: Optional[str] = None
    vendor_name: Optional[str] = None
    project_or_part_number: Optional[str] = None
    document_date: Optional[str] = None
    retention_category: Optional[str] = None
    status: Optional[str] = None


# Endpoints

@router.get("/summary")
async def get_migration_summary():
    """
    Get summary statistics for migration candidates.
    
    Returns counts by status, doc_type, and confidence bands.
    """
    service = get_service()
    try:
        summary = await service.get_summary()
        return summary
    except Exception as e:
        logger.error(f"Error getting summary: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/discover", response_model=DiscoverResponse)
async def discover_candidates(request: DiscoverRequest):
    """
    Discover files in the source SharePoint folder.
    
    Creates migration_candidates records for each file found.
    Idempotent - running again will update existing records.
    """
    service = get_service()
    logger.info(f"Discovery request: {request.sourceSiteUrl}/{request.sourceLibraryName}/{request.sourceFolderPath}")
    
    try:
        result = await service.discover_candidates(
            source_site_url=request.sourceSiteUrl,
            source_library_name=request.sourceLibraryName,
            source_folder_path=request.sourceFolderPath
        )
        return DiscoverResponse(**result)
    except Exception as e:
        logger.error(f"Discovery error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/classify", response_model=ClassifyResponse)
async def classify_candidates(request: ClassifyRequest):
    """
    Classify discovered candidates using AI.
    
    Processes up to maxCount candidates and infers metadata.
    Sets status to 'ready_for_migration' if confidence >= 0.85.
    """
    service = get_service()
    logger.info(f"Classification request: maxCount={request.maxCount}")
    
    try:
        result = await service.classify_candidates(max_count=request.maxCount)
        return ClassifyResponse(**result)
    except Exception as e:
        logger.error(f"Classification error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/migrate", response_model=MigrateResponse)
async def migrate_candidates(request: MigrateRequest):
    """
    Migrate ready candidates to the target SharePoint site.
    
    Copies files and applies metadata columns.
    Idempotent - already migrated files are skipped.
    """
    service = get_service()
    logger.info(f"Migration request: {request.targetSiteUrl}, maxCount={request.maxCount}")
    
    try:
        result = await service.migrate_candidates(
            target_site_url=request.targetSiteUrl,
            target_library_name=request.targetLibraryName,
            max_count=request.maxCount,
            only_ids=request.onlyIds
        )
        return MigrateResponse(**result)
    except Exception as e:
        logger.error(f"Migration error: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candidates")
async def list_candidates(
    status: Optional[str] = Query(None, description="Filter by status"),
    exclude_status: Optional[str] = Query(None, description="Exclude this status"),
    doc_type: Optional[str] = Query(None, description="Filter by doc_type"),
    min_confidence: Optional[float] = Query(None, ge=0, le=1, description="Minimum confidence"),
    max_confidence: Optional[float] = Query(None, ge=0, le=1, description="Maximum confidence"),
    limit: int = Query(100, ge=1, le=500, description="Max results"),
    offset: int = Query(0, ge=0, description="Offset for pagination")
):
    """
    List migration candidates with optional filters.
    """
    service = get_service()
    
    try:
        candidates = await service.get_candidates(
            status=status,
            exclude_status=exclude_status,
            doc_type=doc_type,
            min_confidence=min_confidence,
            max_confidence=max_confidence,
            limit=limit,
            offset=offset
        )
        return {"candidates": candidates, "count": len(candidates)}
    except Exception as e:
        logger.error(f"Error listing candidates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/candidates/{candidate_id}")
async def get_candidate(candidate_id: str):
    """
    Get a single migration candidate by ID.
    """
    service = get_service()
    
    try:
        candidate = await service.get_candidate_by_id(candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="Candidate not found")
        return {"candidate": candidate}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error getting candidate: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.patch("/candidates/{candidate_id}")
async def update_candidate(candidate_id: str, updates: CandidateUpdate):
    """
    Update a migration candidate's metadata fields.
    
    Used for manual review/correction of AI-inferred metadata.
    Can also change status to 'ready_for_migration' for low-confidence items.
    """
    service = get_service()
    
    try:
        update_dict = updates.model_dump(exclude_none=True)
        if not update_dict:
            raise HTTPException(status_code=400, detail="No updates provided")
        
        success = await service.update_candidate(candidate_id, update_dict)
        if not success:
            raise HTTPException(status_code=404, detail="Candidate not found or no changes made")
        
        # Return updated candidate
        candidate = await service.get_candidate_by_id(candidate_id)
        return {"success": True, "candidate": candidate}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error updating candidate: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/candidates/{candidate_id}/approve")
async def approve_candidate(candidate_id: str):
    """
    Mark a candidate as ready for migration.
    
    Convenience endpoint for approving low-confidence items after review.
    """
    service = get_service()
    
    try:
        success = await service.update_candidate(candidate_id, {"status": "ready_for_migration"})
        if not success:
            raise HTTPException(status_code=404, detail="Candidate not found")
        
        candidate = await service.get_candidate_by_id(candidate_id)
        return {"success": True, "candidate": candidate}
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error approving candidate: {e}")
        raise HTTPException(status_code=500, detail=str(e))
