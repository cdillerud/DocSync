"""
GPI Hub — End-of-Day controller (Lane C Step 3B)

Orchestrates the 5-step close-day sequence:
  1. advance_readiness      – delegates to services.unified_validation_service.run_readiness
  2. post_ready_docs        – delegates to routers.readiness.retry_ready_to_post
  3. send_posted_docs       – surface-only classification; NO outbound delivery this pass
  4. escalate_stuck         – delegates to retry_failed_extractions + retry_captured
  5. reconcile_cost_receipt – read-only scan via
                              workflows.ap_invoice.rules.line_reconciliation.reconcile_line_amounts
                              (services.ap_computation stays available for future sub-categories)

Write ledger for this controller's own code (delegates produce their own writes):
  - eod_run_log collection: one row per (run_id, step_name, utc_day) – audit + idempotency
  - hub_documents.exceptions[]: additive array of typed exception records (Steps 1, 2, 3, 5)
  - hub_documents.eod_send_surfaced_utc: single ISO-timestamp field set by Step 3 only

Semantic dedupe key for exceptions[]: (exception_type, source_step, utc_day).
Dedup is enforced by the update filter – atomic at the document layer.

Step 4 emits ONLY an eod_run_log row (b.ii amendment). It does not append to exceptions[].

Feature flag: EOD_ENABLED (env, default 'false'). Controller does not read the
flag itself – the admin router enforces it and returns 501 when off. The
controller is therefore safe to unit-test directly against a mongomock DB.
"""

from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Awaitable, Callable, Mapping, Optional
import logging
import uuid

from workflows.batch.exception_queues import (
    EXCEPTION_TYPES,
    ExceptionRecord,
    build_exception,
)

logger = logging.getLogger(__name__)


ALL_STEPS: tuple[str, ...] = (
    "advance_readiness",
    "post_ready_docs",
    "send_posted_docs",
    "escalate_stuck",
    "reconcile_cost_receipt",
)


@dataclass(frozen=True)
class StepReport:
    step: str
    processed: int
    succeeded: int
    skipped: int
    exceptions_by_type: Mapping[str, int] = field(default_factory=dict)
    is_noop: bool = False


# ---------------------------------------------------------------------------
# Small helpers
# ---------------------------------------------------------------------------

def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _utc_day(iso_ts: Optional[str] = None) -> str:
    # ISO-8601 strings start with YYYY-MM-DD – slicing is safe and stable.
    return (iso_ts or _now_iso())[:10]


def _record_to_dict(rec: ExceptionRecord, utc_day: str) -> dict[str, Any]:
    """Serialize an ExceptionRecord for storage inside hub_documents.exceptions[].

    utc_day is stored as a first-class field so the semantic dedupe key
    (exception_type, source_step, utc_day) is representable via MongoDB's
    $elemMatch operator at write time.
    """
    return {
        "doc_id": rec.doc_id,
        "exception_type": rec.exception_type,
        "severity": rec.severity,
        "detail": rec.detail,
        "evidence": dict(rec.evidence),
        "created_utc": rec.created_utc,
        "source_step": rec.source_step,
        "gate_id": rec.gate_id,
        "utc_day": utc_day,
    }


# ---------------------------------------------------------------------------
# Controller
# ---------------------------------------------------------------------------

class EodController:
    """Executes the 5-step close-day on ``db``.

    ``delegates`` is an optional injection map used by tests; production
    callers construct the controller with no delegates and the methods
    late-import the real implementations. This avoids pulling heavy
    dependencies at router-import time and keeps the controller testable
    against mongomock without patching router modules.
    """

    def __init__(
        self,
        db: Any,
        *,
        delegates: Optional[Mapping[str, Callable[..., Awaitable[Any]]]] = None,
    ):
        self.db = db
        self._delegates: dict[str, Callable[..., Awaitable[Any]]] = dict(delegates or {})

    # ---- delegate resolution -------------------------------------------------

    async def _delegate(self, name: str, default_factory: Callable[[], Callable[..., Awaitable[Any]]], *args, **kwargs):
        fn = self._delegates.get(name) or default_factory()
        return await fn(*args, **kwargs)

    # ---- exception write helper --------------------------------------------

    async def _append_exception(
        self,
        doc_id: str,
        exc_type: str,
        *,
        detail: str,
        source_step: str,
        severity: Optional[str] = None,
        evidence: Optional[Mapping[str, Any]] = None,
        gate_id: Optional[str] = None,
        utc_day: Optional[str] = None,
        dry_run: bool = False,
    ) -> bool:
        """Atomically append a typed exception record to hub_documents.exceptions[].

        Returns True if the append actually occurred (modified_count == 1),
        False if the semantic dedupe guard suppressed it or dry_run is set.

        Dedupe key per user sign-off: (exception_type, source_step, utc_day).
        """
        day = utc_day or _utc_day()
        rec = build_exception(
            doc_id,
            exc_type,  # type: ignore[arg-type]
            detail=detail,
            evidence=evidence,
            severity=severity,  # type: ignore[arg-type]
            source_step=source_step,
            gate_id=gate_id,
            created_utc=_now_iso(),
        )
        entry = _record_to_dict(rec, day)

        if dry_run:
            return False

        # Atomic dedupe: only append if no existing entry shares the same
        # semantic key. MongoDB's $elemMatch + $not combination makes this
        # a single atomic operation; concurrent writers collapse to one.
        result = await self.db.hub_documents.update_one(
            {
                "id": doc_id,
                "exceptions": {
                    "$not": {
                        "$elemMatch": {
                            "exception_type": exc_type,
                            "source_step": source_step,
                            "utc_day": day,
                        }
                    }
                },
            },
            {"$push": {"exceptions": entry}},
        )
        return result.modified_count == 1

    # ---- run log -----------------------------------------------------------

    async def _write_run_log(
        self,
        *,
        run_id: str,
        step_name: str,
        utc_day: str,
        started_utc: str,
        completed_utc: str,
        report: StepReport,
        dry_run: bool,
    ) -> None:
        await self.db.eod_run_log.insert_one(
            {
                "run_id": run_id,
                "step_name": step_name,
                "utc_day": utc_day,
                "started_utc": started_utc,
                "completed_utc": completed_utc,
                "processed": report.processed,
                "succeeded": report.succeeded,
                "skipped": report.skipped,
                "exceptions_by_type": dict(report.exceptions_by_type),
                "is_noop": report.is_noop,
                "dry_run": dry_run,
            }
        )

    # =======================================================================
    # Step 1 — advance_readiness
    # =======================================================================

    async def advance_readiness(
        self,
        *,
        run_id: str,
        utc_day: str,
        dry_run: bool = False,
    ) -> StepReport:
        """Re-evaluate readiness for docs whose readiness is stale or missing.

        Delegate: services.unified_validation_service.run_readiness(doc_id)
        – existing writer persists the readiness object on hub_documents.

        New writes from THIS step:
          - hub_documents.exceptions[]: append missing_master_data(warn)
            when the delegate reports blocked/needs_review after re-eval.
          - eod_run_log: step-report row.

        Dry-run: delegate is not called; candidates are counted only.
        """
        candidates = await self.db.hub_documents.find(
            {
                "$or": [
                    {"readiness": {"$exists": False}},
                    {"readiness.status": {"$in": ["blocked", "needs_review"]}},
                ]
            },
            {"_id": 0, "id": 1},
        ).to_list(length=1000)

        counts: dict[str, int] = {}
        succeeded = 0
        skipped = 0

        if dry_run:
            return StepReport(
                step="advance_readiness",
                processed=len(candidates),
                succeeded=0,
                skipped=len(candidates),
                exceptions_by_type={},
                is_noop=True,
            )

        async def _default_run_readiness():
            from services.unified_validation_service import run_readiness
            return run_readiness

        for c in candidates:
            doc_id = c.get("id")
            if not doc_id:
                skipped += 1
                continue
            try:
                result = await self._delegate("run_readiness", _default_run_readiness, doc_id)
            except Exception as e:
                logger.warning("[EOD] advance_readiness delegate failed for %s: %s", doc_id[:8], str(e))
                skipped += 1
                continue

            status = (result or {}).get("status") if isinstance(result, dict) else None
            if status in ("blocked", "needs_review"):
                blocking = []
                if isinstance(result, dict):
                    blocking = result.get("blocking_reasons") or []
                detail = (
                    f"readiness.status={status}; blocking={', '.join(blocking[:5]) or 'n/a'}"
                )
                appended = await self._append_exception(
                    doc_id,
                    "missing_master_data",
                    detail=detail,
                    source_step="advance_readiness",
                    evidence={"status": status, "blocking_reasons": blocking},
                    utc_day=utc_day,
                )
                if appended:
                    counts["missing_master_data"] = counts.get("missing_master_data", 0) + 1
            succeeded += 1

        return StepReport(
            step="advance_readiness",
            processed=len(candidates),
            succeeded=succeeded,
            skipped=skipped,
            exceptions_by_type=counts,
        )

    # =======================================================================
    # Step 2 — post_ready_docs
    # =======================================================================

    async def post_ready_docs(
        self,
        *,
        run_id: str,
        utc_day: str,
        dry_run: bool = False,
        limit: int = 50,
    ) -> StepReport:
        """Attempt BC post for ReadyForPost docs via the existing retry path.

        Delegate: routers.readiness.retry_ready_to_post(limit)
        – existing writer sets status=Posted, bc_record_no, bc_posting_status, etc.

        New writes from THIS step:
          - hub_documents.exceptions[] for docs whose delegate outcome is
            partial_post or archived_doc_collision.
          - eod_run_log: step-report row.

        Dry-run: delegate is not called; candidates are counted only.
        """
        candidates = await self.db.hub_documents.find(
            {
                "$or": [
                    {"status": "ReadyForPost"},
                    {"workflow_status": "ready_for_post"},
                ],
                "status": {"$nin": ["Posted", "Completed", "Archived"]},
                "bc_purchase_invoice": {"$exists": False},
            },
            {"_id": 0, "id": 1},
        ).to_list(length=limit)

        counts: dict[str, int] = {}

        if dry_run:
            return StepReport(
                step="post_ready_docs",
                processed=len(candidates),
                succeeded=0,
                skipped=len(candidates),
                exceptions_by_type={},
                is_noop=True,
            )

        async def _default_retry():
            from routers.readiness import retry_ready_to_post
            return retry_ready_to_post

        result: dict[str, Any] = {}
        try:
            result = await self._delegate("retry_ready_to_post", _default_retry, limit=limit)
            if not isinstance(result, dict):
                result = {}
        except Exception as e:
            logger.warning("[EOD] post_ready_docs delegate raised: %s", str(e))
            result = {}

        posted = int(result.get("posted", 0) or 0)
        failed = int(result.get("failed", 0) or 0)
        details = result.get("details") or []

        # Classify failure details into the taxonomy. Heuristics are conservative:
        # real partial_post and archived collisions leave recognisable markers in
        # the delegate's `error` string. Anything that doesn't match is counted
        # as a plain failure – the delegate's own logs hold the specifics.
        for d in details:
            action = (d.get("action") or "").lower()
            err = (d.get("error") or "").lower()
            doc_ref = d.get("doc_id") or ""
            if action != "failed" and "error" not in action:
                continue
            # Delegate returns truncated doc_id (8 chars). Resolve to full id.
            full_doc = None
            if doc_ref:
                full_doc = await self.db.hub_documents.find_one(
                    {"id": {"$regex": f"^{doc_ref}"}},
                    {"_id": 0, "id": 1},
                )
            if not full_doc:
                continue
            full_id = full_doc["id"]

            if "partial_post" in err or "partial" in err:
                if await self._append_exception(
                    full_id,
                    "partial_post",
                    detail=d.get("error") or "partial post reported by delegate",
                    source_step="post_ready_docs",
                    evidence={"delegate_error": d.get("error")},
                    utc_day=utc_day,
                ):
                    counts["partial_post"] = counts.get("partial_post", 0) + 1
            elif "archived" in err or "already exists" in err:
                if await self._append_exception(
                    full_id,
                    "archived_doc_collision",
                    detail=d.get("error") or "archived collision reported by delegate",
                    source_step="post_ready_docs",
                    evidence={"delegate_error": d.get("error")},
                    utc_day=utc_day,
                ):
                    counts["archived_doc_collision"] = counts.get("archived_doc_collision", 0) + 1

        return StepReport(
            step="post_ready_docs",
            processed=len(candidates),
            succeeded=posted,
            skipped=max(0, len(candidates) - posted - failed),
            exceptions_by_type=counts,
        )

    # =======================================================================
    # Step 3 — send_posted_docs  (CONSERVATIVE; no outbound delivery)
    # =======================================================================

    async def send_posted_docs(
        self,
        *,
        run_id: str,
        utc_day: str,
        dry_run: bool = False,
        limit: int = 500,
    ) -> StepReport:
        """Surface exceptions on Posted docs that should NOT be sent.

        This step performs NO outbound delivery. It only writes taxonomy
        records for two cases:
          - zero-amount Posted doc           -> intentional_send_skip(info)
          - archived-elsewhere collision     -> archived_doc_collision(block)

        All other Posted docs are skipped with no flag written. Future
        outbound-delivery work will consume eod_send_surfaced_utc to
        decide what still needs processing.

        Writes:
          - hub_documents.exceptions[]: conditional, per classification.
          - hub_documents.eod_send_surfaced_utc: set only when an exception
            is appended. Never unset.
          - eod_run_log: step-report row.
        """
        candidates = await self.db.hub_documents.find(
            {
                "status": {"$in": ["Posted", "posted"]},
                "eod_send_surfaced_utc": {"$exists": False},
            },
            {
                "_id": 0, "id": 1, "amount_float": 1,
                "bc_record_no": 1, "archived_sibling_id": 1,
            },
        ).to_list(length=limit)

        counts: dict[str, int] = {"intentional_send_skip": 0, "archived_doc_collision": 0}
        succeeded = 0
        skipped = 0

        for doc in candidates:
            doc_id = doc.get("id")
            if not doc_id:
                skipped += 1
                continue

            amount = doc.get("amount_float")
            is_zero_amount = amount is not None and float(amount) == 0.0
            archived_sibling = doc.get("archived_sibling_id")

            # Classify. Only the two scope-fence categories may fire here.
            if is_zero_amount:
                exc_type = "intentional_send_skip"
                detail = "zero-amount Posted doc; send is intentionally skipped"
                evidence: dict[str, Any] = {"amount_float": amount}
            elif archived_sibling:
                exc_type = "archived_doc_collision"
                detail = f"Posted doc collides with archived sibling {archived_sibling}"
                evidence = {"archived_sibling_id": archived_sibling}
            else:
                # Out-of-scope per user guardrail – no-op, no flag.
                skipped += 1
                continue

            if dry_run:
                succeeded += 1
                counts[exc_type] += 1
                continue

            # Atomic: append exception AND set eod_send_surfaced_utc only
            # if the flag is still unset and no same-key entry already exists.
            now = _now_iso()
            rec = build_exception(
                doc_id,
                exc_type,
                detail=detail,
                evidence=evidence,
                source_step="send_posted_docs",
                created_utc=now,
            )
            entry = _record_to_dict(rec, utc_day)
            result = await self.db.hub_documents.update_one(
                {
                    "id": doc_id,
                    "eod_send_surfaced_utc": {"$exists": False},
                    "exceptions": {
                        "$not": {
                            "$elemMatch": {
                                "exception_type": exc_type,
                                "source_step": "send_posted_docs",
                                "utc_day": utc_day,
                            }
                        }
                    },
                },
                {
                    "$push": {"exceptions": entry},
                    "$set": {"eod_send_surfaced_utc": now},
                },
            )
            if result.modified_count == 1:
                succeeded += 1
                counts[exc_type] += 1
            else:
                skipped += 1

        # Drop zero-count categories from the report for readability.
        counts = {k: v for k, v in counts.items() if v > 0}

        return StepReport(
            step="send_posted_docs",
            processed=len(candidates),
            succeeded=succeeded,
            skipped=skipped,
            exceptions_by_type=counts,
        )

    # =======================================================================
    # Step 4 — escalate_stuck  (b.ii: NO typed exception emission)
    # =======================================================================

    async def escalate_stuck(
        self,
        *,
        run_id: str,
        utc_day: str,
        dry_run: bool = False,
        limit: int = 200,
    ) -> StepReport:
        """Delegate to existing escalation paths; write NOTHING to exceptions[].

        Per user sign-off (b.ii): Step 4 remains string-based. The existing
        `escalation_reason` field continues to carry the meaning. Step 4
        only writes an eod_run_log row.
        """
        if dry_run:
            # Count candidates without mutating anything.
            stuck = await self.db.hub_documents.count_documents(
                {
                    "status": {
                        "$in": [
                            "captured", "Captured",
                            "needs_review", "NeedsReview",
                        ]
                    },
                    "auto_escalated": {"$ne": True},
                }
            )
            return StepReport(
                step="escalate_stuck",
                processed=stuck,
                succeeded=0,
                skipped=stuck,
                exceptions_by_type={},
                is_noop=True,
            )

        async def _default_retry_failed():
            from routers.readiness import retry_failed_extractions
            return retry_failed_extractions

        failed_result: dict[str, Any] = {}
        try:
            failed_result = await self._delegate(
                "retry_failed_extractions",
                _default_retry_failed,
                limit=limit,
            ) or {}
        except Exception as e:
            logger.warning("[EOD] escalate_stuck retry_failed delegate raised: %s", str(e))

        escalated = int(failed_result.get("escalated_to_exception", 0) or 0)
        retried = int(failed_result.get("retried", 0) or 0)

        return StepReport(
            step="escalate_stuck",
            processed=retried + escalated,
            succeeded=escalated,
            skipped=retried,
            exceptions_by_type={},  # b.ii – explicitly empty
        )

    # =======================================================================
    # Step 5 — reconcile_cost_receipt
    # =======================================================================

    async def reconcile_cost_receipt(
        self,
        *,
        run_id: str,
        utc_day: str,
        dry_run: bool = False,
        window_hours: int = 24,
        limit: int = 500,
    ) -> StepReport:
        """Read-only scan of recently-posted AP invoices for cost variance.

        Delegate: workflows.ap_invoice.rules.line_reconciliation.reconcile_line_amounts
        – pure function, one call per extracted line.

        Emits cost_mismatch(block) when any line reports a non-None variance.
        The remaining three sub-categories (receipt_invoice_mismatch,
        duplicate_invoice_risk, location_division_mismatch) are wired but
        depend on upstream flags that are not yet populated; they remain
        dormant until those signals exist.

        Writes ONLY hub_documents.exceptions[] additively; never mutates
        status/bc_*/readiness.
        """
        cutoff = datetime.now(timezone.utc).isoformat()[:19]  # coarse for mongomock
        _ = window_hours  # window_hours retained in signature for future filtering

        candidates = await self.db.hub_documents.find(
            {
                "status": {"$in": ["Posted", "posted"]},
                "posted_to_bc_at": {"$exists": True},
            },
            {
                "_id": 0, "id": 1, "extracted_fields": 1,
                "duplicate_candidates": 1, "location_division_mismatch": 1,
                "receipt_invoice_mismatch": 1,
            },
        ).to_list(length=limit)
        _ = cutoff

        counts: dict[str, int] = {}
        succeeded = 0

        async def _default_reconcile():
            from workflows.ap_invoice.rules.line_reconciliation import reconcile_line_amounts

            async def _wrapped(line: dict[str, Any]):
                return reconcile_line_amounts(line)
            return _wrapped

        for doc in candidates:
            doc_id = doc.get("id")
            if not doc_id:
                continue

            # cost_mismatch via line reconciliation.
            ef = doc.get("extracted_fields") or {}
            line_items = ef.get("line_items") or ef.get("lines") or []
            cost_variance_lines: list[dict[str, Any]] = []
            if isinstance(line_items, list):
                for idx, line in enumerate(line_items):
                    try:
                        info = await self._delegate(
                            "reconcile_line_amounts", _default_reconcile, line
                        )
                    except Exception as e:
                        logger.debug("[EOD] reconcile line %d failed on %s: %s",
                                     idx, doc_id[:8], str(e))
                        continue
                    # Delegate returns either (expected, actual, info_dict) or info_dict directly.
                    variance_info = None
                    if isinstance(info, tuple) and len(info) == 3:
                        variance_info = info[2]
                    elif isinstance(info, dict):
                        variance_info = info
                    if variance_info:
                        cost_variance_lines.append({"line_index": idx, **variance_info})

            if cost_variance_lines and not dry_run:
                if await self._append_exception(
                    doc_id,
                    "cost_mismatch",
                    detail=f"{len(cost_variance_lines)} line(s) with cost variance",
                    source_step="reconcile_cost_receipt",
                    evidence={"variance_lines": cost_variance_lines[:10]},
                    utc_day=utc_day,
                ):
                    counts["cost_mismatch"] = counts.get("cost_mismatch", 0) + 1

            # Dormant sub-categories: surface only when upstream flags exist.
            if not dry_run:
                if doc.get("duplicate_candidates"):
                    if await self._append_exception(
                        doc_id,
                        "duplicate_invoice_risk",
                        detail="duplicate candidates detected upstream",
                        source_step="reconcile_cost_receipt",
                        evidence={"duplicate_candidates": doc.get("duplicate_candidates")},
                        utc_day=utc_day,
                    ):
                        counts["duplicate_invoice_risk"] = counts.get("duplicate_invoice_risk", 0) + 1
                if doc.get("receipt_invoice_mismatch"):
                    if await self._append_exception(
                        doc_id,
                        "receipt_invoice_mismatch",
                        detail="receipt_invoice_mismatch flag set upstream",
                        source_step="reconcile_cost_receipt",
                        evidence={"upstream_flag": doc.get("receipt_invoice_mismatch")},
                        utc_day=utc_day,
                    ):
                        counts["receipt_invoice_mismatch"] = counts.get("receipt_invoice_mismatch", 0) + 1
                if doc.get("location_division_mismatch"):
                    if await self._append_exception(
                        doc_id,
                        "location_division_mismatch",
                        detail="location_division_mismatch flag set upstream",
                        source_step="reconcile_cost_receipt",
                        evidence={"upstream_flag": doc.get("location_division_mismatch")},
                        utc_day=utc_day,
                    ):
                        counts["location_division_mismatch"] = counts.get("location_division_mismatch", 0) + 1

            succeeded += 1

        return StepReport(
            step="reconcile_cost_receipt",
            processed=len(candidates),
            succeeded=succeeded,
            skipped=0,
            exceptions_by_type=counts,
            is_noop=dry_run,
        )

    # =======================================================================
    # Orchestration
    # =======================================================================

    async def run_close_day(
        self,
        *,
        steps: Optional[list[str]] = None,
        dry_run: bool = False,
    ) -> dict[str, Any]:
        """Execute the 5-step close-day and return an aggregate report."""
        run_id = str(uuid.uuid4())
        utc_day = _utc_day()
        selected = tuple(steps) if steps else ALL_STEPS

        # Validate step names up-front – unknown names are a 400-class error.
        unknown = [s for s in selected if s not in ALL_STEPS]
        if unknown:
            raise ValueError(f"unknown EOD steps: {unknown}; valid: {ALL_STEPS}")

        reports: list[dict[str, Any]] = []

        for step_name in selected:
            started = _now_iso()
            method = getattr(self, step_name)
            try:
                report: StepReport = await method(
                    run_id=run_id, utc_day=utc_day, dry_run=dry_run
                )
            except Exception as e:
                logger.exception("[EOD] step %s crashed: %s", step_name, str(e))
                report = StepReport(
                    step=step_name, processed=0, succeeded=0, skipped=0,
                    exceptions_by_type={}, is_noop=True,
                )
            completed = _now_iso()
            await self._write_run_log(
                run_id=run_id,
                step_name=step_name,
                utc_day=utc_day,
                started_utc=started,
                completed_utc=completed,
                report=report,
                dry_run=dry_run,
            )
            reports.append(
                {
                    "step": report.step,
                    "processed": report.processed,
                    "succeeded": report.succeeded,
                    "skipped": report.skipped,
                    "exceptions_by_type": dict(report.exceptions_by_type),
                    "is_noop": report.is_noop,
                    "started_utc": started,
                    "completed_utc": completed,
                }
            )

        return {
            "run_id": run_id,
            "utc_day": utc_day,
            "dry_run": dry_run,
            "steps": reports,
        }


# ---------------------------------------------------------------------------
# Read-side helper
# ---------------------------------------------------------------------------

async def get_last_run(db: Any, *, step: Optional[str] = None) -> dict[str, Any]:
    """Return the most recent eod_run_log entries.

    If ``step`` is provided, returns the single latest row for that step.
    If omitted, returns the latest row per known step.
    """
    if step:
        if step not in ALL_STEPS:
            raise ValueError(f"unknown step {step!r}; valid: {ALL_STEPS}")
        row = await db.eod_run_log.find_one(
            {"step_name": step},
            {"_id": 0},
            sort=[("completed_utc", -1)],
        )
        return {"step": step, "last_run": row}

    latest: dict[str, Any] = {}
    for s in ALL_STEPS:
        row = await db.eod_run_log.find_one(
            {"step_name": s},
            {"_id": 0},
            sort=[("completed_utc", -1)],
        )
        latest[s] = row
    return {"latest_per_step": latest}


# Expose the exception-type catalog through this module too so the router's
# response schema can document the taxonomy without an extra import.
__all__ = [
    "ALL_STEPS",
    "StepReport",
    "EodController",
    "get_last_run",
    "EXCEPTION_TYPES",
]
