"""
GPI Document Hub - Auto-Resolution Service

Runs reference intelligence automatically in the background after document intake.

Key design:
- Non-blocking: ingestion never waits on resolution
- Cache-first: uses BC cache layer, falls back to API only on miss
- Read-only: never writes to BC
- Idempotent: tracks version/hash to avoid redundant runs
- Rate-limited: max concurrent workers to prevent overwhelming BC/app
- Retry: limited retries with backoff on failure
- Document-type-aware: only auto-runs for relevant types

Events emitted:
- reference.resolve.queued
- reference.resolve.started
- reference.resolve.completed
- reference.resolve.failed
- reference.resolve.retry_scheduled
- reference.resolve.skipped
"""

import asyncio
import hashlib
import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

# Auto-resolution configuration
AUTO_RESOLVE_MAX_WORKERS = 5
AUTO_RESOLVE_MAX_RETRIES = 3
AUTO_RESOLVE_BACKOFF = [30, 60, 120]  # seconds
RESOLVER_VERSION = "1.0.0"

# Document types eligible for auto-resolution
ELIGIBLE_DOC_TYPES = {
    "AP_Invoice", "AP Invoice",
    "Freight_Invoice", "Freight Invoice", "Freight",
    "Shipping_Document", "Shipping Document", "Shipping",
    "BOL", "Bill_of_Lading", "Bill of Lading",
    "Sales_Order", "Sales Order",
}

# Minimum classification confidence for auto-run
MIN_CONFIDENCE_FOR_AUTO = 0.50


def compute_resolution_hash(doc: Dict[str, Any]) -> str:
    """Compute a hash of fields that affect reference resolution."""
    fields = []
    for key in sorted([
        "po_number_clean", "bol_number", "invoice_number_clean",
        "vendor_normalized", "vendor_canonical",
        "document_type", "suggested_job_type",
    ]):
        val = doc.get(key) or ""
        fields.append(f"{key}={val}")

    ef = doc.get("extracted_fields") or {}
    for key in sorted(ef.keys()):
        fields.append(f"ef.{key}={ef[key]}")

    raw = "|".join(fields)
    return hashlib.sha256(raw.encode()).hexdigest()[:16]


def is_eligible_for_auto_resolution(doc: Dict[str, Any]) -> tuple:
    """
    Check if a document should have auto-resolution.
    Returns (eligible: bool, reason: str)
    """
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""

    if doc_type in ELIGIBLE_DOC_TYPES:
        return True, f"doc_type={doc_type} is eligible"

    confidence = doc.get("ai_confidence") or 0.0
    if confidence < MIN_CONFIDENCE_FOR_AUTO:
        return False, f"low confidence ({confidence:.2f}), manual trigger required"

    return False, f"doc_type={doc_type} not in eligible list"


def needs_resolution(doc: Dict[str, Any]) -> tuple:
    """
    Check if resolution should run (idempotency check).
    Returns (should_run: bool, reason: str)
    """
    _ = doc.get("reference_intelligence") or {}
    status = doc.get("reference_intelligence_status")

    # Never run before
    if not status or status == "not_run":
        return True, "first run"

    # Currently pending (another worker is on it)
    if status == "pending":
        return False, "already pending"

    # Check version
    prev_version = doc.get("reference_intelligence_version")
    if prev_version != RESOLVER_VERSION:
        return True, "version changed (%s → %s)" % (prev_version, RESOLVER_VERSION)

    # Check hash (extracted fields changed)
    prev_hash = doc.get("reference_intelligence_hash")
    current_hash = compute_resolution_hash(doc)
    if prev_hash != current_hash:
        return True, f"document data changed (hash mismatch)"

    return False, "document data is current"


class AutoResolutionService:
    """
    Background auto-resolution worker.

    Manages an async queue of documents to resolve references for.
    Rate-limited to MAX_WORKERS concurrent resolutions.
    """

    def __init__(self, db, ref_intelligence_service, event_service=None):
        self.db = db
        self.ref_service = ref_intelligence_service
        self.event_service = event_service
        self._queue = asyncio.Queue(maxsize=500)
        self._workers = []
        self._running = False
        self._stats = {
            "queued": 0, "completed": 0, "failed": 0,
            "skipped": 0, "retried": 0
        }

    def start(self, num_workers: int = AUTO_RESOLVE_MAX_WORKERS):
        """Start background workers."""
        if self._running:
            return
        self._running = True
        for i in range(num_workers):
            task = asyncio.create_task(self._worker(i))
            self._workers.append(task)
        logger.info("[AutoResolve] Started %d workers", num_workers)

    def stop(self):
        """Stop background workers."""
        self._running = False
        for task in self._workers:
            task.cancel()
        self._workers.clear()
        logger.info("[AutoResolve] Stopped")

    async def enqueue(self, doc_id: str, retry_count: int = 0):
        """Add a document to the resolution queue."""
        try:
            self._queue.put_nowait({"doc_id": doc_id, "retry_count": retry_count})
            self._stats["queued"] += 1
        except asyncio.QueueFull:
            logger.warning("[AutoResolve] Queue full, dropping doc %s", doc_id[:8])

    async def _worker(self, worker_id: int):
        """Background worker that processes documents from the queue."""
        while self._running:
            try:
                item = await asyncio.wait_for(self._queue.get(), timeout=5.0)
            except asyncio.TimeoutError:
                continue
            except asyncio.CancelledError:
                break

            doc_id = item["doc_id"]
            retry_count = item.get("retry_count", 0)

            try:
                await self._process_document(doc_id, retry_count, worker_id)
            except Exception as e:
                logger.error("[AutoResolve:W%d] Unhandled error for %s: %s", worker_id, doc_id[:8], str(e))

    async def _process_document(self, doc_id: str, retry_count: int, worker_id: int):
        """Process a single document through auto-resolution."""
        doc = await self.db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        if not doc:
            logger.warning("[AutoResolve:W%d] Doc %s not found", worker_id, doc_id[:8])
            return

        # Eligibility check
        eligible, reason = is_eligible_for_auto_resolution(doc)
        if not eligible:
            logger.debug("[AutoResolve:W%d] Skipping %s: %s", worker_id, doc_id[:8], reason)
            self._stats["skipped"] += 1
            await self._emit("reference.resolve.skipped", doc_id, payload={"reason": reason})
            return

        # Idempotency check (skip if on first run, always run)
        if retry_count == 0:
            should_run, idempotency_reason = needs_resolution(doc)
            if not should_run:
                logger.debug("[AutoResolve:W%d] Skipping %s: %s", worker_id, doc_id[:8], idempotency_reason)
                self._stats["skipped"] += 1
                return

        # Mark as pending
        await self.db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "reference_intelligence_status": "pending",
                "updated_utc": datetime.now(timezone.utc).isoformat()
            }}
        )
        await self._emit("reference.resolve.started", doc_id, payload={
            "retry_count": retry_count, "worker_id": worker_id
        })

        logger.info("[AutoResolve:W%d] Resolving %s (retry=%d)", worker_id, doc_id[:8], retry_count)

        try:
            # Build extracted fields
            extracted_fields = doc.get("extracted_fields") or {}
            for fld in ["po_number", "bol_number", "invoice_number", "order_number"]:
                if doc.get(fld) and not extracted_fields.get(fld):
                    extracted_fields[fld] = doc[fld]
            if doc.get("po_number_clean") and not extracted_fields.get("po_number"):
                extracted_fields["po_number"] = doc["po_number_clean"]
            if doc.get("invoice_number_clean") and not extracted_fields.get("invoice_number"):
                extracted_fields["invoice_number"] = doc["invoice_number_clean"]

            document_text = doc.get("extracted_text") or doc.get("raw_text") or ""

            # Run resolution
            resolution = await self.ref_service.resolve_document_references(
                document=doc,
                extracted_fields=extracted_fields,
                document_text=document_text
            )

            # Store results
            await self.ref_service.update_document_references(doc_id, resolution)

            # Update status fields
            resolution_hash = compute_resolution_hash(doc)
            outcome = resolution.match_outcome or "no_match"
            status_map = {
                "exact_match": "completed",
                "likely_match": "completed",
                "ambiguous_match": "ambiguous",
                "no_match": "completed",
            }

            await self.db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "reference_intelligence_status": status_map.get(outcome, "completed"),
                    "reference_intelligence_last_run": datetime.now(timezone.utc).isoformat(),
                    "reference_intelligence_version": RESOLVER_VERSION,
                    "reference_intelligence_hash": resolution_hash,
                    "reference_intelligence_outcome": outcome,
                    "reference_intelligence_best_score": (
                        resolution.best_match.match_score if resolution.best_match else None
                    ),
                    "updated_utc": datetime.now(timezone.utc).isoformat()
                }}
            )

            self._stats["completed"] += 1
            logger.info(
                "[AutoResolve:W%d] Resolved %s → %s (score=%.2f, time=%dms)",
                worker_id, doc_id[:8], outcome,
                resolution.best_match.match_score if resolution.best_match else 0,
                resolution.processing_time_ms or 0
            )

        except Exception as e:
            logger.error("[AutoResolve:W%d] Failed %s: %s", worker_id, doc_id[:8], str(e))
            self._stats["failed"] += 1

            if retry_count < AUTO_RESOLVE_MAX_RETRIES:
                backoff = AUTO_RESOLVE_BACKOFF[min(retry_count, len(AUTO_RESOLVE_BACKOFF) - 1)]
                await self.db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "reference_intelligence_status": "retry_scheduled",
                        "reference_intelligence_retry_count": retry_count + 1,
                        "updated_utc": datetime.now(timezone.utc).isoformat()
                    }}
                )
                await self._emit("reference.resolve.retry_scheduled", doc_id, payload={
                    "retry_count": retry_count + 1,
                    "backoff_seconds": backoff,
                    "error": str(e)
                })
                self._stats["retried"] += 1
                # Schedule retry
                asyncio.create_task(self._retry_after(doc_id, retry_count + 1, backoff))
            else:
                await self.db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "reference_intelligence_status": "failed",
                        "reference_intelligence_error": str(e),
                        "updated_utc": datetime.now(timezone.utc).isoformat()
                    }}
                )
                await self._emit("reference.resolve.failed", doc_id, status="error", payload={
                    "error": str(e), "retry_count": retry_count
                })

    async def _retry_after(self, doc_id: str, retry_count: int, delay: int):
        """Schedule a retry after a delay."""
        await asyncio.sleep(delay)
        if self._running:
            await self.enqueue(doc_id, retry_count=retry_count)

    async def _emit(self, event_type: str, doc_id: str, status: str = "completed", payload: dict = None):
        """Emit an event if event service is available."""
        if self.event_service:
            try:
                await self.event_service.emit(
                    event_type=event_type,
                    document_id=doc_id,
                    status=status,
                    source_service="auto_resolution",
                    payload=payload or {}
                )
            except Exception as e:
                logger.warning("[AutoResolve] Event emit error: %s", str(e))

    def get_stats(self) -> Dict[str, Any]:
        """Get auto-resolution statistics."""
        return {
            **self._stats,
            "queue_size": self._queue.qsize(),
            "workers": len(self._workers),
            "running": self._running,
        }


# =============================================================================
# GLOBAL INSTANCE
# =============================================================================

_auto_resolve_service: Optional[AutoResolutionService] = None


def get_auto_resolve_service() -> Optional[AutoResolutionService]:
    return _auto_resolve_service


def set_auto_resolve_service(db, ref_intelligence_service, event_service=None) -> AutoResolutionService:
    global _auto_resolve_service
    _auto_resolve_service = AutoResolutionService(db, ref_intelligence_service, event_service)
    return _auto_resolve_service
