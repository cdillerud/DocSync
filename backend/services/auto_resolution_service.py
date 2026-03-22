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

from services.automation_helpers import utcnow, build_document_update

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
    "Freight_Document", "Freight Document",
    "Shipping_Document", "Shipping Document", "Shipping",
    "BOL", "Bill_of_Lading", "Bill of Lading",
    "Sales_Order", "Sales Order",
    "Quality_Issue", "Quality Issue",
    "Order_Confirmation", "Order Confirmation", "Order_Confirm",
    "Warehouse_Receipt", "Warehouse Receipt",
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
        return True, "document data changed (hash mismatch)"

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
        self._vendor_intel = None
        self._rules_engine = None
        self._ap_validation_service = None
        self._freight_gl_service = None
        self._label_correction_service = None
        self._layout_fingerprint_service = None
        self._stable_vendor_service = None
        self._queue = asyncio.Queue(maxsize=500)
        self._workers = []
        self._running = False
        self._stats = {
            "queued": 0, "completed": 0, "failed": 0,
            "skipped": 0, "retried": 0
        }

    def set_vendor_intelligence(self, vendor_intel):
        """Inject vendor intelligence service for post-resolution updates."""
        self._vendor_intel = vendor_intel

    def set_rules_engine(self, rules_engine):
        """Inject automation rules engine for post-resolution evaluation."""
        self._rules_engine = rules_engine

    def set_ap_validation_service(self, ap_validation_service):
        """Inject AP validation service for post-resolution validation."""
        self._ap_validation_service = ap_validation_service

    def set_freight_gl_service(self, freight_gl_service):
        """Inject freight GL routing service."""
        self._freight_gl_service = freight_gl_service

    def set_label_correction_service(self, label_correction_service):
        """Inject label correction service for post-resolution learning."""
        self._label_correction_service = label_correction_service

    def set_layout_fingerprint_service(self, layout_fingerprint_service):
        """Inject layout fingerprint service for structural analysis."""
        self._layout_fingerprint_service = layout_fingerprint_service

    def set_stable_vendor_service(self, stable_vendor_service):
        """Inject stable vendor service for auto-ready evaluation."""
        self._stable_vendor_service = stable_vendor_service

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
                "updated_utc": utcnow()
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
                    "reference_intelligence_last_run": utcnow(),
                    "reference_intelligence_version": RESOLVER_VERSION,
                    "reference_intelligence_hash": resolution_hash,
                    "reference_intelligence_outcome": outcome,
                    "reference_intelligence_best_score": (
                        resolution.best_match.match_score if resolution.best_match else None
                    ),
                    "updated_utc": utcnow()
                }}
            )

            self._stats["completed"] += 1
            logger.info(
                "[AutoResolve:W%d] Resolved %s → %s (score=%.2f, time=%dms)",
                worker_id, doc_id[:8], outcome,
                resolution.best_match.match_score if resolution.best_match else 0,
                resolution.processing_time_ms or 0
            )

            # Update vendor intelligence profile (async, non-blocking)
            if self._vendor_intel:
                try:
                    updated_doc = await self.db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
                    if updated_doc:
                        await self._vendor_intel.update_from_document(updated_doc)
                except Exception as ve:
                    logger.warning("[AutoResolve:W%d] Vendor intel update error: %s", worker_id, str(ve))

            # ---------------------------------------------------------
            # LAYOUT FINGERPRINTING (structural signal, async, non-blocking)
            # Generate structural fingerprint and assign to family
            # ---------------------------------------------------------
            if self._layout_fingerprint_service:
                try:
                    fp_result = await self._layout_fingerprint_service.generate_fingerprint(
                        doc_id, document_text, doc
                    )
                    if fp_result:
                        # Update family metrics with resolution outcome
                        resolution_success = outcome in ("exact_match", "likely_match")
                        best_label = None
                        best_entity = None
                        if resolution.reference_candidates:
                            best_label = resolution.reference_candidates[0].detected_label
                        if resolution.best_match:
                            best_entity = resolution.best_match.entity_type
                        await self._layout_fingerprint_service.update_family_metrics(
                            doc_id,
                            resolution_success=resolution_success,
                            reference_label=best_label,
                            bc_entity_type=best_entity,
                        )
                except Exception as lfe:
                    logger.warning("[AutoResolve:W%d] Layout fingerprint error: %s", worker_id, str(lfe))

            # ---------------------------------------------------------
            # LABEL CORRECTION FEEDBACK LOOP (async, non-blocking)
            # Detect mislabeled references from successful resolutions
            # ---------------------------------------------------------
            if self._label_correction_service and resolution.best_match:
                try:
                    doc_for_correction = await self.db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
                    if doc_for_correction:
                        corrections = await self._label_correction_service.detect_and_record(
                            document_id=doc_id,
                            resolution_result=resolution.to_dict(),
                            document=doc_for_correction,
                        )
                        if corrections:
                            logger.info(
                                "[AutoResolve:W%d] Label corrections recorded for %s: %d",
                                worker_id, doc_id[:8], len(corrections)
                            )
                            # Update vendor profiles with correction patterns
                            if self._vendor_intel:
                                uvm = doc_for_correction.get("unified_vendor_match") or {}
                                vendor_id = uvm.get("bc_vendor_no") or doc_for_correction.get("vendor_raw") or ""
                                if vendor_id:
                                    for c in corrections:
                                        try:
                                            await self._vendor_intel.update_label_correction_patterns(vendor_id, c)
                                        except Exception:
                                            pass
                except Exception as lce:
                    logger.warning("[AutoResolve:W%d] Label correction error: %s", worker_id, str(lce))

            # ---------------------------------------------------------
            # FREIGHT G/L CLASSIFICATION (async, non-blocking)
            # ---------------------------------------------------------
            if self._freight_gl_service:
                try:
                    await self._freight_gl_service.classify_and_save(doc_id)
                except Exception as fe:
                    logger.warning("[AutoResolve:W%d] Freight GL error: %s", worker_id, str(fe))

            # ---------------------------------------------------------
            # AP VALIDATION (authoritative validation step)
            # Only for AP-relevant document types
            # ---------------------------------------------------------
            if self._ap_validation_service:
                try:
                    await self._run_ap_validation(doc_id, worker_id)
                except Exception as ave:
                    logger.warning("[AutoResolve:W%d] AP validation error: %s", worker_id, str(ave))

            # Evaluate automation rules (async, non-blocking)
            if self._rules_engine:
                try:
                    rules_doc = await self.db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
                    if rules_doc:
                        rule_result = await self._rules_engine.evaluate(rules_doc)
                        if rule_result and rule_result.get("matched"):
                            logger.info(
                                "[AutoResolve:W%d] Rule '%s' applied to %s",
                                worker_id, rule_result.get("rule_name"), doc_id[:8]
                            )
                except Exception as re:
                    logger.warning("[AutoResolve:W%d] Rules eval error: %s", worker_id, str(re))

            # ---------------------------------------------------------
            # STABLE VENDOR AUTO-READY EVALUATION
            # Runs after all other steps; produces routing signals
            # ---------------------------------------------------------
            if self._stable_vendor_service:
                try:
                    sv_doc = await self.db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
                    if sv_doc:
                        sv_result = await self._stable_vendor_service.evaluate_document(sv_doc)
                        routing = sv_result.get("routing", "manual_review")
                        # Persist decision on document
                        sv_update = {
                            "stable_vendor_routing": {
                                "routing": routing,
                                "reasons": sv_result.get("reasons", []),
                                "evaluated_at": sv_result.get("evaluated_at", ""),
                                "vendor_stable": sv_result.get("vendor_stability", {}).get("stable_vendor_flag", False),
                                "vendor_score": sv_result.get("vendor_stability", {}).get("stable_vendor_score", 0),
                                "checks": sv_result.get("checks", []),
                            },
                            "updated_utc": utcnow(),
                        }
                        # If auto_ready, update workflow signals
                        if routing == "auto_ready":
                            sv_update["review_priority"] = "auto_ready"
                            sv_update["queue_visible"] = True
                        elif routing == "low_priority_review":
                            sv_update["review_priority"] = "low"
                        await self.db.hub_documents.update_one({"id": doc_id}, {"$set": sv_update})
                        if routing != "manual_review":
                            logger.info(
                                "[AutoResolve:W%d] Stable vendor routing: %s for %s",
                                worker_id, routing, doc_id[:8]
                            )
                except Exception as sve:
                    logger.warning("[AutoResolve:W%d] Stable vendor eval error: %s", worker_id, str(sve))

            # ---------------------------------------------------------
            # PO RESOLUTION (for shipping/freight docs, async, non-blocking)
            # Extracts PO candidates and matches against BC cache
            # ---------------------------------------------------------
            try:
                from services.po_resolution_service import (
                    resolve_po_from_document, attempt_bc_link, requires_po_resolution, PO_REQUIRED_DOC_TYPES
                )
                refreshed_doc = await self.db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
                if refreshed_doc and requires_po_resolution(refreshed_doc.get("document_type", "")):
                    po_result = await resolve_po_from_document(refreshed_doc)
                    bc_link_result = await attempt_bc_link(doc_id, po_result)
                    po_result["bc_link"] = bc_link_result
                    await self.db.hub_documents.update_one(
                        {"id": doc_id},
                        {"$set": {
                            "po_resolution": po_result,
                            "po_candidates": po_result.get("candidates_raw", []),
                            "updated_utc": utcnow(),
                        }}
                    )
                    logger.info(
                        "[AutoResolve:W%d] PO resolution for %s: status=%s po=%s bc_link=%s",
                        worker_id, doc_id[:8],
                        po_result.get("status"), po_result.get("po_number"),
                        bc_link_result.get("status"),
                    )
            except Exception as pre:
                logger.warning("[AutoResolve:W%d] PO resolution error: %s", worker_id, str(pre))

            # ---------------------------------------------------------
            # AUTO-POST AP INVOICES (stable vendors with linked POs)
            # Wires existing services: check_auto_post_eligibility,
            # stable_vendor_routing, po_resolution, and
            # auto_create_pi_from_document.
            # Never blocks pipeline — all errors caught and logged.
            # ---------------------------------------------------------
            try:
                from services.auto_post_service import check_auto_post_eligibility
                from routers.gpi_integration import auto_create_pi_from_document
                from services.automation_helpers import create_activity

                ap_doc = await self.db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
                if ap_doc:
                    doc_type = ap_doc.get("document_type") or ""

                    if doc_type in ("AP_Invoice", "AP Invoice"):
                        # Stable vendor score check
                        sv_routing = ap_doc.get("stable_vendor_routing") or {}
                        vendor_score = sv_routing.get("vendor_score", 0)

                        # PO → BC link status check
                        po_res = ap_doc.get("po_resolution") or {}
                        bc_link = po_res.get("bc_link") or {}
                        bc_link_status = bc_link.get("status", "")

                        # check_auto_post_eligibility expects 'doc_type' key
                        elig_doc = {**ap_doc, "doc_type": doc_type}
                        eligible, elig_reason = await check_auto_post_eligibility(elig_doc)

                        if eligible and vendor_score >= 0.85 and bc_link_status == "linked":
                            logger.info(
                                "[AutoResolve:W%d] Auto-post eligible for %s "
                                "(vendor_score=%.2f, bc_link=%s)",
                                worker_id, doc_id[:8], vendor_score, bc_link_status,
                            )
                            try:
                                result = await auto_create_pi_from_document(doc_id, self.db)

                                if result.get("success"):
                                    await self.db.hub_documents.update_one(
                                        {"id": doc_id},
                                        {"$set": {
                                            "auto_posted": True,
                                            "auto_post_result": result,
                                            "auto_post_at": utcnow(),
                                            "updated_utc": utcnow(),
                                        }},
                                    )
                                    await create_activity(
                                        self.db, doc_id, "document",
                                        "auto_post_success",
                                        title="Auto-posted to BC",
                                        body=f"Purchase invoice created: {result.get('bc_record_no', 'N/A')}",
                                        metadata=result,
                                    )
                                    logger.info(
                                        "[AutoResolve:W%d] Auto-post SUCCESS for %s: %s",
                                        worker_id, doc_id[:8], result.get("bc_record_no"),
                                    )
                                else:
                                    await self.db.hub_documents.update_one(
                                        {"id": doc_id},
                                        {"$set": {
                                            "auto_post_failed": True,
                                            "auto_post_error": result.get("reason", "unknown"),
                                            "auto_post_result": result,
                                            "updated_utc": utcnow(),
                                        }},
                                    )
                                    await create_activity(
                                        self.db, doc_id, "document",
                                        "auto_post_failed",
                                        title="Auto-post failed",
                                        body=f"Reason: {result.get('reason', 'unknown')}",
                                        metadata=result,
                                    )
                                    logger.warning(
                                        "[AutoResolve:W%d] Auto-post FAILED for %s: %s",
                                        worker_id, doc_id[:8], result.get("reason"),
                                    )
                            except Exception as ap_exec_err:
                                await self.db.hub_documents.update_one(
                                    {"id": doc_id},
                                    {"$set": {
                                        "auto_post_failed": True,
                                        "auto_post_error": str(ap_exec_err),
                                        "updated_utc": utcnow(),
                                    }},
                                )
                                await create_activity(
                                    self.db, doc_id, "document",
                                    "auto_post_error",
                                    title="Auto-post exception",
                                    body=str(ap_exec_err),
                                )
                                logger.error(
                                    "[AutoResolve:W%d] Auto-post exception for %s: %s",
                                    worker_id, doc_id[:8], str(ap_exec_err),
                                )
                        else:
                            logger.debug(
                                "[AutoResolve:W%d] Auto-post skip for %s: "
                                "eligible=%s vendor_score=%.2f bc_link=%s reason=%s",
                                worker_id, doc_id[:8], eligible,
                                vendor_score, bc_link_status, elig_reason,
                            )
            except Exception as auto_post_err:
                logger.warning(
                    "[AutoResolve:W%d] Auto-post check error: %s",
                    worker_id, str(auto_post_err),
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
                        "updated_utc": utcnow()
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
                        "updated_utc": utcnow()
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

    # =================================================================
    # AP VALIDATION STEP
    # =================================================================
    
    # Document types eligible for AP validation
    AP_VALIDATION_DOC_TYPES = {
        "AP_Invoice", "AP Invoice",
        "Freight_Invoice", "Freight Invoice", "Freight",
        "Carrier_Invoice", "Carrier Invoice",
    }
    
    # Document types that MAY be AP-validated conditionally
    AP_VALIDATION_CONDITIONAL_TYPES = {
        "Shipping_Document", "Shipping Document",
        "BOL", "Bill_of_Lading", "Bill of Lading",
    }
    
    VALIDATION_VERSION = "2.0.0"

    async def _run_ap_validation(self, doc_id: str, worker_id: int):
        """
        Run APValidationService for a document.
        
        This is the authoritative validation step. It:
        1. Checks document-type gating
        2. Checks idempotency (skip if unchanged)
        3. Runs validation consuming existing intelligence
        4. Stores normalized result on document
        5. Updates derived state
        6. Emits validation events
        """
        doc = await self.db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        if not doc:
            return
        
        doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
        
        # Document-type gating
        eligible = doc_type in self.AP_VALIDATION_DOC_TYPES
        if not eligible and doc_type in self.AP_VALIDATION_CONDITIONAL_TYPES:
            # Conditional: only if document looks like an AP payable
            has_amount = doc.get("amount_float") is not None
            has_vendor = bool(doc.get("vendor_canonical") or doc.get("vendor_normalized"))
            eligible = has_amount and has_vendor
        
        if not eligible:
            return
        
        # Idempotency: skip if data unchanged and version matches
        existing_val = doc.get("ap_validation_result") or {}
        if existing_val.get("validation_version") == self.VALIDATION_VERSION:
            # Check if inputs changed
            prev_hash = existing_val.get("input_hash")
            current_hash = self._compute_validation_hash(doc)
            if prev_hash == current_hash:
                logger.debug("[AutoResolve:W%d] AP validation skipped for %s (unchanged)", worker_id, doc_id[:8])
                return
        
        # Emit validation.started
        await self._emit("validation.started", doc_id, payload={
            "document_type": doc_type,
            "validation_version": self.VALIDATION_VERSION,
        })
        
        try:
            # Build vendor match result from existing document data
            vendor_match_result = self._build_vendor_match(doc)
            
            # Build extracted fields from document
            extracted_fields = doc.get("extracted_fields") or {}
            # Merge in flat normalized fields
            if doc.get("invoice_number_clean"):
                extracted_fields.setdefault("invoice_number", doc["invoice_number_clean"])
            if doc.get("invoice_date"):
                extracted_fields.setdefault("invoice_date", doc["invoice_date"])
            if doc.get("amount_float") is not None:
                extracted_fields.setdefault("amount", doc["amount_float"])
            if doc.get("vendor_raw"):
                extracted_fields.setdefault("vendor", doc["vendor_raw"])
            if doc.get("po_number_clean"):
                extracted_fields.setdefault("po_number", doc["po_number_clean"])
            
            # Run AP validation
            result = await self._ap_validation_service.validate_ap_invoice(
                document=doc,
                extracted_fields=extracted_fields,
                vendor_match_result=vendor_match_result,
            )
            
            result_dict = result.to_dict()
            
            # Add metadata
            input_hash = self._compute_validation_hash(doc)
            result_dict["validation_version"] = self.VALIDATION_VERSION
            result_dict["input_hash"] = input_hash
            result_dict["validation_source"] = "auto_resolution_pipeline"
            
            # Add freight GL info as a warning if direction unknown
            freight_gl = doc.get("freight_gl_classification") or {}
            if freight_gl.get("is_freight") and freight_gl.get("direction") == "unknown":
                result.add_warning(
                    "freight_direction_unknown",
                    "Freight direction could not be determined"
                )
                # Recompute state with the new warning
                result.compute_final_state()
                result_dict = result.to_dict()
                result_dict["validation_version"] = self.VALIDATION_VERSION
                result_dict["input_hash"] = input_hash
                result_dict["validation_source"] = "auto_resolution_pipeline"
            
            # Add reference intelligence warnings
            ref_intel = doc.get("reference_intelligence") or {}
            if ref_intel.get("match_outcome") == "ambiguous_match":
                result.add_warning(
                    "ambiguous_reference",
                    "Reference resolution found ambiguous matches"
                )
                result.compute_final_state()
                result_dict = result.to_dict()
                result_dict["validation_version"] = self.VALIDATION_VERSION
                result_dict["input_hash"] = input_hash
                result_dict["validation_source"] = "auto_resolution_pipeline"
            
            # Determine derived states
            v_state = result_dict["validation_state"]
            workflow_state = "reviewing"
            automation_state = "manual"
            
            if v_state == "pass":
                workflow_state = "ready"
                automation_state = "assisted"
            elif v_state == "warning":
                workflow_state = "reviewing"
                automation_state = "assisted"
            elif v_state == "fail":
                workflow_state = "needs_review"
                automation_state = "manual"
            
            # Store on document
            update = {
                "ap_validation_result": result_dict,
                "validation_state": v_state,
                "validation_passed": v_state in ("pass", "warning"),
                "validation_errors": result_dict.get("blocking_issues", []),
                "validation_warnings": [w.get("details", str(w)) if isinstance(w, dict) else str(w) for w in result_dict.get("warnings", [])],
                "validation_summary": self._build_validation_summary(result_dict),
                "validation_version": self.VALIDATION_VERSION,
                "validation_last_run": utcnow(),
                "derived_workflow_state": workflow_state,
                "derived_automation_state": automation_state,
                "updated_utc": utcnow(),
            }
            
            await self.db.hub_documents.update_one({"id": doc_id}, {"$set": update})
            
            # Emit validation.completed
            await self._emit("validation.completed", doc_id, payload={
                "document_type": doc_type,
                "validation_state": v_state,
                "all_passed": result_dict.get("all_passed", False),
                "blocking_issues_count": len(result_dict.get("blocking_issues", [])),
                "warnings_count": len(result_dict.get("warnings", [])),
                "vendor_resolved": result_dict.get("vendor_resolved", False),
                "invoice_number_present": result_dict.get("invoice_number_present", False),
                "invoice_date_present": result_dict.get("invoice_date_present", False),
                "total_amount_present": result_dict.get("total_amount_present", False),
                "is_duplicate": result_dict.get("is_duplicate", False),
            })
            
            # Emit warning event if applicable
            if v_state == "warning":
                await self._emit("validation.warning_detected", doc_id, payload={
                    "document_type": doc_type,
                    "warnings": [w.get("details", str(w)) if isinstance(w, dict) else str(w) for w in result_dict.get("warnings", [])],
                })
            
            logger.info(
                "[AutoResolve:W%d] AP validated %s → %s (blocking=%d, warnings=%d)",
                worker_id, doc_id[:8], v_state,
                len(result_dict.get("blocking_issues", [])),
                len(result_dict.get("warnings", []))
            )
            
        except Exception as e:
            logger.error("[AutoResolve:W%d] AP validation failed for %s: %s", worker_id, doc_id[:8], str(e))
            await self._emit("validation.failed", doc_id, status="error", payload={
                "document_type": doc_type,
                "error": str(e),
            })

    def _build_vendor_match(self, doc: Dict) -> Optional[Dict]:
        """Build a vendor match result dict from document fields."""
        vendor_no = doc.get("matched_vendor_no") or doc.get("vendor_id")
        vendor_name = doc.get("matched_vendor_name") or doc.get("vendor_canonical")
        match_method = doc.get("vendor_match_method") or doc.get("match_method")
        match_score = doc.get("match_score", 0.0)
        
        # Also check unified_vendor_match
        uvm = doc.get("unified_vendor_match") or {}
        if not vendor_no and uvm.get("bc_vendor_number"):
            vendor_no = uvm["bc_vendor_number"]
            vendor_name = uvm.get("best_match", {}).get("name") or vendor_name
            match_method = uvm.get("source") or match_method
            match_score = uvm.get("score", 0.0)
        
        if vendor_no:
            return {
                "matched": True,
                "bc_vendor_number": vendor_no,
                "best_match": {"vendor_number": vendor_no, "name": vendor_name},
                "source": match_method or "cache",
                "score": match_score,
            }
        elif vendor_name:
            return {"matched": False, "vendor_raw": vendor_name}
        return None

    def _compute_validation_hash(self, doc: Dict) -> str:
        """Compute hash of fields that affect validation."""
        import hashlib
        parts = [
            doc.get("vendor_canonical") or doc.get("vendor_normalized") or "",
            doc.get("matched_vendor_no") or "",
            doc.get("invoice_number_clean") or "",
            doc.get("invoice_date") or "",
            str(doc.get("amount_float") or ""),
            str(doc.get("possible_duplicate") or ""),
            doc.get("document_type") or "",
        ]
        raw = "|".join(parts)
        return hashlib.sha256(raw.encode()).hexdigest()[:16]

    def _build_validation_summary(self, result: Dict) -> str:
        """Build a human-readable validation summary."""
        state = result.get("validation_state", "pending")
        checks_passed = sum(1 for c in result.get("checks", []) if c.get("passed"))
        checks_total = len(result.get("checks", []))
        warnings_count = len(result.get("warnings", []))
        
        if state == "pass":
            return f"Validated: {checks_passed}/{checks_total} checks passed"
        elif state == "warning":
            return f"Validated with {warnings_count} warning(s): {checks_passed}/{checks_total} checks passed"
        elif state == "fail":
            failed = [c.get("check_name", "?") for c in result.get("checks", []) if not c.get("passed")]
            return f"Validation failed: {', '.join(failed)}"
        return "Validation pending"


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
