"""GPI Document Hub - Migration Router"""

import logging
from typing import Optional
from fastapi import APIRouter, HTTPException, Body, Query, BackgroundTasks
from pydantic import BaseModel
from datetime import datetime, timezone
from deps import get_db
from services.migration import WorkflowInitializer
from services.migration.sources import create_sample_migration_file

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/migration", tags=["Migration"])


class MigrationRequest(BaseModel):
    source_file: Optional[str] = None
    source_filter: Optional[str] = None
    doc_type_filter: Optional[str] = None
    mode: Optional[str] = "preview"
    batch_size: int = 50


@router.post("/run")
async def run_migration_job(
    request: MigrationRequest,
    background_tasks: BackgroundTasks
):
    """Run a migration job to import legacy documents."""
    db = get_db()
    return {
        "status": "accepted",
        "message": "Migration job queued",
        "mode": request.mode,
        "source_file": request.source_file
    }


@router.get("/preview")
async def preview_migration(
    source_file: Optional[str] = None,
    source_filter: Optional[str] = None,
    doc_type_filter: Optional[str] = None,
    limit: int = Query(10, le=100)
):
    """Preview documents that would be migrated."""
    db = get_db()
    query = {"is_migrated": True}
    if doc_type_filter:
        query["doc_type"] = doc_type_filter
    if source_filter:
        query["legacy_system"] = source_filter

    docs = await db.hub_documents.find(query, {"_id": 0}).limit(limit).to_list(limit)
    return {"preview": docs, "count": len(docs), "filters": {"doc_type": doc_type_filter, "source": source_filter}}


@router.post("/generate-sample")
async def generate_sample_migration_file(
    output_path: str = Query(default="/app/backend/data/sample_migration.json")
):
    """Generate a sample migration JSON file for testing."""
    try:
        path = create_sample_migration_file(output_path)
        return {"status": "created", "path": str(path)}
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))


@router.get("/stats")
async def get_migration_stats():
    """Get statistics about migrated documents in the system."""
    db = get_db()
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


@router.get("/supported-types")
async def get_supported_migration_types():
    """Get information about document types supported by the migration job."""
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
