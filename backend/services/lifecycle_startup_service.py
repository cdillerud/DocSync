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

async def initialize_pre_scheduler_services(
    *,
    db,
    logger,
    sales_email_polling_enabled: bool,
    sales_email_polling_user: str,
    sales_email_polling_interval_minutes: int,
    load_config_from_db,
    default_job_types,
    vendor_alias_map,
):
    """Initialize services and reference data before workers start."""
    from datetime import datetime, timezone

    from sales_module import (
        configure_sales_email_polling,
        initialize_sales_indexes,
        set_db as set_sales_db,
    )
    from services.file_ingestion_service import (
        set_file_ingestion_db,
    )
    from services.spiro.spiro_sync import set_spiro_db

    # Sales Module (Phase 0): Initialize database and indexes
    set_sales_db(db)
    await initialize_sales_indexes(db)
    # File Ingestion Service: Initialize database
    set_file_ingestion_db(db)
    # Initialize centralized deps module for modular routers
    from deps import set_db as set_deps_db
    set_deps_db(db)
    # Spiro Integration: Initialize database
    set_spiro_db(db)
    # Routing Feedback: Initialize learning layer
    from services.routing_feedback_service import init_feedback_db
    init_feedback_db(db)
    await db.routing_feedback.create_index("routing_key", unique=True)
    await db.routing_feedback.create_index("confidence")
    await db.sender_vendor_map.create_index("sender_email")
    await db.sender_vendor_map.create_index("sender_domain")
    logger.info("Routing feedback + vendor sender learning initialized")
    # Create Spiro indexes
    await db.spiro_contacts.create_index("spiro_id", unique=True)
    await db.spiro_contacts.create_index("email")
    await db.spiro_contacts.create_index("email_domain")
    await db.spiro_contacts.create_index("company_id")
    await db.spiro_companies.create_index("spiro_id", unique=True)
    await db.spiro_companies.create_index("name_normalized")
    await db.spiro_companies.create_index("email_domain")
    await db.spiro_opportunities.create_index("spiro_id", unique=True)
    await db.spiro_opportunities.create_index("company_id")
    await db.spiro_sync_status.create_index("entity_type", unique=True)
    logger.info("Spiro integration initialized")
    # Configure Sales email polling
    configure_sales_email_polling(
        enabled=sales_email_polling_enabled,
        mailbox=sales_email_polling_user,
        interval_minutes=sales_email_polling_interval_minutes
    )
    # Load saved config from MongoDB (overrides .env defaults)
    await load_config_from_db()
    # Initialize default job types if not present
    for jt_key, jt_config in default_job_types.items():
        existing = await db.hub_job_types.find_one({"job_type": jt_key})
        if not existing:
            await db.hub_job_types.insert_one(jt_config)
    # Load vendor aliases into memory
    aliases = await db.vendor_aliases.find({}, {"_id": 0}).to_list(500)
    for alias in aliases:
        alias_str = alias.get("alias_string") or alias.get("alias") or ""
        norm_alias = alias.get("normalized_alias") or alias_str.lower()
        vendor_val = alias.get("vendor_name") or alias.get("vendor_no")
        if alias_str and vendor_val:
            vendor_alias_map[alias_str] = vendor_val
        if norm_alias and vendor_val:
            vendor_alias_map[norm_alias] = vendor_val

    # Seed known manual vendor aliases (OCR variants → BC vendor)
    _MANUAL_ALIASES = [
        {"alias": "MEXUS, INC", "normalized": "mexus", "vendor_name": "Mexus Inc", "vendor_no": "MEXUS"},
        {"alias": "MEXUS, INC.", "normalized": "mexus", "vendor_name": "Mexus Inc", "vendor_no": "MEXUS"},
        {"alias": "MEXUS INC", "normalized": "mexus", "vendor_name": "Mexus Inc", "vendor_no": "MEXUS"},
    ]
    for ma in _MANUAL_ALIASES:
        existing = await db.vendor_aliases.find_one({"normalized_alias": ma["normalized"]})
        if not existing:
            await db.vendor_aliases.insert_one({
                "alias_string": ma["alias"],
                "normalized_alias": ma["normalized"],
                "alias": ma["alias"],
                "normalized": ma["normalized"],
                "canonical_vendor_id": ma["vendor_no"],
                "vendor_no": ma["vendor_no"],
                "vendor_name": ma["vendor_name"],
                "vendor_id": ma["vendor_no"],
                "source": "manual_resolution",
                "confidence": 1.0,
                "usage_count": 0,
                "first_seen": datetime.now(timezone.utc).isoformat(),
                "last_seen": datetime.now(timezone.utc).isoformat(),
                "created_at": datetime.now(timezone.utc).isoformat(),
            })
            vendor_alias_map[ma["alias"]] = ma["vendor_name"]
            vendor_alias_map[ma["normalized"]] = ma["vendor_name"]
            logger.info("Seeded manual vendor alias: %s → %s (%s)", ma["alias"], ma["vendor_name"], ma["vendor_no"])

    # Bootstrap: create normalized aliases for all BC vendor names
    try:
        bc_vendors = await db.hub_bc_vendors.find({}, {"_id": 0, "displayName": 1, "number": 1}).to_list(2000)
        from services.vendor_name_helpers import normalize_vendor_name as _norm_vendor
        bootstrap_count = 0
        for bv in bc_vendors:
            display = bv.get("displayName", "")
            vendor_no = bv.get("number", "")
            if not display or not vendor_no:
                continue
            normalized = _norm_vendor(display)
            if not normalized or len(normalized) < 3:
                continue
            # Only insert if not already present
            existing = await db.vendor_aliases.find_one({"normalized_alias": normalized})
            if not existing:
                await db.vendor_aliases.insert_one({
                    "alias_string": display,
                    "normalized_alias": normalized,
                    "canonical_vendor_id": vendor_no,
                    "vendor_no": vendor_no,
                    "vendor_name": display,
                    "vendor_id": vendor_no,
                    "source": "bc_bootstrap",
                    "confidence": 1.0,
                    "usage_count": 0,
                    "first_seen": datetime.now(timezone.utc).isoformat(),
                    "last_seen": datetime.now(timezone.utc).isoformat(),
                    "created_at": datetime.now(timezone.utc).isoformat(),
                })
                vendor_alias_map[display] = display
                vendor_alias_map[normalized] = display
                bootstrap_count += 1
        if bootstrap_count > 0:
            logger.info("Bootstrapped %d BC vendor aliases into vendor_aliases collection", bootstrap_count)
    except Exception as e:
        logger.warning("BC vendor alias bootstrap failed: %s", e)

    return aliases
