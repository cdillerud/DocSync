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
    po_resolved = bool(po_number and str(po_number).strip())

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
    ai_conf = float(doc.get("ai_confidence") or 0)
    confidence = _compute_confidence(signals, ai_conf, len(blocking), len(warnings))

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
    Also computes automation confidence and decision explanation."""
    from deps import get_db
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise ValueError(f"Document not found: {doc_id}")

    readiness = evaluate_readiness(doc)

    # Compute automation intelligence alongside readiness
    from services.automation_intelligence_service import (
        compute_automation_confidence,
        build_decision_explanation,
    )
    # Temporarily attach readiness so intelligence can read it
    doc["readiness"] = readiness
    auto_conf = compute_automation_confidence(doc)
    explanation = build_decision_explanation(doc)

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "readiness": readiness,
            "automation_confidence": auto_conf,
            "decision_explanation": explanation,
            "updated_utc": readiness["last_evaluated_at"],
        }},
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
    Also computes automation confidence and decision explanation."""
    from deps import get_db
    from services.automation_intelligence_service import (
        compute_automation_confidence,
        build_decision_explanation,
    )
    db = get_db()

    cursor = db.hub_documents.find(
        {"$or": [{"readiness": {"$exists": False}}, {"readiness": None}]},
        {"_id": 0},
    ).limit(limit)
    docs = await cursor.to_list(limit)

    counts = {STATUS_READY_AUTO_DRAFT: 0, STATUS_READY_AUTO_LINK: 0,
              STATUS_NEEDS_REVIEW: 0, STATUS_BLOCKED: 0, STATUS_AMBIGUOUS: 0, "errors": 0}
    for d in docs:
        try:
            r = evaluate_readiness(d)
            d["readiness"] = r
            auto_conf = compute_automation_confidence(d)
            explanation = build_decision_explanation(d)
            await db.hub_documents.update_one(
                {"id": d["id"]},
                {"$set": {
                    "readiness": r,
                    "automation_confidence": auto_conf,
                    "decision_explanation": explanation,
                    "updated_utc": r["last_evaluated_at"],
                }},
            )
            counts[r["status"]] = counts.get(r["status"], 0) + 1
        except Exception:
            counts["errors"] += 1

    return {"total": len(docs), **counts}


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
