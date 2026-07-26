"""
Batch document revalidation orchestration.

Extracted from services.document_handlers so the route-facing handler module
imports the authoritative implementation directly.
"""

import logging
from datetime import datetime, timezone
from typing import List

from fastapi import BackgroundTasks, Query

from deps import get_db
from services.document_intel_helpers import (
    make_automation_decision as _make_automation_decision,
)

logger = logging.getLogger(__name__)


def _get_default_job_types():
    from models.document_types import DEFAULT_JOB_TYPES
    return DEFAULT_JOB_TYPES


async def batch_revalidate_documents(
    doc_types: List[str] = Query(default=["AP_Invoice", "AP_INVOICE", "Remittance"]),
    limit: int = Query(default=500, le=1000),
    skip_completed: bool = Query(default=True),
    background_tasks: BackgroundTasks = None,
):
    """Batch re-validate all documents against Production BC."""
    db = get_db()
    DEFAULT_JOB_TYPES = _get_default_job_types()

    query = {"doc_type": {"$in": doc_types}}
    if skip_completed:
        query["status"] = {"$nin": ["Completed", "Posted", "Archived", "LinkedToBC"]}

    cursor = db.hub_documents.find(query, {"_id": 0}).limit(limit)
    docs = await cursor.to_list(limit)

    if not docs:
        return {"message": "No documents to revalidate", "count": 0}

    from services.bc_validation_service import validate_bc_match

    results = {"total": len(docs), "success": 0, "failed": 0, "improved": 0, "unchanged": 0, "details": []}

    for doc in docs:
        doc_id = doc.get("id")
        try:
            job_type = doc.get("suggested_job_type", doc.get("doc_type", "AP_Invoice"))
            job_configs = await db.hub_job_types.find_one({"job_type": job_type}, {"_id": 0})
            if not job_configs:
                job_configs = DEFAULT_JOB_TYPES.get(job_type, DEFAULT_JOB_TYPES.get("AP_Invoice", {}))

            extracted_fields = doc.get("extracted_fields") or {}
            vendor_name = extracted_fields.get("vendor", doc.get("vendor_canonical", ""))

            old_match_method = doc.get("match_method", doc.get("validation_results", {}).get("match_method", "none"))
            old_validation_passed = doc.get("validation_results", {}).get("all_passed", False)

            validation_results = await validate_bc_match(job_type, extracted_fields, job_configs)
            new_match_method = validation_results.get("match_method", "none")
            new_validation_passed = validation_results.get("all_passed", False)

            confidence = doc.get("ai_confidence") or 0.0
            decision, reasoning, decision_metadata = _make_automation_decision(job_configs, confidence, validation_results)

            update_data = {
                "validation_results": validation_results,
                "match_method": new_match_method,
                "match_score": validation_results.get("match_score", 0.0),
                "automation_decision": decision,
                "vendor_candidates": decision_metadata.get("vendor_candidates", []),
                "revalidated_utc": datetime.now(timezone.utc).isoformat(),
                "revalidated_from": "batch_revalidate_production",
            }

            if validation_results.get("bc_record_info"):
                bc_info = validation_results["bc_record_info"]
                update_data["vendor_canonical"] = bc_info.get("displayName", vendor_name)
                update_data["bc_vendor_number"] = bc_info.get("number")

            if validation_results.get("unified_vendor_match"):
                update_data["unified_vendor_match"] = validation_results["unified_vendor_match"]

            await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})

            improved = (not old_validation_passed and new_validation_passed) or \
                       (old_match_method == "none" and new_match_method != "none")

            results["success"] += 1
            if improved:
                results["improved"] += 1
            else:
                results["unchanged"] += 1

            results["details"].append({
                "doc_id": doc_id[:8] + "...",
                "vendor": vendor_name[:30] if vendor_name else "N/A",
                "old_match": old_match_method, "new_match": new_match_method,
                "improved": improved, "validation_passed": new_validation_passed,
            })

        except Exception as e:
            results["failed"] += 1
            results["details"].append({"doc_id": doc_id[:8] + "...", "error": str(e)[:100]})
            logger.error("Batch revalidate error for %s: %s", doc_id, str(e))

    return results
