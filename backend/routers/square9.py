"""GPI Document Hub - Square9 Router"""

import asyncio
import logging
import os
from datetime import datetime, timezone
from fastapi import APIRouter, HTTPException, Query, Body, Depends
from motor.motor_asyncio import AsyncIOMotorDatabase
from hub_platform.bootstrap import get_platform_database
from typing import Dict
from services.square9_workflow import (
    Square9Stage, DEFAULT_WORKFLOW_CONFIG, get_square9_stage_info,
    determine_square9_stage,
)

logger = logging.getLogger("square9")

router = APIRouter(prefix="/square9", tags=["Square9"])

# Backend runs from /app inside the container (same as `docker compose
# exec backend ...`, which is where this script has been run and
# verified all night). Set explicitly rather than relying on the
# running process's inherited cwd.
READINESS_APP_DIR = "/app"
READINESS_SCRIPT = "ops/prod_verify_square9_cutover_readiness.sh"
READINESS_SNAPSHOT_SCRIPT = "scripts/record_square9_readiness_snapshot.py"
READINESS_RUN_STATUS_KEY = "readiness_run_status"

# A run stuck at "running" past this age is treated as crashed/
# abandoned (e.g. a backend restart mid-run) rather than genuinely
# still in progress, so a new run isn't blocked forever by a status
# document nothing will ever update again.
READINESS_STALE_MINUTES = 15
# Hard ceiling on the subprocess itself - the check has taken 45-90s
# all night; this is a generous multiple, not a tuned expectation.
READINESS_SUBPROCESS_TIMEOUT_SECONDS = 600


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
async def get_square9_stage_counts(
    database: AsyncIOMotorDatabase = Depends(get_platform_database),
):
    """Get document counts by Square9 stage."""
    docs = await database.hub_documents.find({}, {"_id": 0, "id": 1, "workflow_status": 1, "validation_results": 1, "auto_escalated": 1, "square9_stage": 1}).to_list(10000)

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
async def get_square9_migration_status(
    database: AsyncIOMotorDatabase = Depends(get_platform_database),
):
    """Assess readiness for Square9 decommission.

    Returns document counts with/without square9_stage, unique stages,
    and a cutover readiness assessment.
    """

    total = await database.hub_documents.count_documents({})
    with_stage = await database.hub_documents.count_documents(
        {"square9_stage": {"$exists": True, "$ne": None}}
    )
    without_stage = total - with_stage

    unique_stages = await database.hub_documents.distinct("square9_stage")
    unique_stages = [s for s in unique_stages if s]

    # Check current cutover status
    cfg = await database.hub_config.find_one({"key": "square9_cutover"}, {"_id": 0})
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
async def archive_stage_data(body: Dict = Body(...), database: AsyncIOMotorDatabase = Depends(get_platform_database)):
    """Archive Square9 stage data and mark cutover. IRREVERSIBLE without restore."""
    if not body.get("confirm"):
        raise HTTPException(status_code=400, detail="confirm: true required — this operation is destructive")


    # Check if already decommissioned
    cfg = await database.hub_config.find_one({"key": "square9_cutover"}, {"_id": 0})
    if cfg and cfg.get("square9_active") is False:
        return {"status": "already_decommissioned", "archived_at": cfg.get("archived_at")}

    # Count docs with square9_stage that haven't been archived yet
    to_archive = await database.hub_documents.count_documents(
        {"square9_stage": {"$exists": True, "$ne": None}}
    )

    if to_archive == 0:
        return {"status": "nothing_to_archive", "archived": 0}

    # Bulk archive: copy square9_stage → square9_archived_stage, unset square9_stage
    result = await database.hub_documents.update_many(
        {"square9_stage": {"$exists": True, "$ne": None}},
        [
            {"$set": {"square9_archived_stage": "$square9_stage"}},
            {"$unset": "square9_stage"},
        ],
    )
    archived_count = result.modified_count

    # Mark cutover in hub_config
    now = datetime.now(timezone.utc).isoformat()
    await database.hub_config.update_one(
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
async def restore_stage_data(body: Dict = Body(...), database: AsyncIOMotorDatabase = Depends(get_platform_database)):
    """Restore Square9 stage data from archive. Safety escape hatch."""
    if not body.get("confirm"):
        raise HTTPException(status_code=400, detail="confirm: true required")


    # Count docs with archived stage
    to_restore = await database.hub_documents.count_documents(
        {"square9_archived_stage": {"$exists": True, "$ne": None}}
    )

    if to_restore == 0:
        return {"status": "nothing_to_restore", "restored": 0}

    # Restore: copy square9_archived_stage → square9_stage, unset archive
    result = await database.hub_documents.update_many(
        {"square9_archived_stage": {"$exists": True, "$ne": None}},
        [
            {"$set": {"square9_stage": "$square9_archived_stage"}},
            {"$unset": "square9_archived_stage"},
        ],
    )
    restored_count = result.modified_count

    # Re-activate Square9 in hub_config
    now = datetime.now(timezone.utc).isoformat()
    await database.hub_config.update_one(
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


# =============================================================================
# Cutover Readiness Dashboard
# =============================================================================
# Backed by square9_readiness_history, populated by
# backend/scripts/record_square9_readiness_snapshot.py after each run of
# ops/prod_verify_square9_cutover_readiness.sh. Read-only reporting on top
# of that history - doesn't run the (expensive) readiness check itself.

@router.get("/readiness/latest")
async def get_latest_readiness_snapshot(
    database: AsyncIOMotorDatabase = Depends(get_platform_database),
):
    """Most recent Square9 cutover readiness snapshot."""
    latest = await database.square9_readiness_history.find_one(
        {}, {"_id": 0}, sort=[("recorded_utc", -1)]
    )
    if not latest:
        raise HTTPException(
            status_code=404,
            detail="No readiness snapshots recorded yet. Run "
                   "backend/scripts/record_square9_readiness_snapshot.py "
                   "after a readiness check.",
        )
    return latest


@router.get("/readiness/history")
async def get_readiness_history(limit: int = Query(200, ge=1, le=1000), database: AsyncIOMotorDatabase = Depends(get_platform_database)):
    """
    Chronological history of readiness snapshots, oldest first, for
    trend charting. Returns a lightweight projection (not the full
    bucket_C detail) to keep the payload small for a trend line.
    """
    cursor = database.square9_readiness_history.find(
        {},
        {
            "_id": 0,
            "recorded_utc": 1,
            "match_rate_pct": 1,
            "decision": 1,
            "square_count": 1,
            "matched_count": 1,
            "projected_match_rate_pct": 1,
        },
    ).sort("recorded_utc", 1).limit(limit)
    history = await cursor.to_list(length=limit)
    return {"count": len(history), "history": history}


async def _get_run_status_doc(db) -> Dict:
    doc = await db.hub_config.find_one(
        {"_key": READINESS_RUN_STATUS_KEY}, {"_id": 0}
    )
    return doc or {"_key": READINESS_RUN_STATUS_KEY, "status": "idle"}


async def _set_run_status(db, **fields) -> None:
    await db.hub_config.update_one(
        {"_key": READINESS_RUN_STATUS_KEY},
        {"$set": fields},
        upsert=True,
    )


def _run_is_stale(status_doc: Dict) -> bool:
    if status_doc.get("status") != "running":
        return False
    started_at = status_doc.get("started_at")
    if not started_at:
        return True
    try:
        started_dt = datetime.fromisoformat(started_at.replace("Z", "+00:00"))
    except (ValueError, AttributeError):
        return True
    age_minutes = (datetime.now(timezone.utc) - started_dt).total_seconds() / 60
    return age_minutes > READINESS_STALE_MINUTES


async def _execute_readiness_check(db, triggered_by: str) -> None:
    """Runs the readiness check + snapshot-recording as a subprocess,
    entirely independent of any HTTP request/response cycle (the
    endpoint that schedules this returns immediately). Every exit path
    - success, script failure, timeout, unexpected exception - updates
    the shared status document so a stuck 'running' state is never left
    behind for the frontend to poll forever."""
    started_at = datetime.now(timezone.utc).isoformat()
    try:
        proc = await asyncio.create_subprocess_exec(
            "bash", READINESS_SCRIPT,
            cwd=READINESS_APP_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        try:
            stdout_bytes, _ = await asyncio.wait_for(
                proc.communicate(), timeout=READINESS_SUBPROCESS_TIMEOUT_SECONDS,
            )
        except asyncio.TimeoutError:
            proc.kill()
            await proc.wait()
            await _set_run_status(
                db, status="failed", finished_at=datetime.now(timezone.utc).isoformat(),
                error=f"Readiness check exceeded {READINESS_SUBPROCESS_TIMEOUT_SECONDS}s "
                      f"timeout and was killed.",
            )
            return

        output_tail = stdout_bytes.decode("utf-8", errors="replace")[-4000:]
        logger.info(
            "[readiness-check] subprocess finished rc=%s (triggered_by=%s)",
            proc.returncode, triggered_by,
        )

        # rc up to 2 is an expected workflow signal in this script
        # family (e.g. NO-GO), not a failure - mirrors the `step()`
        # helper's own convention inside the shell scripts themselves.
        if proc.returncode is not None and proc.returncode >= 3:
            await _set_run_status(
                db, status="failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error=f"Script exited rc={proc.returncode}. Last output:\n{output_tail}",
            )
            return

        # Persist this run into square9_readiness_history - the same
        # collection /readiness/latest and /readiness/history already
        # read from, so the dashboard picks it up automatically.
        snapshot_proc = await asyncio.create_subprocess_exec(
            "python3", READINESS_SNAPSHOT_SCRIPT,
            cwd=READINESS_APP_DIR,
            stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.STDOUT,
        )
        snapshot_out, _ = await asyncio.wait_for(
            snapshot_proc.communicate(), timeout=60,
        )
        if snapshot_proc.returncode != 0:
            await _set_run_status(
                db, status="failed",
                finished_at=datetime.now(timezone.utc).isoformat(),
                error=(
                    "Readiness check completed but snapshot recording failed "
                    f"(rc={snapshot_proc.returncode}): "
                    f"{snapshot_out.decode('utf-8', errors='replace')[-2000:]}"
                ),
            )
            return

        latest = await db.square9_readiness_history.find_one(
            {}, {"_id": 0, "match_rate_pct": 1, "decision": 1, "recorded_utc": 1},
            sort=[("recorded_utc", -1)],
        )
        await _set_run_status(
            db, status="completed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            error=None,
            last_result=latest or {},
        )
    except Exception as e:
        logger.exception("[readiness-check] unexpected failure")
        await _set_run_status(
            db, status="failed",
            finished_at=datetime.now(timezone.utc).isoformat(),
            error=f"Unexpected error: {e}",
        )
    finally:
        # started_at is set by the caller before scheduling this task;
        # re-affirm it here only if somehow missing, so run-status
        # always has a start time to compute duration/staleness from.
        current = await _get_run_status_doc(db)
        if not current.get("started_at"):
            await _set_run_status(db, started_at=started_at)


@router.post("/readiness/run")
async def trigger_readiness_check(
    database: AsyncIOMotorDatabase = Depends(get_platform_database),
):
    """Kicks off the Square9 cutover readiness check as a background
    subprocess and returns immediately - the check itself takes
    45-90s (observed range over many runs), too long for a normal
    request/response cycle. Poll GET /readiness/run-status for
    progress; GET /readiness/latest picks up the result automatically
    once complete, since this feeds the same square9_readiness_history
    collection that endpoint already reads."""
    current = await _get_run_status_doc(database)

    if current.get("status") == "running" and not _run_is_stale(current):
        raise HTTPException(
            status_code=409,
            detail={
                "message": "A readiness check is already running.",
                "started_at": current.get("started_at"),
            },
        )

    started_at = datetime.now(timezone.utc).isoformat()
    await _set_run_status(
        database, status="running", started_at=started_at, finished_at=None, error=None,
    )

    # Fire-and-forget: this task keeps running after this request
    # returns. Deliberately not FastAPI's BackgroundTasks - the
    # subprocess genuinely outlives the request/response cycle by
    # roughly a minute, and this makes that explicit.
    asyncio.create_task(_execute_readiness_check(database, triggered_by="manual_ui"))

    return {"status": "running", "started_at": started_at}


@router.get("/readiness/run-status")
async def get_readiness_run_status(
    database: AsyncIOMotorDatabase = Depends(get_platform_database),
):
    """Poll this after POST /readiness/run. Returns status: idle |
    running | completed | failed, plus started_at/finished_at and,
    once completed, the resulting snapshot summary."""
    status_doc = await _get_run_status_doc(database)
    if _run_is_stale(status_doc):
        status_doc = dict(status_doc)
        status_doc["status"] = "failed"
        status_doc["error"] = (
            status_doc.get("error")
            or "Run appears abandoned (no update in "
               f"{READINESS_STALE_MINUTES}+ minutes) - likely a backend "
               "restart mid-run. Safe to start a new run."
        )
    return status_doc





