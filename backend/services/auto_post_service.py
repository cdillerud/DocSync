"""
GPI Document Hub - controlled Business Central write service.

AP invoice behavior is preserved. Sales-order automation now uses deterministic
preflight validation and is disabled by default until a reviewed candidate is
explicitly approved.
"""

from __future__ import annotations

import logging
import os
from datetime import datetime, timezone
from typing import Any, Dict, Optional

from pymongo import ReturnDocument

from services.sales_order_bc_writer import create_sales_order_draft
from services.sales_order_preflight import (
    build_bc_sales_order_payload,
    preflight_sales_order,
)

logger = logging.getLogger(__name__)

AUTO_POST_ENABLED = os.environ.get("AUTO_POST_ENABLED", "true").lower() in (
    "true",
    "1",
    "yes",
)
AUTO_POST_CONFIDENCE_THRESHOLD = float(
    os.environ.get("AUTO_POST_CONFIDENCE_THRESHOLD", "0.90")
)

# Sales-order writes are intentionally opt-in. Shadow/preflight mode remains
# available while this flag is false.
AUTO_CREATE_SALES_ORDER_ENABLED = os.environ.get(
    "AUTO_CREATE_SALES_ORDER_ENABLED", "false"
).lower() in ("true", "1", "yes")
SALES_ORDER_CONFIDENCE_THRESHOLD = float(
    os.environ.get("SALES_ORDER_CONFIDENCE_THRESHOLD", "0.90")
)
SALES_ORDER_ITEM_MATCH_THRESHOLD = float(
    os.environ.get("SALES_ORDER_ITEM_MATCH_THRESHOLD", "0.95")
)


class AutoPostResult:
    """Normalized result for AP posting and sales-order creation."""

    def __init__(
        self,
        eligible: bool = False,
        attempted: bool = False,
        success: bool = False,
        bc_document_id: str = None,
        bc_document_number: str = None,
        error: str = None,
        reason: str = None,
        details: Optional[Dict[str, Any]] = None,
    ):
        self.eligible = eligible
        self.attempted = attempted
        self.success = success
        self.bc_document_id = bc_document_id
        self.bc_document_number = bc_document_number
        self.error = error
        self.reason = reason
        self.details = details or {}
        self.timestamp = datetime.now(timezone.utc).isoformat()

    def to_dict(self) -> Dict[str, Any]:
        return {
            "eligible": self.eligible,
            "attempted": self.attempted,
            "success": self.success,
            "bc_document_id": self.bc_document_id,
            "bc_document_number": self.bc_document_number,
            "error": self.error,
            "reason": self.reason,
            "details": self.details,
            "timestamp": self.timestamp,
        }


# =============================================================================
# AP INVOICE AUTO-POST
# =============================================================================


def check_auto_post_eligibility(doc: Dict[str, Any]) -> tuple[bool, str]:
    if not AUTO_POST_ENABLED:
        return False, "Auto-post disabled (AUTO_POST_ENABLED=false)"

    doc_type = str(doc.get("doc_type", "")).upper()
    if doc_type != "AP_INVOICE":
        return False, f"Not an AP invoice (doc_type={doc_type})"

    ai_extraction = doc.get("ai_extraction", {}) or {}
    confidence = (
        ai_extraction.get("confidence", 0)
        or doc.get("classification_confidence", 0)
        or 0
    )
    if confidence < AUTO_POST_CONFIDENCE_THRESHOLD:
        return (
            False,
            f"Confidence too low ({confidence:.2f} < "
            f"{AUTO_POST_CONFIDENCE_THRESHOLD:.2f})",
        )

    extracted_fields = doc.get("extracted_fields", {}) or {}
    invoice_number = (
        doc.get("invoice_number_clean")
        or extracted_fields.get("invoice_number")
        or ai_extraction.get("invoice_number")
    )
    if not invoice_number:
        return False, "Missing invoice number"

    invoice_date = (
        doc.get("invoice_date")
        or extracted_fields.get("invoice_date")
        or ai_extraction.get("invoice_date")
    )
    if not invoice_date:
        return False, "Missing invoice date"

    total_amount = (
        doc.get("amount_float")
        or extracted_fields.get("amount")
        or ai_extraction.get("total_amount")
    )
    if total_amount is None:
        return False, "Missing total amount"

    vendor_id = doc.get("vendor_id") or doc.get("vendor_canonical")
    if not vendor_id:
        return False, "Vendor not matched to BC"

    sharepoint_url = (
        doc.get("sharepoint_share_link_url") or doc.get("sharepoint_web_url")
    )
    if not sharepoint_url:
        return False, "Document not in SharePoint"

    if doc.get("bc_posting_status") == "posted":
        return False, "Already posted to BC"

    return True, "All criteria met"


async def attempt_auto_post(
    doc_id: str, doc: Dict[str, Any], db, bc_service
) -> AutoPostResult:
    eligible, reason = check_auto_post_eligibility(doc)
    if not eligible:
        return AutoPostResult(eligible=False, reason=reason)

    ai_extraction = doc.get("ai_extraction", {}) or {}
    extracted_fields = doc.get("extracted_fields", {}) or {}
    invoice_data = {
        "vendorNumber": doc.get("vendor_id") or doc.get("vendor_canonical"),
        "invoiceNumber": (
            doc.get("invoice_number_clean")
            or extracted_fields.get("invoice_number")
            or ai_extraction.get("invoice_number")
        ),
        "invoiceDate": (
            doc.get("invoice_date")
            or extracted_fields.get("invoice_date")
            or ai_extraction.get("invoice_date")
        ),
        "dueDate": (
            doc.get("due_date_iso")
            or extracted_fields.get("due_date")
            or ai_extraction.get("due_date")
        ),
        "currencyCode": doc.get("currency", "USD"),
        "lines": doc.get("line_items", []),
    }

    now = datetime.now(timezone.utc).isoformat()
    try:
        await db.hub_documents.update_one(
            {"id": doc_id},
            {
                "$set": {
                    "bc_posting_status": "auto_posting",
                    "auto_post_attempted": True,
                    "auto_post_attempted_at": now,
                    "updated_utc": now,
                }
            },
        )

        result = await bc_service.create_purchase_invoice(invoice_data)
        if not result.get("success"):
            error_msg = (
                result.get("error")
                or result.get("details")
                or "Unknown Business Central error"
            )
            await _mark_ap_failure(db, doc_id, error_msg)
            return AutoPostResult(
                eligible=True,
                attempted=True,
                success=False,
                error=error_msg,
                reason="BC API error",
            )

        bc_document_id = result.get("bcDocumentId")
        bc_document_number = result.get("bcDocumentNumber")
        sharepoint_url = (
            doc.get("sharepoint_share_link_url") or doc.get("sharepoint_web_url")
        )
        link_writeback_status = "skipped"

        if sharepoint_url and bc_document_id:
            try:
                writeback_result = await bc_service.update_purchase_invoice_link(
                    invoice_id=bc_document_id,
                    sharepoint_url=sharepoint_url,
                    bc_document_no=bc_document_number,
                    uploaded_by="GPI Hub (Auto-Post)",
                )
                link_writeback_status = (
                    "success" if writeback_result.get("success") else "failed"
                )
            except Exception as exc:
                logger.warning(
                    "Auto-post link writeback failed for %s: %s", doc_id, exc
                )
                link_writeback_status = "failed"

        completed_at = datetime.now(timezone.utc).isoformat()
        await db.hub_documents.update_one(
            {"id": doc_id},
            {
                "$set": {
                    "bc_document_id": bc_document_id,
                    "bc_document_number": bc_document_number,
                    "bc_posting_status": "posted",
                    "bc_posting_error": None,
                    "bc_link_writeback_status": link_writeback_status,
                    "review_status": "auto_posted",
                    "status": "Posted",
                    "workflow_status": "posted",
                    "auto_post_success": True,
                    "posted_to_bc_utc": completed_at,
                    "updated_utc": completed_at,
                }
            },
        )
        return AutoPostResult(
            eligible=True,
            attempted=True,
            success=True,
            bc_document_id=bc_document_id,
            bc_document_number=bc_document_number,
            reason="Auto-posted successfully",
        )
    except Exception as exc:
        error_msg = str(exc)
        logger.exception("AUTO-POST EXCEPTION: Doc %s", doc_id)
        await _mark_ap_failure(db, doc_id, error_msg)
        return AutoPostResult(
            eligible=True,
            attempted=True,
            success=False,
            error=error_msg,
            reason="Exception during auto-post",
        )


async def _mark_ap_failure(db, doc_id: str, error_msg: str) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "bc_posting_status": "auto_post_failed",
                "bc_posting_error": error_msg,
                "review_status": "needs_review",
                "auto_post_success": False,
                "updated_utc": now,
            }
        },
    )


async def process_document_for_auto_post(
    doc_id: str, db, bc_service
) -> AutoPostResult:
    doc = await db.hub_documents.find_one({"id": doc_id})
    if not doc:
        return AutoPostResult(
            eligible=False, reason=f"Document {doc_id} not found"
        )
    return await attempt_auto_post(doc_id, doc, db, bc_service)


# =============================================================================
# SALES ORDER PREFLIGHT AND CONTROLLED CREATION
# =============================================================================


def check_sales_order_eligibility(doc: Dict[str, Any]) -> tuple[bool, str]:
    if not AUTO_CREATE_SALES_ORDER_ENABLED:
        return False, (
            "Auto-create sales order disabled "
            "(AUTO_CREATE_SALES_ORDER_ENABLED=false)"
        )

    preflight = preflight_sales_order(
        doc,
        confidence_threshold=SALES_ORDER_CONFIDENCE_THRESHOLD,
        item_match_threshold=SALES_ORDER_ITEM_MATCH_THRESHOLD,
        require_sharepoint=True,
        require_approval=True,
    )
    if not preflight.can_create:
        codes = ", ".join(issue.code for issue in preflight.errors)
        return False, f"Sales-order preflight failed: {codes}"

    return True, "All sales-order preflight criteria met"


async def attempt_auto_create_sales_order(
    doc_id: str, doc: Dict[str, Any], db, bc_service
) -> AutoPostResult:
    preflight = preflight_sales_order(
        doc,
        confidence_threshold=SALES_ORDER_CONFIDENCE_THRESHOLD,
        item_match_threshold=SALES_ORDER_ITEM_MATCH_THRESHOLD,
        require_sharepoint=True,
        require_approval=True,
    )
    preflight_dict = preflight.to_dict()
    now = datetime.now(timezone.utc).isoformat()

    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "sales_order_preflight": preflight_dict,
                "sales_order_preflight_at": now,
                "bc_create_ready": preflight.can_create,
                "updated_utc": now,
            }
        },
    )

    if not AUTO_CREATE_SALES_ORDER_ENABLED:
        return AutoPostResult(
            eligible=False,
            reason=(
                "Sales-order preflight completed in shadow mode; "
                "AUTO_CREATE_SALES_ORDER_ENABLED=false"
            ),
            details=preflight_dict,
        )

    if not preflight.can_create:
        reason = "; ".join(issue.message for issue in preflight.errors[:5])
        return AutoPostResult(
            eligible=False,
            reason=reason or "Sales-order preflight failed",
            details=preflight_dict,
        )

    candidate = preflight.candidate
    duplicate = await _find_duplicate_sales_order(
        db,
        doc_id=doc_id,
        customer_number=candidate["customerNumber"],
        external_document_number=candidate["externalDocumentNumber"],
    )
    if duplicate:
        reason = (
            "Duplicate customer PO already exists in the Hub"
            f" ({duplicate.get('bc_sales_order_number') or duplicate.get('id')})"
        )
        await db.hub_documents.update_one(
            {"id": doc_id},
            {
                "$set": {
                    "bc_posting_status": "duplicate_blocked",
                    "auto_create_error": reason,
                    "review_status": "needs_review",
                    "updated_utc": datetime.now(timezone.utc).isoformat(),
                }
            },
        )
        return AutoPostResult(
            eligible=False,
            reason=reason,
            details={
                **preflight_dict,
                "duplicate_document_id": duplicate.get("id"),
            },
        )

    # Atomic lock prevents parallel poll/workflow calls from creating the same order.
    locked = await db.hub_documents.find_one_and_update(
        {
            "id": doc_id,
            "bc_document_id": {"$exists": False},
            "bc_sales_order_id": {"$exists": False},
            "bc_posting_status": {"$nin": ["auto_creating", "created"]},
        },
        {
            "$set": {
                "bc_posting_status": "auto_creating",
                "auto_create_attempted": True,
                "auto_create_attempted_at": datetime.now(
                    timezone.utc
                ).isoformat(),
                "sales_order_idempotency_key": candidate["idempotencyKey"],
                "updated_utc": datetime.now(timezone.utc).isoformat(),
            }
        },
        return_document=ReturnDocument.AFTER,
    )
    if not locked:
        return AutoPostResult(
            eligible=False,
            reason="Sales-order creation is already in progress or completed",
            details=preflight_dict,
        )

    order_data = build_bc_sales_order_payload(candidate)

    try:
        result = await create_sales_order_draft(bc_service, order_data)
        if not result.get("success"):
            error_msg = (
                result.get("error")
                or result.get("details")
                or "Unknown Business Central error"
            )
            bc_document_id = result.get("bcDocumentId")
            bc_document_number = result.get("bcDocumentNumber")
            manual_cleanup = bool(result.get("manualCleanupRequired"))
            await db.hub_documents.update_one(
                {"id": doc_id},
                {
                    "$set": {
                        "bc_document_id": bc_document_id,
                        "bc_document_number": bc_document_number,
                        "bc_sales_order_id": bc_document_id,
                        "bc_sales_order_number": bc_document_number,
                        "bc_posting_status": (
                            "auto_create_partial"
                            if manual_cleanup
                            else "auto_create_failed"
                        ),
                        "bc_posting_error": error_msg,
                        "bc_line_errors": result.get("lineErrors") or [],
                        "manual_bc_cleanup_required": manual_cleanup,
                        "review_status": "needs_review",
                        "auto_create_success": False,
                        "updated_utc": datetime.now(timezone.utc).isoformat(),
                    }
                },
            )
            return AutoPostResult(
                eligible=True,
                attempted=True,
                success=False,
                bc_document_id=bc_document_id,
                bc_document_number=bc_document_number,
                error=error_msg,
                reason=(
                    "Partial BC sales order created"
                    if manual_cleanup
                    else "BC API error; order rolled back or not created"
                ),
                details={
                    **preflight_dict,
                    "line_errors": result.get("lineErrors") or [],
                    "rolled_back": result.get("rolledBack", False),
                },
            )

        bc_document_id = result.get("bcDocumentId")
        bc_document_number = result.get("bcDocumentNumber")
        completed_at = datetime.now(timezone.utc).isoformat()
        await db.hub_documents.update_one(
            {"id": doc_id},
            {
                "$set": {
                    "bc_document_id": bc_document_id,
                    "bc_document_number": bc_document_number,
                    "bc_sales_order_id": bc_document_id,
                    "bc_sales_order_number": bc_document_number,
                    "bc_posting_status": "created",
                    "bc_posting_error": None,
                    "review_status": "auto_created",
                    "status": "Created",
                    "workflow_status": "exported",
                    "auto_create_success": True,
                    "manual_bc_cleanup_required": False,
                    "created_in_bc_utc": completed_at,
                    "updated_utc": completed_at,
                }
            },
        )
        return AutoPostResult(
            eligible=True,
            attempted=True,
            success=True,
            bc_document_id=bc_document_id,
            bc_document_number=bc_document_number,
            reason="Sales Order created successfully",
            details=preflight_dict,
        )
    except Exception as exc:
        error_msg = str(exc)
        logger.exception("AUTO-CREATE EXCEPTION: Doc %s", doc_id)
        await _mark_sales_order_failure(
            db, doc_id, error_msg, status="auto_create_failed"
        )
        return AutoPostResult(
            eligible=True,
            attempted=True,
            success=False,
            error=error_msg,
            reason="Exception during auto-create",
            details=preflight_dict,
        )


async def _find_duplicate_sales_order(
    db,
    *,
    doc_id: str,
    customer_number: str,
    external_document_number: str,
) -> Optional[Dict[str, Any]]:
    customer_fields = [
        {"bc_customer_number": customer_number},
        {"bc_customer_no": customer_number},
        {"customer_number_resolved": customer_number},
        {"normalized_fields.bc_customer_number": customer_number},
        {"normalized_fields.customer_number": customer_number},
        {"data.customer_number": customer_number},
    ]
    po_fields = [
        {"order_number_extracted": external_document_number},
        {"customer_po_number": external_document_number},
        {"normalized_fields.customer_po": external_document_number},
        {"normalized_fields.po_number": external_document_number},
        {"extracted_fields.customer_po_no": external_document_number},
        {"extracted_fields.po_number": external_document_number},
        {"data.customer_po": external_document_number},
    ]

    return await db.hub_documents.find_one(
        {
            "id": {"$ne": doc_id},
            "$and": [
                {"$or": customer_fields},
                {"$or": po_fields},
                {
                    "$or": [
                        {"bc_sales_order_id": {"$exists": True, "$ne": None}},
                        {"bc_document_id": {"$exists": True, "$ne": None}},
                        {
                            "bc_posting_status": {
                                "$in": [
                                    "auto_creating",
                                    "created",
                                    "auto_create_partial",
                                ]
                            }
                        },
                    ]
                },
            ],
        },
        {
            "_id": 0,
            "id": 1,
            "bc_sales_order_number": 1,
            "bc_document_number": 1,
        },
    )


async def _mark_sales_order_failure(
    db, doc_id: str, error_msg: str, *, status: str
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    await db.hub_documents.update_one(
        {"id": doc_id},
        {
            "$set": {
                "bc_posting_status": status,
                "bc_posting_error": error_msg,
                "auto_create_error": error_msg,
                "review_status": "needs_review",
                "auto_create_success": False,
                "updated_utc": now,
            }
        },
    )
