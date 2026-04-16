"""
GPI Document Hub -- Pilot Readiness Review Service

Runs the SO Readiness Reviewer against pilot documents, comparing
extracted order data against the customer's BC Production posting profile.

This bridges the pilot pipeline with the learned customer intelligence:
  - Looks up the customer's posting profile from customer_posting_profiles
  - Builds an extracted_order dict from pilot extraction + main pipeline data
  - Calls review_sales_order_readiness() for LLM-assisted comparison
  - Stores the result as so_readiness_review on the document

Advisory only -- never writes to BC or changes workflow state.
"""

import logging
from datetime import datetime, timezone
from typing import Dict, Any

from deps import get_db

logger = logging.getLogger(__name__)


async def review_pilot_document(doc_id: str) -> Dict[str, Any]:
    """
    Run SO Readiness Review on a single pilot document.

    Returns the review result dict.
    """
    db = get_db()
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        return {"error": f"Document {doc_id} not found"}

    ext = doc.get("sales_pilot_extraction") or {}
    ef = doc.get("extracted_fields") or {}
    nf = doc.get("normalized_fields") or {}

    # ---- Resolve customer ----
    customer_name = ext.get("customer_name") or ef.get("customer") or nf.get("customer")
    customer_no = (
        ext.get("customer_no")
        or doc.get("matched_customer_no")
        or doc.get("customer_no")
        or nf.get("customer_no")
    )

    # Also try BC validation for customer_no
    bc_val = doc.get("bc_prod_validation") or {}
    bc_cm = bc_val.get("customer_match") or {}
    if not customer_no and bc_cm.get("found"):
        customer_no = bc_cm.get("bc_customer_no")

    # Also try Spiro match external_id (this IS the BC customer number)
    spiro = doc.get("spiro_match") or {}
    spiro_cm = spiro.get("company_match") or {}
    if not customer_no and spiro_cm.get("external_id"):
        customer_no = spiro_cm["external_id"]

    # Also try vendor_canonical from the main pipeline
    if not customer_no:
        vc = doc.get("vendor_canonical") or ""
        if vc and "gamer" not in vc.lower():
            # vendor_canonical might be a BC customer number or name
            # Try direct lookup in profiles
            candidate = await db.customer_posting_profiles.find_one(
                {"customer_no": vc, "status": "analyzed"}, {"_id": 0, "customer_no": 1}
            )
            if candidate:
                customer_no = candidate["customer_no"]

    # ---- Look up customer posting profile ----
    customer_profile = None
    if customer_no:
        customer_profile = await db.customer_posting_profiles.find_one(
            {"customer_no": customer_no, "status": "analyzed"}, {"_id": 0}
        )

    # If no profile by customer_no, try fuzzy name match against profiles
    if not customer_profile and customer_name:
        import re
        safe_name = re.escape(customer_name.strip()[:30])
        # Try exact name match first
        try:
            customer_profile = await db.customer_posting_profiles.find_one(
                {
                    "status": "analyzed",
                    "$or": [
                        {"customer_name": {"$regex": safe_name, "$options": "i"}},
                        {"customer_no": {"$regex": safe_name[:8], "$options": "i"}},
                    ],
                },
                {"_id": 0},
            )
        except Exception:
            pass

        # Try first significant word (e.g., "COMAR" from "Comar Inc.")
        if not customer_profile:
            words = customer_name.strip().split()
            first_word = words[0] if words else ""
            if first_word and len(first_word) >= 3:
                safe_word = re.escape(first_word)
                try:
                    customer_profile = await db.customer_posting_profiles.find_one(
                        {
                            "status": "analyzed",
                            "$or": [
                                {"customer_name": {"$regex": f"^{safe_word}", "$options": "i"}},
                                {"customer_no": {"$regex": f"^{safe_word[:6]}", "$options": "i"}},
                            ],
                        },
                        {"_id": 0},
                    )
                except Exception:
                    pass

        # Try searching bc_reference_cache to bridge name → customer_no → profile
        if not customer_profile and customer_name:
            safe_name_short = re.escape(customer_name.strip()[:20])
            try:
                bc_hit = await db.bc_reference_cache.find_one(
                    {
                        "bc_entity_type": "customer",
                        "$or": [
                            {"bc_customer_name": {"$regex": safe_name_short, "$options": "i"}},
                            {"displayName": {"$regex": safe_name_short, "$options": "i"}},
                        ],
                    },
                    {"_id": 0, "bc_customer_no": 1},
                )
                if bc_hit and bc_hit.get("bc_customer_no"):
                    customer_no = bc_hit["bc_customer_no"]
                    customer_profile = await db.customer_posting_profiles.find_one(
                        {"customer_no": customer_no, "status": "analyzed"}, {"_id": 0}
                    )
            except Exception:
                pass

    # ---- Build extracted order from pilot data ----
    line_items = nf.get("line_items") or doc.get("line_items") or []
    amount = (
        doc.get("amount_float")
        or ext.get("total_amount")
        or nf.get("amount_float")
        or ef.get("total_amount")
    )

    extracted_order = {
        "customer_name": customer_name,
        "customer_number": customer_no,
        "order_number": ext.get("order_number") or ef.get("order_number"),
        "po_number": ext.get("po_number") or nf.get("customer_po") or ef.get("po_number"),
        "order_date": ef.get("order_date") or nf.get("invoice_date"),
        "ship_to_name": ext.get("ship_to") or nf.get("ship_to") or ef.get("ship_to"),
        "total_amount": amount,
        "line_items": line_items,
    }

    document_context = {
        "doc_id": doc_id,
        "doc_type": doc.get("doc_type"),
        "file_name": doc.get("file_name"),
        "email_sender": doc.get("email_sender"),
        "pilot_mailbox": doc.get("pilot_mailbox"),
    }

    # ---- Run the readiness reviewer ----
    try:
        from services.sales_order_readiness_reviewer import review_sales_order_readiness

        review = await review_sales_order_readiness(
            extracted_order=extracted_order,
            customer_profile=customer_profile,
            validation_results=doc.get("validation_results"),
            document_context=document_context,
        )

        result = review.to_dict()

        # Enrich with pilot-specific context
        result["pilot_context"] = {
            "customer_name": customer_name,
            "customer_no": customer_no,
            "profile_found": customer_profile is not None,
            "profile_customer_no": customer_profile.get("customer_no") if customer_profile else None,
            "profile_customer_name": customer_profile.get("customer_name") if customer_profile else None,
            "profile_order_count": customer_profile.get("total_orders") if customer_profile else None,
            "extraction_quality_pct": ext.get("extraction_quality_pct"),
        }

        # Persist on document
        await db.hub_documents.update_one(
            {"id": doc_id},
            {"$set": {"so_readiness_review": result}},
        )

        logger.info(
            "[PilotReadiness] doc=%s customer=%s profile=%s status=%s confidence=%.2f",
            doc_id[:8], customer_name or "?", "found" if customer_profile else "none",
            review.readiness_status, review.confidence,
        )
        return result

    except Exception as e:
        logger.error("[PilotReadiness] Error reviewing %s: %s", doc_id[:8], e)
        return {
            "error": str(e),
            "document_id": doc_id,
            "customer_name": customer_name,
            "profile_found": customer_profile is not None,
        }


async def review_all_pilot_documents(force: bool = False) -> Dict[str, Any]:
    """
    Run SO Readiness Review on all pilot sales documents.

    Only reviews docs classified as sales types (SALES_INVOICE, Sales_Order, etc.)
    that haven't been reclassified.

    Args:
        force: If True, re-reviews ALL docs. Otherwise only unreviewed.
    """
    db = get_db()

    query: Dict[str, Any] = {
        "inside_sales_pilot": True,
        "doc_type": {"$in": ["SALES_INVOICE", "Sales_Order", "Order_Confirmation"]},
        "reclassified_from": {"$exists": False},
    }
    if not force:
        query["$or"] = [
            {"so_readiness_review": {"$exists": False}},
            {"so_readiness_review": None},
        ]

    docs = await db.hub_documents.find(
        query, {"_id": 0, "id": 1, "file_name": 1}
    ).to_list(500)

    results: Dict[str, Any] = {
        "total": len(docs),
        "reviewed": 0,
        "errors": 0,
        "with_profile": 0,
        "without_profile": 0,
        "statuses": {},
    }

    for doc in docs:
        try:
            r = await review_pilot_document(doc["id"])
            if r.get("error"):
                results["errors"] += 1
                continue

            results["reviewed"] += 1

            # Track profile availability
            pc = r.get("pilot_context") or {}
            if pc.get("profile_found"):
                results["with_profile"] += 1
            else:
                results["without_profile"] += 1

            # Track status distribution
            status = r.get("readiness_status", "unknown")
            results["statuses"][status] = results["statuses"].get(status, 0) + 1

        except Exception as e:
            results["errors"] += 1
            logger.error("[PilotReadiness] Error on %s: %s", doc["id"][:8], e)

    logger.info(
        "[PilotReadiness] Batch complete: %d/%d reviewed, profiles=%d/%d, errors=%d",
        results["reviewed"], results["total"],
        results["with_profile"], results["reviewed"],
        results["errors"],
    )
    return results
