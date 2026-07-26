#!/usr/bin/env python3
"""
Bulk re-run the canonical document pipeline across hub_documents.

Recommended usage from backend/ on the prod VM:

    python scripts/reprocess_all_pipeline_docs.py --concurrency 4
    python scripts/reprocess_all_pipeline_docs.py --limit 100 --concurrency 2
    python scripts/reprocess_all_pipeline_docs.py --resume-job-id <job_id>
    python scripts/reprocess_all_pipeline_docs.py --dry-run
    python scripts/reprocess_all_pipeline_docs.py --stop-after layout
    python scripts/reprocess_all_pipeline_docs.py --skip-stages learning_capture

What this script does:
- Uses the current backend code directly, not the HTTP API
- Reads doc IDs from db.hub_documents
- Runs services.pipeline.document_pipeline.run_pipeline(doc_id, ...)
- Persists a bulk job summary to pipeline_bulk_jobs
- Persists per-document outcomes to pipeline_bulk_job_items
- Supports resume on interrupted runs
- Prints rolling progress and a final summary

Assumptions:
- Run from backend/ so imports like `import server` work
- Your normal prod environment variables are already available
- server.startup() initializes deps.set_db() and DB access correctly
"""

from __future__ import annotations

import argparse
import asyncio
import json
import logging
import os
import signal
import socket
import sys
import time
import traceback
import uuid
from collections import Counter
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional, Set

# ----------------------------------------------------------------------
# Logging
# ----------------------------------------------------------------------

LOG_LEVEL = os.environ.get("PIPELINE_BULK_LOG_LEVEL", "INFO").upper()
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL, logging.INFO),
    format="%(asctime)s | %(levelname)-7s | %(message)s",
)
logger = logging.getLogger("pipeline_bulk_runner")

UTC = timezone.utc


def utcnow_iso() -> str:
    return datetime.now(UTC).isoformat()


def chunks(seq: List[str], size: int) -> List[List[str]]:
    return [seq[i:i + size] for i in range(0, len(seq), size)]


def safe_int(value: Any, default: int) -> int:
    try:
        return int(value)
    except Exception:
        return default


# ----------------------------------------------------------------------
# CLI args
# ----------------------------------------------------------------------

def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Bulk re-run the canonical document pipeline across hub_documents."
    )
    parser.add_argument(
        "--job-name",
        default="prod_bulk_pipeline_reprocess",
        help="Friendly name recorded in pipeline_bulk_jobs.",
    )
    parser.add_argument(
        "--resume-job-id",
        default="",
        help="Resume an existing bulk job by job_id.",
    )
    parser.add_argument(
        "--limit",
        type=int,
        default=0,
        help="Optional cap on how many documents to process. 0 = no limit.",
    )
    parser.add_argument(
        "--concurrency",
        type=int,
        default=4,
        help="Number of documents to process concurrently.",
    )
    parser.add_argument(
        "--batch-size",
        type=int,
        default=250,
        help="Cursor fetch / loop batch size for reading document IDs.",
    )
    parser.add_argument(
        "--progress-every",
        type=int,
        default=25,
        help="Print progress every N completed docs.",
    )
    parser.add_argument(
        "--max-errors",
        type=int,
        default=0,
        help="Abort if this many worker-level exceptions occur. 0 = unlimited.",
    )
    parser.add_argument(
        "--stop-after",
        default="",
        help="Optional pipeline stage name to stop after.",
    )
    parser.add_argument(
        "--skip-stages",
        default="",
        help="Comma-separated pipeline stages to skip.",
    )
    parser.add_argument(
        "--query-json",
        default="{}",
        help=(
            "Mongo query JSON for selecting documents from hub_documents. "
            "Default is {}. Example: '{\"status\":{\"$ne\":\"Deleted\"}}'"
        ),
    )
    parser.add_argument(
        "--sort-field",
        default="created_utc",
        help="Field used to sort docs before processing.",
    )
    parser.add_argument(
        "--sort-direction",
        type=int,
        default=1,
        choices=[1, -1],
        help="1 = ascending, -1 = descending.",
    )
    parser.add_argument(
        "--dry-run",
        action="store_true",
        help="Show how many docs would be processed, then exit.",
    )
    parser.add_argument(
        "--fail-fast",
        action="store_true",
        help="Stop after the first worker-level exception.",
    )
    parser.add_argument(
        "--include-already-processed",
        action="store_true",
        help=(
            "When resuming a job, process documents even if a pipeline_bulk_job_items "
            "record already exists for that doc/job."
        ),
    )
    return parser


# ----------------------------------------------------------------------
# Runtime state
# ----------------------------------------------------------------------

@dataclass
class RuntimeState:
    stop_requested: bool = False


STATE = RuntimeState()


def _handle_signal(signum: int, _frame: Any) -> None:
    logger.warning("Received signal %s. Graceful stop requested.", signum)
    STATE.stop_requested = True


signal.signal(signal.SIGINT, _handle_signal)
signal.signal(signal.SIGTERM, _handle_signal)


# ----------------------------------------------------------------------
# DB / app bootstrap
# ----------------------------------------------------------------------

async def startup_app() -> None:
    import server  # noqa
    await server.startup()


async def shutdown_app() -> None:
    import server  # noqa
    await server.shutdown_db_client()


def get_db():
    from deps import get_db
    return get_db()


# ----------------------------------------------------------------------
# Job persistence helpers
# ----------------------------------------------------------------------

async def ensure_bulk_indexes(db) -> None:
    await db.pipeline_bulk_jobs.create_index("job_id", unique=True)
    await db.pipeline_bulk_jobs.create_index([("started_at", -1)])

    await db.pipeline_bulk_job_items.create_index(
        [("job_id", 1), ("doc_id", 1)],
        unique=True,
    )
    await db.pipeline_bulk_job_items.create_index([("job_id", 1), ("finished_at", -1)])
    await db.pipeline_bulk_job_items.create_index([("doc_id", 1), ("finished_at", -1)])


def summarize_pipeline_result(result_dict: Dict[str, Any]) -> Dict[str, Any]:
    stages = result_dict.get("stages", []) or []
    stage_statuses = Counter(s.get("status", "unknown") for s in stages)

    errored_stages = [s.get("stage") for s in stages if s.get("status") == "error"]
    skipped_stages = [s.get("stage") for s in stages if s.get("status") == "skipped"]

    return {
        "pipeline_status": result_dict.get("status"),
        "pipeline_version": result_dict.get("pipeline_version"),
        "started_at": result_dict.get("started_at"),
        "finished_at": result_dict.get("finished_at"),
        "total_duration_ms": result_dict.get("total_duration_ms"),
        "stages_run": result_dict.get("stages_run"),
        "stages_skipped": result_dict.get("stages_skipped"),
        "stages_errored": result_dict.get("stages_errored"),
        "stage_status_counts": dict(stage_statuses),
        "errored_stages": errored_stages,
        "skipped_stages": skipped_stages,
    }


async def create_new_job(
    db,
    *,
    job_id: str,
    job_name: str,
    args: argparse.Namespace,
    planned_count: int,
) -> None:
    doc = {
        "job_id": job_id,
        "job_name": job_name,
        "status": "running",
        "started_at": utcnow_iso(),
        "finished_at": None,
        "host": socket.gethostname(),
        "pid": os.getpid(),
        "args": {
            "limit": args.limit,
            "concurrency": args.concurrency,
            "batch_size": args.batch_size,
            "progress_every": args.progress_every,
            "max_errors": args.max_errors,
            "stop_after": args.stop_after or None,
            "skip_stages": parse_skip_stages(args.skip_stages),
            "query_json": args.query_json,
            "sort_field": args.sort_field,
            "sort_direction": args.sort_direction,
            "fail_fast": args.fail_fast,
        },
        "planned_count": planned_count,
        "completed_count": 0,
        "ok_count": 0,
        "partial_count": 0,
        "error_count": 0,
        "worker_exception_count": 0,
        "last_progress_at": utcnow_iso(),
        "notes": [],
    }
    await db.pipeline_bulk_jobs.insert_one(doc)


async def append_job_note(db, job_id: str, note: str) -> None:
    await db.pipeline_bulk_jobs.update_one(
        {"job_id": job_id},
        {
            "$push": {"notes": f"{utcnow_iso()} {note}"},
            "$set": {"last_progress_at": utcnow_iso()},
        },
    )


async def mark_job_finished(
    db,
    *,
    job_id: str,
    status: str,
    summary: Dict[str, Any],
) -> None:
    await db.pipeline_bulk_jobs.update_one(
        {"job_id": job_id},
        {
            "$set": {
                "status": status,
                "finished_at": utcnow_iso(),
                "last_progress_at": utcnow_iso(),
                "summary": summary,
            }
        },
    )


async def refresh_job_counts(db, job_id: str) -> Dict[str, int]:
    cursor = db.pipeline_bulk_job_items.aggregate(
        [
            {"$match": {"job_id": job_id}},
            {
                "$group": {
                    "_id": "$pipeline_status",
                    "count": {"$sum": 1},
                }
            },
        ]
    )
    grouped = await cursor.to_list(length=20)
    counts = {"ok": 0, "partial": 0, "error": 0}
    total = 0

    for row in grouped:
        status = row.get("_id") or "unknown"
        count = row.get("count", 0)
        if status in counts:
            counts[status] = count
        total += count

    worker_exception_count = await db.pipeline_bulk_job_items.count_documents(
        {"job_id": job_id, "worker_exception": True}
    )

    update = {
        "completed_count": total,
        "ok_count": counts["ok"],
        "partial_count": counts["partial"],
        "error_count": counts["error"],
        "worker_exception_count": worker_exception_count,
        "last_progress_at": utcnow_iso(),
    }

    await db.pipeline_bulk_jobs.update_one({"job_id": job_id}, {"$set": update})
    return update


# ----------------------------------------------------------------------
# Selection helpers
# ----------------------------------------------------------------------

def parse_skip_stages(skip_stages_raw: str) -> List[str]:
    if not skip_stages_raw.strip():
        return []
    return [s.strip() for s in skip_stages_raw.split(",") if s.strip()]


def parse_query_json(query_json: str) -> Dict[str, Any]:
    try:
        parsed = json.loads(query_json)
    except json.JSONDecodeError as exc:
        raise SystemExit(f"Invalid --query-json: {exc}") from exc
    if not isinstance(parsed, dict):
        raise SystemExit("--query-json must decode to a JSON object.")
    return parsed


async def get_existing_doc_ids_for_job(db, job_id: str) -> Set[str]:
    doc_ids: Set[str] = set()
    cursor = db.pipeline_bulk_job_items.find(
        {"job_id": job_id},
        {"_id": 0, "doc_id": 1},
    )
    async for row in cursor:
        doc_id = row.get("doc_id")
        if doc_id:
            doc_ids.add(doc_id)
    return doc_ids


async def get_target_doc_ids(
    db,
    *,
    base_query: Dict[str, Any],
    sort_field: str,
    sort_direction: int,
    limit: int,
    exclude_doc_ids: Optional[Set[str]] = None,
) -> List[str]:
    query = dict(base_query)

    if exclude_doc_ids:
        query["id"] = {"$nin": list(exclude_doc_ids)}

    projection = {"_id": 0, "id": 1}
    cursor = db.hub_documents.find(query, projection).sort(sort_field, sort_direction)

    doc_ids: List[str] = []
    async for row in cursor:
        doc_id = row.get("id")
        if doc_id:
            doc_ids.append(doc_id)
            if limit > 0 and len(doc_ids) >= limit:
                break

    return doc_ids


# ----------------------------------------------------------------------
# Worker logic
# ----------------------------------------------------------------------

async def persist_job_item(
    db,
    *,
    job_id: str,
    doc_id: str,
    result_dict: Optional[Dict[str, Any]],
    worker_exception: Optional[str] = None,
) -> None:
    now = utcnow_iso()

    if result_dict is not None:
        summary = summarize_pipeline_result(result_dict)
        item = {
            "job_id": job_id,
            "doc_id": doc_id,
            "worker_exception": False,
            "stored_at": now,
            **summary,
        }
    else:
        item = {
            "job_id": job_id,
            "doc_id": doc_id,
            "pipeline_status": "error",
            "worker_exception": True,
            "worker_exception_message": (worker_exception or "")[:2000],
            "stored_at": now,
            "started_at": None,
            "finished_at": None,
            "total_duration_ms": None,
            "stages_run": None,
            "stages_skipped": None,
            "stages_errored": None,
            "stage_status_counts": {},
            "errored_stages": [],
            "skipped_stages": [],
        }

    await db.pipeline_bulk_job_items.update_one(
        {"job_id": job_id, "doc_id": doc_id},
        {"$set": item},
        upsert=True,
    )


async def process_one_doc(
    *,
    db,
    job_id: str,
    doc_id: str,
    stop_after: Optional[str],
    skip_stages: List[str],
) -> Dict[str, Any]:
    from services.pipeline.document_pipeline import run_pipeline

    result = await run_pipeline(
        doc_id,
        stop_after=stop_after or None,
        skip_stages=skip_stages or None,
    )
    result_dict = result.to_dict()
    await persist_job_item(db, job_id=job_id, doc_id=doc_id, result_dict=result_dict)
    return result_dict


async def worker_loop(
    *,
    name: str,
    db,
    job_id: str,
    queue: asyncio.Queue,
    counters: Counter,
    counters_lock: asyncio.Lock,
    args: argparse.Namespace,
) -> None:
    while not STATE.stop_requested:
        try:
            doc_id = await asyncio.wait_for(queue.get(), timeout=1.0)
        except asyncio.TimeoutError:
            if queue.empty():
                return
            continue

        try:
            result_dict = await process_one_doc(
                db=db,
                job_id=job_id,
                doc_id=doc_id,
                stop_after=args.stop_after or None,
                skip_stages=parse_skip_stages(args.skip_stages),
            )

            pipeline_status = result_dict.get("status", "unknown")
            async with counters_lock:
                counters["completed"] += 1
                counters[f"status_{pipeline_status}"] += 1

                if args.progress_every > 0 and counters["completed"] % args.progress_every == 0:
                    logger.info(
                        "Progress | completed=%s ok=%s partial=%s error=%s remaining=%s",
                        counters["completed"],
                        counters["status_ok"],
                        counters["status_partial"],
                        counters["status_error"],
                        queue.qsize(),
                    )

        except Exception as exc:
            tb = traceback.format_exc()
            logger.error("Worker %s failed on doc %s: %s", name, doc_id, exc)
            logger.debug(tb)

            await persist_job_item(
                db,
                job_id=job_id,
                doc_id=doc_id,
                result_dict=None,
                worker_exception=str(exc),
            )

            async with counters_lock:
                counters["completed"] += 1
                counters["status_error"] += 1
                counters["worker_exceptions"] += 1

            if args.fail_fast:
                STATE.stop_requested = True

            if args.max_errors > 0 and counters["worker_exceptions"] >= args.max_errors:
                logger.error(
                    "Max worker exceptions reached (%s). Stopping.",
                    args.max_errors,
                )
                STATE.stop_requested = True

        finally:
            queue.task_done()


# ----------------------------------------------------------------------
# Main
# ----------------------------------------------------------------------

async def async_main(args: argparse.Namespace) -> int:
    await startup_app()
    db = get_db()
    await ensure_bulk_indexes(db)

    base_query = parse_query_json(args.query_json)

    if "id" not in base_query:
        # Make sure we only target records that have the canonical doc ID field.
        base_query["id"] = {"$exists": True, "$ne": None}

    if args.resume_job_id:
        job_id = args.resume_job_id
        existing_job = await db.pipeline_bulk_jobs.find_one({"job_id": job_id}, {"_id": 0})
        if not existing_job:
            logger.error("Resume job_id not found: %s", job_id)
            return 2

        already_done: Set[str] = set()
        if not args.include_already_processed:
            already_done = await get_existing_doc_ids_for_job(db, job_id)

        target_doc_ids = await get_target_doc_ids(
            db,
            base_query=base_query,
            sort_field=args.sort_field,
            sort_direction=args.sort_direction,
            limit=args.limit,
            exclude_doc_ids=already_done,
        )

        logger.info(
            "Resuming job %s | already_done=%s | remaining=%s",
            job_id,
            len(already_done),
            len(target_doc_ids),
        )
        await append_job_note(
            db,
            job_id,
            f"Resumed job. Remaining docs queued: {len(target_doc_ids)}",
        )
    else:
        job_id = uuid.uuid4().hex
        target_doc_ids = await get_target_doc_ids(
            db,
            base_query=base_query,
            sort_field=args.sort_field,
            sort_direction=args.sort_direction,
            limit=args.limit,
            exclude_doc_ids=None,
        )

        await create_new_job(
            db,
            job_id=job_id,
            job_name=args.job_name,
            args=args,
            planned_count=len(target_doc_ids),
        )

    logger.info("Bulk pipeline job_id=%s", job_id)
    logger.info("Target document count=%s", len(target_doc_ids))
    logger.info("Concurrency=%s", args.concurrency)
    logger.info("stop_after=%s", args.stop_after or "<none>")
    logger.info("skip_stages=%s", parse_skip_stages(args.skip_stages))
    logger.info("query=%s", json.dumps(base_query, default=str))

    if args.dry_run:
        print("")
        print("DRY RUN")
        print(f"job_id: {job_id}")
        print(f"target_count: {len(target_doc_ids)}")
        print(f"query: {json.dumps(base_query, default=str)}")
        print(f"concurrency: {args.concurrency}")
        print(f"stop_after: {args.stop_after or ''}")
        print(f"skip_stages: {parse_skip_stages(args.skip_stages)}")
        print("")
        await append_job_note(db, job_id, "Dry run requested. No documents processed.")
        await mark_job_finished(
            db,
            job_id=job_id,
            status="dry_run",
            summary={"target_count": len(target_doc_ids)},
        )
        await shutdown_app()
        return 0

    if not target_doc_ids:
        logger.warning("No matching documents found.")
        await mark_job_finished(
            db,
            job_id=job_id,
            status="completed",
            summary={"target_count": 0, "completed_count": 0},
        )
        await shutdown_app()
        return 0

    queue: asyncio.Queue = asyncio.Queue()
    for doc_id in target_doc_ids:
        await queue.put(doc_id)

    counters = Counter()
    counters_lock = asyncio.Lock()

    started_monotonic = time.monotonic()

    workers = [
        asyncio.create_task(
            worker_loop(
                name=f"worker-{i+1}",
                db=db,
                job_id=job_id,
                queue=queue,
                counters=counters,
                counters_lock=counters_lock,
                args=args,
            )
        )
        for i in range(max(1, args.concurrency))
    ]

    await queue.join()
    STATE.stop_requested = True

    for task in workers:
        task.cancel()

    await asyncio.gather(*workers, return_exceptions=True)

    elapsed_sec = round(time.monotonic() - started_monotonic, 2)
    db_counts = await refresh_job_counts(db, job_id)

    status = "completed"
    if counters["worker_exceptions"] > 0:
        status = "completed_with_errors"

    if STATE.stop_requested and counters["completed"] < len(target_doc_ids):
        status = "stopped"

    summary = {
        "job_id": job_id,
        "target_count": len(target_doc_ids),
        "completed_count": db_counts["completed_count"],
        "ok_count": db_counts["ok_count"],
        "partial_count": db_counts["partial_count"],
        "error_count": db_counts["error_count"],
        "worker_exception_count": db_counts["worker_exception_count"],
        "elapsed_seconds": elapsed_sec,
    }

    await mark_job_finished(db, job_id=job_id, status=status, summary=summary)

    print("")
    print("BULK PIPELINE RUN COMPLETE")
    print(f"job_id: {job_id}")
    print(f"status: {status}")
    print(f"target_count: {len(target_doc_ids)}")
    print(f"completed_count: {db_counts['completed_count']}")
    print(f"ok_count: {db_counts['ok_count']}")
    print(f"partial_count: {db_counts['partial_count']}")
    print(f"error_count: {db_counts['error_count']}")
    print(f"worker_exception_count: {db_counts['worker_exception_count']}")
    print(f"elapsed_seconds: {elapsed_sec}")
    print("")

    await shutdown_app()
    return 0


def main() -> int:
    parser = build_arg_parser()
    args = parser.parse_args()

    try:
        return asyncio.run(async_main(args))
    except KeyboardInterrupt:
        logger.warning("Interrupted by user.")
        return 130
    except Exception as exc:
        logger.error("Fatal error: %s", exc)
        logger.debug(traceback.format_exc())
        return 1


if __name__ == "__main__":
    sys.exit(main())
