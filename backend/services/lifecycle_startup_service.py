"""
Canonical application startup initialization services.

The first extracted startup slice owns core MongoDB index creation.
"""

from __future__ import annotations


async def initialize_core_indexes(*, db, logger) -> None:
    """Create the core document-hub database indexes."""
    await db.hub_documents.create_index("id", unique=True)
    await db.hub_documents.create_index("status")
    await db.hub_documents.create_index("document_type")
    await db.hub_documents.create_index("created_utc")
    await db.hub_documents.create_index("source")
    await db.hub_documents.create_index("suggested_job_type")
    await db.hub_documents.create_index([("extracted_fields.vendor", 1)])
    # Phase 7: Indexes for new flat normalized fields
    await db.hub_documents.create_index("vendor_normalized")
    await db.hub_documents.create_index("invoice_number_clean")
    await db.hub_documents.create_index("vendor_canonical")
    await db.hub_documents.create_index("draft_candidate")
    await db.hub_documents.create_index("possible_duplicate")
    # AP Review indexes
    await db.hub_documents.create_index("review_status")
    await db.hub_documents.create_index("bc_posting_status")
    await db.hub_documents.create_index("vendor_id")
    # Legacy indexes (keep for backward compat)
    await db.hub_documents.create_index([("canonical_fields.vendor_normalized", 1)])
    await db.hub_workflow_runs.create_index("id", unique=True)
    await db.hub_workflow_runs.create_index("document_id")
    await db.hub_workflow_runs.create_index("started_utc")
    await db.hub_config.create_index("_key", unique=True)
    await db.hub_job_types.create_index("job_type", unique=True)
    # Vendor aliases indexes (non-unique — bulk seeding creates many without alias_id)
    try:
        await db.vendor_aliases.create_index("alias_id", unique=True, sparse=True)
    except Exception:
        pass
    try:
        await db.vendor_aliases.create_index("alias_string", sparse=True)
    except Exception:
        pass
    await db.vendor_aliases.create_index("normalized_alias")
    await db.vendor_aliases.create_index("vendor_no")
    await db.vendor_aliases.create_index("canonical_vendor_id")
    try:
        await db.vendor_aliases.create_index("vendor_id")
    except Exception:
        pass
    # Full-text search index for multi-field document search
    try:
        await db.hub_documents.create_index(
            [
                ("file_name", "text"),
                ("vendor_canonical", "text"),
                ("vendor_raw", "text"),
                ("invoice_number_clean", "text"),
                ("po_number_clean", "text"),
                ("extracted_fields.vendor", "text"),
                ("extracted_fields.invoice_number", "text"),
                ("extracted_fields.po_number", "text"),
                ("extracted_fields.customer", "text"),
                ("raw_text", "text"),
            ],
            name="hub_documents_fulltext",
            weights={
                "invoice_number_clean": 10,
                "po_number_clean": 10,
                "vendor_canonical": 8,
                "file_name": 6,
                "extracted_fields.vendor": 5,
                "extracted_fields.invoice_number": 5,
                "extracted_fields.po_number": 5,
                "extracted_fields.customer": 4,
                "vendor_raw": 3,
                "raw_text": 1,
            },
            default_language="english",
        )
    except Exception as e:
        logger.warning("Full-text index creation skipped (may already exist with different config): %s", e)

    # Vendor match rejections indexes
    try:
        await db.vendor_match_rejections.create_index(
            [("normalized_raw", 1), ("proposed_vendor_id", 1)],
            unique=True,
        )
        await db.vendor_match_rejections.create_index("last_rejected_at")
        await db.hub_documents.create_index("vendor_resolution.status")
        await db.hub_documents.create_index("vendor_resolution.method")
    except Exception:
        pass
    # Phase C1: Mail intake log indexes
    await db.mail_intake_log.create_index("internet_message_id")
    await db.mail_intake_log.create_index("attachment_hash")
    await db.mail_intake_log.create_index([("internet_message_id", 1), ("attachment_hash", 1)])
    await db.mail_intake_log.create_index("processed_at")
    await db.mail_poll_runs.create_index("started_at")
