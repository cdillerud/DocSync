"""GPI Document Hub - Square9 Router"""

from fastapi import APIRouter, Query
from deps import get_db
from services.square9_workflow import (
    Square9Stage, DEFAULT_WORKFLOW_CONFIG, get_square9_stage_info,
    determine_square9_stage,
)

router = APIRouter(prefix="/square9", tags=["Square9"])


@router.get("/config")
async def get_square9_config():
    """Get Square9 workflow configuration."""
    return {
        "config": DEFAULT_WORKFLOW_CONFIG,
        "stages": [
            {"value": stage.value, **get_square9_stage_info(stage.value)}
            for stage in Square9Stage
        ],
    }



@router.get("/stage-counts")
async def get_square9_stage_counts():
    db = get_db()
    """Get document counts by Square9 stage."""
    # Get all documents and compute their stages
    docs = await db.hub_documents.find({}, {"_id": 0, "id": 1, "workflow_status": 1, "validation_results": 1, "auto_escalated": 1, "square9_stage": 1}).to_list(10000)
    
    stage_counts = {}
    for doc in docs:
        # Use stored stage or compute it
        stage = doc.get("square9_stage") or determine_square9_stage(doc)
        stage_counts[stage] = stage_counts.get(stage, 0) + 1
    
    # Enhance with stage info
    result = []
    for stage in Square9Stage:
        count = stage_counts.get(stage.value, 0)
        info = get_square9_stage_info(stage.value)
        result.append({
            "stage": stage.value,
            "count": count,
            **info,
        })
    
    return {
        "stages": result,
        "total_documents": len(docs),
    }




