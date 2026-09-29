"""
Sales Rep Auto-Assignment Pipeline Step

After a document is classified and customer is resolved, this service
determines if the document is sales-eligible and auto-assigns it to
the correct sales rep based on customer → rep mappings.

Routing outcomes:
  - pending_rep_review : Assigned to a rep, awaiting their review
  - auto_approved      : High confidence + known rep → auto-create BC SO
  - triage             : No rep found → needs manual assignment

This follows the "learn, apply, improve" philosophy:
  - Uses ALL available data: BC cache, overrides, sender mappings
  - Creates audit trail in sales_review_history
"""

import logging
from datetime import datetime, timezone
from typing import Optional

from services.rep_assignment_service import (
    get_rep_for_customer,
    get_rep_for_customer_name,
    get_rep_from_document_history,
)

logger = logging.getLogger(__name__)

SALES_ELIGIBLE_TYPES = {
    "Sales_Order", "SalesOrder", "Order_Confirmation", "PurchaseOrder", "Purchase_Order",
    "AR_Invoice", "Sales_Quote", "PURCHASE_ORDER", "Purchase Order",
}

# High-confidence threshold for auto-approval (skip rep review)
AUTO_APPROVE_CONFIDENCE = 0.95


async def auto_assign_sales_rep(db, doc_id: str, doc: dict) -> Optional[dict]:
    """Auto-assign a sales rep to a document if it is sales-eligible.

    Args:
        db: Motor database instance
        doc_id: Document ID
        doc: Document dict (must include document_type, extracted_fields, normalized_fields, ai_confidence)

    Returns:
        dict with assignment result, or None if not sales-eligible.
    """
    doc_type = doc.get("document_type") or doc.get("suggested_job_type") or ""
    if doc_type not in SALES_ELIGIBLE_TYPES:
        return None

    now = datetime.now(timezone.utc).isoformat()
    confidence = doc.get("ai_confidence") or 0.0
    extracted = doc.get("extracted_fields") or {}
    normalized = doc.get("normalized_fields") or {}

    # Try to find the customer number from all available sources
    customer_no = (
        normalized.get("bc_customer_no")
        or extracted.get("bc_customer_no")
        or extracted.get("customer_no")
        or ""
    )

    customer_name = (
        normalized.get("customer_name")
        or extracted.get("customer_name")
        or extracted.get("customer")
        or extracted.get("company_name")
        or extracted.get("bill_to_name")
        or extracted.get("ship_to_name")
        or doc.get("vendor_name")
        or doc.get("vendor_canonical")
        or ""
    )

    rep_result = None
    if customer_no:
        rep_result = await get_rep_for_customer(db, customer_no)

    # If no rep from customer_no, try by customer name match in overrides
    if not rep_result and customer_name:
        import re
        escaped_name = re.escape(customer_name)
        override = await db.customer_rep_overrides.find_one(
            {"customer_name": {"$regex": f"^{escaped_name}$", "$options": "i"}, "active": True},
            {"_id": 0},
        )
        if override:
            rep_result = {
                "rep_email": override.get("rep_email", ""),
                "rep_name": override.get("rep_name", ""),
                "salesperson_code": override.get("salesperson_code", ""),
                "source": "override_name_match",
            }

    # Manual overrides are a tiny curated list (~12 entries). Most real pilot
    # documents only ever extract a free-text customer name (never a
    # bc_customer_no), so the richer path is an exact name match against the
    # full BC reference cache (2300 customers, ~2298 with a salesperson_code)
    # rather than the override table. Tried before override fuzzy matching
    # since an exact BC match is more reliable than a first-word guess.
    if not rep_result and customer_name:
        rep_result = await get_rep_for_customer_name(db, customer_name, fuzzy=False)
        if rep_result:
            rep_result = {**rep_result, "source": "bc_cache_name_match"}

    # 2026-09-29: before falling to weaker fuzzy matching, check whether
    # ANOTHER document with this exact customer name already got a
    # confirmed rep assignment (pending_rep_review/auto_approved). This is
    # the "learning" counterpart to the BC-cache exact match above — it's
    # what lets today's resolutions compound forward: once a customer name
    # resolves once, every future document with that same name resolves
    # instantly without re-running fuzzy matching, mirroring the pattern
    # unified_vendor_matcher.py already used for vendor resolution. Guarded
    # by vendor_identity_agrees so a loose/wrong prior assignment can't
    # propagate.
    if not rep_result and customer_name:
        rep_result = await get_rep_from_document_history(db, customer_name)

    # If still no rep, try partial/fuzzy name match against overrides
    if not rep_result and customer_name and len(customer_name) >= 4:
        import re
        # Try substring match (e.g. "Bragg" matching "Bragg Live Food Products, LLC")
        first_word = customer_name.split()[0] if customer_name.split() else ""
        if first_word and len(first_word) >= 3:
            escaped_word = re.escape(first_word)
            override = await db.customer_rep_overrides.find_one(
                {"customer_name": {"$regex": escaped_word, "$options": "i"}, "active": True},
                {"_id": 0},
            )
            if override:
                rep_result = {
                    "rep_email": override.get("rep_email", ""),
                    "rep_name": override.get("rep_name", ""),
                    "salesperson_code": override.get("salesperson_code", ""),
                    "source": "override_partial_match",
                }

    # Fuzzy (first-word substring) name match against the full BC cache —
    # same technique as above but against the 2300-customer cache instead
    # of the 12-entry override table. Tried after the override fuzzy match
    # since a curated manual override should still win when both exist.
    if not rep_result and customer_name and len(customer_name) >= 4:
        rep_result = await get_rep_for_customer_name(db, customer_name, fuzzy=True)
        if rep_result:
            rep_result = {**rep_result, "source": "bc_cache_name_fuzzy_match"}

    # Last resort: try sender email domain → known customer mapping
    if not rep_result:
        sender_email = doc.get("email_sender") or ""
        if sender_email and "@" in sender_email:
            import re
            domain = sender_email.split("@")[1].lower()
            domain_base = domain.split(".")[0]  # e.g. "giovannifoods" from "giovannifoods.com"
            if domain_base and len(domain_base) >= 3:
                # Strategy 1: Full domain base match (e.g. "bragg" in "Bragg Live Food...")
                escaped_domain = re.escape(domain_base)
                override = await db.customer_rep_overrides.find_one(
                    {"customer_name": {"$regex": escaped_domain, "$options": "i"}, "active": True},
                    {"_id": 0},
                )
                # Strategy 2: Check if customer name's first word is IN the domain
                # e.g. "giovanni" (from "Giovanni Food Co.") is in "giovannifoods"
                # Pick the longest match to avoid false positives ("foods" matching multiple)
                if not override:
                    all_overrides = await db.customer_rep_overrides.find(
                        {"active": True}, {"_id": 0}
                    ).to_list(500)
                    best_match = None
                    best_match_len = 0
                    for ov in all_overrides:
                        cust_name = (ov.get("customer_name") or "").lower()
                        cust_words = [w for w in re.split(r'[\s,.\-]+', cust_name) if len(w) >= 3]
                        for word in cust_words:
                            match_len = 0
                            if word in domain_base:
                                match_len = len(word)
                            elif domain_base in word:
                                match_len = len(domain_base)
                            if match_len > best_match_len:
                                best_match = ov
                                best_match_len = match_len
                    # Only accept if the match covers a significant portion of the domain
                    if best_match and best_match_len >= min(5, len(domain_base) * 0.5):
                        override = best_match

                if override:
                    rep_result = {
                        "rep_email": override.get("rep_email", ""),
                        "rep_name": override.get("rep_name", ""),
                        "salesperson_code": override.get("salesperson_code", ""),
                        "source": "sender_domain_match",
                    }

    # Determine routing
    if rep_result and rep_result.get("rep_email"):
        # We have a rep — decide between pending_rep_review and auto_approved
        if confidence >= AUTO_APPROVE_CONFIDENCE:
            review_status = "auto_approved"
        else:
            review_status = "pending_rep_review"

        update_fields = {
            "assigned_rep_email": rep_result["rep_email"],
            "assigned_rep_name": rep_result.get("rep_name", ""),
            "assigned_salesperson_code": rep_result.get("salesperson_code", ""),
            "sales_review_status": review_status,
            "rep_assignment_source": rep_result.get("source", ""),
            "rep_assigned_utc": now,
            "updated_utc": now,
        }

        history_entry = {
            "action": "auto_assigned",
            "at": now,
            "by": "system",
            "rep_email": rep_result["rep_email"],
            "rep_name": rep_result.get("rep_name", ""),
            "source": rep_result.get("source", ""),
            "review_status": review_status,
            "confidence": confidence,
        }

        await db.hub_documents.update_one(
            {"id": doc_id},
            {
                "$set": update_fields,
                "$push": {"sales_review_history": history_entry},
            },
        )

        logger.info(
            "[SalesAutoAssign] Doc %s → %s (%s) status=%s conf=%.2f source=%s",
            doc_id[:8], rep_result["rep_email"], rep_result.get("rep_name"),
            review_status, confidence, rep_result.get("source"),
        )

        return {
            "assigned": True,
            "rep_email": rep_result["rep_email"],
            "rep_name": rep_result.get("rep_name", ""),
            "review_status": review_status,
            "source": rep_result.get("source", ""),
        }
    else:
        # No rep found → triage
        update_fields = {
            "assigned_rep_email": "",
            "assigned_rep_name": "",
            "sales_review_status": "triage",
            "rep_assigned_utc": None,
            "updated_utc": now,
        }

        history_entry = {
            "action": "routed_to_triage",
            "at": now,
            "by": "system",
            "reason": "no_rep_found",
            "customer_no": customer_no,
            "customer_name": customer_name,
        }

        await db.hub_documents.update_one(
            {"id": doc_id},
            {
                "$set": update_fields,
                "$push": {"sales_review_history": history_entry},
            },
        )

        logger.info(
            "[SalesAutoAssign] Doc %s → TRIAGE (no rep for customer_no=%s name=%s)",
            doc_id[:8], customer_no, customer_name[:30] if customer_name else "",
        )

        return {
            "assigned": False,
            "rep_email": "",
            "rep_name": "",
            "review_status": "triage",
            "source": "no_rep_found",
        }
