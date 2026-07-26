"""
Existing-document classification orchestration.

Extracted from services.document_handlers so the route-facing handler module
imports the authoritative implementation directly.
"""

import os
from datetime import datetime, timezone
from pathlib import Path

from fastapi import HTTPException

from deps import get_db
from services.document_intel_helpers import (
    classify_document_with_ai as _classify_with_ai,
    make_automation_decision as _make_automation_decision,
)

UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))
UPLOAD_DIR.mkdir(parents=True, exist_ok=True)


def _get_default_job_types():
    from models.document_types import DEFAULT_JOB_TYPES
    return DEFAULT_JOB_TYPES


async def classify_document(doc_id: str):
    """Re-run AI classification on an existing document."""
    db = get_db()
    DEFAULT_JOB_TYPES = _get_default_job_types()

    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    file_path = UPLOAD_DIR / doc_id
    if not file_path.exists():
        raise HTTPException(status_code=400, detail="Original file not found")

    classification = await _classify_with_ai(str(file_path), doc["file_name"])

    suggested_type = classification.get("suggested_job_type", "Unknown")
    confidence = classification.get("confidence", 0.0)
    extracted_fields = classification.get("extracted_fields", {})

    job_configs = await db.hub_job_types.find_one({"job_type": suggested_type}, {"_id": 0})
    if not job_configs:
        job_configs = DEFAULT_JOB_TYPES.get(suggested_type, DEFAULT_JOB_TYPES["AP_Invoice"])

    from services.bc_validation_service import validate_bc_match
    validation_results = await validate_bc_match(suggested_type, extracted_fields, job_configs)

    decision, reasoning, decision_metadata = _make_automation_decision(job_configs, confidence, validation_results)

    await db.hub_documents.update_one({"id": doc_id}, {"$set": {
        "suggested_job_type": suggested_type,
        "document_type": suggested_type,
        "ai_confidence": confidence,
        "classification_method": f"ai:{classification.get('model', 'gemini-2.5-pro')}",
        "ai_model": classification.get("model", "gemini-2.5-pro"),
        "extracted_fields": extracted_fields,
        "normalized_fields": validation_results.get("normalized_fields", {}),
        "validation_results": validation_results,
        "automation_decision": decision,
        "vendor_candidates": decision_metadata.get("vendor_candidates", []),
        "customer_candidates": decision_metadata.get("customer_candidates", []),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
    }})

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "document": updated_doc,
        "classification": classification,
        "validation": validation_results,
        "decision": decision,
        "reasoning": reasoning,
        "candidates": {
            "vendors": decision_metadata.get("vendor_candidates", []),
            "customers": decision_metadata.get("customer_candidates", []),
        },
    }
