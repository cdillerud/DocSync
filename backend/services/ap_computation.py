"""
GPI Document Hub - AP Computation Helpers

Authoritative implementations of AP invoice validation, status determination,
draft eligibility, and legacy draft-candidate computation, extracted from
server.py during the "Orchestration Extraction" remediation pass.

All functions are pure (no DB or API calls) — they operate on parameters only.
"""

import logging
from typing import Dict, Tuple

from deps import ENABLE_CREATE_DRAFT_HEADER
from models.document_types import DRAFT_CREATION_CONFIG

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# AP Validation
# ---------------------------------------------------------------------------

def compute_ap_validation(
    document_type: str,
    vendor_normalized: str,
    invoice_number_clean: str,
    amount_float: float,
    po_number_clean: str,
    ai_confidence: float,
    possible_duplicate: bool = False,
) -> Dict:
    """
    Compute AP invoice validation result.

    Returns a dict with:
      draft_candidate (bool), validation_errors (list), validation_warnings (list),
      confidence_grade (str), completeness_score (float)
    """
    errors = []
    warnings = []

    # Required fields
    if not vendor_normalized:
        errors.append("Missing vendor name")
    if not invoice_number_clean:
        errors.append("Missing invoice number")
    if amount_float is None or amount_float == 0:
        errors.append("Missing or zero amount")

    # Confidence check
    if ai_confidence < 0.7:
        errors.append(f"Low AI confidence: {ai_confidence:.0%}")
    elif ai_confidence < 0.85:
        warnings.append(f"Moderate AI confidence: {ai_confidence:.0%}")

    # Duplicate check
    if possible_duplicate:
        warnings.append("Possible duplicate invoice detected")

    # PO validation
    if not po_number_clean:
        warnings.append("No PO number extracted")

    # Completeness score
    fields_present = sum([
        bool(vendor_normalized),
        bool(invoice_number_clean),
        bool(amount_float),
        bool(po_number_clean),
    ])
    completeness = fields_present / 4.0

    # Confidence grade
    if ai_confidence >= 0.92:
        grade = "HIGH"
    elif ai_confidence >= 0.80:
        grade = "MEDIUM"
    elif ai_confidence >= 0.70:
        grade = "LOW"
    else:
        grade = "VERY_LOW"

    draft_candidate = len(errors) == 0 and ai_confidence >= 0.80

    return {
        "draft_candidate": draft_candidate,
        "validation_errors": errors,
        "validation_warnings": warnings,
        "confidence_grade": grade,
        "completeness_score": round(completeness, 2),
    }


# ---------------------------------------------------------------------------
# AP Status Determination
# ---------------------------------------------------------------------------

def compute_ap_status(
    vendor_match: dict,
    validation_result: dict,
    duplicate_result: dict,
) -> str:
    """
    Determine AP processing status based on matching, validation, and duplicate results.

    Returns one of:
      "ReadyForReview", "NeedsVendorReview", "NeedsDataCorrection",
      "PossibleDuplicate", "ReadyForApproval"
    """
    if duplicate_result and duplicate_result.get("possible_duplicate"):
        return "PossibleDuplicate"

    if not vendor_match or not vendor_match.get("vendor_canonical"):
        return "NeedsVendorReview"

    if validation_result and validation_result.get("validation_errors"):
        return "NeedsDataCorrection"

    if validation_result and validation_result.get("draft_candidate"):
        return "ReadyForApproval"

    return "ReadyForReview"


# ---------------------------------------------------------------------------
# Draft Candidate (legacy wrapper)
# ---------------------------------------------------------------------------

def compute_draft_candidate_flag(
    document_type: str,
    extracted_fields: dict,
    canonical_fields: dict,
    ai_confidence: float,
) -> Dict:
    """
    Legacy wrapper for backward compatibility.
    Delegates to compute_ap_validation.
    """
    vendor_normalized = canonical_fields.get("vendor_normalized")
    invoice_number_clean = canonical_fields.get("invoice_number_clean")
    amount_float = canonical_fields.get("amount_float")
    po_number_clean = canonical_fields.get("po_number_clean")

    result = compute_ap_validation(
        document_type=document_type,
        vendor_normalized=vendor_normalized,
        invoice_number_clean=invoice_number_clean,
        amount_float=amount_float,
        po_number_clean=po_number_clean,
        ai_confidence=ai_confidence,
        possible_duplicate=False,
    )

    return {
        "draft_candidate": result["draft_candidate"],
        "draft_candidate_reason": result["validation_errors"] + result["validation_warnings"],
        "draft_candidate_score": 100.0 if result["draft_candidate"] else 0.0,
    }


# ---------------------------------------------------------------------------
# Draft Creation Eligibility
# ---------------------------------------------------------------------------

def is_eligible_for_draft_creation(
    job_type: str,
    match_method: str,
    match_score: float,
    ai_confidence: float,
    validation_results: dict,
    doc: dict,
) -> Tuple[bool, str]:
    """
    Check if a document meets ALL preconditions for draft creation.

    PRECONDITIONS (ALL must be true):
      1. Feature flag ENABLE_CREATE_DRAFT_HEADER is true
      2. Job type is AP_Invoice
      3. match_method is in eligible methods
      4. match_score >= threshold
      5. AI confidence >= threshold
      6. All validations passed
      7. Not already linked to BC
      8. No existing bc_record_id

    Returns:
        (is_eligible, reason)
    """
    config = DRAFT_CREATION_CONFIG

    if not ENABLE_CREATE_DRAFT_HEADER:
        return (False, "Feature flag ENABLE_CREATE_DRAFT_HEADER is disabled")

    if job_type != "AP_Invoice":
        return (False, f"Draft creation only supported for AP_Invoice, got {job_type}")

    if match_method not in config["eligible_match_methods"]:
        return (
            False,
            f"Match method '{match_method}' not eligible for draft "
            f"(requires: {config['eligible_match_methods']})",
        )

    if match_score < config["min_match_score_for_draft"]:
        return (
            False,
            f"Match score {match_score:.2%} below draft threshold "
            f"{config['min_match_score_for_draft']:.2%}",
        )

    if ai_confidence < config["min_confidence_for_draft"]:
        return (
            False,
            f"AI confidence {ai_confidence:.2%} below draft threshold "
            f"{config['min_confidence_for_draft']:.2%}",
        )

    if not validation_results.get("all_passed", False):
        failed_checks = [
            c["check_name"]
            for c in validation_results.get("checks", [])
            if not c.get("passed", True) and c.get("required", True)
        ]
        return (False, f"Validation failed: {', '.join(failed_checks)}")

    for check in validation_results.get("checks", []):
        if check["check_name"] == "duplicate_check" and not check.get("passed", True):
            return (False, "Duplicate invoice check failed - hard stop")
        if check["check_name"] == "vendor_match" and not check.get("passed", True):
            return (False, "Vendor match failed - cannot create draft without matched vendor")

    if doc.get("status") == "LinkedToBC":
        return (False, "Document already linked to BC - no draft needed")

    if doc.get("bc_record_id"):
        return (False, f"BC record already exists: {doc.get('bc_record_id')} - idempotency guard")

    return (True, "All preconditions met for draft creation")
