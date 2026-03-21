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
    docs = await db.hub_documents.find({}, {"_id": 0, "id": 1, "workflow_status": 1, "validation_results": 1, "auto_escalated": 1, "square9_stage": 1}).to_list(10000)

    stage_counts = {}
    for doc in docs:
        stage = doc.get("square9_stage") or determine_square9_stage(doc)
        stage_counts[stage] = stage_counts.get(stage, 0) + 1

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


@router.get("/migration-status")
async def get_square9_migration_status():
    """Assess readiness for Square9 decommission.

    Returns document counts with/without square9_stage, unique stages,
    and a cutover readiness assessment.
    """
    db = get_db()

    total = await db.hub_documents.count_documents({})
    with_stage = await db.hub_documents.count_documents(
        {"square9_stage": {"$exists": True, "$ne": None}}
    )
    without_stage = total - with_stage

    unique_stages = await db.hub_documents.distinct("square9_stage")
    unique_stages = [s for s in unique_stages if s]

    # Check current cutover status
    cfg = await db.hub_config.find_one({"_key": "square9_cutover"}, {"_id": 0})
    already_cut = cfg.get("square9_active") is False if cfg else False

    # Readiness: ready if hub has documents and no active inbound from Square9
    readiness = "ready" if total > 0 else "no_documents"
    if already_cut:
        readiness = "already_decommissioned"

    return {
        "total_documents": total,
        "with_square9_stage": with_stage,
        "without_square9_stage": without_stage,
        "unique_stages": unique_stages,
        "square9_active": not already_cut,
        "cutover_readiness": readiness,
        "cutover_info": cfg,
    }




