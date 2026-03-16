"""
GPI Document Hub - Canonical Document Processing Pipeline

Orchestrates the multi-stage document intelligence pipeline by sequencing
existing services.  Each stage is independently callable and produces a
typed result dict so callers can inspect partial progress.

Pipeline stages (v2, 10 stages):
  1. classification    - AI-driven doc type + field extraction
  2. extraction        - surface extracted-field summary
  3. layout            - layout fingerprinting / structural signals
  4. entity_resolution - match extracted names/IDs to internal DB entities
  5. transaction_match - link document to existing transaction records
  6. bundle_detection  - group related documents into packets
  7. lifecycle_check   - analyse document set completeness
  8. policy_decision   - evaluate automation rules and decide action
  9. document_routing  - autonomous routing gate (auto_process / review / blocked)
 10. learning_capture  - update automation metrics from outcome

Usage:
    from services.pipeline.document_pipeline import run_pipeline

    result = await run_pipeline(doc_id)
    result = await run_pipeline(doc_id, stop_after="entity_resolution")
    result = await run_pipeline(doc_id, skip_stages=["bundle_detection"])
"""

import logging
import time
import uuid
from dataclasses import dataclass, field
from typing import Any, Dict, List, Optional

from services.automation_helpers import utcnow

logger = logging.getLogger("pipeline")

PIPELINE_VERSION = "v2"

# ---------------------------------------------------------------------------
# Output safety — cap serialised output to prevent oversized trace payloads
# ---------------------------------------------------------------------------

_MAX_OUTPUT_KEYS = 25
_MAX_STRING_LEN = 500
_MAX_LIST_ITEMS = 25


def _sanitize_output(raw: Dict[str, Any]) -> Dict[str, Any]:
    """Return a bounded copy of a stage output dict.

    Rules (applied one level deep):
    - At most ``_MAX_OUTPUT_KEYS`` keys.
    - String values truncated to ``_MAX_STRING_LEN`` chars.
    - List values capped to ``_MAX_LIST_ITEMS`` entries.
    """
    out: Dict[str, Any] = {}
    for i, (k, v) in enumerate(raw.items()):
        if i >= _MAX_OUTPUT_KEYS:
            out["_truncated_keys"] = len(raw) - _MAX_OUTPUT_KEYS
            break
        if isinstance(v, str) and len(v) > _MAX_STRING_LEN:
            out[k] = v[:_MAX_STRING_LEN] + "…"
        elif isinstance(v, list) and len(v) > _MAX_LIST_ITEMS:
            out[k] = v[:_MAX_LIST_ITEMS]
            out[f"_{k}_truncated"] = len(v) - _MAX_LIST_ITEMS
        else:
            out[k] = v
    return out


# ---------------------------------------------------------------------------
# Stage result container
# ---------------------------------------------------------------------------

# Status semantics (canonical):
#   "ok"      — stage executed successfully and produced output
#   "skipped" — stage did not execute: either explicitly skipped by caller,
#               or a dependency-based precondition was not met (no work attempted)
#   "error"   — stage attempted work and failed (exception or domain-level failure)

@dataclass
class StageResult:
    """Outcome of a single pipeline stage."""
    stage: str
    status: str                          # "ok", "skipped", "error"
    started_at: str = ""
    finished_at: str = ""
    duration_ms: float = 0
    output: Dict[str, Any] = field(default_factory=dict)
    error: Optional[str] = None

    def to_dict(self) -> Dict[str, Any]:
        d: Dict[str, Any] = {
            "stage": self.stage,
            "status": self.status,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "duration_ms": round(self.duration_ms, 1),
            "output": _sanitize_output(self.output),
        }
        if self.error is not None:
            d["error"] = self.error[:_MAX_STRING_LEN] if len(self.error) > _MAX_STRING_LEN else self.error
        return d


@dataclass
class PipelineResult:
    """Aggregate outcome of a full (or partial) pipeline run."""
    run_id: str = ""
    document_id: str = ""
    pipeline_version: str = PIPELINE_VERSION
    started_at: str = ""
    finished_at: str = ""
    total_duration_ms: float = 0
    status: str = "pending"              # "ok", "partial", "error"
    stages_run: int = 0
    stages_skipped: int = 0
    stages_errored: int = 0
    stages: List[StageResult] = field(default_factory=list)

    def to_dict(self) -> Dict[str, Any]:
        return {
            "run_id": self.run_id,
            "document_id": self.document_id,
            "pipeline_version": self.pipeline_version,
            "started_at": self.started_at,
            "finished_at": self.finished_at,
            "total_duration_ms": round(self.total_duration_ms, 1),
            "status": self.status,
            "stages_run": self.stages_run,
            "stages_skipped": self.stages_skipped,
            "stages_errored": self.stages_errored,
            "stages": [s.to_dict() for s in self.stages],
        }


# ---------------------------------------------------------------------------
# Stage definitions  (each wraps an existing service call)
# ---------------------------------------------------------------------------

STAGE_ORDER = [
    "classification",
    "extraction",
    "layout",
    "entity_resolution",
    "transaction_match",
    "bundle_detection",
    "lifecycle_check",
    "policy_decision",
    "document_routing",
    "learning_capture",
]

# Backward compat: the original 7-stage list
STAGE_ORDER_V1 = [
    "classification",
    "entity_resolution",
    "transaction_match",
    "bundle_detection",
    "lifecycle_check",
    "policy_decision",
    "learning_capture",
]


async def _run_classification(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 1: Classify document type and extract fields."""
    from services.document_intelligence_service import process_document

    result = await process_document(doc_id)
    ctx["intel"] = result
    summary = {
        "document_type": result.get("document_type"),
        "confidence": result.get("confidence"),
        "automation_readiness": result.get("automation_readiness", {}).get("status"),
    }
    return StageResult(stage="classification", status="ok", output=summary)


async def _run_extraction(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 2: Expose extracted-field summary from classification."""
    intel = ctx.get("intel", {})
    extracted = intel.get("extracted_fields", {})

    if not extracted:
        return StageResult(
            stage="extraction", status="skipped",
            output={"reason": "no extracted fields from classification"},
        )

    field_names = [k for k in extracted.keys() if extracted[k] is not None]
    summary = {
        "fields_extracted": len(field_names),
        "field_names": field_names[:15],
        "has_line_items": bool(extracted.get("line_items")),
    }
    ctx["extracted_fields"] = extracted
    return StageResult(stage="extraction", status="ok", output=summary)


async def _run_layout(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 3: Layout fingerprinting — structural signal generation."""
    from deps import get_db

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        # Attempted work (DB lookup) and failed → "error"
        return StageResult(stage="layout", status="error",
                           error="document not found in hub_documents")

    layout = doc.get("layout_fingerprint")
    if layout:
        summary = {
            "family_id": layout.get("family_id"),
            "page_count": layout.get("page_count"),
            "layout_type": layout.get("layout_type"),
        }
        ctx["layout"] = layout
        return StageResult(stage="layout", status="ok", output=summary)

    try:
        from services.layout_fingerprint_service import get_layout_fingerprint_service
        svc = get_layout_fingerprint_service(db)
        fp = await svc.fingerprint_document(doc_id)
        ctx["layout"] = fp
        summary = {
            "family_id": fp.get("family_id") if fp else None,
            "newly_fingerprinted": True,
        }
        return StageResult(stage="layout", status="ok", output=summary)
    except Exception as exc:
        # Attempted fingerprinting and it failed → "error"
        return StageResult(stage="layout", status="error",
                           error=f"fingerprinting failed: {exc}")


async def _run_entity_resolution(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 4: Resolve extracted entities against internal DB."""
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
    """Stage 5: Find and score candidate transaction matches."""
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
    """Stage 6: Detect document bundles containing this document."""
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
    """Stage 7: Validate lifecycle completeness for the related entity."""
    from services.document_lifecycle_service import validate_lifecycle
    from deps import get_db

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        # Attempted DB lookup and failed → "error"
        return StageResult(stage="lifecycle_check", status="error",
                           error="document not found in hub_documents")

    entity_type = None
    entity_id = None
    resolutions = ctx.get("resolutions", [])
    for res in resolutions:
        if res.get("status") == "resolved" and res.get("confidence", 0) >= 0.7:
            entity_type = res.get("entity_kind")
            entity_id = res.get("resolved_id") or res.get("canonical_id")
            break

    if not entity_type or not entity_id:
        # Dependency-based non-execution → "skipped"
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
    """Stage 8: Evaluate automation decision policies."""
    from services.decision_policy_service import evaluate_decision

    result = await evaluate_decision(doc_id)
    ctx["decision"] = result
    summary = {
        "action": result.get("action"),
        "policy_name": result.get("matched_policy", {}).get("name"),
        "confidence": result.get("confidence"),
    }
    return StageResult(stage="policy_decision", status="ok", output=summary)


async def _run_document_routing(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 9: Autonomous document routing (Auto-Clear Gate)."""
    from services.document_routing_service import route_document

    result = await route_document(doc_id)
    ctx["routing"] = result
    summary = {
        "routing_status": result.get("routing_status"),
        "routing_score": result.get("routing_score"),
        "reasons_count": len(result.get("routing_reasons", [])),
    }
    return StageResult(stage="document_routing", status="ok", output=summary)


async def _run_learning_capture(doc_id: str, ctx: Dict) -> StageResult:
    """Stage 10: Update aggregated automation metrics."""
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
    "extraction": _run_extraction,
    "layout": _run_layout,
    "entity_resolution": _run_entity_resolution,
    "transaction_match": _run_transaction_match,
    "bundle_detection": _run_bundle_detection,
    "lifecycle_check": _run_lifecycle_check,
    "policy_decision": _run_policy_decision,
    "document_routing": _run_document_routing,
    "learning_capture": _run_learning_capture,
}


# ---------------------------------------------------------------------------
# Trace persistence
# ---------------------------------------------------------------------------

PIPELINE_RUNS_COLLECTION = "pipeline_runs"


async def _persist_trace(result: PipelineResult) -> None:
    """Store a pipeline run trace for later inspection."""
    try:
        from deps import get_db
        db = get_db()
        record = result.to_dict()
        record["_persisted_at"] = utcnow()
        await db[PIPELINE_RUNS_COLLECTION].insert_one(record)
    except Exception as exc:
        logger.warning("[Pipeline] Trace persistence failed: %s", exc)


async def get_pipeline_runs(doc_id: str, limit: int = 20) -> List[Dict[str, Any]]:
    """Retrieve historical pipeline runs for a document."""
    from deps import get_db
    db = get_db()
    cursor = db[PIPELINE_RUNS_COLLECTION].find(
        {"document_id": doc_id},
        {"_id": 0},
    ).sort("started_at", -1).limit(limit)
    return await cursor.to_list(length=limit)


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def run_pipeline(
    doc_id: str,
    *,
    stop_after: Optional[str] = None,
    skip_stages: Optional[List[str]] = None,
    persist: bool = True,
) -> PipelineResult:
    """Run the canonical document processing pipeline.

    Args:
        doc_id:      The document to process.
        stop_after:  Stop after this stage completes (inclusive).
        skip_stages: List of stage names to skip.
        persist:     Store the trace in pipeline_runs (default True).

    Returns:
        PipelineResult with per-stage outcomes, timing, and aggregate metadata.
    """
    pipeline = PipelineResult(
        run_id=f"RUN-{uuid.uuid4().hex[:12].upper()}",
        document_id=doc_id,
        started_at=utcnow(),
    )
    ctx: Dict[str, Any] = {}
    skip = set(skip_stages or [])
    t_pipeline_start = time.monotonic()

    logger.info("[Pipeline] Starting run=%s doc=%s stop_after=%s skip=%s",
                pipeline.run_id, doc_id, stop_after, skip)

    for stage_name in STAGE_ORDER:
        if stage_name in skip:
            sr = StageResult(
                stage=stage_name, status="skipped",
                output={"reason": "explicitly skipped"},
            )
            pipeline.stages.append(sr)
            pipeline.stages_skipped += 1
            if stop_after and stage_name == stop_after:
                break
            continue

        stage_start = utcnow()
        t0 = time.monotonic()
        runner = _STAGE_RUNNERS[stage_name]
        try:
            result = await runner(doc_id, ctx)
            elapsed = (time.monotonic() - t0) * 1000
            result.started_at = stage_start
            result.finished_at = utcnow()
            result.duration_ms = elapsed
            pipeline.stages.append(result)

            if result.status == "ok":
                pipeline.stages_run += 1
            elif result.status == "skipped":
                pipeline.stages_skipped += 1
            elif result.status == "error":
                pipeline.stages_errored += 1

            logger.info("[Pipeline] run=%s stage=%s status=%s %.0fms",
                        pipeline.run_id, stage_name, result.status, elapsed)
        except Exception as exc:
            elapsed = (time.monotonic() - t0) * 1000
            err_result = StageResult(
                stage=stage_name, status="error",
                started_at=stage_start,
                finished_at=utcnow(),
                duration_ms=elapsed,
                error=str(exc),
            )
            pipeline.stages.append(err_result)
            pipeline.stages_errored += 1
            logger.error("[Pipeline] run=%s stage=%s ERROR: %s %.0fms",
                         pipeline.run_id, stage_name, exc, elapsed)

        if stop_after and stage_name == stop_after:
            break

    # Finalize aggregate metadata
    pipeline.total_duration_ms = (time.monotonic() - t_pipeline_start) * 1000
    pipeline.finished_at = utcnow()

    statuses = [s.status for s in pipeline.stages]
    if all(s in ("ok", "skipped") for s in statuses):
        pipeline.status = "ok"
    elif any(s == "error" for s in statuses):
        pipeline.status = "partial"
    else:
        pipeline.status = "ok"

    logger.info(
        "[Pipeline] Finished run=%s doc=%s status=%s total=%.0fms "
        "ran=%d skipped=%d errored=%d",
        pipeline.run_id, doc_id, pipeline.status, pipeline.total_duration_ms,
        pipeline.stages_run, pipeline.stages_skipped, pipeline.stages_errored,
    )

    if persist:
        await _persist_trace(pipeline)

    return pipeline
