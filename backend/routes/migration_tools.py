"""
Legacy migration tools: run/preview/generate-sample/stats/supported-types.

Extracted VERBATIM from server.py during the routes/ migration (see
MIGRATION_PROGRESS.md at repo root, Group 14). No logic changed.
"""
from pathlib import Path
from typing import Optional
from fastapi import APIRouter, HTTPException, Query, BackgroundTasks
from pydantic import BaseModel

from core.db import db
from services.workflow_engine import DocType
from services.migration import (
    MigrationJob, MigrationResult, LegacyDocumentSource,
    JsonFileSource, InMemorySource, WorkflowInitializer,
)
from services.migration.job import MigrationMode, MigrationJobBuilder
from services.migration.sources import create_sample_migration_file

router = APIRouter(prefix="/api")


class MigrationRequest(BaseModel):
    """Request model for starting a migration job."""
    source_file: Optional[str] = None
    source_filter: Optional[str] = None  # "SQUARE9" or "ZETADOCS"
    doc_type_filter: Optional[str] = None
    limit: Optional[int] = None
    mode: str = "dry_run"  # "dry_run" or "real"

@router.post("/migration/run")
async def run_migration_job(
    request: MigrationRequest,
    background_tasks: BackgroundTasks
):
    """
    Start a migration job to import legacy documents.
    
    The job reads documents from the specified source file and imports them
    into GPI Hub with proper classification and workflow initialization.
    
    Modes:
    - dry_run: Validate and preview without writing to database
    - real: Actually write documents to database
    
    Returns migration result with statistics and sample documents.
    """
    # Determine source
    if request.source_file:
        source_path = Path(request.source_file)
        if not source_path.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Source file not found: {request.source_file}"
            )
        source = JsonFileSource(request.source_file)
    else:
        # Use default sample migration file
        sample_path = "/app/backend/data/sample_migration.json"
        if not Path(sample_path).exists():
            # Create sample file if it doesn't exist
            Path(sample_path).parent.mkdir(parents=True, exist_ok=True)
            create_sample_migration_file(sample_path)
        source = JsonFileSource(sample_path)
    
    # Determine mode
    try:
        mode = MigrationMode(request.mode)
    except ValueError:
        raise HTTPException(
            status_code=400,
            detail=f"Invalid mode: {request.mode}. Use 'dry_run' or 'real'"
        )
    
    # Create job
    job = MigrationJob(
        source=source,
        db_collection=db.hub_documents if mode == MigrationMode.REAL else None,
        skip_duplicates=True,
        batch_size=100
    )
    
    # Run job
    result = await job.run(
        mode=mode,
        source_filter=request.source_filter,
        doc_type_filter=request.doc_type_filter,
        limit=request.limit
    )
    
    return result.to_dict()


@router.get("/migration/preview")
async def preview_migration(
    source_file: Optional[str] = None,
    source_filter: Optional[str] = None,
    doc_type_filter: Optional[str] = None,
    limit: int = Query(10, le=100)
):
    """
    Preview legacy documents before migration.
    
    Returns a sample of documents that would be migrated, with their
    classification and workflow status preview.
    """
    # Determine source
    if source_file:
        source_path = Path(source_file)
        if not source_path.exists():
            raise HTTPException(
                status_code=400,
                detail=f"Source file not found: {source_file}"
            )
        source = JsonFileSource(source_file)
    else:
        sample_path = "/app/backend/data/sample_migration.json"
        if not Path(sample_path).exists():
            Path(sample_path).parent.mkdir(parents=True, exist_ok=True)
            create_sample_migration_file(sample_path)
        source = JsonFileSource(sample_path)
    
    # Get document count
    total_count = source.get_document_count(source_filter, doc_type_filter)
    
    # Preview documents
    documents = []
    for legacy_doc in source.iter_documents(source_filter, doc_type_filter, limit):
        # Show raw legacy data and what it would become
        preview = {
            "legacy": legacy_doc.to_dict(),
            "preview": {}
        }
        
        # Classify
        metadata = legacy_doc.metadata
        from services.workflow_engine import ZETADOCS_SET_MAPPING, SQUARE9_WORKFLOW_MAPPING
        
        doc_type = DocType.OTHER.value
        if metadata.legacy_zetadocs_set_code:
            result = ZETADOCS_SET_MAPPING.get(metadata.legacy_zetadocs_set_code)
            if result:
                doc_type = result[0].value
        elif metadata.legacy_workflow_name:
            result = SQUARE9_WORKFLOW_MAPPING.get(metadata.legacy_workflow_name)
            if result:
                doc_type = result.value
        
        # Get workflow preview
        workflow_result = WorkflowInitializer.initialize(doc_type, metadata)
        
        preview["preview"] = {
            "doc_type": doc_type,
            "workflow_status": workflow_result.workflow_status,
            "workflow_reason": workflow_result.reason
        }
        
        documents.append(preview)
    
    return {
        "source_name": source.get_source_name(),
        "total_count": total_count,
        "preview_count": len(documents),
        "filters": {
            "source_filter": source_filter,
            "doc_type_filter": doc_type_filter,
            "limit": limit
        },
        "documents": documents
    }


@router.post("/migration/generate-sample")
async def generate_sample_migration_file(
    output_path: str = Query(default="/app/backend/data/sample_migration.json")
):
    """
    Generate a sample migration JSON file for testing.
    
    Creates a file with realistic legacy documents from Square9 and Zetadocs.
    """
    try:
        create_sample_migration_file(output_path)
        return {
            "success": True,
            "path": output_path,
            "message": "Sample migration file created successfully"
        }
    except Exception as e:
        raise HTTPException(
            status_code=500,
            detail=f"Failed to create sample file: {str(e)}"
        )


@router.get("/migration/stats")
async def get_migration_stats():
    """
    Get statistics about migrated documents in the system.
    """
    # Count migrated documents by source system
    pipeline = [
        {"$match": {"is_migrated": True}},
        {"$group": {
            "_id": {
                "legacy_system": "$legacy_system",
                "doc_type": "$doc_type",
                "workflow_status": "$workflow_status"
            },
            "count": {"$sum": 1}
        }},
        {"$sort": {"_id.legacy_system": 1, "_id.doc_type": 1}}
    ]
    
    results = await db.hub_documents.aggregate(pipeline).to_list(500)
    
    # Organize results
    by_system = {}
    by_doc_type = {}
    by_status = {}
    total = 0
    
    for r in results:
        system = r["_id"].get("legacy_system", "UNKNOWN")
        doc_type = r["_id"].get("doc_type", "OTHER")
        status = r["_id"].get("workflow_status", "unknown")
        count = r["count"]
        
        by_system[system] = by_system.get(system, 0) + count
        by_doc_type[doc_type] = by_doc_type.get(doc_type, 0) + count
        by_status[status] = by_status.get(status, 0) + count
        total += count
    
    return {
        "total_migrated": total,
        "by_legacy_system": by_system,
        "by_doc_type": by_doc_type,
        "by_workflow_status": by_status
    }


@router.get("/migration/supported-types")
async def get_supported_migration_types():
    """
    Get information about document types supported by the migration job.
    """
    return {
        "supported_doc_types": WorkflowInitializer.get_supported_doc_types(),
        "source_systems": ["SQUARE9", "ZETADOCS"],
        "zetadocs_mappings": {
            "ZD00015": "AP_INVOICE",
            "ZD00007": "SALES_INVOICE",
            "ZD00002": "PURCHASE_ORDER",
            "ZD00006": "SALES_INVOICE (Order Confirmations)",
            "ZD00009": "SALES_CREDIT_MEMO",
            "ZD00010": "SALES_INVOICE (Blanket Orders)",
        },
        "square9_mappings": {
            "AP_Invoice": "AP_INVOICE",
            "AP Invoice": "AP_INVOICE",
            "Purchase Invoice": "AP_INVOICE",
            "Sales Invoice": "SALES_INVOICE",
            "Sales_Invoice": "SALES_INVOICE",
            "Purchase Order": "PURCHASE_ORDER",
            "PO": "PURCHASE_ORDER",
            "Credit Memo": "SALES_CREDIT_MEMO",
            "Statement": "STATEMENT",
            "Reminder": "REMINDER",
            "Quality": "QUALITY_DOC",
        }
    }
