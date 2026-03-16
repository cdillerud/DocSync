"""
Vendor Re-Processing Router — Batch re-run vendor matching on existing documents.

Use this after deploying vendor matching fixes to re-evaluate all documents
against the updated logic (normalized exact match, shared fuzzy scorer,
fuzzy_candidate vs fuzzy_match semantics).

Endpoints:
  POST /api/vendor-reprocess/run          — Re-process all vendor-applicable docs
  GET  /api/vendor-reprocess/status        — Check status of last re-processing run
  POST /api/vendor-reprocess/dry-run       — Preview what would change without writing
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from fastapi import APIRouter, Query
from deps import get_db

logger = logging.getLogger("vendor_reprocess")

router = APIRouter(prefix="/vendor-reprocess", tags=["Vendor Re-Processing"])

# Module-level state for tracking the last run
_last_run: Dict[str, Any] = {"status": "idle"}

VENDOR_APPLICABLE_TYPES = [
    "AP_Invoice", "AP_INVOICE", "PurchaseInvoice", "PurchaseOrder",
    "Remittance", "REMITTANCE", "Credit_Memo", "CREDIT_MEMO",
    "Purchase_Invoice", "PURCHASE_INVOICE",
]


async def _get_vendor_raw(doc: dict) -> str:
    """Extract the raw vendor string from a document."""
    extracted = doc.get("extracted_fields") or {}
    return (
        doc.get("vendor_raw_ocr")
        or extracted.get("vendor")
        or extracted.get("vendor_name")
        or extracted.get("supplier")
        or doc.get("vendor_name_raw")
        or ""
    ).strip()


async def _reprocess_single(doc: dict, dry_run: bool = False) -> dict:
    """Re-run vendor matching on a single document. Returns change summary."""
    from services.vendor_matching import lookup_vendor_alias
    from services.vendor_name_helpers import normalize_vendor_name
    from services.vendor_resolution_service import build_resolution_object

    doc_id = doc.get("id", "?")
    old_method = doc.get("vendor_match_method", "none")
    old_canonical = doc.get("vendor_canonical")
    old_resolution = doc.get("vendor_resolution") or {}
    old_status = old_resolution.get("status", "none")

    vendor_raw = await _get_vendor_raw(doc)
    if not vendor_raw:
        return {
            "doc_id": doc_id,
            "action": "skipped",
            "reason": "no_vendor_raw_string",
            "old_method": old_method,
        }

    vendor_normalized = normalize_vendor_name(vendor_raw)
    if not vendor_normalized:
        return {
            "doc_id": doc_id,
            "action": "skipped",
            "reason": "normalized_to_empty",
            "vendor_raw": vendor_raw,
            "old_method": old_method,
        }

    # Run the updated matching logic
    match_result = await lookup_vendor_alias(vendor_normalized)

    new_method = match_result.get("vendor_match_method", "none")
    new_canonical = match_result.get("vendor_canonical")
    new_score = match_result.get("match_score")
    new_resolution_status = match_result.get("resolution_status")

    # Build the resolution object using the correct signature
    resolution = build_resolution_object(vendor_raw, match_result)
    # If the match itself says needs_review, override the resolution status
    if new_resolution_status == "needs_review":
        resolution["status"] = "needs_review"

    changed = (
        new_method != old_method
        or str(new_canonical) != str(old_canonical)
        or resolution.get("status") != old_status
    )

    result = {
        "doc_id": doc_id,
        "vendor_raw": vendor_raw,
        "vendor_normalized": vendor_normalized,
        "old": {
            "method": old_method,
            "canonical": old_canonical,
            "status": old_status,
        },
        "new": {
            "method": new_method,
            "canonical": new_canonical,
            "status": resolution.get("status"),
            "score": new_score,
            "vendor_name": match_result.get("vendor_name"),
            "guardrail_downgraded": match_result.get("guardrail_downgraded", False),
        },
        "changed": changed,
        "action": "would_update" if changed else "no_change",
    }

    if not dry_run and changed:
        db = get_db()
        update = {
            "vendor_match_method": new_method,
            "vendor_resolution": resolution,
        }
        if new_canonical:
            update["vendor_canonical"] = new_canonical
            update["vendor_name"] = match_result.get("vendor_name")
            update["vendor_no"] = match_result.get("vendor_no")
        update["vendor_reprocessed_at"] = datetime.now(timezone.utc).isoformat()

        await db.hub_documents.update_one({"id": doc_id}, {"$set": update})
        result["action"] = "updated"

    return result


@router.post("/run")
async def run_reprocess(
    limit: int = Query(500, ge=1, le=5000),
    force_all: bool = Query(False, description="Re-process even if already processed by new logic"),
):
    """
    Re-process vendor matching on all vendor-applicable documents.
    
    This re-runs lookup_vendor_alias with the fixed logic:
    - Normalized exact match (not regex against raw displayName)
    - Shared fuzzy scorer (calculate_fuzzy_score)
    - fuzzy_match (>=0.90 auto-resolve) vs fuzzy_candidate (<0.90 review)
    """
    global _last_run
    db = get_db()

    _last_run = {"status": "running", "started_at": datetime.now(timezone.utc).isoformat()}

    # Find vendor-applicable docs
    match_filter = {
        "$or": [
            {"doc_type": {"$in": VENDOR_APPLICABLE_TYPES}},
            {"suggested_job_type": {"$in": VENDOR_APPLICABLE_TYPES}},
            {"vendor_resolution.status": {"$exists": True}},
        ]
    }
    if not force_all:
        match_filter["vendor_reprocessed_at"] = {"$exists": False}

    cursor = db.hub_documents.find(match_filter, {"_id": 0}).limit(limit)
    docs = await cursor.to_list(limit)

    results = {
        "total_docs": len(docs),
        "updated": 0,
        "no_change": 0,
        "skipped": 0,
        "errors": 0,
        "method_transitions": {},
        "details": [],
    }

    for doc in docs:
        try:
            r = await _reprocess_single(doc, dry_run=False)
            if r["action"] == "updated":
                results["updated"] += 1
                transition = f"{r['old']['method']} -> {r['new']['method']}"
                results["method_transitions"][transition] = results["method_transitions"].get(transition, 0) + 1
            elif r["action"] == "no_change":
                results["no_change"] += 1
            else:
                results["skipped"] += 1
            results["details"].append(r)
        except Exception as e:
            results["errors"] += 1
            results["details"].append({
                "doc_id": doc.get("id", "?"),
                "action": "error",
                "error": str(e),
            })
            logger.warning("Reprocess error for %s: %s", doc.get("id"), e)

    _last_run = {
        "status": "complete",
        "started_at": _last_run.get("started_at"),
        "completed_at": datetime.now(timezone.utc).isoformat(),
        "summary": {k: v for k, v in results.items() if k != "details"},
    }

    logger.info(
        "Vendor re-processing complete: %d docs, %d updated, %d no_change, %d skipped, %d errors",
        results["total_docs"], results["updated"], results["no_change"],
        results["skipped"], results["errors"],
    )

    return results


@router.post("/dry-run")
async def dry_run_reprocess(limit: int = Query(500, ge=1, le=5000)):
    """
    Preview what would change without writing. Returns same structure as /run
    but with action='would_update' instead of 'updated'.
    """
    db = get_db()

    match_filter = {
        "$or": [
            {"doc_type": {"$in": VENDOR_APPLICABLE_TYPES}},
            {"suggested_job_type": {"$in": VENDOR_APPLICABLE_TYPES}},
            {"vendor_resolution.status": {"$exists": True}},
        ]
    }

    cursor = db.hub_documents.find(match_filter, {"_id": 0}).limit(limit)
    docs = await cursor.to_list(limit)

    results = {
        "total_docs": len(docs),
        "would_update": 0,
        "no_change": 0,
        "skipped": 0,
        "errors": 0,
        "method_transitions": {},
        "details": [],
    }

    for doc in docs:
        try:
            r = await _reprocess_single(doc, dry_run=True)
            if r["action"] == "would_update":
                results["would_update"] += 1
                transition = f"{r['old']['method']} -> {r['new']['method']}"
                results["method_transitions"][transition] = results["method_transitions"].get(transition, 0) + 1
            elif r["action"] == "no_change":
                results["no_change"] += 1
            else:
                results["skipped"] += 1
            results["details"].append(r)
        except Exception as e:
            results["errors"] += 1
            results["details"].append({
                "doc_id": doc.get("id", "?"),
                "action": "error",
                "error": str(e),
            })

    return results


@router.get("/status")
async def reprocess_status():
    """Check the status/result of the last re-processing run."""
    return _last_run
