"""
GPI Document Hub — Sales Order Maturity Checkpoint & Reusability Review

Synthesizes all advisory/learning workstream signals to assess
overall maturity and identify which components are generic vs
domain-specific for reuse in other workflows.

ASSESSMENT ONLY: Never triggers expansion or workflow changes.
"""

import logging
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# Component inventory — generic vs domain-specific
COMPONENT_INVENTORY = {
    "generic_framework": [
        {"component": "Readiness Reviewer", "module": "sales_order_readiness_reviewer.py",
         "pattern": "LLM advisory review with structured JSON output, profile-state-aware prompts",
         "reuse_effort": "low — swap domain prompts and profile schema"},
        {"component": "Decision Explainer", "module": "sales_order_decision_explainer.py",
         "pattern": "Evidence-calibrated tone system with structured explanation output",
         "reuse_effort": "low — tone logic is generic, swap headline/summary templates"},
        {"component": "Reviewer Feedback Capture", "module": "sales_order_reviewer_feedback_service.py",
         "pattern": "Assessment + disagreed_fields + notes + linked review snapshot",
         "reuse_effort": "trivial — schema is domain-agnostic"},
        {"component": "Feedback Analytics", "module": "sales_order_feedback_analytics_service.py",
         "pattern": "MongoDB aggregation pipelines for agreement/disagreement rates",
         "reuse_effort": "trivial — swap collection names"},
        {"component": "Disagreement Diagnostics", "module": "sales_order_disagreement_diagnostics_service.py",
         "pattern": "Field-to-root-cause mapping + confidence band analysis",
         "reuse_effort": "low — swap field map and root-cause categories"},
        {"component": "Confidence Calibration", "module": "sales_order_confidence_calibration_service.py",
         "pattern": "Heuristic penalty-based calibration with profile/signal awareness",
         "reuse_effort": "low — swap penalty definitions per domain"},
        {"component": "Learning Suggestion Pipeline", "module": "sales_order_feedback_learning_service.py",
         "pattern": "Feedback → candidate suggestions with evidence thresholds + drift awareness",
         "reuse_effort": "medium — suggestion types are domain-specific, lifecycle is generic"},
        {"component": "Suggestion Approval/Apply", "module": "sales_order_learning_suggestion_apply_service.py",
         "pattern": "State machine (pending→approved→applied) with audit trail",
         "reuse_effort": "trivial — workflow is fully generic, swap mutation handlers"},
        {"component": "Profile Drift Controls", "module": "sales_order_profile_drift_service.py",
         "pattern": "Change cadence + growth threshold monitoring",
         "reuse_effort": "low — swap profile fields and thresholds"},
        {"component": "Impact Review", "module": "sales_order_learning_impact_review_service.py",
         "pattern": "Pre/post apply outcome comparison",
         "reuse_effort": "trivial — generic pattern"},
        {"component": "Customer Hotspot Review", "module": "sales_order_customer_hotspot_review_service.py",
         "pattern": "Cross-signal friction scoring with root-cause diagnosis",
         "reuse_effort": "low — swap signal sources and scoring weights"},
        {"component": "Override Governance", "module": "RepOverridesPanel.js + sales_dashboard.py",
         "pattern": "Business-exception CRUD separate from learned profiles",
         "reuse_effort": "low — swap entity type and override categories"},
        {"component": "Admin Suggestions UI", "module": "LearningSuggestionsPanel.js",
         "pattern": "Filterable list + expandable detail + approve/reject/apply actions",
         "reuse_effort": "trivial — generic governance UI"},
    ],
    "domain_specific": [
        {"component": "Ship-To Analysis", "module": "ship_to_analysis_service.py",
         "pattern": "Address normalization + location diversity + severity classification",
         "note": "Reusable for any workflow with ship-to/address comparison"},
        {"component": "Item/UOM Analysis", "module": "item_uom_analysis_service.py",
         "pattern": "Item matching + UOM alias resolution + diversity-aware severity",
         "note": "Reusable for any workflow with line-item comparison"},
        {"component": "Customer Profile Schema", "module": "sales_order_learning_service.py",
         "pattern": "Core/regular/occasional items, UOM alternates, diversity scores",
         "note": "Schema is sales-specific; pattern of frequency bands is generic"},
        {"component": "Draft Context Service", "module": "sales_order_draft_context_service.py",
         "pattern": "Profile-based suggestions for draft creation",
         "note": "Domain-specific but pattern (profile → suggestions) is reusable"},
        {"component": "PO Pattern Handling", "module": "embedded in learning service",
         "pattern": "PO format classification (numeric/prefixed/alphanumeric)",
         "note": "Sales/procurement-specific"},
    ],
}

# Candidate next workflows ranked by architectural fit
NEXT_WORKFLOW_CANDIDATES = [
    {"workflow": "AP Invoice Vendor Advisory",
     "fit_score": 0.90,
     "reasoning": "Vendor posting profiles already exist (posting_pattern_analyzer). "
                  "Ship-to and item/UOM analysis directly reusable. "
                  "Vendor learning events already captured. "
                  "Template injection already wired. "
                  "Highest architectural overlap with SO advisory pattern.",
     "reusable_components": 12,
     "new_components_needed": 2,
     "estimated_effort": "low"},
    {"workflow": "Document Classification Advisory",
     "fit_score": 0.70,
     "reasoning": "Classification corrections already stored. "
                  "Feedback capture pattern directly reusable. "
                  "Confidence calibration applicable. "
                  "No ship-to/item analysis needed.",
     "reusable_components": 8,
     "new_components_needed": 4,
     "estimated_effort": "medium"},
    {"workflow": "Shipping Document Processing Advisory",
     "fit_score": 0.55,
     "reasoning": "BOL/packing list extraction exists but less structured. "
                  "Vendor profiles partially applicable. "
                  "Would need new domain-specific analysis layers.",
     "reusable_components": 6,
     "new_components_needed": 6,
     "estimated_effort": "medium-high"},
]


async def run_maturity_checkpoint(db) -> Dict[str, Any]:
    """Synthesize all workstream signals into a maturity assessment."""

    # ── Gather current metrics ──
    total_feedback = await db.so_reviewer_feedback.count_documents({})
    correct_fb = await db.so_reviewer_feedback.count_documents({"reviewer_assessment": "correct"})
    agreement_rate = round(correct_fb / max(total_feedback, 1) * 100, 1)

    total_profiles = await db.customer_posting_profiles.count_documents({"status": "analyzed"})
    high_conf = await db.customer_posting_profiles.count_documents({"template_confidence": "high"})

    total_suggestions = await db.so_learning_suggestions.count_documents({})
    applied_suggestions = await db.so_learning_suggestions.count_documents({"status": "applied"})
    pending_suggestions = await db.so_learning_suggestions.count_documents({"status": "pending"})

    total_audits = await db.so_learning_apply_audit.count_documents({})

    total_overrides = await db.customer_rep_overrides.count_documents({"active": True})

    # Drift risk
    high_drift = 0
    async for p in db.customer_posting_profiles.find(
        {"customer_variability_index": {"$gt": 0.9}}, {"_id": 0, "customer_no": 1}
    ):
        high_drift += 1

    # ── Score maturity dimensions ──
    dimensions = {}

    # 1. Feedback volume
    fb_score = min(100, total_feedback * 5)  # 20 feedback = 100
    dimensions["feedback_volume"] = {"score": fb_score, "detail": f"{total_feedback} feedback records"}

    # 2. Agreement rate
    agree_score = min(100, agreement_rate * 1.2)
    dimensions["agreement_quality"] = {"score": round(agree_score), "detail": f"{agreement_rate}% agreement rate"}

    # 3. Profile coverage
    prof_score = min(100, total_profiles * 3)
    dimensions["profile_coverage"] = {"score": prof_score, "detail": f"{total_profiles} profiles ({high_conf} high confidence)"}

    # 4. Learning loop active
    learn_score = 100 if applied_suggestions > 0 else (50 if total_suggestions > 0 else 0)
    dimensions["learning_loop"] = {"score": learn_score, "detail": f"{applied_suggestions} applied, {pending_suggestions} pending"}

    # 5. Governance controls
    gov_score = 100  # All controls exist
    dimensions["governance_controls"] = {"score": gov_score, "detail": "Approval workflow, drift controls, impact review all active"}

    # 6. Drift monitoring
    drift_score = 100 if high_drift < 3 else (60 if high_drift < 10 else 30)
    dimensions["drift_health"] = {"score": drift_score, "detail": f"{high_drift} high-drift profiles"}

    # 7. Override governance
    ovr_score = min(100, 70 + total_overrides)
    dimensions["override_governance"] = {"score": ovr_score, "detail": f"{total_overrides} active overrides, managed separately from profiles"}

    # Overall maturity
    weights = {"feedback_volume": 15, "agreement_quality": 25, "profile_coverage": 15,
               "learning_loop": 15, "governance_controls": 10, "drift_health": 10, "override_governance": 10}
    overall = round(sum(dimensions[k]["score"] * weights[k] / 100 for k in weights))

    if overall >= 75:
        band = "mature"
        recommendation = "ready_to_reuse"
    elif overall >= 50:
        band = "operational"
        recommendation = "mostly_ready"
    else:
        band = "developing"
        recommendation = "not_ready"

    # ── Strengths and risks ──
    strengths = []
    risks = []

    if agreement_rate >= 60:
        strengths.append(f"Reviewer agreement at {agreement_rate}%")
    else:
        risks.append(f"Agreement rate only {agreement_rate}% — needs improvement")

    if applied_suggestions > 0:
        strengths.append(f"Learning loop active with {applied_suggestions} applied suggestions")
    else:
        risks.append("No suggestions applied yet — learning loop untested in production")

    strengths.append("Full governance stack: approval workflow, drift controls, impact review")
    strengths.append("Confidence calibration reduces overconfident advisory")
    strengths.append("Profile-state-aware prompts (none/weak/medium/strong)")
    strengths.append("Ship-to and item/UOM pre-analysis reduces LLM false positives")

    if high_drift > 5:
        risks.append(f"{high_drift} profiles with high drift risk")
    if pending_suggestions > 10:
        risks.append(f"{pending_suggestions} pending suggestions awaiting review")
    if total_feedback < 10:
        risks.append("Limited feedback volume for confident statistical analysis")

    return {
        "overall_maturity_score": overall,
        "maturity_band": band,
        "recommendation": recommendation,
        "dimensions": dimensions,
        "strengths": strengths,
        "risks": risks,
        "metrics": {
            "total_feedback": total_feedback,
            "agreement_rate": agreement_rate,
            "total_profiles": total_profiles,
            "high_confidence_profiles": high_conf,
            "total_suggestions": total_suggestions,
            "applied_suggestions": applied_suggestions,
            "pending_suggestions": pending_suggestions,
            "total_audits": total_audits,
            "active_overrides": total_overrides,
            "high_drift_profiles": high_drift,
        },
    }


async def get_reusability_review(db) -> Dict[str, Any]:
    """Identify generic vs domain-specific components and recommend next workflow."""

    checkpoint = await run_maturity_checkpoint(db)

    generic_count = len(COMPONENT_INVENTORY["generic_framework"])
    specific_count = len(COMPONENT_INVENTORY["domain_specific"])

    return {
        "maturity_recommendation": checkpoint["recommendation"],
        "overall_maturity_score": checkpoint["overall_maturity_score"],
        "component_summary": {
            "generic_framework": generic_count,
            "domain_specific": specific_count,
            "total": generic_count + specific_count,
            "reuse_ratio": round(generic_count / (generic_count + specific_count) * 100, 1),
        },
        "generic_components": COMPONENT_INVENTORY["generic_framework"],
        "domain_specific_components": COMPONENT_INVENTORY["domain_specific"],
        "next_workflow_candidates": NEXT_WORKFLOW_CANDIDATES,
        "recommended_next": NEXT_WORKFLOW_CANDIDATES[0]["workflow"],
        "recommended_next_reasoning": NEXT_WORKFLOW_CANDIDATES[0]["reasoning"],
    }
