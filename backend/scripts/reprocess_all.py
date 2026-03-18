"""Re-process / re-validate all documents.

Two modes:
  --revalidate  (default, fast, no files needed)
      Re-computes BC validation, extraction quality metrics, and readiness
      using EXISTING extracted_fields.  No LLM calls, no file downloads.
      Fixes stale metrics across all documents instantly.

  --full
      Downloads files from SharePoint, re-runs the 5-stage pipeline
      (PARSE → CLASSIFY → EXTRACT → VALIDATE → ROUTE) with LLM calls.
      Use selectively with --limit or --sparse-only.

Usage (inside Docker container):
  # Re-validate all docs (fast, no LLM):
  python3 scripts/reprocess_all.py --revalidate

  # Re-validate dry run:
  python3 scripts/reprocess_all.py --revalidate --dry-run

  # Full pipeline on sparse docs only:
  python3 scripts/reprocess_all.py --full --sparse-only 3 --limit 50

  # From host:
  docker exec -it gpi-backend python3 scripts/reprocess_all.py --revalidate
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

# Suppress noisy loggers
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


# =========================================================================
# REVALIDATE mode — fast, no files, no LLM
# =========================================================================

async def revalidate_one(db, doc: dict, dry_run: bool) -> dict:
    """Re-compute quality metrics and readiness from existing data.

    Does NOT call BC API.  Only recomputes:
      - extraction_quality (correct field lists per doc type)
      - readiness score
      - strips _detected_by metadata from extracted_fields
    """
    doc_id = doc["id"]
    file_name = doc.get("file_name", "?")
    doc_type = doc.get("suggested_job_type") or doc.get("doc_type") or "Unknown"
    confidence = doc.get("ai_confidence") or 0.0
    extracted = doc.get("extracted_fields") or {}
    old_validation = doc.get("validation_results") or {}
    old_eq = old_validation.get("extraction_quality", {})
    old_completeness = old_eq.get("completeness_score", 0)
    meaningful = _meaningful_field_count(extracted)

    if dry_run:
        return {
            "doc_id": doc_id,
            "file_name": file_name,
            "action": "would_revalidate",
            "doc_type": doc_type,
            "meaningful_fields": meaningful,
            "old_completeness": old_completeness,
        }

    try:
        from models.document_types import DEFAULT_JOB_TYPES
        from services.bc_validation_service import _compute_extraction_quality
        from services.document_intel_helpers import normalize_extracted_fields

        # Resolve job config
        job_config = DEFAULT_JOB_TYPES.get(doc_type)
        if not job_config:
            for k, v in DEFAULT_JOB_TYPES.items():
                if k.upper().replace("_", "") == doc_type.upper().replace("_", ""):
                    job_config = v
                    break
            if not job_config:
                job_config = DEFAULT_JOB_TYPES.get("AP_Invoice", {})

        # Recompute extraction quality with correct field lists (NO BC calls)
        normalized = normalize_extracted_fields(extracted)
        new_eq = _compute_extraction_quality(normalized, extracted, job_config)
        new_completeness = new_eq.get("completeness_score", 0)

        # Patch extraction_quality into existing validation_results
        # AND fix stale check data from previous runs
        new_validation = dict(old_validation)
        new_validation["extraction_quality"] = new_eq

        # Fix stale checks: downgrade sales_order_match and customer_match
        # to required=False (they were briefly set to required=True)
        existing_checks = list(new_validation.get("checks", []))
        checks_fixed = False
        for check in existing_checks:
            if check.get("check_name") in ("sales_order_match", "customer_match"):
                if check.get("required") is True:
                    check["required"] = False
                    checks_fixed = True
        new_validation["checks"] = existing_checks

        # Recalculate all_passed from the corrected checks
        if checks_fixed or new_validation.get("all_passed") is False:
            required_checks = [c for c in existing_checks if c.get("required") is True]
            if required_checks:
                new_validation["all_passed"] = all(c.get("passed", False) for c in required_checks)
            else:
                # No required checks failed — only soft/optional failures
                new_validation["all_passed"] = True

        # Check extraction quality gate (documents with 0 meaningful fields)
        meaningful_fields = {
            k: v for k, v in extracted.items()
            if v and not k.endswith("_detected_by")
        }
        if not meaningful_fields and old_validation.get("all_passed"):
            new_validation["all_passed"] = False
            existing_checks = new_validation.get("checks", [])
            if not any(c.get("check_name") == "extraction_quality_gate" for c in existing_checks):
                existing_checks.append({
                    "check_name": "extraction_quality_gate",
                    "passed": False,
                    "details": "No meaningful data extracted from document",
                    "required": True,
                })
                new_validation["checks"] = existing_checks

        # Compute readiness
        from services.document_intelligence_service import _derive_automation_readiness
        readiness = _derive_automation_readiness(
            classification_confidence=confidence,
            extracted_fields=extracted,
            doc_type=doc_type,
            validation_results=new_validation,
            automation_decision=doc.get("automation_decision", "manual"),
        )

        # Strip _detected_by from extracted_fields
        cleaned_ef = {
            k: v for k, v in extracted.items()
            if not k.endswith("_detected_by")
        }
        ef_changed = len(cleaned_ef) != len(extracted)

        # Build update
        now = datetime.now(timezone.utc).isoformat()
        update = {
            "validation_results": new_validation,
            "automation_readiness": readiness["status"],
            "automation_readiness_score": readiness["score"],
            "automation_readiness_reasons": readiness["reasons"],
            "updated_utc": now,
        }
        if ef_changed:
            update["extracted_fields"] = cleaned_ef

        await db.hub_documents.update_one({"id": doc_id}, {"$set": update})

        completeness_changed = abs(old_completeness - new_completeness) > 0.01
        old_passed = old_validation.get("all_passed")
        new_passed = new_validation.get("all_passed")
        validation_changed = old_passed != new_passed

        return {
            "doc_id": doc_id,
            "file_name": file_name,
            "action": "revalidated",
            "doc_type": doc_type,
            "meaningful_fields": meaningful,
            "old_passed": old_passed,
            "new_passed": new_passed,
            "validation_changed": old_passed != new_passed,
            "old_completeness": old_completeness,
            "new_completeness": new_completeness,
            "completeness_changed": completeness_changed,
            "metadata_cleaned": ef_changed,
            "readiness": readiness["status"],
        }

    except Exception as e:
        logger.error("Revalidate failed for %s (%s): %s", doc_id, file_name, e)
        return {
            "doc_id": doc_id,
            "file_name": file_name,
            "action": "error",
            "reason": str(e),
            "doc_type": doc_type,
        }


# =========================================================================
# FULL mode — needs files, runs LLM
# =========================================================================

async def reprocess_one_full(db, doc: dict, dry_run: bool) -> dict:
    """Run the full 5-stage pipeline on a single document."""
    doc_id = doc["id"]
    file_name = doc.get("file_name", "?")
    old_type = doc.get("suggested_job_type") or doc.get("doc_type") or "Unknown"
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
            "old_type": old_type,
            "old_fields": old_meaningful,
        }

    try:
        from services.classification_pipeline import run_pipeline
        pipeline = await run_pipeline(doc_id, doc)

        now = datetime.now(timezone.utc).isoformat()
        update = {
            "suggested_job_type": pipeline.document_type,
            "ai_confidence": pipeline.classification_confidence,
            "extracted_fields": pipeline.extracted_fields,
            "validation_results": pipeline.validation_results,
            "automation_readiness": pipeline.readiness_status,
            "automation_readiness_score": pipeline.readiness_score,
            "automation_readiness_reasons": pipeline.readiness_reasons,
            "automation_decision": pipeline.automation_decision,
            "intelligence_processed_at": now,
            "updated_utc": now,
            "pipeline_status": pipeline.final_status,
            "classification_method": pipeline.classification_method,
        }
        await db.hub_documents.update_one({"id": doc_id}, {"$set": update})

        new_meaningful = pipeline.meaningful_field_count
        return {
            "doc_id": doc_id,
            "file_name": file_name,
            "action": "processed",
            "old_type": old_type,
            "new_type": pipeline.document_type,
            "type_changed": old_type != pipeline.document_type,
            "old_fields": old_meaningful,
            "new_fields": new_meaningful,
            "fields_delta": new_meaningful - old_meaningful,
            "pipeline_status": pipeline.final_status,
        }

    except Exception as e:
        logger.error("Full reprocess failed for %s: %s", doc_id, e)
        return {
            "doc_id": doc_id,
            "file_name": file_name,
            "action": "error",
            "reason": str(e),
        }


# =========================================================================
# Main runner
# =========================================================================

async def run(
    mode: str = "revalidate",
    dry_run: bool = False,
    limit: int = 0,
    sparse_only: int = 0,
    delay: float = 0.5,
):
    client = AsyncIOMotorClient(MONGO_URL)
    db = client[DB_NAME]

    # Init services
    try:
        from services.classification_feedback_service import init_classification_feedback
        init_classification_feedback(db)
    except Exception:
        pass
    try:
        import deps
        deps._db = db
    except Exception:
        pass

    total = await db.hub_documents.count_documents({})
    print(f"\n{'='*70}")
    print(f"  GPI Document Hub — Batch {'Re-validate' if mode == 'revalidate' else 'Re-process'}")
    print(f"  Mode: {mode.upper()} {'(DRY RUN)' if dry_run else '(LIVE)'}")
    print(f"  Total documents: {total}")
    if limit:
        print(f"  Limit: {limit}")
    if sparse_only:
        print(f"  Sparse only: < {sparse_only} meaningful fields")
    if mode == "full":
        print(f"  LLM delay: {delay}s")
    print(f"{'='*70}\n")

    projection = {
        "_id": 0, "id": 1, "file_name": 1, "suggested_job_type": 1,
        "doc_type": 1, "ai_confidence": 1, "extracted_fields": 1,
        "local_file_path": 1, "file_path": 1, "status": 1,
        "normalized_fields": 1, "validation_results": 1,
        "automation_decision": 1,
    }

    cursor = db.hub_documents.find({}, projection)
    if limit:
        cursor = cursor.limit(limit)

    results = []
    count = 0
    start_time = time.time()

    async for doc in cursor:
        if sparse_only:
            ef = doc.get("extracted_fields") or {}
            if _meaningful_field_count(ef) >= sparse_only:
                continue

        count += 1
        fn = doc.get("file_name", "?")
        elapsed = time.time() - start_time
        rate = count / elapsed if elapsed > 0 else 0
        sys.stdout.write(f"\r  [{count}] {fn[:50]:50s} ({rate:.1f}/s)")
        sys.stdout.flush()

        if mode == "revalidate":
            result = await revalidate_one(db, doc, dry_run)
        else:
            result = await reprocess_one_full(db, doc, dry_run)
            if result["action"] == "processed" and delay > 0:
                await asyncio.sleep(delay)

        results.append(result)

    # ---- Report ----
    print(f"\n\n{'='*70}")
    print(f"  RESULTS")
    print(f"{'='*70}\n")

    actions = Counter(r["action"] for r in results)
    print(f"  Total scanned:    {len(results)}")

    if mode == "revalidate":
        print(f"  Revalidated:      {actions.get('revalidated', 0)}")
        print(f"  Errors:           {actions.get('error', 0)}")
        if dry_run:
            print(f"  Would revalidate: {actions.get('would_revalidate', 0)}")

        revalidated = [r for r in results if r["action"] == "revalidated"]
        if revalidated:
            val_changed = [r for r in revalidated if r.get("validation_changed")]
            comp_changed = [r for r in revalidated if r.get("completeness_changed")]
            metadata_cleaned = [r for r in revalidated if r.get("metadata_cleaned")]

            print(f"\n  Changes:")
            print(f"    Validation pass/fail changed: {len(val_changed)}")
            print(f"    Completeness score changed:   {len(comp_changed)}")
            print(f"    _detected_by metadata cleaned: {len(metadata_cleaned)}")

            if val_changed:
                print(f"\n  Validation changes:")
                # Group by old→new
                changes = Counter(
                    f"{'PASS' if r['old_passed'] else 'FAIL'} -> {'PASS' if r['new_passed'] else 'FAIL'}"
                    for r in val_changed
                )
                for change, cnt in changes.most_common():
                    print(f"    {change}: {cnt}")

                print(f"\n  Documents that changed to FAIL:")
                newly_failed = [r for r in val_changed if not r.get("new_passed")]
                for r in newly_failed[:20]:
                    print(f"    {r['file_name'][:45]:45s} {r['doc_type']:20s} fields={r['meaningful_fields']}")
                if len(newly_failed) > 20:
                    print(f"    ... and {len(newly_failed) - 20} more")

            # Readiness distribution
            readiness = Counter(r.get("readiness", "?") for r in revalidated)
            print(f"\n  Readiness distribution:")
            for status, cnt in readiness.most_common():
                print(f"    {status}: {cnt}")

    else:
        print(f"  Processed:        {actions.get('processed', 0)}")
        print(f"  Skipped (no file): {actions.get('skipped', 0)}")
        print(f"  Errors:           {actions.get('error', 0)}")

        processed = [r for r in results if r["action"] == "processed"]
        if processed:
            improved = [r for r in processed if r.get("fields_delta", 0) > 0]
            degraded = [r for r in processed if r.get("fields_delta", 0) < 0]
            print(f"\n  Field changes: +{len(improved)} improved, {len(degraded)} degraded")

            type_changes = [r for r in processed if r.get("type_changed")]
            if type_changes:
                print(f"\n  Type changes: {len(type_changes)}")
                for ct, cnt in Counter(
                    f"{r['old_type']} -> {r['new_type']}" for r in type_changes
                ).most_common():
                    print(f"    {ct}: {cnt}")

    errors = [r for r in results if r["action"] == "error"]
    if errors:
        print(f"\n  Errors ({len(errors)}):")
        for r in errors[:10]:
            print(f"    {r.get('file_name', '?')[:45]:45s} {r.get('reason', '?')[:60]}")

    elapsed = time.time() - start_time
    print(f"\n  Completed in {elapsed:.1f}s")
    print(f"{'='*70}\n")

    client.close()
    return {"total": len(results), "actions": dict(actions)}


if __name__ == "__main__":
    parser = argparse.ArgumentParser(
        description="Re-process or re-validate all documents"
    )
    group = parser.add_mutually_exclusive_group()
    group.add_argument(
        "--revalidate", action="store_true", default=True,
        help="Re-compute validation + quality metrics from existing data (fast, no LLM)"
    )
    group.add_argument(
        "--full", action="store_true",
        help="Full pipeline re-run (needs files on disk, uses LLM)"
    )
    parser.add_argument("--dry-run", action="store_true", help="Report only, no writes")
    parser.add_argument("--limit", type=int, default=0, help="Process at most N documents")
    parser.add_argument("--sparse-only", type=int, default=0, help="Only docs with < N meaningful fields")
    parser.add_argument("--delay", type=float, default=0.5, help="Seconds between LLM calls (full mode)")
    args = parser.parse_args()

    mode = "full" if args.full else "revalidate"
    asyncio.run(run(
        mode=mode,
        dry_run=args.dry_run,
        limit=args.limit,
        sparse_only=args.sparse_only,
        delay=args.delay,
    ))
