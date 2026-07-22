"""Safe non-transactional document disposition with AI learning."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from deps import get_db

logger = logging.getLogger(__name__)


DISPOSITION_CONFIG = {
    "graphics_artwork": {
        "document_type": "Graphics_Artwork",
        "label": "Graphics / artwork",
        "learning_description": (
            "Packaging graphics, label artwork, dielines, print layouts, "
            "artwork proofs, can templates, or other production graphics. "
            "Common visual/text cues include print area, slit width, cut "
            "height, bleed, trim lines, dimensions, nutrition panels, "
            "barcodes, and package-label layouts."
        ),
    },
}


def _original_document_type(doc: Dict[str, Any]) -> str:
    return (
        doc.get("suggested_job_type")
        or doc.get("doc_type")
        or doc.get("document_type")
        or "Unknown_Document"
    )


def _learning_text(doc: Dict[str, Any], disposition: str) -> str:
    config = DISPOSITION_CONFIG[disposition]

    raw_text = (
        doc.get("raw_text")
        or doc.get("extracted_text")
        or doc.get("ocr_text")
        or doc.get("text_content")
        or ""
    )

    if not raw_text:
        fields = doc.get("extracted_fields") or {}
        raw_text = " | ".join(
            str(value)
            for value in fields.values()
            if value and not isinstance(value, (dict, list))
        )

    return (
        f"Human verified disposition: {config['label']}. "
        f"{config['learning_description']} "
        f"Document evidence: {raw_text[:320]}"
    )[:500]


def build_disposition_update(
    doc: Dict[str, Any],
    disposition: str,
    disposed_by: str,
    notes: str = "",
) -> Dict[str, Any]:
    if disposition not in DISPOSITION_CONFIG:
        raise ValueError(f"Unsupported disposition: {disposition}")

    config = DISPOSITION_CONFIG[disposition]
    now = datetime.now(timezone.utc).isoformat()
    original_type = _original_document_type(doc)

    return {
        "document_type": config["document_type"],
        "doc_type": config["document_type"],
        "suggested_job_type": config["document_type"],
        "document_type_source": "human_disposition",
        "classification_override": {
            "original_type": original_type,
            "corrected_type": config["document_type"],
            "corrected_at": now,
            "corrected_by": disposed_by,
        },
        "non_transactional": True,
        "non_transactional_disposition": disposition,
        "non_transactional_label": config["label"],
        "non_transactional_notes": notes,
        "non_transactional_disposed_at": now,
        "non_transactional_disposed_by": disposed_by,
        "excluded_from_processing": True,
        "excluded_from_bc": True,
        "excluded_from_routing": True,
        "automation_decision": "exclude",
        "automation_readiness": "excluded",
        "automation_readiness_score": 100,
        "automation_readiness_reasons": [
            f"non_transactional_{disposition}"
        ],
        "status": "Archived",
        "workflow_status": "completed",
        "auto_cleared": True,
        "auto_clear_reason": f"non_transactional_{disposition}",
        "updated_utc": now,
    }


async def apply_non_transactional_disposition(
    doc_id: str,
    disposition: str,
    disposed_by: str = "human_decision_queue",
    notes: str = "",
    db: Optional[Any] = None,
) -> Dict[str, Any]:
    """Archive an operationally irrelevant document and record AI feedback."""

    if disposition not in DISPOSITION_CONFIG:
        raise ValueError(f"Unsupported disposition: {disposition}")

    if db is None:
        db = get_db()
    doc = await db.hub_documents.find_one(
        {"id": doc_id},
        {"_id": 0},
    )

    if not doc:
        raise ValueError(f"Document not found: {doc_id}")

    if (
        doc.get("non_transactional") is True
        and doc.get("non_transactional_disposition") == disposition
    ):
        return {
            "success": True,
            "skipped": True,
            "reason": "already_dispositioned",
            "document_id": doc_id,
            "disposition": disposition,
            "document_type": doc.get("document_type"),
        }

    original_type = _original_document_type(doc)
    update = build_disposition_update(
        doc,
        disposition,
        disposed_by,
        notes,
    )

    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": update},
    )

    await db.document_intelligence_results.update_one(
        {"document_id": doc_id},
        {
            "$set": {
                "document_type": update["document_type"],
                "automation_decision": "exclude",
                "automation_readiness": "excluded",
                "automation_readiness_score": 100,
                "automation_readiness_reasons": (
                    update["automation_readiness_reasons"]
                ),
                "manually_corrected": True,
                "non_transactional": True,
                "non_transactional_disposition": disposition,
                "updated_at": update["updated_utc"],
            }
        },
    )

    await db.hub_workflow_runs.update_many(
        {
            "document_id": doc_id,
            "status": {"$nin": ["completed", "cancelled"]},
        },
        {
            "$set": {
                "status": "cancelled",
                "cancel_reason": (
                    f"non_transactional_{disposition}"
                ),
                "ended_utc": update["updated_utc"],
            }
        },
    )

    audit_record = {
        "disposition_id": uuid.uuid4().hex,
        "document_id": doc_id,
        "file_name": doc.get("file_name", ""),
        "original_type": original_type,
        "corrected_type": update["document_type"],
        "disposition": disposition,
        "disposed_by": disposed_by,
        "disposed_at": update["updated_utc"],
        "notes": notes,
        "file_retained": True,
    }

    await db.document_dispositions.insert_one(audit_record)

    learning_recorded = False
    learning_error = None

    try:
        from services.classification_feedback_service import (
            record_correction,
        )

        result = await record_correction(
            doc_id=doc_id,
            original_type=original_type,
            corrected_type=update["document_type"],
            corrected_by=disposed_by,
            doc_context={
                "file_name": doc.get("file_name", ""),
                # Deliberately blank: do not teach that every document
                # from this sender/vendor is graphics artwork.
                "vendor_raw": "",
                "vendor_canonical": "",
                "text_snippet": _learning_text(doc, disposition),
                "classification_method": doc.get(
                    "classification_method",
                    "",
                ),
                "classification_confidence": (
                    doc.get("classification_confidence")
                    or doc.get("ai_confidence")
                    or 0
                ),
            },
        )

        learning_recorded = bool(result.get("success"))
    except Exception as exc:
        learning_error = str(exc)[:500]
        logger.warning(
            "Disposition saved but classification learning failed for %s: %s",
            doc_id,
            exc,
        )

    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "disposition_learning_recorded": learning_recorded,
                "disposition_learning_error": learning_error,
            }
        },
    )

    return {
        "success": True,
        "skipped": False,
        "document_id": doc_id,
        "file_name": doc.get("file_name", ""),
        "original_type": original_type,
        "document_type": update["document_type"],
        "disposition": disposition,
        "learning_recorded": learning_recorded,
        "file_retained": True,
    }
