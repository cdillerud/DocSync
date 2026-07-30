"""Positive confirmation of the current Decision Queue state."""

import logging
import uuid
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from deps import get_db

logger = logging.getLogger(__name__)

UNKNOWN_DOCUMENT_TYPES = {
    "",
    "Unknown",
    "Unknown_Document",
    "OTHER",
    None,
}

VALID_DECISION_QUEUE_RESOLUTIONS = {
    "confirmed_current",
    "corrected_state",
    "acknowledged",
    "same_document",
    "different_document",
    "unable_to_determine",
}

STATE_BOUND_RESOLUTIONS = {
    "confirmed_current",
    "corrected_state",
}


def current_document_state(
    doc: Dict[str, Any],
) -> Dict[str, str]:
    document_type = (
        doc.get("doc_type")
        or doc.get("document_type")
        or doc.get("suggested_job_type")
        or ""
    )

    mailbox_category = (
        doc.get("mailbox_category")
        or ""
    )

    return {
        "doc_type": str(document_type).strip(),
        "mailbox_category": str(mailbox_category).strip(),
    }


def _confirmation_for_issue(
    doc: Dict[str, Any],
    issue_type: str = "",
) -> Dict[str, Any]:
    normalized_issue_type = issue_type.strip()

    confirmations = (
        doc.get("decision_queue_confirmations")
        or {}
    )

    if (
        normalized_issue_type
        and isinstance(confirmations, dict)
    ):
        confirmation = confirmations.get(
            normalized_issue_type
        )

        if isinstance(confirmation, dict):
            return confirmation

    legacy_confirmation = (
        doc.get("decision_queue_confirmation")
        or {}
    )

    if not isinstance(legacy_confirmation, dict):
        return {}

    if not normalized_issue_type:
        return legacy_confirmation

    if (
        legacy_confirmation.get("issue_type", "")
        == normalized_issue_type
    ):
        return legacy_confirmation

    return {}


def confirmation_matches_current_state(
    doc: Dict[str, Any],
    issue_type: str = "",
) -> bool:
    confirmation = _confirmation_for_issue(
        doc,
        issue_type,
    )

    if not confirmation:
        return False

    resolution = str(
        confirmation.get("resolution")
        or "confirmed_current"
    ).strip().lower()

    if resolution not in STATE_BOUND_RESOLUTIONS:
        return True

    state = current_document_state(doc)

    return (
        confirmation.get("document_type")
        == state["doc_type"]
        and confirmation.get(
            "mailbox_category",
            "",
        )
        == state["mailbox_category"]
    )


def build_confirmation_record(
    doc: Dict[str, Any],
    confirmed_by: str,
    issue_type: str = "",
    notes: str = "",
    resolution: str = "confirmed_current",
) -> Dict[str, Any]:
    state = current_document_state(doc)
    document_type = state["doc_type"]

    normalized_resolution = str(
        resolution
        or "confirmed_current"
    ).strip().lower()

    if (
        normalized_resolution
        not in VALID_DECISION_QUEUE_RESOLUTIONS
    ):
        raise ValueError(
            "Invalid Decision Queue resolution"
        )

    if (
        normalized_resolution
        in STATE_BOUND_RESOLUTIONS
        and document_type in UNKNOWN_DOCUMENT_TYPES
    ):
        raise ValueError(
            "Set a valid document type before confirming"
        )

    normalized_issue_type = issue_type.strip()

    if (
        normalized_issue_type
        and not normalized_issue_type.replace(
            "_",
            "",
        ).replace(
            "-",
            "",
        ).isalnum()
    ):
        raise ValueError(
            "Invalid Decision Queue issue type"
        )

    now = datetime.now(timezone.utc).isoformat()

    return {
        "confirmation_id": uuid.uuid4().hex,
        "document_id": doc.get("id", ""),
        "document_type": document_type,
        "mailbox_category": (
            state["mailbox_category"]
        ),
        "confirmed_by": confirmed_by,
        "confirmed_at": now,
        "issue_type": normalized_issue_type,
        "resolution": normalized_resolution,
        "state_bound": (
            normalized_resolution
            in STATE_BOUND_RESOLUTIONS
        ),
        "notes": notes.strip(),
        "source": "human_decision_queue",
    }


async def confirm_current_decision(
    doc_id: str,
    confirmed_by: str = "human_decision_queue",
    issue_type: str = "",
    notes: str = "",
    resolution: str = "confirmed_current",
    db: Optional[Any] = None,
) -> Dict[str, Any]:
    if db is None:
        db = get_db()

    doc = await db.hub_documents.find_one(
        {"id": doc_id},
        {"_id": 0},
    )

    if not doc:
        raise ValueError(
            f"Document not found: {doc_id}"
        )

    if (
        doc.get("non_transactional") is True
        or doc.get("excluded_from_processing")
        is True
    ):
        raise ValueError(
            "Excluded documents cannot be confirmed"
        )

    state = current_document_state(doc)

    if confirmation_matches_current_state(
        doc,
        issue_type,
    ):
        return {
            "success": True,
            "skipped": True,
            "reason": "already_confirmed",
            "document_id": doc_id,
            "document_type": state["doc_type"],
            "mailbox_category": (
                state["mailbox_category"]
            ),
        }

    confirmation = build_confirmation_record(
        doc=doc,
        confirmed_by=confirmed_by,
        issue_type=issue_type,
        notes=notes,
        resolution=resolution,
    )

    confirmation_key = (
        confirmation["issue_type"]
        or "general"
    )

    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "decision_queue_confirmed": True,
                "decision_queue_confirmation": (
                    confirmation
                ),
                (
                    "decision_queue_confirmations."
                    + confirmation_key
                ): confirmation,
                "decision_queue_confirmed_at": (
                    confirmation["confirmed_at"]
                ),
                "decision_queue_confirmed_by": (
                    confirmed_by
                ),
                "updated_utc": (
                    confirmation["confirmed_at"]
                ),
            }
        },
    )

    audit_record = {
        **confirmation,
        "file_name": doc.get(
            "file_name",
            "",
        ),
        "vendor_raw": doc.get(
            "vendor_raw",
            "",
        ),
        "vendor_canonical": doc.get(
            "vendor_canonical",
            "",
        ),
    }

    await db.document_decision_confirmations.insert_one(
        audit_record
    )

    if confirmation["resolution"] != "confirmed_current":
        return {
            "success": True,
            "skipped": False,
            "document_id": doc_id,
            "document_type": state["doc_type"],
            "mailbox_category": (
                state["mailbox_category"]
            ),
            "resolution": (
                confirmation["resolution"]
            ),
            "classification_feedback": {
                "success": False,
                "reason": "not_applicable",
            },
            "sender_routing_override_written": False,
        }

    classification_feedback = {
        "success": False,
        "reason": "not_attempted",
    }

    try:
        from services.classification_feedback_service import (
            record_confirmation,
        )

        raw_text = (
            doc.get("raw_text")
            or doc.get("extracted_text")
            or ""
        )

        if not raw_text:
            fields = (
                doc.get("extracted_fields")
                or {}
            )

            raw_text = " | ".join(
                str(value)
                for value in fields.values()
                if value
                and not isinstance(
                    value,
                    (dict, list),
                )
            )

        classification_feedback = (
            await record_confirmation(
                doc_id=doc_id,
                confirmed_type=state["doc_type"],
                confirmation_source=(
                    "human_decision_queue"
                ),
                doc_context={
                    "file_name": doc.get(
                        "file_name",
                        "",
                    ),
                    "vendor_raw": doc.get(
                        "vendor_raw",
                        "",
                    ),
                    "vendor_canonical": doc.get(
                        "vendor_canonical",
                        "",
                    ),
                    "text_snippet": raw_text[:500],
                    "classification_method": (
                        doc.get(
                            "classification_method",
                            "",
                        )
                    ),
                    "classification_confidence": (
                        doc.get(
                            "classification_confidence"
                        )
                        or doc.get(
                            "ai_confidence"
                        )
                        or 0
                    ),
                },
            )
        )
    except Exception as exc:
        logger.warning(
            "Decision confirmation saved but "
            "classification feedback failed "
            "for %s: %s",
            doc_id,
            exc,
        )

        classification_feedback = {
            "success": False,
            "reason": str(exc)[:500],
        }

    return {
        "success": True,
        "skipped": False,
        "document_id": doc_id,
        "document_type": state["doc_type"],
        "mailbox_category": (
            state["mailbox_category"]
        ),
        "resolution": (
            confirmation["resolution"]
        ),
        "classification_feedback": (
            classification_feedback
        ),
        "sender_routing_override_written": False,
    }
