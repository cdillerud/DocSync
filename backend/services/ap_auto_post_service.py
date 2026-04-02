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
"""

import logging
import uuid
from datetime import datetime, timezone, timedelta
from typing import Dict, Tuple

logger = logging.getLogger(__name__)


def check_ap_ready_to_post(doc: dict, vendor_profile: dict = None, source: str = "auto") -> Tuple[bool, str, list]:
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
    invoice_no = ef.get("invoice_number") or nf.get("invoice_number") or doc.get("invoice_number_clean") or ""
    amount = ef.get("amount") or nf.get("amount") or doc.get("amount_float")
    invoice_date = ef.get("invoice_date") or nf.get("invoice_date") or ""
    vendor_raw = ef.get("vendor") or nf.get("vendor") or ""

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
    vp = vendor_profile or {}
    po_expected = vp.get("po_expected", True)
    
    if has_manual_override:
        logger.info("[AP Auto-Post] PO check SKIPPED — manual override set by reviewer")
    elif is_human_action:
        logger.info("[AP Auto-Post] PO check SKIPPED — human review action (%s)", source)
    elif not po_expected:
        logger.info("[AP Auto-Post] PO check SKIPPED for vendor %s — BC history shows PO never expected", vendor_no)
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
    if vendor_no:
        try:
            from services.vendor_invoice_profile_service import get_or_build_profile
            vendor_profile = await get_or_build_profile(db, vendor_no)
        except Exception as vp_err:
            logger.warning("[AP Auto-Post] Could not load vendor profile for %s: %s", vendor_no, vp_err)

    ready, reason, failures = check_ap_ready_to_post(doc, vendor_profile=vendor_profile, source=source)

    if not ready:
        # Set to NeedsReview
        now = datetime.now(timezone.utc).isoformat()
        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "status": "NeedsReview",
            "workflow_status": "needs_review",
            "auto_cleared": False,
            "auto_post_attempted": True,
            "auto_post_reason": reason,
            "auto_post_failures": failures,
            "updated_utc": now,
        }})

        # Write event
        await _write_event(db, doc_id, "automation.decision.completed", {
            "decision": "NeedsReview",
            "auto_clear": False,
            "auto_post": False,
            "reason": reason,
            "failures": failures,
            "source": source,
        })

        logger.info("[AP Auto-Post] NeedsReview for %s: %s", doc_id[:8], reason)
        return {"success": True, "posted": False, "reason": reason, "status": "NeedsReview", "failures": failures}

    # All conditions met — attempt to post to BC
    import os
    bc_write_enabled = os.environ.get("BC_WRITE_ENABLED", "false").lower() == "true"

    if not bc_write_enabled:
        # BC writes disabled — mark as ready but don't post
        now = datetime.now(timezone.utc).isoformat()
        await db.hub_documents.update_one({"id": doc_id}, {"$set": {
            "status": "ReadyForPost",
            "workflow_status": "ready_for_post",
            "auto_cleared": True,
            "auto_post_attempted": True,
            "auto_post_reason": "All checks passed but BC_WRITE_ENABLED=false",
            "updated_utc": now,
        }})
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

        return {"success": True, "posted": False, "reason": "BC writes disabled", "status": "ReadyForPost"}

    # Actually post to BC
    try:
        from routers.gpi_integration import create_purchase_invoice_from_document
        result = await create_purchase_invoice_from_document(doc_id)

        if result.get("success"):
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
                "reason": f"BC post failed: {error_msg}",
                "source": source,
            })
            logger.warning("[AP Auto-Post] BC post FAILED for %s: %s", doc_id[:8], error_msg)
            return {"success": True, "posted": False, "reason": f"BC post failed: {error_msg}", "status": "NeedsReview"}

    except Exception as e:
        error_msg = str(e)
        now = datetime.now(timezone.utc).isoformat()
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
            "reason": f"BC post error: {error_msg}",
            "source": source,
        })
        logger.error("[AP Auto-Post] Exception for %s: %s", doc_id[:8], error_msg)
        return {"success": False, "posted": False, "reason": f"Error: {error_msg}", "status": "NeedsReview"}


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
