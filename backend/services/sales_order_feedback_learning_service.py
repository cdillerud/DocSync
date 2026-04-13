"""
GPI Document Hub — Sales Order Feedback-to-Learning Pipeline

Converts reviewer feedback and disagreement patterns into candidate
customer-profile learning suggestions. Suggestions are stored for
human review — never auto-applied.

SUGGESTION GENERATION ONLY: Never mutates profiles or changes advisory behavior.
"""

import logging
import os
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Default evidence thresholds (can be overridden by env vars)
DEFAULT_THRESHOLDS = {
    "add_alternate_ship_to":        2,
    "add_occasional_valid_item":    2,
    "add_alternate_uom_for_item":   2,
    "widen_order_value_tolerance":   2,
    "revise_po_pattern":            2,
    "increase_variability_tolerance": 3,
}

# Tuned (relaxed) thresholds for low-risk types — env-configurable
TUNED_THRESHOLDS = {
    "add_alternate_ship_to":     int(os.environ.get("LEARN_THRESH_SHIP_TO", "1")),
    "add_occasional_valid_item": int(os.environ.get("LEARN_THRESH_ITEM", "1")),
}

# Types eligible for threshold relaxation
RELAXABLE_TYPES = {"add_alternate_ship_to", "add_occasional_valid_item"}

MIN_CONFIDENCE = 0.4


async def generate_learning_suggestions(
    db,
    customer_no: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    """
    Analyze feedback + disagreement data and generate candidate
    profile-learning suggestions. Does NOT apply any changes.
    """
    started = datetime.now(timezone.utc).isoformat()

    # Pre-load drift risk for affected customers
    drift_cache: Dict[str, str] = {}

    # Fetch disagreement feedback
    match: Dict[str, Any] = {
        "reviewer_assessment": {"$in": ["incorrect", "partially_correct"]},
    }
    if customer_no:
        match["customer_no"] = customer_no

    feedback = await db.so_reviewer_feedback.find(match, {"_id": 0}).to_list(2000)

    if not feedback:
        return {"total_feedback_analyzed": 0, "suggestions_generated": 0, "message": "No disagreement feedback found"}

    # Group by customer
    by_customer: Dict[str, List[Dict]] = defaultdict(list)
    for fb in feedback:
        cno = fb.get("customer_no", "")
        if cno:
            by_customer[cno].append(fb)

    # Load related documents for richer context
    doc_ids = list({fb.get("document_id") for fb in feedback if fb.get("document_id")})
    docs_map = {}
    if doc_ids:
        async for d in db.hub_documents.find(
            {"id": {"$in": doc_ids}},
            {"_id": 0, "id": 1, "so_readiness_review": 1}
        ):
            docs_map[d["id"]] = d

    # Load profiles
    cust_nos = list(by_customer.keys())
    profiles = {}
    if cust_nos:
        async for p in db.customer_posting_profiles.find(
            {"customer_no": {"$in": cust_nos}, "status": "analyzed"}, {"_id": 0}
        ):
            profiles[p["customer_no"]] = p

    # Generate suggestions per customer
    suggestions = []
    for cno, fbs in by_customer.items():
        profile = profiles.get(cno)
        # Load drift risk
        drift_risk = await _get_drift_risk(db, cno, drift_cache)
        cust_suggestions = _analyze_customer_feedback(cno, fbs, profile, docs_map, drift_risk)
        suggestions.extend(cust_suggestions)

    # Store suggestions (skip duplicates by type+customer+proposed_change key)
    stored = 0
    for s in suggestions[:limit]:
        # Check for existing pending suggestion with same fingerprint
        fingerprint = f"{s['customer_no']}:{s['suggestion_type']}:{s.get('proposed_profile_change', {}).get('key', '')}"
        existing = await db.so_learning_suggestions.find_one(
            {"fingerprint": fingerprint, "status": "pending"}, {"_id": 0, "suggestion_id": 1}
        )
        if existing:
            # Update evidence count
            await db.so_learning_suggestions.update_one(
                {"suggestion_id": existing["suggestion_id"]},
                {"$set": {
                    "supporting_feedback_count": s["supporting_feedback_count"],
                    "confidence": s["confidence"],
                    "evidence_summary": s["evidence_summary"],
                    "updated_at": datetime.now(timezone.utc).isoformat(),
                }}
            )
        else:
            s["fingerprint"] = fingerprint
            await db.so_learning_suggestions.insert_one(s)
            s.pop("_id", None)
            stored += 1

    logger.info("[FeedbackLearning] Analyzed %d feedback → %d suggestions (%d new)",
                len(feedback), len(suggestions), stored)

    return {
        "total_feedback_analyzed": len(feedback),
        "customers_analyzed": len(by_customer),
        "suggestions_generated": len(suggestions),
        "new_stored": stored,
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_suggestions(
    db,
    customer_no: Optional[str] = None,
    suggestion_type: Optional[str] = None,
    status: Optional[str] = None,
    min_confidence: Optional[float] = None,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    limit: int = 50,
    skip: int = 0,
) -> Dict[str, Any]:
    """Fetch learning suggestions with filters."""
    match: Dict[str, Any] = {}
    if customer_no:
        match["customer_no"] = customer_no
    if suggestion_type:
        match["suggestion_type"] = suggestion_type
    if status:
        match["status"] = status
    if min_confidence is not None:
        match["confidence"] = {"$gte": min_confidence}
    if date_from or date_to:
        ts: Dict[str, Any] = {}
        if date_from:
            ts["$gte"] = date_from
        if date_to:
            ts["$lte"] = date_to
        match["created_at"] = ts

    total = await db.so_learning_suggestions.count_documents(match)
    cursor = db.so_learning_suggestions.find(
        match, {"_id": 0}
    ).sort("confidence", -1).skip(skip).limit(limit)
    records = await cursor.to_list(limit)

    return {"total": total, "showing": len(records), "skip": skip, "suggestions": records}


async def get_suggestion_by_id(db, suggestion_id: str) -> Optional[Dict[str, Any]]:
    """Fetch a single suggestion by ID."""
    return await db.so_learning_suggestions.find_one(
        {"suggestion_id": suggestion_id}, {"_id": 0}
    )


# =============================================================================
# Core analysis logic
# =============================================================================

def _analyze_customer_feedback(
    customer_no: str,
    feedback: List[Dict],
    profile: Optional[Dict],
    docs_map: Dict,
    drift_risk: str = "low",
) -> List[Dict]:
    """Generate candidate suggestions for one customer from their feedback."""
    suggestions = []
    now = datetime.now(timezone.utc).isoformat()
    customer_name = feedback[0].get("customer_name", "") if feedback else ""

    # Collect signals from all feedback
    ship_to_disagreements = []
    item_disagreements = []
    uom_disagreements = []
    amount_disagreements = []
    po_disagreements = []

    for fb in feedback:
        fields = fb.get("disagreed_fields") or []
        doc = docs_map.get(fb.get("document_id"), {})
        review = doc.get("so_readiness_review") or {}
        ship_to = review.get("ship_to_analysis") or {}
        item_uom = review.get("item_uom_analysis") or {}

        if "ship_to" in fields:
            raw_ship = ship_to.get("raw_input", "")
            if raw_ship:
                ship_to_disagreements.append({
                    "ship_to": raw_ship,
                    "doc_id": fb.get("document_id"),
                    "notes": fb.get("notes", ""),
                    "decision": fb.get("final_human_decision"),
                })

        if "item_match" in fields:
            for line in item_uom.get("line_details", []):
                if line.get("item_match") == "unknown":
                    item_disagreements.append({
                        "item": line.get("raw_item", ""),
                        "doc_id": fb.get("document_id"),
                        "notes": fb.get("notes", ""),
                    })

        if "uom" in fields:
            for line in item_uom.get("line_details", []):
                if line.get("uom_match") in ("unknown", "known_alternate"):
                    uom_disagreements.append({
                        "item": line.get("raw_item", ""),
                        "uom": line.get("raw_uom", ""),
                        "doc_id": fb.get("document_id"),
                    })

        if "amount_range" in fields:
            amount_disagreements.append({"doc_id": fb.get("document_id"), "notes": fb.get("notes", "")})

        if "po_pattern" in fields:
            po_disagreements.append({"doc_id": fb.get("document_id"), "notes": fb.get("notes", "")})

    profile_snapshot = {
        "invoices_analyzed": profile.get("invoices_analyzed") if profile else 0,
        "template_confidence": profile.get("template_confidence") if profile else None,
        "profile_richness_score": profile.get("profile_richness_score") if profile else 0,
    }

    # ── Ship-to suggestions ──
    ship_to_counter = Counter(d["ship_to"] for d in ship_to_disagreements if d["ship_to"])
    ship_thresh = _get_threshold("add_alternate_ship_to", drift_risk)
    for ship_to, count in ship_to_counter.most_common():
        relaxed = ship_thresh < DEFAULT_THRESHOLDS["add_alternate_ship_to"]
        if count >= ship_thresh:
            conf = min(0.95, 0.3 + count * 0.15)
            suggestions.append(_make_suggestion(
                stype="add_alternate_ship_to",
                customer_no=customer_no, customer_name=customer_name,
                evidence=f"Reviewer disagreed with ship-to flagging {count} time(s) for '{ship_to}'",
                confidence=conf,
                supporting_docs=[d["doc_id"] for d in ship_to_disagreements if d["ship_to"] == ship_to],
                count=count,
                change={"key": f"alternate_ship_tos.{ship_to}", "action": "add", "value": ship_to},
                profile_snapshot=profile_snapshot, now=now,
                threshold_used=ship_thresh,
                relaxed_threshold=relaxed,
                drift_risk=drift_risk,
            ))
        elif count >= 1 and count < ship_thresh:
            suggestions.append(_make_suggestion(
                stype="add_alternate_ship_to",
                customer_no=customer_no, customer_name=customer_name,
                evidence=f"Single reviewer noted '{ship_to}' as valid — insufficient evidence for confident suggestion",
                confidence=0.3,
                supporting_docs=[ship_to_disagreements[0]["doc_id"]],
                count=1,
                change={"key": f"alternate_ship_tos.{ship_to}", "action": "add", "value": ship_to},
                profile_snapshot=profile_snapshot, now=now,
                status="insufficient_evidence",
                threshold_used=ship_thresh,
                relaxed_threshold=False,
                drift_risk=drift_risk,
            ))

    # ── Item suggestions ──
    item_counter = Counter(d["item"] for d in item_disagreements if d["item"])
    item_thresh = _get_threshold("add_occasional_valid_item", drift_risk)
    for item, count in item_counter.most_common():
        relaxed = item_thresh < DEFAULT_THRESHOLDS["add_occasional_valid_item"]
        if count >= item_thresh:
            conf = min(0.90, 0.3 + count * 0.15)
            suggestions.append(_make_suggestion(
                stype="add_occasional_valid_item",
                customer_no=customer_no, customer_name=customer_name,
                evidence=f"Reviewer disagreed with item flagging {count} time(s) for '{item}'",
                confidence=conf,
                supporting_docs=[d["doc_id"] for d in item_disagreements if d["item"] == item],
                count=count,
                change={"key": f"occasional_valid_items.{item}", "action": "add", "value": item},
                profile_snapshot=profile_snapshot, now=now,
                threshold_used=item_thresh,
                relaxed_threshold=relaxed,
                drift_risk=drift_risk,
            ))
        elif count >= 1 and count < item_thresh:
            suggestions.append(_make_suggestion(
                stype="add_occasional_valid_item",
                customer_no=customer_no, customer_name=customer_name,
                evidence=f"Single reviewer noted '{item}' as valid — weak evidence",
                confidence=0.25,
                supporting_docs=[item_disagreements[0]["doc_id"]],
                count=1,
                change={"key": f"occasional_valid_items.{item}", "action": "add", "value": item},
                profile_snapshot=profile_snapshot, now=now,
                status="insufficient_evidence",
                threshold_used=item_thresh,
                relaxed_threshold=False,
                drift_risk=drift_risk,
            ))

    # ── UOM suggestions ──
    uom_thresh = _get_threshold("add_alternate_uom_for_item", drift_risk)
    uom_pairs = Counter((d["item"], d["uom"]) for d in uom_disagreements if d["item"] and d["uom"])
    for (item, uom), count in uom_pairs.most_common():
        if count >= 1:
            conf = min(0.85, 0.35 + count * 0.15) if count >= uom_thresh else 0.3
            stat = "pending" if count >= uom_thresh else "insufficient_evidence"
            suggestions.append(_make_suggestion(
                stype="add_alternate_uom_for_item",
                customer_no=customer_no, customer_name=customer_name,
                evidence=f"Reviewer disagreed with UOM flagging {count} time(s) for '{item}' with UOM '{uom}'",
                confidence=conf,
                supporting_docs=[d["doc_id"] for d in uom_disagreements if d["item"] == item and d["uom"] == uom],
                count=count,
                change={"key": f"alternate_valid_uoms_by_item.{item}", "action": "add_uom", "item": item, "uom": uom},
                profile_snapshot=profile_snapshot, now=now,
                status=stat,
            ))

    # ── Amount range suggestion ──
    amt_thresh = _get_threshold("widen_order_value_tolerance", drift_risk)
    if len(amount_disagreements) >= amt_thresh:
        suggestions.append(_make_suggestion(
            stype="widen_order_value_tolerance",
            customer_no=customer_no, customer_name=customer_name,
            evidence=f"Reviewer disagreed with amount flagging {len(amount_disagreements)} time(s)",
            confidence=min(0.80, 0.3 + len(amount_disagreements) * 0.12),
            supporting_docs=[d["doc_id"] for d in amount_disagreements],
            count=len(amount_disagreements),
            change={"key": "amount_range", "action": "widen", "note": "Review and widen min/max bounds"},
            profile_snapshot=profile_snapshot, now=now,
        ))

    # ── PO pattern suggestion ──
    po_thresh = _get_threshold("revise_po_pattern", drift_risk)
    if len(po_disagreements) >= po_thresh:
        suggestions.append(_make_suggestion(
            stype="revise_po_pattern",
            customer_no=customer_no, customer_name=customer_name,
            evidence=f"Reviewer disagreed with PO format flagging {len(po_disagreements)} time(s)",
            confidence=min(0.75, 0.3 + len(po_disagreements) * 0.12),
            supporting_docs=[d["doc_id"] for d in po_disagreements],
            count=len(po_disagreements),
            change={"key": "po_number_pattern", "action": "revise"},
            profile_snapshot=profile_snapshot, now=now,
        ))

    # ── Variability suggestion ──
    total_disagreements = len(feedback)
    if total_disagreements >= 3 and profile:
        current_var = profile.get("customer_variability_index", 0)
        if current_var < 0.5:
            suggestions.append(_make_suggestion(
                stype="increase_variability_tolerance",
                customer_no=customer_no, customer_name=customer_name,
                evidence=f"{total_disagreements} disagreements suggest higher operational diversity than profile captures (current variability={current_var:.2f})",
                confidence=min(0.80, 0.3 + total_disagreements * 0.10),
                supporting_docs=[fb.get("document_id") for fb in feedback[:5]],
                count=total_disagreements,
                change={"key": "customer_variability_index", "action": "increase", "current": current_var},
                profile_snapshot=profile_snapshot, now=now,
            ))

    return suggestions


def _make_suggestion(
    stype: str, customer_no: str, customer_name: str,
    evidence: str, confidence: float,
    supporting_docs: List[str], count: int,
    change: Dict, profile_snapshot: Dict, now: str,
    status: str = "pending",
    threshold_used: int = 2,
    relaxed_threshold: bool = False,
    drift_risk: str = "low",
) -> Dict[str, Any]:
    return {
        "suggestion_id": str(uuid.uuid4())[:12],
        "suggestion_type": stype,
        "customer_no": customer_no,
        "customer_name": customer_name,
        "supporting_documents": supporting_docs[:10],
        "supporting_feedback_count": count,
        "evidence_summary": evidence,
        "confidence": round(confidence, 4),
        "proposed_profile_change": change,
        "current_profile_snapshot": profile_snapshot,
        "status": status,
        "threshold_used": threshold_used,
        "relaxed_threshold": relaxed_threshold,
        "drift_risk_at_generation": drift_risk,
        "created_at": now,
        "updated_at": now,
    }


def _get_threshold(stype: str, drift_risk: str) -> int:
    """
    Return the evidence threshold for a suggestion type, considering drift risk.
    High-drift customers use stricter (default) thresholds even for relaxable types.
    """
    default = DEFAULT_THRESHOLDS.get(stype, 2)

    if stype not in RELAXABLE_TYPES:
        return default

    if drift_risk == "high":
        # High drift = conservative — use default or stricter
        logger.info("[FeedbackLearning] High drift risk — using default threshold %d for %s", default, stype)
        return default

    tuned = TUNED_THRESHOLDS.get(stype, default)

    if tuned < default:
        logger.info("[FeedbackLearning] Using relaxed threshold %d (default %d) for %s (drift=%s)",
                    tuned, default, stype, drift_risk)
    return tuned


async def _get_drift_risk(db, customer_no: str, cache: Dict[str, str]) -> str:
    """Load drift risk for a customer, with caching."""
    if customer_no in cache:
        return cache[customer_no]

    try:
        from services.sales_order_profile_drift_service import get_customer_drift_detail
        detail = await get_customer_drift_detail(db, customer_no)
        risk = detail.get("drift_risk", "low")
    except Exception:
        risk = "low"

    cache[customer_no] = risk
    return risk
