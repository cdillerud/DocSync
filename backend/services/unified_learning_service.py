"""
GPI Document Hub — Unified Learning Stack

Single parameterized implementation for both AP Invoice and Sales Order
learning pipelines. Replaces 8 duplicate service files with one.

Each pipeline is configured via a LearningConfig that specifies:
  - entity type (vendor vs customer)
  - collection names (suggestions, feedback, profiles, audit)
  - entity field names

All functions accept a LearningConfig as their first parameter.
The old AP/Sales-specific files become thin wrappers calling this service.

GOVERNED WORKFLOW: No silent or automatic profile changes.
ANALYSIS ONLY (impact review): Never changes thresholds or workflow.
"""

import logging
from collections import Counter, defaultdict
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from deps import get_db

logger = logging.getLogger(__name__)


# ═══════════════════════════════════════════════════════════════════════════
# Configuration
# ═══════════════════════════════════════════════════════════════════════════

@dataclass
class LearningConfig:
    """Pipeline-specific configuration for the unified learning stack."""
    entity_type: str              # "vendor" or "customer"
    entity_field: str             # "vendor_no" or "customer_no"
    entity_name_field: str        # "vendor_name" or "customer_name"
    suggestions_collection: str   # "ap_learning_suggestions" or "so_learning_suggestions"
    feedback_collection: str      # "ap_reviewer_feedback" or "so_reviewer_feedback"
    profile_collection: str       # "vendor_invoice_profiles" or "customer_posting_profiles"
    audit_collection: str         # "ap_learning_apply_audit" or "so_learning_apply_audit"
    label: str = ""               # "AP Invoice" or "Sales Order" (display)


AP_CONFIG = LearningConfig(
    entity_type="vendor",
    entity_field="vendor_no",
    entity_name_field="vendor_name",
    suggestions_collection="ap_learning_suggestions",
    feedback_collection="ap_reviewer_feedback",
    profile_collection="vendor_invoice_profiles",
    audit_collection="ap_learning_apply_audit",
    label="AP Invoice",
)

SALES_CONFIG = LearningConfig(
    entity_type="customer",
    entity_field="customer_no",
    entity_name_field="customer_name",
    suggestions_collection="so_learning_suggestions",
    feedback_collection="so_reviewer_feedback",
    profile_collection="customer_posting_profiles",
    audit_collection="so_learning_apply_audit",
    label="Sales Order",
)


# ═══════════════════════════════════════════════════════════════════════════
# Suggestion Lifecycle (approve / reject / apply)
# ═══════════════════════════════════════════════════════════════════════════

VALID_TRANSITIONS = {
    "pending":               {"approved", "rejected"},
    "insufficient_evidence": {"approved", "rejected"},
    "approved":              {"applied", "rejected"},
    "rejected":              {"pending"},
    "applied":               set(),
}


async def approve_suggestion(
    db, cfg: LearningConfig, suggestion_id: str, approver: str,
) -> Dict[str, Any]:
    """Move a suggestion to approved status."""
    return await _transition(db, cfg, suggestion_id, "approved", approver)


async def reject_suggestion(
    db, cfg: LearningConfig, suggestion_id: str, approver: str,
) -> Dict[str, Any]:
    """Move a suggestion to rejected status."""
    return await _transition(db, cfg, suggestion_id, "rejected", approver)


async def apply_suggestion(
    db, cfg: LearningConfig, suggestion_id: str, applier: str,
) -> Dict[str, Any]:
    """
    Apply an approved suggestion to the entity's profile.

    Delegates to each pipeline's own mutation handlers rather than a
    generic flat $set: AP's (_add_vendor_alias / _widen_amount /
    _relax_po / _add_accepted_ref / _increase_variability) and Sales'
    (_add_to_list / _add_uom_for_item / _widen_amount_range /
    _revise_po / _increase_variability) compute the change from live
    profile state and no-op safely when nothing needs to change --
    a stored flat "mutation" snapshot cannot do either of those.
    Each delegate records its own before/after audit trail.
    """
    if cfg.label == "AP Invoice":
        from services.ap_invoice_learning_suggestion_apply_service import apply_ap_suggestion
        return await apply_ap_suggestion(db, suggestion_id, applier)

    if cfg.label == "Sales Order":
        from services.sales_order_learning_suggestion_apply_service import apply_suggestion as _apply_so_suggestion
        return await _apply_so_suggestion(db, suggestion_id, applier)

    return {"error": f"apply_suggestion: no handler wired for pipeline '{cfg.label}'"}


async def _transition(
    db, cfg: LearningConfig, suggestion_id: str, target: str, actor: str,
) -> Dict[str, Any]:
    """Generic state transition for suggestion lifecycle."""
    coll = db[cfg.suggestions_collection]
    suggestion = await coll.find_one({"suggestion_id": suggestion_id}, {"_id": 0})
    if not suggestion:
        return {"error": "Suggestion not found"}

    current = suggestion.get("status", "pending")
    allowed = VALID_TRANSITIONS.get(current, set())
    if target not in allowed:
        return {"error": f"Cannot transition from '{current}' to '{target}'. Allowed: {allowed}"}

    now = datetime.now(timezone.utc).isoformat()
    update = {"status": target, f"{target}_by": actor, f"{target}_at": now}
    await coll.update_one({"suggestion_id": suggestion_id}, {"$set": update})

    logger.info("[Learning] %s suggestion %s: %s → %s by %s", cfg.label, suggestion_id, current, target, actor)
    return {"status": target, "suggestion_id": suggestion_id, "previous": current}


# ═══════════════════════════════════════════════════════════════════════════
# Feedback Analysis & Suggestion Generation
# ═══════════════════════════════════════════════════════════════════════════

async def generate_suggestions(
    db, cfg: LearningConfig, limit: int = 100,
) -> Dict[str, Any]:
    """
    Analyze reviewer feedback and generate candidate profile-learning
    suggestions for this pipeline.

    Delegates to each pipeline's own purpose-built pattern analyzer
    (AP: vendor-match / PO / amount / variability signals; Sales:
    ship-to / item / UOM / amount / PO / variability signals, with
    drift-risk-aware thresholds). Each analyzer emits the specific
    suggestion_type values its own apply-side handler knows how to
    act on -- a generic "field disagreed N times" signal does not
    carry enough information to safely produce a profile change.
    """
    if cfg.label == "AP Invoice":
        from services.ap_invoice_feedback_learning_service import generate_ap_learning_suggestions
        return await generate_ap_learning_suggestions(db, limit=limit)

    if cfg.label == "Sales Order":
        from services.sales_order_feedback_learning_service import generate_learning_suggestions as _generate_so_suggestions
        return await _generate_so_suggestions(db, limit=limit)

    return {"error": f"generate_suggestions: no analyzer wired for pipeline '{cfg.label}'"}


async def get_suggestions(
    db, cfg: LearningConfig,
    status: Optional[str] = None,
    entity_no: Optional[str] = None,
    suggestion_type: Optional[str] = None,
    limit: int = 50, skip: int = 0,
) -> Dict[str, Any]:
    """Retrieve suggestions with optional filters."""
    query: Dict[str, Any] = {}
    if status:
        query["status"] = status
    if entity_no:
        query[cfg.entity_field] = entity_no
    if suggestion_type:
        query["suggestion_type"] = suggestion_type

    coll = db[cfg.suggestions_collection]
    total = await coll.count_documents(query)
    items = await coll.find(query, {"_id": 0}).sort("created_at", -1).skip(skip).limit(limit).to_list(limit)

    return {"total": total, "showing": len(items), "suggestions": items}


async def get_suggestion_by_id(
    db, cfg: LearningConfig, suggestion_id: str,
) -> Optional[Dict[str, Any]]:
    """Retrieve a single suggestion by ID."""
    return await db[cfg.suggestions_collection].find_one(
        {"suggestion_id": suggestion_id}, {"_id": 0},
    )


# ═══════════════════════════════════════════════════════════════════════════
# Impact Review
# ═══════════════════════════════════════════════════════════════════════════

async def run_impact_review(
    db, cfg: LearningConfig,
    date_from: Optional[str] = None,
    date_to: Optional[str] = None,
    entity_no: Optional[str] = None,
    suggestion_type: Optional[str] = None,
    applied_by: Optional[str] = None,
) -> Dict[str, Any]:
    """Compare pre-apply vs post-apply outcomes for applied suggestions."""
    match: Dict[str, Any] = {"status": "applied"}
    if entity_no:
        match[cfg.entity_field] = entity_no
    if suggestion_type:
        match["suggestion_type"] = suggestion_type
    if applied_by:
        match["applied_by"] = applied_by

    applied = await db[cfg.suggestions_collection].find(match, {"_id": 0}).to_list(500)
    if not applied:
        return {"total_applied": 0, "message": f"No applied {cfg.label} suggestions found"}

    affected = list({s.get(cfg.entity_field) for s in applied if s.get(cfg.entity_field)})
    all_feedback = await db[cfg.feedback_collection].find(
        {cfg.entity_field: {"$in": affected}}, {"_id": 0}
    ).to_list(5000)

    by_type = defaultdict(lambda: {"pre": [], "post": [], "applied_count": 0})
    by_entity = defaultdict(lambda: {"pre": [], "post": [], "suggestions": []})
    improved, no_change, regressed = [], [], []

    for suggestion in applied:
        eno = suggestion.get(cfg.entity_field, "")
        stype = suggestion.get("suggestion_type", "")
        applied_at = suggestion.get("applied_at", "")

        entity_fb = [fb for fb in all_feedback if fb.get(cfg.entity_field) == eno]
        pre = [fb for fb in entity_fb if (fb.get("timestamp") or "") < applied_at]
        post = [fb for fb in entity_fb if (fb.get("timestamp") or "") >= applied_at]

        by_type[stype]["pre"].extend(pre)
        by_type[stype]["post"].extend(post)
        by_type[stype]["applied_count"] += 1

        by_entity[eno]["pre"].extend(pre)
        by_entity[eno]["post"].extend(post)
        by_entity[eno]["suggestions"].append(suggestion)

        pre_rate = _agreement_rate(pre)
        post_rate = _agreement_rate(post)
        delta = post_rate - pre_rate if pre_rate is not None and post_rate is not None else None

        entry = {
            "suggestion_id": suggestion.get("suggestion_id"),
            "suggestion_type": stype,
            cfg.entity_field: eno,
            cfg.entity_name_field: suggestion.get(cfg.entity_name_field, ""),
            "applied_at": applied_at,
            "pre_feedback_count": len(pre),
            "post_feedback_count": len(post),
            "pre_agreement_pct": pre_rate,
            "post_agreement_pct": post_rate,
            "delta": round(delta, 1) if delta is not None else None,
        }

        if delta is not None:
            (improved if delta > 5 else regressed if delta < -5 else no_change).append(entry)
        else:
            no_change.append(entry)

    # Type-level summary
    type_summary = {}
    for stype, data in by_type.items():
        pr = _agreement_rate(data["pre"])
        po = _agreement_rate(data["post"])
        type_summary[stype] = {
            "applied_count": data["applied_count"],
            "pre_feedback": len(data["pre"]),
            "post_feedback": len(data["post"]),
            "pre_agreement_pct": pr,
            "post_agreement_pct": po,
            "delta": round(po - pr, 1) if pr is not None and po is not None else None,
            "pre_top_disagreed": _top_disagreed_fields(data["pre"])[:3],
            "post_top_disagreed": _top_disagreed_fields(data["post"])[:3],
        }

    # Entity-level summary
    entity_summary = []
    for eno, data in sorted(by_entity.items(), key=lambda x: len(x[1]["suggestions"]), reverse=True):
        pr = _agreement_rate(data["pre"])
        po = _agreement_rate(data["post"])
        entity_summary.append({
            cfg.entity_field: eno,
            cfg.entity_name_field: data["suggestions"][0].get(cfg.entity_name_field, "") if data["suggestions"] else "",
            "suggestions_applied": len(data["suggestions"]),
            "pre_agreement_pct": pr,
            "post_agreement_pct": po,
            "delta": round(po - pr, 1) if pr is not None and po is not None else None,
        })

    recs = _build_recommendations(type_summary, improved, regressed, no_change)

    return {
        "pipeline": cfg.label,
        "total_applied": len(applied),
        f"{cfg.entity_type}s_affected": len(affected),
        "improved_count": len(improved),
        "no_change_count": len(no_change),
        "regressed_count": len(regressed),
        "by_suggestion_type": type_summary,
        f"by_{cfg.entity_type}": entity_summary[:20],
        "improved_examples": improved[:5],
        "no_benefit_examples": [e for e in no_change if e.get("post_feedback_count", 0) > 0][:5],
        "regressed_examples": regressed[:5],
        "recommendations": recs,
    }


async def get_impact_details(
    db, cfg: LearningConfig,
    limit: int = 50, skip: int = 0,
    entity_no: Optional[str] = None,
    suggestion_type: Optional[str] = None,
) -> Dict[str, Any]:
    """Per-suggestion impact detail records."""
    match: Dict[str, Any] = {}
    if entity_no:
        match[cfg.entity_field] = entity_no
    if suggestion_type:
        match["suggestion_type"] = suggestion_type

    audits = await db[cfg.audit_collection].find(
        match, {"_id": 0}
    ).sort("applied_at", -1).skip(skip).limit(limit).to_list(limit)

    total = await db[cfg.audit_collection].count_documents(match)
    return {"total": total, "showing": len(audits), "skip": skip, "records": audits}


# ═══════════════════════════════════════════════════════════════════════════
# Confidence Calibration
# ═══════════════════════════════════════════════════════════════════════════

def calibrate_confidence(
    extraction_confidence: float,
    profile_strength: Optional[float] = None,
    feedback_agreement: Optional[float] = None,
    match_score: Optional[float] = None,
) -> Dict[str, Any]:
    """
    Calibrate raw AI confidence using learning signals.

    Combines:
      - Raw extraction confidence (LLM output)
      - Profile strength (how much history exists for this entity)
      - Feedback agreement (how often reviewers agree with AI)
      - Match score (entity resolution confidence)

    Returns adjusted confidence + band + explanation.
    """
    raw = max(0.0, min(1.0, extraction_confidence))
    adjustments = []
    calibrated = raw

    # Profile strength adjustment
    if profile_strength is not None:
        if profile_strength > 0.8:
            boost = 0.05
            calibrated = min(1.0, calibrated + boost)
            adjustments.append(f"Profile strong ({profile_strength:.0%}): +{boost:.0%}")
        elif profile_strength < 0.3:
            penalty = 0.10
            calibrated = max(0.0, calibrated - penalty)
            adjustments.append(f"Profile weak ({profile_strength:.0%}): -{penalty:.0%}")

    # Feedback agreement adjustment
    if feedback_agreement is not None:
        if feedback_agreement > 0.9:
            boost = 0.05
            calibrated = min(1.0, calibrated + boost)
            adjustments.append(f"High agreement ({feedback_agreement:.0%}): +{boost:.0%}")
        elif feedback_agreement < 0.5:
            penalty = 0.15
            calibrated = max(0.0, calibrated - penalty)
            adjustments.append(f"Low agreement ({feedback_agreement:.0%}): -{penalty:.0%}")

    # Match score adjustment
    if match_score is not None:
        if match_score < 0.5:
            penalty = 0.10
            calibrated = max(0.0, calibrated - penalty)
            adjustments.append(f"Weak entity match ({match_score:.0%}): -{penalty:.0%}")

    band = _band(calibrated)

    return {
        "raw_confidence": round(raw, 4),
        "calibrated_confidence": round(calibrated, 4),
        "band": band,
        "adjustments": adjustments,
        "reliable": band in ("high", "very_high"),
    }


async def calibrate_document(
    db, cfg: LearningConfig, document_id: str,
) -> Dict[str, Any]:
    """Calibrate confidence for a specific document using its entity profile."""
    doc = await db.hub_documents.find_one({"id": document_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found"}

    raw = doc.get("ai_confidence", 0.5)

    # Get entity profile strength
    entity_no = doc.get(cfg.entity_field) or doc.get("matched_customer_no") or doc.get("vendor_canonical") or ""
    profile_strength = None
    if entity_no:
        profile = await db[cfg.profile_collection].find_one(
            {"$or": [
                {cfg.entity_field: entity_no},
                {cfg.entity_field.replace("_no", ""): entity_no},
            ]},
            {"_id": 0, "total_orders": 1, "total_invoices": 1, "confidence_tier": 1},
        )
        if profile:
            count = profile.get("total_orders") or profile.get("total_invoices") or 0
            if count >= 50:
                profile_strength = 0.95
            elif count >= 20:
                profile_strength = 0.75
            elif count >= 5:
                profile_strength = 0.5
            else:
                profile_strength = 0.2

    # Get feedback agreement for this entity
    feedback_agreement = None
    if entity_no:
        fb_list = await db[cfg.feedback_collection].find(
            {cfg.entity_field: entity_no}, {"_id": 0, "reviewer_assessment": 1}
        ).limit(50).to_list(50)
        if fb_list:
            correct = sum(1 for fb in fb_list if fb.get("reviewer_assessment") == "correct")
            feedback_agreement = correct / len(fb_list)

    # Match score from validation
    vr = doc.get("validation_results") or {}
    match_score = float(vr.get("match_score", 0)) if vr.get("match_score") else None

    result = calibrate_confidence(raw, profile_strength, feedback_agreement, match_score)
    result["document_id"] = document_id
    result[cfg.entity_field] = entity_no
    result["pipeline"] = cfg.label

    return result


async def batch_calibrate(
    db, cfg: LearningConfig, limit: int = 200,
) -> Dict[str, Any]:
    """Calibrate confidence for a batch of recent documents."""
    docs = await db.hub_documents.find(
        {"document_type": {"$in": _types_for_config(cfg)}},
        {"_id": 0, "id": 1},
    ).sort("created_utc", -1).limit(limit).to_list(limit)

    results = {"total": len(docs), "calibrated": 0, "bands": Counter()}
    for doc in docs:
        try:
            r = await calibrate_document(db, cfg, doc["id"])
            if not r.get("error"):
                results["calibrated"] += 1
                results["bands"][r.get("band", "unknown")] += 1
        except Exception:
            pass

    results["bands"] = dict(results["bands"])
    return results


# ═══════════════════════════════════════════════════════════════════════════
# Cross-Pipeline Unified View
# ═══════════════════════════════════════════════════════════════════════════

async def get_unified_learning_summary(db) -> Dict[str, Any]:
    """
    Single view across both AP and Sales learning pipelines.
    Powers the unified AI Learning Intelligence dashboard.
    """
    ap = await _pipeline_summary(db, AP_CONFIG)
    sales = await _pipeline_summary(db, SALES_CONFIG)

    return {
        "ap_invoice": ap,
        "sales_order": sales,
        "combined": {
            "total_suggestions": ap["total_suggestions"] + sales["total_suggestions"],
            "pending": ap["pending"] + sales["pending"],
            "approved": ap["approved"] + sales["approved"],
            "applied": ap["applied"] + sales["applied"],
            "rejected": ap["rejected"] + sales["rejected"],
            "total_feedback": ap["total_feedback"] + sales["total_feedback"],
            "avg_agreement": _safe_avg(ap.get("agreement_pct"), sales.get("agreement_pct")),
        },
    }


async def _pipeline_summary(db, cfg: LearningConfig) -> Dict[str, Any]:
    """Summary stats for one learning pipeline."""
    suggestions_coll = db[cfg.suggestions_collection]
    feedback_coll = db[cfg.feedback_collection]

    total = await suggestions_coll.count_documents({})
    pending = await suggestions_coll.count_documents({"status": "pending"})
    approved = await suggestions_coll.count_documents({"status": "approved"})
    applied = await suggestions_coll.count_documents({"status": "applied"})
    rejected = await suggestions_coll.count_documents({"status": "rejected"})

    total_fb = await feedback_coll.count_documents({})
    correct_fb = await feedback_coll.count_documents({"reviewer_assessment": "correct"})
    agreement_pct = round(correct_fb / total_fb * 100, 1) if total_fb > 0 else None

    return {
        "pipeline": cfg.label,
        "total_suggestions": total,
        "pending": pending,
        "approved": approved,
        "applied": applied,
        "rejected": rejected,
        "total_feedback": total_fb,
        "agreement_pct": agreement_pct,
    }


# ═══════════════════════════════════════════════════════════════════════════
# Helpers
# ═══════════════════════════════════════════════════════════════════════════

def _agreement_rate(feedback: List[Dict]) -> Optional[float]:
    if not feedback:
        return None
    correct = sum(1 for fb in feedback if fb.get("reviewer_assessment") == "correct")
    return round(correct / len(feedback) * 100, 1)


def _top_disagreed_fields(feedback: List[Dict], top_n: int = 5) -> List[Dict]:
    counter = Counter()
    for fb in feedback:
        if fb.get("reviewer_assessment") in ("incorrect", "partially_correct", "not_helpful"):
            for f in (fb.get("disagreed_fields") or []):
                counter[f] += 1
    return [{"field": f, "count": c} for f, c in counter.most_common(top_n)]


def _build_recommendations(
    type_summary: Dict, improved: List, regressed: List, no_change: List,
) -> List[Dict[str, str]]:
    recs = []
    for stype, data in type_summary.items():
        delta = data.get("delta")
        if delta is not None and delta > 10:
            recs.append({"type": stype, "signal": "positive",
                         "note": f"+{delta}pp agreement — consider lowering evidence threshold for faster adoption"})
        elif delta is not None and delta < -5:
            recs.append({"type": stype, "signal": "investigate",
                         "note": f"{delta}pp agreement drop — review whether applied changes were too broad"})
        elif data.get("post_feedback", 0) == 0:
            recs.append({"type": stype, "signal": "insufficient_data",
                         "note": "No post-apply feedback yet — continue monitoring"})

    if len(improved) > len(regressed) * 2 and improved:
        recs.append({"type": "overall", "signal": "positive",
                     "note": f"{len(improved)} improvements vs {len(regressed)} regressions — learning pipeline is adding value"})
    elif regressed and len(regressed) >= len(improved):
        recs.append({"type": "overall", "signal": "caution",
                     "note": f"{len(regressed)} regressions vs {len(improved)} improvements — review approval criteria"})

    if not recs:
        recs.append({"type": "overall", "signal": "monitoring",
                     "note": "Continue collecting post-apply feedback to build evidence"})
    return recs


def _band(c: float) -> str:
    if c >= 0.95:
        return "very_high"
    if c >= 0.80:
        return "high"
    if c >= 0.60:
        return "medium"
    if c >= 0.40:
        return "low"
    return "very_low"


def _safe_avg(*values) -> Optional[float]:
    valid = [v for v in values if v is not None]
    return round(sum(valid) / len(valid), 1) if valid else None


def _types_for_config(cfg: LearningConfig) -> List[str]:
    if cfg.entity_type == "vendor":
        return ["AP_Invoice", "AP_INVOICE", "PurchaseInvoice", "Purchase_Invoice"]
    return ["SALES_INVOICE", "Sales_Order", "SalesOrder", "SalesInvoice", "Order_Confirmation"]
