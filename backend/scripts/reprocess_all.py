"""Re-process all documents through the 5-stage classification pipeline.

Updates extraction quality, validation results, and pipeline metadata
for every document.  Does NOT change document status or re-trigger
auto-clear/filing — only refreshes classification, extraction, and
validation data.

Usage:
  # Dry run (report what would change, no writes):
  cd /app && python3 backend/scripts/reprocess_all.py --dry-run

  # Full run:
  cd /app && python3 backend/scripts/reprocess_all.py

  # Limit to N documents (useful for testing):
  cd /app && python3 backend/scripts/reprocess_all.py --limit 10

  # Only re-process documents with sparse extraction (< N meaningful fields):
  cd /app && python3 backend/scripts/reprocess_all.py --sparse-only 3

  # Docker:
  docker exec -it gpi-backend python3 backend/scripts/reprocess_all.py
"""

import argparse
import asyncio
import logging
import os
import sys
import time
from collections import Counter
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, os.path.join(os.path.dirname(__file__), ".."))

from motor.motor_asyncio import AsyncIOMotorClient

MONGO_URL = os.environ.get("MONGO_URL", "mongodb://localhost:27017")
DB_NAME = os.environ.get("DB_NAME", "gpi_document_hub")
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s [%(levelname)s] %(message)s",
)
logger = logging.getLogger("reprocess_all")

# Suppress noisy loggers during batch run
logging.getLogger("services.classification_feedback_service").setLevel(logging.WARNING)
logging.getLogger("services.bc_validation_service").setLevel(logging.WARNING)
logging.getLogger("httpx").setLevel(logging.WARNING)


def _meaningful_field_count(ef: dict) -> int:
    """Count non-metadata fields with actual values."""
    if not ef or not isinstance(ef, dict):
        return 0
    return sum(
        1 for k, v in ef.items()
        if v and not k.endswith("_detected_by")
    )


async def reprocess_one(db, doc: dict, dry_run: bool) -> dict:
    """Run the pipeline on a single document. Returns a change summary."""
    doc_id = doc["id"]
    file_name = doc.get("file_name", "?")

    old_type = doc.get("suggested_job_type") or doc.get("doc_type") or "Unknown"
    old_confidence = doc.get("ai_confidence", 0.0)
    old_ef = doc.get("extracted_fields") or {}
    old_meaningful = _meaningful_field_count(old_ef)

    # Check if file exists
    has_file = False
    for key in ("local_file_path", "file_path"):
        fp = doc.get(key)
        if fp and os.path.exists(str(fp)):
            has_file = True
            break
    if not has_file and (UPLOAD_DIR / doc_id).exists():
        has_file = True

    if not has_file:
        return {
            "doc_id": doc_id,
            "file_name": file_name,
            "action": "skipped",
            "reason": "no_file",
            "old_type": old_type,
            "old_fields": old_meaningful,
        }

    if dry_run:
        return {
            "doc_id": doc_id,
            "file_name": file_name,
            "action": "would_process",
            "reason": "dry_run",
            "old_type": old_type,
            "old_fields": old_meaningful,
            "has_file": True,
        }

    # Run the pipeline
    try:
        from services.classification_pipeline import run_pipeline
        pipeline = await run_pipeline(doc_id, doc)

        new_type = pipeline.document_type
        new_confidence = pipeline.classification_confidence
        new_ef = pipeline.extracted_fields
        new_meaningful = pipeline.meaningful_field_count

        # Build the update
        now = datetime.now(timezone.utc).isoformat()
        update = {
            "suggested_job_type": new_type,
            "ai_confidence": new_confidence,
            "extracted_fields": new_ef,
            "validation_results": pipeline.validation_results,
            "automation_readiness": pipeline.readiness_status,
            "automation_readiness_score": pipeline.readiness_score,
            "automation_readiness_reasons": pipeline.readiness_reasons,
            "automation_decision": pipeline.automation_decision,
            "intelligence_processed_at": now,
            "updated_utc": now,
            "pipeline_status": pipeline.final_status,
            "pipeline_failure_stage": pipeline.failure_stage,
            "pipeline_failure_reason": pipeline.failure_reason,
            "classification_method": pipeline.classification_method,
        }

        await db.hub_documents.update_one({"id": doc_id}, {"$set": update})

        # Also store in intelligence collection
        from services.document_intelligence_service import INTELLIGENCE_COLLECTION
        intel_result = {
            "document_id": doc_id,
            "document_type": new_type,
            "classification_confidence": round(new_confidence, 4),
            "extracted_fields": new_ef,
            "validation_results": pipeline.validation_results,
            "automation_decision": pipeline.automation_decision,
            "automation_readiness": pipeline.readiness_status,
            "automation_readiness_score": pipeline.readiness_score,
            "processed_at": now,
            "pipeline_status": pipeline.final_status,
            "pipeline_stages": {
                name: {
                    "status": sr.status.value,
                    "quality_gate": sr.quality_gate_passed,
                    "error": sr.error,
                    "ms": sr.duration_ms,
                }
                for name, sr in pipeline.stages.items()
            },
            "classification_method": pipeline.classification_method,
            "meaningful_field_count": new_meaningful,
        }
        await db[INTELLIGENCE_COLLECTION].update_one(
            {"document_id": doc_id},
            {"$set": intel_result},
            upsert=True,
        )

        # Determine what changed
        type_changed = old_type != new_type
        fields_delta = new_meaningful - old_meaningful

        return {
            "doc_id": doc_id,
            "file_name": file_name,
            "action": "processed",
            "old_type": old_type,
            "new_type": new_type,
            "type_changed": type_changed,
            "old_fields": old_meaningful,
            "new_fields": new_meaningful,
            "fields_delta": fields_delta,
            "pipeline_status": pipeline.final_status,
            "failure_stage": pipeline.failure_stage,
            "confidence": new_confidence,
        }

    except Exception as e:
        logger.error("Failed to process %s (%s): %s", doc_id, file_name, e)
        return {
            "doc_id": doc_id,
            "file_name": file_name,
            "action": "error",
            "reason": str(e),
            "old_type": old_type,
            "old_fields": old_meaningful,
        }


async def run(
    dry_run: bool = False,
    limit: int = 0,
    sparse_only: int = 0,
    delay: float = 0.5,
):
    """Main batch runner."""
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    # Initialize services that need db reference
    try:
        from services.classification_feedback_service import init_classification_feedback
        init_classification_feedback(db)
    except Exception:
        pass

    # Also set db for deps module
    try:
        import deps
        deps._db = db
    except Exception:
        pass

    total = await db.hub_documents.count_documents({})
    print(f"\n{'='*70}")
    print(f"  GPI Document Hub — Batch Re-process Pipeline")
    print(f"  Mode: {'DRY RUN' if dry_run else 'LIVE'}")
    print(f"  Total documents: {total}")
    if limit:
        print(f"  Limit: {limit}")
    if sparse_only:
        print(f"  Sparse only: documents with < {sparse_only} meaningful fields")
    print(f"  LLM delay: {delay}s between documents")
    print(f"{'='*70}\n")

    query = {}
    projection = {
        "_id": 0, "id": 1, "file_name": 1, "suggested_job_type": 1,
        "doc_type": 1, "ai_confidence": 1, "extracted_fields": 1,
        "local_file_path": 1, "file_path": 1, "status": 1,
        "normalized_fields": 1,
    }

    cursor = db.hub_documents.find(query, projection)
    if limit:
        cursor = cursor.limit(limit)

    results = []
    processed = 0
    start_time = time.time()

    async for doc in cursor:
        # Filter sparse-only if requested
        if sparse_only:
            ef = doc.get("extracted_fields") or {}
            meaningful = _meaningful_field_count(ef)
            if meaningful >= sparse_only:
                continue

        processed += 1
        file_name = doc.get("file_name", "?")

        # Progress indicator
        elapsed = time.time() - start_time
        rate = processed / elapsed if elapsed > 0 else 0
        sys.stdout.write(
            f"\r  [{processed}] {file_name[:50]:50s} "
            f"({rate:.1f} docs/s)"
        )
        sys.stdout.flush()

        result = await reprocess_one(db, doc, dry_run)
        results.append(result)

        # Rate limit LLM calls
        if result["action"] == "processed" and delay > 0:
            await asyncio.sleep(delay)

    print(f"\n\n{'='*70}")
    print(f"  RESULTS")
    print(f"{'='*70}\n")

    # Summarize
    actions = Counter(r["action"] for r in results)
    print(f"  Total scanned:  {len(results)}")
    print(f"  Processed:      {actions.get('processed', 0)}")
    print(f"  Skipped (no file): {actions.get('skipped', 0)}")
    print(f"  Errors:         {actions.get('error', 0)}")
    if dry_run:
        print(f"  Would process:  {actions.get('would_process', 0)}")

    # Type changes
    type_changes = [r for r in results if r.get("type_changed")]
    if type_changes:
        print(f"\n  Type changes: {len(type_changes)}")
        change_types = Counter(f"{r['old_type']} -> {r['new_type']}" for r in type_changes)
        for ct, count in change_types.most_common():
            print(f"    {ct}: {count}")

    # Field improvements
    processed_results = [r for r in results if r["action"] == "processed"]
    if processed_results:
        improved = [r for r in processed_results if r.get("fields_delta", 0) > 0]
        degraded = [r for r in processed_results if r.get("fields_delta", 0) < 0]
        unchanged = [r for r in processed_results if r.get("fields_delta", 0) == 0]

        total_delta = sum(r.get("fields_delta", 0) for r in processed_results)
        print(f"\n  Field extraction changes:")
        print(f"    Improved:   {len(improved)} documents (+{sum(r['fields_delta'] for r in improved)} fields)")
        print(f"    Degraded:   {len(degraded)} documents ({sum(r['fields_delta'] for r in degraded)} fields)")
        print(f"    Unchanged:  {len(unchanged)} documents")
        print(f"    Net change: {'+' if total_delta >= 0 else ''}{total_delta} fields")

        # Pipeline status
        statuses = Counter(r.get("pipeline_status") for r in processed_results)
        print(f"\n  Pipeline outcomes:")
        for status, count in statuses.most_common():
            print(f"    {status}: {count}")

        # Show worst failures
        failures = [r for r in processed_results if r.get("pipeline_status") == "failed"]
        if failures:
            print(f"\n  Pipeline failures ({len(failures)}):")
            for r in failures[:10]:
                print(f"    {r['file_name'][:45]:45s} stage={r.get('failure_stage')} fields={r['new_fields']}")

    # Show errors
    errors = [r for r in results if r["action"] == "error"]
    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for r in errors[:10]:
            print(f"    {r['file_name'][:45]:45s} {r.get('reason', '?')[:60]}")

    # Show documents with no file
    no_file = [r for r in results if r["action"] == "skipped" and r.get("reason") == "no_file"]
    if no_file:
        print(f"\n  Documents with no file on disk ({len(no_file)}):")
        for r in no_file[:10]:
            print(f"    {r['file_name'] or '(no name)':45s} {r['old_type']:20s} fields={r['old_fields']}")
        if len(no_file) > 10:
            print(f"    ... and {len(no_file) - 10} more")

    elapsed = time.time() - start_time
    print(f"\n  Completed in {elapsed:.1f}s")
    print(f"{'='*70}\n")

    client.close()

    return {
        "total": len(results),
        "processed": actions.get("processed", 0),
        "skipped": actions.get("skipped", 0),
        "errors": actions.get("error", 0),
        "type_changes": len(type_changes) if not dry_run else 0,
        "field_improvements": len(improved) if processed_results else 0,
    }


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description="Re-process all documents through the classification pipeline")
    parser.add_argument("--dry-run", action="store_true", help="Report what would change without writing")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N documents")
    parser.add_argument("--sparse-only", type=int, default=0, help="Only process documents with fewer than N meaningful fields")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds to wait between LLM calls (default: 0.5)")
    args = parser.parse_args()

    asyncio.run(run(
        dry_run=args.dry_run,
        limit=args.limit,
        sparse_only=args.sparse_only,
        delay=args.delay,
    ))
