"""
GPI Document Hub - Autonomous Document Routing Service (Auto-Clear Gate)

Evaluates processed documents and assigns a routing decision:
  - auto_process : high-confidence, all checks passed → skip manual review
  - review       : moderate confidence or minor gaps → human review needed
  - blocked      : critical data missing or validation failures → cannot proceed

The service is called after the intelligence generation step in the pipeline
and writes routing_status, routing_reasons, routing_score, and routing_timestamp
to the document record.

Folder recommendations are phase-aware. A recommendation computed before filing
may initialize the immutable routing_suggestion_snapshot. A recommendation
computed after SharePoint filing is stored separately as routing_gate_snapshot
and is never mislabeled as the original pre-filing decision.

Rules (in evaluation order):
  1. Classification confidence
  2. Required-field completeness
  3. Validation pass/fail
  4. Duplicate detection
  5. Vendor/customer resolution
  6. Optional-field bonus
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

from models.document_types import DEFAULT_JOB_TYPES

logger = logging.getLogger("document_routing")

ROUTE_AUTO_PROCESS = "auto_process"
ROUTE_REVIEW = "review"
ROUTE_BLOCKED = "blocked"

THRESHOLD_AUTO_PROCESS = 75
THRESHOLD_REVIEW = 40


def evaluate_routing(
    doc: Dict[str, Any],
    intelligence: Optional[Dict[str, Any]] = None,
    validation_results: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate a document and return a routing decision."""
    score = 0
    reasons: List[str] = []

    confidence = _resolve_confidence(doc, intelligence)
    doc_type = _resolve_doc_type(doc, intelligence)
    extracted = _resolve_extracted_fields(doc, intelligence)
    val_results = (
        validation_results
        or doc.get("validation_results")
        or (intelligence or {}).get("validation_results")
    )

    score += _score_confidence(confidence, reasons)
    score += _score_required_fields(doc_type, extracted, reasons)
    score += _score_validation(val_results, reasons)
    score += _score_duplicates(doc, reasons)
    score += _score_entity_resolution(doc, intelligence, reasons)
    score += _score_optional_fields(doc_type, extracted, reasons)

    score = max(0, min(score, 100))
    if score >= THRESHOLD_AUTO_PROCESS:
        status = ROUTE_AUTO_PROCESS
    elif score >= THRESHOLD_REVIEW:
        status = ROUTE_REVIEW
    else:
        status = ROUTE_BLOCKED

    return {
        "routing_status": status,
        "routing_reasons": reasons,
        "routing_score": score,
        "routing_timestamp": datetime.now(timezone.utc).isoformat(),
    }


async def route_document(doc_id: str) -> Dict[str, Any]:
    """Evaluate and persist the routing gate for a document.

    If this gate runs before SharePoint filing, it may initialize the immutable
    pre-filing recommendation. If it runs after filing, its recommendation is
    recorded separately and cannot overwrite or impersonate pre-filing history.
    """
    from deps import get_db

    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise ValueError(f"Document not found: {doc_id}")

    intelligence = await db.document_intelligence_results.find_one(
        {"document_id": doc_id}, {"_id": 0}
    )
    result = evaluate_routing(doc, intelligence)

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "routing_status": result["routing_status"],
            "routing_reasons": result["routing_reasons"],
            "routing_score": result["routing_score"],
            "routing_timestamp": result["routing_timestamp"],
            "updated_utc": result["routing_timestamp"],
        }},
    )

    suggestion = None
    try:
        suggestion = await _compute_initial_folder_suggestion(doc, intelligence)
        if suggestion:
            persisted = await _persist_folder_suggestion(
                db=db,
                doc_id=doc_id,
                suggestion=suggestion,
            )
            result.update({
                "suggested_folder": suggestion["folder_path"],
                "suggested_reason": suggestion["reason"],
                "suggestion_source": suggestion["source"],
                "suggestion_timestamp": suggestion["suggested_at"],
                "suggestion_capture_type": suggestion["capture_type"],
                "suggestion_persisted": persisted,
            })
    except Exception as error:
        result["suggestion_capture_error"] = str(error)[:300]
        logger.warning(
            "[Routing] folder suggestion capture failed doc=%s: %s",
            doc_id,
            error,
        )

    logger.info(
        "[Routing] doc=%s status=%s score=%d folder=%s capture=%s persisted=%s reasons=%s",
        doc_id,
        result["routing_status"],
        result["routing_score"],
        (suggestion or {}).get("folder_path", ""),
        (suggestion or {}).get("capture_type", ""),
        result.get("suggestion_persisted", False),
        result["routing_reasons"],
    )
    return result


def _has_filing_evidence(doc: Dict[str, Any]) -> bool:
    """Return True once a document has concrete SharePoint/filed evidence."""
    if any(doc.get(field) for field in (
        "sharepoint_item_id",
        "sharepoint_web_url",
        "filed_at",
        "filed_folder",
        "filed_to",
    )):
        return True

    status_text = f"{doc.get('status', '')} {doc.get('workflow_status', '')}".lower()
    return any(token in status_text for token in (
        "filed",
        "storedinsp",
        "exported",
        "completed",
        "processed",
    )) and bool(doc.get("sharepoint_folder_path") or doc.get("sharepoint_folder"))


async def _compute_initial_folder_suggestion(
    doc: Dict[str, Any],
    intelligence: Optional[Dict[str, Any]],
) -> Optional[Dict[str, Any]]:
    """Compute a phase-aware folder recommendation from enriched evidence."""
    from services.folder_routing_service import route_with_feedback

    routing_doc = dict(doc)
    extracted = dict(doc.get("extracted_fields") or {})
    if intelligence:
        extracted.update(intelligence.get("extracted_fields") or {})
        if intelligence.get("document_type"):
            routing_doc["document_type"] = intelligence["document_type"]
    routing_doc["extracted_fields"] = extracted

    is_international = _is_truthy(routing_doc.get("is_international")) or _is_truthy(
        extracted.get("is_international")
    )
    location_code = (
        routing_doc.get("resolved_location_code")
        or routing_doc.get("location_code")
        or extracted.get("location_code")
        or extracted.get("locationCode")
    )
    freight_direction = (
        routing_doc.get("freight_direction")
        or extracted.get("freight_direction")
    )

    folder_path, reason, details = await route_with_feedback(
        doc=routing_doc,
        is_international=is_international,
        location_code=location_code,
        freight_direction=freight_direction,
    )
    if not folder_path:
        return None

    post_filing = _has_filing_evidence(routing_doc)
    details = details or {}
    return {
        "folder_path": str(folder_path).strip(),
        "reason": str(reason or "").strip(),
        "source": str(details.get("source") or "folder_routing_service"),
        "suggested_at": datetime.now(timezone.utc).isoformat(),
        "capture_type": (
            "post_filing_routing_gate" if post_filing else "pre_filing_routing"
        ),
        "capture_origin": "document_routing_service",
        "details": details,
    }


async def _persist_folder_suggestion(
    db,
    doc_id: str,
    suggestion: Dict[str, Any],
) -> bool:
    """Persist a recommendation without falsifying or overwriting history."""
    if suggestion.get("capture_type") == "post_filing_routing_gate":
        result = await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "routing_gate_snapshot": suggestion,
                "routing_gate_checked_at": suggestion["suggested_at"],
            }},
        )
        return bool(result.modified_count)

    result = await db.hub_documents.update_one(
        {
            "id": doc_id,
            "$or": [
                {"routing_suggestion_snapshot": {"$exists": False}},
                {"routing_suggestion_snapshot": None},
                {"routing_suggestion_snapshot": {}},
            ],
        },
        {"$set": {
            "routing_suggestion_snapshot": suggestion,
            "initial_suggested_folder": suggestion["folder_path"],
            "initial_routing_reason": suggestion["reason"],
            "initial_routing_source": suggestion["source"],
            "initial_routing_suggested_at": suggestion["suggested_at"],
        }},
    )
    return bool(result.modified_count)


# Backward-compatible private name used by earlier tests/imports.
_persist_initial_folder_suggestion = _persist_folder_suggestion


def _is_truthy(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    return str(value or "").strip().lower() in {
        "1", "true", "yes", "y", "international", "intl"
    }


async def get_routing_summary() -> Dict[str, Any]:
    """Return aggregate routing status counts for the dashboard."""
    from deps import get_db

    db = get_db()
    pipeline = [
        {"$group": {
            "_id": "$routing_status",
            "count": {"$sum": 1},
            "avg_score": {"$avg": "$routing_score"},
        }},
    ]
    raw = await db.hub_documents.aggregate(pipeline).to_list(10)

    counts = {}
    for row in raw:
        key = row["_id"] or "unrouted"
        counts[key] = {
            "count": row["count"],
            "avg_score": round(row.get("avg_score") or 0, 1),
        }

    return {
        "total": sum(value["count"] for value in counts.values()),
        "counts": counts,
    }


def _resolve_confidence(doc: Dict, intel: Optional[Dict]) -> float:
    if intel and intel.get("classification_confidence"):
        return float(intel["classification_confidence"])
    return float(doc.get("ai_confidence", 0) or 0)


def _resolve_doc_type(doc: Dict, intel: Optional[Dict]) -> str:
    if intel and intel.get("document_type"):
        return intel["document_type"]
    return doc.get("suggested_job_type") or doc.get("doc_type") or "Unknown"


def _resolve_extracted_fields(doc: Dict, intel: Optional[Dict]) -> Dict:
    if intel and intel.get("extracted_fields"):
        return intel["extracted_fields"]
    return doc.get("extracted_fields") or {}


def _get_required_fields(doc_type: str) -> List[str]:
    """Look up required extraction fields for a document type."""
    cfg = DEFAULT_JOB_TYPES.get(doc_type)
    if not cfg:
        for key, value in DEFAULT_JOB_TYPES.items():
            if key.upper().replace("_", "") == doc_type.upper().replace("_", ""):
                cfg = value
                break
    if not cfg:
        cfg = DEFAULT_JOB_TYPES.get("AP_Invoice", {})
    return cfg.get("required_extractions", [])


def _get_optional_fields(doc_type: str) -> List[str]:
    cfg = DEFAULT_JOB_TYPES.get(doc_type)
    if not cfg:
        for key, value in DEFAULT_JOB_TYPES.items():
            if key.upper().replace("_", "") == doc_type.upper().replace("_", ""):
                cfg = value
                break
    if not cfg:
        cfg = DEFAULT_JOB_TYPES.get("AP_Invoice", {})
    return cfg.get("optional_extractions", [])


def _score_confidence(confidence: float, reasons: List[str]) -> int:
    """Max 35 points."""
    if confidence >= 0.92:
        return 35
    if confidence >= 0.80:
        reasons.append(f"moderate_confidence ({confidence:.0%})")
        return 25
    if confidence >= 0.65:
        reasons.append(f"low_confidence ({confidence:.0%})")
        return 15
    reasons.append(f"very_low_confidence ({confidence:.0%})")
    return 5


def _score_required_fields(doc_type: str, extracted: Dict, reasons: List[str]) -> int:
    """Max 30 points."""
    required = _get_required_fields(doc_type)
    if not required:
        return 30

    present = 0
    missing = []
    for field in required:
        value = extracted.get(field)
        if value and (not isinstance(value, str) or value.strip()):
            present += 1
        else:
            missing.append(field)

    for field in missing:
        reasons.append(f"missing_required_{field}")

    return int(30 * (present / len(required)))


def _score_validation(val_results: Optional[Dict], reasons: List[str]) -> int:
    """Max 15 points."""
    if not val_results:
        reasons.append("no_validation_results")
        return 5

    if val_results.get("all_passed"):
        return 15

    failed_checks = [
        check.get("check_name") or check.get("check")
        for check in val_results.get("checks", [])
        if not check.get("passed") and check.get("required", True)
    ]
    if failed_checks:
        for check_name in failed_checks[:3]:
            reasons.append(f"validation_failed_{check_name}")
        return 0

    return 8


def _score_duplicates(doc: Dict, reasons: List[str]) -> int:
    """Penalty-only: 0 or negative."""
    if doc.get("possible_duplicate") or doc.get("is_duplicate"):
        reasons.append("possible_duplicate")
        return -15
    return 0


def _score_entity_resolution(
    doc: Dict,
    intel: Optional[Dict],
    reasons: List[str],
) -> int:
    """Max 10 points for vendor/customer resolved."""
    points = 0
    has_vendor = bool(
        doc.get("vendor_canonical")
        or doc.get("vendor_id")
        or doc.get("vendor_name_resolved")
    )
    has_customer = bool(
        doc.get("customer_canonical")
        or doc.get("customer_id")
    )

    if has_vendor:
        points += 5
    if has_customer:
        points += 5

    if not has_vendor and not has_customer:
        reasons.append("no_entity_resolved")
        return 0

    return min(points, 10)


def _score_optional_fields(doc_type: str, extracted: Dict, reasons: List[str]) -> int:
    """Max 10 points bonus for optional fields."""
    optional = _get_optional_fields(doc_type)
    if not optional:
        return 0

    present = 0
    for field in optional:
        value = extracted.get(field)
        if value and (not isinstance(value, str) or value.strip()):
            present += 1

    return int(10 * (present / len(optional)))
