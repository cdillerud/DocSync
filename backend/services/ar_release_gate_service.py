"""
AR Release Gate Service — Prepay & Terms Approval

Evaluates sales/AR documents to determine if they can be released for
processing (create SO, create invoice, etc.) or must be held for human review.

Checks performed:
  1. Customer resolution  — is the customer matched to a BC customer?
  2. Prepay hold          — does the customer record require prepayment?
  3. Credit limit check   — is the order total within remaining credit?
  4. Payment terms        — are payment terms set and non-blocked?
  5. Ship-to validation   — is there a valid shipping address?

Each check produces a pass / warning / fail signal. The aggregate result
determines the release decision:
  • released     — all checks pass, auto-processing may proceed
  • held         — one or more blocking issues require human approval
  • override     — a human has manually overridden the hold

The gate stores its result on the document as `ar_release_gate`.
"""

import logging
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger("ar_release_gate")

# ---------------------------------------------------------------------------
# Configuration
# ---------------------------------------------------------------------------

# Document types eligible for AR release gate evaluation
AR_DOC_TYPES = {
    "salesorder", "salesinvoice", "sales_order", "sales_invoice",
    "sales order", "sales invoice", "so", "si",
}

# Payment terms that are considered "hold" terms
BLOCKED_PAYMENT_TERMS = {"PREPAY", "COD", "CIA", "HOLD", "BLOCKED", "SUSPENDED"}

# Default credit limit when none is set on the customer record
DEFAULT_CREDIT_LIMIT = 0.0

# ---------------------------------------------------------------------------
# Data model
# ---------------------------------------------------------------------------

def _empty_gate() -> dict:
    return {
        "status": "pending",
        "checks": {},
        "blocking_reasons": [],
        "warning_reasons": [],
        "released": False,
        "override": None,
        "evaluated_at": None,
        "version": 1,
    }


# ---------------------------------------------------------------------------
# Individual checks
# ---------------------------------------------------------------------------

def _check_customer_resolution(doc: dict) -> dict:
    """Check if the customer is resolved to a BC customer."""
    customer_id = doc.get("bc_customer_id") or doc.get("customer_matched_id")
    customer_name = (
        doc.get("customer_matched_name")
        or doc.get("extracted_fields", {}).get("customer")
        or doc.get("normalized_fields", {}).get("customer")
    )

    if customer_id:
        return {"result": "pass", "detail": f"Resolved: {customer_name or customer_id}"}
    if customer_name:
        return {"result": "warning", "detail": f"Name found ({customer_name}) but not matched to BC customer"}
    return {"result": "fail", "detail": "Customer not identified on document"}


def _check_prepay_hold(doc: dict, customer_record: Optional[dict] = None) -> dict:
    """Check if the customer requires prepayment."""
    # If we have BC customer record data, inspect it
    if customer_record:
        blocked = customer_record.get("blocked", "")
        if blocked and str(blocked).strip() not in ("", " "):
            return {"result": "fail", "detail": f"Customer blocked in BC: {blocked}"}
        payment_terms = (customer_record.get("paymentTermsCode") or "").upper()
        if payment_terms in BLOCKED_PAYMENT_TERMS:
            return {
                "result": "fail",
                "detail": f"Prepay required (terms: {payment_terms})",
            }
        return {"result": "pass", "detail": "No prepay hold on customer record"}

    # Fallback: check extracted fields for indicators
    terms = (
        doc.get("extracted_fields", {}).get("payment_terms", "")
        or doc.get("normalized_fields", {}).get("payment_terms", "")
    ).upper()

    if any(t in terms for t in BLOCKED_PAYMENT_TERMS):
        return {"result": "fail", "detail": f"Prepay indicator in document: {terms}"}

    # No customer record and no negative indicators → warning
    if not doc.get("bc_customer_id"):
        return {"result": "warning", "detail": "Customer record not loaded — cannot verify prepay status"}
    return {"result": "pass", "detail": "No prepay indicators found"}


def _check_credit_limit(doc: dict, customer_record: Optional[dict] = None) -> dict:
    """Check if order total is within remaining customer credit."""
    total = (
        doc.get("total_amount")
        or doc.get("extracted_fields", {}).get("total_amount")
        or doc.get("normalized_fields", {}).get("total_amount")
    )
    if total is None:
        return {"result": "warning", "detail": "Total amount not extracted — cannot check credit"}

    try:
        total = float(total)
    except (ValueError, TypeError):
        return {"result": "warning", "detail": f"Total amount not numeric: {total}"}

    if customer_record:
        credit_limit = customer_record.get("creditLimitLCY", DEFAULT_CREDIT_LIMIT) or DEFAULT_CREDIT_LIMIT
        balance = customer_record.get("balanceLCY", 0) or 0
        remaining = credit_limit - balance

        if credit_limit == 0:
            return {"result": "warning", "detail": "No credit limit set on customer"}
        if total > remaining:
            return {
                "result": "fail",
                "detail": f"Order ${total:,.2f} exceeds remaining credit ${remaining:,.2f} "
                          f"(limit ${credit_limit:,.2f}, balance ${balance:,.2f})",
            }
        return {
            "result": "pass",
            "detail": f"Within credit: ${total:,.2f} / ${remaining:,.2f} remaining",
        }

    return {"result": "warning", "detail": "Customer record not available — cannot check credit limit"}


def _check_payment_terms(doc: dict, customer_record: Optional[dict] = None) -> dict:
    """Check if payment terms are set and approved."""
    terms = None
    if customer_record:
        terms = customer_record.get("paymentTermsCode")
    if not terms:
        terms = (
            doc.get("extracted_fields", {}).get("payment_terms")
            or doc.get("normalized_fields", {}).get("payment_terms")
        )

    if not terms:
        return {"result": "warning", "detail": "Payment terms not found"}
    terms_upper = str(terms).upper()
    if terms_upper in BLOCKED_PAYMENT_TERMS:
        return {"result": "fail", "detail": f"Payment terms require hold: {terms}"}
    return {"result": "pass", "detail": f"Payment terms: {terms}"}


def _check_ship_to(doc: dict) -> dict:
    """Check if shipping address is present."""
    ship_to = (
        doc.get("extracted_fields", {}).get("ship_to_address")
        or doc.get("normalized_fields", {}).get("ship_to")
        or doc.get("extracted_fields", {}).get("delivery_address")
    )
    if ship_to:
        return {"result": "pass", "detail": "Ship-to address present"}
    return {"result": "warning", "detail": "Ship-to address not found on document"}


# ---------------------------------------------------------------------------
# Main evaluation
# ---------------------------------------------------------------------------

def evaluate_ar_release(doc: dict, customer_record: Optional[dict] = None) -> dict:
    """
    Run all AR release gate checks and produce a gate result.

    Args:
        doc: The hub document dict.
        customer_record: Optional BC customer record dict.

    Returns:
        A dict to store as `ar_release_gate` on the document.
    """
    gate = _empty_gate()

    checks = {
        "customer_resolution": _check_customer_resolution(doc),
        "prepay_hold": _check_prepay_hold(doc, customer_record),
        "credit_limit": _check_credit_limit(doc, customer_record),
        "payment_terms": _check_payment_terms(doc, customer_record),
        "ship_to": _check_ship_to(doc),
    }

    gate["checks"] = checks

    for name, check in checks.items():
        if check["result"] == "fail":
            gate["blocking_reasons"].append(name)
        elif check["result"] == "warning":
            gate["warning_reasons"].append(name)

    has_block = len(gate["blocking_reasons"]) > 0
    gate["status"] = "held" if has_block else "released"
    gate["released"] = not has_block
    gate["evaluated_at"] = datetime.now(timezone.utc).isoformat()

    return gate


def is_ar_eligible(doc: dict) -> bool:
    """Return True if this document should go through AR release gate."""
    doc_type = (doc.get("doc_type") or doc.get("suggested_job_type") or "").lower().replace(" ", "").replace("_", "")
    return doc_type in {t.replace(" ", "").replace("_", "") for t in AR_DOC_TYPES}


# ---------------------------------------------------------------------------
# Database operations
# ---------------------------------------------------------------------------

async def evaluate_and_store(doc_id: str, db, customer_record: Optional[dict] = None) -> dict:
    """Evaluate a document and store the result in MongoDB."""
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": "Document not found", "document_id": doc_id}

    if not is_ar_eligible(doc):
        return {"skipped": True, "reason": "Not an AR-eligible document", "document_id": doc_id}

    gate = evaluate_ar_release(doc, customer_record)

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {"ar_release_gate": gate}},
    )

    logger.info(
        "AR release gate for %s: status=%s, blocking=%s, warnings=%s",
        doc_id, gate["status"], gate["blocking_reasons"], gate["warning_reasons"],
    )

    return {"document_id": doc_id, **gate}


async def override_gate(doc_id: str, db, approved_by: str, notes: str = "") -> dict:
    """Manually override the AR release gate (human approval)."""
    now = datetime.now(timezone.utc).isoformat()

    result = await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "ar_release_gate.status": "override",
            "ar_release_gate.released": True,
            "ar_release_gate.override": {
                "approved_by": approved_by,
                "approved_at": now,
                "notes": notes,
            },
        }},
    )

    if result.modified_count == 0:
        return {"error": "Document not found or gate not evaluated", "document_id": doc_id}

    logger.info("AR release gate overridden for %s by %s", doc_id, approved_by)
    return {"document_id": doc_id, "status": "override", "approved_by": approved_by}


async def get_ar_release_metrics(db) -> dict:
    """Get aggregate AR release gate metrics."""
    pipeline = [
        {"$match": {"ar_release_gate": {"$exists": True}}},
        {"$group": {
            "_id": "$ar_release_gate.status",
            "count": {"$sum": 1},
        }},
    ]
    raw = await db.hub_documents.aggregate(pipeline).to_list(10)
    by_status = {r["_id"]: r["count"] for r in raw if r["_id"]}
    total = sum(by_status.values())

    # Top blocking reasons
    block_pipeline = [
        {"$match": {"ar_release_gate.blocking_reasons": {"$exists": True, "$ne": []}}},
        {"$unwind": "$ar_release_gate.blocking_reasons"},
        {"$group": {"_id": "$ar_release_gate.blocking_reasons", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    block_raw = await db.hub_documents.aggregate(block_pipeline).to_list(10)
    top_blockers = [{"reason": r["_id"], "count": r["count"]} for r in block_raw if r["_id"]]

    return {
        "total_evaluated": total,
        "by_status": by_status,
        "top_blocking_reasons": top_blockers,
    }
