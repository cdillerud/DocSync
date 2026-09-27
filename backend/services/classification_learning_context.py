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
"""

from __future__ import annotations

import logging
from typing import Any, Dict, Optional, Tuple

logger = logging.getLogger("classification_learning_context")


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
                profile_used = True
                vep_hints = []
                ref_pri = profile.get("reference_priority")
                if ref_pri:
                    vep_hints.append(
                        f"For vendor '{effective_vendor}', the PO/reference number is typically "
                        f"found in: {', '.join(ref_pri)}."
                    )
                doc_bias = profile.get("doc_type_bias")
                if doc_bias and doc_bias != "unknown":
                    vep_hints.append(
                        f"This vendor most commonly sends: {doc_bias}."
                    )
                label_bias = profile.get("label_bias")
                if label_bias:
                    for predicted, hint in label_bias.items():
                        target = hint.get("target_label", "")
                        if target:
                            vep_hints.append(
                                f"When you see '{predicted}' on this vendor's docs, "
                                f"it usually refers to: {target}."
                            )
                if vep_hints:
                    dynamic_prompt += (
                        "\n\n== VENDOR EXTRACTION PROFILE (learned from historical data) ==\n"
                        + "\n".join(vep_hints)
                    )
                    logger.info(
                        "[%s] Injected VEP hints for %s (%d hints)",
                        log_prefix, effective_vendor, len(vep_hints),
                    )
    except Exception as e:
        logger.debug("[%s] VEP lookup failed (non-blocking): %s", log_prefix, e)

    # 1. Few-shot examples from classification corrections + vendor type hints
    try:
        from services.classification_feedback_service import (
            build_few_shot_prompt_section,
            build_vendor_hints_prompt_section,
        )
        few_shot = await build_few_shot_prompt_section(vendor_no=vendor_id)
        if few_shot:
            dynamic_prompt += "\n" + few_shot
            logger.info("[%s] Injected %d chars of few-shot examples", log_prefix, len(few_shot))

        if vendor_name:
            vendor_hint = await build_vendor_hints_prompt_section(vendor_name)
            if vendor_hint:
                dynamic_prompt += "\n" + vendor_hint
                logger.info("[%s] Injected vendor type hint for %s", log_prefix, vendor_name)
    except Exception as e:
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
            dynamic_prompt += "\n\n" + feedback_context
            logger.info(
                "[%s] Injected %d chars of feedback loop context for vendor=%s",
                log_prefix, len(feedback_context), effective_vendor,
            )
    except Exception as e:
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
            dynamic_prompt += "\n\n" + classification_ctx
            logger.info(
                "[%s] Injected %d chars of BC classification intelligence",
                log_prefix, len(classification_ctx),
            )
    except Exception as e:
        logger.debug("[%s] Classification context injection failed: %s", log_prefix, e)

    # 4. Deep Learning: Extraction pattern hints — learned field expectations per vendor
    try:
        from services.deep_learning_engine import get_extraction_hints_for_vendor
        from deps import get_db
        hint_db = get_db()
        if effective_vendor:
            hints = await get_extraction_hints_for_vendor(hint_db, effective_vendor)
            if hints.get("reliable_fields") or hints.get("expected_fields"):
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
        logger.debug("[%s] Deep learning hint injection failed: %s", log_prefix, e)

    # 5. Amount Intelligence — learned typical amounts for validation
    try:
        from services.vendor_context_builder import build_amount_intelligence_context
        from deps import get_db
        amt_db = get_db()
        if effective_vendor:
            amt_context = await build_amount_intelligence_context(amt_db, effective_vendor)
            if amt_context:
                dynamic_prompt += "\n\n" + amt_context
                logger.info("[%s] Injected amount intelligence for %s", log_prefix, effective_vendor)
    except Exception as e:
        logger.debug("[%s] Amount intelligence injection failed: %s", log_prefix, e)

    # 6. Field Correlation Predictions — learned field->doc_type rules
    try:
        from services.advanced_learning_engine import get_field_predictions
        from deps import get_db
        corr_db = get_db()
        pred_doc = {"extracted_fields": doc.get("extracted_fields") or {}}
        predictions = await get_field_predictions(corr_db, pred_doc)
        if predictions:
            corr_text = "\n\n## FIELD CORRELATION PREDICTIONS (learned rules):\n"
            for pred in predictions[:3]:
                corr_text += (
                    f"- When '{pred['feature']}' is present -> likely {pred['predicts']} "
                    f"({pred['confidence']:.0%} confidence, {pred['samples']} samples)\n"
                )
            corr_text += "Consider these patterns when classifying this document.\n"
            dynamic_prompt += corr_text
            logger.info("[%s] Injected %d field correlation predictions", log_prefix, len(predictions))
    except Exception as e:
        logger.debug("[%s] Field correlation injection failed: %s", log_prefix, e)

    return dynamic_prompt, profile_used
