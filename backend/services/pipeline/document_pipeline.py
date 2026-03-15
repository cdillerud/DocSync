"""
GPI Document Hub - Canonical Document Processing Pipeline

Orchestrates the multi-stage document intelligence pipeline by sequencing
existing services.  Each stage is independently callable and produces a
typed result dict so callers can inspect partial progress.

Pipeline stages (in order):
  1. classification    - AI-driven doc type + field extraction
  2. entity_resolution - match extracted names/IDs to internal DB entities
  3. transaction_match  - link document to existing transaction records
  4. bundle_detection   - group related documents into packets
  5. lifecycle_check    - analyse document set completeness
  6. policy_decision    - evaluate automation rules and decide action
  7. learning_capture   - update automation metrics from outcome

Usage:
    from services.pipeline.document_pipeline import DocumentPipeline, run_pipeline

    result = await run_pipeline(doc_id)          # run all stages
    result = await run_pipeline(doc_id, stop_after="entity_resolution")  # partial
"""

import logging
import time
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("pipeline")

# ---------------------------------------------------------------------------
# Stage result container
# ---------------------------------------------------------------------------

@dataclass
class StageResult:
    """Outcome of a single pipeline stage."""
    stage: str
    status: str            # "ok", "skipped", "error"
    duration_ms: float = 0
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None


@dataclass
class PipelineResult:
    """Aggregate outcome of a full (or partial) pipeline run."""
    document_id: str
    started_at: str = ""
    finished_at: str = ""
    status: str = "pending"  # "ok", "partial", "error"
    stages: List[StageResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "document_id": self.document_id,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "status": self.status,
            "stages": [
                {
                    "stage": s.stage,
                    "status": s.status,
                    "duration_ms": round(s.duration_ms, 1),
                    "error": s.error,
                    "output_keys": list(s.output.keys()),
                }
                for s in self.stages
            ],
        }


# ---------------------------------------------------------------------------
# Stage definitions  (each wraps an existing service call)
# ---------------------------------------------------------------------------

STAGE_ORDER = [
    "classification",
    "entity_resolution",
    "transaction_match",
    "bundle_detection",
    "lifecycle_check",
    "policy_decision",
    "learning_capture",
]


async def _run_classification(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 1: Classify document and extract fields."""
    from services.document_intelligence_service import process_document

    result = await process_document(doc_id)
    ctx["intel"] = result
    summary = {
        "document_type": result.get("document_type"),
        "confidence": result.get("confidence"),
        "automation_readiness": result.get("automation_readiness", {}).get("status"),
    }
    return StageResult(stage="classification", status="ok", output=summary)


async def _run_entity_resolution(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 2: Resolve extracted entities against internal DB."""
    from services.entity_resolution_service import resolve_entities

    result = await resolve_entities(doc_id)
    ctx["resolutions"] = result.get("resolutions", [])
    summary = {
        "total_entities": result.get("summary", {}).get("total", 0),
        "resolved_count": result.get("summary", {}).get("resolved", 0),
        "confidence_avg": result.get("summary", {}).get("confidence_avg"),
    }
    return StageResult(stage="entity_resolution", status="ok", output=summary)


async def _run_transaction_match(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 3: Find and score candidate transaction matches."""
    from services.transaction_matching_service import match_transactions

    result = await match_transactions(doc_id)
    ctx["tx_match"] = result
    summary = {
        "overall_status": result.get("overall_status"),
        "candidates_count": result.get("candidates_count", 0),
        "best_confidence": result.get("best_match", {}).get("confidence"),
    }
    return StageResult(stage="transaction_match", status="ok", output=summary)


async def _run_bundle_detection(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 4: Detect document bundles containing this document."""
    from services.document_bundle_service import detect_bundles

    result = await detect_bundles(document_ids=[doc_id])
    ctx["bundles"] = result
    summary = {
        "bundles_created": result.get("bundles_created", 0),
        "bundles_updated": result.get("bundles_updated", 0),
        "documents_grouped": result.get("documents_grouped", 0),
    }
    return StageResult(stage="bundle_detection", status="ok", output=summary)


async def _run_lifecycle_check(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 5: Validate lifecycle completeness for the related entity.

    Requires entity resolution to have found a high-confidence match so we
    know which entity to check.  Skipped when no entity is resolved.
    """
    from services.document_lifecycle_service import validate_lifecycle
    from deps import get_db

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return StageResult(stage="lifecycle_check", status="skipped",
                           error="document not found")

    # Determine entity to validate from document context
    entity_type = None
    entity_id = None
    resolutions = ctx.get("resolutions", [])
    for res in resolutions:
        if res.get("status") == "resolved" and res.get("confidence", 0) >= 0.7:
            entity_type = res.get("entity_kind")
            entity_id = res.get("resolved_id") or res.get("canonical_id")
            break

    if not entity_type or not entity_id:
        return StageResult(stage="lifecycle_check", status="skipped",
                           output={"reason": "no high-confidence entity resolved"})

    result = await validate_lifecycle(entity_type, entity_id)
    ctx["lifecycle"] = result
    summary = {
        "entity_type": entity_type,
        "entity_id": entity_id,
        "completeness": result.get("completeness_pct"),
        "issues_count": result.get("issues_count", 0),
    }
    return StageResult(stage="lifecycle_check", status="ok", output=summary)


async def _run_policy_decision(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 6: Evaluate automation decision policies."""
    from services.decision_policy_service import evaluate_decision

    result = await evaluate_decision(doc_id)
    ctx["decision"] = result
    summary = {
        "action": result.get("action"),
        "policy_name": result.get("matched_policy", {}).get("name"),
        "confidence": result.get("confidence"),
    }
    return StageResult(stage="policy_decision", status="ok", output=summary)


async def _run_learning_capture(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 7: Update aggregated automation metrics."""
    from services.learning_loop_service import update_automation_metrics

    result = await update_automation_metrics()
    ctx["learning"] = result
    summary = {
        "metrics_updated": True,
    }
    return StageResult(stage="learning_capture", status="ok", output=summary)


# Map stage names to runner functions
_STAGE_RUNNERS = {
    "classification": _run_classification,
    "entity_resolution": _run_entity_resolution,
    "transaction_match": _run_transaction_match,
    "bundle_detection": _run_bundle_detection,
    "lifecycle_check": _run_lifecycle_check,
    "policy_decision": _run_policy_decision,
    "learning_capture": _run_learning_capture,
}


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_pipeline(
    doc_id: str,
    *,
    stop_after: Optional[str] = None,
    skip_stages: Optional[List[str]] = None,
) -> PipelineResult:
    """Run the canonical document processing pipeline.

    Args:
        doc_id:      The document to process.
        stop_after:  Stop after this stage completes (inclusive).
        skip_stages: List of stage names to skip.

    Returns:
        PipelineResult with per-stage outcomes.
    """
    pipeline = PipelineResult(
        document_id=doc_id,
        started_at=datetime.now(timezone.utc).isoformat(),
    )
    ctx: Dict[str, Any] = {}
    skip = set(skip_stages or [])

    logger.info("[Pipeline] Starting for doc=%s  stop_after=%s  skip=%s",
                doc_id, stop_after, skip)

    for stage_name in STAGE_ORDER:
        if stage_name in skip:
            pipeline.stages.append(
                StageResult(stage=stage_name, status="skipped",
                            output={"reason": "explicitly skipped"})
            )
            if stop_after and stage_name == stop_after:
                break
            continue

        runner = _STAGE_RUNNERS[stage_name]
        t0 = time.monotonic()
        try:
            result = await runner(doc_id, ctx)
            result.duration_ms = (time.monotonic() - t0) * 1000
            pipeline.stages.append(result)
            logger.info("[Pipeline] doc=%s  stage=%s  status=%s  %.0fms",
                        doc_id, stage_name, result.status, result.duration_ms)
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            err_result = StageResult(
                stage=stage_name, status="error",
                duration_ms=elapsed, error=str(exc),
            )
            pipeline.stages.append(err_result)
            logger.error("[Pipeline] doc=%s  stage=%s  ERROR: %s  %.0fms",
                         doc_id, stage_name, exc, elapsed)
            # Continue to next stage; non-fatal

        if stop_after and stage_name == stop_after:
            break

    # Determine overall status
    statuses = [s.status for s in pipeline.stages]
    if all(s in ("ok", "skipped") for s in statuses):
        pipeline.status = "ok"
    elif any(s == "error" for s in statuses):
        pipeline.status = "partial"
    else:
        pipeline.status = "ok"

    pipeline.finished_at = datetime.now(timezone.utc).isoformat()
    logger.info("[Pipeline] Finished doc=%s  status=%s  stages=%d",
                doc_id, pipeline.status, len(pipeline.stages))
    return pipeline
