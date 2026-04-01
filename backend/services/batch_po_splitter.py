"""
Batch Document Splitter Service

Detects multi-page PDFs and splits them into separate logical documents.
Each child document runs through the full intake pipeline independently.

Supports TWO splitting modes:
  1. **Boundary-aware split** (default): Uses document_boundary_service to detect
     where one document ends and another begins (vendor changes, invoice number
     changes, letterhead transitions). Groups contiguous same-doc pages together.
  2. **Per-page split** (fallback): Splits every page into its own document.

Flow:
  1. Parent PDF received → multi-page detected
  2. Boundary analysis: detect logical document groups
  3. Each group extracted as its own PDF
  4. Each child PDF → _internal_intake_document → classify → extract → validate → auto-post
  5. Parent doc updated with split metadata + links to children
"""

import io
import logging
import uuid
import hashlib
from datetime import datetime, timezone
from typing import Optional

from pypdf import PdfReader, PdfWriter

logger = logging.getLogger(__name__)

# Document types eligible for batch splitting — ALL types that commonly arrive
# as multi-page bundles
SPLITTABLE_TYPES = {
    "Purchase_Order", "PurchaseOrder", "Sales_Order", "SalesOrder",
    "AP_Invoice", "APInvoice", "AP Invoice", "Invoice",
    "BOL", "Bill_of_Lading", "BillOfLading",
    "Packing_Slip", "PackingSlip", "Shipping_Document",
    "Credit_Memo", "CreditMemo",
    "Unknown",  # Unknown multi-page docs should also be split for per-page classification
}

# Minimum pages to trigger auto-split
AUTO_SPLIT_MIN_PAGES = 2


def detect_batch_po(file_content: bytes, document_type: str) -> dict:
    """Check if a PDF is a multi-page document that should be split.

    Returns:
        dict with keys: should_split (bool), page_count (int), reason (str),
                        groups (list), boundaries (list)
    """
    try:
        reader = PdfReader(io.BytesIO(file_content))
        page_count = len(reader.pages)
    except Exception as e:
        logger.warning("[BatchSplit] Failed to read PDF: %s", str(e))
        return {"should_split": False, "page_count": 0, "reason": f"pdf_read_error: {e}"}

    if page_count < AUTO_SPLIT_MIN_PAGES:
        return {"should_split": False, "page_count": page_count, "reason": "single_page"}

    # For known splittable types, always split multi-page docs
    if document_type in SPLITTABLE_TYPES:
        # Use intelligent boundary detection
        from services.document_boundary_service import analyze_document_boundaries
        analysis = analyze_document_boundaries(file_content)

        return {
            "should_split": True,
            "page_count": page_count,
            "document_count": analysis.get("document_count", page_count),
            "groups": analysis.get("groups", []),
            "boundaries": analysis.get("boundaries", []),
            "reason": analysis.get("analysis", f"multi_page ({page_count} pages)"),
            "split_mode": "boundary_aware" if analysis.get("document_count", 0) > 1 else "per_page",
        }

    # For unknown types, still split if multi-page (classify each page independently)
    if page_count >= 3:
        from services.document_boundary_service import analyze_document_boundaries
        analysis = analyze_document_boundaries(file_content)
        if analysis.get("should_split"):
            return {
                "should_split": True,
                "page_count": page_count,
                "document_count": analysis.get("document_count", page_count),
                "groups": analysis.get("groups", []),
                "boundaries": analysis.get("boundaries", []),
                "reason": analysis.get("analysis", f"multi_page_unknown ({page_count} pages)"),
                "split_mode": "boundary_aware",
            }

    return {
        "should_split": False,
        "page_count": page_count,
        "reason": f"not_splittable_type ({document_type})",
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
    on_page_done=None,
    groups: list = None,
) -> dict:
    """Split a multi-page PDF and ingest each logical document through the full pipeline.
    
    Uses boundary-aware grouping when available:
    - If `groups` is provided, splits by logical document groups (pages grouped together)
    - If not, falls back to per-page splitting

    Args:
        db: Motor database instance
        parent_doc_id: ID of the parent (original) document
        parent_filename: Original filename
        file_content: Raw PDF bytes
        sender: Email sender (forwarded to child docs)
        source: Capture source
        subject: Email subject
        on_page_done: Optional async callback(page_num, total, child_info) for progress
        groups: Optional list of page groups from boundary detection

    Returns:
        dict with split results: {status, children_count, children: [...]}
    """
    import asyncio
    from server import _internal_intake_document

    now = datetime.now(timezone.utc).isoformat()
    reader = PdfReader(io.BytesIO(file_content))
    total_pages = len(reader.pages)

    # Determine split strategy
    if groups and len(groups) > 0:
        # Boundary-aware: split by logical document groups
        split_units = []
        for g in groups:
            split_units.append({
                "pages": g["pages"],  # 1-indexed page numbers
                "label": f"doc{g['group_num']}",
                "vendor_hint": g.get("vendor_hint", ""),
                "doc_type_hints": g.get("doc_type_hints", []),
            })
        split_mode = "boundary_aware"
        logger.info("[BatchSplit] Using boundary-aware split: %d groups from %d pages",
                    len(split_units), total_pages)
    else:
        # Fallback: per-page split
        split_units = [{"pages": [i + 1], "label": f"p{i + 1}"} for i in range(total_pages)]
        split_mode = "per_page"
        logger.info("[BatchSplit] Using per-page split: %d pages", total_pages)

    base_name = parent_filename.rsplit(".", 1)[0] if "." in parent_filename else parent_filename
    ext = parent_filename.rsplit(".", 1)[1] if "." in parent_filename else "pdf"

    async def _process_unit(unit, unit_idx):
        pages = unit["pages"]
        label = unit.get("label", f"part{unit_idx + 1}")

        # Build child PDF from selected pages
        writer = PdfWriter()
        for p in sorted(pages):
            if 1 <= p <= total_pages:
                writer.add_page(reader.pages[p - 1])

        buf = io.BytesIO()
        writer.write(buf)
        child_bytes = buf.getvalue()
        child_filename = f"{base_name}_{label}.{ext}"

        try:
            # Delete any previous child with same hash
            child_hash = hashlib.sha256(child_bytes).hexdigest()
            await db.hub_documents.delete_many({"sha256_hash": child_hash})

            page_range = f"{min(pages)}-{max(pages)}" if len(pages) > 1 else str(pages[0])
            child_subject = f"{subject} [Pages {page_range}/{total_pages}]" if subject else f"Split from {parent_filename} [Pages {page_range}/{total_pages}]"

            result = await _internal_intake_document(
                file_content=child_bytes,
                filename=child_filename,
                content_type="application/pdf",
                source=source,
                sender=sender,
                subject=child_subject,
                email_id=f"batch-{parent_doc_id[:8]}-{label}",
                mailbox_category=None,
            )

            child_doc_id = (
                result.get("document_id")
                or (result.get("document") or {}).get("id")
                or ""
            )

            if child_doc_id:
                await db.hub_documents.update_one(
                    {"id": child_doc_id},
                    {"$set": {
                        "batch_parent_id": parent_doc_id,
                        "batch_page_num": pages[0] if len(pages) == 1 else None,
                        "batch_pages": sorted(pages),
                        "batch_total_pages": total_pages,
                        "batch_source_filename": parent_filename,
                        "batch_split_mode": split_mode,
                        "batch_group_num": unit_idx + 1,
                    }},
                )

            child_info = {
                "group_num": unit_idx + 1,
                "pages": sorted(pages),
                "page_count": len(pages),
                "child_doc_id": child_doc_id,
                "filename": child_filename,
                "status": "success",
                "document_type": result.get("document_type") or (result.get("document") or {}).get("document_type") or "",
                "vendor_hint": unit.get("vendor_hint", ""),
            }
            logger.info("[BatchSplit] Group %d (pages %s) → doc %s (%s)",
                        unit_idx + 1, page_range, child_doc_id[:8] if child_doc_id else "?",
                        child_info["document_type"])

            if on_page_done:
                await on_page_done(unit_idx + 1, len(split_units), child_info)

            return child_info

        except Exception as e:
            logger.error("[BatchSplit] Error on group %d (pages %s): %s",
                        unit_idx + 1, pages, str(e))
            err_info = {
                "group_num": unit_idx + 1,
                "pages": sorted(pages),
                "child_doc_id": "",
                "filename": child_filename,
                "status": "error",
                "error": str(e),
            }
            if on_page_done:
                await on_page_done(unit_idx + 1, len(split_units), err_info)
            return err_info

    # Process all units (sequentially to avoid overwhelming the pipeline)
    children = []
    for idx, unit in enumerate(split_units):
        result = await _process_unit(unit, idx)
        children.append(result)

    errors = [c for c in children if c["status"] == "error"]

    # Update parent doc with split metadata
    await db.hub_documents.update_one(
        {"id": parent_doc_id},
        {"$set": {
            "batch_split": True,
            "batch_split_at": now,
            "batch_split_mode": split_mode,
            "batch_children_count": len(children),
            "batch_document_count": len(children),
            "batch_children_ids": [c["child_doc_id"] for c in children if c.get("child_doc_id")],
            "batch_split_errors": len(errors),
            "updated_utc": now,
        }},
    )

    status = "success" if not errors else ("partial" if len(children) > len(errors) else "error")
    logger.info("[BatchSplit] Complete: parent=%s mode=%s children=%d errors=%d",
                parent_doc_id[:8], split_mode, len(children), len(errors))

    return {
        "status": status,
        "parent_doc_id": parent_doc_id,
        "parent_filename": parent_filename,
        "split_mode": split_mode,
        "total_pages": total_pages,
        "children_count": len(children),
        "children_success": sum(1 for c in children if c["status"] == "success"),
        "children_errors": len(errors),
        "children": children,
    }
