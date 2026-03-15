"""
GPI Document Hub - Document Bundle Service

Detects when multiple documents belong to the same business transaction,
groups them into bundles, evaluates completeness, and provides automation guidance.

SAFETY: No inventory mutations, no BC calls, no auto-finalization.
"""

import uuid
import logging
from datetime import datetime, timezone, timedelta
from typing import Dict, Any, Optional, List

from deps import get_db

logger = logging.getLogger(__name__)

BUNDLES_COLLECTION = "document_bundles"
INTELLIGENCE_COLLECTION = "document_intelligence_results"
ACTIVITIES_COLLECTION = "activities"

# Bundle types
BUNDLE_TYPE_CUSTOMER_ORDER = "customer_order_packet"
BUNDLE_TYPE_PURCHASING = "purchasing_packet"
BUNDLE_TYPE_AP = "ap_packet"
BUNDLE_TYPE_WAREHOUSE = "warehouse_packet"
BUNDLE_TYPE_UNKNOWN = "unknown"

# Bundle statuses
STATUS_GROUPED = "grouped"
STATUS_NEEDS_REVIEW = "needs_review"
STATUS_COMPLETE = "complete"
STATUS_INCOMPLETE = "incomplete"

# Completeness statuses
COMPLETENESS_COMPLETE = "complete"
COMPLETENESS_PARTIAL = "partial"
COMPLETENESS_INSUFFICIENT = "insufficient"

# Document types that contribute to each bundle type
BUNDLE_TYPE_DOC_MAP = {
    BUNDLE_TYPE_CUSTOMER_ORDER: {
        "primary": ["Sales_PO", "customer_po"],
        "supporting": ["Order_Confirmation", "Sales_Order", "Shipping_Document", "Quality_Issue"],
        "expected_min": ["customer_po_or_sales_po"],
        "expected_nice": ["supporting_document"],
    },
    BUNDLE_TYPE_PURCHASING: {
        "primary": ["Freight_Document", "Shipping_Document", "vendor_po_support"],
        "supporting": ["Sales_PO", "AP_Invoice", "Quality_Issue"],
        "expected_min": ["po_support_document"],
        "expected_nice": ["vendor_support"],
    },
    BUNDLE_TYPE_AP: {
        "primary": ["AP_Invoice", "invoice"],
        "supporting": ["Freight_Document", "Shipping_Document", "Remittance", "Warehouse_Document"],
        "expected_min": ["invoice_document"],
        "expected_nice": ["receiving_or_packing_support"],
    },
    BUNDLE_TYPE_WAREHOUSE: {
        "primary": ["Warehouse_Document"],
        "supporting": ["Sales_PO", "customer_po", "Shipping_Document"],
        "expected_min": ["warehouse_agreement"],
        "expected_nice": ["customer_po_or_support"],
    },
}


async def _create_activity(db, entity_id, entity_type, activity_type, title, body="", metadata=None):
    now = datetime.now(timezone.utc).isoformat()
    record = {
        "activity_id": f"ACT-{uuid.uuid4().hex[:8].upper()}",
        "entity_type": entity_type,
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


def _detect_bundle_type(doc_types: List[str]) -> str:
    """Infer bundle type from the document types present in a group."""
    types_set = set(doc_types)

    # AP packet: has invoice
    ap_types = {"AP_Invoice", "invoice"}
    if types_set & ap_types:
        return BUNDLE_TYPE_AP

    # Customer order: has customer PO or sales PO
    co_types = {"Sales_PO", "customer_po", "Sales_Order", "Order_Confirmation"}
    if types_set & co_types:
        return BUNDLE_TYPE_CUSTOMER_ORDER

    # Warehouse: has warehouse doc
    wh_types = {"Warehouse_Document"}
    if types_set & wh_types:
        return BUNDLE_TYPE_WAREHOUSE

    # Purchasing: has freight/shipping
    po_types = {"Freight_Document", "Shipping_Document", "vendor_po_support"}
    if types_set & po_types:
        return BUNDLE_TYPE_PURCHASING

    return BUNDLE_TYPE_UNKNOWN


def _evaluate_completeness(bundle_type: str, doc_types: List[str], doc_count: int) -> Dict[str, Any]:
    """Evaluate completeness of a bundle based on its type and member documents."""
    rules = BUNDLE_TYPE_DOC_MAP.get(bundle_type, {})
    primary_types = set(rules.get("primary", []))
    supporting_types = set(rules.get("supporting", []))
    types_set = set(doc_types)

    has_primary = bool(types_set & primary_types)
    has_supporting = bool(types_set & supporting_types)
    missing = []

    if bundle_type == BUNDLE_TYPE_AP:
        if not has_primary:
            missing.append("No invoice document in packet")
        if not has_supporting and doc_count < 2:
            missing.append("Missing receiving/packing support")
    elif bundle_type == BUNDLE_TYPE_CUSTOMER_ORDER:
        if not has_primary:
            missing.append("No customer PO in packet")
        if not has_supporting and doc_count < 2:
            missing.append("Only one supporting document found")
    elif bundle_type == BUNDLE_TYPE_PURCHASING:
        if not has_primary:
            missing.append("No PO support document in packet")
        if not has_supporting and doc_count < 2:
            missing.append("Missing vendor support document")
    elif bundle_type == BUNDLE_TYPE_WAREHOUSE:
        if not has_primary:
            missing.append("No warehouse agreement in packet")
        if not has_supporting:
            missing.append("Missing customer PO or related support")
    else:
        if doc_count < 2:
            missing.append("Only one document — bundle type unknown")

    if not missing:
        status = COMPLETENESS_COMPLETE
    elif has_primary:
        status = COMPLETENESS_PARTIAL
    else:
        status = COMPLETENESS_INSUFFICIENT

    return {
        "completeness_status": status,
        "missing_expected_documents": missing,
        "has_primary": has_primary,
        "has_supporting": has_supporting,
    }


def _extract_keys(intel: Dict) -> Dict[str, Any]:
    """Extract grouping keys from an intelligence result."""
    fields = intel.get("extracted_fields", {})
    keys = {}

    po = fields.get("po_number") or fields.get("order_number") or fields.get("customer_po") or ""
    if po and str(po).strip():
        keys["po_number"] = str(po).strip().upper()

    inv = fields.get("invoice_number") or fields.get("invoice_no") or ""
    if inv and str(inv).strip():
        keys["invoice_number"] = str(inv).strip().upper()

    vendor = fields.get("vendor") or fields.get("vendor_name") or fields.get("shipper") or ""
    if vendor and str(vendor).strip():
        keys["vendor"] = str(vendor).strip().upper()

    customer = fields.get("customer") or fields.get("customer_name") or fields.get("consignee") or ""
    if customer and str(customer).strip():
        keys["customer"] = str(customer).strip().upper()

    amount = fields.get("amount") or fields.get("invoice_amount") or fields.get("total") or ""
    if amount:
        try:
            keys["amount"] = float(str(amount).replace(",", "").replace("$", ""))
        except (ValueError, TypeError):
            pass

    # Transaction match info
    best_match = intel.get("best_transaction_match")
    if best_match and best_match.get("entity_id"):
        keys["linked_entity_id"] = best_match["entity_id"]
        keys["linked_entity_type"] = best_match.get("entity_type", "")

    return keys


# ─── Grouping Logic ──────────────────────────────────────────────────────────

def _group_documents(doc_records: List[Dict]) -> List[Dict]:
    """
    Group documents into bundles using layered strategy:
    1. Exact shared PO number
    2. Exact shared invoice number
    3. Shared linked entity (transaction match)
    4. Shared vendor/customer + amount proximity
    """
    if not doc_records:
        return []

    # Assign each doc its extracted keys
    for doc in doc_records:
        doc["_keys"] = _extract_keys(doc)

    assigned = set()
    groups = []

    # Layer 1: Exact PO number match
    po_groups = {}
    for doc in doc_records:
        po = doc["_keys"].get("po_number")
        if po:
            po_groups.setdefault(po, []).append(doc)
    for po, docs in po_groups.items():
        if len(docs) >= 2:
            group_ids = set(d["document_id"] for d in docs)
            groups.append({
                "documents": docs,
                "grouping_basis": f"shared_po_number:{po}",
                "confidence": 0.95,
                "primary_key": ("po_number", po),
            })
            assigned |= group_ids

    # Layer 2: Exact invoice number match
    inv_groups = {}
    for doc in doc_records:
        if doc["document_id"] in assigned:
            continue
        inv = doc["_keys"].get("invoice_number")
        if inv:
            inv_groups.setdefault(inv, []).append(doc)
    for inv, docs in inv_groups.items():
        if len(docs) >= 2:
            group_ids = set(d["document_id"] for d in docs)
            groups.append({
                "documents": docs,
                "grouping_basis": f"shared_invoice_number:{inv}",
                "confidence": 0.92,
                "primary_key": ("invoice_number", inv),
            })
            assigned |= group_ids

    # Layer 3: Shared linked entity (transaction match target)
    entity_groups = {}
    for doc in doc_records:
        if doc["document_id"] in assigned:
            continue
        eid = doc["_keys"].get("linked_entity_id")
        if eid:
            entity_groups.setdefault(eid, []).append(doc)
    for eid, docs in entity_groups.items():
        if len(docs) >= 2:
            group_ids = set(d["document_id"] for d in docs)
            etype = docs[0]["_keys"].get("linked_entity_type", "unknown")
            groups.append({
                "documents": docs,
                "grouping_basis": f"shared_linked_entity:{etype}:{eid}",
                "confidence": 0.88,
                "primary_key": ("linked_entity_id", eid),
            })
            assigned |= group_ids

    # Layer 4: Shared vendor/customer + similar amount (fuzzy)
    remaining = [d for d in doc_records if d["document_id"] not in assigned]
    vendor_groups = {}
    for doc in remaining:
        vkey = doc["_keys"].get("vendor") or doc["_keys"].get("customer")
        if vkey:
            vendor_groups.setdefault(vkey, []).append(doc)
    for vkey, docs in vendor_groups.items():
        if len(docs) >= 2:
            # Check if amounts are similar (within 20%) or dates close
            amounts = [d["_keys"].get("amount") for d in docs if d["_keys"].get("amount")]
            if len(amounts) >= 2:
                avg = sum(amounts) / len(amounts)
                if avg > 0 and all(abs(a - avg) / avg < 0.20 for a in amounts):
                    group_ids = set(d["document_id"] for d in docs)
                    groups.append({
                        "documents": docs,
                        "grouping_basis": f"shared_entity_amount:{vkey}",
                        "confidence": 0.65,
                        "primary_key": ("vendor_customer", vkey),
                    })
                    assigned |= group_ids
            elif len(docs) >= 2 and not amounts:
                # Same vendor/customer, no amounts to compare — low confidence
                group_ids = set(d["document_id"] for d in docs)
                groups.append({
                    "documents": docs,
                    "grouping_basis": f"shared_entity_only:{vkey}",
                    "confidence": 0.50,
                    "primary_key": ("vendor_customer", vkey),
                })
                assigned |= group_ids

    return groups


# ─── Public API ──────────────────────────────────────────────────────────────

async def detect_bundles(document_ids: Optional[List[str]] = None, days_back: int = 7) -> Dict[str, Any]:
    """
    Detect document bundles from recent processed documents or specified IDs.
    Creates/updates bundle records in the database.
    """
    db = get_db()
    now = datetime.now(timezone.utc)

    # Fetch intelligence results
    query = {}
    if document_ids:
        query["document_id"] = {"$in": document_ids}
    else:
        cutoff = (now - timedelta(days=days_back)).isoformat()
        query["processed_at"] = {"$gte": cutoff}

    intel_docs = await db[INTELLIGENCE_COLLECTION].find(
        query, {"_id": 0}
    ).to_list(500)

    if not intel_docs:
        return {"bundles_detected": 0, "bundles": [], "documents_scanned": 0}

    # Skip documents already in confirmed/complete bundles (unless re-detecting specific IDs)
    if not document_ids:
        existing_bundle_doc_ids = set()
        existing_bundles = await db[BUNDLES_COLLECTION].find(
            {"bundle_status": {"$in": [STATUS_COMPLETE, STATUS_GROUPED]}},
            {"_id": 0, "document_ids": 1}
        ).to_list(500)
        for b in existing_bundles:
            existing_bundle_doc_ids.update(b.get("document_ids", []))
        intel_docs = [d for d in intel_docs if d["document_id"] not in existing_bundle_doc_ids]

    groups = _group_documents(intel_docs)

    created_bundles = []
    for group in groups:
        docs = group["documents"]
        doc_ids = [d["document_id"] for d in docs]
        doc_types = [d.get("document_type", "unknown") for d in docs]

        bundle_type = _detect_bundle_type(doc_types)
        completeness = _evaluate_completeness(bundle_type, doc_types, len(docs))

        # Determine bundle status
        if group["confidence"] < 0.70:
            bundle_status = STATUS_NEEDS_REVIEW
        elif completeness["completeness_status"] == COMPLETENESS_COMPLETE:
            bundle_status = STATUS_GROUPED
        elif completeness["completeness_status"] == COMPLETENESS_INSUFFICIENT:
            bundle_status = STATUS_INCOMPLETE
        else:
            bundle_status = STATUS_GROUPED

        # Extract detected keys (union of all doc keys)
        all_keys = {}
        for d in docs:
            for k, v in d.get("_keys", {}).items():
                if k not in all_keys:
                    all_keys[k] = v

        # Determine linked entity from group
        linked_entity_type = all_keys.get("linked_entity_type", "")
        linked_entity_id = all_keys.get("linked_entity_id", "")

        # Check if a bundle already exists for this exact set of documents
        existing = await db[BUNDLES_COLLECTION].find_one(
            {"document_ids": {"$all": doc_ids, "$size": len(doc_ids)}},
            {"_id": 0},
        )
        if existing:
            # Update existing bundle
            await db[BUNDLES_COLLECTION].update_one(
                {"bundle_id": existing["bundle_id"]},
                {"$set": {
                    "bundle_type": bundle_type,
                    "bundle_status": bundle_status,
                    "completeness_status": completeness["completeness_status"],
                    "missing_expected_documents": completeness["missing_expected_documents"],
                    "detected_keys": all_keys,
                    "updated_at": now.isoformat(),
                }},
            )
            existing.update({
                "bundle_type": bundle_type,
                "bundle_status": bundle_status,
                "completeness_status": completeness["completeness_status"],
                "missing_expected_documents": completeness["missing_expected_documents"],
            })
            created_bundles.append(existing)
            continue

        bundle_id = f"BDL-{uuid.uuid4().hex[:8].upper()}"
        bundle_record = {
            "bundle_id": bundle_id,
            "bundle_type": bundle_type,
            "bundle_status": bundle_status,
            "linked_entity_type": linked_entity_type,
            "linked_entity_id": linked_entity_id,
            "document_ids": doc_ids,
            "document_count": len(doc_ids),
            "detected_keys": all_keys,
            "completeness_status": completeness["completeness_status"],
            "missing_expected_documents": completeness["missing_expected_documents"],
            "grouping_basis": group["grouping_basis"],
            "grouping_confidence": group["confidence"],
            "created_at": now.isoformat(),
            "updated_at": now.isoformat(),
            "notes": "",
            "original_detection": {
                "basis": group["grouping_basis"],
                "confidence": group["confidence"],
                "document_ids": doc_ids,
                "bundle_type": bundle_type,
            },
        }
        await db[BUNDLES_COLLECTION].insert_one(bundle_record.copy())
        bundle_record.pop("_id", None)
        created_bundles.append(bundle_record)

        # Enrich each member document's intelligence result with bundle info
        for did in doc_ids:
            await db[INTELLIGENCE_COLLECTION].update_one(
                {"document_id": did},
                {"$set": {
                    "bundle_id": bundle_id,
                    "bundle_type": bundle_type,
                    "bundle_status": bundle_status,
                    "bundle_completeness_status": completeness["completeness_status"],
                    "related_document_count": len(doc_ids) - 1,
                }},
            )

        # Activities
        await _create_activity(
            db, bundle_id, "bundle", "bundle_detected",
            f"Bundle detected: {bundle_type} with {len(doc_ids)} documents",
            f"Basis: {group['grouping_basis']}, Confidence: {group['confidence']:.0%}",
            metadata={"document_ids": doc_ids, "bundle_type": bundle_type},
        )
        for did in doc_ids:
            await _create_activity(
                db, did, "document", "added_to_bundle",
                f"Added to bundle {bundle_id} ({bundle_type})",
                metadata={"bundle_id": bundle_id},
            )

    return {
        "bundles_detected": len(created_bundles),
        "bundles": created_bundles,
        "documents_scanned": len(intel_docs),
    }


async def get_bundle(bundle_id: str) -> Optional[Dict[str, Any]]:
    """Get full bundle detail with member documents and completeness analysis."""
    db = get_db()
    bundle = await db[BUNDLES_COLLECTION].find_one(
        {"bundle_id": bundle_id}, {"_id": 0}
    )
    if not bundle:
        return None

    # Enrich with member document details
    members = []
    for did in bundle.get("document_ids", []):
        intel = await db[INTELLIGENCE_COLLECTION].find_one(
            {"document_id": did}, {"_id": 0}
        )
        doc = await db.hub_documents.find_one(
            {"id": did},
            {"_id": 0, "id": 1, "file_name": 1, "status": 1, "suggested_job_type": 1,
             "automation_readiness": 1, "automation_readiness_score": 1},
        )
        members.append({
            "document_id": did,
            "file_name": doc.get("file_name", "") if doc else "",
            "document_type": intel.get("document_type", "") if intel else "",
            "classification_confidence": intel.get("classification_confidence", 0) if intel else 0,
            "automation_readiness": intel.get("automation_readiness", "") if intel else "",
            "automation_readiness_score": intel.get("automation_readiness_score", 0) if intel else 0,
            "transaction_match_status": intel.get("transaction_match_status", "") if intel else "",
            "entity_resolution_status": intel.get("entity_resolution_status", "") if intel else "",
            "status": doc.get("status", "") if doc else "",
        })

    # Compute suggested next action
    next_action = _compute_next_action(bundle, members)

    bundle["member_documents"] = members
    bundle["suggested_next_action"] = next_action
    return bundle


async def list_bundles(
    bundle_type: Optional[str] = None,
    bundle_status: Optional[str] = None,
    completeness_status: Optional[str] = None,
    linked_entity_type: Optional[str] = None,
    linked_entity_id: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """List bundles with optional filters."""
    db = get_db()
    query = {}
    if bundle_type:
        query["bundle_type"] = bundle_type
    if bundle_status:
        query["bundle_status"] = bundle_status
    if completeness_status:
        query["completeness_status"] = completeness_status
    if linked_entity_type:
        query["linked_entity_type"] = linked_entity_type
    if linked_entity_id:
        query["linked_entity_id"] = linked_entity_id

    total = await db[BUNDLES_COLLECTION].count_documents(query)
    bundles = await db[BUNDLES_COLLECTION].find(
        query, {"_id": 0}
    ).sort("updated_at", -1).skip(offset).limit(limit).to_list(limit)

    # Status counts
    all_bundles = await db[BUNDLES_COLLECTION].find({}, {"_id": 0, "bundle_status": 1, "completeness_status": 1}).to_list(1000)
    status_counts = {}
    completeness_counts = {}
    for b in all_bundles:
        s = b.get("bundle_status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1
        c = b.get("completeness_status", "unknown")
        completeness_counts[c] = completeness_counts.get(c, 0) + 1

    return {
        "total": total,
        "bundles": bundles,
        "status_counts": status_counts,
        "completeness_counts": completeness_counts,
    }


async def update_bundle(
    bundle_id: str,
    bundle_type: Optional[str] = None,
    bundle_status: Optional[str] = None,
    notes: Optional[str] = None,
    add_document_ids: Optional[List[str]] = None,
    remove_document_ids: Optional[List[str]] = None,
    updated_by: str = "admin",
) -> Dict[str, Any]:
    """Manually update a bundle — reclassify, add/remove docs, mark reviewed."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    bundle = await db[BUNDLES_COLLECTION].find_one(
        {"bundle_id": bundle_id}, {"_id": 0}
    )
    if not bundle:
        raise ValueError(f"Bundle not found: {bundle_id}")

    updates = {"updated_at": now}
    changes = []

    if bundle_type and bundle_type != bundle.get("bundle_type"):
        changes.append(f"type: {bundle.get('bundle_type')} → {bundle_type}")
        updates["bundle_type"] = bundle_type

    if bundle_status and bundle_status != bundle.get("bundle_status"):
        changes.append(f"status: {bundle.get('bundle_status')} → {bundle_status}")
        updates["bundle_status"] = bundle_status

    if notes is not None:
        updates["notes"] = notes

    doc_ids = list(bundle.get("document_ids", []))

    if add_document_ids:
        for did in add_document_ids:
            if did not in doc_ids:
                doc_ids.append(did)
                changes.append(f"added doc: {did}")
                # Enrich added doc
                await db[INTELLIGENCE_COLLECTION].update_one(
                    {"document_id": did},
                    {"$set": {
                        "bundle_id": bundle_id,
                        "bundle_type": updates.get("bundle_type", bundle.get("bundle_type")),
                        "bundle_status": updates.get("bundle_status", bundle.get("bundle_status")),
                        "related_document_count": len(doc_ids) - 1,
                    }},
                )
                await _create_activity(
                    db, did, "document", "added_to_bundle",
                    f"Manually added to bundle {bundle_id}",
                    metadata={"bundle_id": bundle_id, "added_by": updated_by},
                )

    if remove_document_ids:
        for did in remove_document_ids:
            if did in doc_ids:
                doc_ids.remove(did)
                changes.append(f"removed doc: {did}")
                # Clear bundle info from removed doc
                await db[INTELLIGENCE_COLLECTION].update_one(
                    {"document_id": did},
                    {"$unset": {
                        "bundle_id": "", "bundle_type": "", "bundle_status": "",
                        "bundle_completeness_status": "", "related_document_count": "",
                    }},
                )

    updates["document_ids"] = doc_ids
    updates["document_count"] = len(doc_ids)

    # Re-evaluate completeness
    if doc_ids:
        intel_docs = await db[INTELLIGENCE_COLLECTION].find(
            {"document_id": {"$in": doc_ids}}, {"_id": 0, "document_type": 1}
        ).to_list(50)
        doc_types = [d.get("document_type", "unknown") for d in intel_docs]
        bt = updates.get("bundle_type", bundle.get("bundle_type", BUNDLE_TYPE_UNKNOWN))
        comp = _evaluate_completeness(bt, doc_types, len(doc_ids))
        updates["completeness_status"] = comp["completeness_status"]
        updates["missing_expected_documents"] = comp["missing_expected_documents"]

        if comp["completeness_status"] != bundle.get("completeness_status"):
            changes.append(f"completeness: {bundle.get('completeness_status')} → {comp['completeness_status']}")
            await _create_activity(
                db, bundle_id, "bundle", "bundle_completeness_changed",
                f"Bundle completeness changed to {comp['completeness_status']}",
                metadata={"missing": comp["missing_expected_documents"]},
            )

        # Update member docs with new bundle info
        for did in doc_ids:
            await db[INTELLIGENCE_COLLECTION].update_one(
                {"document_id": did},
                {"$set": {
                    "bundle_status": updates.get("bundle_status", bundle.get("bundle_status")),
                    "bundle_completeness_status": comp["completeness_status"],
                    "related_document_count": len(doc_ids) - 1,
                    "bundle_type": bt,
                }},
            )

    await db[BUNDLES_COLLECTION].update_one(
        {"bundle_id": bundle_id}, {"$set": updates}
    )

    if changes:
        await _create_activity(
            db, bundle_id, "bundle", "bundle_manually_corrected",
            f"Bundle updated by {updated_by}: {'; '.join(changes)}",
            metadata={"changes": changes, "updated_by": updated_by},
        )

    return await db[BUNDLES_COLLECTION].find_one(
        {"bundle_id": bundle_id}, {"_id": 0}
    )


async def get_bundle_review_queue(
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Get bundles needing review — needs_review status or incomplete completeness."""
    db = get_db()
    query = {
        "$or": [
            {"bundle_status": STATUS_NEEDS_REVIEW},
            {"completeness_status": {"$ne": COMPLETENESS_COMPLETE}},
        ]
    }
    total = await db[BUNDLES_COLLECTION].count_documents(query)
    bundles = await db[BUNDLES_COLLECTION].find(
        query, {"_id": 0}
    ).sort("updated_at", -1).skip(offset).limit(limit).to_list(limit)

    # Enrich with suggested next action
    for b in bundles:
        b["suggested_next_action"] = _compute_next_action_simple(b)

    return {"total": total, "bundles": bundles}


async def get_document_bundle_info(doc_id: str) -> Optional[Dict[str, Any]]:
    """Get bundle information for a specific document."""
    db = get_db()
    bundle = await db[BUNDLES_COLLECTION].find_one(
        {"document_ids": doc_id}, {"_id": 0}
    )
    return bundle


def _compute_next_action(bundle: Dict, members: List[Dict]) -> str:
    """Compute suggested next action based on bundle state and member statuses."""
    comp = bundle.get("completeness_status", "")
    status = bundle.get("bundle_status", "")

    if status == STATUS_NEEDS_REVIEW:
        return "Review bundle grouping — uncertain match"
    if comp == COMPLETENESS_INSUFFICIENT:
        return "Incomplete packet — add missing documents"
    if comp == COMPLETENESS_PARTIAL:
        missing = bundle.get("missing_expected_documents", [])
        if missing:
            return f"Partial packet — {missing[0]}"
        return "Partial packet — review and add supporting documents"

    # Check if members are automation-ready
    all_ready = all(m.get("automation_readiness") == "ready" for m in members)
    any_linked = any(m.get("transaction_match_status") == "confirmed" for m in members)

    if comp == COMPLETENESS_COMPLETE and all_ready and any_linked:
        return "Ready — link existing transaction"
    if comp == COMPLETENESS_COMPLETE and all_ready:
        return "Ready — create draft or link existing"
    if comp == COMPLETENESS_COMPLETE:
        return "Complete packet — review member documents"

    return "Review bundle"


def _compute_next_action_simple(bundle: Dict) -> str:
    """Compute next action from bundle data alone (no member enrichment)."""
    comp = bundle.get("completeness_status", "")
    status = bundle.get("bundle_status", "")

    if status == STATUS_NEEDS_REVIEW:
        return "Review bundle grouping"
    if comp == COMPLETENESS_INSUFFICIENT:
        missing = bundle.get("missing_expected_documents", [])
        return f"Incomplete — {missing[0]}" if missing else "Incomplete packet"
    if comp == COMPLETENESS_PARTIAL:
        missing = bundle.get("missing_expected_documents", [])
        return f"Partial — {missing[0]}" if missing else "Partial packet"
    if comp == COMPLETENESS_COMPLETE:
        return "Complete — ready for review"
    return "Review bundle"
