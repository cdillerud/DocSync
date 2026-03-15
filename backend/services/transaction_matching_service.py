"""
GPI Document Hub - Transaction Matching Service

Matches incoming documents to existing drafts/transactions before creating new ones.
Strategy: exact reference → entity+reference combo → entity+amount/date → ambiguous list.

SAFETY: Never auto-link ambiguous matches. Only auto-link single high-confidence winners.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from deps import get_db

logger = logging.getLogger(__name__)

MATCHES_COLLECTION = "transaction_matches"
INTELLIGENCE_COLLECTION = "document_intelligence_results"
ACTIVITIES_COLLECTION = "activities"

# Confidence thresholds
HIGH_CONFIDENCE = 0.90
MEDIUM_CONFIDENCE = 0.70

# Match statuses
STATUS_MATCHED = "matched"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_UNMATCHED = "unmatched"
STATUS_CONFIRMED = "confirmed"
STATUS_REJECTED = "rejected"

# Document type → target entity type mapping
DOC_TYPE_TARGETS = {
    "Sales_PO": ["sales_order_draft", "sales_order"],
    "customer_po": ["sales_order_draft", "sales_order"],
    "AP_Invoice": ["ap_intake_draft", "invoice"],
    "invoice": ["ap_intake_draft", "invoice"],
    "Freight_Document": ["po_draft", "purchase_order"],
    "Shipping_Document": ["po_draft", "purchase_order"],
    "vendor_po_support": ["po_draft", "purchase_order"],
}


async def _create_activity(db, entity_id, activity_type, title, body="", metadata=None):
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "activity_id": f"ACT-{uuid.uuid4().hex[:8].upper()}",
        "entity_type": "document",
        "entity_id": entity_id,
        "activity_type": activity_type,
        "title": title,
        "body": body,
        "created_by": "system",
        "created_at": now,
        "metadata": metadata or {},
    }
    await db[ACTIVITIES_COLLECTION].insert_one(record.copy())
    record.pop("_id", None)
    return record


async def _search_so_drafts(db, fields: Dict, resolved: List[Dict]) -> List[Dict]:
    """Search SO drafts by PO number, customer name."""
    candidates = []
    po = fields.get("po_number") or fields.get("order_number") or fields.get("customer_po") or ""
    customer = fields.get("customer") or fields.get("consignee") or fields.get("customer_name") or ""

    # Exact PO number match
    if po:
        cursor = db.so_drafts.find(
            {"customer_po_number": {"$regex": f"^{_esc(po)}$", "$options": "i"}},
            {"_id": 0},
        )
        for doc in await cursor.to_list(10):
            candidates.append(_build_candidate(
                entity_type="sales_order_draft",
                entity_id=doc["so_draft_id"],
                display=f"SO Draft: {doc['so_draft_id']} — {doc.get('customer_name', '')} (PO: {doc.get('customer_po_number', '')})",
                basis=f"po_number_exact: {po}",
                confidence=0.95,
                raw=doc,
            ))

    # Customer + date combo
    if customer and not candidates:
        cursor = db.so_drafts.find(
            {"customer_name": {"$regex": _esc(customer), "$options": "i"}},
            {"_id": 0},
        )
        for doc in await cursor.to_list(10):
            candidates.append(_build_candidate(
                entity_type="sales_order_draft",
                entity_id=doc["so_draft_id"],
                display=f"SO Draft: {doc['so_draft_id']} — {doc.get('customer_name', '')}",
                basis=f"customer_name: {customer}",
                confidence=0.70,
                raw=doc,
            ))

    return candidates


async def _search_po_drafts(db, fields: Dict, resolved: List[Dict]) -> List[Dict]:
    """Search PO drafts by reference, vendor."""
    candidates = []
    po = fields.get("po_number") or fields.get("bol_number") or fields.get("pro_number") or ""
    vendor = fields.get("vendor") or fields.get("shipper") or fields.get("carrier") or ""

    if po:
        cursor = db.po_drafts.find(
            {"$or": [
                {"source_reference": {"$regex": f"^{_esc(po)}$", "$options": "i"}},
                {"po_draft_id": {"$regex": _esc(po), "$options": "i"}},
            ]},
            {"_id": 0},
        )
        for doc in await cursor.to_list(10):
            candidates.append(_build_candidate(
                entity_type="po_draft",
                entity_id=doc["po_draft_id"],
                display=f"PO Draft: {doc['po_draft_id']} — {doc.get('vendor_name', '')}",
                basis=f"reference_exact: {po}",
                confidence=0.95,
                raw=doc,
            ))

    if vendor and not candidates:
        cursor = db.po_drafts.find(
            {"vendor_name": {"$regex": _esc(vendor), "$options": "i"}},
            {"_id": 0},
        )
        for doc in await cursor.to_list(10):
            candidates.append(_build_candidate(
                entity_type="po_draft",
                entity_id=doc["po_draft_id"],
                display=f"PO Draft: {doc['po_draft_id']} — {doc.get('vendor_name', '')}",
                basis=f"vendor_name: {vendor}",
                confidence=0.65,
                raw=doc,
            ))

    return candidates


async def _search_ap_drafts(db, fields: Dict, resolved: List[Dict]) -> List[Dict]:
    """Search AP intake drafts by invoice number, vendor, amount."""
    candidates = []
    inv = fields.get("invoice_number") or fields.get("invoice_no") or ""
    vendor = fields.get("vendor") or fields.get("vendor_name") or ""
    amount = fields.get("amount") or fields.get("invoice_amount") or fields.get("total") or ""

    if inv:
        cursor = db.ap_intake_drafts.find(
            {"invoice_number": {"$regex": f"^{_esc(inv)}$", "$options": "i"}},
            {"_id": 0},
        )
        for doc in await cursor.to_list(10):
            conf = 0.95
            # Boost if amount also matches
            if amount and doc.get("invoice_amount"):
                try:
                    if abs(float(str(amount).replace(",", "").replace("$", "")) - float(doc["invoice_amount"])) < 0.01:
                        conf = 0.99
                except (ValueError, TypeError):
                    pass
            candidates.append(_build_candidate(
                entity_type="ap_intake_draft",
                entity_id=doc["ap_draft_id"],
                display=f"AP Draft: {doc['ap_draft_id']} — {doc.get('vendor_name', '')} (Inv: {doc.get('invoice_number', '')})",
                basis=f"invoice_number_exact: {inv}",
                confidence=conf,
                raw=doc,
            ))

    # Vendor + amount fallback
    if vendor and amount and not candidates:
        try:
            amt_float = float(str(amount).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            amt_float = None

        if amt_float is not None:
            cursor = db.ap_intake_drafts.find(
                {"vendor_name": {"$regex": _esc(vendor), "$options": "i"}},
                {"_id": 0},
            )
            for doc in await cursor.to_list(20):
                doc_amt = doc.get("invoice_amount", 0)
                try:
                    doc_amt = float(doc_amt)
                except (ValueError, TypeError):
                    continue
                if abs(doc_amt - amt_float) < 0.01:
                    candidates.append(_build_candidate(
                        entity_type="ap_intake_draft",
                        entity_id=doc["ap_draft_id"],
                        display=f"AP Draft: {doc['ap_draft_id']} — {doc.get('vendor_name', '')} (${doc_amt:.2f})",
                        basis=f"vendor_amount: {vendor} + ${amt_float:.2f}",
                        confidence=0.85,
                        raw=doc,
                    ))

    return candidates


async def _search_linked_documents(db, fields: Dict, doc_type: str) -> List[Dict]:
    """Search hub_documents for documents already linked to transactions with same references."""
    candidates = []
    po = fields.get("po_number") or fields.get("order_number") or ""
    inv = fields.get("invoice_number") or ""

    query_parts = []
    if po:
        query_parts.append({"po_number_clean": {"$regex": f"^{_esc(po)}$", "$options": "i"}})
    if inv:
        query_parts.append({"invoice_number_clean": {"$regex": f"^{_esc(inv)}$", "$options": "i"}})

    if not query_parts:
        return candidates

    cursor = db.hub_documents.find(
        {"$or": query_parts, "status": {"$in": ["Linked", "LinkedToBC", "AutoLinked"]}},
        {"_id": 0, "id": 1, "file_name": 1, "status": 1, "suggested_job_type": 1,
         "target_entity_type": 1, "target_entity_id": 1},
    )
    for doc in await cursor.to_list(5):
        if doc.get("target_entity_id"):
            candidates.append(_build_candidate(
                entity_type=doc.get("target_entity_type", "unknown"),
                entity_id=doc["target_entity_id"],
                display=f"Linked via: {doc.get('file_name', doc['id'])} → {doc['target_entity_id']}",
                basis=f"linked_document_reference",
                confidence=0.80,
                raw=doc,
            ))

    return candidates


def _build_candidate(entity_type, entity_id, display, basis, confidence, raw=None):
    return {
        "candidate_entity_type": entity_type,
        "candidate_entity_id": entity_id,
        "candidate_display_name": display,
        "match_basis": basis,
        "match_confidence": round(confidence, 3),
        "match_status": STATUS_MATCHED if confidence >= HIGH_CONFIDENCE else (STATUS_AMBIGUOUS if confidence >= MEDIUM_CONFIDENCE else STATUS_UNMATCHED),
        "is_selected": False,
    }


def _esc(s):
    """Escape regex special chars."""
    import re
    return re.escape(str(s).strip())


def _determine_overall_status(candidates: List[Dict]) -> Dict[str, Any]:
    """Determine overall match status from candidates."""
    if not candidates:
        return {"status": STATUS_UNMATCHED, "best_match": None, "auto_link_available": False}

    # Dedupe by entity_id
    seen = set()
    deduped = []
    for c in candidates:
        eid = c["candidate_entity_id"]
        if eid not in seen:
            seen.add(eid)
            deduped.append(c)
    candidates = sorted(deduped, key=lambda x: x["match_confidence"], reverse=True)

    best = candidates[0]

    if best["match_confidence"] >= HIGH_CONFIDENCE:
        # Check if there's a close second
        if len(candidates) > 1 and candidates[1]["match_confidence"] >= MEDIUM_CONFIDENCE:
            return {"status": STATUS_AMBIGUOUS, "best_match": best, "auto_link_available": False}
        return {"status": STATUS_MATCHED, "best_match": best, "auto_link_available": True}
    elif best["match_confidence"] >= MEDIUM_CONFIDENCE:
        return {"status": STATUS_AMBIGUOUS, "best_match": best, "auto_link_available": False}
    else:
        return {"status": STATUS_UNMATCHED, "best_match": None, "auto_link_available": False}


# ─── Public API ───────────────────────────────────────────────────────────────

async def match_transactions(doc_id: str) -> Dict[str, Any]:
    """Run transaction matching for a document. Returns candidates and overall status."""
    db = get_db()

    intel = await db[INTELLIGENCE_COLLECTION].find_one({"document_id": doc_id}, {"_id": 0})
    if not intel:
        raise ValueError(f"No intelligence result for document: {doc_id}. Run processing first.")

    fields = intel.get("extracted_fields", {})
    doc_type = intel.get("document_type", "")

    # Determine which collections to search
    targets = DOC_TYPE_TARGETS.get(doc_type, [])

    # Get entity resolution data for enrichment
    resolved = await db.entity_resolutions.find({"document_id": doc_id}, {"_id": 0}).to_list(20)

    candidates = []

    # Search based on document type
    if any(t in ("sales_order_draft", "sales_order") for t in targets):
        candidates.extend(await _search_so_drafts(db, fields, resolved))

    if any(t in ("po_draft", "purchase_order") for t in targets):
        candidates.extend(await _search_po_drafts(db, fields, resolved))

    if any(t in ("ap_intake_draft", "invoice") for t in targets):
        candidates.extend(await _search_ap_drafts(db, fields, resolved))

    # Also search linked documents for cross-references
    candidates.extend(await _search_linked_documents(db, fields, doc_type))

    # Deduplicate
    seen = set()
    unique = []
    for c in candidates:
        key = f"{c['candidate_entity_type']}:{c['candidate_entity_id']}"
        if key not in seen:
            seen.add(key)
            unique.append(c)
    candidates = sorted(unique, key=lambda x: x["match_confidence"], reverse=True)

    overall = _determine_overall_status(candidates)
    now = datetime.now(timezone.utc).isoformat()

    # Delete old matches, store new ones
    await db[MATCHES_COLLECTION].delete_many({"document_id": doc_id})

    stored_matches = []
    for c in candidates[:10]:
        match_rec = {
            "transaction_match_id": f"TM-{uuid.uuid4().hex[:8].upper()}",
            "document_id": doc_id,
            **c,
            "created_at": now,
            "selected_at": None,
            "selected_by": None,
            "notes": "",
        }
        await db[MATCHES_COLLECTION].insert_one(match_rec.copy())
        match_rec.pop("_id", None)
        stored_matches.append(match_rec)

    # Update intelligence result
    best = overall["best_match"]
    intel_update = {
        "transaction_match_status": overall["status"],
        "matched_transaction_count": len(candidates),
        "best_transaction_match": {
            "entity_type": best["candidate_entity_type"],
            "entity_id": best["candidate_entity_id"],
            "display_name": best["candidate_display_name"],
            "confidence": best["match_confidence"],
            "basis": best["match_basis"],
        } if best else None,
        "auto_link_available": overall["auto_link_available"],
        "auto_link_created": False,
        "auto_draft_suppressed_due_to_match": overall["auto_link_available"],
        "transaction_match_blocking_items": [],
    }

    if overall["status"] == STATUS_AMBIGUOUS:
        intel_update["transaction_match_blocking_items"] = [
            f"ambiguous: {len(candidates)} candidate matches found"
        ]

    await db[INTELLIGENCE_COLLECTION].update_one(
        {"document_id": doc_id}, {"$set": intel_update}
    )

    # Activity
    if overall["status"] == STATUS_MATCHED and best:
        await _create_activity(
            db, doc_id, "transaction_match_found",
            f"Transaction match found: {best['candidate_display_name']}",
            f"Confidence: {best['match_confidence']:.0%}, Basis: {best['match_basis']}",
            metadata={"match_id": stored_matches[0]["transaction_match_id"] if stored_matches else ""},
        )
    elif overall["status"] == STATUS_AMBIGUOUS:
        await _create_activity(
            db, doc_id, "transaction_match_ambiguous",
            f"Ambiguous transaction match: {len(candidates)} candidates",
            metadata={"candidate_count": len(candidates)},
        )
    else:
        await _create_activity(
            db, doc_id, "transaction_match_none",
            "No existing transaction match found",
        )

    return {
        "document_id": doc_id,
        "matches": stored_matches,
        "overall_status": overall["status"],
        "auto_link_available": overall["auto_link_available"],
        "best_match": overall["best_match"],
        "total_candidates": len(candidates),
    }


async def get_transaction_matches(doc_id: str) -> List[Dict[str, Any]]:
    """Get all stored transaction match candidates for a document."""
    db = get_db()
    return await db[MATCHES_COLLECTION].find(
        {"document_id": doc_id}, {"_id": 0}
    ).sort("match_confidence", -1).to_list(50)


async def auto_link(doc_id: str) -> Dict[str, Any]:
    """
    Auto-link document to the best matched transaction.
    ONLY links when there is a single high-confidence match.
    Rejects ambiguous matches — those must be manually confirmed.
    """
    db = get_db()

    matches = await get_transaction_matches(doc_id)
    if not matches:
        raise ValueError(f"No transaction matches for document: {doc_id}. Run matching first.")

    # Find the best confirmed or high-confidence match
    selected = None
    for m in matches:
        if m.get("match_status") == STATUS_CONFIRMED and m.get("is_selected"):
            selected = m
            break

    if not selected:
        # Try auto-select from high-confidence single winner (exclude rejected)
        high_conf = [m for m in matches if m["match_confidence"] >= HIGH_CONFIDENCE and m.get("match_status") != STATUS_REJECTED]
        if len(high_conf) == 1:
            selected = high_conf[0]
        elif len(high_conf) > 1:
            raise PermissionError(
                f"Ambiguous: {len(high_conf)} high-confidence matches found. "
                f"Manually confirm one before auto-linking."
            )
        else:
            raise PermissionError(
                "No high-confidence match available for auto-linking. "
                "Manually confirm a candidate or create a new draft."
            )

    now = datetime.now(timezone.utc).isoformat()

    # Mark as selected
    await db[MATCHES_COLLECTION].update_one(
        {"transaction_match_id": selected["transaction_match_id"]},
        {"$set": {"is_selected": True, "selected_at": now, "selected_by": "auto_link", "match_status": STATUS_CONFIRMED}},
    )

    # Link: update hub_documents with cross-reference
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "linked_transaction_type": selected["candidate_entity_type"],
            "linked_transaction_id": selected["candidate_entity_id"],
            "linked_transaction_display": selected["candidate_display_name"],
            "linked_at": now,
            "linked_by": "auto_link",
            "updated_utc": now,
        }},
    )

    # Update intelligence result
    await db[INTELLIGENCE_COLLECTION].update_one(
        {"document_id": doc_id},
        {"$set": {
            "auto_link_created": True,
            "auto_draft_suppressed_due_to_match": True,
            "transaction_match_status": STATUS_CONFIRMED,
        }},
    )

    # Update the target draft to reference this document
    target_type = selected["candidate_entity_type"]
    target_id = selected["candidate_entity_id"]
    coll_map = {
        "sales_order_draft": "so_drafts",
        "po_draft": "po_drafts",
        "ap_intake_draft": "ap_intake_drafts",
    }
    target_coll = coll_map.get(target_type)
    if target_coll:
        id_field = {"so_drafts": "so_draft_id", "po_drafts": "po_draft_id", "ap_intake_drafts": "ap_draft_id"}.get(target_coll)
        if id_field:
            await db[target_coll].update_one(
                {id_field: target_id},
                {"$addToSet": {"linked_document_ids": doc_id}, "$set": {"updated_at": now}},
            )

    # Activity
    await _create_activity(
        db, doc_id, "transaction_auto_linked",
        f"Document auto-linked to {selected['candidate_display_name']}",
        f"Confidence: {selected['match_confidence']:.0%}, Basis: {selected['match_basis']}",
        metadata={"target_type": target_type, "target_id": target_id},
    )

    return {
        "document_id": doc_id,
        "linked": True,
        "target_entity_type": target_type,
        "target_entity_id": target_id,
        "target_display_name": selected["candidate_display_name"],
        "match_confidence": selected["match_confidence"],
        "match_basis": selected["match_basis"],
    }


async def confirm_match(
    match_id: str,
    confirmed: bool = True,
    selected_by: str = "admin",
    notes: str = "",
) -> Dict[str, Any]:
    """Manually confirm or reject a transaction match candidate."""
    db = get_db()

    existing = await db[MATCHES_COLLECTION].find_one(
        {"transaction_match_id": match_id}, {"_id": 0}
    )
    if not existing:
        raise ValueError(f"Transaction match not found: {match_id}")

    now = datetime.now(timezone.utc).isoformat()
    doc_id = existing["document_id"]

    if confirmed:
        # Deselect all others for this document
        await db[MATCHES_COLLECTION].update_many(
            {"document_id": doc_id, "transaction_match_id": {"$ne": match_id}},
            {"$set": {"is_selected": False, "match_status": STATUS_REJECTED}},
        )
        # Confirm this one
        await db[MATCHES_COLLECTION].update_one(
            {"transaction_match_id": match_id},
            {"$set": {
                "is_selected": True,
                "match_status": STATUS_CONFIRMED,
                "selected_at": now,
                "selected_by": selected_by,
                "notes": notes,
            }},
        )
        # Update intelligence
        await db[INTELLIGENCE_COLLECTION].update_one(
            {"document_id": doc_id},
            {"$set": {
                "transaction_match_status": STATUS_CONFIRMED,
                "auto_link_available": True,
                "auto_draft_suppressed_due_to_match": True,
                "transaction_match_blocking_items": [],
                "best_transaction_match": {
                    "entity_type": existing["candidate_entity_type"],
                    "entity_id": existing["candidate_entity_id"],
                    "display_name": existing["candidate_display_name"],
                    "confidence": 1.0,
                    "basis": f"manual_confirm ({existing['match_basis']})",
                },
            }},
        )
        await _create_activity(
            db, doc_id, "transaction_match_confirmed",
            f"Transaction match confirmed: {existing['candidate_display_name']}",
            f"Confirmed by {selected_by}",
            metadata={"match_id": match_id},
        )
    else:
        await db[MATCHES_COLLECTION].update_one(
            {"transaction_match_id": match_id},
            {"$set": {
                "is_selected": False,
                "match_status": STATUS_REJECTED,
                "selected_at": now,
                "selected_by": selected_by,
                "notes": notes,
            }},
        )
        # Re-evaluate remaining candidates
        remaining = await db[MATCHES_COLLECTION].find(
            {"document_id": doc_id, "match_status": {"$ne": STATUS_REJECTED}},
            {"_id": 0},
        ).to_list(20)
        overall = _determine_overall_status(remaining)
        best = overall["best_match"]
        await db[INTELLIGENCE_COLLECTION].update_one(
            {"document_id": doc_id},
            {"$set": {
                "transaction_match_status": overall["status"],
                "auto_link_available": overall["auto_link_available"],
                "auto_draft_suppressed_due_to_match": overall["auto_link_available"],
                "best_transaction_match": {
                    "entity_type": best["candidate_entity_type"],
                    "entity_id": best["candidate_entity_id"],
                    "display_name": best["candidate_display_name"],
                    "confidence": best["match_confidence"],
                    "basis": best["match_basis"],
                } if best else None,
            }},
        )
        await _create_activity(
            db, doc_id, "transaction_match_rejected",
            f"Transaction match rejected: {existing['candidate_display_name']}",
            f"Rejected by {selected_by}. Notes: {notes}",
            metadata={"match_id": match_id},
        )

    return await db[MATCHES_COLLECTION].find_one(
        {"transaction_match_id": match_id}, {"_id": 0}
    )

    # Note: learning hook is called before return via the pattern below

# Learning loop hook appended after confirm_match
_original_confirm_match = confirm_match

async def confirm_match(match_id, confirmed=True, selected_by="admin", notes=""):
    result = await _original_confirm_match(match_id, confirmed, selected_by, notes)
    try:
        from services.learning_loop_service import on_transaction_match_override
        if result:
            await on_transaction_match_override(
                document_id=result.get("document_id", ""),
                match_id=match_id,
                confirmed=confirmed,
                candidate_entity_type=result.get("candidate_entity_type", ""),
                candidate_entity_id=result.get("candidate_entity_id", ""),
                candidate_display_name=result.get("candidate_display_name", ""),
                corrected_by=selected_by,
            )
    except Exception:
        pass
    return result
