"""
GPI Document Hub - Autonomous Document Routing Service (Auto-Clear Gate)

Evaluates processed documents and assigns a routing decision:
  - auto_process : high-confidence, all checks passed → skip manual review
  - review       : moderate confidence or minor gaps → human review needed
  - blocked      : critical data missing or validation failures → cannot proceed

The service is called after the intelligence generation step in the pipeline
and writes routing_status, routing_reasons, routing_score, and routing_timestamp
to the document record.

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
from typing import Any, Dict, List, Optional, Tuple

from models.document_types import DEFAULT_JOB_TYPES

logger = logging.getLogger("document_routing")

# ---------------------------------------------------------------------------
# Routing status constants
# ---------------------------------------------------------------------------

ROUTE_AUTO_PROCESS = "auto_process"
ROUTE_REVIEW = "review"
ROUTE_BLOCKED = "blocked"

# Score thresholds
THRESHOLD_AUTO_PROCESS = 75
THRESHOLD_REVIEW = 40


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

def evaluate_routing(
    doc: Dict[str, Any],
    intelligence: Optional[Dict[str, Any]] = None,
    validation_results: Optional[Dict[str, Any]] = None,
) -> Dict[str, Any]:
    """Evaluate a document and return a routing decision.

    Args:
        doc: The hub_documents record (must include extracted_fields, ai_confidence, etc.).
        intelligence: The document_intelligence_results record (optional enrichment).
        validation_results: BC validation results dict (optional).

    Returns:
        dict with keys:
          routing_status   : "auto_process" | "review" | "blocked"
          routing_reasons  : list[str] — human-readable reasons
          routing_score    : int 0-100
          routing_timestamp: ISO-8601 string
    """
    score = 0
    reasons: List[str] = []

    # Resolve key fields from doc + intelligence
    confidence = _resolve_confidence(doc, intelligence)
    doc_type = _resolve_doc_type(doc, intelligence)
    extracted = _resolve_extracted_fields(doc, intelligence)
    val_results = validation_results or doc.get("validation_results") or (intelligence or {}).get("validation_results")

    # --- Rule 1: Classification confidence (max 35 pts) ---
    score += _score_confidence(confidence, reasons)

    # --- Rule 2: Required-field completeness (max 30 pts) ---
    score += _score_required_fields(doc_type, extracted, reasons)

    # --- Rule 3: Validation results (max 15 pts) ---
    score += _score_validation(val_results, reasons)

    # --- Rule 4: Duplicate detection (max 0 pts, penalty only) ---
    score += _score_duplicates(doc, reasons)

    # --- Rule 5: Vendor / customer resolution (max 10 pts) ---
    score += _score_entity_resolution(doc, intelligence, reasons)

    # --- Rule 6: Optional-field bonus (max 10 pts) ---
    score += _score_optional_fields(doc_type, extracted, reasons)

    # Clamp
    score = max(0, min(score, 100))

    # Determine status
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
    """Evaluate and persist the routing decision for a document.

    Fetches the document and its intelligence result from the DB,
    runs evaluate_routing, and writes the result back to hub_documents.

    Returns the routing result dict.
    """
    from deps import get_db

    db = get_db()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise ValueError(f"Document not found: {doc_id}")

    # Fetch intelligence result if available
    intelligence = await db.document_intelligence_results.find_one(
        {"document_id": doc_id}, {"_id": 0}
    )

    result = evaluate_routing(doc, intelligence)

    # Persist to hub_documents
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

    logger.info(
        "[Routing] doc=%s status=%s score=%d reasons=%s",
        doc_id, result["routing_status"], result["routing_score"],
        result["routing_reasons"],
    )
    return result


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
    for r in raw:
        key = r["_id"] or "unrouted"
        counts[key] = {
            "count": r["count"],
            "avg_score": round(r.get("avg_score") or 0, 1),
        }

    total = sum(v["count"] for v in counts.values())
    return {
        "total": total,
        "counts": counts,
    }


# ---------------------------------------------------------------------------
# Scoring helpers (pure functions — no DB access)
# ---------------------------------------------------------------------------

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
        # Try common mappings
        for k, v in DEFAULT_JOB_TYPES.items():
            if k.upper().replace("_", "") == doc_type.upper().replace("_", ""):
                cfg = v
                break
    if not cfg:
        cfg = DEFAULT_JOB_TYPES.get("AP_Invoice", {})
    return cfg.get("required_extractions", [])


def _get_optional_fields(doc_type: str) -> List[str]:
    cfg = DEFAULT_JOB_TYPES.get(doc_type)
    if not cfg:
        for k, v in DEFAULT_JOB_TYPES.items():
            if k.upper().replace("_", "") == doc_type.upper().replace("_", ""):
                cfg = v
                break
    if not cfg:
        cfg = DEFAULT_JOB_TYPES.get("AP_Invoice", {})
    return cfg.get("optional_extractions", [])


# --- Individual scorers ---

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
        return 30  # No requirements defined → full marks

    present = 0
    missing = []
    for f in required:
        val = extracted.get(f)
        if val and (not isinstance(val, str) or val.strip()):
            present += 1
        else:
            missing.append(f)

    if missing:
        for f in missing:
            reasons.append(f"missing_required_{f}")

    ratio = present / len(required)
    return int(30 * ratio)


def _score_validation(val_results: Optional[Dict], reasons: List[str]) -> int:
    """Max 15 points."""
    if not val_results:
        reasons.append("no_validation_results")
        return 5  # Not validated yet — partial credit

    if val_results.get("all_passed"):
        return 15

    failed_checks = [
        c.get("check_name") or c.get("check")
        for c in val_results.get("checks", [])
        if not c.get("passed") and c.get("required", True)
    ]
    if failed_checks:
        for c in failed_checks[:3]:
            reasons.append(f"validation_failed_{c}")
        return 0

    # Some non-required checks failed — partial credit
    return 8


def _score_duplicates(doc: Dict, reasons: List[str]) -> int:
    """Penalty-only: 0 or negative."""
    if doc.get("possible_duplicate") or doc.get("is_duplicate"):
        reasons.append("possible_duplicate")
        return -15
    return 0


def _score_entity_resolution(doc: Dict, intel: Optional[Dict], reasons: List[str]) -> int:
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

    # If neither resolved, small penalty/reason
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
    for f in optional:
        val = extracted.get(f)
        if val and (not isinstance(val, str) or val.strip()):
            present += 1

    return int(10 * (present / len(optional)))
