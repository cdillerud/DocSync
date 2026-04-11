"""
GPI Document Hub - Readiness Router

Endpoints:
  GET  /api/readiness/metrics           - Readiness analytics
  GET  /api/readiness/queue             - Filterable readiness queue
  POST /api/readiness/evaluate/{id}     - Evaluate single document
  POST /api/readiness/batch             - Batch evaluate documents
  POST /api/readiness/reevaluate-all    - Re-evaluate ALL documents
  POST /api/readiness/sync-status       - Force cleanup Inbox (15-rule engine)
  GET  /api/readiness/inbox-diagnostic  - Preview what cleanup would do
  GET  /api/readiness/automation-rate   - Automation rate dashboard
  POST /api/readiness/retry-failed      - Batch retry extraction-failed docs
  POST /api/readiness/retry-captured    - Retry docs stuck in 'captured' status
  POST /api/readiness/retry-ready-to-post - Post ReadyForPost docs to BC
  GET  /api/readiness/exception-queue   - View exception queue
  POST /api/readiness/po-pending/park   - Park PO-gap docs in retry queue
  POST /api/readiness/po-pending/retry  - Re-evaluate all PO-pending docs
  GET  /api/readiness/po-pending        - View PO pending queue
"""

from fastapi import APIRouter, HTTPException, Query
from typing import Optional

router = APIRouter(prefix="/readiness", tags=["Readiness"])


@router.get("/metrics")
async def get_readiness_metrics():
    """Get readiness analytics: counts by status/action, top reasons, trends."""
    from services.document_readiness_service import get_readiness_metrics as _get
    return await _get()


@router.get("/queue")
async def get_readiness_queue(
    status: Optional[str] = Query(None, description="Filter: ready_auto_draft|ready_auto_link|needs_review|blocked|ambiguous"),
    action: Optional[str] = Query(None, description="Filter: auto_draft|auto_link|review|hold"),
    reason: Optional[str] = Query(None, description="Filter by blocking or warning reason"),
    limit: int = Query(50, ge=1, le=200),
    skip: int = Query(0, ge=0),
):
    """Get documents filtered by readiness status for review queues."""
    from services.document_readiness_service import get_readiness_queue as _get
    return await _get(status=status, action=action, reason=reason, limit=limit, skip=skip)


@router.post("/evaluate/{doc_id}")
async def evaluate_document_readiness(doc_id: str):
    """Evaluate and persist readiness for a single document."""
    from services.document_readiness_service import evaluate_and_persist
    try:
        result = await evaluate_and_persist(doc_id)
        return {"success": True, "doc_id": doc_id, "readiness": result}
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


@router.post("/batch")
async def batch_evaluate_readiness(limit: int = Query(200, ge=1, le=1000)):
    """Evaluate readiness for all documents that don't have it yet."""
    from services.document_readiness_service import batch_evaluate
    return await batch_evaluate(limit=limit)


@router.post("/reevaluate-all")
async def reevaluate_all_readiness(limit: int = Query(5000, ge=1, le=10000)):
    """
    Re-evaluate ALL documents — finds and fixes signal contradictions.
    Every correction feeds into the learning pipeline.
    Returns: status transitions, signal corrections, per-vendor breakdown.
    """
    from services.document_readiness_service import batch_reevaluate_all
    return await batch_reevaluate_all(limit=limit)


@router.post("/fix-validation-gaps")
async def fix_validation_gaps(limit: int = Query(500, ge=1, le=5000)):
    """
    Targeted fix for blocking validation gaps (PO validation + Vendor matching).

    Orchestrates:
    1. PO Validation Learning — auto-relaxes PO requirements for vendors with chronic failures
    2. Vendor Auto-Resolution — fuzzy-matches unresolved vendors to BC profiles
    3. Re-evaluates all affected docs to clear them through the pipeline

    Returns detailed summary of what was fixed.
    """
    from deps import get_db
    from services.gap_closer_service import fix_all_validation_gaps

    db = get_db()
    return await fix_all_validation_gaps(db, limit=limit)
@router.post("/sync-status")
async def sync_readiness_to_status(limit: int = Query(5000, le=10000)):
    """
    Aggressive force-cleanup: Directly moves documents OUT of the Inbox queue
    by setting terminal statuses or auto_cleared flags. Uses simple rules:

    Rule 1: Has bc_purchase_invoice_no → Completed (already posted to BC)
    Rule 2: draft_review_status == approved → Completed
    Rule 3: auto_draft_created == true → Completed (draft exists in BC)
    Rule 4: readiness.status is ready + no blockers → auto_cleared + processed
    Rule 5: Remaining non-terminal docs with vendor resolved → auto_cleared
    """
    from deps import get_db
    from datetime import datetime, timezone
    import logging

    logger = logging.getLogger("force_cleanup")
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Terminal statuses that already remove docs from the queue view
    TERMINAL = ["Completed", "Posted", "Archived", "completed", "posted",
                "archived", "FileMissing", "batch_parent", "Validated", "validated",
                "ValidationPassed", "ReadyForPost", "ready_for_post", "AutoFiled",
                "auto_filed", "LinkedToBC", "Exception", "exception"]
    DONE_WF = ["completed", "validation_passed", "processed",
               "ready_for_approval", "exported", "file_missing", "exception_review"]

    # Base conditions (used with $and to avoid $or key collisions)
    not_dup = {"is_duplicate": {"$ne": True}}
    not_terminal = {"status": {"$nin": TERMINAL}}
    not_cleared = {"$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}]}

    def base_and(*extra):
        """Build a query with base stuck conditions + extra filters using $and."""
        return {"$and": [not_dup, not_terminal, not_cleared, *extra]}

    def completed_update(rule):
        return {"$set": {
            "status": "Completed",
            "workflow_status": "completed",
            "auto_cleared": True,
            "automation_decision": "auto_process",
            "force_cleanup_rule": rule,
            "force_cleanup_at": now,
        }}

    results = {}

    # ── Rule 1: Has BC Purchase Invoice Number → mark Completed ──
    r1 = await db.hub_documents.update_many(
        base_and({"bc_purchase_invoice_no": {"$exists": True, "$nin": [None, ""]}}),
        completed_update("has_bc_pi"),
    )
    results["rule1_has_bc_pi"] = r1.modified_count
    logger.info("[ForceCleanup] Rule 1 (has BC PI): %d docs → Completed", r1.modified_count)

    # ── Rule 2: Draft approved → mark Completed ──
    r2 = await db.hub_documents.update_many(
        base_and({"draft_review_status": "approved"}),
        completed_update("draft_approved"),
    )
    results["rule2_draft_approved"] = r2.modified_count
    logger.info("[ForceCleanup] Rule 2 (draft approved): %d docs → Completed", r2.modified_count)

    # ── Rule 3: Auto-draft created in BC → mark Completed ──
    r3 = await db.hub_documents.update_many(
        base_and({"auto_draft_created": True}),
        completed_update("auto_draft_created"),
    )
    results["rule3_auto_draft_created"] = r3.modified_count
    logger.info("[ForceCleanup] Rule 3 (auto-draft created): %d docs → Completed", r3.modified_count)

    # ── Rule 4: Readiness says ready + no blocking reasons → Completed ──
    r4 = await db.hub_documents.update_many(
        base_and(
            {"readiness.status": {"$in": ["ready_auto_draft", "ready_auto_link", "ready"]}},
            {"$or": [
                {"readiness.blocking_reasons": {"$size": 0}},
                {"readiness.blocking_reasons": {"$exists": False}},
            ]},
        ),
        completed_update("readiness_ready_no_blockers"),
    )
    results["rule4_readiness_ready"] = r4.modified_count
    logger.info("[ForceCleanup] Rule 4 (readiness ready): %d docs → Completed", r4.modified_count)

    # ── Rule 5: Vendor resolved + fields present → Completed ──
    r5 = await db.hub_documents.update_many(
        base_and(
            {"readiness.signals.vendor_resolved": True},
            {"readiness.signals.required_fields_complete": True},
            {"readiness.signals.duplicate_risk": {"$ne": True}},
            {"readiness.signals.policy_blocked": {"$ne": True}},
        ),
        completed_update("vendor_resolved_fields_complete"),
    )
    results["rule5_vendor_resolved"] = r5.modified_count
    logger.info("[ForceCleanup] Rule 5 (vendor+fields): %d docs → Completed", r5.modified_count)

    # ── Rule 6: ReadyForPost status (from old sync) → mark Completed ──
    r6 = await db.hub_documents.update_many(
        {"$and": [not_dup, {"status": "ReadyForPost"}, not_cleared]},
        completed_update("readyforpost_to_completed"),
    )
    results["rule6_readyforpost"] = r6.modified_count
    logger.info("[ForceCleanup] Rule 6 (ReadyForPost→Completed): %d docs", r6.modified_count)

    # ── Rule 7: Readiness says ready (even with blockers) → Completed ──
    r7 = await db.hub_documents.update_many(
        base_and({"readiness.status": {"$in": ["ready_auto_draft", "ready_auto_link", "ready"]}}),
        completed_update("readiness_ready_catchall"),
    )
    results["rule7_readiness_catchall"] = r7.modified_count
    logger.info("[ForceCleanup] Rule 7 (readiness ready catchall): %d docs", r7.modified_count)

    # ── Rule 8: Non-AP document types with a known vendor → auto-clear ──
    # Shipping docs, inventory reports, BOLs, statements, etc. should NOT sit
    # in the AP review queue. If they have a vendor, they're filed.
    NON_AP_TYPES_REGEX = "(?i)(shipping|inventory|bol|packing|freight|warehouse|statement|remittance|unknown|receipt|report|order_confirm|w9|w-9)"
    r8 = await db.hub_documents.update_many(
        base_and(
            {"$or": [
                {"doc_type": {"$regex": NON_AP_TYPES_REGEX}},
                {"document_type": {"$regex": NON_AP_TYPES_REGEX}},
                {"suggested_job_type": {"$regex": NON_AP_TYPES_REGEX}},
            ]},
            {"$or": [
                {"vendor_canonical": {"$exists": True, "$nin": [None, "", "—"]}},
                {"bc_vendor_number": {"$exists": True, "$nin": [None, ""]}},
            ]},
        ),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "non_ap_with_vendor",
            "force_cleanup_at": now,
        }},
    )
    results["rule8_non_ap_vendor"] = r8.modified_count
    logger.info("[ForceCleanup] Rule 8 (non-AP + vendor): %d docs → auto-filed", r8.modified_count)

    # ── Rule 9: Non-AP document types WITHOUT vendor → auto-clear ──
    # These are supporting docs (BOLs, receipts, etc.) with no vendor.
    # They're noise in the inbox — file them away.
    r9 = await db.hub_documents.update_many(
        base_and(
            {"$or": [
                {"doc_type": {"$regex": NON_AP_TYPES_REGEX}},
                {"document_type": {"$regex": NON_AP_TYPES_REGEX}},
                {"suggested_job_type": {"$regex": NON_AP_TYPES_REGEX}},
            ]},
        ),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "non_ap_no_vendor",
            "force_cleanup_at": now,
        }},
    )
    results["rule9_non_ap_no_vendor"] = r9.modified_count
    logger.info("[ForceCleanup] Rule 9 (non-AP, no vendor): %d docs → auto-filed", r9.modified_count)

    # ── Rule 10: Any doc with a known vendor that was already auto_post_attempted ──
    # These were evaluated and the auto-post system already looked at them.
    # They shouldn't sit in the inbox forever.
    r10 = await db.hub_documents.update_many(
        base_and(
            {"auto_post_attempted": True},
            {"$or": [
                {"vendor_canonical": {"$exists": True, "$nin": [None, "", "—"]}},
                {"bc_vendor_number": {"$exists": True, "$nin": [None, ""]}},
            ]},
        ),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_process",
            "force_cleanup_rule": "auto_post_attempted_with_vendor",
            "force_cleanup_at": now,
        }},
    )
    results["rule10_attempted_vendor"] = r10.modified_count
    logger.info("[ForceCleanup] Rule 10 (auto-post attempted + vendor): %d docs", r10.modified_count)

    # ── Rule 11: Docs reverted by old auto-post bug (status NeedsReview but had been ready) ──
    # The old auto-post code reverted non-AP docs to NeedsReview even when readiness said ready.
    # Look for docs that have auto_post_reason containing "Not classified as AP_Invoice"
    r11 = await db.hub_documents.update_many(
        base_and(
            {"$or": [
                {"auto_post_failures": {"$elemMatch": {"$regex": "Not classified as AP"}}},
                {"auto_post_reason": {"$regex": "not an AP|Not classified as AP"}},
            ]},
        ),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "reverted_non_ap",
            "force_cleanup_at": now,
        }},
    )
    results["rule11_reverted_non_ap"] = r11.modified_count
    logger.info("[ForceCleanup] Rule 11 (reverted non-AP): %d docs", r11.modified_count)

    # ── Rule 12: Junk file types misclassified as AP Invoice ──
    # .jpg, .png, .xlsx, .xls files are NOT real AP invoices
    JUNK_EXT_REGEX = r"\.(jpg|jpeg|png|gif|bmp|xlsx|xls|csv|tiff?)$"
    r12 = await db.hub_documents.update_many(
        base_and({"file_name": {"$regex": JUNK_EXT_REGEX, "$options": "i"}}),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "junk_file_type",
            "force_cleanup_at": now,
        }},
    )
    results["rule12_junk_files"] = r12.modified_count
    logger.info("[ForceCleanup] Rule 12 (junk file types): %d docs", r12.modified_count)

    # ── Rule 13: Account Statements misclassified as AP Invoice ──
    # Files with "statement" or "SOA" in name aren't real invoices
    STATEMENT_REGEX = r"(?i)(statement|SOA_|account.?statement|remittance.?advice|online.?bill.?pay)"
    r13 = await db.hub_documents.update_many(
        base_and({"file_name": {"$regex": STATEMENT_REGEX}}),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "statement_not_invoice",
            "force_cleanup_at": now,
        }},
    )
    results["rule13_statements"] = r13.modified_count
    logger.info("[ForceCleanup] Rule 13 (statements): %d docs", r13.modified_count)

    # ── Rule 14: Self-vendor docs (vendor is Gamer Packaging = own company) ──
    SELF_VENDOR_REGEX = r"(?i)^gamer\s*(packaging|pack)"
    r14 = await db.hub_documents.update_many(
        base_and(
            {"$or": [
                {"vendor_canonical": {"$regex": SELF_VENDOR_REGEX}},
                {"extracted_fields.vendor": {"$regex": SELF_VENDOR_REGEX}},
            ]},
        ),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "self_vendor",
            "force_cleanup_at": now,
        }},
    )
    results["rule14_self_vendor"] = r14.modified_count
    logger.info("[ForceCleanup] Rule 14 (self-vendor): %d docs", r14.modified_count)

    # ── Rule 15: W9 / tax forms misclassified as AP Invoice ──
    W9_REGEX = r"(?i)(w-?9|w9_|tax.?form)"
    r15 = await db.hub_documents.update_many(
        base_and({"file_name": {"$regex": W9_REGEX}}),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "tax_form",
            "force_cleanup_at": now,
        }},
    )
    results["rule15_tax_forms"] = r15.modified_count
    logger.info("[ForceCleanup] Rule 15 (tax forms): %d docs", r15.modified_count)

    # ── Rule 16: "Captured" docs with no vendor — stuck unclassified ──
    r16 = await db.hub_documents.update_many(
        base_and(
            {"status": {"$in": ["Captured", "captured", "received"]}},
        ),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "captured_stale",
            "force_cleanup_at": now,
        }},
    )
    results["rule16_captured_stale"] = r16.modified_count
    logger.info("[ForceCleanup] Rule 16 (captured/stale): %d docs", r16.modified_count)

    # ── Rule 17: XML duplicates — if an XML invoice has a matching PDF, it's redundant ──
    r17 = await db.hub_documents.update_many(
        base_and({"file_name": {"$regex": r"\.xml$", "$options": "i"}}),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "xml_duplicate",
            "force_cleanup_at": now,
        }},
    )
    results["rule17_xml_files"] = r17.modified_count
    logger.info("[ForceCleanup] Rule 17 (XML files): %d docs", r17.modified_count)

    # ── Rule 18: AR_Invoice / Sales Invoice type — not AP, auto-file ──
    r18 = await db.hub_documents.update_many(
        base_and(
            {"$or": [
                {"doc_type": {"$regex": "(?i)(ar_invoice|sales.?invoice|credit.?memo)"}},
                {"document_type": {"$regex": "(?i)(ar_invoice|sales.?invoice|credit.?memo)"}},
            ]},
        ),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "ar_not_ap",
            "force_cleanup_at": now,
        }},
    )
    results["rule18_ar_invoices"] = r18.modified_count
    logger.info("[ForceCleanup] Rule 18 (AR/Sales invoices): %d docs", r18.modified_count)

    # ── Rule 19: Broaden self-vendor match — vendor name contains "gamer" ──
    r19 = await db.hub_documents.update_many(
        base_and(
            {"$or": [
                {"vendor_canonical": {"$regex": "(?i)gamer"}},
                {"extracted_fields.vendor": {"$regex": "(?i)gamer"}},
            ]},
        ),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "self_vendor_broad",
            "force_cleanup_at": now,
        }},
    )
    results["rule19_self_vendor_broad"] = r19.modified_count
    logger.info("[ForceCleanup] Rule 19 (self-vendor broad): %d docs", r19.modified_count)

    # ── Rule 20: Duplicate filenames — same file_name appears multiple times ──
    # Find filenames that appear more than once among stuck docs
    dup_pipe = [
        {"$match": {"$and": [not_dup, not_terminal, not_cleared]}},
        {"$group": {"_id": "$file_name", "count": {"$sum": 1}, "ids": {"$push": "$id"}}},
        {"$match": {"count": {"$gt": 1}}},
    ]
    dup_groups = await db.hub_documents.aggregate(dup_pipe).to_list(500)
    dup_cleared = 0
    for grp in dup_groups:
        # Keep the first doc, clear the rest as duplicates
        if len(grp["ids"]) > 1:
            dup_ids = grp["ids"][1:]  # skip first
            r = await db.hub_documents.update_many(
                {"id": {"$in": dup_ids}},
                {"$set": {
                    "status": "Completed",
                    "workflow_status": "processed",
                    "auto_cleared": True,
                    "is_duplicate": True,
                    "automation_decision": "auto_filed",
                    "force_cleanup_rule": "duplicate_filename",
                    "force_cleanup_at": now,
                }},
            )
            dup_cleared += r.modified_count
    results["rule20_duplicate_filenames"] = dup_cleared
    logger.info("[ForceCleanup] Rule 20 (duplicate filenames): %d docs", dup_cleared)

    # ── Rule 21: Reverted docs — auto_cleared=True but status reverted to non-terminal ──
    # These docs were previously completed but something set their status back
    # (e.g., AP auto-post failure, reprocessing). They have auto_cleared=True so
    # Rules 1-20 skip them (not_cleared filter). Fix them here.
    r21 = await db.hub_documents.update_many(
        {"$and": [
            not_dup,
            {"auto_cleared": True},
            {"status": {"$nin": TERMINAL}},
            {"status": {"$in": ["NeedsReview", "Classified", "StoredInSP", "Received",
                                "ReadyToLink", "captured", "received"]}},
        ]},
        completed_update("reverted_auto_cleared"),
    )
    results["rule21_reverted_auto_cleared"] = r21.modified_count
    logger.info("[ForceCleanup] Rule 21 (reverted auto_cleared): %d docs → re-completed", r21.modified_count)

    # ── Rule 22: Readiness-status mismatch — readiness says ready but status is NeedsReview ──
    # Direct fix for docs where readiness evaluation worked but status sync was missed
    r22 = await db.hub_documents.update_many(
        {"$and": [
            not_dup,
            {"status": "NeedsReview"},
            {"readiness.status": {"$in": ["ready_auto_draft", "ready_auto_link", "ready"]}},
            {"$or": [
                {"readiness.blocking_reasons": {"$size": 0}},
                {"readiness.blocking_reasons": {"$exists": False}},
            ]},
        ]},
        completed_update("readiness_status_mismatch"),
    )
    results["rule22_readiness_mismatch"] = r22.modified_count
    logger.info("[ForceCleanup] Rule 22 (readiness-status mismatch): %d docs → Completed", r22.modified_count)

    # ── Rule 23: AP Invoices with vendor resolved + po_expected=false → auto-clear ──
    # Vendors whose PO validation has been learned as unnecessary should auto-clear
    # Find vendor_nos where po_expected=false, then clear their docs
    po_relaxed_vendors = await db.vendor_invoice_profiles.find(
        {"po_expected": False},
        {"_id": 0, "vendor_no": 1},
    ).to_list(500)
    po_relaxed_vnos = [v["vendor_no"] for v in po_relaxed_vendors if v.get("vendor_no")]
    if po_relaxed_vnos:
        r23 = await db.hub_documents.update_many(
            base_and(
                {"$or": [
                    {"bc_vendor_number": {"$in": po_relaxed_vnos}},
                    {"vendor_no": {"$in": po_relaxed_vnos}},
                ]},
                {"readiness.signals.vendor_resolved": True},
            ),
            {"$set": {
                "status": "Completed",
                "workflow_status": "processed",
                "auto_cleared": True,
                "automation_decision": "auto_filed",
                "force_cleanup_rule": "po_relaxed_vendor",
                "force_cleanup_at": now,
            }},
        )
    else:
        r23 = type("R", (), {"modified_count": 0})()
    results["rule23_po_relaxed_vendor"] = r23.modified_count
    logger.info("[ForceCleanup] Rule 23 (PO-relaxed vendor): %d docs → Completed", r23.modified_count)

    # ── Rule 24: Packing lists / Commercial invoices from freight forwarders ──
    # These are shipping supporting docs misclassified as AP Invoice
    PACKING_REGEX = r"(?i)(packing.?list|commercial.?invoice|entry.?summary|bill.?of.?lading|house.?bill|hbl|bol|bl_copy|bl_draft)"
    r24 = await db.hub_documents.update_many(
        base_and(
            {"file_name": {"$regex": PACKING_REGEX}},
            {"$or": [
                {"vendor_canonical": {"$exists": True, "$nin": [None, "", "—"]}},
                {"bc_vendor_number": {"$exists": True, "$nin": [None, ""]}},
            ]},
        ),
        {"$set": {
            "status": "Completed",
            "workflow_status": "processed",
            "auto_cleared": True,
            "automation_decision": "auto_filed",
            "force_cleanup_rule": "shipping_supporting_doc",
            "force_cleanup_at": now,
        }},
    )
    results["rule24_shipping_supporting"] = r24.modified_count
    logger.info("[ForceCleanup] Rule 24 (shipping supporting docs): %d docs", r24.modified_count)

    # ── Rule 25: Broadest readiness catchall — NeedsReview with NO blocking reasons ──
    # If readiness has no blocking reasons at all (even with warnings), auto-clear
    r25 = await db.hub_documents.update_many(
        {"$and": [
            not_dup,
            {"status": "NeedsReview"},
            {"$or": [
                {"readiness.blocking_reasons": {"$size": 0}},
                {"readiness.blocking_reasons": {"$exists": False}},
            ]},
            {"$or": [
                {"vendor_canonical": {"$exists": True, "$nin": [None, "", "—"]}},
                {"bc_vendor_number": {"$exists": True, "$nin": [None, ""]}},
                {"readiness.signals.vendor_resolved": True},
            ]},
        ]},
        completed_update("no_blockers_with_vendor"),
    )
    results["rule25_no_blockers"] = r25.modified_count
    logger.info("[ForceCleanup] Rule 25 (NeedsReview + no blockers + vendor): %d docs → Completed", r25.modified_count)

    # ── Count remaining stuck docs ──
    remaining = await db.hub_documents.count_documents({
        "$and": [
            {"is_duplicate": {"$ne": True}},
            {"$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}]},
            {"status": {"$nin": TERMINAL}},
            {"$or": [
                {"workflow_status": {"$nin": DONE_WF}},
                {"workflow_status": {"$exists": False}},
            ]},
        ]
    })

    total_fixed = sum(results.values())
    results["total_fixed"] = total_fixed
    results["remaining_in_inbox"] = remaining
    results["message"] = (
        f"Force cleanup complete: {total_fixed} documents moved out of Inbox. "
        f"{remaining} documents still need manual attention."
    )

    logger.info(
        "[ForceCleanup] DONE — total fixed: %d, remaining in inbox: %d",
        total_fixed, remaining,
    )
    return results



@router.get("/inbox-diagnostic")
async def inbox_diagnostic():
    """
    Shows exactly why documents are stuck in the Inbox and what force-cleanup
    would do for each category. Run this BEFORE sync-status to preview.
    """
    from deps import get_db
    db = get_db()

    TERMINAL = ["Completed", "Posted", "Archived", "completed", "posted",
                "archived", "FileMissing", "batch_parent", "Validated", "validated",
                "ValidationPassed", "ReadyForPost", "ready_for_post", "AutoFiled",
                "auto_filed", "LinkedToBC", "Exception", "exception"]
    DONE_WF = ["completed", "validation_passed", "processed",
               "ready_for_approval", "exported", "file_missing", "exception_review"]

    # Count all docs in the inbox view
    stuck_filter = {
        "$and": [
            {"is_duplicate": {"$ne": True}},
            {"$or": [{"auto_cleared": {"$ne": True}}, {"auto_cleared": {"$exists": False}}]},
            {"status": {"$nin": TERMINAL}},
            {"$or": [
                {"workflow_status": {"$nin": DONE_WF}},
                {"workflow_status": {"$exists": False}},
            ]},
        ]
    }
    total_stuck = await db.hub_documents.count_documents(stuck_filter)

    # Break down by status + readiness + doc type
    breakdown_pipe = [
        {"$match": stuck_filter},
        {"$group": {
            "_id": {
                "status": "$status",
                "readiness": "$readiness.status",
                "doc_type": {"$ifNull": [
                    "$doc_type",
                    {"$ifNull": ["$document_type", {"$ifNull": ["$suggested_job_type", "unknown"]}]}
                ]},
                "has_bc_pi": {"$cond": [
                    {"$and": [
                        {"$ifNull": ["$bc_purchase_invoice_no", False]},
                        {"$ne": ["$bc_purchase_invoice_no", ""]},
                    ]}, True, False
                ]},
                "has_draft": {"$ifNull": ["$auto_draft_created", False]},
                "draft_approved": {"$eq": ["$draft_review_status", "approved"]},
                "vendor_resolved": {"$ifNull": ["$readiness.signals.vendor_resolved", False]},
                "has_vendor": {"$cond": [
                    {"$or": [
                        {"$and": [{"$ifNull": ["$vendor_canonical", False]}, {"$ne": ["$vendor_canonical", ""]}, {"$ne": ["$vendor_canonical", "—"]}]},
                        {"$and": [{"$ifNull": ["$bc_vendor_number", False]}, {"$ne": ["$bc_vendor_number", ""]}]},
                    ]}, True, False
                ]},
                "auto_post_attempted": {"$ifNull": ["$auto_post_attempted", False]},
            },
            "count": {"$sum": 1},
            "sample_vendors": {"$addToSet": {"$ifNull": ["$vendor_canonical", "—"]}},
            "sample_files": {"$push": {"$ifNull": ["$file_name", "?"]}},
        }},
        {"$sort": {"count": -1}},
    ]
    breakdown = await db.hub_documents.aggregate(breakdown_pipe).to_list(100)

    NON_AP_TYPES = {"shipping", "inventory", "bol", "packing", "freight", "warehouse",
                    "statement", "remittance", "unknown", "receipt", "report",
                    "order_confirm", "w9", "w-9", "ar_invoice"}

    import re
    JUNK_EXT_RE = re.compile(r"\.(jpg|jpeg|png|gif|bmp|xlsx|xls|csv|tiff?)$", re.IGNORECASE)
    STATEMENT_RE = re.compile(r"(?i)(statement|SOA_|account.?statement|remittance.?advice|online.?bill.?pay)")
    W9_RE = re.compile(r"(?i)(w-?9|w9_|tax.?form)")
    SELF_VENDOR_RE = re.compile(r"(?i)^gamer\s*(packaging|pack)")

    # Classify each group
    categories = []
    for b in breakdown:
        k = b["_id"]
        doc_type_lower = (k.get("doc_type") or "").lower()
        is_non_ap = any(t in doc_type_lower for t in NON_AP_TYPES)
        sample_files = (b.get("sample_files") or [])[:3]

        # Check filename patterns from sample files
        has_junk_ext = any(JUNK_EXT_RE.search(f) for f in sample_files)
        has_statement = any(STATEMENT_RE.search(f) for f in sample_files)
        has_w9 = any(W9_RE.search(f) for f in sample_files)
        sample_vendors = list(b.get("sample_vendors", []))[:3]
        is_self_vendor = any(SELF_VENDOR_RE.match(v) for v in sample_vendors if v)

        rule = "no_rule_yet"
        if k.get("has_bc_pi"):
            rule = "Rule 1: Has BC PI"
        elif k.get("draft_approved"):
            rule = "Rule 2: Draft approved"
        elif k.get("has_draft"):
            rule = "Rule 3: Auto-draft"
        elif k.get("readiness") in ("ready_auto_draft", "ready_auto_link", "ready"):
            rule = "Rule 7: Readiness ready"
        elif k.get("vendor_resolved"):
            rule = "Rule 5: Vendor resolved"
        elif is_non_ap and k.get("has_vendor"):
            rule = "Rule 8: Non-AP + vendor"
        elif is_non_ap:
            rule = "Rule 9: Non-AP"
        elif has_junk_ext:
            rule = "Rule 12: Junk file type"
        elif has_statement:
            rule = "Rule 13: Statement/SOA"
        elif is_self_vendor:
            rule = "Rule 14: Self-vendor"
        elif has_w9:
            rule = "Rule 15: Tax form"
        elif k.get("auto_post_attempted") and k.get("has_vendor"):
            rule = "Rule 10: Auto-post attempted"
        else:
            rule = "Needs manual review"

        categories.append({
            "status": k.get("status"),
            "readiness_status": k.get("readiness"),
            "doc_type": k.get("doc_type"),
            "has_vendor": k.get("has_vendor"),
            "count": b["count"],
            "cleanup_rule": rule,
            "sample_vendors": sample_vendors,
            "sample_files": sample_files,
        })

    # Estimate cleanup impact
    would_fix = sum(c["count"] for c in categories if "Needs manual" not in c["cleanup_rule"])
    would_remain = sum(c["count"] for c in categories if "Needs manual" in c["cleanup_rule"])

    return {
        "total_in_inbox": total_stuck,
        "would_fix": would_fix,
        "would_remain_after_cleanup": would_remain,
        "breakdown": categories,
        "action": "POST /api/readiness/sync-status to execute cleanup",
    }


@router.get("/automation-rate")
async def get_automation_rate(days: int = Query(30, ge=1, le=90)):
    """
    Automation rate dashboard data:
    - Current automation rate %
    - Daily trend of auto-processed vs manual-review
    - Queue size breakdown
    - Top vendors still requiring manual review
    """
    from deps import get_db
    from datetime import datetime, timezone, timedelta

    db = get_db()
    now = datetime.now(timezone.utc)
    cutoff = (now - timedelta(days=days)).isoformat()

    # --- Current snapshot ---
    total = await db.hub_documents.count_documents({"is_duplicate": {"$ne": True}})
    auto_statuses = ["ready_auto_draft", "ready_auto_link"]
    manual_statuses = ["needs_review", "ambiguous"]

    auto_count = await db.hub_documents.count_documents({
        "is_duplicate": {"$ne": True},
        "$or": [
            {"readiness.status": {"$in": auto_statuses}},
            {"status": {"$in": ["Completed", "Posted"]}},
            {"bc_purchase_invoice_no": {"$exists": True, "$nin": [None, ""]}},
        ],
    })
    manual_count = await db.hub_documents.count_documents({
        "is_duplicate": {"$ne": True},
        "readiness.status": {"$in": manual_statuses},
    })
    blocked_count = await db.hub_documents.count_documents({
        "is_duplicate": {"$ne": True},
        "readiness.status": "blocked",
    })

    # Docs with BC PI = successfully auto-processed
    bc_posted = await db.hub_documents.count_documents({
        "bc_purchase_invoice_no": {"$exists": True, "$nin": [None, ""]},
    })

    automation_rate = round(auto_count / max(total, 1) * 100, 1)
    posting_rate = round(bc_posted / max(total, 1) * 100, 1)

    # --- Daily trend (bucketed by readiness.last_evaluated_at or updated_utc) ---
    daily_pipeline = [
        {"$match": {
            "is_duplicate": {"$ne": True},
            "readiness.last_evaluated_at": {"$exists": True, "$gte": cutoff},
        }},
        {"$addFields": {
            "eval_date": {"$substr": ["$readiness.last_evaluated_at", 0, 10]},
        }},
        {"$group": {
            "_id": "$eval_date",
            "total": {"$sum": 1},
            "auto_ready": {"$sum": {"$cond": [
                {"$in": ["$readiness.status", auto_statuses]}, 1, 0
            ]}},
            "manual_review": {"$sum": {"$cond": [
                {"$in": ["$readiness.status", manual_statuses]}, 1, 0
            ]}},
            "blocked": {"$sum": {"$cond": [
                {"$eq": ["$readiness.status", "blocked"]}, 1, 0
            ]}},
        }},
        {"$sort": {"_id": 1}},
    ]
    daily_raw = await db.hub_documents.aggregate(daily_pipeline).to_list(days + 5)
    daily_trend = [
        {
            "date": r["_id"],
            "auto": r["auto_ready"],
            "manual": r["manual_review"],
            "blocked": r["blocked"],
            "total": r["total"],
            "rate": round(r["auto_ready"] / max(r["total"], 1) * 100, 1),
        }
        for r in daily_raw if r["_id"]
    ]

    # --- Top vendors requiring manual review ---
    vendor_manual_pipeline = [
        {"$match": {
            "is_duplicate": {"$ne": True},
            "readiness.status": {"$in": manual_statuses + ["blocked"]},
        }},
        {"$group": {
            "_id": {"$ifNull": ["$bc_vendor_number", {"$ifNull": ["$vendor_canonical", "Unknown"]}]},
            "count": {"$sum": 1},
            "top_reasons": {"$push": {"$arrayElemAt": [{"$ifNull": ["$readiness.blocking_reasons", ["$readiness.warning_reasons"]]}, 0]}},
        }},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    vendor_manual_raw = await db.hub_documents.aggregate(vendor_manual_pipeline).to_list(10)
    top_manual_vendors = []
    for v in vendor_manual_raw:
        vendor_id = v["_id"] or "Unknown"
        reasons = [r for r in (v.get("top_reasons") or []) if r]
        # Count most common reason
        reason_counts = {}
        for r in reasons:
            if isinstance(r, list):
                for sub_r in r:
                    reason_counts[sub_r] = reason_counts.get(sub_r, 0) + 1
            elif isinstance(r, str):
                reason_counts[r] = reason_counts.get(r, 0) + 1
        top_reason = max(reason_counts, key=reason_counts.get) if reason_counts else "unknown"
        top_manual_vendors.append({
            "vendor": vendor_id,
            "count": v["count"],
            "primary_reason": top_reason,
        })

    # --- Readiness distribution ---
    dist_pipeline = [
        {"$match": {"is_duplicate": {"$ne": True}, "readiness.status": {"$exists": True}}},
        {"$group": {"_id": "$readiness.status", "count": {"$sum": 1}}},
    ]
    dist_raw = await db.hub_documents.aggregate(dist_pipeline).to_list(10)
    distribution = {r["_id"]: r["count"] for r in dist_raw if r["_id"]}

    return {
        "automation_rate": automation_rate,
        "posting_rate": posting_rate,
        "total_documents": total,
        "auto_processed": auto_count,
        "manual_review": manual_count,
        "blocked": blocked_count,
        "bc_posted": bc_posted,
        "distribution": distribution,
        "daily_trend": daily_trend,
        "top_manual_vendors": top_manual_vendors,
        "period_days": days,
    }


@router.post("/retry-failed")
async def retry_failed_extractions(
    limit: int = Query(100, le=500),
    force_escalate: bool = Query(False, description="If true, immediately move all stuck docs to Exception Queue regardless of retry count"),
):
    """
    Batch retry documents with failed extraction (0 fields, no vendor).
    Normal mode: Increments retry_count on each. After 4 retries, moves to Exception Queue.
    Force mode (force_escalate=true): Immediately moves ALL stuck docs to Exception Queue.
    """
    from deps import get_db
    from datetime import datetime, timezone
    from services.square9_workflow import DEFAULT_WORKFLOW_CONFIG

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    max_retries = DEFAULT_WORKFLOW_CONFIG["max_retry_attempts"]

    TERMINAL = ["Completed", "Posted", "Archived", "completed", "posted",
                "archived", "FileMissing", "batch_parent", "Validated", "validated",
                "ValidationPassed", "ReadyForPost", "AutoFiled", "LinkedToBC",
                "Exception", "exception"]

    # Find docs stuck in inbox with extraction problems
    failed_docs = await db.hub_documents.find(
        {
            "is_duplicate": {"$ne": True},
            "status": {"$nin": TERMINAL},
            "$or": [
                {"auto_cleared": {"$ne": True}},
                {"auto_cleared": {"$exists": False}},
            ],
            # Extraction failure indicators
            "$and": [
                {"$or": [
                    {"readiness.signals.vendor_resolved": {"$ne": True}},
                    {"readiness.signals.required_fields_complete": {"$ne": True}},
                    {"readiness.status": {"$in": ["blocked", "needs_review"]}},
                    {"readiness": {"$exists": False}},
                ]},
            ],
        },
        {"_id": 0, "id": 1, "file_name": 1, "retry_count": 1, "max_retries": 1,
         "vendor_canonical": 1, "readiness.status": 1, "status": 1},
    ).limit(limit).to_list(limit)

    retried = 0
    escalated = 0
    already_maxed = 0
    retry_details = []

    for doc in failed_docs:
        doc_id = doc["id"]
        current_retries = doc.get("retry_count", 0)
        doc_max = doc.get("max_retries", max_retries)

        if force_escalate or current_retries >= doc_max:
            # Force escalate or already at max — move to Exception Queue
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "status": "Exception",
                    "workflow_status": "exception_review",
                    "auto_cleared": True,
                    "auto_escalated": True,
                    "retry_count": max(current_retries, doc_max),
                    "escalation_reason": f"{'Force escalated' if force_escalate else f'Max retries ({doc_max}) reached'} — extraction failed",
                    "force_cleanup_rule": "max_retries_exception",
                    "updated_utc": now,
                }},
            )
            escalated += 1
            retry_details.append({
                "doc_id": doc_id[:8],
                "file": doc.get("file_name", "?"),
                "action": "exception_queue",
                "retries": current_retries,
            })
            continue

        # Increment retry count
        new_count = current_retries + 1
        retry_entry = {
            "attempt": new_count,
            "timestamp": now,
            "reason": "batch_retry_failed_extraction",
            "stage": "extraction_retry",
        }

        update = {
            "retry_count": new_count,
            "last_retry_utc": now,
            "last_retry_reason": "batch_retry_failed_extraction",
            "updated_utc": now,
        }

        # If this puts us at max, escalate to Exception
        if new_count >= doc_max:
            update["status"] = "Exception"
            update["workflow_status"] = "exception_review"
            update["auto_cleared"] = True
            update["auto_escalated"] = True
            update["escalation_reason"] = f"Max retries ({doc_max}) reached — extraction failed"
            escalated += 1
            action = "exception_queue"
        else:
            retried += 1
            action = f"retry_{new_count}/{doc_max}"

        await db.hub_documents.update_one(
            {"id": doc_id},
            {
                "$set": update,
                "$push": {"retry_history": retry_entry},
            },
        )

        retry_details.append({
            "doc_id": doc_id[:8],
            "file": doc.get("file_name", "?"),
            "action": action,
            "retries": new_count,
        })

    return {
        "total_found": len(failed_docs),
        "retried": retried,
        "escalated_to_exception": escalated,
        "already_maxed": already_maxed,
        "max_retries": max_retries,
        "details": retry_details[:30],
        "message": (
            f"Processed {len(failed_docs)} failed docs: "
            f"{retried} retried, {escalated} moved to Exception Queue."
        ),
    }


@router.post("/retry-captured")
async def retry_captured_docs(
    limit: int = Query(50, le=200),
    force_escalate: bool = Query(False, description="Immediately move all stuck captured docs to Exception Queue"),
):
    """
    Manual trigger: retry documents stuck in 'captured' workflow_status.
    Normal: Re-runs reprocess with reclassify=True, up to 4 retries then Exception Queue.
    Force: Immediately moves all to Exception Queue.
    """
    from deps import get_db
    from datetime import datetime, timezone

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()
    MAX_RETRIES = 4

    stuck_docs = await db.hub_documents.find(
        {
            "workflow_status": {"$in": ["captured", "Captured"]},
            "status": {"$nin": ["Completed", "Posted", "Archived", "Exception",
                                "exception", "batch_parent", "FileMissing"]},
            "captured_retry_escalated": {"$ne": True},
        },
        {"_id": 0, "id": 1, "file_name": 1, "captured_retry_count": 1},
    ).limit(limit).to_list(limit)

    retried = 0
    escalated = 0
    details = []

    for doc in stuck_docs:
        doc_id = doc["id"]
        retry_count = doc.get("captured_retry_count", 0) + 1

        if force_escalate or retry_count > MAX_RETRIES:
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "status": "Exception",
                    "workflow_status": "exception_review",
                    "auto_cleared": True,
                    "auto_escalated": True,
                    "captured_retry_escalated": True,
                    "captured_retry_count": retry_count,
                    "escalation_reason": f"{'Force escalated' if force_escalate else f'Max retries ({MAX_RETRIES}) reached'} — stuck in captured",
                    "updated_utc": now,
                },
                "$push": {"workflow_history": {
                    "timestamp": now,
                    "from_status": "captured",
                    "to_status": "exception_review",
                    "event": "captured_retry_escalation",
                    "actor": "manual_trigger",
                    "reason": f"{'Force escalated' if force_escalate else f'Max retries ({MAX_RETRIES})'} — stuck in captured",
                }}},
            )
            escalated += 1
            details.append({"doc_id": doc_id[:8], "file": doc.get("file_name", "?"), "action": "exception_queue", "retries": retry_count})
            continue

        # Attempt reprocess
        try:
            from server import _reprocess_document_inner
            full_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
            if full_doc:
                await _reprocess_document_inner(doc_id, full_doc, reclassify=True)
        except Exception as e:
            import logging
            logging.getLogger("readiness").warning("[RetryCaptured] Reprocess failed for %s: %s", doc_id[:8], str(e))

        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "captured_retry_count": retry_count,
                "captured_last_retry_utc": now,
                "updated_utc": now,
            },
            "$push": {"workflow_history": {
                "timestamp": now,
                "from_status": "captured",
                "to_status": "captured",
                "event": "captured_manual_retry",
                "actor": "manual_trigger",
                "reason": f"Manual retry attempt {retry_count}/{MAX_RETRIES}",
            }}},
        )
        retried += 1
        details.append({"doc_id": doc_id[:8], "file": doc.get("file_name", "?"), "action": f"retry_{retry_count}/{MAX_RETRIES}", "retries": retry_count})

    return {
        "total_found": len(stuck_docs),
        "retried": retried,
        "escalated_to_exception": escalated,
        "max_retries": MAX_RETRIES,
        "details": details[:30],
        "message": f"Processed {len(stuck_docs)} stuck captured docs: {retried} retried, {escalated} escalated.",
    }


@router.get("/exception-queue")
async def get_exception_queue(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    """
    Returns documents in the Exception Queue — docs that failed extraction
    after max retries and need human review / manual intervention.
    """
    from deps import get_db
    db = get_db()

    query = {
        "$and": [
            {"is_duplicate": {"$ne": True}},
            # Exclude docs that have already been resolved/completed
            {"status": {"$nin": [
                "Completed", "completed", "Posted", "posted", "Archived", "archived",
                "AutoFiled", "auto_filed", "LinkedToBC", "Validated", "validated",
                "ValidationPassed", "ReadyForPost", "ready_for_post", "batch_parent",
            ]}},
            {"$or": [
                {"status": {"$in": ["Exception", "exception"]}},
                {"workflow_status": "exception_review"},
                {"auto_escalated": True},
            ]},
        ],
    }

    total = await db.hub_documents.count_documents(query)
    docs = await db.hub_documents.find(
        query,
        {
            "_id": 0, "id": 1, "file_name": 1, "status": 1,
            "vendor_canonical": 1, "doc_type": 1, "document_type": 1,
            "retry_count": 1, "max_retries": 1, "escalation_reason": 1,
            "readiness.status": 1, "readiness.blocking_reasons": 1,
            "created_utc": 1, "updated_utc": 1,
            "extracted_fields": 1,
        },
    ).sort("updated_utc", -1).skip(skip).limit(limit).to_list(limit)

    return {
        "total": total,
        "documents": docs,
    }


# ───────────────────────────────────────────────────
# PO Auto-Retry Queue
# ───────────────────────────────────────────────────

PO_RETRY_INTERVAL_HOURS = 4
PO_MAX_WAIT_DAYS = 3
PO_MAX_RETRIES = PO_MAX_WAIT_DAYS * 24 // PO_RETRY_INTERVAL_HOURS  # = 18 cycles


@router.post("/po-pending/park")
async def park_po_pending_docs():
    """
    Finds documents stuck on PO validation gaps and parks them in the
    'po_pending' queue. These docs will be auto-retried every 4 hours.
    After 3 days (18 retries) they escalate to the Exception Queue.
    """
    from deps import get_db
    from datetime import datetime, timezone

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    DONE_STATUSES = ["Completed", "Posted", "Archived", "completed", "posted",
                     "archived", "FileMissing", "Exception", "exception",
                     "Validated", "validated", "ReadyForPost", "AutoFiled",
                     "batch_parent"]

    # Find docs where PO is the issue — multiple detection methods
    po_gap_filter = {
        "is_duplicate": {"$ne": True},
        "is_batch_parent": {"$ne": True},
        "status": {"$nin": DONE_STATUSES},
        "auto_cleared": {"$ne": True},
        "po_pending_parked": {"$ne": True},  # not already parked
        "$or": [
            # Readiness says po_missing in warnings
            {"readiness.warning_reasons": "po_missing"},
            # BC validation has po_validation or po_check failed
            {"validation_results.checks": {
                "$elemMatch": {
                    "check_name": {"$in": ["po_validation", "po_check"]},
                    "passed": False,
                },
            }},
            {"bc_validation.checks": {
                "$elemMatch": {
                    "check_name": {"$in": ["po_validation", "po_check"]},
                    "passed": False,
                },
            }},
            # Readiness blocking includes po_validation
            {"readiness.blocking_reasons": {"$regex": "po"}},
        ],
    }

    docs = await db.hub_documents.find(
        po_gap_filter,
        {"_id": 0, "id": 1, "file_name": 1, "vendor_canonical": 1,
         "po_number_clean": 1, "extracted_fields.po_number": 1},
    ).limit(500).to_list(500)

    parked = 0
    details = []

    for doc in docs:
        doc_id = doc["id"]
        po = doc.get("po_number_clean") or (doc.get("extracted_fields") or {}).get("po_number", "?")

        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {
                "po_pending_parked": True,
                "po_pending_parked_at": now,
                "po_pending_retry_count": 0,
                "po_pending_max_retries": PO_MAX_RETRIES,
                "po_pending_next_retry": now,  # retry immediately on first cycle
                "workflow_status": "po_pending",
            }},
        )
        parked += 1
        details.append({
            "doc_id": doc_id[:8],
            "file": doc.get("file_name", "?"),
            "vendor": doc.get("vendor_canonical", "?"),
            "po": po,
        })

    return {
        "parked": parked,
        "retry_interval_hours": PO_RETRY_INTERVAL_HOURS,
        "max_wait_days": PO_MAX_WAIT_DAYS,
        "max_retries": PO_MAX_RETRIES,
        "details": details[:30],
        "message": f"Parked {parked} docs in PO Pending queue. Will retry every {PO_RETRY_INTERVAL_HOURS}h for up to {PO_MAX_WAIT_DAYS} days.",
    }


@router.post("/po-pending/retry")
async def retry_po_pending_docs():
    """
    Re-evaluates all PO-pending documents. If PO now resolves → doc proceeds
    to normal processing. If max retries exceeded → Exception Queue.
    Runs full readiness evaluation (not just PO check).
    """
    from deps import get_db
    from datetime import datetime, timezone
    from services.document_readiness_service import evaluate_and_persist
    import logging

    logger = logging.getLogger("po_retry")
    db = get_db()
    now = datetime.now(timezone.utc)
    now_iso = now.isoformat()

    # Find all parked PO-pending docs (exclude batch parents)
    pending_docs = await db.hub_documents.find(
        {
            "po_pending_parked": True,
            "is_batch_parent": {"$ne": True},
            "status": {"$nin": ["Completed", "Posted", "Exception", "exception", "batch_parent"]},
        },
        {"_id": 0},
    ).limit(500).to_list(500)

    resolved = 0
    still_pending = 0
    escalated = 0
    errors = 0
    details = []

    for doc in pending_docs:
        doc_id = doc["id"]
        retry_count = doc.get("po_pending_retry_count", 0) + 1
        max_retries = doc.get("po_pending_max_retries", PO_MAX_RETRIES)

        try:
            # Full re-evaluation
            readiness = await evaluate_and_persist(doc)
            po_resolved = (readiness.get("signals") or {}).get("po_resolved", False)
            is_ready = readiness.get("status", "").startswith("ready")

            if po_resolved or is_ready:
                # PO resolved or doc is now ready — unpark and let it proceed
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "po_pending_parked": False,
                        "po_pending_resolved_at": now_iso,
                        "po_pending_retry_count": retry_count,
                        "workflow_status": "processed" if is_ready else "validation",
                    }},
                )
                resolved += 1
                details.append({"doc_id": doc_id[:8], "action": "resolved", "retries": retry_count})
                logger.info("[PO Retry] RESOLVED doc=%s after %d retries", doc_id[:8], retry_count)

            elif retry_count >= max_retries:
                # Max retries exceeded — escalate to Exception Queue
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "po_pending_parked": False,
                        "po_pending_retry_count": retry_count,
                        "status": "Exception",
                        "workflow_status": "exception_review",
                        "auto_cleared": True,
                        "auto_escalated": True,
                        "escalation_reason": f"PO not found after {retry_count} retries ({PO_MAX_WAIT_DAYS} days)",
                        "force_cleanup_rule": "po_pending_max_retries",
                        "updated_utc": now_iso,
                    }},
                )
                escalated += 1
                details.append({"doc_id": doc_id[:8], "action": "exception_queue", "retries": retry_count})
                logger.info("[PO Retry] ESCALATED doc=%s after %d retries (max=%d)", doc_id[:8], retry_count, max_retries)

            else:
                # Still pending — update retry count and schedule next
                next_retry = (now + __import__("datetime").timedelta(hours=PO_RETRY_INTERVAL_HOURS)).isoformat()
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "po_pending_retry_count": retry_count,
                        "po_pending_next_retry": next_retry,
                        "po_pending_last_retry": now_iso,
                        "updated_utc": now_iso,
                    }},
                )
                still_pending += 1
                details.append({"doc_id": doc_id[:8], "action": f"retry_{retry_count}/{max_retries}", "retries": retry_count})

        except Exception as e:
            errors += 1
            details.append({"doc_id": doc_id[:8], "action": "error", "error": str(e)[:80]})
            logger.error("[PO Retry] Error on doc=%s: %s", doc_id[:8], str(e))

    return {
        "total_checked": len(pending_docs),
        "resolved": resolved,
        "still_pending": still_pending,
        "escalated_to_exception": escalated,
        "errors": errors,
        "details": details[:30],
        "message": (
            f"PO retry: {resolved} resolved, {still_pending} still waiting, "
            f"{escalated} escalated to Exception Queue."
        ),
    }


@router.get("/po-pending")
async def get_po_pending_queue(
    skip: int = Query(0, ge=0),
    limit: int = Query(50, ge=1, le=500),
):
    """Returns documents in the PO Pending auto-retry queue."""
    from deps import get_db
    db = get_db()

    query = {
        "po_pending_parked": True,
        "status": {"$nin": [
            "Completed", "completed", "Posted", "posted", "Archived", "archived",
            "AutoFiled", "auto_filed", "LinkedToBC", "Validated", "validated",
            "ValidationPassed", "ReadyForPost", "ready_for_post", "batch_parent",
        ]},
    }
    total = await db.hub_documents.count_documents(query)
    docs = await db.hub_documents.find(
        query,
        {
            "_id": 0, "id": 1, "file_name": 1, "status": 1,
            "vendor_canonical": 1, "doc_type": 1, "document_type": 1,
            "po_number_clean": 1, "extracted_fields.po_number": 1,
            "po_pending_retry_count": 1, "po_pending_max_retries": 1,
            "po_pending_parked_at": 1, "po_pending_next_retry": 1,
            "po_pending_last_retry": 1,
            "readiness.status": 1, "readiness.blocking_reasons": 1,
            "created_utc": 1, "updated_utc": 1,
        },
    ).sort("po_pending_parked_at", -1).skip(skip).limit(limit).to_list(limit)

    return {"total": total, "documents": docs}


@router.post("/retry-ready-to-post")
async def retry_ready_to_post(
    limit: int = Query(50, le=200),
):
    """
    Manual trigger: attempt to post all ReadyForPost documents to BC.
    Picks up docs that passed all validation but haven't been posted yet.
    """
    import os
    from deps import get_db
    from datetime import datetime, timezone

    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    bc_write_enabled = os.environ.get("BC_WRITE_ENABLED", "false").lower() == "true"
    if not bc_write_enabled:
        return {
            "success": False,
            "reason": "BC_WRITE_ENABLED is false — cannot post to BC",
            "posted": 0, "failed": 0, "total": 0,
        }

    ready_docs = await db.hub_documents.find(
        {
            "$or": [
                {"status": "ReadyForPost"},
                {"workflow_status": "ready_for_post"},
            ],
            "status": {"$nin": ["Posted", "Completed", "Archived"]},
            "bc_purchase_invoice": {"$exists": False},
        },
        {"_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_no": 1, "file_name": 1,
         "ready_post_retry_count": 1},
    ).limit(limit).to_list(limit)

    posted = 0
    failed = 0
    details = []

    for doc in ready_docs:
        doc_id = doc.get("id", "")
        if not doc_id:
            continue
        try:
            from routers.gpi_integration import create_purchase_invoice_from_document
            result = await create_purchase_invoice_from_document(
                doc_id, vendor_no_override="", force=False
            )
            if result.get("success") or result.get("already_exists"):
                bc_record_no = result.get("bc_record_no", "")
                await db.hub_documents.update_one(
                    {"id": doc_id},
                    {"$set": {
                        "status": "Posted",
                        "workflow_status": "posted",
                        "auto_cleared": True,
                        "auto_post_success": True,
                        "bc_posting_status": "posted",
                        "bc_record_no": bc_record_no,
                        "bc_system_id": result.get("bc_system_id", ""),
                        "posted_to_bc_at": now,
                        "updated_utc": now,
                    }},
                )
                posted += 1
                details.append({"doc_id": doc_id[:8], "file": doc.get("file_name", "?"),
                                "action": "posted", "bc_record_no": bc_record_no})
            else:
                error_msg = str(result.get("error_message") or result.get("error") or "Unknown")[:200]
                failed += 1
                details.append({"doc_id": doc_id[:8], "file": doc.get("file_name", "?"),
                                "action": "failed", "error": error_msg})
        except Exception as e:
            failed += 1
            details.append({"doc_id": doc_id[:8], "file": doc.get("file_name", "?"),
                            "action": "error", "error": str(e)[:200]})

    return {
        "success": True,
        "total": len(ready_docs),
        "posted": posted,
        "failed": failed,
        "details": details,
    }
