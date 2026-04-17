"""
Inventory XLS Router
─────────────────────

REST endpoints for the inventory XLS inference pipeline.

Flow:
  1. POST /api/inventory-xls/ingest     (multipart) → run classifier+parser, create staging
  2. GET  /api/inventory-xls/staging    → list staging records
  3. GET  /api/inventory-xls/staging/{id}
  4. POST /api/inventory-xls/staging/{id}/update    → fix column map / reassign customer
  5. POST /api/inventory-xls/staging/{id}/approve   → apply to ledger, persist learning
  6. POST /api/inventory-xls/staging/{id}/reject    → audit, keep for review
  7. POST /api/inventory-xls/ingest-pilot-doc/{doc_id} → re-classify an already-ingested hub_document
  8. GET  /api/inventory-xls/learning-summary       → learned-mapping stats
"""

import hashlib
import logging
from typing import Optional

from fastapi import APIRouter, Body, File, Form, HTTPException, Query, UploadFile

from deps import get_db
from services.file_ingestion_service import FileIngestionService
from services.inventory_xls_classifier import classify_xls
from services.inventory_xls_parser import (
    build_column_map, extract_effective_date_from_filename, normalize_rows,
)
from services.inventory_xls_staging_service import (
    approve_staging, get_learning_summary, get_staging, list_staging,
    reject_staging, stage_import, suggest_customer_workspace, update_staging,
)

logger = logging.getLogger(__name__)
router = APIRouter(prefix="/inventory-xls", tags=["Inventory XLS"])

_ingestor = FileIngestionService()


@router.post("/ingest")
async def ingest_xls(
    file: UploadFile = File(...),
    sender_email: Optional[str] = Form(None),
    sheet_name: Optional[str] = Form(None),
    force_llm: bool = Form(False),
):
    """Classify + parse + stage a new XLS upload.

    Returns the staging record (status=pending_review) OR
    {already_staged: true} if this exact file + customer has been staged before.
    """
    db = get_db()
    raw = await file.read()
    if not raw:
        raise HTTPException(status_code=422, detail="Empty file")
    ext = (file.filename or "").lower().rsplit(".", 1)[-1]
    if ext not in ("xlsx", "xls", "csv"):
        raise HTTPException(status_code=415, detail=f"Unsupported file type: {ext}")

    file_hash = hashlib.sha256(raw).hexdigest()

    # Parse headers + rows via existing ingestion service
    if ext == "csv":
        headers, rows = _ingestor.parse_csv(raw, file.filename or "upload.csv")
    else:
        headers, rows = _ingestor.parse_excel(raw, file.filename or "upload.xlsx", sheet_name=sheet_name)
    if not headers:
        raise HTTPException(status_code=422, detail="No header row detected")

    # Classify
    cls = classify_xls(file.filename or "", headers=headers, sender_email=sender_email)
    if cls.classification == "not_inventory":
        return {
            "staged": False,
            "reason": "File did not match any inventory pattern",
            "classification": cls.__dict__,
        }

    # Build column map
    sender_domain = sender_email.split("@", 1)[1].lower() if sender_email and "@" in sender_email else None
    cm = await build_column_map(
        db, headers=headers, sample_rows=rows[:3],
        classification=cls.classification, sender_domain=sender_domain,
        filename=file.filename or "", force_llm=force_llm,
    )
    if cm.missing_required:
        logger.warning(
            "[InventoryXLS] file=%s missing_required=%s — staging for human mapping",
            file.filename, cm.missing_required,
        )

    # Extract effective date from filename
    eff_date = extract_effective_date_from_filename(file.filename or "")

    # Normalize rows (may yield zero if mapping is incomplete — still stage so user can fix)
    norm = normalize_rows(
        rows=rows, column_map=cm, classification=cls.classification,
        filename_effective_date=eff_date,
    )

    # Suggest customer workspace
    suggested = await suggest_customer_workspace(db, sender_email, file.filename or "")

    # Stage
    result = await stage_import(
        db,
        filename=file.filename or "upload.xlsx",
        file_hash=file_hash,
        sender_email=sender_email,
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
    )
    return {
        "staged": not result.get("already_staged", False),
        "already_staged": result.get("already_staged", False),
        **result,
        "stats": norm["stats"],
        "suggested_customer": suggested,
    }


@router.post("/ingest-pilot-doc/{doc_id}")
async def ingest_from_pilot_doc(doc_id: str, force_llm: bool = Query(False)):
    """Run the XLS pipeline on a document already stored in hub_documents.

    Use this to retroactively classify XLS attachments that arrived through the
    main mailbox ingestion before this pipeline existed.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise HTTPException(status_code=404, detail="Document not found")
    fname = doc.get("file_name") or ""
    ext = fname.lower().rsplit(".", 1)[-1]
    if ext not in ("xlsx", "xls", "csv"):
        raise HTTPException(status_code=415, detail=f"Document is not an XLS/CSV: {fname}")

    import base64
    b64 = doc.get("file_content_b64")
    if not b64:
        raise HTTPException(status_code=410, detail="Document file bytes not available (no file_content_b64 backup)")
    try:
        raw = base64.b64decode(b64)
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Failed to decode stored bytes: {e}")

    file_hash = hashlib.sha256(raw).hexdigest()
    if ext == "csv":
        headers, rows = _ingestor.parse_csv(raw, fname)
    else:
        headers, rows = _ingestor.parse_excel(raw, fname)
    if not headers:
        raise HTTPException(status_code=422, detail="No header row in document")

    sender = doc.get("email_sender")
    cls = classify_xls(fname, headers=headers, sender_email=sender)
    if cls.classification == "not_inventory":
        return {"staged": False, "reason": "not_inventory", "classification": cls.__dict__}

    sender_domain = sender.split("@", 1)[1].lower() if sender and "@" in sender else None
    cm = await build_column_map(
        db, headers=headers, sample_rows=rows[:3],
        classification=cls.classification, sender_domain=sender_domain,
        filename=fname, force_llm=force_llm,
    )
    eff_date = extract_effective_date_from_filename(fname)
    norm = normalize_rows(rows=rows, column_map=cm, classification=cls.classification, filename_effective_date=eff_date)
    suggested = await suggest_customer_workspace(db, sender, fname)

    return await stage_import(
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


@router.get("/staging")
async def api_list_staging(
    status: Optional[str] = Query(None),
    customer_id: Optional[str] = Query(None),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    db = get_db()
    return await list_staging(db, status=status, customer_id=customer_id, limit=limit, skip=skip)


@router.get("/staging/{staging_id}")
async def api_get_staging(staging_id: str):
    db = get_db()
    doc = await get_staging(db, staging_id)
    if not doc:
        raise HTTPException(status_code=404, detail="Not found")
    return doc


@router.post("/staging/{staging_id}/update")
async def api_update_staging(staging_id: str, body: dict = Body(default={})):
    db = get_db()
    return await update_staging(db, staging_id, body or {})


@router.post("/staging/{staging_id}/approve")
async def api_approve_staging(staging_id: str, approved_by: str = Query("user")):
    db = get_db()
    try:
        return await approve_staging(db, staging_id, approved_by=approved_by)
    except ValueError as e:
        raise HTTPException(status_code=422, detail=str(e))


@router.post("/staging/{staging_id}/reject")
async def api_reject_staging(
    staging_id: str,
    rejected_by: str = Query("user"),
    reason: str = Query(""),
):
    db = get_db()
    try:
        return await reject_staging(db, staging_id, rejected_by=rejected_by, reason=reason)
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.get("/learning-summary")
async def api_learning_summary():
    db = get_db()
    return await get_learning_summary(db)


# ── Bulk backfill of existing pilot XLS docs ──────────

@router.post("/backfill-pilot-docs")
async def backfill_pilot_docs(
    limit: int = Query(200, ge=1, le=1000),
    dry_run: bool = Query(False, description="If true, report classifications without staging"),
    force_llm: bool = Query(False),
):
    """
    Scan hub_documents for pilot-ingested .xlsx/.xls/.csv files that were
    classified as SALES_INVOICE / Report by the main pipeline, run them
    through the inventory XLS classifier, and stage any that look like
    inventory docs.

    Read-only if dry_run=true. Otherwise creates staging rows but NEVER
    writes to the ledger (staging approval is still required).
    """
    import base64 as _b64
    db = get_db()
    q = {
        "inside_sales_pilot": True,
        "file_name": {"$regex": r"\.(xlsx|xls|csv)$", "$options": "i"},
    }
    docs = await db.hub_documents.find(
        q,
        {"_id": 0, "id": 1, "file_name": 1, "email_sender": 1,
         "file_content_b64": 1, "inventory_xls_backfilled": 1},
    ).limit(limit).to_list(limit)

    results = {
        "scanned": len(docs),
        "classified_inventory": 0,
        "already_staged": 0,
        "staged": 0,
        "skipped_not_inventory": 0,
        "errors": 0,
        "skipped_no_bytes": 0,
        "by_classification": {},
        "items": [],
    }

    for doc in docs:
        fname = doc.get("file_name") or ""
        b64 = doc.get("file_content_b64")
        entry = {"doc_id": doc["id"][:12], "file": fname[:60]}

        if doc.get("inventory_xls_backfilled") and not dry_run:
            # Already processed in a prior backfill run
            results["already_staged"] += 1
            entry["status"] = "already_processed"
            results["items"].append(entry)
            continue

        if not b64:
            results["skipped_no_bytes"] += 1
            entry["status"] = "no_bytes"
            results["items"].append(entry)
            continue

        try:
            raw = _b64.b64decode(b64)
            ext = fname.lower().rsplit(".", 1)[-1]
            if ext == "csv":
                headers, rows = _ingestor.parse_csv(raw, fname)
            else:
                headers, rows = _ingestor.parse_excel(raw, fname)
            if not headers:
                entry["status"] = "no_headers"
                results["errors"] += 1
                results["items"].append(entry)
                continue

            sender = doc.get("email_sender")
            cls = classify_xls(fname, headers=headers, sender_email=sender)
            entry["classification"] = cls.classification
            entry["confidence"] = cls.confidence
            results["by_classification"][cls.classification] = \
                results["by_classification"].get(cls.classification, 0) + 1

            if cls.classification == "not_inventory":
                results["skipped_not_inventory"] += 1
                entry["status"] = "not_inventory"
                results["items"].append(entry)
                # Mark the doc so it's not re-scanned on next backfill
                if not dry_run:
                    await db.hub_documents.update_one(
                        {"id": doc["id"]},
                        {"$set": {
                            "inventory_xls_backfilled": True,
                            "inventory_xls_classification": "not_inventory",
                        }},
                    )
                continue

            results["classified_inventory"] += 1

            if dry_run:
                entry["status"] = "would_stage"
                results["items"].append(entry)
                continue

            # Build + stage
            sender_domain = None
            if sender and "@" in sender:
                sender_domain = sender.split("@", 1)[1].lower()

            cm = await build_column_map(
                db, headers=headers, sample_rows=rows[:3],
                classification=cls.classification, sender_domain=sender_domain,
                filename=fname, force_llm=force_llm,
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
                source_doc_id=doc["id"],
            )

            if stage_res.get("already_staged"):
                results["already_staged"] += 1
                entry["status"] = "already_staged"
                entry["staging_id"] = stage_res.get("staging_id", "")[:12]
            else:
                results["staged"] += 1
                entry["status"] = "staged"
                entry["staging_id"] = (stage_res.get("staging") or {}).get("id", "")[:12]
                entry["rows"] = (stage_res.get("staging") or {}).get("row_count", 0)

            # Mark source doc
            await db.hub_documents.update_one(
                {"id": doc["id"]},
                {"$set": {
                    "inventory_xls_backfilled": True,
                    "inventory_xls_classification": cls.classification,
                    "inventory_xls_staging_id": entry.get("staging_id"),
                }},
            )
        except Exception as e:
            logger.warning("[XLSBackfill] %s failed: %s", fname[:40], e)
            results["errors"] += 1
            entry["status"] = "error"
            entry["error"] = str(e)[:200]

        results["items"].append(entry)

    return results
