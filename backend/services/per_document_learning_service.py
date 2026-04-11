"""
Per-Document Intelligence Engine — Learn from EVERY single document.

Called at the end of every document's processing lifecycle:
  ingestion, classification, validation, approval, rejection,
  auto-file, bc-post, field-edit, manual-link.

Six learning dimensions:
  1. OUTCOME RECORDING — success/failure/partial with full context
  2. VENDOR INTELLIGENCE — real-time per-vendor accuracy tracking
  3. CONFIDENCE CALIBRATION — AI confidence vs actual outcome gap
  4. POSITIVE REINFORCEMENT — successes reinforce patterns
  5. VALIDATION GAP ANALYSIS — WHY high confidence fails validation
  6. EXTRACTION ACCURACY — per-field, per-vendor accuracy tracking
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

logger = logging.getLogger("per_doc_learning")

# Outcome types
OUTCOME_AUTO_VALIDATED = "auto_validated"
OUTCOME_AUTO_FILED = "auto_filed"
OUTCOME_NEEDS_REVIEW = "needs_review"
OUTCOME_BLOCKED = "blocked"
OUTCOME_APPROVED = "approved"
OUTCOME_REJECTED = "rejected"
OUTCOME_POSTED_BC = "posted_to_bc"
OUTCOME_LINKED = "linked"
OUTCOME_FIELD_CORRECTED = "field_corrected"
OUTCOME_RECLASSIFIED = "reclassified"

COLLECTION = "document_outcomes"
VENDOR_INTEL_COLLECTION = "vendor_realtime_intelligence"
CONFIDENCE_CAL_COLLECTION = "confidence_calibration"
VALIDATION_GAP_COLLECTION = "validation_gap_log"
FIELD_ACCURACY_COLLECTION = "field_accuracy_tracking"


def _now():
    return datetime.now(timezone.utc).isoformat()


def compute_effective_confidence(doc: Dict) -> float:
    """
    Adjust raw AI classification confidence based on extraction completeness.

    Problem: AI may report 85% confidence on classification, but extract 0/6 fields.
    This inflates the 85-95% confidence band with docs that always fail.

    Fix: Penalize the confidence proportional to extraction gaps so these docs
    land in a lower (more honest) band.

    Returns the adjusted effective confidence (0.0–1.0).
    """
    ai_conf = float(doc.get("ai_confidence") or doc.get("classification_confidence") or 0)
    if ai_conf == 0:
        return 0.0

    extracted = doc.get("extracted_fields") or {}

    # Check core required fields
    has_vendor = bool(extracted.get("vendor"))
    has_invoice = bool(extracted.get("invoice_number"))
    has_amount = bool(
        extracted.get("amount") or extracted.get("invoice_amount") or extracted.get("total_amount")
    )
    has_date = bool(extracted.get("invoice_date") or extracted.get("date"))

    # Also check if vendor was resolved (a strong signal)
    vendor_resolved = bool(
        doc.get("vendor_canonical")
        or doc.get("bc_vendor_number")
        or (doc.get("vendor_resolution") or {}).get("status") == "resolved"
    )

    core_fields = [has_vendor, has_invoice, has_amount, has_date]
    core_present = sum(core_fields)
    core_total = len(core_fields)
    completeness = core_present / core_total  # 0.0 to 1.0

    # If extraction is >= 50% complete, no penalty
    if completeness >= 0.5:
        return ai_conf

    # Scale factor: ranges from 0.35 (0% extraction) to 1.0 (50% extraction)
    # At 0% extraction: effective = ai_conf * 0.35 → 85% becomes ~30%
    # At 25% extraction: effective = ai_conf * 0.675 → 85% becomes ~57%
    scale = 0.35 + 0.65 * (completeness / 0.5)

    # Small bonus if vendor was resolved despite poor extraction
    if vendor_resolved and not has_vendor:
        scale = min(1.0, scale + 0.15)

    return round(ai_conf * scale, 4)


def _classify_outcome(doc: Dict, trigger: str) -> str:
    """Determine the document's outcome category."""
    status = (doc.get("status") or "").lower()
    decision = (doc.get("automation_decision") or "").lower()

    if trigger in ("approval", "approve"):
        return OUTCOME_APPROVED
    if trigger == "rejection":
        return OUTCOME_REJECTED
    if trigger == "bc_post":
        return OUTCOME_POSTED_BC
    if trigger == "field_edit":
        return OUTCOME_FIELD_CORRECTED
    if trigger in ("reclassify", "reclassification"):
        return OUTCOME_RECLASSIFIED
    if trigger in ("link", "manual_link"):
        return OUTCOME_LINKED

    if doc.get("auto_cleared"):
        return OUTCOME_AUTO_FILED
    if decision == "auto_link" or status in ("readytolink", "completed"):
        return OUTCOME_AUTO_VALIDATED
    if status in ("needsreview",):
        return OUTCOME_NEEDS_REVIEW
    if status in ("exception", "blocked"):
        return OUTCOME_BLOCKED

    return OUTCOME_NEEDS_REVIEW


def _extract_validation_failures(doc: Dict) -> List[Dict]:
    """Extract which validation checks failed and why."""
    vr = doc.get("validation_results") or {}
    checks = vr.get("checks") or []
    failures = []
    for c in checks:
        if isinstance(c, dict) and not c.get("passed", True):
            failures.append({
                "check": c.get("check_name", "unknown"),
                "reason": c.get("message", c.get("details", "")),
                "required": c.get("required", False),
            })
    return failures


def _get_vendor_info(doc: Dict) -> Dict:
    """Extract vendor identifiers from the document."""
    return {
        "vendor_no": doc.get("bc_vendor_number") or doc.get("vendor_no") or doc.get("matched_vendor_no") or "",
        "vendor_name": doc.get("vendor_canonical") or (doc.get("extracted_fields") or {}).get("vendor") or "",
    }


# =========================================================================
# 1. OUTCOME RECORDING
# =========================================================================

async def _record_outcome(db, doc: Dict, trigger: str, outcome: str):
    """Store the document's processing outcome for historical analysis."""
    doc_id = doc.get("id", "")
    vendor = _get_vendor_info(doc)
    confidence = doc.get("ai_confidence") or 0.0
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
    validation_failures = _extract_validation_failures(doc)

    record = {
        "doc_id": doc_id,
        "trigger": trigger,
        "outcome": outcome,
        "doc_type": doc_type,
        "vendor_no": vendor["vendor_no"],
        "vendor_name": vendor["vendor_name"],
        "ai_confidence": confidence,
        "classification_method": doc.get("classification_method") or "",
        "automation_decision": doc.get("automation_decision") or "",
        "status": doc.get("status") or "",
        "validation_passed": len(validation_failures) == 0,
        "validation_failures": validation_failures,
        "validation_failure_count": len(validation_failures),
        "had_vendor_match": bool(vendor["vendor_no"]),
        "had_po_match": bool(doc.get("po_number_clean") or (doc.get("extracted_fields") or {}).get("po_number")),
        "auto_cleared": doc.get("auto_cleared", False),
        "recorded_at": _now(),
    }

    # Upsert by doc_id + trigger to avoid duplicates on re-processing
    await db[COLLECTION].update_one(
        {"doc_id": doc_id, "trigger": trigger},
        {"$set": record},
        upsert=True,
    )
    return record


# =========================================================================
# 2. REAL-TIME VENDOR INTELLIGENCE
# =========================================================================

async def _update_vendor_intelligence(db, doc: Dict, outcome: str):
    """Update the vendor's real-time intelligence profile from this document."""
    vendor = _get_vendor_info(doc)
    vendor_no = vendor["vendor_no"]
    if not vendor_no:
        return

    is_success = outcome in (OUTCOME_AUTO_VALIDATED, OUTCOME_AUTO_FILED, OUTCOME_APPROVED, OUTCOME_POSTED_BC, OUTCOME_LINKED)
    is_failure = outcome in (OUTCOME_BLOCKED, OUTCOME_REJECTED)
    is_correction = outcome in (OUTCOME_FIELD_CORRECTED, OUTCOME_RECLASSIFIED)

    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
    confidence = doc.get("ai_confidence") or 0.0

    inc_ops = {
        "total_documents": 1,
        "total_confidence_sum": confidence,
    }

    if is_success:
        inc_ops["success_count"] = 1
    elif is_failure:
        inc_ops["failure_count"] = 1
    elif is_correction:
        inc_ops["correction_count"] = 1
    else:
        inc_ops["review_count"] = 1

    # Track per-doc-type counters
    if doc_type:
        safe_type = doc_type.replace(".", "_").replace("$", "_")
        inc_ops[f"by_type.{safe_type}.total"] = 1
        if is_success:
            inc_ops[f"by_type.{safe_type}.success"] = 1

    set_ops = {
        "vendor_no": vendor_no,
        "vendor_name": vendor["vendor_name"],
        "last_document_at": _now(),
        "last_outcome": outcome,
    }

    await db[VENDOR_INTEL_COLLECTION].update_one(
        {"vendor_no": vendor_no},
        {"$inc": inc_ops, "$set": set_ops},
        upsert=True,
    )

    # Recompute derived rates
    profile = await db[VENDOR_INTEL_COLLECTION].find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    if profile:
        total = profile.get("total_documents", 1)
        success = profile.get("success_count", 0)
        corrections = profile.get("correction_count", 0)
        conf_sum = profile.get("total_confidence_sum", 0)

        auto_rate = round(success / max(total, 1), 4)
        correction_rate = round(corrections / max(total, 1), 4)
        avg_confidence = round(conf_sum / max(total, 1), 4)
        confidence_gap = round(avg_confidence - auto_rate, 4)

        await db[VENDOR_INTEL_COLLECTION].update_one(
            {"vendor_no": vendor_no},
            {"$set": {
                "auto_validation_rate": auto_rate,
                "correction_rate": correction_rate,
                "avg_confidence": avg_confidence,
                "confidence_to_validation_gap": confidence_gap,
                "rates_updated_at": _now(),
            }}
        )

    logger.info(
        "[PerDocLearn] Vendor intel: %s outcome=%s (total=%d)",
        vendor_no, outcome, (profile or {}).get("total_documents", 1),
    )


# =========================================================================
# 3. CONFIDENCE CALIBRATION
# =========================================================================

async def _calibrate_confidence(db, doc: Dict, outcome: str):
    """Track confidence vs reality — are we over-confident or under-confident?
    
    Uses EFFECTIVE confidence (adjusted for extraction quality) to assign bands,
    so docs with high classification confidence but poor extraction get placed
    in lower bands where they actually belong.
    """
    raw_confidence = doc.get("ai_confidence") or 0.0
    if raw_confidence == 0:
        return

    # Use effective confidence for band assignment
    confidence = compute_effective_confidence(doc)
    if confidence == 0:
        return

    is_correct = outcome in (OUTCOME_AUTO_VALIDATED, OUTCOME_AUTO_FILED, OUTCOME_APPROVED, OUTCOME_POSTED_BC, OUTCOME_LINKED)

    # Bucket effective confidence into bands
    if confidence < 0.50:
        band = "0_50"
    elif confidence < 0.70:
        band = "50_70"
    elif confidence < 0.85:
        band = "70_85"
    elif confidence < 0.95:
        band = "85_95"
    else:
        band = "95_100"

    vendor = _get_vendor_info(doc)
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""

    # Global calibration
    inc_ops = {
        f"bands.{band}.total": 1,
    }
    if is_correct:
        inc_ops[f"bands.{band}.correct"] = 1
    else:
        inc_ops[f"bands.{band}.incorrect"] = 1

    await db[CONFIDENCE_CAL_COLLECTION].update_one(
        {"calibration_id": "global"},
        {"$inc": inc_ops, "$set": {"updated_at": _now()}},
        upsert=True,
    )

    # Per-vendor calibration
    if vendor["vendor_no"]:
        await db[CONFIDENCE_CAL_COLLECTION].update_one(
            {"calibration_id": f"vendor_{vendor['vendor_no']}"},
            {
                "$inc": inc_ops,
                "$set": {
                    "vendor_no": vendor["vendor_no"],
                    "vendor_name": vendor["vendor_name"],
                    "updated_at": _now(),
                },
            },
            upsert=True,
        )

    # Per-doc-type calibration
    if doc_type:
        safe_type = doc_type.replace(".", "_").replace("$", "_")
        await db[CONFIDENCE_CAL_COLLECTION].update_one(
            {"calibration_id": f"type_{safe_type}"},
            {
                "$inc": inc_ops,
                "$set": {"doc_type": doc_type, "updated_at": _now()},
            },
            upsert=True,
        )


# =========================================================================
# 4. POSITIVE REINFORCEMENT
# =========================================================================

async def _reinforce_positive(db, doc: Dict, outcome: str):
    """When outcome is positive, reinforce ALL the patterns that led to it."""
    if outcome not in (OUTCOME_AUTO_VALIDATED, OUTCOME_AUTO_FILED, OUTCOME_APPROVED, OUTCOME_POSTED_BC, OUTCOME_LINKED):
        return

    doc_id = doc.get("id", "")
    vendor = _get_vendor_info(doc)
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""

    # 1. Reinforce classification (record as positive confirmation)
    if doc_type and doc_type not in ("Unknown", "Unknown_Document"):
        try:
            from services.classification_feedback_service import record_confirmation, _build_doc_context
            await record_confirmation(
                doc_id=doc_id,
                confirmed_type=doc_type,
                confirmation_source=f"outcome_{outcome}",
                doc_context=_build_doc_context(doc),
            )
        except Exception as e:
            logger.debug("[PerDocLearn] Classification reinforcement skipped: %s", e)

    # 2. Reinforce vendor alias mapping
    vendor_name = vendor["vendor_name"]
    vendor_no = vendor["vendor_no"]
    if vendor_name and vendor_no:
        normalized = vendor_name.strip().lower().replace(",", "").replace(".", "").replace("  ", " ").strip()
        await db.vendor_aliases.update_one(
            {"normalized_alias": normalized},
            {
                "$set": {
                    "canonical_name": vendor_name,
                    "vendor_no": vendor_no,
                    "last_confirmed_at": _now(),
                    "source": "positive_outcome",
                },
                "$inc": {"confirmation_count": 1},
            },
        )

    # 3. Reinforce extraction patterns — store successful extraction as a template
    extracted = doc.get("extracted_fields") or {}
    if vendor_no and extracted:
        meaningful_fields = {k: v for k, v in extracted.items()
                            if v and k not in ("_vendor_canonical", "vendor_inferred_by", "line_items")
                            and not k.startswith("_")}
        if meaningful_fields:
            await db.vendor_extraction_successes.update_one(
                {"vendor_no": vendor_no},
                {
                    "$inc": {"success_count": 1},
                    "$set": {
                        "last_successful_fields": list(meaningful_fields.keys()),
                        "last_success_at": _now(),
                        "doc_type": doc_type,
                    },
                    "$addToSet": {
                        "confirmed_field_names": {"$each": list(meaningful_fields.keys())},
                    },
                },
                upsert=True,
            )

    # 4. Reinforce posting template confidence (if vendor has one)
    if vendor_no and outcome in (OUTCOME_POSTED_BC, OUTCOME_APPROVED):
        await db.posting_pattern_analysis.update_one(
            {"vendor_no": vendor_no, "status": "analyzed"},
            {"$inc": {"positive_outcome_count": 1},
             "$set": {"last_positive_outcome_at": _now()}},
        )

    logger.info("[PerDocLearn] Positive reinforcement: doc=%s vendor=%s outcome=%s", doc_id[:12], vendor_no, outcome)


# =========================================================================
# 5. VALIDATION GAP ANALYSIS
# =========================================================================

async def _analyze_validation_gap(db, doc: Dict, outcome: str):
    """When high confidence + failed validation, record WHY."""
    confidence = doc.get("ai_confidence") or 0.0
    if confidence < 0.80:
        return  # Only care about the gap for high-confidence docs

    if outcome in (OUTCOME_AUTO_VALIDATED, OUTCOME_AUTO_FILED, OUTCOME_POSTED_BC):
        return  # No gap — things worked

    failures = _extract_validation_failures(doc)
    if not failures:
        return  # No specific failures to learn from

    vendor = _get_vendor_info(doc)
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""

    gap_record = {
        "doc_id": doc.get("id", ""),
        "vendor_no": vendor["vendor_no"],
        "vendor_name": vendor["vendor_name"],
        "doc_type": doc_type,
        "ai_confidence": confidence,
        "outcome": outcome,
        "validation_failures": failures,
        "failure_checks": [f["check"] for f in failures],
        "recorded_at": _now(),
    }

    await db[VALIDATION_GAP_COLLECTION].insert_one(gap_record)

    # Update per-vendor gap summary
    if vendor["vendor_no"]:
        for f in failures:
            check_name = f["check"].replace(".", "_").replace("$", "_")
            await db[VENDOR_INTEL_COLLECTION].update_one(
                {"vendor_no": vendor["vendor_no"]},
                {
                    "$inc": {f"gap_analysis.{check_name}": 1},
                    "$set": {f"gap_last_seen.{check_name}": _now()},
                },
            )

    logger.info(
        "[PerDocLearn] Validation gap: doc=%s conf=%.2f outcome=%s failures=%s",
        doc.get("id", "")[:12], confidence, outcome, [f["check"] for f in failures],
    )


# =========================================================================
# 6. EXTRACTION ACCURACY TRACKING
# =========================================================================

async def _track_extraction_accuracy(db, doc: Dict, outcome: str):
    """Track per-field extraction accuracy from validation results."""
    vendor = _get_vendor_info(doc)
    vendor_no = vendor["vendor_no"]
    if not vendor_no:
        return

    vr = doc.get("validation_results") or {}
    checks = vr.get("checks") or []

    for check in checks:
        if not isinstance(check, dict):
            continue
        check_name = check.get("check_name", "")
        passed = check.get("passed", True)

        # Map check names to field names
        field_map = {
            "vendor_check": "vendor",
            "vendor_match": "vendor",
            "po_check": "po_number",
            "po_validation": "po_number",
            "po_match": "po_number",
            "amount_check": "amount",
            "amount_validation": "amount",
            "date_check": "invoice_date",
            "duplicate_check": "invoice_number",
        }

        field_name = field_map.get(check_name, "")
        if not field_name:
            continue

        safe_field = field_name.replace(".", "_").replace("$", "_")

        inc_ops = {f"fields.{safe_field}.total": 1}
        if passed:
            inc_ops[f"fields.{safe_field}.correct"] = 1
        else:
            inc_ops[f"fields.{safe_field}.incorrect"] = 1

        await db[FIELD_ACCURACY_COLLECTION].update_one(
            {"vendor_no": vendor_no},
            {
                "$inc": inc_ops,
                "$set": {
                    "vendor_no": vendor_no,
                    "vendor_name": vendor["vendor_name"],
                    "updated_at": _now(),
                },
            },
            upsert=True,
        )

    # Recompute per-field accuracy rates
    profile = await db[FIELD_ACCURACY_COLLECTION].find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    if profile and profile.get("fields"):
        for field_name, counts in profile["fields"].items():
            total = counts.get("total", 0)
            correct = counts.get("correct", 0)
            if total > 0:
                await db[FIELD_ACCURACY_COLLECTION].update_one(
                    {"vendor_no": vendor_no},
                    {"$set": {f"fields.{field_name}.accuracy": round(correct / total, 4)}},
                )


# =========================================================================
# MASTER FUNCTION — Called after EVERY document event
# =========================================================================

async def learn_from_document(db, doc_id: str, trigger: str = "ingestion"):
    """
    The master learning function. Called after every document event.
    Extracts all learning signals from the document's current state.

    trigger: ingestion, classification, validation, approval, rejection,
             auto_file, bc_post, field_edit, link, reclassify, reprocess
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        logger.warning("[PerDocLearn] Document not found: %s", doc_id)
        return {"learned": False, "reason": "doc_not_found"}

    outcome = _classify_outcome(doc, trigger)

    results = {
        "doc_id": doc_id,
        "trigger": trigger,
        "outcome": outcome,
        "dimensions": {},
    }

    # Run all 6 dimensions in sequence (fast, no external API calls)
    try:
        await _record_outcome(db, doc, trigger, outcome)
        results["dimensions"]["outcome"] = "ok"
    except Exception as e:
        results["dimensions"]["outcome"] = f"error: {e}"
        logger.warning("[PerDocLearn] Outcome recording failed: %s", e)

    try:
        await _update_vendor_intelligence(db, doc, outcome)
        results["dimensions"]["vendor_intel"] = "ok"
    except Exception as e:
        results["dimensions"]["vendor_intel"] = f"error: {e}"
        logger.warning("[PerDocLearn] Vendor intelligence failed: %s", e)

    try:
        await _calibrate_confidence(db, doc, outcome)
        results["dimensions"]["confidence_cal"] = "ok"
    except Exception as e:
        results["dimensions"]["confidence_cal"] = f"error: {e}"
        logger.warning("[PerDocLearn] Confidence calibration failed: %s", e)

    try:
        await _reinforce_positive(db, doc, outcome)
        results["dimensions"]["reinforcement"] = "ok"
    except Exception as e:
        results["dimensions"]["reinforcement"] = f"error: {e}"
        logger.warning("[PerDocLearn] Positive reinforcement failed: %s", e)

    try:
        await _analyze_validation_gap(db, doc, outcome)
        results["dimensions"]["gap_analysis"] = "ok"
    except Exception as e:
        results["dimensions"]["gap_analysis"] = f"error: {e}"
        logger.warning("[PerDocLearn] Validation gap analysis failed: %s", e)

    try:
        await _track_extraction_accuracy(db, doc, outcome)
        results["dimensions"]["extraction_accuracy"] = "ok"
    except Exception as e:
        results["dimensions"]["extraction_accuracy"] = f"error: {e}"
        logger.warning("[PerDocLearn] Extraction accuracy tracking failed: %s", e)

    logger.info(
        "[PerDocLearn] doc=%s trigger=%s outcome=%s dims=%s",
        doc_id[:12], trigger, outcome,
        {k: "ok" if v == "ok" else "err" for k, v in results["dimensions"].items()},
    )

    # === DEEP LEARNING: Run all 5 advanced engines ===
    try:
        from services.deep_learning_engine import run_deep_learning
        deep_results = await run_deep_learning(db, doc_id, trigger)
        results["deep_learning"] = deep_results
    except Exception as e:
        results["deep_learning"] = {"error": str(e)}
        logger.debug("[PerDocLearn] Deep learning for %s: %s", doc_id[:8], e)

    # === ADVANCED LEARNING: Run all 7 intelligence engines ===
    try:
        from services.advanced_learning_engine import run_advanced_learning
        adv_results = await run_advanced_learning(db, doc_id, trigger)
        results["advanced_learning"] = adv_results
    except Exception as e:
        results["advanced_learning"] = {"error": str(e)}
        logger.debug("[PerDocLearn] Advanced learning for %s: %s", doc_id[:8], e)

    # === DUPLICATE INTELLIGENCE: Learn from duplicate flag outcomes ===
    try:
        was_flagged = bool(doc.get("possible_duplicate") or doc.get("is_duplicate"))
        if was_flagged:
            vendor = _get_vendor_info(doc)
            from services.duplicate_intelligence_service import record_duplicate_outcome
            if outcome in (OUTCOME_APPROVED, OUTCOME_POSTED_BC, OUTCOME_LINKED, OUTCOME_AUTO_FILED):
                # Document succeeded despite duplicate flag — false positive
                await record_duplicate_outcome(
                    db, doc_id, vendor["vendor_no"],
                    was_flagged_duplicate=True,
                    actual_outcome="false_positive",
                    resolution_source=f"outcome_{outcome}",
                )
                results["dimensions"]["duplicate_intel"] = "false_positive"
            elif outcome == OUTCOME_REJECTED:
                # Document rejected — could be confirmed duplicate
                await record_duplicate_outcome(
                    db, doc_id, vendor["vendor_no"],
                    was_flagged_duplicate=True,
                    actual_outcome="confirmed_duplicate",
                    resolution_source=f"outcome_{outcome}",
                )
                results["dimensions"]["duplicate_intel"] = "confirmed"
        else:
            results["dimensions"]["duplicate_intel"] = "not_flagged"
    except Exception as e:
        results["dimensions"]["duplicate_intel"] = f"error: {e}"
        logger.debug("[PerDocLearn] Duplicate intelligence for %s: %s", doc_id[:8], e)

    # === ESCALATION INTELLIGENCE: Learn which vendor+doc_type combos fail ===
    # IMPORTANT: Only record escalation for genuine new outcomes (ingestion, correction),
    # NOT for re-evaluations/backfills which would create a death spiral of escalation
    try:
        if trigger not in ("backfill", "reevaluation", "recalibration"):
            vendor = _get_vendor_info(doc)
            doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
            if vendor["vendor_no"] and doc_type:
                from services.escalation_intelligence_service import record_automation_outcome
                if outcome in (OUTCOME_AUTO_VALIDATED, OUTCOME_AUTO_FILED, OUTCOME_POSTED_BC, OUTCOME_LINKED):
                    esc_outcome = "success"
                elif outcome in (OUTCOME_BLOCKED, OUTCOME_REJECTED):
                    esc_outcome = "failure"
                elif outcome == OUTCOME_FIELD_CORRECTED:
                    esc_outcome = "correction"
                else:
                    esc_outcome = "review"
                await record_automation_outcome(db, vendor["vendor_no"], doc_type, esc_outcome, doc_id)
                results["dimensions"]["escalation_intel"] = esc_outcome
        else:
            results["dimensions"]["escalation_intel"] = "skipped_backfill"
    except Exception as e:
        results["dimensions"]["escalation_intel"] = f"error: {e}"
        logger.debug("[PerDocLearn] Escalation intelligence for %s: %s", doc_id[:8], e)

    return results


# =========================================================================
# QUERY APIs — Expose learning intelligence
# =========================================================================

async def get_learning_pulse(db) -> Dict:
    """Real-time pulse of how the AI is learning — global stats."""
    # Total outcomes
    total = await db[COLLECTION].count_documents({})
    by_outcome_pipeline = [
        {"$group": {"_id": "$outcome", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    by_outcome = {r["_id"]: r["count"] for r in await db[COLLECTION].aggregate(by_outcome_pipeline).to_list(20)}

    # Global confidence calibration
    cal = await db[CONFIDENCE_CAL_COLLECTION].find_one(
        {"calibration_id": "global"}, {"_id": 0}
    )
    bands = {}
    if cal and cal.get("bands"):
        for band_name, counts in cal["bands"].items():
            t = counts.get("total", 0)
            c = counts.get("correct", 0)
            bands[band_name] = {
                "total": t,
                "correct": c,
                "accuracy": round(c / max(t, 1), 4),
            }

    # Top vendors by learning volume
    top_vendors_pipeline = [
        {"$sort": {"total_documents": -1}},
        {"$limit": 10},
        {"$project": {
            "_id": 0, "vendor_no": 1, "vendor_name": 1,
            "total_documents": 1, "success_count": 1,
            "auto_validation_rate": 1, "correction_rate": 1,
            "avg_confidence": 1, "confidence_to_validation_gap": 1,
        }},
    ]
    top_vendors = await db[VENDOR_INTEL_COLLECTION].aggregate(top_vendors_pipeline).to_list(10)

    # Validation gap hot spots — query hub_documents directly (source of truth)
    # Only count BLOCKING gaps (required != False) on active documents
    gap_pipeline = [
        {"$match": {
            "validation_results.checks": {"$exists": True},
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        }},
        {"$unwind": "$validation_results.checks"},
        {"$match": {
            "validation_results.checks.passed": False,
            "validation_results.checks.required": {"$ne": False},
        }},
        {"$group": {"_id": "$validation_results.checks.check_name", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    gap_hotspots = [{"check": r["_id"], "count": r["count"]}
                    for r in await db.hub_documents.aggregate(gap_pipeline).to_list(10)]

    # Recent learning events
    recent = await db[COLLECTION].find(
        {}, {"_id": 0, "doc_id": 1, "trigger": 1, "outcome": 1, "vendor_no": 1, "ai_confidence": 1, "recorded_at": 1}
    ).sort("recorded_at", -1).limit(20).to_list(20)

    return {
        "total_documents_learned_from": total,
        "outcomes": by_outcome,
        "confidence_calibration": bands,
        "top_vendors": top_vendors,
        "validation_gap_hotspots": gap_hotspots,
        "recent_learning": recent,
        "generated_at": _now(),
    }


async def get_vendor_learning_profile(db, vendor_no: str) -> Optional[Dict]:
    """Get complete learning profile for a specific vendor."""
    intel = await db[VENDOR_INTEL_COLLECTION].find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )
    if not intel:
        return None

    # Get field accuracy
    accuracy = await db[FIELD_ACCURACY_COLLECTION].find_one(
        {"vendor_no": vendor_no}, {"_id": 0}
    )

    # Get confidence calibration
    cal = await db[CONFIDENCE_CAL_COLLECTION].find_one(
        {"calibration_id": f"vendor_{vendor_no}"}, {"_id": 0}
    )

    # Get recent validation gaps — from hub_documents (source of truth)
    vendor_gap_pipeline = [
        {"$match": {
            "$or": [{"bc_vendor_number": vendor_no}, {"vendor_no": vendor_no}],
            "validation_results.checks": {"$exists": True},
            "status": {"$nin": ["Completed", "Posted", "Deleted", "Archived"]},
        }},
        {"$unwind": "$validation_results.checks"},
        {"$match": {
            "validation_results.checks.passed": False,
            "validation_results.checks.required": {"$ne": False},
        }},
        {"$project": {
            "_id": 0,
            "doc_id": "$id",
            "check_name": "$validation_results.checks.check_name",
            "message": "$validation_results.checks.message",
            "created_utc": 1,
        }},
        {"$sort": {"created_utc": -1}},
        {"$limit": 10},
    ]
    gaps = await db.hub_documents.aggregate(vendor_gap_pipeline).to_list(10)

    # Get recent outcomes
    outcomes = await db[COLLECTION].find(
        {"vendor_no": vendor_no}, {"_id": 0}
    ).sort("recorded_at", -1).limit(20).to_list(20)

    return {
        "vendor_no": vendor_no,
        "intelligence": intel,
        "field_accuracy": accuracy,
        "confidence_calibration": cal,
        "recent_gaps": gaps,
        "recent_outcomes": outcomes,
    }


async def get_confidence_calibration_report(db) -> Dict:
    """Full confidence calibration report — how well-calibrated is the AI?"""
    all_cals = await db[CONFIDENCE_CAL_COLLECTION].find(
        {}, {"_id": 0}
    ).to_list(500)

    global_cal = None
    vendor_cals = []
    type_cals = []

    for cal in all_cals:
        cid = cal.get("calibration_id", "")
        if cid == "global":
            global_cal = cal
        elif cid.startswith("vendor_"):
            vendor_cals.append(cal)
        elif cid.startswith("type_"):
            type_cals.append(cal)

    return {
        "global": global_cal,
        "by_vendor": sorted(vendor_cals, key=lambda x: x.get("vendor_no", "")),
        "by_doc_type": type_cals,
        "generated_at": _now(),
    }
