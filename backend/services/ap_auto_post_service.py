"""
AP Invoice Auto-Post Service

Dead simple rules:
  1. Classified as AP_Invoice ✓
  2. Required fields extracted (invoice #, date, amount) ✓
  3. Vendor matched in BC ✓
  4. PO matched in BC ✓

  ALL pass → AUTO-POST to BC
  ANY fail → NEEDS_REVIEW

After human review + "Mark Ready" → AUTO-POST

Phase 2 — Confidence-Gated Auto-Draft:
  When a document reaches ReadyForPost and the vendor has a
  HIGH-confidence posting template (learned from BC history),
  automatically create a DRAFT Purchase Invoice in BC.
"""

import logging
import os
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, List, Optional, Tuple

logger = logging.getLogger(__name__)

# Confidence level ordering
CONFIDENCE_LEVELS = {"low": 1, "medium": 2, "high": 3}


def check_ap_ready_to_post(doc: dict, vendor_profile: dict = None, source: str = "auto", posting_profile: dict = None) -> Tuple[bool, str, list]:
    """Check if an AP invoice passes the 4 conditions for auto-posting.
    
    Args:
        doc: Document from MongoDB
        vendor_profile: Optional vendor profile from vendor_invoice_profile_service.
                       Used to determine if PO is expected for this vendor.
        source: "auto" (intake pipeline), "reprocess", or "mark_ready" (human review)
    
    Returns: (ready, reason, failures)
    """
    failures = []
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    val = doc.get("validation_results") or {}

    # Check for manual override — human reviewer has already approved this document
    has_manual_override = doc.get("manual_po_override") or doc.get("manual_override")
    is_human_action = source in ("mark_ready", "manual_override", "human_review")

    # 1. Classified as AP_Invoice
    doc_type = doc.get("doc_type") or doc.get("document_type") or doc.get("suggested_job_type") or ""
    if doc_type.upper().replace(" ", "_") not in ("AP_INVOICE", "PURCHASE_INVOICE"):
        failures.append("Not classified as AP_Invoice")

    # 2. Required fields extracted
    invoice_no = ef.get("invoice_number") or nf.get("invoice_number") or doc.get("invoice_number_clean") or doc.get("external_document_no") or ""
    amount = ef.get("amount") or nf.get("amount") or doc.get("amount_float") or ef.get("invoice_amount") or ef.get("total_amount") or nf.get("total_amount") or ""
    invoice_date = ef.get("invoice_date") or nf.get("invoice_date") or doc.get("document_date") or ""
    vendor_raw = ef.get("vendor") or nf.get("vendor") or doc.get("vendor_canonical") or ""

    if not invoice_no:
        failures.append("Missing invoice number")
    if not amount:
        failures.append("Missing amount")
    if not invoice_date:
        failures.append("Missing invoice date")
    if not vendor_raw:
        failures.append("Missing vendor name from extraction")

    # 3. Vendor matched in BC
    vendor_no = (
        doc.get("bc_vendor_number")
        or doc.get("vendor_no")
        or (doc.get("validation_results") or {}).get("bc_record_info", {}).get("number")
        or ""
    )
    if not vendor_no:
        failures.append("Vendor not resolved to BC vendor number")

    # 4. PO check — with overrides
    # Skip PO check if:
    #   a) Human reviewer already overrode it (manual_po_override flag)
    #   b) Human is clicking "Mark Ready" right now (source=mark_ready)
    #   c) Vendor profile says PO is never expected (freight carriers etc.)
    #   d) Vendor has a high-confidence posting template (we KNOW how to post this vendor)
    vp = vendor_profile or {}
    po_expected = vp.get("po_expected", True)
    
    # Check posting template confidence
    pp = posting_profile or {}
    pp_template = pp.get("posting_template", {})
    pp_confidence = pp_template.get("confidence", "low")
    pp_has_high_confidence = pp_confidence in ("high", "medium") and pp.get("invoices_analyzed", 0) >= 10

    if has_manual_override:
        logger.info("[AP Auto-Post] PO check SKIPPED — manual override set by reviewer")
    elif is_human_action:
        logger.info("[AP Auto-Post] PO check SKIPPED — human review action (%s)", source)
    elif not po_expected:
        logger.info("[AP Auto-Post] PO check SKIPPED for vendor %s — BC history shows PO never expected", vendor_no)
    elif pp_has_high_confidence:
        logger.info("[AP Auto-Post] PO check SKIPPED for vendor %s — posting template confidence=%s (%d invoices learned)",
                     vendor_no, pp_confidence, pp.get("invoices_analyzed", 0))
    else:
        po_passed = False
        for check in val.get("checks", []):
            if check.get("check_name") in ("po_validation", "po_match") and check.get("passed"):
                po_passed = True
                break
        
        # Accept if no PO was extracted at all (some invoices legitimately have no PO)
        po_extracted = bool(
            ef.get("po_number") or nf.get("po_number") or 
            doc.get("po_number_clean") or ef.get("order_number")
        )
        if po_extracted and not po_passed:
            failures.append("PO extracted but not found/matched in BC")

    if failures:
        return False, f"AP invoice not ready: {'; '.join(failures)}", failures
    
    return True, "All conditions met — ready for auto-post", []


async def attempt_ap_auto_post(doc_id: str, db, source: str = "auto") -> Dict:
    """Attempt to auto-post an AP invoice to BC.
    
    Args:
        doc_id: Document ID
        db: MongoDB database
        source: "auto" (intake pipeline), "reprocess", or "mark_ready" (human review)
    
    Returns: {success, posted, reason, bc_record_no, status}
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"success": False, "posted": False, "reason": "Document not found", "status": "error"}

    # Load vendor profile to get PO expectations, learned from BC history
    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""
    vendor_profile = None
    posting_profile = None
    if vendor_no:
        try:
            from services.vendor_invoice_profile_service import get_or_build_profile
            vendor_profile = await get_or_build_profile(db, vendor_no)
        except Exception as vp_err:
            logger.warning("[AP Auto-Post] Could not load vendor profile for %s: %s", vendor_no, vp_err)
        try:
            from services.posting_pattern_analyzer import get_posting_profile_for_vendor
            posting_profile = await get_posting_profile_for_vendor(db, vendor_no)
        except Exception as pp_err:
            logger.debug("[AP Auto-Post] No posting profile for %s: %s", vendor_no, pp_err)

    ready, reason, failures = check_ap_ready_to_post(doc, vendor_profile=vendor_profile, source=source, posting_profile=posting_profile)

    if not ready:
        # Only revert status for actual AP documents that failed validation.
        # Non-AP docs (shipping, inventory, etc.) should NOT be reverted to NeedsReview
        # just because they aren't AP invoices — that's expected, not a failure.
        doc_type = doc.get("doc_type") or doc.get("document_type") or doc.get("suggested_job_type") or ""
        is_ap_type = doc_type.upper().replace(" ", "_") in ("AP_INVOICE", "PURCHASE_INVOICE")
        not_ap_failure = any("Not classified as AP_Invoice" in f for f in failures)

        now = datetime.now(timezone.utc).isoformat()

        if not_ap_failure:
            # Non-AP doc — don't touch its status, just record the skip
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "auto_post_attempted": True,
                "auto_post_reason": "Skipped — not an AP invoice type",
                "updated_utc": now,
            }})
            logger.debug("[AP Auto-Post] Skipped non-AP doc %s (type: %s)", doc_id[:8], doc_type)
            return {"success": True, "posted": False, "reason": "not_ap_type", "status": "skipped"}
        elif is_ap_type:
            # Genuine AP doc that failed validation — revert to NeedsReview
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "status": "NeedsReview",
                "workflow_status": "needs_review",
                "auto_cleared": False,
                "auto_post_attempted": True,
                "auto_post_reason": reason,
                "auto_post_failures": failures,
                "updated_utc": now,
            }})
        else:
            # Non-AP doc with other failures — don't revert status
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "auto_post_attempted": True,
                "auto_post_reason": reason,
                "auto_post_failures": failures,
                "updated_utc": now,
            }})

        # Write event
        await _write_event(db, doc_id, "automation.decision.completed", {
            "decision": "NeedsReview" if is_ap_type else "skipped",
            "auto_clear": False,
            "auto_post": False,
            "reason": reason,
            "failures": failures,
            "source": source,
        })

        logger.info("[AP Auto-Post] %s for %s: %s", "NeedsReview" if is_ap_type else "Skipped", doc_id[:8], reason)
        return {"success": True, "posted": False, "reason": reason, "status": "NeedsReview" if is_ap_type else "skipped", "failures": failures}

    # All conditions met — attempt to post to BC
    bc_write_enabled = os.environ.get("BC_WRITE_ENABLED", "false").lower() == "true"

    if not bc_write_enabled:
        # BC writes disabled — mark as ready but don't post
        now = datetime.now(timezone.utc).isoformat()
        update_data = {
            "status": "ReadyForPost",
            "workflow_status": "ready_for_post",
            "auto_cleared": True,
            "auto_post_attempted": True,
            "auto_post_reason": "All checks passed — BC writes disabled, queued for manual post",
            "updated_utc": now,
        }
        # Attach posting template if available (helps human reviewer)
        if posting_profile and posting_profile.get("posting_template"):
            update_data["suggested_posting_template"] = posting_profile["posting_template"]
            update_data["posting_profile_confidence"] = posting_profile["posting_template"].get("confidence", "low")

        await db.hub_documents.update_one({"id": doc_id}, {"$set": update_data})
        await _write_event(db, doc_id, "automation.decision.completed", {
            "decision": "ReadyForPost",
            "auto_clear": True,
            "auto_post": False,
            "reason": "All checks passed — BC writes disabled, queued for manual post",
            "source": source,
        })
        logger.info("[AP Auto-Post] All checks passed for %s but BC_WRITE_ENABLED=false", doc_id[:8])

        # Auto-confirm: Record successful automation as positive feedback
        await _record_success_feedback(db, doc_id, "ReadyForPost", source)

        # Phase 2: Try auto-drafting if confidence gate passes
        auto_draft_result = None
        try:
            auto_draft_result = await attempt_auto_draft_pi(doc_id, db, source="pipeline_auto_draft")
            if auto_draft_result.get("drafted"):
                logger.info("[AP Auto-Post] Auto-drafted PI %s for %s",
                            auto_draft_result.get("bc_record_no", "?"), doc_id[:8])
        except Exception as ad_err:
            logger.debug("[AP Auto-Post] Auto-draft check failed (non-blocking): %s", ad_err)

        return {
            "success": True, "posted": False, "reason": "BC writes disabled", "status": "ReadyForPost",
            "auto_draft": auto_draft_result,
        }

    # Actually post to BC
    try:
        from routers.gpi_integration import create_purchase_invoice_from_document
        result = await create_purchase_invoice_from_document(doc_id, vendor_no_override="", force=False)

        if result.get("success") or result.get("already_exists"):
            now = datetime.now(timezone.utc).isoformat()
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "status": "Posted",
                "workflow_status": "posted",
                "auto_cleared": True,
                "auto_post_attempted": True,
                "auto_post_success": True,
                "bc_posting_status": "posted",
                "bc_record_no": result.get("bc_record_no", ""),
                "bc_system_id": result.get("bc_system_id", ""),
                "posted_to_bc_at": now,
                "updated_utc": now,
            }})
            await _write_event(db, doc_id, "automation.decision.completed", {
                "decision": "Posted",
                "auto_clear": True,
                "auto_post": True,
                "reason": f"Auto-posted to BC: PI #{result.get('bc_record_no', 'N/A')}",
                "source": source,
                "bc_record_no": result.get("bc_record_no"),
            })
            logger.info("[AP Auto-Post] SUCCESS for %s: BC PI #%s", doc_id[:8], result.get("bc_record_no"))

            # Auto-confirm: Record successful BC post as positive feedback
            await _record_success_feedback(db, doc_id, "Posted", source)

            return {
                "success": True, "posted": True,
                "reason": f"Posted to BC as PI #{result.get('bc_record_no')}",
                "status": "Posted",
                "bc_record_no": result.get("bc_record_no"),
                "bc_system_id": result.get("bc_system_id"),
            }
        else:
            error_msg = result.get("error", "Unknown BC API error")
            now = datetime.now(timezone.utc).isoformat()
            # Keep at ReadyForPost so the background scheduler can retry (transient BC failures)
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "status": "ReadyForPost",
                "workflow_status": "ready_for_post",
                "auto_post_attempted": True,
                "auto_post_success": False,
                "auto_post_error": error_msg,
                "bc_posting_status": "pending_retry",
                "updated_utc": now,
            }})
            await _write_event(db, doc_id, "automation.decision.completed", {
                "decision": "ReadyForPost",
                "auto_post": False,
                "reason": f"BC post failed (will retry): {error_msg}",
                "source": source,
            })
            logger.warning("[AP Auto-Post] BC post FAILED for %s (staying ReadyForPost for retry): %s", doc_id[:8], error_msg)
            return {"success": True, "posted": False, "reason": f"BC post failed: {error_msg}", "status": "ReadyForPost"}

    except Exception as e:
        error_msg = str(e)
        now = datetime.now(timezone.utc).isoformat()
        # Distinguish transient errors (keep ReadyForPost) from permanent errors (revert to NeedsReview)
        from fastapi import HTTPException as _HTTPException
        is_permanent = isinstance(e, _HTTPException) and e.status_code in (404, 422)
        if is_permanent:
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "status": "NeedsReview",
                "workflow_status": "needs_review",
                "auto_post_attempted": True,
                "auto_post_success": False,
                "auto_post_error": error_msg,
                "bc_posting_status": "failed",
                "updated_utc": now,
            }})
            await _write_event(db, doc_id, "automation.decision.completed", {
                "decision": "NeedsReview",
                "auto_post": False,
                "reason": f"BC post permanent error: {error_msg}",
                "source": source,
            })
            logger.error("[AP Auto-Post] Permanent error for %s → NeedsReview: %s", doc_id[:8], error_msg)
            return {"success": False, "posted": False, "reason": f"Error: {error_msg}", "status": "NeedsReview"}
        else:
            # Transient error — keep at ReadyForPost for background scheduler retry
            await db.hub_documents.update_one({"id": doc_id}, {"$set": {
                "status": "ReadyForPost",
                "workflow_status": "ready_for_post",
                "auto_post_attempted": True,
                "auto_post_success": False,
                "auto_post_error": error_msg,
                "bc_posting_status": "pending_retry",
                "updated_utc": now,
            }})
            await _write_event(db, doc_id, "automation.decision.completed", {
                "decision": "ReadyForPost",
                "auto_post": False,
                "reason": f"BC post transient error (will retry): {error_msg}",
                "source": source,
            })
            logger.warning("[AP Auto-Post] Transient error for %s → staying ReadyForPost: %s", doc_id[:8], error_msg)
            return {"success": False, "posted": False, "reason": f"Error (will retry): {error_msg}", "status": "ReadyForPost"}


async def _write_event(db, doc_id: str, event_type: str, payload: dict):
    """Write an event directly to MongoDB."""
    try:
        now = datetime.now(timezone.utc)
        await db.workflow_events.insert_one({
            "event_id": str(uuid.uuid4()),
            "document_id": doc_id,
            "event_type": "system.reprocessed",
            "timestamp": now.isoformat(),
            "source_service": "ap_auto_post_service",
            "payload": {"trigger": payload.get("source", "auto")},
        })
        await db.workflow_events.insert_one({
            "event_id": str(uuid.uuid4()),
            "document_id": doc_id,
            "event_type": event_type,
            "timestamp": (now + timedelta(milliseconds=100)).isoformat(),
            "source_service": "ap_auto_post_service",
            "payload": payload,
        })

        # Re-derive state
        try:
            from services.derived_state_service import get_derived_state_service, DerivedStateService
            dss = get_derived_state_service()
            if not dss:
                dss = DerivedStateService(db)
            await dss.update_document_derived_state(doc_id)
        except Exception:
            pass
    except Exception as e:
        logger.warning("[AP Auto-Post] Event write error: %s", e)


async def _record_success_feedback(db, doc_id: str, outcome: str, source: str):
    """
    Record successful automation as positive feedback.
    
    When a document reaches ReadyForPost or Posted, we know that:
    - The classification was correct
    - The extraction was correct
    - The vendor match was correct
    
    Store this as a confirmed-correct signal that the feedback loop
    can use to reinforce patterns.
    """
    try:
        doc = await db.hub_documents.find_one(
            {"id": doc_id},
            {"_id": 0, "doc_type": 1, "suggested_job_type": 1, "vendor_canonical": 1,
             "bc_vendor_number": 1, "filename": 1, "file_name": 1,
             "extracted_fields": 1, "classification_method": 1, "ai_confidence": 1}
        )
        if not doc:
            return

        now = datetime.now(timezone.utc).isoformat()
        doc_type = doc.get("doc_type") or doc.get("suggested_job_type") or ""
        vendor = doc.get("vendor_canonical") or doc.get("bc_vendor_number") or ""
        fname = doc.get("filename") or doc.get("file_name") or ""

        # Record as confirmed classification correction (positive)
        await db.classification_corrections.update_one(
            {"doc_id": doc_id, "source": "auto_confirm"},
            {"$set": {
                "doc_id": doc_id,
                "original_type": doc_type,
                "corrected_type": doc_type,  # Same = confirmed correct
                "corrected_by": "system_auto_confirm",
                "corrected_at": now,
                "file_name": fname,
                "vendor_raw": vendor,
                "vendor_canonical": vendor,
                "text_snippet": f"[auto-confirmed {outcome}] file={fname}",
                "classification_method": doc.get("classification_method", ""),
                "classification_confidence": doc.get("ai_confidence", 0),
                "source": "auto_confirm",
                "outcome": outcome,
                "auto_post_source": source,
            }},
            upsert=True,
        )

        # Also record vendor alias reinforcement if we have both canonical name and vendor no
        vendor_no = doc.get("bc_vendor_number", "")
        if vendor_no and vendor:
            await db.vendor_aliases.update_one(
                {"alias_string": vendor, "vendor_no": vendor_no},
                {
                    "$set": {
                        "alias_string": vendor,
                        "alias": vendor.upper(),
                        "normalized_alias": vendor.lower(),
                        "vendor_no": vendor_no,
                        "canonical_vendor_id": vendor_no,
                        "vendor_name": vendor,
                        "source": "auto_confirm",
                        "learned_at": now,
                    },
                    "$inc": {"confirm_count": 1},
                    "$setOnInsert": {"alias_id": str(uuid.uuid4())},
                },
                upsert=True,
            )

        logger.info("[AP Auto-Post] Recorded success feedback for %s (%s)", doc_id[:8], outcome)
    except Exception as e:
        logger.debug("[AP Auto-Post] Success feedback recording failed (non-blocking): %s", e)



# =============================================================================
# Phase 2: Confidence-Gated Auto-Draft PI Creation
# =============================================================================

async def _load_auto_post_settings(db) -> dict:
    """Load auto-post settings from DB."""
    settings = await db.auto_post_settings.find_one({"_id": "global"}) or {}
    return {
        "auto_post_enabled": settings.get("auto_post_enabled", False),
        "min_confidence": settings.get("min_confidence", "high"),
        "min_invoices_analyzed": settings.get("min_invoices_analyzed", 10),
        "require_po_match": settings.get("require_po_match", True),
        "allowed_vendors": settings.get("allowed_vendors", []),
        "blocked_vendors": settings.get("blocked_vendors", []),
    }


def _confidence_meets_threshold(confidence: str, min_confidence: str) -> bool:
    """Check if a confidence level meets or exceeds the minimum threshold."""
    return CONFIDENCE_LEVELS.get(confidence, 0) >= CONFIDENCE_LEVELS.get(min_confidence, 3)


async def check_auto_draft_eligibility(doc: dict, db) -> Dict:
    """
    Check if a ReadyForPost document qualifies for automatic draft PI creation.

    Returns:
        {
            "eligible": bool,
            "reason": str,
            "vendor_no": str,
            "template_confidence": str,
            "invoices_analyzed": int,
        }
    """
    doc_id = doc.get("id", "")
    vendor_no = doc.get("bc_vendor_number") or doc.get("vendor_no") or ""

    # Gate 1: Must have a vendor number
    if not vendor_no:
        return {"eligible": False, "reason": "No vendor number resolved", "vendor_no": "", "template_confidence": "none", "invoices_analyzed": 0}

    # Gate 2: Must not already have a draft PI
    if doc.get("bc_purchase_invoice"):
        existing_no = doc["bc_purchase_invoice"].get("bc_record_no", "?")
        return {"eligible": False, "reason": f"Draft PI already exists: {existing_no}", "vendor_no": vendor_no, "template_confidence": "n/a", "invoices_analyzed": 0}

    # Gate 2b: Cross-document duplicate check — another doc with same vendor+invoice already drafted?
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}
    invoice_number = ef.get("invoice_number") or nf.get("invoice_number") or doc.get("invoice_number_clean") or ""
    if invoice_number and vendor_no:
        existing_draft = await db.hub_documents.find_one(
            {
                "id": {"$ne": doc_id},
                "bc_purchase_invoice": {"$exists": True},
                "$and": [
                    {"$or": [
                        {"bc_vendor_number": vendor_no},
                        {"vendor_no": vendor_no},
                    ]},
                    {"$or": [
                        {"extracted_fields.invoice_number": invoice_number},
                        {"normalized_fields.invoice_number": invoice_number},
                        {"invoice_number_clean": invoice_number},
                    ]},
                ],
            },
            {"_id": 0, "id": 1, "bc_purchase_invoice.bc_record_no": 1},
        )
        if existing_draft:
            existing_bc = (existing_draft.get("bc_purchase_invoice") or {}).get("bc_record_no", "?")
            return {"eligible": False, "reason": f"Duplicate: another doc for vendor {vendor_no} / inv {invoice_number} already has PI {existing_bc}", "vendor_no": vendor_no, "template_confidence": "n/a", "invoices_analyzed": 0}

    # Gate 3: Load settings
    settings = await _load_auto_post_settings(db)
    if not settings["auto_post_enabled"]:
        return {"eligible": False, "reason": "Auto-post is disabled in settings", "vendor_no": vendor_no, "template_confidence": "n/a", "invoices_analyzed": 0}

    # Gate 4: Vendor not blocked
    if vendor_no in settings.get("blocked_vendors", []):
        return {"eligible": False, "reason": f"Vendor {vendor_no} is in blocked list", "vendor_no": vendor_no, "template_confidence": "n/a", "invoices_analyzed": 0}

    # Gate 5: If allowed_vendors is set, vendor must be in it
    allowed = settings.get("allowed_vendors", [])
    if allowed and vendor_no not in allowed:
        return {"eligible": False, "reason": f"Vendor {vendor_no} not in allowed list", "vendor_no": vendor_no, "template_confidence": "n/a", "invoices_analyzed": 0}

    # Gate 6: Load posting profile
    profile = await db.posting_pattern_analysis.find_one(
        {"vendor_no": vendor_no, "status": "analyzed"},
        {"_id": 0, "posting_template": 1, "invoices_analyzed": 1}
    )
    if not profile:
        return {"eligible": False, "reason": f"No posting profile for vendor {vendor_no}", "vendor_no": vendor_no, "template_confidence": "none", "invoices_analyzed": 0}

    template = profile.get("posting_template", {})
    confidence = template.get("confidence", "low")
    invoices_analyzed = profile.get("invoices_analyzed", 0)

    # Gate 7: Confidence threshold
    if not _confidence_meets_threshold(confidence, settings["min_confidence"]):
        return {"eligible": False, "reason": f"Template confidence '{confidence}' below threshold '{settings['min_confidence']}'", "vendor_no": vendor_no, "template_confidence": confidence, "invoices_analyzed": invoices_analyzed}

    # Gate 8: Minimum invoices analyzed
    if invoices_analyzed < settings["min_invoices_analyzed"]:
        return {"eligible": False, "reason": f"Only {invoices_analyzed} invoices analyzed (need {settings['min_invoices_analyzed']})", "vendor_no": vendor_no, "template_confidence": confidence, "invoices_analyzed": invoices_analyzed}

    return {
        "eligible": True,
        "reason": f"All gates passed: {confidence} confidence, {invoices_analyzed} invoices analyzed",
        "vendor_no": vendor_no,
        "template_confidence": confidence,
        "invoices_analyzed": invoices_analyzed,
    }


async def attempt_auto_draft_pi(doc_id: str, db, source: str = "confidence_gate") -> Dict:
    """
    Attempt to automatically create a DRAFT Purchase Invoice for a ReadyForPost document.

    This is the Phase 2 confidence gate:
    1. Check eligibility (settings, vendor profile, confidence threshold)
    2. If eligible, create a DRAFT PI using the learned posting template
    3. Record the result as an event

    SAFETY: Only creates DRAFT Purchase Invoices. Never posts to the ledger.

    Returns: {success, drafted, reason, bc_record_no, eligibility}
    """
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"success": False, "drafted": False, "reason": "Document not found"}

    # Check eligibility
    eligibility = await check_auto_draft_eligibility(doc, db)

    if not eligibility["eligible"]:
        logger.debug("[Auto-Draft] Skipped %s: %s", doc_id[:8], eligibility["reason"])
        return {
            "success": True,
            "drafted": False,
            "reason": eligibility["reason"],
            "eligibility": eligibility,
        }

    # Eligible — create the draft PI
    logger.info("[Auto-Draft] Creating draft PI for %s (vendor=%s, confidence=%s)",
                doc_id[:8], eligibility["vendor_no"], eligibility["template_confidence"])

    try:
        from routers.gpi_integration import create_purchase_invoice_from_document
        result = await create_purchase_invoice_from_document(doc_id, vendor_no_override="", force=False)

        if result.get("success") or result.get("already_exists"):
            bc_record_no = result.get("bc_record_no", "")
            now = datetime.now(timezone.utc).isoformat()

            # Tag the document as auto-drafted
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "auto_draft_created": True,
                    "auto_draft_source": source,
                    "auto_draft_at": now,
                    "auto_draft_confidence": eligibility["template_confidence"],
                    "auto_draft_bc_record_no": bc_record_no,
                }}
            )

            # Record event
            await _write_event(db, doc_id, "auto_draft.pi.created", {
                "bc_record_no": bc_record_no,
                "vendor_no": eligibility["vendor_no"],
                "confidence": eligibility["template_confidence"],
                "invoices_analyzed": eligibility["invoices_analyzed"],
                "source": source,
            })

            logger.info("[Auto-Draft] SUCCESS: Draft PI %s for %s", bc_record_no, doc_id[:8])
            return {
                "success": True,
                "drafted": True,
                "reason": f"Draft PI {bc_record_no} created automatically",
                "bc_record_no": bc_record_no,
                "already_exists": result.get("already_exists", False),
                "eligibility": eligibility,
            }
        else:
            error_msg = result.get("error_message") or result.get("error") or "Unknown error"
            logger.warning("[Auto-Draft] BC creation failed for %s: %s", doc_id[:8], error_msg)
            return {
                "success": True,
                "drafted": False,
                "reason": f"BC draft creation failed: {error_msg}",
                "eligibility": eligibility,
            }

    except Exception as e:
        logger.error("[Auto-Draft] Exception for %s: %s", doc_id[:8], str(e))
        return {
            "success": False,
            "drafted": False,
            "reason": f"Error: {str(e)}",
            "eligibility": eligibility,
        }


async def process_auto_draft_queue(db, limit: int = 50) -> Dict:
    """
    Process all ReadyForPost documents through the confidence gate.
    Creates draft PIs for qualifying documents.

    Returns summary: {processed, drafted, skipped, errors, details}
    """
    settings = await _load_auto_post_settings(db)
    if not settings["auto_post_enabled"]:
        return {
            "processed": 0, "drafted": 0, "skipped": 0, "errors": 0,
            "reason": "Auto-post is disabled",
            "details": [],
        }

    # Find ReadyForPost documents without existing drafts
    docs = await db.hub_documents.find(
        {
            "$or": [
                {"status": "ReadyForPost"},
                {"workflow_status": "ready_for_post"},
            ],
            "bc_purchase_invoice": {"$exists": False},
        },
        {"_id": 0, "id": 1, "bc_vendor_number": 1, "vendor_no": 1}
    ).limit(limit).to_list(limit)

    results = {"processed": 0, "drafted": 0, "skipped": 0, "errors": 0, "details": []}

    for doc_stub in docs:
        doc_id = doc_stub.get("id", "")
        if not doc_id:
            continue

        results["processed"] += 1
        try:
            result = await attempt_auto_draft_pi(doc_id, db, source="batch_queue")
            if result.get("drafted"):
                results["drafted"] += 1
            else:
                results["skipped"] += 1
            results["details"].append({
                "doc_id": doc_id[:8],
                "vendor_no": doc_stub.get("bc_vendor_number") or doc_stub.get("vendor_no", ""),
                "drafted": result.get("drafted", False),
                "reason": result.get("reason", ""),
                "bc_record_no": result.get("bc_record_no", ""),
            })
        except Exception as e:
            results["errors"] += 1
            results["details"].append({
                "doc_id": doc_id[:8],
                "error": str(e),
            })

    logger.info("[Auto-Draft Queue] Processed %d: drafted=%d, skipped=%d, errors=%d",
                results["processed"], results["drafted"], results["skipped"], results["errors"])
    return results