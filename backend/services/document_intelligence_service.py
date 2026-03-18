"""
GPI Document Hub - Document Intelligence Service

Centralizes the document processing pipeline into a single orchestrator:
  classify → extract → validate → derive automation readiness → store → emit events

Imports intelligence logic from document_intel_helpers (extracted from server.py)
and ai_classifier.
"""

import os
import uuid
import logging
from datetime import datetime, timezone
from pathlib import Path
from typing import Dict, Any, Optional, List

from deps import get_db
from models.document_types import DEFAULT_JOB_TYPES
from services.automation_helpers import utcnow, create_activity

# Upload directory — same convention as server.py / document_handlers.py
UPLOAD_DIR = Path(os.environ.get("UPLOAD_DIR", "/app/backend/uploads"))

logger = logging.getLogger(__name__)

# Collections
INTELLIGENCE_COLLECTION = "document_intelligence_results"
AUTOMATION_ACTIONS_COLLECTION = "automation_actions"
SO_DRAFTS_COLLECTION = "so_drafts"
AP_INTAKE_DRAFTS_COLLECTION = "ap_intake_drafts"
PO_DRAFTS_COLLECTION = "po_drafts"

# Automation readiness levels
READINESS_READY = "ready"
READINESS_NEEDS_REVIEW = "needs_review"
READINESS_BLOCKED = "blocked"

# Model metadata
MODEL_NAME = "gemini-3-flash-preview"
MODEL_PROVIDER = "gemini"
PROMPT_VERSION = "1.0"


def _get_extraction_schema(doc_type: str) -> Dict[str, Any]:
    """Get required and optional extraction fields for a document type."""
    job_config = DEFAULT_JOB_TYPES.get(doc_type, {})
    if not job_config:
        # Try common mappings
        type_map = {
            "AP_INVOICE": "AP_Invoice",
            "SALES_INVOICE": "AR_Invoice",
            "PURCHASE_ORDER": "Sales_PO",
            "SALES_ORDER": "Sales_PO",
            "SALES_CREDIT_MEMO": "AR_Invoice",
            "PURCHASE_CREDIT_MEMO": "AP_Invoice",
            "STATEMENT": "Statement",
            "REMINDER": "Reminder",
            "QUALITY_DOC": "Quality_Issue",
            "PACKING_SLIP": "Shipping_Document",
            "BILL_OF_LADING": "Shipping_Document",
        }
        mapped = type_map.get(doc_type, "AP_Invoice")
        job_config = DEFAULT_JOB_TYPES.get(mapped, DEFAULT_JOB_TYPES.get("AP_Invoice", {}))
    return {
        "required": job_config.get("required_extractions", []),
        "optional": job_config.get("optional_extractions", []),
    }


def _derive_automation_readiness(
    classification_confidence: float,
    extracted_fields: Dict[str, Any],
    doc_type: str,
    validation_results: Optional[Dict] = None,
    automation_decision: Optional[str] = None,
) -> Dict[str, Any]:
    """
    Compute automation readiness based on confidence, extraction completeness,
    and validation results.

    Returns dict with:
      - status: ready | needs_review | blocked
      - reasons: list of reason strings
      - score: 0-100 numeric readiness score
    """
    reasons: List[str] = []
    score = 0

    # 1) Classification confidence contributes up to 40 points
    if classification_confidence >= 0.90:
        score += 40
    elif classification_confidence >= 0.75:
        score += 25
        reasons.append(f"moderate_classification_confidence ({classification_confidence:.0%})")
    elif classification_confidence >= 0.50:
        score += 10
        reasons.append(f"low_classification_confidence ({classification_confidence:.0%})")
    else:
        reasons.append(f"very_low_classification_confidence ({classification_confidence:.0%})")

    # 2) Extraction completeness contributes up to 40 points
    schema = _get_extraction_schema(doc_type)
    required = schema["required"]
    optional = schema["optional"]

    missing_required = []
    for field in required:
        val = extracted_fields.get(field)
        if not val or (isinstance(val, str) and not val.strip()):
            missing_required.append(field)

    if not missing_required:
        score += 40
    else:
        # Partial credit
        if required:
            filled = len(required) - len(missing_required)
            score += int(40 * (filled / len(required)))
        for f in missing_required:
            reasons.append(f"missing_{f}")

    present_optional = 0
    for field in optional:
        val = extracted_fields.get(field)
        if val and (not isinstance(val, str) or val.strip()):
            present_optional += 1
    if optional:
        score += int(10 * (present_optional / len(optional)))

    # 3) Validation results contribute up to 10 points
    if validation_results:
        if validation_results.get("all_passed"):
            score += 10
        else:
            failed = [
                c["check_name"]
                for c in validation_results.get("checks", [])
                if not c.get("passed") and c.get("required", True)
            ]
            for f in failed:
                reasons.append(f"validation_failed_{f}")

    # 4) Existing automation decision as signal
    if automation_decision == "auto_link":
        score = max(score, 80)
    elif automation_decision == "auto_create":
        score = max(score, 90)

    # Determine status
    if missing_required:
        status = READINESS_BLOCKED
    elif score >= 75:
        status = READINESS_READY
    elif score >= 40:
        status = READINESS_NEEDS_REVIEW
    else:
        status = READINESS_BLOCKED

    return {
        "status": status,
        "reasons": reasons,
        "score": min(score, 100),
    }


async def process_document(doc_id: str) -> Dict[str, Any]:
    """
    Run the full document intelligence pipeline on a document.

    Delegates to the 5-stage classification_pipeline, then persists results,
    computes folder routing, and emits events.
    """
    db = get_db()

    # 1) Fetch document
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise ValueError(f"Document not found: {doc_id}")

    started_at = datetime.now(timezone.utc)
    result_id = uuid.uuid4().hex[:12]

    # 2) Run the 5-stage pipeline
    from services.classification_pipeline import run_pipeline
    pipeline = await run_pipeline(doc_id, doc)

    document_type = pipeline.document_type
    classification_confidence = pipeline.classification_confidence
    ai_extracted_fields = pipeline.extracted_fields
    validation_results = pipeline.validation_results
    automation_decision = pipeline.automation_decision
    automation_reasoning = pipeline.automation_reasoning

    readiness = {
        "status": pipeline.readiness_status,
        "score": pipeline.readiness_score,
        "reasons": pipeline.readiness_reasons,
    }

    ended_at = datetime.now(timezone.utc)

    # 3) Build intelligence result
    intelligence_result = {
        "result_id": result_id,
        "document_id": doc_id,
        "document_type": document_type,
        "classification_confidence": round(classification_confidence, 4),
        "extracted_fields": ai_extracted_fields,
        "extraction_schema": _get_extraction_schema(document_type),
        "validation_results": validation_results,
        "automation_decision": automation_decision,
        "automation_reasoning": automation_reasoning,
        "automation_readiness": readiness["status"],
        "automation_readiness_score": readiness["score"],
        "automation_readiness_reasons": readiness["reasons"],
        "model_name": MODEL_NAME,
        "model_provider": MODEL_PROVIDER,
        "prompt_version": PROMPT_VERSION,
        "processed_at": ended_at.isoformat(),
        "processing_duration_ms": int((ended_at - started_at).total_seconds() * 1000),
        "manually_corrected": False,
        "correction_history": [],
        # Pipeline metadata for debugging
        "pipeline_status": pipeline.final_status,
        "pipeline_failure_stage": pipeline.failure_stage,
        "pipeline_failure_reason": pipeline.failure_reason,
        "pipeline_stages": {
            name: {
                "status": sr.status.value,
                "quality_gate": sr.quality_gate_passed,
                "error": sr.error,
                "ms": sr.duration_ms,
            }
            for name, sr in pipeline.stages.items()
        },
        "classification_method": pipeline.classification_method,
        "meaningful_field_count": pipeline.meaningful_field_count,
    }

    # 4) Store in dedicated collection (upsert by document_id)
    await db[INTELLIGENCE_COLLECTION].update_one(
        {"document_id": doc_id},
        {"$set": intelligence_result},
        upsert=True,
    )

    # 5) Update hub_documents with key intelligence fields
    doc_update = {
        "intelligence_result_id": result_id,
        "automation_readiness": readiness["status"],
        "automation_readiness_score": readiness["score"],
        "automation_readiness_reasons": readiness["reasons"],
        "automation_decision": automation_decision,
        "ai_confidence": classification_confidence,
        "suggested_job_type": document_type,
        "extracted_fields": ai_extracted_fields,
        "validation_results": validation_results,
        "intelligence_processed_at": ended_at.isoformat(),
        "updated_utc": ended_at.isoformat(),
    }
    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc_update})

    # 8b) Compute and store SharePoint folder suggestion
    try:
        from services.folder_routing_service import determine_folder_path
        updated_doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
        if updated_doc:
            ef = ai_extracted_fields or {}
            if ef.get("is_international"):
                updated_doc["is_international"] = True
            folder_path, folder_reason, _ = determine_folder_path(
                doc=updated_doc,
                freight_direction=ef.get("freight_direction"),
                is_international=bool(ef.get("is_international")),
            )
            await db.hub_documents.update_one(
                {"id": doc_id},
                {"$set": {
                    "sharepoint_folder_suggested": folder_path,
                    "sharepoint_folder_reason": folder_reason,
                }}
            )
            intelligence_result["sharepoint_folder_suggested"] = folder_path
            intelligence_result["sharepoint_folder_reason"] = folder_reason
    except Exception as e:
        logger.warning("Folder routing failed for %s: %s", doc_id, e)

    # 9) Emit event
    try:
        from services.event_service import get_event_service
        event_service = get_event_service()
        if event_service:
            await event_service.emit(
                "document_intelligence.processed",
                {
                    "document_id": doc_id,
                    "document_type": document_type,
                    "confidence": classification_confidence,
                    "automation_readiness": readiness["status"],
                    "readiness_score": readiness["score"],
                },
            )
    except Exception:
        pass  # Non-critical

    return intelligence_result


async def get_intelligence_result(doc_id: str) -> Optional[Dict[str, Any]]:
    """Get the latest intelligence result for a document."""
    db = get_db()
    result = await db[INTELLIGENCE_COLLECTION].find_one(
        {"document_id": doc_id}, {"_id": 0}
    )
    return result


async def get_review_queue(
    status_filter: Optional[str] = None,
    doc_type_filter: Optional[str] = None,
    sort_by: str = "readiness_score",
    sort_order: int = 1,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """
    Get documents needing human review from the intelligence results.

    Returns items where automation_readiness is 'needs_review' or 'blocked'.
    """
    db = get_db()

    match: Dict[str, Any] = {}
    if status_filter and status_filter in (READINESS_NEEDS_REVIEW, READINESS_BLOCKED, READINESS_READY):
        match["automation_readiness"] = status_filter
    else:
        match["automation_readiness"] = {"$in": [READINESS_NEEDS_REVIEW, READINESS_BLOCKED]}

    if doc_type_filter:
        match["document_type"] = doc_type_filter

    # Get total count
    total = await db[INTELLIGENCE_COLLECTION].count_documents(match)

    # Get counts by status
    status_pipeline = [
        {"$match": match if status_filter else {}},
        {"$group": {"_id": "$automation_readiness", "count": {"$sum": 1}}},
    ]
    status_counts_raw = await db[INTELLIGENCE_COLLECTION].aggregate(status_pipeline).to_list(10)
    status_counts = {r["_id"]: r["count"] for r in status_counts_raw if r["_id"]}

    # Sort
    sort_field = "automation_readiness_score" if sort_by == "readiness_score" else sort_by
    cursor = (
        db[INTELLIGENCE_COLLECTION]
        .find(match, {"_id": 0})
        .sort(sort_field, sort_order)
        .skip(offset)
        .limit(limit)
    )
    items = await cursor.to_list(limit)

    # Enrich with document metadata
    if items:
        doc_ids = [item["document_id"] for item in items]
        docs = await db.hub_documents.find(
            {"id": {"$in": doc_ids}},
            {
                "_id": 0,
                "id": 1,
                "file_name": 1,
                "status": 1,
                "category": 1,
                "email_sender": 1,
                "email_subject": 1,
                "created_utc": 1,
                "source_system": 1,
            },
        ).to_list(len(doc_ids))
        doc_map = {d["id"]: d for d in docs}

        for item in items:
            doc_meta = doc_map.get(item["document_id"], {})
            item["file_name"] = doc_meta.get("file_name", "")
            item["doc_status"] = doc_meta.get("status", "")
            item["category"] = doc_meta.get("category", "")
            item["email_sender"] = doc_meta.get("email_sender", "")
            item["email_subject"] = doc_meta.get("email_subject", "")
            item["created_utc"] = doc_meta.get("created_utc", "")
            item["source_system"] = doc_meta.get("source_system", "")

    return {
        "items": items,
        "total": total,
        "status_counts": status_counts,
        "limit": limit,
        "offset": offset,
    }


async def apply_correction(
    doc_id: str,
    corrected_type: Optional[str] = None,
    corrected_fields: Optional[Dict[str, Any]] = None,
    corrected_by: str = "admin",
    correction_notes: str = "",
) -> Dict[str, Any]:
    """
    Apply manual corrections to intelligence result and re-derive readiness.
    """
    db = get_db()

    existing = await db[INTELLIGENCE_COLLECTION].find_one(
        {"document_id": doc_id}, {"_id": 0}
    )
    if not existing:
        raise ValueError(f"No intelligence result for document: {doc_id}")

    now = utcnow()

    # Build correction history entry
    correction_entry = {
        "corrected_at": now,
        "corrected_by": corrected_by,
        "notes": correction_notes,
        "changes": {},
    }

    updated = {}

    if corrected_type and corrected_type != existing.get("document_type"):
        correction_entry["changes"]["document_type"] = {
            "from": existing.get("document_type"),
            "to": corrected_type,
        }
        updated["document_type"] = corrected_type
        updated["extraction_schema"] = _get_extraction_schema(corrected_type)

    if corrected_fields:
        old_fields = existing.get("extracted_fields", {})
        field_changes = {}
        for key, val in corrected_fields.items():
            if old_fields.get(key) != val:
                field_changes[key] = {"from": old_fields.get(key), "to": val}
        if field_changes:
            correction_entry["changes"]["extracted_fields"] = field_changes
            merged = {**old_fields, **corrected_fields}
            updated["extracted_fields"] = merged

    if not correction_entry["changes"]:
        return existing  # No actual changes

    # Re-derive readiness with corrected values
    doc_type = updated.get("document_type", existing["document_type"])
    fields = updated.get("extracted_fields", existing.get("extracted_fields", {}))
    confidence = existing.get("classification_confidence", 0.0)

    # If type was corrected, treat it as high confidence
    if corrected_type:
        confidence = 1.0
        updated["classification_confidence"] = 1.0

    readiness = _derive_automation_readiness(
        classification_confidence=confidence,
        extracted_fields=fields,
        doc_type=doc_type,
        validation_results=existing.get("validation_results"),
    )

    updated["automation_readiness"] = readiness["status"]
    updated["automation_readiness_score"] = readiness["score"]
    updated["automation_readiness_reasons"] = readiness["reasons"]
    updated["manually_corrected"] = True
    updated["last_corrected_at"] = now
    updated["last_corrected_by"] = corrected_by

    # Append to correction history
    history = existing.get("correction_history", [])
    history.append(correction_entry)
    updated["correction_history"] = history

    # Update intelligence result
    await db[INTELLIGENCE_COLLECTION].update_one(
        {"document_id": doc_id}, {"$set": updated}
    )

    # Update hub_documents too
    doc_update = {
        "automation_readiness": readiness["status"],
        "automation_readiness_score": readiness["score"],
        "automation_readiness_reasons": readiness["reasons"],
        "updated_utc": now,
    }
    if corrected_type:
        doc_update["suggested_job_type"] = corrected_type
        doc_update["doc_type"] = corrected_type
        doc_update["ai_confidence"] = 1.0
    if corrected_fields:
        doc_update["extracted_fields"] = fields

    await db.hub_documents.update_one({"id": doc_id}, {"$set": doc_update})

    # Emit correction event
    try:
        from services.event_service import get_event_service
        event_service = get_event_service()
        if event_service:
            await event_service.emit(
                "document_intelligence.corrected",
                {
                    "document_id": doc_id,
                    "corrected_by": corrected_by,
                    "changes": correction_entry["changes"],
                    "new_readiness": readiness["status"],
                },
            )
    except Exception:
        pass

    # Learning loop hooks
    try:
        from services.learning_loop_service import on_classification_correction, on_field_correction
        if "document_type" in correction_entry["changes"]:
            change = correction_entry["changes"]["document_type"]
            await on_classification_correction(
                doc_id, change["from"], change["to"],
                existing.get("classification_confidence", 0), corrected_by,
            )
        if "extracted_fields" in correction_entry["changes"]:
            await on_field_correction(
                doc_id, doc_type,
                correction_entry["changes"]["extracted_fields"],
                corrected_by,
            )
    except Exception as e:
        logger.warning("Learning loop hook failed: %s", e)

    # Return updated result
    return await db[INTELLIGENCE_COLLECTION].find_one(
        {"document_id": doc_id}, {"_id": 0}
    )


async def get_intelligence_summary() -> Dict[str, Any]:
    """Get summary statistics for the intelligence pipeline."""
    db = get_db()

    total = await db[INTELLIGENCE_COLLECTION].count_documents({})

    pipeline = [
        {"$group": {
            "_id": "$automation_readiness",
            "count": {"$sum": 1},
            "avg_score": {"$avg": "$automation_readiness_score"},
            "avg_confidence": {"$avg": "$classification_confidence"},
        }}
    ]
    stats = await db[INTELLIGENCE_COLLECTION].aggregate(pipeline).to_list(10)

    by_readiness = {}
    for s in stats:
        if s["_id"]:
            by_readiness[s["_id"]] = {
                "count": s["count"],
                "avg_score": round(s.get("avg_score", 0), 1),
                "avg_confidence": round(s.get("avg_confidence", 0), 3),
            }

    # By document type
    type_pipeline = [
        {"$group": {
            "_id": "$document_type",
            "count": {"$sum": 1},
            "avg_confidence": {"$avg": "$classification_confidence"},
        }},
        {"$sort": {"count": -1}},
    ]
    type_stats = await db[INTELLIGENCE_COLLECTION].aggregate(type_pipeline).to_list(20)

    corrections = await db[INTELLIGENCE_COLLECTION].count_documents({"manually_corrected": True})

    return {
        "total_processed": total,
        "by_readiness": by_readiness,
        "by_document_type": [
            {"type": s["_id"], "count": s["count"], "avg_confidence": round(s.get("avg_confidence", 0), 3)}
            for s in type_stats if s["_id"]
        ],
        "total_corrections": corrections,
    }


# ═══════════════════════════════════════════════════════════════════════════════
# AUTO-DRAFT CREATION
# ═══════════════════════════════════════════════════════════════════════════════

# Document type → target entity mapping
DOC_TYPE_DRAFT_MAP = {
    "Sales_PO": {"target_entity_type": "sales_order_draft", "action_type": "create_sales_order_draft"},
    "customer_po": {"target_entity_type": "sales_order_draft", "action_type": "create_sales_order_draft"},
    "AP_Invoice": {"target_entity_type": "ap_intake_draft", "action_type": "create_ap_intake_draft"},
    "invoice": {"target_entity_type": "ap_intake_draft", "action_type": "create_ap_intake_draft"},
    "Freight_Document": {"target_entity_type": "po_draft", "action_type": "create_po_draft"},
    "Shipping_Document": {"target_entity_type": "po_draft", "action_type": "create_po_draft"},
    "vendor_po_support": {"target_entity_type": "po_draft", "action_type": "create_po_draft"},
}


async def _create_activity_record(
    db, entity_type: str, entity_id: str, activity_type: str,
    title: str, body_text: str = "", created_by: str = "system", metadata: dict = None,
):
    """Create an activity record — delegates to shared automation_helpers."""
    return await create_activity(
        db, entity_id=entity_id, entity_type=entity_type,
        activity_type=activity_type, title=title, body=body_text,
        metadata=metadata, created_by=created_by,
    )


def _resolve_draft_mapping(document_type: str) -> Optional[Dict[str, str]]:
    """Resolve document type to target draft mapping."""
    mapping = DOC_TYPE_DRAFT_MAP.get(document_type)
    if mapping:
        return mapping
    # Try case-insensitive / normalized matching
    norm = document_type.upper().replace(" ", "_").replace("-", "_")
    for key, val in DOC_TYPE_DRAFT_MAP.items():
        if key.upper().replace(" ", "_").replace("-", "_") == norm:
            return val
    # Check for keywords
    if any(kw in norm for kw in ["SALES", "CUSTOMER", "PO"]) and "AP" not in norm:
        return {"target_entity_type": "sales_order_draft", "action_type": "create_sales_order_draft"}
    if any(kw in norm for kw in ["AP", "INVOICE", "BILL"]):
        return {"target_entity_type": "ap_intake_draft", "action_type": "create_ap_intake_draft"}
    return None


async def _create_so_draft(db, doc: Dict, intel: Dict, fields: Dict) -> Dict[str, Any]:
    """Create a Sales Order draft from extracted document fields."""
    now = utcnow()
    draft_id = f"SO-DRAFT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    customer = fields.get("customer") or fields.get("consignee") or fields.get("customer_name") or ""
    po_number = fields.get("po_number") or fields.get("order_number") or fields.get("customer_po") or ""
    order_date = fields.get("order_date") or fields.get("date") or now[:10]

    line_items = fields.get("line_items", [])
    if isinstance(line_items, str):
        line_items = []
    lines = []
    for i, li in enumerate(line_items if isinstance(line_items, list) else []):
        if isinstance(li, dict):
            lines.append({
                "line_no": i + 1,
                "item": li.get("item") or li.get("description") or li.get("product") or f"Line {i+1}",
                "quantity": li.get("quantity") or li.get("qty") or 0,
                "unit_price": li.get("unit_price") or li.get("price") or 0,
                "description": li.get("description") or li.get("item") or "",
            })

    draft = {
        "so_draft_id": draft_id,
        "source_document_id": doc.get("id"),
        "source_file_name": doc.get("file_name", ""),
        "customer_name": customer,
        "customer_po_number": po_number,
        "order_date": order_date,
        "lines": lines,
        "total_lines": len(lines),
        "total_amount": sum(l.get("quantity", 0) * l.get("unit_price", 0) for l in lines),
        "status": "draft",
        "created_at": now,
        "created_by": "auto_draft",
        "notes": f"Auto-generated from document {doc.get('id', '')}",
        "classification_confidence": intel.get("classification_confidence", 0),
    }

    await db[SO_DRAFTS_COLLECTION].insert_one(draft.copy())
    draft.pop("_id", None)
    return draft


async def _create_po_draft(db, doc: Dict, intel: Dict, fields: Dict) -> Dict[str, Any]:
    """Create a PO draft from extracted document fields."""
    now = utcnow()
    draft_id = f"PO-DRAFT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    vendor = fields.get("vendor") or fields.get("shipper") or fields.get("carrier") or ""
    source_ref = fields.get("po_number") or fields.get("bol_number") or fields.get("pro_number") or ""

    line_items = fields.get("line_items", [])
    if isinstance(line_items, str):
        line_items = []
    lines = []
    for li in (line_items if isinstance(line_items, list) else []):
        if isinstance(li, dict):
            lines.append({
                "item": li.get("item") or li.get("description") or "Unknown",
                "qty": li.get("quantity") or li.get("qty") or 0,
                "source": "auto_draft",
            })

    # If no line items extracted, create a placeholder from item-level fields
    if not lines:
        item = fields.get("item") or fields.get("product") or fields.get("description") or ""
        qty = fields.get("quantity") or fields.get("pieces") or 0
        if item:
            lines.append({"item": item, "qty": qty, "source": "auto_draft"})

    draft = {
        "po_draft_id": draft_id,
        "source_document_id": doc.get("id"),
        "source_file_name": doc.get("file_name", ""),
        "vendor_name": vendor,
        "vendor_id": "",
        "source_reference": source_ref,
        "customer_id": "",
        "customer_name": "",
        "lines": lines,
        "total_lines": len(lines),
        "total_qty": sum(l.get("qty", 0) for l in lines),
        "po_type": "auto_draft",
        "status": "draft",
        "source": "auto_draft",
        "created_at": now,
        "notes": f"Auto-generated from document {doc.get('id', '')}",
    }

    await db[PO_DRAFTS_COLLECTION].insert_one(draft.copy())
    draft.pop("_id", None)
    return draft


async def _create_ap_intake_draft(db, doc: Dict, intel: Dict, fields: Dict) -> Dict[str, Any]:
    """Create an AP Intake draft from extracted invoice fields."""
    now = utcnow()
    draft_id = f"AP-DRAFT-{datetime.now(timezone.utc).strftime('%Y%m%d%H%M%S')}-{uuid.uuid4().hex[:6].upper()}"

    vendor = fields.get("vendor") or fields.get("vendor_name") or ""
    invoice_number = fields.get("invoice_number") or ""
    invoice_date = fields.get("invoice_date") or fields.get("date") or ""
    amount = fields.get("amount") or fields.get("invoice_amount") or fields.get("total") or 0
    po_number = fields.get("po_number") or ""

    if isinstance(amount, str):
        try:
            amount = float(amount.replace(",", "").replace("$", "").strip())
        except (ValueError, AttributeError):
            amount = 0

    line_items = fields.get("line_items", [])
    if isinstance(line_items, str):
        line_items = []
    lines = []
    for li in (line_items if isinstance(line_items, list) else []):
        if isinstance(li, dict):
            lines.append({
                "description": li.get("description") or li.get("item") or "",
                "amount": li.get("amount") or li.get("total") or 0,
                "quantity": li.get("quantity") or li.get("qty") or 0,
                "unit_price": li.get("unit_price") or li.get("price") or 0,
            })

    draft = {
        "ap_draft_id": draft_id,
        "source_document_id": doc.get("id"),
        "source_file_name": doc.get("file_name", ""),
        "vendor_name": vendor,
        "invoice_number": invoice_number,
        "invoice_date": invoice_date,
        "invoice_amount": amount,
        "po_reference": po_number,
        "lines": lines,
        "total_lines": len(lines),
        "status": "draft",
        "created_at": now,
        "created_by": "auto_draft",
        "notes": f"Auto-generated from document {doc.get('id', '')}",
        "classification_confidence": intel.get("classification_confidence", 0),
    }

    await db[AP_INTAKE_DRAFTS_COLLECTION].insert_one(draft.copy())
    draft.pop("_id", None)
    return draft


async def create_auto_draft(doc_id: str) -> Dict[str, Any]:
    """
    Create a downstream draft record from an automation-ready document.

    Validates readiness, maps doc type → draft type, creates draft,
    stores automation action, logs activity.
    Returns the action record with embedded draft data.
    """
    db = get_db()

    # 1) Validate document exists
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0})
    if not doc:
        raise ValueError(f"Document not found: {doc_id}")

    # 2) Validate intelligence result exists
    intel = await db[INTELLIGENCE_COLLECTION].find_one({"document_id": doc_id}, {"_id": 0})
    if not intel:
        raise ValueError(f"No intelligence result for document: {doc_id}. Run processing first.")

    # 3) Validate automation readiness
    readiness = intel.get("automation_readiness")
    if readiness != READINESS_READY:
        raise PermissionError(
            f"Document automation_readiness is '{readiness}', not 'ready'. "
            f"Score: {intel.get('automation_readiness_score', 0)}, "
            f"Reasons: {intel.get('automation_readiness_reasons', [])}"
        )

    # 4) Check entity resolution — block if required entities unresolved
    er_status = intel.get("entity_resolution_status")
    if er_status == "blocked":
        blocking = intel.get("entity_resolution_blocking_items", [])
        raise PermissionError(
            f"Auto-draft blocked by unresolved entities: {blocking}. "
            f"Run entity resolution and resolve before creating drafts."
        )

    # 5) Check transaction matching — suppress draft if confident existing match
    if intel.get("auto_draft_suppressed_due_to_match") and intel.get("auto_link_available"):
        best = intel.get("best_transaction_match", {})
        raise PermissionError(
            f"Draft creation suppressed: confident match found to existing "
            f"{best.get('entity_type', 'transaction')} '{best.get('display_name', best.get('entity_id', ''))}' "
            f"(confidence: {best.get('confidence', 0):.0%}). Use auto-link instead."
        )

    # 6) Resolve draft mapping
    document_type = intel.get("document_type", "")
    mapping = _resolve_draft_mapping(document_type)
    if not mapping:
        raise ValueError(
            f"No auto-draft mapping for document type: '{document_type}'. "
            f"Supported types: {list(DOC_TYPE_DRAFT_MAP.keys())}"
        )

    target_entity_type = mapping["target_entity_type"]
    action_type = mapping["action_type"]

    # 7) Duplicate prevention
    existing_action = await db[AUTOMATION_ACTIONS_COLLECTION].find_one(
        {
            "document_id": doc_id,
            "target_entity_type": target_entity_type,
            "action_status": "draft_created",
        },
        {"_id": 0},
    )
    if existing_action:
        raise DuplicateDraftError(
            f"A {target_entity_type} was already created from this document.",
            existing_action=existing_action,
        )

    # 6) Create the appropriate draft
    fields = intel.get("extracted_fields", {})
    now = datetime.now(timezone.utc)
    action_id = f"AA-{uuid.uuid4().hex[:8].upper()}"

    try:
        if target_entity_type == "sales_order_draft":
            draft = await _create_so_draft(db, doc, intel, fields)
            target_entity_id = draft["so_draft_id"]
        elif target_entity_type == "po_draft":
            draft = await _create_po_draft(db, doc, intel, fields)
            target_entity_id = draft["po_draft_id"]
        elif target_entity_type == "ap_intake_draft":
            draft = await _create_ap_intake_draft(db, doc, intel, fields)
            target_entity_id = draft["ap_draft_id"]
        else:
            raise ValueError(f"Unsupported target entity type: {target_entity_type}")

        action_status = "draft_created"
    except Exception as e:
        if isinstance(e, (ValueError, DuplicateDraftError)):
            raise
        # Draft creation failed
        action_status = "failed"
        target_entity_id = ""
        draft = {"error": str(e)}
        logger.error("Auto-draft creation failed for %s: %s", doc_id, e)

    # 7) Store automation action record
    action_record = {
        "automation_action_id": action_id,
        "document_id": doc_id,
        "source_document_type": document_type,
        "target_entity_type": target_entity_type,
        "target_entity_id": target_entity_id,
        "action_type": action_type,
        "action_status": action_status,
        "created_at": now.isoformat(),
        "created_by": "auto_draft",
        "notes": "Auto-draft from document intelligence pipeline",
    }
    await db[AUTOMATION_ACTIONS_COLLECTION].insert_one(action_record.copy())
    action_record.pop("_id", None)

    # 8) Update intelligence result with draft info
    intel_update = {
        "auto_draft_available": True,
        "auto_draft_created": action_status == "draft_created",
        "target_entity_type": target_entity_type,
        "target_entity_id": target_entity_id,
        "last_automation_action_id": action_id,
        "last_automation_action_status": action_status,
    }
    await db[INTELLIGENCE_COLLECTION].update_one(
        {"document_id": doc_id}, {"$set": intel_update}
    )

    # 9) Update hub_documents
    await db.hub_documents.update_one(
        {"id": doc_id},
        {"$set": {
            "auto_draft_created": action_status == "draft_created",
            "target_entity_type": target_entity_type,
            "target_entity_id": target_entity_id,
            "updated_utc": now.isoformat(),
        }},
    )

    # 10) Create activity
    if action_status == "draft_created":
        await _create_activity_record(
            db, "document", doc_id, "auto_draft_created",
            f"Auto-draft created: {target_entity_type}",
            f"Created {target_entity_id} from document intelligence pipeline. "
            f"Confidence: {intel.get('classification_confidence', 0):.0%}",
            metadata={"target_entity_type": target_entity_type, "target_entity_id": target_entity_id},
        )
    else:
        await _create_activity_record(
            db, "document", doc_id, "auto_draft_failed",
            f"Auto-draft creation failed: {target_entity_type}",
            f"Error: {draft.get('error', 'Unknown')}",
            metadata={"action_id": action_id},
        )

    # 11) Emit event
    try:
        from services.event_service import get_event_service
        event_service = get_event_service()
        if event_service:
            await event_service.emit(
                f"document_intelligence.auto_draft.{action_status}",
                {
                    "document_id": doc_id,
                    "action_id": action_id,
                    "target_entity_type": target_entity_type,
                    "target_entity_id": target_entity_id,
                },
            )
    except Exception:
        pass

    return {
        **action_record,
        "draft": draft,
    }


async def get_automation_action(doc_id: str) -> Optional[Dict[str, Any]]:
    """Get the latest automation action for a document."""
    db = get_db()
    action = await db[AUTOMATION_ACTIONS_COLLECTION].find_one(
        {"document_id": doc_id},
        {"_id": 0},
        sort=[("created_at", -1)],
    )
    return action


class DuplicateDraftError(Exception):
    """Raised when a duplicate draft already exists."""
    def __init__(self, message: str, existing_action: Dict = None):
        super().__init__(message)
        self.existing_action = existing_action or {}
