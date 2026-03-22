"""GPI Document Hub - Square9 Router"""

import logging
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Body
from typing import Dict
from deps import get_db
from services.square9_workflow import (
    Square9Stage, DEFAULT_WORKFLOW_CONFIG, get_square9_stage_info,
    determine_square9_stage,
)

logger = logging.getLogger("square9")

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
    cfg = await db.hub_config.find_one({"key": "square9_cutover"}, {"_id": 0})
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


@router.post("/archive-stage-data")
async def archive_stage_data(body: Dict = Body(...)):
    """Archive Square9 stage data and mark cutover. IRREVERSIBLE without restore."""
    if not body.get("confirm"):
        raise HTTPException(status_code=400, detail="confirm: true required — this operation is destructive")

    db = get_db()

    # Check if already decommissioned
    cfg = await db.hub_config.find_one({"key": "square9_cutover"}, {"_id": 0})
    if cfg and cfg.get("square9_active") is False:
        return {"status": "already_decommissioned", "archived_at": cfg.get("archived_at")}

    # Count docs with square9_stage that haven't been archived yet
    to_archive = await db.hub_documents.count_documents(
        {"square9_stage": {"$exists": True, "$ne": None}}
    )

    if to_archive == 0:
        return {"status": "nothing_to_archive", "archived": 0}

    # Bulk archive: copy square9_stage → square9_archived_stage, unset square9_stage
    result = await db.hub_documents.update_many(
        {"square9_stage": {"$exists": True, "$ne": None}},
        [
            {"$set": {"square9_archived_stage": "$square9_stage"}},
            {"$unset": "square9_stage"},
        ],
    )
    archived_count = result.modified_count

    # Mark cutover in hub_config
    now = datetime.now(timezone.utc).isoformat()
    await db.hub_config.update_one(
        {"key": "square9_cutover"},
        {"$set": {
            "key": "square9_cutover",
            "square9_active": False,
            "archived_at": now,
            "archived_count": archived_count,
        }},
        upsert=True,
    )

    logger.info("Square9 archive complete: %d documents archived at %s", archived_count, now)

    return {
        "status": "decommissioned",
        "archived": archived_count,
        "archived_at": now,
    }


@router.post("/restore-stage-data")
async def restore_stage_data(body: Dict = Body(...)):
    """Restore Square9 stage data from archive. Safety escape hatch."""
    if not body.get("confirm"):
        raise HTTPException(status_code=400, detail="confirm: true required")

    db = get_db()

    # Count docs with archived stage
    to_restore = await db.hub_documents.count_documents(
        {"square9_archived_stage": {"$exists": True, "$ne": None}}
    )

    if to_restore == 0:
        return {"status": "nothing_to_restore", "restored": 0}

    # Restore: copy square9_archived_stage → square9_stage, unset archive
    result = await db.hub_documents.update_many(
        {"square9_archived_stage": {"$exists": True, "$ne": None}},
        [
            {"$set": {"square9_stage": "$square9_archived_stage"}},
            {"$unset": "square9_archived_stage"},
        ],
    )
    restored_count = result.modified_count

    # Re-activate Square9 in hub_config
    now = datetime.now(timezone.utc).isoformat()
    await db.hub_config.update_one(
        {"key": "square9_cutover"},
        {"$set": {
            "key": "square9_cutover",
            "square9_active": True,
            "restored_at": now,
            "restored_count": restored_count,
        }},
        upsert=True,
    )

    logger.info("Square9 restore complete: %d documents restored at %s", restored_count, now)

    return {
        "status": "restored",
        "restored": restored_count,
        "restored_at": now,
    }




