"""Document reprocessing orchestration.

Authoritative home for the safe, idempotent document reprocess pipeline that
previously lived in ``server.py``.  Route handlers and readiness tooling should
import ``reprocess_document`` or ``reprocess_document_inner`` from this module.

The compatibility functions in ``server.py`` may remain temporarily while
legacy tests and external imports are migrated.
"""

import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Any, Dict

from fastapi import HTTPException

from deps import get_db
from models.document_types import DEFAULT_JOB_TYPES, TransactionAction
from paths import UPLOAD_DIR
from services.auto_clear_service import (
    AutoClearDecision,
    evaluate_auto_clear,
    get_auto_clear_update,
)
from services.document_intel_helpers import (
    classify_document_with_ai,
    compute_ap_normalized_fields,
    make_automation_decision,
)
from workflows.document_capture.rules.workflow_status import (
    update_standard_workflow_status,
)

logger = logging.getLogger(__name__)


async def reprocess_document(doc_id: str, reclassify: bool = False) -> Dict[str, Any]:
    """Safely re-run classification, validation, resolution, and workflow state.

    This operation is intentionally idempotent. It does not duplicate
    SharePoint uploads, create replacement BC records for already-linked
    documents, or create draft invoices.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")

    try:
        result = await reprocess_document_inner(doc_id, doc, reclassify)
        if isinstance(result, dict) and "document" in result:
            result["document"].pop("file_content_b64", None)
        return result
    except Exception as exc:
        logger.error(
            "[REPROCESS] FATAL error reprocessing %s: %s",
            doc_id[:8],
            str(exc),
            exc_info=True,
        )
        return {
            "reprocessed": False,
            "error": str(exc),
            "error_type": type(exc).__name__,
            "old_status": doc.get("status"),
            "new_status": doc.get("status"),
            "document": doc,
            "reasoning": f"Reprocess failed: {str(exc)}",
        }


async def reprocess_document_inner(
    doc_id: str,
    doc: Dict[str, Any],
    reclassify: bool,
) -> Dict[str, Any]:
    """Execute the internal reprocess pipeline for an already-loaded document."""
    db = get_db()

    if doc.get("status") == "LinkedToBC":
        return {
            "reprocessed": False,
            "reason": "Document already linked to BC - no reprocessing needed",
            "document": doc,
        }

    if doc.get("bc_record_id"):
        return {
            "reprocessed": False,
            "reason": (
                f"BC record already exists ({doc.get('bc_record_id')}) "
                "- idempotency guard"
            ),
            "document": doc,
        }

    file_path = UPLOAD_DIR / doc_id
    file_content = file_path.read_bytes() if file_path.exists() else None

    if reclassify and not file_path.exists():
        file_b64 = doc.get("file_content_b64")
        if file_b64:
            try:
                import base64

                recovered_bytes = base64.b64decode(file_b64)
                file_path.write_bytes(recovered_bytes)
                file_content = recovered_bytes
                logger.info(
                    "[REPROCESS] Recovered file from MongoDB for %s (%d bytes)",
                    doc_id[:8],
                    len(recovered_bytes),
                )
            except Exception as exc:
                logger.warning(
                    "[REPROCESS] MongoDB file recovery failed for %s: %s",
                    doc_id[:8],
                    str(exc),
                )

        if not file_content:
            email_id = doc.get("email_id")
            if email_id:
                try:
                    from services.email_polling_service import (
                        fetch_email_with_attachments,
                    )

                    mailbox = os.environ.get("EMAIL_POLLING_USER", "")
                    if not mailbox:
                        mailbox = os.environ.get("SALES_EMAIL_POLLING_USER", "")

                    if mailbox:
                        logger.info(
                            "[REPROCESS] File not on disk, attempting email "
                            "re-fetch for %s (email_id=%s, mailbox=%s)",
                            doc_id[:8],
                            email_id[:20],
                            mailbox,
                        )
                        email_data = await fetch_email_with_attachments(
                            email_id,
                            mailbox,
                        )
                        if email_data and email_data.get("attachments"):
                            target_name = doc.get("file_name", "")
                            for attachment in email_data["attachments"]:
                                if (
                                    attachment.get("name") == target_name
                                    or not target_name
                                ):
                                    recovered_bytes = attachment.get("content_bytes")
                                    if recovered_bytes:
                                        file_path.write_bytes(recovered_bytes)
                                        file_content = recovered_bytes
                                        logger.info(
                                            "[REPROCESS] Recovered file from email: "
                                            "%s (%d bytes)",
                                            target_name,
                                            len(recovered_bytes),
                                        )
                                        break
                        if not file_content:
                            logger.warning(
                                "[REPROCESS] Email found but no matching "
                                "attachment for %s",
                                doc_id[:8],
                            )
                    else:
                        logger.warning(
                            "[REPROCESS] No EMAIL_POLLING_USER configured, "
                            "cannot recover file for %s",
                            doc_id[:8],
                        )
                except Exception as exc:
                    logger.warning(
                        "[REPROCESS] Email re-fetch failed for %s: %s",
                        doc_id[:8],
                        str(exc),
                    )

    if reclassify and file_path.exists():
        try:
            logger.info("Re-running AI classification for document %s", doc_id)
            classification = await classify_document_with_ai(
                str(file_path),
                doc["file_name"],
            )
            await db.hub_documents.update_one(
                {"id": doc_id},
                {
                    "$set": {
                        "document_type": classification.get(
                            "suggested_job_type", "Unknown"
                        ),
                        "suggested_job_type": classification.get(
                            "suggested_job_type", "Unknown"
                        ),
                        "ai_confidence": classification.get("confidence", 0.0),
                        "extracted_fields": classification.get(
                            "extracted_fields"
                        )
                        or {},
                        "updated_utc": datetime.now(timezone.utc).isoformat(),
                    }
                },
            )
            doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        except Exception as exc:
            logger.error(
                "[REPROCESS] AI classification crashed for %s: %s",
                doc_id[:8],
                str(exc),
            )

    job_type = doc.get("suggested_job_type", "AP_Invoice")
    job_config = await db.hub_job_types.find_one(
        {"job_type": job_type},
        {"_id": 0},
    )
    if not job_config:
        job_config = (
            DEFAULT_JOB_TYPES.get(job_type)
            or DEFAULT_JOB_TYPES.get("AP_Invoice")
            or {
                "job_type": job_type,
                "automation_level": 0,
                "requires_human_review_if_exception": True,
            }
        )

    extracted_fields = doc.get("extracted_fields") or {}

    try:
        from services.po_resolution_service import (
            attempt_bc_link,
            resolve_po_from_document,
        )

        po_result = await resolve_po_from_document(doc)
        bc_link_result = await attempt_bc_link(doc_id, po_result)
        po_result["bc_link"] = bc_link_result
        await db.hub_documents.update_one(
            {"id": doc_id},
            {
                "$set": {
                    "po_resolution": po_result,
                    "po_candidates": po_result.get("candidates_raw", []),
                }
            },
        )
        if po_result.get("po_number"):
            extracted_fields["_po_resolution_number"] = po_result["po_number"]
        valid_candidates = [
            candidate["normalized"]
            for candidate in po_result.get("candidates_valid", [])
            if candidate.get("valid_format") and not candidate.get("is_non_po")
        ]
        if valid_candidates:
            extracted_fields["_po_all_candidates"] = valid_candidates
    except Exception as exc:
        logger.warning(
            "[REPROCESS] PO resolution error for %s: %s",
            doc_id[:8],
            str(exc),
        )

    old_match_method = doc.get("match_method", "none")
    try:
        from services.bc_validation_service import validate_bc_match

        validation_results = await validate_bc_match(
            job_type,
            extracted_fields,
            job_config,
        )
    except Exception as exc:
        logger.error(
            "[REPROCESS] BC validation crashed for %s: %s",
            doc_id[:8],
            str(exc),
        )
        validation_results = {
            "all_passed": False,
            "checks": [
                {
                    "check_name": "validation_error",
                    "passed": False,
                    "details": str(exc),
                    "required": True,
                }
            ],
            "warnings": [],
            "match_method": "none",
            "match_score": 0.0,
            "normalized_fields": {},
            "validation_status": "fail",
        }

    if not validation_results:
        validation_results = {
            "all_passed": False,
            "checks": [],
            "warnings": [],
            "match_method": "none",
            "match_score": 0.0,
            "normalized_fields": {},
            "validation_status": "fail",
        }

    new_match_method = validation_results.get("match_method", "none")
    confidence = doc.get("ai_confidence") or 0.0
    doc_type_for_conf = (
        doc.get("doc_type")
        or doc.get("document_type")
        or doc.get("suggested_job_type")
        or ""
    )
    if (
        doc_type_for_conf not in ("Other", "Unknown", "Unknown_Document", "")
        and confidence < 0.5
    ):
        confidence = 0.85

    try:
        decision, reasoning, decision_metadata = make_automation_decision(
            job_config,
            confidence,
            validation_results,
        )
    except Exception as exc:
        logger.error("[REPROCESS] make_automation_decision error: %s", str(exc))
        decision = "needs_review"
        reasoning = f"Decision error: {str(exc)}"
        decision_metadata = {}

    decision_metadata = decision_metadata or {}
    old_status = doc.get("status")
    new_status = old_status
    transaction_action = doc.get("transaction_action", TransactionAction.NONE)
    share_link = doc.get("sharepoint_share_link_url")

    if validation_results.get("all_passed"):
        if share_link:
            new_status = "Validated"
            transaction_action = TransactionAction.VALIDATED
        else:
            new_status = "ValidationPassed"
    elif decision == "needs_review":
        new_status = "NeedsReview"

    is_ap_invoice = doc_type_for_conf.upper().replace(" ", "_") in (
        "AP_INVOICE",
        "PURCHASE_INVOICE",
    )
    if is_ap_invoice and new_status not in (
        "Validated",
        "ValidationPassed",
        "Posted",
        "ReadyForPost",
        "NeedsReview",
    ):
        new_status = "NeedsReview"

    workflow_status_map = {
        "Validated": "validated",
        "ValidationPassed": "validation_passed",
        "NeedsReview": "needs_review",
        "LinkedToBC": "linked_to_bc",
        "Posted": "posted",
        "ReadyForPost": "ready_for_post",
    }
    new_workflow_status = workflow_status_map.get(
        new_status,
        new_status.lower() if new_status else "pending",
    )

    update_data = {
        "validation_results": validation_results,
        "automation_decision": decision,
        "match_method": new_match_method,
        "match_score": validation_results.get("match_score", 0.0),
        "vendor_candidates": decision_metadata.get("vendor_candidates", []),
        "customer_candidates": decision_metadata.get("customer_candidates", []),
        "status": new_status,
        "workflow_status": new_workflow_status,
        "square9_stage": new_workflow_status,
        "transaction_action": transaction_action,
        "reprocessed_utc": datetime.now(timezone.utc).isoformat(),
        "updated_utc": datetime.now(timezone.utc).isoformat(),
        "last_error": None,
        "auto_cleared": False,
        "auto_clear_decision": None,
        "auto_clear_reason": None,
        "auto_clear_details": None,
    }
    await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})

    doc_type_value = (
        doc.get("doc_type")
        or doc.get("document_type")
        or doc.get("suggested_job_type")
        or ""
    )
    is_ap_reprocess = doc_type_value.upper().replace(" ", "_") in (
        "AP_INVOICE",
        "PURCHASE_INVOICE",
    )

    if is_ap_reprocess:
        try:
            vendor_from_validation = (
                validation_results.get("bc_record_info") or {}
            ).get("number")
            if vendor_from_validation:
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {"bc_vendor_number": vendor_from_validation}},
                )

            from services.ap_auto_post_service import finalize_ap_decision

            ap_finalize = await finalize_ap_decision(
                doc_id,
                db,
                source="reprocess",
                emit_reprocess_events=True,
                on_exception_fallback_status="NeedsReview",
            )
            new_status = ap_finalize["status"]
        except Exception as exc:
            logger.error(
                "[REPROCESS] AP Auto-Post error for %s: %s",
                doc_id[:8],
                str(exc),
            )
            new_status = "NeedsReview"
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {"status": "NeedsReview"}},
            )
    elif doc_type_value and doc_type_value.upper() != "AP_INVOICE":
        try:
            normalized_fields = compute_ap_normalized_fields(extracted_fields)
            await update_standard_workflow_status(
                doc_id,
                doc_type_value,
                confidence,
                normalized_fields,
            )
            refreshed = await db.hub_documents.find_one(
                {"id": doc_id},
                {"_id": 0, "status": 1, "workflow_status": 1},
            )
            if refreshed:
                new_status = refreshed.get("status", new_status)
                new_workflow_status = refreshed.get(
                    "workflow_status",
                    new_workflow_status,
                )
        except Exception as exc:
            logger.warning(
                "[REPROCESS] Workflow update error for %s: %s",
                doc_id[:8],
                str(exc),
            )

    if is_ap_reprocess:
        logger.info(
            "[REPROCESS] Auto-clear SKIPPED for AP_Invoice %s "
            "- using strict auto-post",
            doc_id[:8],
        )
    else:
        try:
            doc_for_evaluation = await db.hub_documents.find_one(
                {"id": doc_id},
                {"_id": 0},
            )
            if doc_for_evaluation:
                auto_clear_decision, auto_clear_reason, auto_clear_details = (
                    evaluate_auto_clear(
                        doc_for_evaluation,
                        validation_results=validation_results,
                    )
                )
                auto_clear_update = get_auto_clear_update(
                    auto_clear_decision,
                    auto_clear_details,
                )

                if auto_clear_decision == AutoClearDecision.NEEDS_REVIEW:
                    auto_clear_update["status"] = "NeedsReview"
                    auto_clear_update["workflow_status"] = "needs_review"
                    auto_clear_update["square9_stage"] = "needs_review"
                    new_status = "NeedsReview"
                    new_workflow_status = "needs_review"

                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": auto_clear_update},
                )
                if auto_clear_decision == AutoClearDecision.CLEARED:
                    new_status = "Completed"

                reprocess_timestamp = datetime.now(timezone.utc)
                await db.workflow_events.insert_one(
                    {
                        "event_id": str(uuid.uuid4()),
                        "document_id": doc_id,
                        "event_type": "system.reprocessed",
                        "timestamp": reprocess_timestamp.isoformat(),
                        "source_service": "reprocess",
                        "payload": {"trigger": "manual_reprocess"},
                    }
                )
                is_cleared = auto_clear_decision == AutoClearDecision.CLEARED
                await db.workflow_events.insert_one(
                    {
                        "event_id": str(uuid.uuid4()),
                        "document_id": doc_id,
                        "event_type": "automation.decision.completed",
                        "timestamp": (
                            reprocess_timestamp + timedelta(milliseconds=100)
                        ).isoformat(),
                        "source_service": "auto_clear_service",
                        "payload": {
                            "decision": (
                                "NeedsReview"
                                if auto_clear_decision
                                == AutoClearDecision.NEEDS_REVIEW
                                else auto_clear_decision.value
                            ),
                            "auto_clear": is_cleared,
                            "reason": auto_clear_reason,
                        },
                    }
                )

                try:
                    from services.derived_state_service import (
                        DerivedStateService,
                        get_derived_state_service,
                    )

                    derived_state_service = get_derived_state_service()
                    if not derived_state_service:
                        derived_state_service = DerivedStateService(db)
                    await derived_state_service.update_document_derived_state(doc_id)
                except Exception as exc:
                    logger.warning(
                        "[REPROCESS] Derived state error: %s",
                        str(exc),
                    )
        except Exception as exc:
            logger.warning(
                "[REPROCESS] Auto-clear error for %s: %s",
                doc_id[:8],
                str(exc),
            )

    workflow = {
        "id": str(uuid.uuid4()),
        "document_id": doc_id,
        "workflow_name": "reprocess",
        "started_utc": datetime.now(timezone.utc).isoformat(),
        "ended_utc": datetime.now(timezone.utc).isoformat(),
        "status": "Completed",
        "steps": [
            {
                "step": "revalidation",
                "status": "completed",
                "result": {
                    "old_match_method": old_match_method,
                    "new_match_method": new_match_method,
                    "validation_passed": validation_results.get("all_passed"),
                    "decision": decision,
                    "square9_aligned": True,
                    "reason": (
                        "Square9 workflow: validate data, confirm SharePoint "
                        "storage. BC attachment handled separately."
                    ),
                },
            },
            {
                "step": "status_transition",
                "status": "completed" if new_status != old_status else "no_change",
                "result": {
                    "old_status": old_status,
                    "new_status": new_status,
                    "sharepoint_stored": bool(share_link),
                },
            },
        ],
        "correlation_id": str(uuid.uuid4()),
        "error": None,
    }
    await db.hub_workflow_runs.insert_one(workflow)

    updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    return {
        "reprocessed": True,
        "status_changed": old_status != new_status,
        "old_status": old_status,
        "new_status": new_status,
        "match_method_changed": old_match_method != new_match_method,
        "old_match_method": old_match_method,
        "new_match_method": new_match_method,
        "validation_passed": validation_results.get("all_passed"),
        "sharepoint_stored": bool(share_link),
        "document": updated_doc,
        "reasoning": reasoning,
    }


# Temporary compatibility alias for callers that still use the private name.
_reprocess_document_inner = reprocess_document_inner
