"""
SharePoint Migration API Routes

REST API endpoints for the OneGamer to One_Gamer-Flat-Test SharePoint migration POC.
"""

import logging
import asyncio
from typing import Optional, List
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
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

# Track background migration status
migration_status = {
    "running": False,
    "last_result": None,
    "processed": 0,
    "total": 0
}


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
    metadata_errors: int = 0


class ResetCandidatesRequest(BaseModel):
    """Request body for resetting candidates."""
    candidate_ids: Optional[List[str]] = None  # Reset specific IDs, or all migrated if None
    reset_to_status: str = "ready_for_migration"


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
async def migrate_candidates(request: MigrateRequest, background_tasks: BackgroundTasks):
    """
    Migrate ready candidates to the target SharePoint site.
    
    Copies files and applies metadata columns.
    Idempotent - already migrated files are skipped.
    For large files (videos), uses chunked upload.
    
    Returns immediately and processes in background to avoid timeout.
    """
    global migration_status
    
    if migration_status["running"]:
        # Return current status if already running
        return MigrateResponse(
            attempted=migration_status["processed"],
            migrated=0,
            errors=0,
            metadata_errors=0
        )
    
    service = get_service()
    batch_size = min(request.maxCount or 10, 10)
    logger.info(f"Migration request: {request.targetSiteUrl}, maxCount={batch_size}")
    
    async def run_migration():
        global migration_status
        migration_status["running"] = True
        migration_status["processed"] = 0
        try:
            result = await service.migrate_candidates(
                target_site_url=request.targetSiteUrl,
                target_library_name=request.targetLibraryName,
                max_count=batch_size,
                only_ids=request.onlyIds
            )
            migration_status["last_result"] = result
            migration_status["processed"] = result.get("attempted", 0)
            logger.info(f"Background migration complete: {result}")
        except Exception as e:
            logger.error(f"Background migration error: {e}")
            migration_status["last_result"] = {"error": str(e)}
        finally:
            migration_status["running"] = False
    
    # Start migration in background
    background_tasks.add_task(run_migration)
    
    # Return immediately with pending status
    return MigrateResponse(
        attempted=0,
        migrated=0,
        errors=0,
        metadata_errors=0
    )


@router.get("/migrate/status")
async def get_migration_status():
    """Get the current background migration status."""
    return migration_status


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


@router.post("/reset-candidates")
async def reset_candidates(request: ResetCandidatesRequest):
    """
    Reset candidates back to a specific status.
    
    This allows re-classification or re-migration to apply updated metadata.
    Optionally accepts specific candidate_ids, or resets based on status filter.
    """
    service = get_service()
    
    try:
        # Build query
        if request.candidate_ids:
            query = {"id": {"$in": request.candidate_ids}}
        elif request.reset_from_status:
            query = {"status": request.reset_from_status}
        else:
            # Default: reset all non-discovered (to force full re-classification)
            query = {"status": {"$ne": "discovered"}}
        
        # Reset the candidates
        result = await service.collection.update_many(
            query,
            {"$set": {
                "status": request.reset_to_status,
                "target_item_id": None,
                "target_url": None,
                "migration_timestamp": None,
                "migration_error": None,
                "metadata_write_status": None,
                "metadata_write_error": None
            }}
        )
        
        return {
            "success": True,
            "reset_count": result.modified_count,
            "reset_to_status": request.reset_to_status
        }
    except Exception as e:
        logger.error(f"Error resetting candidates: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/apply-metadata/{candidate_id}")
async def apply_metadata_to_existing(candidate_id: str):
    """
    Apply metadata to an already migrated file in SharePoint.
    
    Useful for fixing metadata on files that were migrated before columns existed.
    """
    service = get_service()
    
    try:
        # Get the candidate
        candidate = await service.get_candidate_by_id(candidate_id)
        if not candidate:
            raise HTTPException(status_code=404, detail="Candidate not found")
        
        if candidate.get("status") != "migrated" or not candidate.get("target_item_id"):
            raise HTTPException(status_code=400, detail="Candidate must be in migrated status with target_item_id")
        
        # Apply metadata
        result = await service.apply_metadata_to_migrated(candidate_id)
        
        return {
            "success": result.get("success", False),
            "metadata_write_status": result.get("status"),
            "error": result.get("error")
        }
    except HTTPException:
        raise
    except Exception as e:
        logger.error(f"Error applying metadata: {e}")
        raise HTTPException(status_code=500, detail=str(e))


@router.post("/retry-failed")
async def retry_failed_migrations(request: MigrateRequest):
    """
    Retry all failed migrations.
    
    Resets error status candidates to ready_for_migration and re-runs migration.
    """
    service = get_service()
    
    try:
        # Reset all error candidates to ready_for_migration
        reset_result = await service.collection.update_many(
            {"status": "error"},
            {"$set": {
                "status": "ready_for_migration",
                "migration_error": None
            }}
        )
        
        logger.info(f"Reset {reset_result.modified_count} failed candidates for retry")
        
        # Run migration
        result = await service.migrate_candidates(
            target_site_url=request.targetSiteUrl,
            target_library_name=request.targetLibraryName,
            max_count=request.maxCount or 50
        )
        
        return {
            "reset_count": reset_result.modified_count,
            **result
        }
    except Exception as e:
        logger.error(f"Error retrying failed migrations: {e}")
        raise HTTPException(status_code=500, detail=str(e))
