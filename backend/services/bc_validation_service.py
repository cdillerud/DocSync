"""
GPI Document Hub - BC Validation Service

Authoritative implementation of validate_bc_match() — validates extracted
document fields against Business Central records.

Extracted from server.py during the "BC Validation Isolation" remediation pass.
Dependencies:
  - deps (config, DB)
  - bc_access (token, company ID, URL builder)
  - document_intel_helpers (field normalization)
  - unified_vendor_matcher (vendor matching)
  - httpx (BC API calls)

server.py retains a thin compatibility wrapper that delegates here.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List

import httpx

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Private helpers — BC-specific normalization & fuzzy scoring
# ---------------------------------------------------------------------------

def _normalize_vendor_name(name: str) -> str:
    """Normalize a vendor/customer name for matching.

    Regex-based suffix removal handles commas, dots, and abbreviations
    (e.g. "ACME, Inc." → "acme").

    NOTE: This differs from reference_helpers.normalize_company_name() which
    uses simple endswith() checks.  Both are preserved to avoid changing
    match outcomes for existing documents.
    """
    if not name:
        return ""
    name = name.lower()
    suffixes = [
        r'\s*,?\s*(inc\.?|incorporated)$',
        r'\s*,?\s*(llc\.?|l\.l\.c\.?)$',
        r'\s*,?\s*(ltd\.?|limited)$',
        r'\s*,?\s*(corp\.?|corporation)$',
        r'\s*,?\s*(co\.?|company)$',
        r'\s*,?\s*(plc\.?)$',
        r'\s*,?\s*(gmbh)$',
        r'\s*,?\s*(ag)$',
    ]
    for suffix in suffixes:
        name = re.sub(suffix, '', name, flags=re.IGNORECASE)
    name = re.sub(r'[^\w\s]', '', name)
    name = re.sub(r'\s+', ' ', name).strip()
    return name


def _calculate_fuzzy_score(name1: str, name2: str) -> float:
    """Token-overlap fuzzy score with BC vendor-code prefix stripping.

    Handles BC names like "TUMALOC - Tumalo Creek" by removing short code
    prefixes before comparison.

    NOTE: This differs from reference_helpers.fuzzy_ratio() which uses
    SequenceMatcher.  Both are preserved to avoid changing match outcomes.
    """
    if not name1 or not name2:
        return 0.0

    def _clean_bc_name(n: str) -> str:
        if ' - ' in n:
            parts = n.split(' - ', 1)
            if len(parts) == 2 and len(parts[0]) <= 10:
                n = parts[1]
        return n

    name1_clean = _clean_bc_name(name1)
    name2_clean = _clean_bc_name(name2)

    tokens1 = set(_normalize_vendor_name(name1_clean).split())
    tokens2 = set(_normalize_vendor_name(name2_clean).split())

    if not tokens1 or not tokens2:
        return 0.0

    intersection = tokens1 & tokens2
    union = tokens1 | tokens2
    base_score = len(intersection) / len(union)

    # Also try original names (in case the code IS the match)
    orig_tokens1 = set(_normalize_vendor_name(name1).split())
    orig_tokens2 = set(_normalize_vendor_name(name2).split())
    orig_intersection = orig_tokens1 & orig_tokens2
    orig_union = orig_tokens1 | orig_tokens2
    orig_score = len(orig_intersection) / len(orig_union) if orig_union else 0

    return max(base_score, orig_score)


# ---------------------------------------------------------------------------
# Extraction quality scoring (pure computation)
# ---------------------------------------------------------------------------

def _compute_extraction_quality(
    normalized_fields: dict,
    extracted_fields: dict,
    job_config: dict,
) -> dict:
    """Compute extraction quality metrics.

    Uses the job-type-specific required/optional field lists and also
    counts total meaningful (non-metadata) fields extracted.
    """
    required_fields = job_config.get("required_extractions", [])
    optional_fields = job_config.get("optional_extractions", [])

    # Count how many required/optional fields are present
    # Check both normalized and extracted, excluding heuristic metadata
    def _has_value(field_name: str) -> bool:
        nv = normalized_fields.get(field_name)
        ev = extracted_fields.get(field_name)
        return bool(nv) or bool(ev)

    required_count = sum(1 for f in required_fields if _has_value(f))
    optional_count = sum(1 for f in optional_fields if _has_value(f))

    # Completeness: weighted score (required=80%, optional=20%)
    req_score = (required_count / len(required_fields)) * 0.8 if required_fields else 0.8
    opt_score = (optional_count / len(optional_fields)) * 0.2 if optional_fields else 0.2
    completeness = req_score + opt_score

    # Total meaningful fields (for the "X/Y fields" display)
    all_defined = required_fields + optional_fields
    all_extracted = sum(1 for f in all_defined if _has_value(f))

    return {
        "vendor_extracted": _has_value("vendor"),
        "invoice_number_extracted": _has_value("invoice_number"),
        "amount_extracted": _has_value("amount"),
        "po_detected": _has_value("po_number"),
        "due_date_extracted": _has_value("due_date"),
        "completeness_score": round(completeness, 2),
        "ready_for_draft_candidate": (
            required_count == len(required_fields) if required_fields else True
        ),
        "required_fields": required_fields,
        "required_extracted": required_count,
        "optional_fields": optional_fields,
        "optional_extracted": optional_count,
        "total_defined": len(all_defined),
        "total_extracted": all_extracted,
    }


# ---------------------------------------------------------------------------
# Customer matching against BC
# ---------------------------------------------------------------------------

async def _match_customer_in_bc(
    customer_name: str,
    strategies: List[str],
    threshold: float,
    token: str,
    company_id: str,
    api_url_fn,
) -> dict:
    """Multi-strategy customer matching against BC.

    Args:
        api_url_fn: callable(path) → full BC API URL for the given resource.
    """
    result: Dict[str, Any] = {
        "matched": False,
        "match_method": None,
        "selected_customer": None,
        "customer_candidates": [],
        "score": 0.0,
    }

    if not customer_name:
        return result

    normalized_input = _normalize_vendor_name(customer_name)

    async with httpx.AsyncClient(timeout=30.0) as c:
        resp = await c.get(
            api_url_fn("customers", company_id),
            headers={"Authorization": f"Bearer {token}"},
            params={"$select": "id,number,displayName", "$top": "500"},
        )

        if resp.status_code != 200:
            return result

        customers = resp.json().get("value", [])
        candidates: list = []

        for customer in customers:
            customer_display = customer.get("displayName", "")
            customer_number = customer.get("number", "")

            if "exact_no" in strategies and customer_number.lower() == customer_name.lower():
                result["matched"] = True
                result["match_method"] = "exact_no"
                result["selected_customer"] = customer
                result["score"] = 1.0
                return result

            if "exact_name" in strategies and customer_display.lower() == customer_name.lower():
                result["matched"] = True
                result["match_method"] = "exact_name"
                result["selected_customer"] = customer
                result["score"] = 1.0
                return result

            if "normalized" in strategies:
                normalized_bc = _normalize_vendor_name(customer_display)
                if normalized_input and normalized_bc == normalized_input:
                    result["matched"] = True
                    result["match_method"] = "normalized"
                    result["selected_customer"] = customer
                    result["score"] = 0.95
                    return result

            if "fuzzy" in strategies:
                score = _calculate_fuzzy_score(customer_name, customer_display)
                if score > 0.3:
                    candidates.append({
                        "customer": customer,
                        "score": score,
                        "display_name": customer_display,
                        "customer_id": customer.get("id"),
                    })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        result["customer_candidates"] = candidates[:5]

        if candidates and candidates[0]["score"] >= threshold:
            result["matched"] = True
            result["match_method"] = "fuzzy"
            result["selected_customer"] = candidates[0]["customer"]
            result["score"] = candidates[0]["score"]
        elif candidates:
            result["matched"] = False
            result["match_method"] = "fuzzy_candidates"
            result["score"] = candidates[0]["score"] if candidates else 0

    return result


# ---------------------------------------------------------------------------
# PO validation helper
# ---------------------------------------------------------------------------

async def _validate_po(
    c: httpx.AsyncClient,
    token: str,
    api_url_fn,
    company_id: str,
    po_number: str,
    validation_results: dict,
    required: bool,
) -> None:
    """Validate a PO number against BC purchaseOrders."""
    try:
        resp = await c.get(
            api_url_fn("purchaseOrders", company_id),
            headers={"Authorization": f"Bearer {token}"},
            params={"$filter": f"number eq '{po_number.replace(chr(39), chr(39)+chr(39))}'"},
        )
    except Exception as e:
        # Network/timeout error — treat as inconclusive, NOT "not found"
        validation_results["warnings"].append({
            "check_name": "po_bc_api_error",
            "details": f"BC API error during PO lookup for '{po_number}': {str(e)[:100]} — treating as unverified",
        })
        if required:
            validation_results["all_passed"] = False
        validation_results["checks"].append({
            "check_name": "po_validation",
            "passed": False,
            "details": f"PO '{po_number}' could not be verified — BC API error",
            "required": required,
        })
        return

    if resp.status_code == 200:
        pos = resp.json().get("value", [])
        if pos:
            validation_results["checks"].append({
                "check_name": "po_validation",
                "passed": True,
                "details": f"Found PO: {po_number}",
                "required": required,
            })
        else:
            if required:
                validation_results["all_passed"] = False
            validation_results["checks"].append({
                "check_name": "po_validation",
                "passed": False,
                "details": f"PO '{po_number}' not found in BC",
                "required": required,
            })
            if not required:
                validation_results["warnings"].append({
                    "check_name": "po_not_found",
                    "details": f"PO '{po_number}' was extracted but not found in BC - requires review",
                })
    else:
        # Non-200 response (400, 401, 429, 500) — inconclusive, NOT "not found"
        if required:
            validation_results["all_passed"] = False
        validation_results["checks"].append({
            "check_name": "po_validation",
            "passed": False,
            "details": f"PO '{po_number}' could not be verified — BC returned {resp.status_code}",
            "required": required,
        })
        validation_results["warnings"].append({
            "check_name": "po_bc_api_error",
            "details": f"BC API returned {resp.status_code} for PO '{po_number}' — needs manual verification",
        })


# ---------------------------------------------------------------------------
# Public API
# ---------------------------------------------------------------------------

async def validate_bc_match(
    job_type: str,
    extracted_fields: dict,
    job_config: dict,
) -> dict:
    """Validate extracted data against Business Central records.

    Returns structured validation results with candidates for review.

    match_method values: exact_no, exact_name, normalized, alias, fuzzy,
                         manual, sales_order_number, none
    """
    result = await _validate_bc_match_inner(job_type, extracted_fields, job_config)

    # Compute UI-facing validation_status from actual check outcomes.
    # all_passed tracks ONLY required failures (for automation).
    # validation_status is the honest summary for UI display:
    #   "pass"  = every check passed
    #   "warn"  = some optional checks failed, all required passed
    #   "fail"  = at least one required check failed
    failed_checks = [c for c in result.get("checks", []) if not c.get("passed", True)]
    required_failures = [c for c in failed_checks if c.get("required", False)]
    if required_failures:
        result["validation_status"] = "fail"
    elif failed_checks:
        result["validation_status"] = "warn"
    else:
        result["validation_status"] = "pass"

    return result


async def _validate_bc_match_inner(
    job_type: str,
    extracted_fields: dict,
    job_config: dict,
) -> dict:
    """Inner implementation of validate_bc_match."""
    from services.document_intel_helpers import normalize_extracted_fields
    from deps import get_db, DEMO_MODE, BC_CLIENT_ID
    from services.bc_access import get_bc_adapter

    normalized_fields = normalize_extracted_fields(extracted_fields)

    validation_results: Dict[str, Any] = {
        "all_passed": True,
        "checks": [],
        "warnings": [],
        "bc_record_id": None,
        "bc_record_info": None,
        "vendor_candidates": [],
        "customer_candidates": [],
        "normalized_fields": normalized_fields,
        "match_method": "none",
        "match_score": 0.0,
        "extraction_quality": _compute_extraction_quality(
            normalized_fields, extracted_fields, job_config,
        ),
    }

    # ---- Extraction quality gate: reject documents with no real data ----
    meaningful_fields = {
        k: v for k, v in extracted_fields.items()
        if v and not k.endswith("_detected_by")
    }
    if not meaningful_fields:
        validation_results["all_passed"] = False
        validation_results["checks"].append({
            "check_name": "extraction_quality_gate",
            "passed": False,
            "details": "No meaningful data extracted from document — cannot validate",
            "required": True,
        })
        return validation_results

    # ---- Demo mode early return ----
    if DEMO_MODE or not BC_CLIENT_ID:
        validation_results["checks"].append({
            "check_name": "demo_mode",
            "passed": True,
            "details": "Running in demo mode - validation simulated",
            "required": False,
        })
        return validation_results

    # ---- Obtain BC credentials via shared adapter ----
    try:
        adapter = get_bc_adapter()
        token = await adapter.get_token()
        if not token:
            validation_results["all_passed"] = False
            validation_results["checks"].append({
                "check_name": "bc_connection",
                "passed": False,
                "details": "Could not obtain BC token",
                "required": True,
            })
            return validation_results

        company_id = await adapter.get_company_id(token)
        if not company_id:
            validation_results["all_passed"] = False
            validation_results["checks"].append({
                "check_name": "bc_connection",
                "passed": False,
                "details": "No BC companies found",
                "required": True,
            })
            return validation_results

        # URL builder shorthand
        def _api_url(resource: str, cid: str = company_id) -> str:
            return adapter.api_url(resource, cid)

        # ---- Config ----
        match_strategies = job_config.get(
            "vendor_match_strategies",
            ["exact_no", "exact_name", "normalized", "fuzzy"],
        )
        match_threshold = job_config.get("vendor_match_threshold", 0.80)
        po_mode = job_config.get("po_validation_mode", "PO_IF_PRESENT")

        db = get_db()

        async with httpx.AsyncClient(timeout=30.0) as c:

            # ============================================================
            # AP_Invoice / Remittance — vendor match + PO + duplicate + freight
            # ============================================================
            if job_type in ("AP_Invoice", "Remittance"):
                vendor_name = (
                    normalized_fields.get("vendor")
                    or extracted_fields.get("vendor", "")
                )

                # If reference intelligence already resolved a canonical vendor, prefer it
                ref_canonical = extracted_fields.get("_vendor_canonical") or ""
                if ref_canonical and not vendor_name:
                    vendor_name = ref_canonical

                if vendor_name:
                    from services.unified_vendor_matcher import match_vendor_unified

                    # Try canonical name first if available, fall back to extracted
                    names_to_try = []
                    if ref_canonical and ref_canonical.lower() != vendor_name.lower():
                        names_to_try.append(ref_canonical)
                    names_to_try.append(vendor_name)

                    unified_result = None
                    for try_name in names_to_try:
                        unified_result = await match_vendor_unified(
                            db, try_name, match_threshold,
                        )
                        if unified_result.get("matched"):
                            break

                    vendor_result: Dict[str, Any] = {
                        "matched": unified_result.get("matched", False),
                        "match_method": unified_result.get("source") or "none",
                        "selected_vendor": None,
                        "vendor_candidates": [],
                        "score": unified_result.get("score", 0.0),
                    }

                    if unified_result.get("matched") and unified_result.get("best_match"):
                        best = unified_result["best_match"]
                        vendor_result["selected_vendor"] = {
                            "id": best.get("vendor_id") or unified_result.get("bc_vendor_id"),
                            "displayName": best.get("name"),
                            "number": best.get("vendor_number") or unified_result.get("bc_vendor_number"),
                        }

                    for m in unified_result.get("all_matches", []):
                        vendor_result["vendor_candidates"].append({
                            "display_name": m.get("name"),
                            "vendor_id": m.get("vendor_id"),
                            "score": m.get("score", 0),
                            "source": m.get("source"),
                        })

                    validation_results["unified_vendor_match"] = {
                        "sources_checked": unified_result.get("sources_checked", []),
                        "is_freight_carrier": unified_result.get("is_freight_carrier", False),
                        "all_matches_count": len(unified_result.get("all_matches", [])),
                    }

                    validation_results["vendor_candidates"] = vendor_result.get("vendor_candidates", [])

                    if vendor_result["matched"]:
                        validation_results["match_method"] = vendor_result["match_method"]
                        validation_results["match_score"] = vendor_result["score"]

                        vendor_display = (
                            vendor_result["selected_vendor"].get("displayName")
                            if vendor_result["selected_vendor"]
                            else vendor_name
                        )
                        validation_results["checks"].append({
                            "check_name": "vendor_match",
                            "passed": True,
                            "details": f"Found vendor via {vendor_result['match_method']}: {vendor_display} (score: {vendor_result['score']:.0%})",
                            "required": True,
                            "match_method": vendor_result["match_method"],
                            "score": vendor_result["score"],
                            "is_freight_carrier": unified_result.get("is_freight_carrier", False),
                        })
                        if vendor_result["selected_vendor"]:
                            validation_results["bc_record_id"] = vendor_result["selected_vendor"].get("id")
                            validation_results["bc_record_info"] = vendor_result["selected_vendor"]
                        
                        # AUTO-LEARN: Save this vendor match as an alias so future lookups
                        # resolve instantly without hitting BC API
                        if vendor_result["score"] >= 0.9 and vendor_name and vendor_result["selected_vendor"]:
                            try:
                                resolved_no = vendor_result["selected_vendor"].get("number", "")
                                resolved_name = vendor_result["selected_vendor"].get("displayName", "")
                                if resolved_no and vendor_name:
                                    import uuid
                                    from services.vendor_name_helpers import normalize_vendor_name
                                    alias_key = normalize_vendor_name(vendor_name).upper()
                                    await db.vendor_aliases.update_one(
                                        {"alias_string": alias_key},
                                        {"$set": {
                                            "alias": alias_key,
                                            "alias_string": alias_key,
                                            "alias_raw": vendor_name,
                                            "normalized_alias": alias_key.lower(),
                                            "vendor_no": resolved_no,
                                            "vendor_name": resolved_name,
                                            "canonical_vendor_id": resolved_no,
                                            "source": "auto_learned",
                                            "match_method": vendor_result["match_method"],
                                            "match_score": vendor_result["score"],
                                            "updated_at": datetime.now(timezone.utc).isoformat(),
                                        },
                                        "$setOnInsert": {
                                            "alias_id": str(uuid.uuid4()),
                                            "created_at": datetime.now(timezone.utc).isoformat(),
                                        }},
                                        upsert=True,
                                    )
                                    logger.info(
                                        "[AutoLearn] Saved vendor alias: '%s' → %s (%s) via %s @ %.0f%%",
                                        vendor_name, resolved_no, resolved_name,
                                        vendor_result["match_method"], vendor_result["score"] * 100,
                                    )
                            except Exception as learn_err:
                                logger.debug("[AutoLearn] Failed to save alias: %s", learn_err)
                    else:
                        validation_results["match_method"] = "none"
                        details = f"No vendor found matching '{vendor_name}' (checked: {', '.join(unified_result.get('sources_checked', []))})"
                        if vendor_result["vendor_candidates"]:
                            top = vendor_result["vendor_candidates"][0]
                            details += f". Best candidate: {top['display_name']} ({top['score']:.0%})"
                        # If vendor was already resolved by ref intel, downgrade to non-required warning
                        check_required = True
                        if ref_canonical and vendor_result["vendor_candidates"]:
                            check_required = False  # Ref intel resolved it — just a warning
                        validation_results["checks"].append({
                            "check_name": "vendor_match",
                            "passed": False,
                            "details": details,
                            "required": check_required,
                            "candidates_available": len(vendor_result["vendor_candidates"]) > 0,
                        })
                        if check_required:
                            validation_results["all_passed"] = False

                # ---- PO validation ----
                po_number = (
                    normalized_fields.get("po_number")
                    or extracted_fields.get("po_number", "")
                )
                # Gather ALL PO candidates from every source
                po_resolution_number = extracted_fields.get("_po_resolution_number", "")
                all_candidates = list(extracted_fields.get("_po_all_candidates", []))
                
                # Filter out the document's own invoice number from PO candidates.
                # An invoice number should never be tried as a PO.
                # NOTE: BOL numbers are NOT filtered — on freight invoices (e.g. Tumalo Creek),
                # the BOL often IS the PO number or references a real PO.
                _exclude_from_po = set()
                inv_num = (
                    normalized_fields.get("invoice_number") or extracted_fields.get("invoice_number")
                    or normalized_fields.get("invoice_number_clean") or ""
                )
                if inv_num:
                    _exclude_from_po.add(str(inv_num).strip())
                    # Also exclude with/without leading zeros (e.g., "0305132" ↔ "305132")
                    _exclude_from_po.add(str(inv_num).strip().lstrip("0") or "0")

                # Build ordered list: AI extraction first, then PO resolution best, then all candidates
                po_candidates_to_check = []
                seen = set()
                for candidate in [po_number, po_resolution_number] + all_candidates:
                    candidate_clean = str(candidate).strip() if candidate else ""
                    candidate_stripped = candidate_clean.lstrip("0") or "0"
                    if candidate_clean and candidate_clean not in seen:
                        seen.add(candidate_clean)
                        # Skip if this is the invoice number itself
                        if candidate_clean in _exclude_from_po or candidate_stripped in _exclude_from_po:
                            logger.info("[PO-Filter] Excluding '%s' from PO candidates (matches invoice number)", candidate_clean)
                            continue
                        po_candidates_to_check.append(candidate_clean)

                if po_mode == "PO_REQUIRED":
                    if not po_candidates_to_check:
                        validation_results["all_passed"] = False
                        validation_results["checks"].append({
                            "check_name": "po_validation",
                            "passed": False,
                            "details": "PO number required but not found in any source (LLM, filename, BOL, text)",
                            "required": True,
                        })
                    else:
                        po_found = False
                        tried = []
                        for candidate_po in po_candidates_to_check:
                            test_result = {"checks": [], "warnings": []}
                            await _validate_po(c, token, _api_url, company_id, candidate_po, test_result, required=True)
                            check = test_result["checks"][-1] if test_result["checks"] else {}
                            tried.append(candidate_po)
                            if check.get("passed"):
                                validation_results["checks"].append(check)
                                po_found = True
                                break
                        if not po_found:
                            # Report primary failure with list of all sources tried
                            await _validate_po(c, token, _api_url, company_id, po_candidates_to_check[0], validation_results, required=True)
                            if len(tried) > 1:
                                validation_results["warnings"].append({
                                    "check_name": "po_multi_source_tried",
                                    "details": f"Tried {len(tried)} PO candidates from all sources: {', '.join(tried[:5])} — none found in BC",
                                })

                elif po_mode == "PO_IF_PRESENT":
                    if po_candidates_to_check:
                        po_found = False
                        tried = []
                        for candidate_po in po_candidates_to_check:
                            test_result = {"checks": [], "warnings": []}
                            await _validate_po(c, token, _api_url, company_id, candidate_po, test_result, required=False)
                            check = test_result["checks"][-1] if test_result["checks"] else {}
                            tried.append(candidate_po)
                            if check.get("passed"):
                                validation_results["checks"].append(check)
                                po_found = True
                                break
                        if not po_found:
                            # PO WAS extracted but NOT found in BC — this MUST block validation
                            # for AP invoices. The document needs manual review.
                            validation_results["all_passed"] = False
                            await _validate_po(c, token, _api_url, company_id, po_candidates_to_check[0], validation_results, required=True)
                            if len(tried) > 1:
                                validation_results["warnings"].append({
                                    "check_name": "po_multi_source_tried",
                                    "details": f"Tried {len(tried)} PO candidates from all sources: {', '.join(tried[:5])} — none found in BC",
                                })
                    else:
                        validation_results["warnings"].append({
                            "check_name": "po_not_present",
                            "details": "No PO number found in any source (LLM, filename, BOL, text) - skipping PO validation",
                        })

                # ---- Duplicate invoice check ----
                invoice_number = (
                    normalized_fields.get("invoice_number")
                    or extracted_fields.get("invoice_number")
                )
                if invoice_number:
                    resp = await c.get(
                        _api_url("purchaseInvoices"),
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$filter": f"vendorInvoiceNumber eq '{invoice_number}'"},
                    )
                    if resp.status_code == 200:
                        existing = resp.json().get("value", [])
                        if existing and not job_config.get("allow_duplicate_check_override"):
                            validation_results["all_passed"] = False
                            validation_results["checks"].append({
                                "check_name": "duplicate_check",
                                "passed": False,
                                "details": f"Duplicate invoice found: {invoice_number}",
                                "required": True,
                                "existing_invoice_id": existing[0].get("id"),
                            })
                        else:
                            validation_results["checks"].append({
                                "check_name": "duplicate_check",
                                "passed": True,
                                "details": "No duplicate invoice found",
                                "required": True,
                            })

                # ---- Freight direction detection ----
                bol_or_order = (
                    normalized_fields.get("bol_number")
                    or normalized_fields.get("order_number")
                    or extracted_fields.get("bol_number")
                    or extracted_fields.get("order_number")
                )

                if bol_or_order:
                    bol_str = str(bol_or_order).strip()
                    logger.info("[BC Validation] AP Invoice - validating order reference: %s", bol_str)
                    freight_direction = "unknown"

                    # Step 1: Sales Orders (OUTBOUND)
                    resp = await c.get(
                        _api_url("salesOrders"),
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$filter": f"number eq '{bol_str}'"},
                    )
                    if resp.status_code == 200:
                        orders = resp.json().get("value", [])
                        if orders:
                            matched_order = orders[0]
                            freight_direction = "outbound"
                            validation_results["freight_direction"] = "outbound"
                            validation_results["checks"].append({
                                "check_name": "freight_direction",
                                "passed": True,
                                "details": f"OUTBOUND freight - Order {bol_str} matches Sales Order for {matched_order.get('customerName')}",
                                "required": False,
                                "freight_direction": "outbound",
                                "matched_sales_order": matched_order.get("number"),
                                "matched_customer": matched_order.get("customerName"),
                            })
                            validation_results["matched_sales_order"] = {
                                "number": matched_order.get("number"),
                                "customer_name": matched_order.get("customerName"),
                                "customer_number": matched_order.get("customerNumber"),
                                "order_date": matched_order.get("orderDate"),
                            }
                            logger.info(
                                "[BC Validation] OUTBOUND freight - order %s -> customer %s",
                                bol_str, matched_order.get("customerName"),
                            )

                    # Step 2: Purchase Orders (INBOUND)
                    if freight_direction == "unknown":
                        po_resp = await c.get(
                            _api_url("purchaseOrders"),
                            headers={"Authorization": f"Bearer {token}"},
                            params={"$filter": f"number eq '{bol_str}'"},
                        )
                        if po_resp.status_code == 200:
                            pos = po_resp.json().get("value", [])
                            if pos:
                                matched_po = pos[0]
                                freight_direction = "inbound"
                                validation_results["freight_direction"] = "inbound"
                                validation_results["checks"].append({
                                    "check_name": "freight_direction",
                                    "passed": True,
                                    "details": f"INBOUND freight - Order {bol_str} matches Purchase Order from {matched_po.get('vendorName')}",
                                    "required": False,
                                    "freight_direction": "inbound",
                                    "matched_purchase_order": matched_po.get("number"),
                                    "matched_vendor": matched_po.get("vendorName"),
                                })
                                validation_results["matched_purchase_order"] = {
                                    "number": matched_po.get("number"),
                                    "vendor_name": matched_po.get("vendorName"),
                                    "vendor_number": matched_po.get("vendorNumber"),
                                    "order_date": matched_po.get("orderDate"),
                                }
                                logger.info(
                                    "[BC Validation] INBOUND freight - order %s -> vendor %s",
                                    bol_str, matched_po.get("vendorName"),
                                )

                    # Step 3: Neither matched
                    if freight_direction == "unknown":
                        validation_results["freight_direction"] = "unknown"
                        validation_results["warnings"].append({
                            "check_name": "freight_direction_unknown",
                            "details": f"Order reference '{bol_str}' not found as Sales Order or Purchase Order - cannot determine freight direction",
                        })
                        logger.warning(
                            "[BC Validation] UNKNOWN freight direction - order %s not found in SO or PO",
                            bol_str,
                        )

            # ============================================================
            # Sales_PO / AR_Invoice — customer match
            # ============================================================
            elif job_type in ("Sales_PO", "AR_Invoice"):
                customer_name = (
                    normalized_fields.get("customer")
                    or extracted_fields.get("customer", "")
                )
                if customer_name:
                    customer_result = await _match_customer_in_bc(
                        customer_name, match_strategies, match_threshold,
                        token, company_id, _api_url,
                    )

                    validation_results["customer_candidates"] = customer_result.get("customer_candidates", [])

                    if customer_result["matched"]:
                        validation_results["match_method"] = customer_result["match_method"]
                        validation_results["match_score"] = customer_result["score"]
                        validation_results["checks"].append({
                            "check_name": "customer_match",
                            "passed": True,
                            "details": f"Found customer via {customer_result['match_method']}: {customer_result['selected_customer'].get('displayName')} (score: {customer_result['score']:.0%})",
                            "required": True,
                            "match_method": customer_result["match_method"],
                            "score": customer_result["score"],
                        })
                        validation_results["bc_record_id"] = customer_result["selected_customer"].get("id")
                        validation_results["bc_record_info"] = customer_result["selected_customer"]
                    else:
                        validation_results["all_passed"] = False
                        validation_results["match_method"] = "none"
                        details = f"No customer found matching '{customer_name}'"
                        if customer_result["customer_candidates"]:
                            top = customer_result["customer_candidates"][0]
                            details += f". Best candidate: {top['display_name']} ({top['score']:.0%})"
                        validation_results["checks"].append({
                            "check_name": "customer_match",
                            "passed": False,
                            "details": details,
                            "required": True,
                            "candidates_available": len(customer_result["customer_candidates"]) > 0,
                        })

            # ============================================================
            # Shipping / Warehouse — Customer match + Sales Order validation
            # ============================================================
            elif job_type in ("Shipping_Document", "Warehouse_Document", "SHIPMENT", "RECEIPT"):
                # --- Customer/consignee matching ---
                customer_name = (
                    normalized_fields.get("consignee")
                    or normalized_fields.get("customer")
                    or extracted_fields.get("consignee")
                    or extracted_fields.get("customer")
                )
                shipper_name = (
                    normalized_fields.get("shipper")
                    or extracted_fields.get("shipper")
                    or normalized_fields.get("vendor")
                    or extracted_fields.get("vendor")
                )

                if customer_name:
                    customer_result = await _match_customer_in_bc(
                        customer_name, match_strategies, match_threshold,
                        token, company_id, _api_url,
                    )
                    validation_results["customer_candidates"] = customer_result.get("customer_candidates", [])

                    if customer_result["matched"]:
                        validation_results["match_method"] = customer_result["match_method"]
                        validation_results["match_score"] = customer_result["score"]
                        if customer_result["selected_customer"]:
                            validation_results["bc_record_info"] = {
                                "number": customer_result["selected_customer"].get("number"),
                                "displayName": customer_result["selected_customer"].get("displayName"),
                                "type": "customer",
                            }
                        validation_results["checks"].append({
                            "check_name": "customer_match",
                            "passed": True,
                            "details": (
                                f"Matched consignee '{customer_name}' to BC customer: "
                                f"{customer_result['selected_customer'].get('displayName', '')} "
                                f"({customer_result['score']:.0%})"
                            ),
                            "required": False,
                        })
                    else:
                        validation_results["checks"].append({
                            "check_name": "customer_match",
                            "passed": False,
                            "details": f"Consignee '{customer_name}' not found in BC customers",
                            "required": False,
                        })

                # Also try to match shipper as a vendor (for tracking purposes)
                if shipper_name:
                    try:
                        from services.unified_vendor_matcher import match_vendor_unified
                        shipper_result = await match_vendor_unified(db, shipper_name, match_threshold)
                        if shipper_result.get("matched"):
                            # Don't override customer match info — store separately
                            validation_results["shipper_match"] = {
                                "matched": True,
                                "name": shipper_result.get("best_match", {}).get("name", shipper_name),
                                "score": shipper_result.get("score", 0),
                                "source": shipper_result.get("source", ""),
                            }
                            # If we have no match_method yet, use the shipper match
                            if validation_results["match_method"] == "none":
                                validation_results["match_method"] = f"shipper:{shipper_result.get('source', 'vendor')}"
                                validation_results["match_score"] = shipper_result.get("score", 0)
                    except Exception as e:
                        logger.debug("[BC Validation] Shipper matching skipped: %s", e)

                # --- Sales Order lookup ---
                order_number = (
                    normalized_fields.get("bol_number")
                    or normalized_fields.get("po_number")
                    or normalized_fields.get("order_number")
                    or extracted_fields.get("bol_number")
                    or extracted_fields.get("po_number")
                    or extracted_fields.get("order_number")
                )

                if order_number:
                    order_number_str = str(order_number).strip()
                    logger.info("[BC Validation] Shipping doc - looking up Sales Order: %s", order_number_str)

                    resp = await c.get(
                        _api_url("salesOrders"),
                        headers={"Authorization": f"Bearer {token}"},
                        params={"$filter": f"number eq '{order_number_str}'"},
                    )

                    if resp.status_code == 200:
                        orders = resp.json().get("value", [])
                        if orders:
                            matched_order = orders[0]
                            validation_results["match_method"] = "sales_order_number"
                            validation_results["match_score"] = 1.0
                            validation_results["bc_record_id"] = matched_order.get("id")
                            validation_results["bc_record_info"] = {
                                "id": matched_order.get("id"),
                                "number": matched_order.get("number"),
                                "customerName": matched_order.get("customerName"),
                                "customerNumber": matched_order.get("customerNumber"),
                                "orderDate": matched_order.get("orderDate"),
                                "status": matched_order.get("status"),
                                "totalAmountIncludingTax": matched_order.get("totalAmountIncludingTax"),
                            }
                            validation_results["checks"].append({
                                "check_name": "sales_order_match",
                                "passed": True,
                                "details": f"Found Sales Order #{matched_order.get('number')} for {matched_order.get('customerName')}",
                                "required": True,
                                "order_number": matched_order.get("number"),
                                "customer_name": matched_order.get("customerName"),
                                "customer_number": matched_order.get("customerNumber"),
                                "order_date": matched_order.get("orderDate"),
                                "total_amount": matched_order.get("totalAmountIncludingTax"),
                            })
                            logger.info(
                                "[BC Validation] Shipping doc - MATCHED Sales Order %s -> %s",
                                order_number_str, matched_order.get("customerName"),
                            )
                        else:
                            # Order number present but not found in BC — warning only.
                            # Many BOLs reference internal numbers that don't map to BC SOs.
                            validation_results["warnings"].append({
                                "check_name": "sales_order_not_found",
                                "details": f"No Sales Order found matching '{order_number_str}' in BC",
                            })
                            validation_results["checks"].append({
                                "check_name": "sales_order_match",
                                "passed": False,
                                "details": f"Sales Order '{order_number_str}' not found in BC",
                                "required": False,
                            })
                            logger.warning("[BC Validation] Shipping doc - Sales Order %s NOT FOUND", order_number_str)
                    else:
                        logger.warning("[BC Validation] Sales Order lookup failed: HTTP %d", resp.status_code)
                        validation_results["warnings"].append({
                            "check_name": "sales_order_lookup_error",
                            "details": f"Could not query Sales Orders: HTTP {resp.status_code}",
                        })
                else:
                    validation_results["warnings"].append({
                        "check_name": "no_order_number",
                        "details": "No BOL/Order number extracted - cannot validate against Sales Orders",
                    })

    except Exception as e:
        logger.error("BC validation failed: %s", str(e))
        validation_results["all_passed"] = False
        validation_results["checks"].append({
            "check_name": "bc_error",
            "passed": False,
            "details": f"BC validation error: {str(e)}",
            "required": True,
        })

    return validation_results
