"""Human-resolution provenance for AP routing learning.

This module defines the data contract that turns an AI suggestion plus a human
resolution into trustworthy learning evidence. Merely generating an AI route
never creates authority.
"""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.ap_routing_learning_service import normalize_route_path, normalize_vendor_name

COLLECTION = "ap_routing_review_outcomes"
SOURCE_REVIEWER_CONFIRMATION = "reviewer_confirmation"
SOURCE_REVIEWER_CORRECTION = "reviewer_correction"


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _document_identity(document: Dict[str, Any]) -> str:
    return str(
        document.get("source_item_id")
        or document.get("document_id")
        or document.get("id")
        or document.get("file_name")
        or ""
    ).strip()


def prepare_reviewed_routing_outcome(
    *,
    document: Dict[str, Any],
    ai_decision: Dict[str, Any],
    final_human_route: str,
    reviewer_id: Optional[str] = None,
    resolved_at: Optional[str] = None,
) -> Dict[str, Any]:
    """Create one human-resolved AI-vs-human outcome.

    The final human route is required. The source is derived from whether the
    human confirmed or corrected the AI's proposal. This function does not
    persist anything by itself.
    """
    final_route = normalize_route_path(final_human_route)
    if not final_route:
        raise ValueError("final_human_route is required")

    prediction = ai_decision.get("prediction") or {}
    proposed_route = normalize_route_path(
        ai_decision.get("proposed_route")
        or ai_decision.get("route_path")
        or prediction.get("proposed_route")
    )
    if not proposed_route:
        raise ValueError("AI proposed route is required before a review outcome can become learning evidence")

    accepted = proposed_route == final_route
    source = SOURCE_REVIEWER_CONFIRMATION if accepted else SOURCE_REVIEWER_CORRECTION
    fields = document.get("extracted_fields") or {}
    vendor_name = str(
        document.get("vendor_name")
        or document.get("vendor_canonical")
        or fields.get("vendor")
        or ai_decision.get("vendor_name")
        or ""
    ).strip()
    document_type = str(
        document.get("document_type")
        or document.get("suggested_job_type")
        or fields.get("document_type")
        or ""
    ).strip()
    references = list(
        document.get("references")
        or fields.get("references")
        or prediction.get("bc_refs_used")
        or []
    )
    resolved = str(resolved_at or _now())
    identity = _document_identity(document)
    stable = "|".join([identity, proposed_route, final_route, resolved])

    return {
        "outcome_id": hashlib.sha256(stable.encode("utf-8")).hexdigest(),
        "document_id": identity,
        "source_item_id": str(document.get("source_item_id") or ""),
        "file_name": str(document.get("file_name") or ""),
        "vendor_name": vendor_name,
        "normalized_vendor": normalize_vendor_name(vendor_name),
        "document_type": document_type,
        "references": [str(ref) for ref in references if str(ref).strip()][:24],
        "bc_context": dict(document.get("bc_context") or {}),
        "ai_proposed_route": proposed_route,
        "ai_confidence": float(
            ai_decision.get("confidence")
            or prediction.get("confidence")
            or 0.0
        ),
        "ai_reason": str(
            ai_decision.get("reason")
            or prediction.get("reasoning_summary")
            or ""
        )[:2000],
        "final_human_route": final_route,
        "route_path": final_route,
        "accepted": accepted,
        "corrected": not accepted,
        "human_resolved": True,
        "reviewer_id": str(reviewer_id or ""),
        "resolved_at": resolved,
        "label_source": source,
        "label_weight": 3.0 if not accepted else 1.0,
        "active": True,
        "ai_generated": False,
    }


async def upsert_reviewed_routing_outcome(db, outcome: Dict[str, Any]) -> Dict[str, Any]:
    """Persist a previously prepared human resolution when a write path is authorized."""
    if not outcome.get("human_resolved") or not outcome.get("outcome_id"):
        raise ValueError("only prepared human-resolved outcomes may be persisted")
    await db[COLLECTION].update_one(
        {"outcome_id": outcome["outcome_id"]},
        {"$set": dict(outcome)},
        upsert=True,
    )
    return dict(outcome)


def outcome_as_learning_example(outcome: Dict[str, Any]) -> Dict[str, Any]:
    """Convert a human outcome into retrieval evidence without self-training."""
    if not outcome.get("human_resolved"):
        raise ValueError("unresolved AI predictions cannot become learning examples")
    route = normalize_route_path(outcome.get("final_human_route") or outcome.get("route_path"))
    if not route:
        raise ValueError("human outcome has no final route")
    source = str(outcome.get("label_source") or "")
    if source not in {SOURCE_REVIEWER_CONFIRMATION, SOURCE_REVIEWER_CORRECTION}:
        raise ValueError("outcome does not have reviewer-confirmed provenance")
    result = dict(outcome)
    result["route_path"] = route
    result["label_weight"] = 3.0 if source == SOURCE_REVIEWER_CORRECTION else 1.0
    result["ai_generated"] = False
    result["human_resolved"] = True
    return result
