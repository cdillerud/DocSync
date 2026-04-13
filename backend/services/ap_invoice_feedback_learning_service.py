"""
GPI Document Hub — AP Invoice Feedback-to-Learning Service

Generates candidate vendor-profile learning suggestions from
reviewer feedback. Governed, suggestion-only — never auto-applies.
"""

import logging
import uuid
from collections import Counter, defaultdict
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

AP_DEFAULT_THRESHOLDS = {
    "add_vendor_alias": 2,
    "add_accepted_reference_pattern": 2,
    "widen_amount_tolerance": 2,
    "add_accepted_po_behavior": 2,
    "increase_vendor_variability": 3,
}


async def generate_ap_learning_suggestions(
    db,
    vendor_no: Optional[str] = None,
    limit: int = 50,
) -> Dict[str, Any]:
    started = datetime.now(timezone.utc).isoformat()

    match: Dict[str, Any] = {
        "reviewer_assessment": {"$in": ["incorrect", "partially_correct"]},
    }
    if vendor_no:
        match["vendor_no"] = vendor_no

    feedback = await db.ap_reviewer_feedback.find(match, {"_id": 0}).to_list(2000)
    if not feedback:
        return {"total_analyzed": 0, "suggestions_generated": 0, "message": "No AP disagreement feedback"}

    by_vendor: Dict[str, List] = defaultdict(list)
    for fb in feedback:
        vno = fb.get("vendor_no", "")
        if vno:
            by_vendor[vno].append(fb)

    suggestions = []
    for vno, fbs in by_vendor.items():
        suggestions.extend(_analyze_vendor_feedback(vno, fbs))

    stored = 0
    for s in suggestions[:limit]:
        fp = s["fingerprint"]
        existing = await db.ap_learning_suggestions.find_one(
            {"fingerprint": fp, "status": "pending"}, {"_id": 0, "suggestion_id": 1}
        )
        if existing:
            await db.ap_learning_suggestions.update_one(
                {"suggestion_id": existing["suggestion_id"]},
                {"$set": {"supporting_feedback_count": s["supporting_feedback_count"],
                          "confidence": s["confidence"],
                          "updated_at": datetime.now(timezone.utc).isoformat()}}
            )
        else:
            s["fingerprint"] = fp
            await db.ap_learning_suggestions.insert_one(s)
            s.pop("_id", None)
            stored += 1

    logger.info("[AP-Learning] %d feedback → %d suggestions (%d new)", len(feedback), len(suggestions), stored)
    return {
        "total_analyzed": len(feedback),
        "vendors_analyzed": len(by_vendor),
        "suggestions_generated": len(suggestions),
        "new_stored": stored,
        "started_at": started,
        "completed_at": datetime.now(timezone.utc).isoformat(),
    }


async def get_ap_suggestions(
    db, vendor_no: Optional[str] = None,
    suggestion_type: Optional[str] = None,
    status: Optional[str] = None,
    limit: int = 50, skip: int = 0,
) -> Dict[str, Any]:
    match: Dict[str, Any] = {}
    if vendor_no:
        match["vendor_no"] = vendor_no
    if suggestion_type:
        match["suggestion_type"] = suggestion_type
    if status:
        match["status"] = status

    total = await db.ap_learning_suggestions.count_documents(match)
    records = await db.ap_learning_suggestions.find(
        match, {"_id": 0}
    ).sort("confidence", -1).skip(skip).limit(limit).to_list(limit)
    return {"total": total, "showing": len(records), "suggestions": records}


def _analyze_vendor_feedback(vendor_no: str, feedback: List[Dict]) -> List[Dict]:
    suggestions = []
    now = datetime.now(timezone.utc).isoformat()
    vendor_name = feedback[0].get("vendor_name", "") if feedback else ""

    vendor_match_issues = []
    po_issues = []
    amount_issues = []
    dup_issues = []

    for fb in feedback:
        fields = fb.get("disagreed_fields") or []
        if "vendor_match" in fields:
            vendor_match_issues.append(fb)
        if "po_reference" in fields:
            po_issues.append(fb)
        if "amount_range" in fields:
            amount_issues.append(fb)
        if "duplicate" in fields:
            dup_issues.append(fb)

    # Vendor alias
    thresh = AP_DEFAULT_THRESHOLDS["add_vendor_alias"]
    if len(vendor_match_issues) >= thresh:
        suggestions.append(_make(
            "add_vendor_alias", vendor_no, vendor_name,
            f"Reviewer disagreed with vendor match {len(vendor_match_issues)} time(s)",
            min(0.90, 0.3 + len(vendor_match_issues) * 0.15),
            [fb.get("document_id") for fb in vendor_match_issues], len(vendor_match_issues), now,
        ))
    elif vendor_match_issues:
        suggestions.append(_make(
            "add_vendor_alias", vendor_no, vendor_name,
            "Single vendor-match disagreement — weak evidence", 0.25,
            [vendor_match_issues[0].get("document_id")], 1, now, status="insufficient_evidence",
        ))

    # PO/reference
    if len(po_issues) >= thresh:
        suggestions.append(_make(
            "add_accepted_po_behavior", vendor_no, vendor_name,
            f"PO/reference pattern disagreed {len(po_issues)} time(s)",
            min(0.85, 0.3 + len(po_issues) * 0.15),
            [fb.get("document_id") for fb in po_issues], len(po_issues), now,
        ))

    # Amount tolerance
    if len(amount_issues) >= thresh:
        suggestions.append(_make(
            "widen_amount_tolerance", vendor_no, vendor_name,
            f"Amount flagging disagreed {len(amount_issues)} time(s)",
            min(0.80, 0.3 + len(amount_issues) * 0.12),
            [fb.get("document_id") for fb in amount_issues], len(amount_issues), now,
        ))

    # Variability
    total = len(feedback)
    if total >= AP_DEFAULT_THRESHOLDS["increase_vendor_variability"]:
        suggestions.append(_make(
            "increase_vendor_variability", vendor_no, vendor_name,
            f"{total} total disagreements suggest higher variability than profile captures",
            min(0.80, 0.3 + total * 0.10),
            [fb.get("document_id") for fb in feedback[:5]], total, now,
        ))

    return suggestions


def _make(stype, vno, vname, evidence, conf, docs, count, now, status="pending"):
    return {
        "suggestion_id": str(uuid.uuid4())[:12],
        "suggestion_type": stype,
        "vendor_no": vno,
        "vendor_name": vname,
        "supporting_documents": docs[:10],
        "supporting_feedback_count": count,
        "evidence_summary": evidence,
        "confidence": round(conf, 4),
        "status": status,
        "fingerprint": f"{vno}:{stype}",
        "created_at": now,
        "updated_at": now,
    }
