"""
Automation Intelligence Service — Confidence Scoring, Explainability, Reviewer Assist

Provides:
  1. Weighted automation confidence scoring (0.0–1.0)
  2. Structured decision explanation objects
  3. AI-assisted reviewer suggestions for needs_review documents
  4. Automation metrics aggregation

Integrates with the readiness engine without replacing it — adds
automation_confidence and decision_explanation as companion fields.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("automation_intelligence")

# ---------------------------------------------------------------------------
# Confidence scoring weights
# ---------------------------------------------------------------------------

WEIGHTS = {
    "vendor_resolution_score":        0.25,
    "entity_resolution_confidence":   0.20,
    "extraction_confidence":          0.20,
    "transaction_graph_strength":     0.15,
    "policy_pass_score":              0.10,
    "duplicate_risk_penalty":        -0.10,
}

AUTO_EXECUTE_THRESHOLD = 0.90
REVIEW_THRESHOLD = 0.70


# ---------------------------------------------------------------------------
# Signal extractors — read raw signals from a document
# ---------------------------------------------------------------------------

def _vendor_resolution_score(doc: dict) -> float:
    """0.0–1.0 based on vendor resolution quality."""
    vr = doc.get("vendor_resolution") or {}
    method = doc.get("vendor_match_method") or vr.get("match_method", "")

    # Direct / exact match
    if method in ("bc_exact_match", "manual_match"):
        return 1.0
    if method == "alias_match":
        return 0.90
    if method == "fuzzy_match":
        raw = vr.get("match_score") or vr.get("fuzzy_score") or 0
        return min(1.0, max(0.0, float(raw) / 100.0)) if raw else 0.6
    # Vendor canonical present but unknown method
    if doc.get("vendor_canonical") or vr.get("status") == "resolved":
        return 0.75
    return 0.0


def _entity_resolution_confidence(doc: dict) -> float:
    """0.0–1.0 based on customer/ship-to resolution."""
    score = 0.0
    if doc.get("customer_canonical") or doc.get("customer_id") or doc.get("bc_customer_id"):
        score += 0.6
    if doc.get("customer_matched_name"):
        score += 0.2
    extracted = doc.get("extracted_fields") or {}
    if extracted.get("ship_to_address") or extracted.get("delivery_address"):
        score += 0.2
    return min(1.0, score)


def _extraction_confidence(doc: dict) -> float:
    """0.0–1.0 based on AI extraction quality."""
    ai_conf = float(doc.get("ai_confidence") or doc.get("classification_confidence") or 0)
    extracted = doc.get("extracted_fields") or {}

    # Required fields present bonus
    has_vendor = bool(extracted.get("vendor"))
    has_invoice = bool(extracted.get("invoice_number"))
    has_amount = bool(
        extracted.get("amount") or extracted.get("invoice_amount") or extracted.get("total_amount")
    )
    completeness = (int(has_vendor) + int(has_invoice) + int(has_amount)) / 3.0

    line_items = extracted.get("line_items") or []
    li_quality = 0.0
    if line_items:
        valid = sum(
            1 for li in line_items
            if (li.get("amount") or li.get("unit_price") or li.get("total"))
            and (li.get("description") or li.get("item"))
        )
        li_quality = valid / len(line_items) if line_items else 0

    return min(1.0, ai_conf * 0.4 + completeness * 0.4 + li_quality * 0.2)


def _transaction_graph_strength(doc: dict) -> float:
    """0.0–1.0 based on how well-connected the document is to BC records."""
    score = 0.0
    if doc.get("bc_document_id") or doc.get("linked_bc_id") or doc.get("bc_purchase_invoice_id"):
        score += 0.5
    if doc.get("transaction_action") == "linked":
        score += 0.3
    extracted = doc.get("extracted_fields") or {}
    if extracted.get("po_number") or doc.get("po_number_clean"):
        score += 0.2
    return min(1.0, score)


def _policy_pass_score(doc: dict) -> float:
    """0.0–1.0 based on policy engine pass status."""
    decision = doc.get("automation_decision") or ""
    if decision in ("approved", "auto_process", "auto_clear"):
        return 1.0
    if decision in ("hold", "needs_review", "manual"):
        return 0.4
    if decision in ("blocked", "reject"):
        return 0.0

    # Readiness-based fallback
    readiness = doc.get("readiness") or {}
    status = readiness.get("status", "")
    if status in ("ready_auto_draft", "ready_auto_link"):
        return 0.85
    if status == "needs_review":
        return 0.5
    if status in ("blocked", "ambiguous"):
        return 0.2
    return 0.5  # no data → neutral


def _duplicate_risk_score(doc: dict) -> float:
    """0.0–1.0 — higher means MORE risk (used as penalty)."""
    # Check BC validation duplicate check first — it's authoritative
    bc_val = doc.get("bc_validation") or {}
    for chk in (bc_val.get("checks") or []):
        if chk.get("check_name") == "duplicate_check":
            return 1.0 if not chk.get("passed") else 0.0
    # Fallback to raw flags only if BC validation didn't run a duplicate check
    if doc.get("is_duplicate"):
        return 1.0
    if doc.get("possible_duplicate"):
        return 0.7
    return 0.0


# ---------------------------------------------------------------------------
# Feature 1: Automation Confidence Scoring
# ---------------------------------------------------------------------------

def compute_automation_confidence(doc: dict) -> dict:
    """
    Compute a weighted automation confidence score for a document.

    Returns dict with score breakdown and thresholds.
    """
    raw_signals = {
        "vendor_resolution_score": _vendor_resolution_score(doc),
        "entity_resolution_confidence": _entity_resolution_confidence(doc),
        "extraction_confidence": _extraction_confidence(doc),
        "transaction_graph_strength": _transaction_graph_strength(doc),
        "policy_pass_score": _policy_pass_score(doc),
        "duplicate_risk_penalty": _duplicate_risk_score(doc),
    }

    # Weighted sum
    total = 0.0
    for key, weight in WEIGHTS.items():
        total += raw_signals[key] * weight

    score = max(0.0, min(1.0, total))

    # Determine recommended action from score
    if score >= AUTO_EXECUTE_THRESHOLD:
        action = "auto_execute"
    elif score >= REVIEW_THRESHOLD:
        action = "assisted_review"
    else:
        action = "manual_review"

    return {
        "score": round(score, 4),
        "signals": {k: round(v, 4) for k, v in raw_signals.items()},
        "weights": WEIGHTS,
        "thresholds": {
            "auto_execute": AUTO_EXECUTE_THRESHOLD,
            "review": REVIEW_THRESHOLD,
        },
        "recommended_action": action,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Feature 2: Decision Explainability
# ---------------------------------------------------------------------------

def build_decision_explanation(doc: dict) -> dict:
    """
    Build a structured, human-readable explanation of why the system made
    its current decision about this document.
    """
    readiness = doc.get("readiness") or {}
    vr = doc.get("vendor_resolution") or {}
    ac = doc.get("automation_confidence") or compute_automation_confidence(doc)
    signals = readiness.get("signals") or {}

    confidence = ac.get("score", 0) if isinstance(ac, dict) else float(ac or 0)
    status = readiness.get("status", "unknown")
    action = readiness.get("recommended_action", "review")

    # Build supporting evidence
    evidence: List[str] = []
    risk_flags: List[str] = []

    # Vendor
    match_method = doc.get("vendor_match_method") or vr.get("match_method", "")
    vendor_name = doc.get("vendor_canonical") or vr.get("matched_vendor_name", "")
    if signals.get("vendor_resolved"):
        evidence.append(f"Vendor resolved via {match_method or 'known method'}" +
                       (f" → {vendor_name}" if vendor_name else ""))
    else:
        risk_flags.append("Vendor not resolved to Business Central")

    # Customer
    if signals.get("customer_resolved"):
        cust = doc.get("customer_matched_name") or doc.get("customer_canonical") or ""
        evidence.append(f"Customer matched{': ' + cust if cust else ''}")
    elif (doc.get("doc_type") or "").lower() in ("salesorder", "salesinvoice", "sales_order", "sales_invoice"):
        risk_flags.append("Customer not resolved for sales document")

    # PO
    extracted = doc.get("extracted_fields") or {}
    po = extracted.get("po_number") or doc.get("po_number_clean")
    if signals.get("po_resolved"):
        evidence.append(f"PO reference found: {po}")
    else:
        risk_flags.append("No PO number for cross-reference")

    # Graph
    if signals.get("graph_linked"):
        bc_id = doc.get("bc_document_id") or doc.get("linked_bc_id") or ""
        evidence.append(f"Linked to BC record{': ' + bc_id if bc_id else ''}")

    # Duplicate
    if signals.get("duplicate_risk"):
        risk_flags.append("Possible duplicate document detected")
    else:
        evidence.append("No duplicate documents detected")

    # Line items
    if signals.get("line_items_present"):
        li_count = len(extracted.get("line_items") or [])
        if signals.get("line_items_confident"):
            evidence.append(f"{li_count} line items extracted with high confidence")
        else:
            risk_flags.append(f"{li_count} line items extracted but quality is low")

    # Required fields
    if signals.get("required_fields_complete"):
        evidence.append("All required fields (vendor, invoice #, amount) present")
    else:
        missing = []
        if not extracted.get("vendor"):
            missing.append("vendor")
        if not extracted.get("invoice_number"):
            missing.append("invoice number")
        if not any(extracted.get(f) for f in ["amount", "invoice_amount", "total_amount"]):
            missing.append("amount")
        if missing:
            risk_flags.append(f"Missing required fields: {', '.join(missing)}")

    # Policy
    if signals.get("policy_blocked"):
        risk_flags.append("Blocked by automation policy engine")
    elif signals.get("policy_held"):
        risk_flags.append("Held for manual review by policy engine")

    # Override
    if signals.get("manually_overridden"):
        evidence.append("Document was manually reviewed and approved")

    # AR release gate
    ar_gate = doc.get("ar_release_gate") or {}
    if ar_gate.get("status") == "held":
        blocking = ar_gate.get("blocking_reasons", [])
        risk_flags.append(f"AR release gate held: {', '.join(blocking)}" if blocking else "AR release gate held")
    elif ar_gate.get("status") == "override":
        evidence.append(f"AR release gate overridden by {ar_gate.get('override', {}).get('approved_by', 'user')}")
    elif ar_gate.get("status") == "released":
        evidence.append("AR release gate passed")

    return {
        "decision": action,
        "confidence": round(confidence, 4),
        "status": status,
        "signals": {k: v for k, v in signals.items()} if signals else {},
        "supporting_evidence": evidence,
        "risk_flags": risk_flags,
        "recommended_action": action,
        "explanation_generated_at": datetime.now(timezone.utc).isoformat(),
    }


# ---------------------------------------------------------------------------
# Feature 3: Reviewer Assist Engine
# ---------------------------------------------------------------------------

def generate_review_suggestions(doc: dict) -> List[dict]:
    """
    Generate suggested one-click actions for a document that needs review.
    Each suggestion has: action, field, suggested_value, confidence, reason.
    """
    suggestions: List[dict] = []
    extracted = doc.get("extracted_fields") or {}
    vr = doc.get("vendor_resolution") or {}
    readiness = doc.get("readiness") or {}
    signals = readiness.get("signals") or {}

    # --- Vendor confirmation ---
    if not signals.get("vendor_resolved"):
        vendor_raw = extracted.get("vendor") or doc.get("vendor_raw_ocr") or ""
        # Check if we have a fuzzy match candidate
        fuzzy_name = vr.get("matched_vendor_name") or vr.get("fuzzy_candidate")
        fuzzy_score = vr.get("match_score") or vr.get("fuzzy_score") or 0

        if fuzzy_name and float(fuzzy_score) > 50:
            suggestions.append({
                "action": "confirm_vendor",
                "field": "vendor_canonical",
                "suggested_value": fuzzy_name,
                "confidence": round(min(1.0, float(fuzzy_score) / 100.0), 2),
                "reason": f"Fuzzy match ({fuzzy_score}%) for '{vendor_raw}'",
                "vendor_id": vr.get("matched_vendor_id"),
            })
        elif vendor_raw:
            suggestions.append({
                "action": "resolve_vendor",
                "field": "vendor_canonical",
                "suggested_value": vendor_raw,
                "confidence": 0.3,
                "reason": f"Raw vendor name extracted: '{vendor_raw}' — needs manual resolution",
            })

    # --- Customer confirmation ---
    if not signals.get("customer_resolved"):
        customer_raw = (
            extracted.get("customer")
            or doc.get("customer_extracted")
            or extracted.get("bill_to")
        )
        if customer_raw:
            suggestions.append({
                "action": "confirm_customer",
                "field": "customer_canonical",
                "suggested_value": str(customer_raw),
                "confidence": 0.5,
                "reason": f"Customer name extracted: '{customer_raw}' — needs BC match",
            })

    # --- PO link ---
    if not signals.get("po_resolved"):
        po = extracted.get("po_number") or doc.get("po_number_clean")
        if po:
            suggestions.append({
                "action": "link_po",
                "field": "po_number_clean",
                "suggested_value": str(po),
                "confidence": 0.7,
                "reason": f"PO number extracted: '{po}' — verify and link",
            })
        else:
            # Check for any reference numbers
            ref = extracted.get("reference_number") or extracted.get("order_number")
            if ref:
                suggestions.append({
                    "action": "link_po",
                    "field": "po_number_clean",
                    "suggested_value": str(ref),
                    "confidence": 0.4,
                    "reason": f"Reference number '{ref}' may be PO — verify",
                })

    # --- Duplicate resolution ---
    if signals.get("duplicate_risk"):
        dup_id = doc.get("duplicate_of_id") or doc.get("possible_duplicate_id")
        suggestions.append({
            "action": "resolve_duplicate",
            "field": "is_duplicate",
            "suggested_value": "not_duplicate",
            "confidence": 0.5,
            "reason": f"Flagged as possible duplicate" +
                      (f" of {dup_id}" if dup_id else "") +
                      " — confirm or dismiss",
        })

    # --- Missing required fields ---
    if not signals.get("required_fields_complete"):
        if not extracted.get("vendor"):
            suggestions.append({
                "action": "correct_field",
                "field": "vendor",
                "suggested_value": "",
                "confidence": 0.0,
                "reason": "Vendor field missing — manual entry required",
            })
        if not extracted.get("invoice_number"):
            inv = doc.get("legacy_bc_doc_no") or ""
            suggestions.append({
                "action": "correct_field",
                "field": "invoice_number",
                "suggested_value": str(inv) if inv else "",
                "confidence": 0.3 if inv else 0.0,
                "reason": f"Invoice number missing" +
                          (f" — legacy ref '{inv}' may apply" if inv else " — manual entry required"),
            })
        amount_fields = ["amount", "invoice_amount", "total_amount"]
        if not any(extracted.get(f) for f in amount_fields):
            suggestions.append({
                "action": "correct_field",
                "field": "total_amount",
                "suggested_value": "",
                "confidence": 0.0,
                "reason": "Total amount missing — manual entry required",
            })

    # --- Vendor needs review (low-confidence match) ---
    if vr.get("status") == "needs_review":
        matched = vr.get("matched_vendor_name", "")
        score = vr.get("match_score", 0)
        if matched:
            suggestions.append({
                "action": "confirm_vendor",
                "field": "vendor_canonical",
                "suggested_value": matched,
                "confidence": round(min(1.0, float(score) / 100.0), 2) if score else 0.5,
                "reason": f"Low-confidence vendor match: '{matched}' (score: {score}) — confirm or reject",
                "vendor_id": vr.get("matched_vendor_id"),
            })

    # Sort by confidence descending
    suggestions.sort(key=lambda s: s.get("confidence", 0), reverse=True)
    return suggestions


async def accept_suggestion(doc_id: str, action: str, field: str, value: str, accepted_by: str = "reviewer") -> dict:
    """Apply a reviewer suggestion to a document."""
    from deps import get_db
    db = get_db()

    now = datetime.now(timezone.utc).isoformat()

    update: Dict[str, Any] = {}
    log_entry = {
        "action": action,
        "field": field,
        "value": value,
        "accepted_by": accepted_by,
        "accepted_at": now,
    }

    if action == "confirm_vendor" and field == "vendor_canonical":
        update["vendor_canonical"] = value
        update["vendor_match_method"] = "manual_match"
    elif action == "confirm_customer" and field == "customer_canonical":
        update["customer_canonical"] = value
    elif action == "link_po" and field == "po_number_clean":
        update["po_number_clean"] = value
    elif action == "resolve_duplicate":
        update["possible_duplicate"] = False
        update["is_duplicate"] = False
        update["duplicate_resolved_by"] = accepted_by
    elif action == "correct_field":
        update[f"extracted_fields.{field}"] = value
    else:
        return {"error": f"Unknown action: {action}"}

    update["updated_utc"] = now

    result = await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": update,
            "$push": {"review_assist_log": log_entry},
        },
    )

    if result.modified_count == 0:
        return {"error": "Document not found", "doc_id": doc_id}

    logger.info("Review suggestion accepted: doc=%s action=%s field=%s by=%s", doc_id, action, field, accepted_by)
    return {"success": True, "doc_id": doc_id, "applied": log_entry}


# ---------------------------------------------------------------------------
# Feature 4: Automation Metrics
# ---------------------------------------------------------------------------

async def get_automation_metrics() -> dict:
    """Aggregate automation intelligence metrics across all documents."""
    from deps import get_db
    db = get_db()

    total = await db.hub_documents.count_documents({})
    if total == 0:
        return {
            "total_documents": 0,
            "automation_rate": 0,
            "review_rate": 0,
            "blocked_rate": 0,
            "avg_confidence": 0,
            "confidence_distribution": {},
            "top_review_causes": [],
            "top_blocking_reasons": [],
        }

    # Counts by readiness status
    status_pipe = [
        {"$group": {"_id": "$readiness.status", "count": {"$sum": 1}}},
    ]
    status_raw = await db.hub_documents.aggregate(status_pipe).to_list(10)
    by_status = {r["_id"]: r["count"] for r in status_raw if r["_id"]}

    auto_count = by_status.get("ready_auto_draft", 0) + by_status.get("ready_auto_link", 0)
    review_count = by_status.get("needs_review", 0) + by_status.get("ambiguous", 0)
    blocked_count = by_status.get("blocked", 0)
    evaluated = auto_count + review_count + blocked_count

    # Automation confidence stats
    conf_pipe = [
        {"$match": {"automation_confidence.score": {"$exists": True}}},
        {"$group": {
            "_id": None,
            "avg": {"$avg": "$automation_confidence.score"},
            "min": {"$min": "$automation_confidence.score"},
            "max": {"$max": "$automation_confidence.score"},
            "count": {"$sum": 1},
        }},
    ]
    conf_raw = await db.hub_documents.aggregate(conf_pipe).to_list(1)
    conf_stats = conf_raw[0] if conf_raw else {"avg": 0, "min": 0, "max": 0, "count": 0}

    # Confidence distribution buckets
    bucket_pipe = [
        {"$match": {"automation_confidence.score": {"$exists": True}}},
        {"$bucket": {
            "groupBy": "$automation_confidence.score",
            "boundaries": [0, 0.3, 0.5, 0.7, 0.9, 1.01],
            "default": "other",
            "output": {"count": {"$sum": 1}},
        }},
    ]
    try:
        bucket_raw = await db.hub_documents.aggregate(bucket_pipe).to_list(10)
        distribution = {}
        label_map = {0: "0.0-0.3", 0.3: "0.3-0.5", 0.5: "0.5-0.7", 0.7: "0.7-0.9", 0.9: "0.9-1.0"}
        for b in bucket_raw:
            label = label_map.get(b["_id"], str(b["_id"]))
            distribution[label] = b["count"]
    except Exception:
        distribution = {}

    # Top review causes (warning reasons for needs_review docs)
    review_cause_pipe = [
        {"$match": {"readiness.status": {"$in": ["needs_review", "ambiguous"]}}},
        {"$unwind": "$readiness.warning_reasons"},
        {"$group": {"_id": "$readiness.warning_reasons", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    review_raw = await db.hub_documents.aggregate(review_cause_pipe).to_list(10)
    top_review_causes = [{"reason": r["_id"], "count": r["count"]} for r in review_raw if r["_id"]]

    # Top blocking reasons
    block_pipe = [
        {"$match": {"readiness.status": "blocked"}},
        {"$unwind": "$readiness.blocking_reasons"},
        {"$group": {"_id": "$readiness.blocking_reasons", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    block_raw = await db.hub_documents.aggregate(block_pipe).to_list(10)
    top_blocking = [{"reason": r["_id"], "count": r["count"]} for r in block_raw if r["_id"]]

    # Per-signal averages (for radar chart)
    signal_pipe = [
        {"$match": {"automation_confidence.signals": {"$exists": True}}},
        {"$group": {
            "_id": None,
            "avg_vendor": {"$avg": "$automation_confidence.signals.vendor_resolution_score"},
            "avg_entity": {"$avg": "$automation_confidence.signals.entity_resolution_confidence"},
            "avg_extraction": {"$avg": "$automation_confidence.signals.extraction_confidence"},
            "avg_graph": {"$avg": "$automation_confidence.signals.transaction_graph_strength"},
            "avg_policy": {"$avg": "$automation_confidence.signals.policy_pass_score"},
            "avg_dup_risk": {"$avg": "$automation_confidence.signals.duplicate_risk_penalty"},
        }},
    ]
    signal_raw = await db.hub_documents.aggregate(signal_pipe).to_list(1)
    signal_avgs = {}
    if signal_raw:
        s = signal_raw[0]
        signal_avgs = {
            "vendor_resolution": round(s.get("avg_vendor") or 0, 3),
            "entity_resolution": round(s.get("avg_entity") or 0, 3),
            "extraction_quality": round(s.get("avg_extraction") or 0, 3),
            "transaction_graph": round(s.get("avg_graph") or 0, 3),
            "policy_compliance": round(s.get("avg_policy") or 0, 3),
            "duplicate_risk": round(s.get("avg_dup_risk") or 0, 3),
        }

    return {
        "total_documents": total,
        "evaluated_documents": evaluated,
        "automation_rate": round(auto_count / total, 4) if total else 0,
        "review_rate": round(review_count / total, 4) if total else 0,
        "blocked_rate": round(blocked_count / total, 4) if total else 0,
        "by_status": by_status,
        "avg_confidence": round(conf_stats.get("avg") or 0, 4),
        "min_confidence": round(conf_stats.get("min") or 0, 4),
        "max_confidence": round(conf_stats.get("max") or 0, 4),
        "scored_documents": conf_stats.get("count", 0),
        "confidence_distribution": distribution,
        "signal_averages": signal_avgs,
        "top_review_causes": top_review_causes,
        "top_blocking_reasons": top_blocking,
        "thresholds": {
            "auto_execute": AUTO_EXECUTE_THRESHOLD,
            "review": REVIEW_THRESHOLD,
        },
    }


# ---------------------------------------------------------------------------
# Evaluate & persist (combines confidence + explanation on a document)
# ---------------------------------------------------------------------------

async def evaluate_automation_intelligence(doc_id: str) -> dict:
    """
    Compute automation confidence and decision explanation for a document,
    persist results, and return the combined output.
    """
    from deps import get_db
    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found", "doc_id": doc_id}

    confidence = compute_automation_confidence(doc)
    explanation = build_decision_explanation(doc)
    suggestions = generate_review_suggestions(doc)

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "automation_confidence": confidence,
            "decision_explanation": explanation,
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }},
    )

    return {
        "doc_id": doc_id,
        "automation_confidence": confidence,
        "decision_explanation": explanation,
        "review_suggestions": suggestions if explanation.get("status") in ("needs_review", "blocked", "ambiguous") else [],
    }


async def batch_evaluate_intelligence(limit: int = 200) -> dict:
    """Batch compute automation intelligence for documents missing it."""
    from deps import get_db
    db = get_db()

    cursor = db.hub_documents.find(
        {"$or": [
            {"automation_confidence": {"$exists": False}},
            {"automation_confidence": None},
        ]},
        {"_id": 0},
    ).limit(limit)
    docs = await cursor.to_list(limit)

    counts = {"processed": 0, "errors": 0}
    for d in docs:
        try:
            conf = compute_automation_confidence(d)
            expl = build_decision_explanation(d)
            await db.hub_documents.update_one(
                {"id": d["id"]},
                {"$set": {
                    "automation_confidence": conf,
                    "decision_explanation": expl,
                    "updated_utc": datetime.now(timezone.utc).isoformat(),
                }},
            )
            counts["processed"] += 1
        except Exception as e:
            logger.warning("Failed to evaluate intelligence for %s: %s", d.get("id"), e)
            counts["errors"] += 1

    return {"total": len(docs), **counts}
