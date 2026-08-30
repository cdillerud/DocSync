"""Bridge explicit Accounting route corrections into supervised learning.

Manual correction is expensive. Once it happens, the system should not throw
that information away. This service records an audit event and creates a
high-weight reviewer-correction example, but never moves SharePoint files by
itself.
"""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Dict, Optional

from services.ap_routing_decision_service import route_is_allowed
from services.ap_routing_learning_service import (
    LABEL_SOURCE_REVIEWER_CORRECTION,
    upsert_routing_example,
)


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


async def record_routing_correction(
    db,
    *,
    document: Dict[str, Any],
    corrected_route: str,
    reviewer_user_id: str,
    contract: Dict[str, Any],
    bc_context: Optional[Dict[str, Any]] = None,
    notes: str = "",
) -> Dict[str, Any]:
    context = bc_context or document.get("ap_routing_bc_context") or {}
    if not route_is_allowed(corrected_route, contract, context):
        return {
            "error": "corrected route is not allowed by current Accounting routing contract",
            "corrected_route": corrected_route,
            "contract_version": contract.get("version"),
        }

    extracted = document.get("extracted_fields") or document.get("ai_extraction") or {}
    vendor_name = (
        document.get("vendor_canonical")
        or document.get("vendor_raw")
        or extracted.get("vendor")
        or extracted.get("vendor_name")
        or context.get("bc_vendor_name")
        or ""
    )
    now = _now()
    example = await upsert_routing_example(
        db,
        {
            "label_source": LABEL_SOURCE_REVIEWER_CORRECTION,
            "document_id": document.get("id"),
            "source_item_id": document.get("sharepoint_item_id") or document.get("id"),
            "file_name": document.get("file_name"),
            "route_path": corrected_route,
            "vendor_name": vendor_name,
            "document_type": document.get("document_type") or document.get("suggested_job_type"),
            "classification_confidence": document.get("confidence"),
            "extracted_fields": extracted,
            "bundle_references": document.get("bundle_references") or {},
            "bc_context": context,
            "key_evidence": document.get("ap_routing_key_evidence") or {},
            "reviewer_corrected": True,
            "reviewer_user_id": reviewer_user_id,
            "reviewer_notes": notes,
            "corrected_at": now,
        },
    )

    audit = {
        "document_id": document.get("id"),
        "file_name": document.get("file_name"),
        "previous_route": document.get("folder_path") or document.get("sharepoint_folder") or "",
        "corrected_route": corrected_route,
        "reviewer_user_id": reviewer_user_id,
        "notes": notes,
        "contract_version": contract.get("version"),
        "example_fingerprint": example.get("fingerprint"),
        "timestamp": now,
    }
    await db.ap_routing_corrections.insert_one(dict(audit))
    await db.hub_documents.update_one(
        {"id": document.get("id")},
        {
            "$set": {
                "ap_routing_correction_latest": audit,
                "ap_routing_learning_example": example.get("fingerprint"),
            }
        },
    )
    return {"status": "recorded", "audit": audit, "example": example}
