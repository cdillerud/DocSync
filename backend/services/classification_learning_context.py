"""
GPI Document Hub - Classification Learning Context

Single shared source for every learned-intelligence signal that gets layered
onto a classification/extraction system prompt: vendor extraction profiles,
few-shot correction examples, vendor type hints, feedback-loop context, BC
entity-distribution intelligence, deep-learning extraction-pattern hints,
amount intelligence, and field-correlation predictions.

Extracted 2026-09-27 from classification_pipeline.stage_classify_llm, which
had this logic but only runs on-demand (/api/document-intelligence/{id}/process
and manual reprocess scripts) — never on documents as they actually arrive.
document_intel_helpers._call_llm_for_extraction (the live intake path every
inbound document hits) had a much thinner copy of the same idea (few-shot +
basic feedback context only, no doc context to look up an already-known
vendor). Both now call this one function instead of keeping their own
copies, so the two paths cannot drift apart the way duplicated learning code
has everywhere else in this codebase.

Every injection block is independently best-effort: a failure in any one
source (missing collection, service import error, etc.) is caught and
logged at debug level, never blocks classification.

2026-09-28: added self-instrumentation (record_injection_event). The VEP
block silently returned "used" with zero actual hints injected for months
(wrong field names, fixed the same day this was added) because nothing
tracked whether each source actually fired — only debug-level logs nobody
watched. Every call now writes one best-effort event to
learning_injection_events recording which of the 8 sources fired, found
nothing, or errored, so a regression like that shows up in
get_injection_health_summary() instead of staying invisible for 6 months.
"""

from __future__ import annotations

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("classification_learning_context")

# Every source tracked in the health summary, in injection order. Keep this
# in sync with the block labels used below and in record_injection_event.
SOURCES = (
    "vep", "few_shot", "vendor_hint", "feedback_loop",
    "bc_intelligence", "deep_learning", "amount_intelligence",
    "field_correlation",
)


async def build_learning_enriched_prompt(
    base_prompt: str,
    doc: Optional[Dict[str, Any]] = None,
    log_prefix: str = "LEARNING",
) -> Tuple[str, bool]:
    """Layer every learned-intelligence signal onto a classification prompt.

    Args:
        base_prompt: the starting system prompt (e.g. _CLASSIFY_SYSTEM_PROMPT).
        doc: whatever is already known about this document — vendor_no,
             vendor_canonical/vendor_raw, suggested_job_type/doc_type,
             sender_email/email_sender, file_name, extracted_fields. All
             optional; every field defaults to "unknown" gracefully.
        log_prefix: tag for log lines, so callers can tell which code path
             (live intake vs on-demand pipeline) produced them.

    Returns:
        (enriched_prompt, profile_used) — profile_used is True when a
        Vendor Extraction Profile was found and injected, for callers that
        want to record it (classification_pipeline stores it on StageResult).
    """
    doc = doc or {}
    dynamic_prompt = base_prompt
    profile_used = False
    # One of "fired" | "empty" | "error:<ExceptionClassName>" per source,
    # populated as each block runs below. See record_injection_event.
    status: Dict[str, str] = {s: "empty" for s in SOURCES}

    vendor_id = doc.get("vendor_no") or doc.get("vendor_id") or doc.get("matched_vendor_no") or ""
    vendor_name = doc.get("vendor_canonical") or doc.get("vendor_raw") or ""
    existing_doc_type = doc.get("suggested_job_type") or doc.get("doc_type") or ""
    sender_email = doc.get("sender_email") or doc.get("email_sender") or ""

    if not vendor_name:
        try:
            from services.vendor_inference_service import infer_vendor
            file_name = doc.get("file_name") or ""
            inferred, _ = infer_vendor(file_name)
            if inferred:
                vendor_name = inferred
                vendor_id = vendor_id or inferred
        except Exception:
            pass

    effective_vendor = vendor_id or vendor_name

    logger.info(
        "[%s] Preparing prompt — vendor_id=%s vendor_name=%s doc_type=%s",
        log_prefix,
        vendor_id[:20] if vendor_id else "(none)",
        vendor_name[:20] if vendor_name else "(none)",
        existing_doc_type or "(none)",
    )

    # 0. Vendor Extraction Profile — adaptive hints from historical data
    try:
        from services.vendor_extraction_profile_service import get_vep_service
        vep_svc = get_vep_service()
        if vep_svc and effective_vendor:
            profile = await vep_svc.get_profile(effective_vendor)
            if profile and profile.get("enabled"):
                vep_hints = []
                # NOTE: the profile's actual stored/returned keys are
                # reference_priority_order / document_type_bias /
                # reference_label_bias (see vendor_extraction_profile_service
                # .get_profile / .get_resolver_adjustments) -- this previously
                # read reference_priority / doc_type_bias / label_bias, which
                # never existed on any stored profile, so this whole 552-profile
                # signal was silently a no-op everywhere it was wired in.
                ref_pri = profile.get("reference_priority_order")
                if ref_pri:
                    vep_hints.append(
                        f"For vendor '{effective_vendor}', the PO/reference number is typically "
                        f"found in: {', '.join(ref_pri)}."
                    )
                doc_bias = profile.get("document_type_bias")
                if doc_bias and doc_bias != "unknown":
                    vep_hints.append(
                        f"This vendor most commonly sends: {doc_bias}."
                    )
                label_bias = profile.get("reference_label_bias")
                if label_bias:
                    for predicted, hint in label_bias.items():
                        target = hint.get("target_label", "")
                        if target:
                            vep_hints.append(
                                f"When you see '{predicted}' on this vendor's docs, "
                                f"it usually refers to: {target}."
                            )
                if vep_hints:
                    profile_used = True
                    status["vep"] = "fired"
                    dynamic_prompt += (
                        "\n\n== VENDOR EXTRACTION PROFILE (learned from historical data) ==\n"
                        + "\n".join(vep_hints)
                    )
                    logger.info(
                        "[%s] Injected VEP hints for %s (%d hints)",
                        log_prefix, effective_vendor, len(vep_hints),
                    )
    except Exception as e:
        status["vep"] = f"error:{type(e).__name__}"
        logger.debug("[%s] VEP lookup failed (non-blocking): %s", log_prefix, e)

    # 1. Few-shot examples from classification corrections + vendor type hints
    try:
        from services.classification_feedback_service import (
            build_few_shot_prompt_section,
            build_vendor_hints_prompt_section,
        )
        few_shot = await build_few_shot_prompt_section(vendor_no=vendor_id)
        if few_shot:
            status["few_shot"] = "fired"
            dynamic_prompt += "\n" + few_shot
            logger.info("[%s] Injected %d chars of few-shot examples", log_prefix, len(few_shot))

        if vendor_name:
            vendor_hint = await build_vendor_hints_prompt_section(vendor_name)
            if vendor_hint:
                status["vendor_hint"] = "fired"
                dynamic_prompt += "\n" + vendor_hint
                logger.info("[%s] Injected vendor type hint for %s", log_prefix, vendor_name)
    except Exception as e:
        err = f"error:{type(e).__name__}"
        if status["few_shot"] == "empty":
            status["few_shot"] = err
        if status["vendor_hint"] == "empty":
            status["vendor_hint"] = err
        logger.debug("[%s] Classification feedback injection failed: %s", log_prefix, e)

    # 2. Feedback loop context — learned corrections from user interactions
    try:
        from services.feedback_loop_service import build_feedback_context_for_prompt
        from deps import get_db
        feedback_db = get_db()
        feedback_context = await build_feedback_context_for_prompt(
            feedback_db,
            vendor_id=effective_vendor,
            doc_type=existing_doc_type,
        )
        if feedback_context:
            status["feedback_loop"] = "fired"
            dynamic_prompt += "\n\n" + feedback_context
            logger.info(
                "[%s] Injected %d chars of feedback loop context for vendor=%s",
                log_prefix, len(feedback_context), effective_vendor,
            )
    except Exception as e:
        status["feedback_loop"] = f"error:{type(e).__name__}"
        logger.debug("[%s] Feedback loop injection failed: %s", log_prefix, e)

    # 3. BC-powered classification intelligence — entity distribution + domain hints
    try:
        from services.vendor_context_builder import build_classification_context
        from deps import get_db
        ctx_db = get_db()
        classification_ctx = await build_classification_context(
            ctx_db,
            vendor_no=vendor_id,
            vendor_name=vendor_name,
            sender_email=sender_email,
        )
        if classification_ctx:
            status["bc_intelligence"] = "fired"
            dynamic_prompt += "\n\n" + classification_ctx
            logger.info(
                "[%s] Injected %d chars of BC classification intelligence",
                log_prefix, len(classification_ctx),
            )
    except Exception as e:
        status["bc_intelligence"] = f"error:{type(e).__name__}"
        logger.debug("[%s] Classification context injection failed: %s", log_prefix, e)

    # 4. Deep Learning: Extraction pattern hints — learned field expectations per vendor
    try:
        from services.deep_learning_engine import get_extraction_hints_for_vendor
        from deps import get_db
        hint_db = get_db()
        if effective_vendor:
            hints = await get_extraction_hints_for_vendor(hint_db, effective_vendor)
            if hints.get("reliable_fields") or hints.get("expected_fields"):
                status["deep_learning"] = "fired"
                hint_text = "\n\n## LEARNED EXTRACTION PATTERNS (from previous documents):\n"
                if hints.get("reliable_fields"):
                    hint_text += f"Fields ALWAYS present for this vendor: {', '.join(hints['reliable_fields'])}\n"
                if hints.get("expected_fields"):
                    hint_text += f"Fields SOMETIMES present: {', '.join(hints['expected_fields'])}\n"
                if hints.get("line_item_expectations"):
                    le = hints["line_item_expectations"]
                    hint_text += f"Typical line items: ~{le.get('typical_count', 'unknown')} items"
                    if le.get("usually_has_amounts"):
                        hint_text += " (with amounts)"
                    hint_text += "\n"
                hint_text += "Use these patterns to guide your extraction — look for these fields specifically.\n"
                dynamic_prompt += hint_text
                logger.info("[%s] Injected deep learning extraction hints for %s", log_prefix, effective_vendor)
    except Exception as e:
        status["deep_learning"] = f"error:{type(e).__name__}"
        logger.debug("[%s] Deep learning hint injection failed: %s", log_prefix, e)

    # 5. Amount Intelligence — learned typical amounts for validation
    try:
        from services.vendor_context_builder import build_amount_intelligence_context
        from deps import get_db
        amt_db = get_db()
        if effective_vendor:
            amt_context = await build_amount_intelligence_context(amt_db, effective_vendor)
            if amt_context:
                status["amount_intelligence"] = "fired"
                dynamic_prompt += "\n\n" + amt_context
                logger.info("[%s] Injected amount intelligence for %s", log_prefix, effective_vendor)
    except Exception as e:
        status["amount_intelligence"] = f"error:{type(e).__name__}"
        logger.debug("[%s] Amount intelligence injection failed: %s", log_prefix, e)

    # 6. Field Correlation Predictions — learned field->doc_type rules
    try:
        from services.advanced_learning_engine import get_field_predictions
        from deps import get_db
        corr_db = get_db()
        pred_doc = {"extracted_fields": doc.get("extracted_fields") or {}}
        predictions = await get_field_predictions(corr_db, pred_doc)
        if predictions:
            status["field_correlation"] = "fired"
            corr_text = "\n\n## FIELD CORRELATION PREDICTIONS (learned rules):\n"
            for pred in predictions[:3]:
                # get_field_predictions returns "predicted_type", not "predicts" --
                # this KeyError'd on every single call that found a real
                # correlation (i.e. whenever this signal had anything to say at
                # all), caught by the health endpoint's first live run.
                corr_text += (
                    f"- When '{pred['feature']}' is present -> likely {pred['predicted_type']} "
                    f"({pred['confidence']:.0%} confidence, {pred['samples']} samples)\n"
                )
            corr_text += "Consider these patterns when classifying this document.\n"
            dynamic_prompt += corr_text
            logger.info("[%s] Injected %d field correlation predictions", log_prefix, len(predictions))
    except Exception as e:
        status["field_correlation"] = f"error:{type(e).__name__}"
        logger.debug("[%s] Field correlation injection failed: %s", log_prefix, e)

    await _record_injection_event(log_prefix, effective_vendor, existing_doc_type, status)

    return dynamic_prompt, profile_used


async def _record_injection_event(
    log_prefix: str, vendor: str, doc_type: str, status: Dict[str, str],
) -> None:
    """Best-effort observability write -- never raises, never blocks classification.

    One document per classification/extraction call in learning_injection_events,
    so get_injection_health_summary() can answer "what fraction of documents in
    the last N hours actually got each of the 8 signals" instead of that only
    being visible as scattered INFO/DEBUG log lines nobody was watching.
    """
    try:
        from deps import get_db
        db = get_db()
        await db.learning_injection_events.insert_one({
            "id": str(uuid.uuid4()),
            "ts": datetime.now(timezone.utc).isoformat(),
            "log_prefix": log_prefix,
            "vendor": vendor or None,
            "doc_type": doc_type or None,
            "sources": dict(status),
        })
    except Exception as e:
        logger.debug("[%s] Injection event recording failed (non-blocking): %s", log_prefix, e)


async def get_injection_health_summary(hours: int = 24) -> Dict[str, Any]:
    """Aggregate recent learning_injection_events into a per-source firing rate.

    Answers the question "is each learning signal actually reaching real
    documents" without reading logs -- a fired_rate of 0 for a source that
    isn't consistently "no data yet" (e.g. it fires for some vendors but
    never any) is exactly the shape of bug that made the VEP signal a silent
    no-op for months.
    """
    from deps import get_db
    from datetime import timedelta

    db = get_db()
    since = (datetime.now(timezone.utc) - timedelta(hours=hours)).isoformat()

    events = await db.learning_injection_events.find(
        {"ts": {"$gte": since}}, {"_id": 0}
    ).to_list(20000)

    total = len(events)
    by_path: Dict[str, int] = {}
    counts = {s: {"fired": 0, "empty": 0, "error": 0} for s in SOURCES}
    error_samples: Dict[str, str] = {}

    for ev in events:
        by_path[ev.get("log_prefix", "?")] = by_path.get(ev.get("log_prefix", "?"), 0) + 1
        for source, outcome in (ev.get("sources") or {}).items():
            if source not in counts:
                continue
            if outcome == "fired":
                counts[source]["fired"] += 1
            elif outcome and outcome.startswith("error"):
                counts[source]["error"] += 1
                error_samples.setdefault(source, outcome)
            else:
                counts[source]["empty"] += 1

    per_source = {}
    for s in SOURCES:
        c = counts[s]
        per_source[s] = {
            "fired": c["fired"],
            "empty": c["empty"],
            "error": c["error"],
            "fired_rate": round(c["fired"] / total, 3) if total else None,
            "error_rate": round(c["error"] / total, 3) if total else None,
            "sample_error": error_samples.get(s),
        }

    return {
        "window_hours": hours,
        "total_events": total,
        "events_by_path": by_path,
        "sources": per_source,
    }
