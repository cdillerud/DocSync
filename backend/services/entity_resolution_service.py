"""
GPI Document Hub - Entity Resolution Service

Resolves extracted document field values (customer names, vendor names, PO numbers,
invoice numbers) to internal business entities with confidence scoring and
human-review fallback.

Resolution strategy (layered):
  1. Exact match
  2. Normalized exact match
  3. Fuzzy string match
  4. Reference/number lookup
  5. Ambiguous candidate list
"""

import re
import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from deps import get_db
from services.reference_helpers import normalize_text, fuzzy_ratio

logger = logging.getLogger(__name__)

RESOLUTIONS_COLLECTION = "entity_resolutions"
INTELLIGENCE_COLLECTION = "document_intelligence_results"
ACTIVITIES_COLLECTION = "activities"

# Entity kinds
ENTITY_KINDS = ("customer", "vendor", "sales_order", "purchase_order", "invoice")

# Resolution statuses
STATUS_MATCHED = "matched"
STATUS_AMBIGUOUS = "ambiguous"
STATUS_UNMATCHED = "unmatched"
STATUS_CORRECTED = "corrected"

# Confidence thresholds
HIGH_CONFIDENCE = 0.90
MEDIUM_CONFIDENCE = 0.70
LOW_CONFIDENCE = 0.50

# Fields to resolve per document type
RESOLUTION_FIELDS = {
    "customer": ["customer", "consignee", "customer_name", "bill_to"],
    "vendor": ["vendor", "shipper", "carrier", "vendor_name", "supplier"],
    "purchase_order": ["po_number", "purchase_order_number", "order_number"],
    "invoice": ["invoice_number", "invoice_no"],
    "sales_order": ["so_number", "sales_order_number"],
}


def _normalize(value: str) -> str:
    """Normalize a string for matching — delegates to shared helper."""
    return normalize_text(value)


def _fuzzy_score(a: str, b: str) -> float:
    """Calculate fuzzy similarity — delegates to shared helper."""
    return fuzzy_ratio(a, b, normalizer=normalize_text)


async def _resolve_customer(db, source_value: str) -> Dict[str, Any]:
    """Resolve a customer name against known entities."""
    if not source_value:
        return _empty_resolution("customer", "", "no_input")

    candidates = []

    # 1) Exact match in hub_documents customer references
    exact = await db.hub_documents.find_one(
        {"$or": [
            {"extracted_fields.customer": {"$regex": f"^{re.escape(source_value)}$", "$options": "i"}},
            {"extracted_fields.consignee": {"$regex": f"^{re.escape(source_value)}$", "$options": "i"}},
        ]},
        {"_id": 0, "extracted_fields.customer": 1, "extracted_fields.consignee": 1, "id": 1},
    )
    if exact:
        name = exact.get("extracted_fields", {}).get("customer") or exact.get("extracted_fields", {}).get("consignee") or source_value
        candidates.append({"entity_id": name, "entity_name": name, "score": 1.0, "method": "exact"})

    # 2) Check SO drafts for customer references
    so_match = await db.so_drafts.find_one(
        {"customer_name": {"$regex": f"^{re.escape(source_value)}$", "$options": "i"}},
        {"_id": 0, "so_draft_id": 1, "customer_name": 1},
    )
    if so_match:
        candidates.append({
            "entity_id": so_match["customer_name"],
            "entity_name": so_match["customer_name"],
            "score": 1.0,
            "method": "so_draft_exact",
        })

    # 3) Fuzzy search in hub_documents (sampling recent docs)
    if not candidates:
        pipeline = [
            {"$match": {"extracted_fields.customer": {"$exists": True, "$ne": ""}}},
            {"$group": {"_id": "$extracted_fields.customer"}},
            {"$limit": 100},
        ]
        known_customers = await db.hub_documents.aggregate(pipeline).to_list(100)
        for kc in known_customers:
            cname = kc["_id"]
            if cname:
                score = _fuzzy_score(source_value, cname)
                if score >= LOW_CONFIDENCE:
                    candidates.append({"entity_id": cname, "entity_name": cname, "score": round(score, 3), "method": "fuzzy"})

    # 4) Also check consignee field
    if len(candidates) < 3:
        pipeline2 = [
            {"$match": {"extracted_fields.consignee": {"$exists": True, "$ne": ""}}},
            {"$group": {"_id": "$extracted_fields.consignee"}},
            {"$limit": 50},
        ]
        known_consignees = await db.hub_documents.aggregate(pipeline2).to_list(50)
        seen = {c["entity_name"] for c in candidates}
        for kc in known_consignees:
            cname = kc["_id"]
            if cname and cname not in seen:
                score = _fuzzy_score(source_value, cname)
                if score >= LOW_CONFIDENCE:
                    candidates.append({"entity_id": cname, "entity_name": cname, "score": round(score, 3), "method": "fuzzy_consignee"})

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return _build_resolution("customer", source_value, candidates)


async def _resolve_vendor(db, source_value: str) -> Dict[str, Any]:
    """Resolve a vendor name against aliases and BC vendors."""
    if not source_value:
        return _empty_resolution("vendor", "", "no_input")

    norm = _normalize(source_value)
    candidates = []

    # 1) Exact alias match
    alias_doc = await db.vendor_aliases.find_one(
        {"$or": [
            {"normalized_alias": norm},
            {"alias_string": {"$regex": f"^{re.escape(source_value)}$", "$options": "i"}},
        ]},
        {"_id": 0},
    )
    if alias_doc:
        candidates.append({
            "entity_id": alias_doc.get("canonical_vendor_id") or alias_doc.get("vendor_no") or alias_doc.get("vendor_name", ""),
            "entity_name": alias_doc.get("vendor_name", ""),
            "entity_number": alias_doc.get("vendor_no", ""),
            "score": 1.0,
            "method": "alias_exact",
        })

    # 2) Exact BC vendor match
    bc_vendor = await db.hub_bc_vendors.find_one(
        {"$or": [
            {"name_normalized": norm},
            {"displayName": {"$regex": f"^{re.escape(source_value)}$", "$options": "i"}},
        ]},
        {"_id": 0, "displayName": 1, "number": 1, "id": 1},
    )
    if bc_vendor:
        candidates.append({
            "entity_id": bc_vendor.get("number") or bc_vendor.get("id", ""),
            "entity_name": bc_vendor.get("displayName", ""),
            "entity_number": bc_vendor.get("number", ""),
            "score": 1.0,
            "method": "bc_exact",
        })

    # 3) Fuzzy against vendor aliases
    if not candidates or candidates[0]["score"] < HIGH_CONFIDENCE:
        aliases = await db.vendor_aliases.find(
            {}, {"_id": 0, "alias_string": 1, "vendor_name": 1, "vendor_no": 1, "canonical_vendor_id": 1}
        ).to_list(2000)
        seen = {c.get("entity_id") for c in candidates}
        for a in aliases:
            alias_str = a.get("alias_string") or a.get("vendor_name") or ""
            if not alias_str:
                continue
            score = _fuzzy_score(source_value, alias_str)
            vid = a.get("canonical_vendor_id") or a.get("vendor_no") or a.get("vendor_name", "")
            if score >= LOW_CONFIDENCE and vid not in seen:
                candidates.append({
                    "entity_id": vid,
                    "entity_name": a.get("vendor_name", alias_str),
                    "entity_number": a.get("vendor_no", ""),
                    "score": round(score, 3),
                    "method": "alias_fuzzy",
                })
                seen.add(vid)

    # 4) Fuzzy against BC vendors
    if not candidates or candidates[0]["score"] < HIGH_CONFIDENCE:
        bc_vendors = await db.hub_bc_vendors.find(
            {}, {"_id": 0, "displayName": 1, "number": 1, "id": 1}
        ).to_list(200)
        seen = {c.get("entity_id") for c in candidates}
        for bv in bc_vendors:
            bname = bv.get("displayName", "")
            if not bname:
                continue
            score = _fuzzy_score(source_value, bname)
            vid = bv.get("number") or bv.get("id", "")
            if score >= LOW_CONFIDENCE and vid not in seen:
                candidates.append({
                    "entity_id": vid,
                    "entity_name": bname,
                    "entity_number": bv.get("number", ""),
                    "score": round(score, 3),
                    "method": "bc_fuzzy",
                })
                seen.add(vid)

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return _build_resolution("vendor", source_value, candidates)


async def _resolve_po_number(db, source_value: str) -> Dict[str, Any]:
    """Resolve a PO/order number against existing drafts and documents."""
    if not source_value:
        return _empty_resolution("purchase_order", "", "no_input")

    candidates = []

    # 1) Exact match in PO drafts
    po = await db.po_drafts.find_one(
        {"$or": [
            {"po_draft_id": source_value},
            {"source_reference": {"$regex": f"^{re.escape(source_value)}$", "$options": "i"}},
        ]},
        {"_id": 0, "po_draft_id": 1, "vendor_name": 1, "status": 1},
    )
    if po:
        candidates.append({
            "entity_id": po["po_draft_id"],
            "entity_name": f"PO Draft: {po['po_draft_id']} ({po.get('vendor_name', '')})",
            "score": 1.0,
            "method": "po_draft_exact",
        })

    # 2) Match in SO drafts (customer PO number)
    so = await db.so_drafts.find_one(
        {"customer_po_number": {"$regex": f"^{re.escape(source_value)}$", "$options": "i"}},
        {"_id": 0, "so_draft_id": 1, "customer_name": 1},
    )
    if so:
        candidates.append({
            "entity_id": so["so_draft_id"],
            "entity_name": f"SO Draft: {so['so_draft_id']} ({so.get('customer_name', '')})",
            "score": 1.0,
            "method": "so_draft_exact",
        })

    # 3) Match in hub_documents by PO reference
    doc_match = await db.hub_documents.find_one(
        {"$or": [
            {"po_number_clean": {"$regex": f"^{re.escape(source_value)}$", "$options": "i"}},
            {"extracted_fields.po_number": {"$regex": f"^{re.escape(source_value)}$", "$options": "i"}},
        ]},
        {"_id": 0, "id": 1, "file_name": 1, "status": 1},
    )
    if doc_match:
        candidates.append({
            "entity_id": doc_match["id"],
            "entity_name": f"Document: {doc_match.get('file_name', doc_match['id'])}",
            "score": 0.95,
            "method": "document_reference",
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return _build_resolution("purchase_order", source_value, candidates)


async def _resolve_invoice_number(db, source_value: str) -> Dict[str, Any]:
    """Resolve an invoice number against AP drafts and documents."""
    if not source_value:
        return _empty_resolution("invoice", "", "no_input")

    candidates = []

    # 1) Exact match in AP intake drafts
    ap = await db.ap_intake_drafts.find_one(
        {"invoice_number": {"$regex": f"^{re.escape(source_value)}$", "$options": "i"}},
        {"_id": 0, "ap_draft_id": 1, "vendor_name": 1, "invoice_amount": 1},
    )
    if ap:
        candidates.append({
            "entity_id": ap["ap_draft_id"],
            "entity_name": f"AP Draft: {ap['ap_draft_id']} ({ap.get('vendor_name', '')})",
            "score": 1.0,
            "method": "ap_draft_exact",
        })

    # 2) Match in hub_documents
    doc_match = await db.hub_documents.find_one(
        {"$or": [
            {"invoice_number_clean": {"$regex": f"^{re.escape(source_value)}$", "$options": "i"}},
            {"extracted_fields.invoice_number": {"$regex": f"^{re.escape(source_value)}$", "$options": "i"}},
        ]},
        {"_id": 0, "id": 1, "file_name": 1, "status": 1},
    )
    if doc_match:
        candidates.append({
            "entity_id": doc_match["id"],
            "entity_name": f"Document: {doc_match.get('file_name', doc_match['id'])}",
            "score": 0.95,
            "method": "document_reference",
        })

    candidates.sort(key=lambda x: x["score"], reverse=True)
    return _build_resolution("invoice", source_value, candidates)


def _build_resolution(entity_kind: str, source_value: str, candidates: List[Dict]) -> Dict[str, Any]:
    """Build a resolution result from ranked candidates."""
    # Deduplicate by entity_id
    seen = set()
    deduped = []
    for c in candidates:
        eid = c.get("entity_id", "")
        if eid and eid not in seen:
            seen.add(eid)
            deduped.append(c)
    candidates = deduped[:10]

    if not candidates:
        return _empty_resolution(entity_kind, source_value, "no_candidates")

    best = candidates[0]

    # Determine status
    if best["score"] >= HIGH_CONFIDENCE:
        if len(candidates) > 1 and candidates[1]["score"] >= MEDIUM_CONFIDENCE:
            status = STATUS_AMBIGUOUS  # Multiple strong candidates
        else:
            status = STATUS_MATCHED
    elif best["score"] >= MEDIUM_CONFIDENCE:
        if len(candidates) > 1 and candidates[1]["score"] >= LOW_CONFIDENCE:
            status = STATUS_AMBIGUOUS
        else:
            status = STATUS_MATCHED
    else:
        status = STATUS_UNMATCHED

    return {
        "entity_kind": entity_kind,
        "source_value": source_value,
        "matched_entity_id": best.get("entity_id", ""),
        "matched_entity_type": entity_kind,
        "matched_entity_name": best.get("entity_name", ""),
        "match_method": best.get("method", ""),
        "match_confidence": best["score"],
        "candidate_matches": candidates[:5],
        "resolution_status": status,
    }


def _empty_resolution(entity_kind: str, source_value: str, reason: str) -> Dict[str, Any]:
    return {
        "entity_kind": entity_kind,
        "source_value": source_value,
        "matched_entity_id": "",
        "matched_entity_type": entity_kind,
        "matched_entity_name": "",
        "match_method": reason,
        "match_confidence": 0.0,
        "candidate_matches": [],
        "resolution_status": STATUS_UNMATCHED,
    }


async def _create_activity(db, entity_type, entity_id, activity_type, title, body_text="", metadata=None):
    """Create activity record."""
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "activity_id": f"ACT-{uuid.uuid4().hex[:8].upper()}",
        "entity_type": entity_type,
        "entity_id": entity_id,
        "activity_type": activity_type,
        "title": title,
        "body": body_text,
        "created_by": "system",
        "created_at": now,
        "metadata": metadata or {},
    }
    await db[ACTIVITIES_COLLECTION].insert_one(record.copy())
    record.pop("_id", None)
    return record


# ─── Public API ───────────────────────────────────────────────────────────────

async def resolve_entities(doc_id: str) -> Dict[str, Any]:
    """
    Resolve all relevant extracted entities for a document.
    Returns a list of resolution results and a summary.
    """
    db = get_db()

    # Load intelligence result
    intel = await db[INTELLIGENCE_COLLECTION].find_one({"document_id": doc_id}, {"_id": 0})
    if not intel:
        raise ValueError(f"No intelligence result for document: {doc_id}. Run processing first.")

    fields = intel.get("extracted_fields", {})
    now = datetime.now(timezone.utc)
    resolutions = []

    # Determine which fields to resolve based on what's extracted
    resolve_map = {
        "customer": _resolve_customer,
        "vendor": _resolve_vendor,
        "purchase_order": _resolve_po_number,
        "invoice": _resolve_invoice_number,
    }

    for entity_kind, resolver in resolve_map.items():
        source_fields = RESOLUTION_FIELDS.get(entity_kind, [])
        for field_name in source_fields:
            val = fields.get(field_name)
            if val and isinstance(val, str) and val.strip():
                result = await resolver(db, val.strip())
                result["source_field"] = field_name
                result["resolution_id"] = f"RES-{uuid.uuid4().hex[:8].upper()}"
                result["document_id"] = doc_id
                result["resolved_at"] = now.isoformat()
                result["resolved_by"] = "system"
                result["notes"] = ""
                resolutions.append(result)
                break  # Only resolve first non-empty field per entity kind

    # Store resolutions (replace all for this document)
    if resolutions:
        await db[RESOLUTIONS_COLLECTION].delete_many({"document_id": doc_id})
        for r in resolutions:
            await db[RESOLUTIONS_COLLECTION].insert_one(r.copy())
            r.pop("_id", None)

    # Compute summary
    summary = _compute_resolution_summary(resolutions)

    # Update intelligence result with resolution info
    await db[INTELLIGENCE_COLLECTION].update_one(
        {"document_id": doc_id},
        {"$set": {
            "entity_resolution_status": summary["status"],
            "entity_resolution_blocking_items": summary["blocking_items"],
            "resolved_entities": summary["resolved"],
            "unresolved_entity_count": summary["unresolved_count"],
            "ambiguous_entity_count": summary["ambiguous_count"],
        }},
    )

    # Activity logging
    if summary["unresolved_count"] > 0 or summary["ambiguous_count"] > 0:
        await _create_activity(
            db, "document", doc_id, "entity_resolution_issues",
            f"Entity resolution: {summary['unresolved_count']} unresolved, {summary['ambiguous_count']} ambiguous",
            metadata={"blocking_items": summary["blocking_items"]},
        )
    else:
        await _create_activity(
            db, "document", doc_id, "entity_resolution_completed",
            f"Entity resolution completed: {len(resolutions)} entities resolved",
        )

    return {
        "document_id": doc_id,
        "resolutions": resolutions,
        "summary": summary,
    }


def _compute_resolution_summary(resolutions: List[Dict]) -> Dict[str, Any]:
    """Compute a summary of resolution results."""
    resolved = []
    blocking_items = []
    unresolved_count = 0
    ambiguous_count = 0

    for r in resolutions:
        status = r.get("resolution_status", STATUS_UNMATCHED)
        entry = {
            "entity_kind": r["entity_kind"],
            "source_field": r.get("source_field", ""),
            "source_value": r["source_value"],
            "status": status,
            "matched_entity_name": r.get("matched_entity_name", ""),
            "confidence": r.get("match_confidence", 0),
        }
        resolved.append(entry)

        if status == STATUS_UNMATCHED:
            unresolved_count += 1
            blocking_items.append(f"{r['entity_kind']}_unmatched: '{r['source_value']}'")
        elif status == STATUS_AMBIGUOUS:
            ambiguous_count += 1
            blocking_items.append(f"{r['entity_kind']}_ambiguous: '{r['source_value']}' ({len(r.get('candidate_matches', []))} candidates)")

    # Overall status
    if unresolved_count > 0:
        overall = "blocked"
    elif ambiguous_count > 0:
        overall = "needs_review"
    else:
        overall = "resolved"

    return {
        "status": overall,
        "resolved": resolved,
        "blocking_items": blocking_items,
        "unresolved_count": unresolved_count,
        "ambiguous_count": ambiguous_count,
        "total_resolved": len(resolutions),
    }


async def get_resolutions(doc_id: str) -> List[Dict[str, Any]]:
    """Get all stored resolution results for a document."""
    db = get_db()
    cursor = db[RESOLUTIONS_COLLECTION].find({"document_id": doc_id}, {"_id": 0})
    return await cursor.to_list(50)


async def correct_resolution(
    resolution_id: str,
    matched_entity_id: Optional[str] = None,
    matched_entity_name: Optional[str] = None,
    corrected_by: str = "admin",
    notes: str = "",
    mark_unmatched: bool = False,
) -> Dict[str, Any]:
    """
    Apply a manual correction to a resolution result.
    Preserves original output for auditability.
    """
    db = get_db()

    existing = await db[RESOLUTIONS_COLLECTION].find_one(
        {"resolution_id": resolution_id}, {"_id": 0}
    )
    if not existing:
        raise ValueError(f"Resolution not found: {resolution_id}")

    now = datetime.now(timezone.utc).isoformat()

    # Preserve original
    original = {
        "matched_entity_id": existing.get("matched_entity_id"),
        "matched_entity_name": existing.get("matched_entity_name"),
        "match_confidence": existing.get("match_confidence"),
        "match_method": existing.get("match_method"),
        "resolution_status": existing.get("resolution_status"),
    }

    updates = {
        "resolution_status": STATUS_CORRECTED,
        "resolved_at": now,
        "resolved_by": corrected_by,
        "notes": notes,
        "original_resolution": original,
    }

    if mark_unmatched:
        updates["matched_entity_id"] = ""
        updates["matched_entity_name"] = ""
        updates["match_confidence"] = 0.0
        updates["match_method"] = "manual_unmatched"
        updates["resolution_status"] = STATUS_UNMATCHED
    elif matched_entity_id is not None:
        updates["matched_entity_id"] = matched_entity_id
        updates["matched_entity_name"] = matched_entity_name or matched_entity_id
        updates["match_confidence"] = 1.0
        updates["match_method"] = "manual_override"

    await db[RESOLUTIONS_COLLECTION].update_one(
        {"resolution_id": resolution_id}, {"$set": updates}
    )

    # Re-fetch updated
    updated = await db[RESOLUTIONS_COLLECTION].find_one(
        {"resolution_id": resolution_id}, {"_id": 0}
    )

    # Re-compute document-level summary
    doc_id = existing["document_id"]
    all_res = await get_resolutions(doc_id)
    summary = _compute_resolution_summary(all_res)

    await db[INTELLIGENCE_COLLECTION].update_one(
        {"document_id": doc_id},
        {"$set": {
            "entity_resolution_status": summary["status"],
            "entity_resolution_blocking_items": summary["blocking_items"],
            "resolved_entities": summary["resolved"],
            "unresolved_entity_count": summary["unresolved_count"],
            "ambiguous_entity_count": summary["ambiguous_count"],
        }},
    )

    # Activity
    await _create_activity(
        db, "document", doc_id, "entity_resolution_corrected",
        f"Entity resolution corrected: {existing['entity_kind']} '{existing['source_value']}'",
        body_text=f"Changed to: {updates.get('matched_entity_name', '(unmatched)')} by {corrected_by}",
        metadata={"resolution_id": resolution_id, "original": original},
    )

    # Learning loop hook
    try:
        from services.learning_loop_service import on_entity_override
        await on_entity_override(
            document_id=doc_id,
            entity_kind=existing.get("entity_kind", ""),
            source_value=existing.get("source_value", ""),
            original_entity_id=original.get("matched_entity_id", ""),
            original_entity_name=original.get("matched_entity_name", ""),
            corrected_entity_id=updates.get("matched_entity_id", ""),
            corrected_entity_name=updates.get("matched_entity_name", ""),
            confidence_before=original.get("match_confidence", 0),
            corrected_by=corrected_by,
        )
    except Exception as e:
        logger.warning("Learning loop hook failed: %s", e)

    return updated
