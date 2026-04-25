"""
GPI Document Hub — document-capture rule: pilot enrichment cluster.

Phase 3 Step 4d.8 carve-out home for ``run_pilot_enrichment`` and its
internal helper ``_maybe_stage_inventory_xls``. Moved verbatim from
server.py:2050 / server.py:2082. The original `server` sites are
retained as compatibility shims during the carve-out window.

Public surface: ``run_pilot_enrichment`` (one function).
Internal helper: ``_maybe_stage_inventory_xls`` (private to this module).
"""
import logging

from deps import get_db

logger = logging.getLogger(__name__)


async def run_pilot_enrichment(pid: str):
    """Fire-and-forget: run BC validation, Spiro match, SO rules, readiness review on a pilot doc."""
    try:
        logger.info("[Pilot Enrichment] Starting auto-enrichment for %s", pid[:8])

        # Unified validation runs bc_prod + readiness + pilot_readiness in order
        from services.unified_validation_service import validate_document
        await validate_document(pid, policy_hint="pilot_sales")

        # Spiro CRM match + SO Rules Engine are not part of validation —
        # they are sales-specific enrichments, called here directly.
        from services.spiro_service import match_document_to_spiro
        await match_document_to_spiro(pid)

        from services.so_rules_engine import evaluate_sales_order
        await evaluate_sales_order(pid)

        # Inventory XLS side-channel: if this pilot doc is an XLS/CSV that
        # looks like an inventory snapshot/forecast/open-orders, auto-stage
        # it into the inventory pipeline. This NEVER writes to the ledger —
        # staging approval is still required (unless the learned-mapping
        # auto-approve threshold is hit).
        try:
            await _maybe_stage_inventory_xls(pid)
        except Exception as xls_err:
            logger.debug("[Pilot Enrichment] Inventory XLS side-channel skipped for %s: %s", pid[:8], xls_err)

        logger.info("[Pilot Enrichment] Completed auto-enrichment for %s", pid[:8])
    except Exception as e:
        logger.warning("[Pilot Enrichment] Error enriching %s: %s", pid[:8], e)

async def _maybe_stage_inventory_xls(doc_id: str) -> None:
    """Route a pilot-ingested XLS/CSV through the Inventory XLS classifier if it matches.

    No-op unless:
      - file is .xlsx / .xls / .csv
      - file hasn't been backfilled before
      - classifier confidently recognizes it as inventory
    """
    import base64 as _b64
    db = get_db()
    doc = await db.hub_documents.find_one(
        {"id": doc_id},
        {"_id": 0, "id": 1, "file_name": 1, "email_sender": 1,
         "file_content_b64": 1, "inventory_xls_backfilled": 1},
    )
    if not doc:
        return
    fname = doc.get("file_name") or ""
    ext = fname.lower().rsplit(".", 1)[-1]
    if ext not in ("xlsx", "xls", "csv"):
        return
    if doc.get("inventory_xls_backfilled"):
        return
    b64 = doc.get("file_content_b64")
    if not b64:
        return

    from services.file_ingestion_service import FileIngestionService
    from services.inventory_xls_classifier import classify_xls
    from services.inventory_xls_parser import (
        build_column_map, extract_effective_date_from_filename, normalize_rows,
    )
    from workflows.inventory.planning.staging import (
        stage_import, suggest_customer_workspace,
    )

    raw = _b64.b64decode(b64)
    ingestor = FileIngestionService()
    if ext == "csv":
        headers, rows = ingestor.parse_csv(raw, fname)
    else:
        headers, rows = ingestor.parse_excel(raw, fname)
    if not headers:
        return

    sender = doc.get("email_sender")
    cls = classify_xls(fname, headers=headers, sender_email=sender)
    if cls.classification == "not_inventory":
        return

    sender_domain = sender.split("@", 1)[1].lower() if sender and "@" in sender else None
    cm = await build_column_map(
        db, headers=headers, sample_rows=rows[:3],
        classification=cls.classification, sender_domain=sender_domain, filename=fname,
    )
    eff_date = extract_effective_date_from_filename(fname)
    norm = normalize_rows(
        rows=rows, column_map=cm, classification=cls.classification,
        filename_effective_date=eff_date,
    )
    import hashlib as _h
    file_hash = _h.sha256(raw).hexdigest()
    suggested = await suggest_customer_workspace(db, sender, fname)

    stage_res = await stage_import(
        db,
        filename=fname,
        file_hash=file_hash,
        sender_email=sender,
        classification={
            "classification": cls.classification,
            "confidence": cls.confidence,
            "movement_intent": cls.movement_intent,
            "ownership_hint": cls.ownership_hint,
            "signals": cls.signals,
            "suggested_customer_hint": cls.suggested_customer_hint,
        },
        column_map=cm.to_dict(),
        normalized_rows=norm["rows"],
        row_errors=norm["row_errors"],
        headers=headers,
        suggested_customer_id=(suggested or {}).get("id"),
        filename_effective_date=eff_date,
        source_doc_id=doc_id,
    )
    staging_id = (stage_res.get("staging") or {}).get("id")
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "inventory_xls_backfilled": True,
            "inventory_xls_classification": cls.classification,
            "inventory_xls_staging_id": staging_id,
            "inventory_xls_auto_applied": bool(stage_res.get("auto_applied")),
        }},
    )
    logger.info(
        "[Pilot Enrichment] Inventory XLS side-channel: %s classified=%s staging=%s auto_applied=%s",
        fname[:40], cls.classification, (staging_id or "")[:8], stage_res.get("auto_applied"),
    )
