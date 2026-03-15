"""
GPI Document Hub - Document Lifecycle Validation Service

Evaluates whether the set of documents connected to a transaction represents
a valid and complete business lifecycle. Detects missing docs, duplicates,
out-of-order events, and inconsistencies.

SAFETY: No inventory mutations, no BC calls, no auto-finalization.
Validation is advisory and analytical only.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from deps import get_db

logger = logging.getLogger(__name__)

VALIDATIONS_COLLECTION = "lifecycle_validations"
INTELLIGENCE_COLLECTION = "document_intelligence_results"
BUNDLES_COLLECTION = "document_bundles"
ACTIVITIES_COLLECTION = "activities"

# Validation statuses
VS_VALID = "valid"
VS_INCOMPLETE = "incomplete"
VS_DUPLICATE = "duplicate_detected"
VS_INCONSISTENT = "inconsistent"
VS_NEEDS_REVIEW = "needs_review"

# ── Lifecycle Templates ──────────────────────────────────────────────────────

SALES_ORDER_STAGES = [
    {"stage": "order_received", "doc_types": ["Sales_PO", "customer_po"], "required": True, "label": "Customer PO"},
    {"stage": "order_created", "doc_types": ["Sales_Order", "Order_Confirmation"], "required": False, "label": "Sales Order / Confirmation"},
    {"stage": "proofing", "doc_types": ["Quality_Issue"], "required": False, "label": "Artwork / Proof"},
    {"stage": "shipped", "doc_types": ["Shipping_Document", "Freight_Document"], "required": False, "label": "Shipment Document"},
    {"stage": "invoiced", "doc_types": ["AP_Invoice", "invoice"], "required": False, "label": "Invoice"},
]

PURCHASING_STAGES = [
    {"stage": "po_created", "doc_types": ["Freight_Document", "Shipping_Document", "vendor_po_support"], "required": True, "label": "PO Support Document"},
    {"stage": "po_drafted", "doc_types": ["Sales_PO", "Sales_Order"], "required": False, "label": "PO Draft"},
    {"stage": "received", "doc_types": ["Shipping_Document", "Warehouse_Document"], "required": False, "label": "Receiving / Shipment Doc"},
    {"stage": "vendor_invoiced", "doc_types": ["AP_Invoice", "invoice"], "required": False, "label": "Vendor Invoice"},
]

AP_STAGES = [
    {"stage": "invoice_received", "doc_types": ["AP_Invoice", "invoice"], "required": True, "label": "Invoice"},
    {"stage": "receiving_support", "doc_types": ["Shipping_Document", "Freight_Document", "Warehouse_Document", "Remittance"], "required": False, "label": "Receiving / Support Doc"},
    {"stage": "ap_drafted", "doc_types": ["ap_intake_draft"], "required": False, "label": "AP Draft"},
]

LIFECYCLE_TEMPLATES = {
    "so_draft": {"name": "Sales Order", "stages": SALES_ORDER_STAGES},
    "sales_order": {"name": "Sales Order", "stages": SALES_ORDER_STAGES},
    "customer_order_packet": {"name": "Sales Order", "stages": SALES_ORDER_STAGES},
    "po_draft": {"name": "Purchasing", "stages": PURCHASING_STAGES},
    "purchasing_packet": {"name": "Purchasing", "stages": PURCHASING_STAGES},
    "ap_intake_draft": {"name": "Accounts Payable", "stages": AP_STAGES},
    "ap_packet": {"name": "Accounts Payable", "stages": AP_STAGES},
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


def _detect_stage(doc_types: List[str], stages: List[Dict]) -> Dict[str, Any]:
    """Walk the lifecycle stages and find the current + next."""
    types_set = set(doc_types)
    detected_stage = None
    expected_next = None
    completed_stages = []
    missing_stages = []

    for i, stage in enumerate(stages):
        stage_types = set(stage["doc_types"])
        if types_set & stage_types:
            detected_stage = stage["stage"]
            completed_stages.append(stage["stage"])
        elif stage["required"]:
            missing_stages.append(stage)

    # Expected next: first stage after the last completed one that isn't completed
    if detected_stage:
        last_idx = max(
            (i for i, s in enumerate(stages) if s["stage"] in completed_stages),
            default=-1,
        )
        for j in range(last_idx + 1, len(stages)):
            if stages[j]["stage"] not in completed_stages:
                expected_next = stages[j]["stage"]
                break

    if not detected_stage:
        detected_stage = "unknown"
        expected_next = stages[0]["stage"] if stages else None

    return {
        "detected_stage": detected_stage,
        "expected_next_stage": expected_next,
        "completed_stages": completed_stages,
        "missing_stages": missing_stages,
    }


def _detect_duplicates(intel_docs: List[Dict]) -> List[Dict]:
    """Detect duplicate documents by invoice number+vendor, PO+vendor, reference collisions."""
    duplicates = []

    # Group by invoice_number + vendor
    inv_map = {}
    po_map = {}
    for doc in intel_docs:
        fields = doc.get("extracted_fields", {})
        inv = fields.get("invoice_number") or fields.get("invoice_no") or ""
        vendor = fields.get("vendor") or fields.get("vendor_name") or ""
        po = fields.get("po_number") or fields.get("customer_po") or fields.get("order_number") or ""

        if inv and vendor:
            key = f"{str(inv).strip().upper()}|{str(vendor).strip().upper()}"
            inv_map.setdefault(key, []).append(doc["document_id"])

        if po and vendor:
            key = f"{str(po).strip().upper()}|{str(vendor).strip().upper()}"
            po_map.setdefault(key, []).append(doc["document_id"])

    for key, ids in inv_map.items():
        if len(ids) >= 2:
            inv_num, vend = key.split("|", 1)
            duplicates.append({
                "type": "duplicate_invoice",
                "reference": inv_num,
                "vendor": vend,
                "document_ids": ids,
                "message": f"Duplicate invoice {inv_num} from {vend} ({len(ids)} documents)",
            })

    for key, ids in po_map.items():
        if len(ids) >= 2:
            po_num, vend = key.split("|", 1)
            duplicates.append({
                "type": "duplicate_po",
                "reference": po_num,
                "vendor": vend,
                "document_ids": ids,
                "message": f"Duplicate PO {po_num} from {vend} ({len(ids)} documents)",
            })

    return duplicates


def _check_inconsistencies(intel_docs: List[Dict], stages: List[Dict], completed_stages: List[str]) -> List[Dict]:
    """Check for reference mismatches and out-of-order events."""
    inconsistencies = []

    # Collect all customer/vendor references
    customers = set()
    vendors = set()
    for doc in intel_docs:
        fields = doc.get("extracted_fields", {})
        cust = fields.get("customer") or fields.get("customer_name") or ""
        vend = fields.get("vendor") or fields.get("vendor_name") or ""
        if cust and str(cust).strip():
            customers.add(str(cust).strip().upper())
        if vend and str(vend).strip():
            vendors.add(str(vend).strip().upper())

    if len(customers) > 1:
        inconsistencies.append({
            "type": "mismatched_customer",
            "message": f"Multiple customer references found: {', '.join(customers)}",
            "values": list(customers),
        })
    if len(vendors) > 1:
        inconsistencies.append({
            "type": "mismatched_vendor",
            "message": f"Multiple vendor references found: {', '.join(vendors)}",
            "values": list(vendors),
        })

    # Check for out-of-order: e.g., invoice exists but no PO for purchasing
    stage_names = [s["stage"] for s in stages]
    if completed_stages:
        first_completed_idx = min(
            (stage_names.index(s) for s in completed_stages if s in stage_names),
            default=0,
        )
        last_completed_idx = max(
            (stage_names.index(s) for s in completed_stages if s in stage_names),
            default=0,
        )
        # Check for gaps
        for idx in range(first_completed_idx, last_completed_idx):
            stage_name = stage_names[idx]
            if stage_name not in completed_stages and stages[idx]["required"]:
                inconsistencies.append({
                    "type": "lifecycle_gap",
                    "message": f"Required stage '{stages[idx]['label']}' is missing between completed stages",
                    "stage": stage_name,
                })

    return inconsistencies


# ── Public API ──────────────────────────────────────────────────────────────

async def validate_lifecycle(entity_type: str, entity_id: str, validated_by: str = "system") -> Dict[str, Any]:
    """
    Run lifecycle validation for an entity (so_draft, po_draft, ap_intake_draft, or bundle).
    Collects all linked documents, applies lifecycle rules, detects issues.
    """
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Determine lifecycle template
    template = LIFECYCLE_TEMPLATES.get(entity_type)
    if not template:
        template = LIFECYCLE_TEMPLATES.get("ap_packet")  # fallback

    stages = template["stages"]

    # Collect documents linked to this entity
    intel_docs = []
    bundle_id = ""

    # Check if entity is a bundle
    if entity_type.endswith("_packet") or entity_type == "bundle":
        bundle = await db[BUNDLES_COLLECTION].find_one({"bundle_id": entity_id}, {"_id": 0})
        if bundle:
            bundle_id = entity_id
            doc_ids = bundle.get("document_ids", [])
            intel_docs = await db[INTELLIGENCE_COLLECTION].find(
                {"document_id": {"$in": doc_ids}}, {"_id": 0}
            ).to_list(100)
    else:
        # Find docs linked to this entity via intelligence results
        intel_docs = await db[INTELLIGENCE_COLLECTION].find(
            {"$or": [
                {"target_entity_id": entity_id},
                {"best_transaction_match.entity_id": entity_id},
            ]},
            {"_id": 0}
        ).to_list(100)

        # Also check bundle membership
        bundle = await db[BUNDLES_COLLECTION].find_one(
            {"linked_entity_id": entity_id}, {"_id": 0}
        )
        if bundle:
            bundle_id = bundle.get("bundle_id", "")
            extra_ids = [d for d in bundle.get("document_ids", [])
                         if d not in {doc["document_id"] for doc in intel_docs}]
            if extra_ids:
                extra_docs = await db[INTELLIGENCE_COLLECTION].find(
                    {"document_id": {"$in": extra_ids}}, {"_id": 0}
                ).to_list(100)
                intel_docs.extend(extra_docs)

    # Gather doc types
    doc_types = [d.get("document_type", "unknown") for d in intel_docs]

    # Stage detection
    stage_result = _detect_stage(doc_types, stages)

    # Duplicate detection
    duplicates = _detect_duplicates(intel_docs)

    # Missing document detection
    missing_docs = []
    for ms in stage_result["missing_stages"]:
        missing_docs.append({
            "stage": ms["stage"],
            "label": ms["label"],
            "expected_types": ms["doc_types"],
            "message": f"Missing: {ms['label']}",
        })

    # Inconsistency detection
    inconsistencies = _check_inconsistencies(intel_docs, stages, stage_result["completed_stages"])

    # Determine validation status
    if duplicates:
        validation_status = VS_DUPLICATE
    elif inconsistencies:
        validation_status = VS_INCONSISTENT
    elif missing_docs:
        validation_status = VS_INCOMPLETE
    elif not intel_docs:
        validation_status = VS_NEEDS_REVIEW
    else:
        validation_status = VS_VALID

    # Build validation messages
    messages = []
    if validation_status == VS_VALID:
        messages.append(f"Lifecycle is valid — {len(intel_docs)} documents at stage '{stage_result['detected_stage']}'")
    for dup in duplicates:
        messages.append(dup["message"])
    for m in missing_docs:
        messages.append(m["message"])
    for inc in inconsistencies:
        messages.append(inc["message"])
    if not intel_docs:
        messages.append("No documents found for this entity")

    # Recommended next action
    if validation_status == VS_VALID:
        if stage_result["expected_next_stage"]:
            next_action = f"Awaiting next stage: {stage_result['expected_next_stage']}"
        else:
            next_action = "Lifecycle complete — all expected documents present"
    elif validation_status == VS_DUPLICATE:
        next_action = "Review and resolve duplicate documents"
    elif validation_status == VS_INCONSISTENT:
        next_action = "Review reference inconsistencies"
    elif validation_status == VS_INCOMPLETE:
        next_action = f"Add missing document: {missing_docs[0]['label']}" if missing_docs else "Add missing documents"
    else:
        next_action = "Review lifecycle — no documents found"

    validation_id = f"LCV-{uuid.uuid4().hex[:8].upper()}"
    record = {
        "lifecycle_validation_id": validation_id,
        "entity_type": entity_type,
        "entity_id": entity_id,
        "bundle_id": bundle_id,
        "validation_status": validation_status,
        "detected_stage": stage_result["detected_stage"],
        "expected_next_stage": stage_result["expected_next_stage"],
        "completed_stages": stage_result["completed_stages"],
        "missing_documents": missing_docs,
        "duplicate_documents": duplicates,
        "inconsistent_references": inconsistencies,
        "validation_messages": messages,
        "recommended_next_action": next_action,
        "document_count": len(intel_docs),
        "document_ids": [d["document_id"] for d in intel_docs],
        "lifecycle_template": template["name"],
        "validated_at": now,
        "validated_by": validated_by,
        "notes": "",
    }

    # Upsert — one validation per entity
    await db[VALIDATIONS_COLLECTION].update_one(
        {"entity_type": entity_type, "entity_id": entity_id},
        {"$set": record},
        upsert=True,
    )
    # Remove _id if inserted
    stored = await db[VALIDATIONS_COLLECTION].find_one(
        {"lifecycle_validation_id": validation_id}, {"_id": 0}
    )

    # Enrich bundle with lifecycle info
    if bundle_id:
        await db[BUNDLES_COLLECTION].update_one(
            {"bundle_id": bundle_id},
            {"$set": {
                "lifecycle_validation_status": validation_status,
                "lifecycle_stage": stage_result["detected_stage"],
                "lifecycle_missing_documents": [m["message"] for m in missing_docs],
            }},
        )

    # Enrich member documents
    for doc in intel_docs:
        await db[INTELLIGENCE_COLLECTION].update_one(
            {"document_id": doc["document_id"]},
            {"$set": {
                "lifecycle_status": validation_status,
                "lifecycle_stage": stage_result["detected_stage"],
                "lifecycle_missing_documents": [m["message"] for m in missing_docs],
                "lifecycle_duplicate_flags": [d["message"] for d in duplicates],
            }},
        )

    # Activity events
    await _create_activity(
        db, entity_id, entity_type, "lifecycle_validated",
        f"Lifecycle validation: {validation_status} — stage: {stage_result['detected_stage']}",
        f"{len(intel_docs)} documents analyzed. {len(messages)} messages.",
        metadata={"validation_id": validation_id, "status": validation_status},
    )

    if missing_docs:
        await _create_activity(
            db, entity_id, entity_type, "missing_document_detected",
            f"Missing documents detected: {', '.join(m['label'] for m in missing_docs)}",
            metadata={"missing": [m["label"] for m in missing_docs]},
        )

    if duplicates:
        await _create_activity(
            db, entity_id, entity_type, "duplicate_detected",
            f"Duplicate documents detected: {', '.join(d['message'] for d in duplicates)}",
            metadata={"duplicates": [d["message"] for d in duplicates]},
        )

    return stored or record


async def get_lifecycle(entity_type: str, entity_id: str) -> Optional[Dict[str, Any]]:
    """Get the latest lifecycle validation for an entity."""
    db = get_db()
    result = await db[VALIDATIONS_COLLECTION].find_one(
        {"entity_type": entity_type, "entity_id": entity_id},
        {"_id": 0},
    )
    if not result:
        return None

    # Enrich with document details
    doc_ids = result.get("document_ids", [])
    documents = []
    for did in doc_ids:
        intel = await db[INTELLIGENCE_COLLECTION].find_one({"document_id": did}, {"_id": 0})
        hub_doc = await db.hub_documents.find_one(
            {"id": did}, {"_id": 0, "id": 1, "file_name": 1, "status": 1}
        )
        documents.append({
            "document_id": did,
            "file_name": hub_doc.get("file_name", "") if hub_doc else "",
            "document_type": intel.get("document_type", "") if intel else "",
            "automation_readiness": intel.get("automation_readiness", "") if intel else "",
            "status": hub_doc.get("status", "") if hub_doc else "",
        })
    result["documents"] = documents
    return result


async def get_lifecycle_issues(
    issue_type: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Get entities with lifecycle issues (not valid)."""
    db = get_db()
    query = {"validation_status": {"$ne": VS_VALID}}
    if issue_type:
        query["validation_status"] = issue_type
    if entity_type:
        query["entity_type"] = entity_type

    total = await db[VALIDATIONS_COLLECTION].count_documents(query)
    issues = await db[VALIDATIONS_COLLECTION].find(
        query, {"_id": 0}
    ).sort([
        ("validation_status", 1),  # duplicate_detected first, then incomplete, inconsistent
        ("validated_at", -1),
    ]).skip(offset).limit(limit).to_list(limit)

    # Status counts
    all_validations = await db[VALIDATIONS_COLLECTION].find(
        {}, {"_id": 0, "validation_status": 1}
    ).to_list(1000)
    status_counts = {}
    for v in all_validations:
        s = v.get("validation_status", "unknown")
        status_counts[s] = status_counts.get(s, 0) + 1

    return {
        "total": total,
        "issues": issues,
        "status_counts": status_counts,
    }
