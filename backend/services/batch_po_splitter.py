"""
Batch PO Splitter Service

Detects multi-page Purchase Order PDFs and splits each page into a separate
document that runs through the full intake pipeline independently.

Flow:
  1. Parent PDF received → classified as Purchase_Order (multi-page)
  2. Auto-split: each page extracted as its own PDF
  3. Each child PDF → _internal_intake_document → classify → extract → validate → auto-assign
  4. Parent doc updated with split metadata + links to children
  5. Each child lands in the correct rep's My Queue or Triage

Supports both automatic (during intake) and manual (via API endpoint) splitting.
"""

import io
import logging
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Optional

from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)

# Document types eligible for batch splitting
SPLITTABLE_TYPES = {
    "Purchase_Order", "PurchaseOrder", "Sales_Order", "SalesOrder",
}

# Minimum pages to trigger auto-split
AUTO_SPLIT_MIN_PAGES = 2


def detect_batch_po(file_content: bytes, document_type: str) -> dict:
    """Check if a PDF is a multi-page batch PO that should be split.

    Returns:
        dict with keys: should_split (bool), page_count (int), reason (str)
    """
    if document_type not in SPLITTABLE_TYPES:
        return {"should_split": False, "page_count": 0, "reason": "not_splittable_type"}

    try:
        reader = PdfReader(io.BytesIO(file_content))
        page_count = len(reader.pages)
    except Exception as e:
        logger.warning("[BatchSplit] Failed to read PDF: %s", str(e))
        return {"should_split": False, "page_count": 0, "reason": f"pdf_read_error: {e}"}

    if page_count < AUTO_SPLIT_MIN_PAGES:
        return {"should_split": False, "page_count": page_count, "reason": "single_page"}

    return {
        "should_split": True,
        "page_count": page_count,
        "reason": f"multi_page_po ({page_count} pages)",
    }


def split_pdf_pages(file_content: bytes) -> list[dict]:
    """Split a PDF into individual page PDFs.

    Returns:
        List of dicts: [{page_num, pdf_bytes, page_hash}, ...]
    """
    reader = PdfReader(io.BytesIO(file_content))
    pages = []

    for i, page in enumerate(reader.pages):
        writer = PdfWriter()
        writer.add_page(page)

        buf = io.BytesIO()
        writer.write(buf)
        pdf_bytes = buf.getvalue()

        pages.append({
            "page_num": i + 1,
            "pdf_bytes": pdf_bytes,
            "page_size": len(pdf_bytes),
            "page_hash": hashlib.sha256(pdf_bytes).hexdigest(),
        })

    logger.info("[BatchSplit] Split PDF into %d pages", len(pages))
    return pages


async def split_and_ingest_batch(
    db,
    parent_doc_id: str,
    parent_filename: str,
    file_content: bytes,
    sender: str = "",
    source: str = "batch_split",
    subject: str = "",
) -> dict:
    """Split a multi-page PO PDF and ingest each page through the full pipeline.

    Args:
        db: Motor database instance
        parent_doc_id: ID of the parent (original) document
        parent_filename: Original filename
        file_content: Raw PDF bytes
        sender: Email sender (forwarded to child docs)
        source: Capture source
        subject: Email subject

    Returns:
        dict with split results: {status, children_count, children: [...]}
    """
    from server import _internal_intake_document

    now = datetime.now(timezone.utc).isoformat()

    # Split pages
    pages = split_pdf_pages(file_content)
    if not pages:
        return {"status": "error", "reason": "no_pages_found", "children_count": 0, "children": []}

    # Generate child filenames from parent
    # e.g. "Purchase Orders 61312-61361.pdf" → "Purchase Orders 61312-61361_p1.pdf"
    base_name = parent_filename.rsplit(".", 1)[0] if "." in parent_filename else parent_filename
    ext = parent_filename.rsplit(".", 1)[1] if "." in parent_filename else "pdf"

    children = []
    errors = []

    for page_info in pages:
        page_num = page_info["page_num"]
        child_filename = f"{base_name}_p{page_num}.{ext}"

        try:
            # Remove any existing doc with same hash (allow re-splits)
            await db.hub_documents.delete_many({"sha256_hash": page_info["page_hash"]})

            result = await _internal_intake_document(
                file_content=page_info["pdf_bytes"],
                filename=child_filename,
                content_type="application/pdf",
                source=source,
                sender=sender,
                subject=f"{subject} [Page {page_num}/{len(pages)}]" if subject else f"Split from {parent_filename} [Page {page_num}/{len(pages)}]",
                email_id=f"batch-{parent_doc_id[:8]}-p{page_num}",
                mailbox_category="Sales",
            )

            child_doc_id = (
                result.get("document_id")
                or (result.get("document") or {}).get("id")
                or ""
            )

            # Link child to parent
            if child_doc_id:
                await db.hub_documents.update_one(
                    {"id": child_doc_id},
                    {"$set": {
                        "batch_parent_id": parent_doc_id,
                        "batch_page_num": page_num,
                        "batch_total_pages": len(pages),
                        "batch_source_filename": parent_filename,
                    }},
                )

            child_info = {
                "page_num": page_num,
                "child_doc_id": child_doc_id,
                "filename": child_filename,
                "status": "success",
                "document_type": result.get("document_type") or (result.get("document") or {}).get("document_type") or "",
            }
            children.append(child_info)
            logger.info(
                "[BatchSplit] Page %d/%d → doc %s (%s)",
                page_num, len(pages), child_doc_id[:8] if child_doc_id else "?", child_filename,
            )

        except Exception as e:
            logger.error("[BatchSplit] Error on page %d: %s", page_num, str(e))
            errors.append({"page_num": page_num, "error": str(e)})
            children.append({
                "page_num": page_num,
                "child_doc_id": "",
                "filename": child_filename,
                "status": "error",
                "error": str(e),
            })

    # Update parent doc with split metadata
    await db.hub_documents.update_one(
        {"id": parent_doc_id},
        {"$set": {
            "batch_split": True,
            "batch_split_at": now,
            "batch_children_count": len(children),
            "batch_children_ids": [c["child_doc_id"] for c in children if c.get("child_doc_id")],
            "batch_split_errors": len(errors),
            "updated_utc": now,
        }},
    )

    status = "success" if not errors else ("partial" if children else "error")
    logger.info(
        "[BatchSplit] Complete: parent=%s children=%d errors=%d",
        parent_doc_id[:8], len(children), len(errors),
    )

    return {
        "status": status,
        "parent_doc_id": parent_doc_id,
        "parent_filename": parent_filename,
        "total_pages": len(pages),
        "children_count": len(children),
        "children_success": sum(1 for c in children if c["status"] == "success"),
        "children_errors": len(errors),
        "children": children,
    }
