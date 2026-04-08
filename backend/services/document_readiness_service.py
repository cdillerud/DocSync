"""
GPI Document Hub - Document Readiness Engine

The single authoritative workflow-state evaluator. Computes a canonical
readiness object per document that determines whether the document is
ready for auto-draft, auto-link, manual review, or is blocked.

Consumes:
  - vendor_resolution (from vendor matching pipeline)
  - policy engine output (automation_decision)
  - duplicate checks
  - extraction completeness
  - validation results
  - reviewer overrides

Produces:
  - readiness object (status, confidence, signals, reasons, actions)
  - becomes source of truth for queue categorization

Usage:
    from services.document_readiness_service import evaluate_readiness
    readiness = evaluate_readiness(doc)
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("document_readiness")


# ---------------------------------------------------------------------------
# Readiness statuses
# ---------------------------------------------------------------------------

STATUS_READY_AUTO_DRAFT = "ready_auto_draft"
STATUS_READY_AUTO_LINK = "ready_auto_link"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_BLOCKED = "blocked"
STATUS_AMBIGUOUS = "ambiguous"

# Recommended actions
ACTION_AUTO_DRAFT = "auto_draft"
ACTION_AUTO_LINK = "auto_link"
ACTION_REVIEW = "review"
ACTION_HOLD = "hold"


# ---------------------------------------------------------------------------
# Signal computation
# ---------------------------------------------------------------------------

def compute_signals(doc: Dict[str, Any]) -> Dict[str, bool]:
    """Compute 11 boolean readiness signals from document fields."""
    extracted = doc.get("extracted_fields") or {}
    vr = doc.get("vendor_resolution") or {}
    validation = doc.get("validation_results") or {}

    vendor_canonical = doc.get("vendor_canonical")
    vendor_resolved = bool(
        vendor_canonical
        or vr.get("status") == "resolved"
        or doc.get("vendor_match_method") in ("alias_match", "bc_exact_match", "fuzzy_match", "manual_match")
    )

    customer_canonical = doc.get("customer_canonical") or doc.get("customer_id")
    customer_resolved = bool(customer_canonical)

    po_number = (
        extracted.get("po_number")
        or doc.get("po_number_clean")
        or doc.get("po_number")
    )
    po_extracted = bool(po_number and str(po_number).strip())

    # For shipping-style docs, PO resolution against BC is the authoritative signal
    po_res = doc.get("po_resolution") or {}
    po_resolution_status = po_res.get("status", "")
    po_resolved_bc = po_resolution_status == "resolved"
    po_ambiguous = po_resolution_status == "ambiguous"

    # po_resolved = True if PO was resolved against BC, OR if we just have a PO number
    # for non-shipping docs (where BC PO match is not critical)
    from services.po_resolution_service import PO_REQUIRED_DOC_TYPES
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
    if doc_type in PO_REQUIRED_DOC_TYPES:
        # For shipping docs: require actual BC resolution, not just field presence
        po_resolved = po_resolved_bc
    else:
        # For non-shipping docs (e.g. AP_Invoice): start with field presence...
        po_resolved = po_extracted
        # ...but if BC validation explicitly failed the PO check, override to False
        bc_val = doc.get("bc_validation") or {}
        bc_checks = bc_val.get("checks") or []
        for chk in bc_checks:
            if chk.get("check_name") == "po_check" and chk.get("passed") is False:
                po_resolved = False
                break

    # Duplicate risk — check the actual BC validation duplicate check first.
    # The `possible_duplicate` flag is set during ingestion and can be stale
    # if a later BC validation explicitly confirmed "No duplicate found".
    duplicate_risk = False
    bc_val = doc.get("bc_validation") or {}
    bc_checks = bc_val.get("checks") or []
    bc_dup_check_ran = False
    for chk in bc_checks:
        if chk.get("check_name") == "duplicate_check":
            bc_dup_check_ran = True
            if not chk.get("passed"):
                duplicate_risk = True
            break
    # Only fall back to raw flags if BC validation didn't run a duplicate check
    if not bc_dup_check_ran:
        duplicate_risk = bool(doc.get("possible_duplicate") or doc.get("is_duplicate"))

    graph_linked = bool(
        doc.get("bc_document_id")
        or doc.get("linked_bc_id")
        or doc.get("bc_purchase_invoice_id")
        or doc.get("transaction_action") == "linked"
    )

    line_items = extracted.get("line_items") or []
    line_items_present = len(line_items) > 0

    # Line items confident if they have amounts/descriptions
    line_items_confident = False
    if line_items_present:
        valid_items = sum(
            1 for li in line_items
            if (li.get("amount") or li.get("unit_price") or li.get("total"))
            and (li.get("description") or li.get("item"))
        )
        line_items_confident = valid_items >= len(line_items) * 0.5

    # Required fields: vendor, invoice_number, amount
    required = ["vendor", "invoice_number"]
    amount_fields = ["amount", "invoice_amount", "total_amount"]
    has_amount = any(extracted.get(f) for f in amount_fields)
    has_required = all(extracted.get(f) for f in required) and has_amount
    required_fields_complete = has_required

    # Policy signals
    decision = doc.get("automation_decision") or ""
    policy_blocked = decision in ("blocked", "reject")
    policy_held = decision in ("hold", "needs_review", "manual")

    # AUTO-CLEAR stale policy holds: if key validation signals are all green,
    # the document shouldn't remain held just because the initial automation_decision
    # said "needs_review". The initial decision was made before vendor matching,
    # extraction, and validation completed. Re-evaluate based on current reality.
    if policy_held and not policy_blocked:
        all_green = (
            vendor_resolved
            and required_fields_complete
            and not duplicate_risk
        )
        if all_green:
            policy_held = False

    manually_overridden = bool(
        (vr.get("reviewed_override"))
        or doc.get("approved_by")
        or doc.get("manual_override")
    )

    return {
        "vendor_resolved": vendor_resolved,
        "customer_resolved": customer_resolved,
        "po_resolved": po_resolved,
        "duplicate_risk": duplicate_risk,
        "graph_linked": graph_linked,
        "line_items_present": line_items_present,
        "line_items_confident": line_items_confident,
        "required_fields_complete": required_fields_complete,
        "policy_blocked": policy_blocked,
        "policy_held": policy_held,
        "manually_overridden": manually_overridden,
    }


# ---------------------------------------------------------------------------
# Readiness evaluation (pure function)
# ---------------------------------------------------------------------------

def evaluate_readiness(doc: Dict[str, Any]) -> Dict[str, Any]:
    """Evaluate document readiness — the authoritative workflow-state decision.

    Returns a canonical readiness object.
    """
    signals = compute_signals(doc)

    # --- Short-circuit: already completed/auto-cleared docs ---
    # But NOT if the document has zero meaningful extracted data — that
    # indicates it was cleared incorrectly and should surface the real state.
    doc_status = (doc.get("status") or "").lower()
    workflow_status = (doc.get("workflow_status") or "").lower()
    is_terminal = (
        doc.get("auto_cleared")
        or doc_status in ("completed", "posted", "archived")
        or workflow_status in ("completed", "exported", "processed")
    )
    extracted = doc.get("extracted_fields") or {}
    meaningful_count = sum(
        1 for k, v in extracted.items()
        if v and not k.endswith("_detected_by")
    )
    if is_terminal and meaningful_count >= 1:
        return {
            "status": STATUS_READY_AUTO_LINK,
            "confidence": 1.0,
            "recommended_action": ACTION_AUTO_LINK,
            "blocking_reasons": [],
            "warning_reasons": [],
            "required_reviewer_actions": [],
            "explanations": ["Document already processed and completed"],
            "signals": signals,
            "last_evaluated_at": datetime.now(timezone.utc).isoformat(),
            "reviewed_override": signals.get("manually_overridden", False),
        }

    blocking: List[str] = []
    warnings: List[str] = []
    reviewer_actions: List[str] = []
    explanations: List[str] = []

    # --- Blocking reasons ---
    if signals["policy_blocked"]:
        blocking.append("policy_engine_blocked")
        explanations.append("Document blocked by automation policy")

    if signals["duplicate_risk"]:
        blocking.append("duplicate_risk")
        explanations.append("Possible duplicate detected")
        reviewer_actions.append("Verify this is not a duplicate")

    if not signals["required_fields_complete"]:
        blocking.append("missing_required_fields")
        missing = []
        extracted = doc.get("extracted_fields") or {}
        if not extracted.get("vendor"):
            missing.append("vendor")
        if not extracted.get("invoice_number"):
            missing.append("invoice_number")
        if not any(extracted.get(f) for f in ["amount", "invoice_amount", "total_amount"]):
            missing.append("amount")
        explanations.append(f"Missing required fields: {', '.join(missing)}")
        reviewer_actions.append(f"Provide missing fields: {', '.join(missing)}")

    if not signals["vendor_resolved"]:
        blocking.append("vendor_unresolved")
        explanations.append("Vendor not matched to Business Central")
        reviewer_actions.append("Resolve vendor match")

    # --- Warning reasons ---
    if signals["policy_held"]:
        warnings.append("policy_hold")
        explanations.append("Policy engine recommends manual review")

    if not signals["customer_resolved"] and doc.get("suggested_job_type") in ("Sales_Order", "Sales_Invoice"):
        warnings.append("customer_unresolved")
        explanations.append("Customer not matched for sales document")
        reviewer_actions.append("Resolve customer match")

    if not signals["po_resolved"]:
        warnings.append("po_missing")
        explanations.append("No PO number found for cross-reference")

    if not signals["line_items_present"]:
        warnings.append("no_line_items")
        explanations.append("No line items extracted")

    if signals["line_items_present"] and not signals["line_items_confident"]:
        warnings.append("low_line_item_confidence")
        explanations.append("Line items incomplete or low quality")

    # Check vendor resolution quality
    vr = doc.get("vendor_resolution") or {}
    vr_status = vr.get("status")
    if vr_status == "needs_review":
        warnings.append("vendor_needs_review")
        explanations.append("Vendor match is low-confidence, needs human review")
        reviewer_actions.append("Confirm or correct vendor match")

    # --- Confidence computation ---
    # Use effective confidence (adjusted for extraction quality) as the AI base
    from services.per_document_learning_service import compute_effective_confidence
    effective_conf = compute_effective_confidence(doc)
    confidence = _compute_confidence(signals, effective_conf, len(blocking), len(warnings))

    # --- Status determination ---
    if blocking:
        status = STATUS_BLOCKED
        action = ACTION_HOLD
    elif signals["manually_overridden"]:
        status = STATUS_READY_AUTO_DRAFT if signals["vendor_resolved"] else STATUS_NEEDS_REVIEW
        action = ACTION_AUTO_DRAFT if status == STATUS_READY_AUTO_DRAFT else ACTION_REVIEW
        explanations.append("Document was manually reviewed/overridden")
    elif signals["graph_linked"]:
        status = STATUS_READY_AUTO_LINK
        action = ACTION_AUTO_LINK
        explanations.append("Document already linked to BC record")
    elif len(warnings) >= 3:
        status = STATUS_AMBIGUOUS
        action = ACTION_REVIEW
        explanations.append("Multiple warnings require human evaluation")
    elif warnings and not signals["vendor_resolved"]:
        status = STATUS_NEEDS_REVIEW
        action = ACTION_REVIEW
    elif warnings:
        if (confidence or 0) >= 0.8:
            status = STATUS_READY_AUTO_DRAFT
            action = ACTION_AUTO_DRAFT
            explanations.append("High confidence despite minor warnings")
        else:
            status = STATUS_NEEDS_REVIEW
            action = ACTION_REVIEW
    else:
        # No blocking, no warnings
        if signals["vendor_resolved"] and signals["required_fields_complete"]:
            status = STATUS_READY_AUTO_DRAFT
            action = ACTION_AUTO_DRAFT
            explanations.append("All checks passed — ready for automatic processing")
        else:
            status = STATUS_NEEDS_REVIEW
            action = ACTION_REVIEW

    return {
        "status": status,
        "confidence": round(confidence, 3),
        "recommended_action": action,
        "blocking_reasons": blocking,
        "warning_reasons": warnings,
        "required_reviewer_actions": reviewer_actions,
        "explanations": explanations,
        "signals": signals,
        "last_evaluated_at": datetime.now(timezone.utc).isoformat(),
        "reviewed_override": signals["manually_overridden"],
    }


def _compute_confidence(signals: Dict[str, bool], ai_conf: float, n_blocking: int, n_warnings: int) -> float:
    """Compute overall readiness confidence 0.0–1.0."""
    score = ai_conf * 0.3  # Base from AI classification

    # Signal bonuses
    if signals["vendor_resolved"]:
        score += 0.20
    if signals["required_fields_complete"]:
        score += 0.20
    if signals["po_resolved"]:
        score += 0.05
    if signals["customer_resolved"]:
        score += 0.05
    if signals["line_items_present"]:
        score += 0.05
    if signals["line_items_confident"]:
        score += 0.05
    if signals["graph_linked"]:
        score += 0.10

    # Penalties
    if signals["duplicate_risk"]:
        score -= 0.25
    if signals["policy_blocked"]:
        score -= 0.30
    if signals["policy_held"]:
        score -= 0.10
    score -= n_warnings * 0.03

    return max(0.0, min(1.0, score))


# ---------------------------------------------------------------------------
# Async DB operations
# ---------------------------------------------------------------------------

async def evaluate_and_persist(doc_id: str) -> Dict[str, Any]:
    """Evaluate readiness for a document and persist the result.
    Also computes automation confidence and decision explanation.
    Detects signal contradictions that were corrected and records learning events."""
    from deps import get_db
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise ValueError(f"Document not found: {doc_id}")

    # Capture old readiness before re-evaluation
    old_readiness = doc.get("readiness") or {}
    old_signals = old_readiness.get("signals") or {}
    old_blocking = old_readiness.get("blocking_reasons") or []

    readiness = evaluate_readiness(doc)
    new_signals = readiness.get("signals") or {}
    new_blocking = readiness.get("blocking_reasons") or []

    # === GAP CLOSER 1: Confidence Band Awareness ===
    # If this doc's confidence band has low historical accuracy, route to review
    try:
        from services.gap_closer_service import get_confidence_band_accuracy, apply_confidence_awareness
        ai_confidence = doc.get("ai_confidence") or 0.0
        if ai_confidence > 0:
            band_check = await get_confidence_band_accuracy(db, ai_confidence, doc=doc)
            if band_check.get("should_review"):
                readiness = apply_confidence_awareness(readiness, band_check)
                logger.info(
                    "[GapCloser:ConfBand] doc=%s raw_conf=%.2f eff_band=%s accuracy=%.2f → routed to review",
                    doc_id[:8], ai_confidence, band_check["band"], band_check.get("accuracy", 0),
                )
    except Exception as gc_err:
        logger.debug("[GapCloser:ConfBand] Skipped for %s: %s", doc_id[:8], gc_err)

    # === GAP CLOSER 5: Duplicate Intelligence ===
    # If this doc is blocked by duplicate_risk but the vendor's duplicate
    # detection is known to be unreliable, auto-clear the flag.
    try:
        if readiness.get("signals", {}).get("duplicate_risk") and "duplicate_risk" in readiness.get("blocking_reasons", []):
            from services.duplicate_intelligence_service import evaluate_duplicate_flag
            dup_eval = await evaluate_duplicate_flag(db, doc)
            if dup_eval.get("should_auto_clear"):
                readiness["blocking_reasons"] = [
                    r for r in readiness["blocking_reasons"] if r != "duplicate_risk"
                ]
                readiness["signals"]["duplicate_risk"] = False
                readiness["warning_reasons"] = readiness.get("warning_reasons", []) + ["duplicate_intelligence_cleared"]
                readiness["explanations"] = readiness.get("explanations", []) + [
                    f"INTELLIGENCE: {dup_eval['reason']}"
                ]
                # Recalculate status if no more blockers
                if not readiness["blocking_reasons"]:
                    if readiness["signals"].get("vendor_resolved") and readiness["signals"].get("required_fields_complete"):
                        readiness["status"] = STATUS_READY_AUTO_DRAFT
                        readiness["recommended_action"] = ACTION_AUTO_DRAFT
                    else:
                        readiness["status"] = STATUS_NEEDS_REVIEW
                        readiness["recommended_action"] = ACTION_REVIEW
                logger.info(
                    "[GapCloser:DupIntel] doc=%s — duplicate flag auto-cleared (vendor FPR: %s)",
                    doc_id[:8], dup_eval.get("vendor_intel", {}).get("false_positive_rate", "?"),
                )
    except Exception as gc_err:
        logger.debug("[GapCloser:DupIntel] Skipped for %s: %s", doc_id[:8], gc_err)

    # === GAP CLOSER 6: Amount Anomaly Detection ===
    # If the document's amount is anomalous for this vendor, add a warning
    try:
        vendor_no_for_anomaly = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
        if vendor_no_for_anomaly:
            extracted_for_anomaly = doc.get("extracted_fields") or {}
            amount_val = 0.0
            for af in ["amount", "invoice_amount", "total_amount"]:
                val = extracted_for_anomaly.get(af)
                if val:
                    try:
                        amount_val = float(str(val).replace("$", "").replace(",", "").strip())
                        break
                    except (ValueError, TypeError):
                        pass
            if amount_val > 0:
                from services.advanced_learning_engine import check_amount_anomaly
                anomaly_check = await check_amount_anomaly(db, vendor_no_for_anomaly, amount_val)
                if anomaly_check.get("is_anomaly"):
                    severity = anomaly_check.get("severity", "medium")
                    readiness["warning_reasons"] = readiness.get("warning_reasons", []) + ["amount_anomaly"]
                    readiness["explanations"] = readiness.get("explanations", []) + [
                        f"INTELLIGENCE: Amount ${amount_val:,.2f} is anomalous for vendor {vendor_no_for_anomaly} "
                        f"(typical: ${anomaly_check.get('avg_amount', 0):,.2f} ± ${anomaly_check.get('stddev', 0):,.2f}, "
                        f"z-score: {anomaly_check.get('z_score', 0)}, severity: {severity})"
                    ]
                    # High-severity anomalies should force review
                    if severity == "high" and readiness["status"] in (STATUS_READY_AUTO_DRAFT, STATUS_READY_AUTO_LINK):
                        readiness["status"] = STATUS_NEEDS_REVIEW
                        readiness["recommended_action"] = ACTION_REVIEW
                    logger.info(
                        "[GapCloser:AmountAnomaly] doc=%s vendor=%s amount=%.2f z=%.1f severity=%s",
                        doc_id[:8], vendor_no_for_anomaly, amount_val,
                        anomaly_check.get("z_score", 0), severity,
                    )
    except Exception as gc_err:
        logger.debug("[GapCloser:AmountAnomaly] Skipped for %s: %s", doc_id[:8], gc_err)

    # === GAP CLOSER 7: Auto-Escalation Intelligence ===
    # If this vendor + doc_type consistently fails automation, pre-route to review
    try:
        vendor_no_for_esc = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
        doc_type_for_esc = doc.get("document_type") or doc.get("suggested_job_type") or ""
        if vendor_no_for_esc and doc_type_for_esc:
            from services.escalation_intelligence_service import should_pre_escalate
            esc_check = await should_pre_escalate(db, vendor_no_for_esc, doc_type_for_esc)
            if esc_check.get("should_escalate"):
                if readiness["status"] in (STATUS_READY_AUTO_DRAFT, STATUS_READY_AUTO_LINK):
                    readiness["status"] = STATUS_NEEDS_REVIEW
                    readiness["recommended_action"] = ACTION_REVIEW
                readiness["warning_reasons"] = readiness.get("warning_reasons", []) + ["auto_escalation"]
                readiness["explanations"] = readiness.get("explanations", []) + [
                    f"INTELLIGENCE: {esc_check['reason']}"
                ]
                logger.info(
                    "[GapCloser:Escalation] doc=%s — pre-escalated (success rate: %s)",
                    doc_id[:8], esc_check.get("success_rate", "?"),
                )
    except Exception as gc_err:
        logger.debug("[GapCloser:Escalation] Skipped for %s: %s", doc_id[:8], gc_err)

    # Compute automation intelligence alongside readiness
    from services.automation_intelligence_service import (
        compute_automation_confidence,
        build_decision_explanation,
    )
    from services.per_document_learning_service import compute_effective_confidence
    # Temporarily attach readiness so intelligence can read it
    doc["readiness"] = readiness
    auto_conf = compute_automation_confidence(doc)
    explanation = build_decision_explanation(doc)

    effective_conf = compute_effective_confidence(doc)
    raw_ai_conf = float(doc.get("ai_confidence") or 0)

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "readiness": readiness,
            "automation_confidence": auto_conf,
            "decision_explanation": explanation,
            "effective_confidence": effective_conf,
            "confidence_penalty_applied": round(raw_ai_conf - effective_conf, 4) if raw_ai_conf > effective_conf else 0,
            "updated_utc": readiness["last_evaluated_at"],
        }},
    )

    # Auto-clear stale automation_decision if policy hold was dropped
    old_held = old_signals.get("policy_held", False)
    new_held = new_signals.get("policy_held", False)
    if old_held and not new_held:
        old_decision = doc.get("automation_decision") or ""
        if old_decision in ("hold", "needs_review", "manual"):
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {"automation_decision": "auto_process"}},
            )
            logger.info(
                "[Readiness] Auto-cleared stale policy hold on %s (was '%s', all signals green)",
                doc_id[:8], old_decision,
            )

    # --- Learning: detect contradictions that were corrected ---
    corrections = []
    now = readiness["last_evaluated_at"]
    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""

    # Duplicate risk flipped from True to False (BC check overrode stale flag)
    if old_signals.get("duplicate_risk") and not new_signals.get("duplicate_risk"):
        corrections.append({
            "signal": "duplicate_risk",
            "old_value": True,
            "new_value": False,
            "reason": "BC validation duplicate check passed — cleared stale possible_duplicate flag",
        })

    # PO resolved flipped from True to False (BC check overrode field-only resolution)
    if old_signals.get("po_resolved") and not new_signals.get("po_resolved"):
        corrections.append({
            "signal": "po_resolved",
            "old_value": True,
            "new_value": False,
            "reason": "BC validation PO check failed — PO was extracted but not found in BC",
        })

    # PO resolved flipped from False to True
    if not old_signals.get("po_resolved") and new_signals.get("po_resolved"):
        corrections.append({
            "signal": "po_resolved",
            "old_value": False,
            "new_value": True,
            "reason": "PO now resolved after BC re-validation",
        })

    # Policy hold auto-cleared (all signals green, stale hold dropped)
    if old_signals.get("policy_held") and not new_signals.get("policy_held"):
        corrections.append({
            "signal": "policy_held",
            "old_value": True,
            "new_value": False,
            "reason": "readiness_self_correction",
        })

    # Blocking reasons removed
    removed_blockers = set(old_blocking) - set(new_blocking)
    for blocker in removed_blockers:
        corrections.append({
            "signal": f"blocker_{blocker}",
            "old_value": True,
            "new_value": False,
            "reason": f"Blocking reason '{blocker}' no longer applies after re-evaluation",
        })

    if corrections:
        await db.posting_learning_events.insert_one({
            "vendor_no": vendor_no,
            "doc_id": doc_id,
            "event_type": "readiness_contradiction_fix",
            "posted_at": now,
            "feedback": "self_correction",
            "corrections": corrections,
            "old_status": old_readiness.get("status", ""),
            "new_status": readiness.get("status", ""),
            "old_confidence": old_readiness.get("confidence", 0),
            "new_confidence": readiness.get("confidence", 0),
        })
        for c in corrections:
            await db.classification_corrections.insert_one({
                "doc_id": doc_id,
                "vendor_id": vendor_no,
                "correction_type": f"readiness_{c['signal']}",
                "original_type": str(c["old_value"]),
                "corrected_type": str(c["new_value"]),
                "source": "readiness_self_correction",
                "confirmed_at": now,
                "applied": True,
            })
        logger.info(
            "[Readiness] doc=%s self-corrected %d signal contradictions: %s",
            doc_id[:8], len(corrections),
            ", ".join(c["signal"] for c in corrections),
        )

    logger.info(
        "[Readiness] doc=%s status=%s confidence=%.2f auto_conf=%.2f action=%s blockers=%d warnings=%d",
        doc_id, readiness["status"], readiness["confidence"],
        auto_conf["score"],
        readiness["recommended_action"], len(readiness["blocking_reasons"]),
        len(readiness["warning_reasons"]),
    )
    return readiness


async def batch_evaluate(limit: int = 200) -> Dict[str, int]:
    """Evaluate readiness for documents that don't have it yet.
    Uses evaluate_and_persist for full learning integration."""
    from deps import get_db
    db = get_db()

    cursor = db.hub_documents.find(
        {"$or": [{"readiness": {"$exists": False}}, {"readiness": None}]},
        {"_id": 0, "id": 1},
    ).limit(limit)
    docs = await cursor.to_list(limit)

    counts = {STATUS_READY_AUTO_DRAFT: 0, STATUS_READY_AUTO_LINK: 0,
              STATUS_NEEDS_REVIEW: 0, STATUS_BLOCKED: 0, STATUS_AMBIGUOUS: 0,
              "errors": 0, "corrections": 0}
    for d in docs:
        try:
            r = await evaluate_and_persist(d["id"])
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        except Exception:
            counts["errors"] += 1

    return {"total": len(docs), **counts}


async def batch_reevaluate_all(limit: int = 5000) -> Dict[str, Any]:
    """
    Re-evaluate ALL documents (not just new ones).
    Detects and corrects signal contradictions across the entire dataset.
    Every correction feeds into the learning pipeline via evaluate_and_persist().

    Returns a detailed summary: status transitions, corrections found, per-vendor breakdown.
    """
    from deps import get_db
    db = get_db()

    # Prioritize stale policy-held docs first (the ones most likely to be stuck)
    held_cursor = db.hub_documents.find(
        {
            "is_duplicate": {"$ne": True},
            "automation_decision": {"$in": ["hold", "needs_review", "manual"]},
        },
        {"_id": 0, "id": 1, "readiness": 1, "bc_vendor_number": 1, "vendor_no": 1},
    )
    held_docs = await held_cursor.to_list(None)

    # Then get remaining docs up to the limit
    held_ids = {d["id"] for d in held_docs if d.get("id")}
    remaining_limit = max(limit - len(held_docs), 0)
    if remaining_limit > 0:
        other_cursor = db.hub_documents.find(
            {
                "is_duplicate": {"$ne": True},
                "id": {"$nin": list(held_ids)},
            },
            {"_id": 0, "id": 1, "readiness": 1, "bc_vendor_number": 1, "vendor_no": 1},
        ).limit(remaining_limit)
        other_docs = await other_cursor.to_list(remaining_limit)
    else:
        other_docs = []

    docs = held_docs + other_docs

    results = {
        "total_processed": 0,
        "total_corrections": 0,
        "status_transitions": [],
        "vendor_corrections": {},
        "by_status": {},
        "errors": 0,
        "error_details": [],
    }

    for d in docs:
        doc_id = d.get("id", "")
        if not doc_id:
            continue
        results["total_processed"] += 1

        old_readiness = d.get("readiness") or {}
        old_status = old_readiness.get("status", "none")
        old_signals = old_readiness.get("signals") or {}
        vendor_no = d.get("bc_vendor_number") or d.get("vendor_no") or ""

        try:
            new_readiness = await evaluate_and_persist(doc_id)
            new_status = new_readiness.get("status", "unknown")

            # Count by status
            results["by_status"][new_status] = results["by_status"].get(new_status, 0) + 1

            # Detect status transition
            if old_status != new_status:
                results["status_transitions"].append({
                    "doc_id": doc_id[:8],
                    "vendor_no": vendor_no,
                    "from": old_status,
                    "to": new_status,
                    "old_confidence": old_readiness.get("confidence", 0),
                    "new_confidence": new_readiness.get("confidence", 0),
                })

            # AUTO-ACT: If doc was promoted to a "ready" state, trigger auto-posting
            # This closes the gap where readiness says "Ready" but no action is taken.
            ready_statuses = ("ready_auto_link", "ready_auto_draft", "ready")
            was_not_ready = old_status not in ready_statuses
            is_now_ready = new_status in ready_statuses
            if (was_not_ready and is_now_ready) or (is_now_ready and not d.get("bc_purchase_invoice_no")):
                try:
                    doc_full = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
                    if doc_full and not doc_full.get("bc_purchase_invoice_no"):
                        doc_type = (doc_full.get("doc_type") or doc_full.get("suggested_job_type") or "").lower()
                        if "ap" in doc_type or "invoice" in doc_type:
                            from services.ap_auto_post_service import attempt_ap_auto_post
                            ap_result = await attempt_ap_auto_post(doc_id, db, source="reevaluation_auto_act")
                            if ap_result.get("posted") or ap_result.get("created"):
                                results["auto_acted"] = results.get("auto_acted", 0) + 1
                                logger.info(
                                    "[Reevaluate:AutoAct] doc=%s vendor=%s → auto-posted to BC",
                                    doc_id[:8], vendor_no,
                                )
                except Exception as act_err:
                    logger.warning("[Reevaluate:AutoAct] doc=%s error: %s", doc_id[:8], str(act_err))

            # Detect signal corrections
            new_signals = new_readiness.get("signals") or {}
            changed_signals = []
            for key in set(list(old_signals.keys()) + list(new_signals.keys())):
                old_val = old_signals.get(key)
                new_val = new_signals.get(key)
                if old_val != new_val:
                    changed_signals.append({"signal": key, "old": old_val, "new": new_val})

            if changed_signals:
                results["total_corrections"] += len(changed_signals)
                if vendor_no:
                    vc = results["vendor_corrections"].get(vendor_no, {"count": 0, "signals": []})
                    vc["count"] += len(changed_signals)
                    for cs in changed_signals:
                        vc["signals"].append(cs["signal"])
                    results["vendor_corrections"][vendor_no] = vc

        except Exception as e:
            results["errors"] += 1
            results["error_details"].append({"doc_id": doc_id[:8], "error": str(e)})

    # Convert vendor_corrections to sorted list
    vendor_list = [
        {"vendor_no": k, "correction_count": v["count"], "signals": list(set(v["signals"]))}
        for k, v in results["vendor_corrections"].items()
    ]
    vendor_list.sort(key=lambda x: x["correction_count"], reverse=True)
    results["vendor_corrections"] = vendor_list[:20]

    logger.info(
        "[Readiness] Batch re-evaluate: processed=%d, corrections=%d, transitions=%d, auto_acted=%d, errors=%d",
        results["total_processed"], results["total_corrections"],
        len(results["status_transitions"]), results.get("auto_acted", 0), results["errors"],
    )
    return results


# ---------------------------------------------------------------------------
# Metrics
# ---------------------------------------------------------------------------

async def get_readiness_metrics() -> Dict[str, Any]:
    """Compute readiness analytics."""
    from deps import get_db
    db = get_db()

    total = await db.hub_documents.count_documents({})

    # By status
    status_pipe = [
        {"$group": {"_id": "$readiness.status", "count": {"$sum": 1}}},
    ]
    status_raw = await db.hub_documents.aggregate(status_pipe).to_list(10)
    by_status = {r["_id"]: r["count"] for r in status_raw if r["_id"]}
    no_readiness = total - sum(by_status.values())

    # By action
    action_pipe = [
        {"$match": {"readiness.recommended_action": {"$exists": True, "$ne": None}}},
        {"$group": {"_id": "$readiness.recommended_action", "count": {"$sum": 1}}},
    ]
    action_raw = await db.hub_documents.aggregate(action_pipe).to_list(10)
    by_action = {r["_id"]: r["count"] for r in action_raw if r["_id"]}

    # Top blocking reasons
    block_pipe = [
        {"$match": {"readiness.blocking_reasons": {"$exists": True, "$ne": []}}},
        {"$unwind": "$readiness.blocking_reasons"},
        {"$group": {"_id": "$readiness.blocking_reasons", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 15},
    ]
    block_raw = await db.hub_documents.aggregate(block_pipe).to_list(15)
    top_blocking = [{"reason": r["_id"], "count": r["count"]} for r in block_raw if r["_id"]]

    # Top warning reasons
    warn_pipe = [
        {"$match": {"readiness.warning_reasons": {"$exists": True, "$ne": []}}},
        {"$unwind": "$readiness.warning_reasons"},
        {"$group": {"_id": "$readiness.warning_reasons", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 15},
    ]
    warn_raw = await db.hub_documents.aggregate(warn_pipe).to_list(15)
    top_warnings = [{"reason": r["_id"], "count": r["count"]} for r in warn_raw if r["_id"]]

    # Top reviewer actions
    action_req_pipe = [
        {"$match": {"readiness.required_reviewer_actions": {"$exists": True, "$ne": []}}},
        {"$unwind": "$readiness.required_reviewer_actions"},
        {"$group": {"_id": "$readiness.required_reviewer_actions", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 15},
    ]
    action_req_raw = await db.hub_documents.aggregate(action_req_pipe).to_list(15)
    top_reviewer_actions = [{"action": r["_id"], "count": r["count"]} for r in action_req_raw if r["_id"]]

    # Average confidence by status
    conf_pipe = [
        {"$match": {"readiness.confidence": {"$exists": True}}},
        {"$group": {
            "_id": "$readiness.status",
            "avg_confidence": {"$avg": "$readiness.confidence"},
        }},
    ]
    conf_raw = await db.hub_documents.aggregate(conf_pipe).to_list(10)
    confidence_by_status = {r["_id"]: round(r["avg_confidence"], 3) for r in conf_raw if r["_id"]}

    return {
        "total_documents": total,
        "by_status": by_status,
        "by_action": by_action,
        "no_readiness_data": no_readiness,
        "top_blocking_reasons": top_blocking,
        "top_warning_reasons": top_warnings,
        "top_reviewer_actions": top_reviewer_actions,
        "confidence_by_status": confidence_by_status,
    }


# ---------------------------------------------------------------------------
# Queue query
# ---------------------------------------------------------------------------

async def get_readiness_queue(
    status: Optional[str] = None,
    action: Optional[str] = None,
    reason: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
) -> Dict[str, Any]:
    """Get documents filtered by readiness criteria for review queues."""
    from deps import get_db
    db = get_db()

    query: Dict[str, Any] = {"readiness": {"$exists": True, "$ne": None}}
    if status:
        query["readiness.status"] = status
    if action:
        query["readiness.recommended_action"] = action
    if reason:
        query["$or"] = [
            {"readiness.blocking_reasons": reason},
            {"readiness.warning_reasons": reason},
        ]

    total = await db.hub_documents.count_documents(query)
    cursor = db.hub_documents.find(
        query,
        {
            "_id": 0, "id": 1, "file_name": 1, "suggested_job_type": 1,
            "status": 1, "vendor_canonical": 1, "ai_confidence": 1,
            "readiness": 1, "created_utc": 1, "updated_utc": 1,
        },
    ).sort("readiness.confidence", 1).skip(skip).limit(limit)
    docs = await cursor.to_list(limit)

    return {"total": total, "documents": docs}
