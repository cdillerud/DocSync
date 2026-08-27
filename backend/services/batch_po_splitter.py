"""Batch PDF splitter with idempotent child intake and audit-safe replay."""

import hashlib
import io
import logging
from datetime import datetime, timezone

from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)

SPLITTABLE_TYPES = {
    "Purchase_Order", "PurchaseOrder", "Sales_Order", "SalesOrder",
    "AP_Invoice", "APInvoice", "AP Invoice", "Invoice",
    "BOL", "Bill_of_Lading", "BillOfLading",
    "Packing_Slip", "PackingSlip", "Shipping_Document",
    "Credit_Memo", "CreditMemo", "Unknown",
}
AUTO_SPLIT_MIN_PAGES = 2

_UNKNOWN_CHILD_TYPES = {
    None, "", "DEFAULT",
    "Unknown", "UNKNOWN", "unknown",
    "Unknown_Document", "UNKNOWN_DOCUMENT",
    "Unknown_Sales", "UNKNOWN_SALES",
    "Other", "OTHER",
}


def detect_batch_po(file_content: bytes, document_type: str) -> dict:
    """Determine whether a PDF contains multiple logical documents."""
    try:
        reader = PdfReader(io.BytesIO(file_content))
        page_count = len(reader.pages)
    except Exception as error:
        logger.warning("[BatchSplit] Failed to read PDF: %s", error)
        return {
            "should_split": False,
            "page_count": 0,
            "reason": f"pdf_read_error: {error}",
        }

    if page_count < AUTO_SPLIT_MIN_PAGES:
        return {"should_split": False, "page_count": page_count, "reason": "single_page"}

    if document_type in SPLITTABLE_TYPES or page_count >= 3:
        from services.document_boundary_service import analyze_document_boundaries

        analysis = analyze_document_boundaries(file_content)
        if analysis.get("should_split"):
            return {
                "should_split": True,
                "page_count": page_count,
                "document_count": analysis.get("document_count", page_count),
                "groups": analysis.get("groups", []),
                "boundaries": analysis.get("boundaries", []),
                "reason": analysis.get("analysis", f"multi_page ({page_count} pages)"),
                "split_mode": "boundary_aware",
            }
        if document_type in SPLITTABLE_TYPES:
            return {
                "should_split": False,
                "page_count": page_count,
                "document_count": 1,
                "reason": analysis.get(
                    "analysis", f"single_cohesive_document ({page_count} pages)"
                ),
            }

    return {
        "should_split": False,
        "page_count": page_count,
        "reason": f"not_splittable_type ({document_type})",
    }


def split_pdf_pages(file_content: bytes) -> list[dict]:
    """Split a PDF into one-page PDFs with stable content hashes."""
    reader = PdfReader(io.BytesIO(file_content))
    pages = []
    for index, page in enumerate(reader.pages):
        writer = PdfWriter()
        writer.add_page(page)
        buffer = io.BytesIO()
        writer.write(buffer)
        pdf_bytes = buffer.getvalue()
        pages.append({
            "page_num": index + 1,
            "pdf_bytes": pdf_bytes,
            "page_size": len(pdf_bytes),
            "page_hash": hashlib.sha256(pdf_bytes).hexdigest(),
        })
    logger.info("[BatchSplit] Split PDF into %d pages", len(pages))
    return pages


async def _existing_child_by_hash(db, child_hash: str) -> dict:
    """Return an existing canonical child instead of deleting/recreating it."""
    return await db.hub_documents.find_one(
        {"sha256_hash": child_hash, "is_duplicate": {"$ne": True}},
        {
            "_id": 0,
            "id": 1,
            "document_type": 1,
            "doc_type": 1,
            "suggested_job_type": 1,
            "batch_parent_id": 1,
            "batch_parent_ids": 1,
        },
    ) or {}


async def _record_child_parent_link(
    db,
    child_doc_id: str,
    parent_doc_id: str,
    parent_filename: str,
    pages: list[int],
    total_pages: int,
    split_mode: str,
    group_num: int,
    reused_existing: bool,
) -> None:
    now = datetime.now(timezone.utc).isoformat()
    set_fields = {
        "batch_page_num": pages[0] if len(pages) == 1 else None,
        "batch_pages": sorted(pages),
        "batch_total_pages": total_pages,
        "batch_source_filename": parent_filename,
        "batch_split_mode": split_mode,
        "batch_group_num": group_num,
        "batch_last_parent_link_at": now,
    }
    if not reused_existing:
        set_fields["batch_parent_id"] = parent_doc_id
    else:
        set_fields["batch_reused_existing"] = True
        set_fields["batch_reused_at"] = now

    await db.hub_documents.update_one(
        {"id": child_doc_id},
        {
            "$set": set_fields,
            "$addToSet": {"batch_parent_ids": parent_doc_id},
        },
    )


async def split_and_ingest_batch(
    db,
    parent_doc_id: str,
    parent_filename: str,
    file_content: bytes,
    sender: str = "",
    source: str = "batch_split",
    subject: str = "",
    on_page_done=None,
    groups: list = None,
) -> dict:
    """Split a PDF and ingest each logical child exactly once by content hash."""
    from services.document_bytes_intake_service import intake_document_from_bytes

    now = datetime.now(timezone.utc).isoformat()
    reader = PdfReader(io.BytesIO(file_content))
    total_pages = len(reader.pages)

    parent_doc = await db.hub_documents.find_one(
        {"id": parent_doc_id},
        {
            "_id": 0,
            "doc_type": 1,
            "document_type": 1,
            "suggested_job_type": 1,
            "vendor_canonical": 1,
            "vendor_id": 1,
            "vendor_name": 1,
            "customer_canonical": 1,
            "customer_id": 1,
            "mailbox_category": 1,
            "source_mailbox_address": 1,
            "source_mailbox_id": 1,
            "source_mailbox_category": 1,
            "source_graph_message_id": 1,
            "source_internet_message_id": 1,
            "source_attachment_id": 1,
        },
    ) or {}

    if groups:
        split_units = [
            {
                "pages": group["pages"],
                "label": f"doc{group['group_num']}",
                "vendor_hint": group.get("vendor_hint", ""),
                "doc_type_hints": group.get("doc_type_hints", []),
            }
            for group in groups
        ]
        split_mode = "boundary_aware"
    else:
        split_units = [
            {"pages": [index + 1], "label": f"p{index + 1}"}
            for index in range(total_pages)
        ]
        split_mode = "per_page"

    base_name = parent_filename.rsplit(".", 1)[0] if "." in parent_filename else parent_filename
    extension = parent_filename.rsplit(".", 1)[1] if "." in parent_filename else "pdf"

    async def _process_unit(unit: dict, unit_index: int) -> dict:
        pages = sorted(unit["pages"])
        label = unit.get("label", f"part{unit_index + 1}")
        writer = PdfWriter()
        for page_number in pages:
            if 1 <= page_number <= total_pages:
                writer.add_page(reader.pages[page_number - 1])

        buffer = io.BytesIO()
        writer.write(buffer)
        child_bytes = buffer.getvalue()
        child_hash = hashlib.sha256(child_bytes).hexdigest()
        child_filename = f"{base_name}_{label}.{extension}"
        page_range = f"{min(pages)}-{max(pages)}" if len(pages) > 1 else str(pages[0])

        try:
            existing = await _existing_child_by_hash(db, child_hash)
            reused_existing = bool(existing.get("id"))

            if reused_existing:
                child_doc_id = str(existing["id"])
                result = {
                    "document_id": child_doc_id,
                    "document_type": (
                        existing.get("document_type")
                        or existing.get("doc_type")
                        or existing.get("suggested_job_type")
                        or ""
                    ),
                    "skipped_duplicate": True,
                }
                logger.info(
                    "[BatchSplit] Reusing existing child %s for parent=%s pages=%s hash=%s",
                    child_doc_id[:8],
                    parent_doc_id[:8],
                    page_range,
                    child_hash[:12],
                )
            else:
                child_subject = (
                    f"{subject} [Pages {page_range}/{total_pages}]"
                    if subject
                    else f"Split from {parent_filename} [Pages {page_range}/{total_pages}]"
                )
                result = await intake_document_from_bytes(
                    file_content=child_bytes,
                    filename=child_filename,
                    content_type="application/pdf",
                    source=source,
                    sender=sender,
                    subject=child_subject,
                    email_id=f"batch-{parent_doc_id[:8]}-{label}",
                    mailbox_category=parent_doc.get("mailbox_category"),
                )
                child_doc_id = (
                    result.get("document_id")
                    or (result.get("document") or {}).get("id")
                    or ""
                )

            if not child_doc_id:
                raise RuntimeError("Child intake returned no document id")

            await _record_child_parent_link(
                db=db,
                child_doc_id=child_doc_id,
                parent_doc_id=parent_doc_id,
                parent_filename=parent_filename,
                pages=pages,
                total_pages=total_pages,
                split_mode=split_mode,
                group_num=unit_index + 1,
                reused_existing=reused_existing,
            )

            # Preserve the exact receiving mailbox/message provenance through the
            # split boundary. New children inherit the parent as first-seen source;
            # reused canonical children only append this parent observation.
            if (
                parent_doc.get("source_mailbox_address")
                or parent_doc.get("source_mailbox_id")
                or parent_doc.get("source_graph_message_id")
                or parent_doc.get("source_internet_message_id")
            ):
                from services.mailbox_provenance_service import persist_mailbox_provenance

                await persist_mailbox_provenance(
                    db,
                    child_doc_id,
                    mailbox_address=parent_doc.get("source_mailbox_address"),
                    mailbox_id=parent_doc.get("source_mailbox_id"),
                    mailbox_category=(
                        parent_doc.get("source_mailbox_category")
                        or parent_doc.get("mailbox_category")
                    ),
                    graph_message_id=parent_doc.get("source_graph_message_id"),
                    internet_message_id=parent_doc.get("source_internet_message_id"),
                    attachment_id=parent_doc.get("source_attachment_id"),
                    source="batch_split_parent",
                    set_first_seen=not reused_existing,
                )

            if not reused_existing:
                await _inherit_parent_and_reevaluate(
                    db=db,
                    child_doc_id=child_doc_id,
                    parent_doc=parent_doc,
                    unit_vendor_hint=unit.get("vendor_hint", ""),
                )

            child_info = {
                "group_num": unit_index + 1,
                "pages": pages,
                "page_count": len(pages),
                "child_doc_id": child_doc_id,
                "filename": child_filename,
                "content_hash": child_hash,
                "status": "success",
                "reused_existing": reused_existing,
                "document_type": (
                    result.get("document_type")
                    or (result.get("document") or {}).get("document_type")
                    or ""
                ),
                "vendor_hint": unit.get("vendor_hint", ""),
            }
            if on_page_done:
                await on_page_done(unit_index + 1, len(split_units), child_info)
            return child_info
        except Exception as error:
            logger.error(
                "[BatchSplit] Error on group %d (pages %s): %s",
                unit_index + 1,
                pages,
                error,
            )
            error_info = {
                "group_num": unit_index + 1,
                "pages": pages,
                "child_doc_id": "",
                "filename": child_filename,
                "content_hash": child_hash,
                "status": "error",
                "error": str(error),
            }
            if on_page_done:
                await on_page_done(unit_index + 1, len(split_units), error_info)
            return error_info

    children = []
    for index, unit in enumerate(split_units):
        children.append(await _process_unit(unit, index))

    errors = [child for child in children if child["status"] == "error"]
    await db.hub_documents.update_one(
        {"id": parent_doc_id},
        {"$set": {
            "batch_split": True,
            "batch_split_at": now,
            "batch_split_mode": split_mode,
            "batch_children_count": len(children),
            "batch_document_count": len(children),
            "batch_children_ids": [
                child["child_doc_id"] for child in children if child.get("child_doc_id")
            ],
            "batch_split_errors": len(errors),
            "batch_split_reused_count": sum(
                1 for child in children if child.get("reused_existing")
            ),
            "updated_utc": now,
        }},
    )

    status = "success" if not errors else (
        "partial" if len(children) > len(errors) else "error"
    )
    return {
        "status": status,
        "parent_doc_id": parent_doc_id,
        "parent_filename": parent_filename,
        "split_mode": split_mode,
        "total_pages": total_pages,
        "children_count": len(children),
        "children_success": sum(1 for child in children if child["status"] == "success"),
        "children_errors": len(errors),
        "children_reused": sum(1 for child in children if child.get("reused_existing")),
        "children": children,
    }


async def _inherit_parent_and_reevaluate(
    db,
    child_doc_id: str,
    parent_doc: dict,
    unit_vendor_hint: str = "",
) -> None:
    """Fail uncertain split children to NeedsReview while preserving AI evidence."""
    try:
        child = await db.hub_documents.find_one({"id": child_doc_id}, {"_id": 0})
        if not child:
            return

        child_type = (
            child.get("doc_type")
            or child.get("document_type")
            or child.get("suggested_job_type")
            or ""
        )
        child_confidence = (
            (child.get("ai_classification") or {}).get("confidence")
            or child.get("classification_confidence")
            or child.get("ai_confidence")
            or 0.0
        )
        try:
            child_confidence = float(child_confidence)
        except (TypeError, ValueError):
            child_confidence = 0.0

        if child_type not in _UNKNOWN_CHILD_TYPES and child_confidence >= 0.70:
            return

        parent_type = (
            parent_doc.get("doc_type")
            or parent_doc.get("document_type")
            or parent_doc.get("suggested_job_type")
            or ""
        )
        parent_vendor = (
            parent_doc.get("vendor_canonical") or parent_doc.get("vendor_name") or ""
        )
        parent_customer = parent_doc.get("customer_canonical") or ""
        update_fields = {
            "parent_inheritance_applied": True,
            "parent_inheritance_at": datetime.now(timezone.utc).isoformat(),
            "doc_type_from_split_ai": child_type or None,
            "classification_confidence_from_split_ai": child_confidence,
            "status": "NeedsReview",
            "workflow_status": "needs_review",
            "square9_stage": "needs_review",
            "queue_visible": True,
            "auto_cleared": False,
            "auto_clear_decision": "needs_review",
            "auto_clear_details": {
                "checks": [{
                    "check": "split_child_unclassified_guard",
                    "passed": False,
                    "message": (
                        f"Split child AI doc_type='{child_type or 'None'}' "
                        f"conf={child_confidence:.2f} — inherited parent "
                        f"doc_type='{parent_type or 'None'}', requiring human review"
                    ),
                }],
                "unclassified_guard_triggered": True,
                "parent_inheritance_applied": True,
            },
            "updated_utc": datetime.now(timezone.utc).isoformat(),
        }

        if parent_type and parent_type not in _UNKNOWN_CHILD_TYPES:
            update_fields["doc_type"] = parent_type
            update_fields["document_type"] = parent_type
            update_fields["suggested_job_type"] = parent_type
        if parent_vendor and not child.get("vendor_canonical"):
            update_fields["vendor_canonical"] = parent_vendor
            update_fields["vendor_inherited_from_parent"] = True
        if parent_doc.get("vendor_id") and not child.get("vendor_id"):
            update_fields["vendor_id"] = parent_doc["vendor_id"]
        if parent_customer and not child.get("customer_canonical"):
            update_fields["customer_canonical"] = parent_customer
        if unit_vendor_hint and not child.get("vendor_canonical"):
            update_fields.setdefault("vendor_canonical", unit_vendor_hint)

        await db.hub_documents.update_one(
            {"id": child_doc_id},
            {"$set": update_fields},
        )
        logger.info(
            "[BatchSplit] Child %s uncertain (type=%s conf=%.2f); inherited parent context and forced NeedsReview",
            child_doc_id[:8],
            child_type or "None",
            child_confidence,
        )
    except Exception as error:
        logger.warning(
            "[BatchSplit] Inheritance/re-evaluate failed for child %s: %s",
            child_doc_id[:8] if child_doc_id else "?",
            error,
        )
