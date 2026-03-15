"""
GPI Document Hub - Learning Loop Engine

Captures human corrections during document processing and converts them
into structured intelligence signals: vendor/customer aliases, extraction
hints, and automation confidence metrics.

SAFETY: Does not automatically retrain models, change decision policies,
or alter extraction prompts. Only captures learning signals.
"""

import uuid
import logging
from datetime import datetime, timezone
from typing import Dict, Any, Optional, List

from deps import get_db

logger = logging.getLogger(__name__)

LEARNING_EVENTS = "learning_events"
VENDOR_ALIASES = "vendor_aliases"
CUSTOMER_ALIASES = "customer_aliases"
EXTRACTION_HINTS = "extraction_hints"
LEARNING_METRICS = "learning_metrics"
INTELLIGENCE_COLLECTION = "document_intelligence_results"
ACTIVITIES_COLLECTION = "activities"

# Event types
ET_CLASSIFICATION = "classification_correction"
ET_FIELD = "field_correction"
ET_ENTITY_OVERRIDE = "entity_override"
ET_MATCH_OVERRIDE = "transaction_match_override"
ET_BUNDLE_CORRECTION = "bundle_membership_correction"
ET_MANUAL_LINK = "manual_link_override"


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


# ── Learning Event Recording ─────────────────────────────────────────────────

async def record_learning_event(
    document_id: str,
    event_type: str,
    field_name: str = "",
    original_value: Any = None,
    corrected_value: Any = None,
    confidence_before: float = 0.0,
    confidence_after: float = 0.0,
    correction_source: str = "manual",
    related_entity_id: str = "",
    related_entity_type: str = "",
    document_type: str = "",
    entity_context: str = "",
    created_by: str = "admin",
    notes: str = "",
) -> Dict[str, Any]:
    """Record a learning event from a user correction."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    event_id = f"LEV-{uuid.uuid4().hex[:8].upper()}"
    record = {
        "learning_event_id": event_id,
        "document_id": document_id,
        "event_type": event_type,
        "document_type": document_type,
        "entity_context": entity_context,
        "field_name": field_name,
        "original_value": str(original_value) if original_value is not None else "",
        "corrected_value": str(corrected_value) if corrected_value is not None else "",
        "confidence_before": confidence_before,
        "confidence_after": confidence_after,
        "correction_source": correction_source,
        "related_entity_id": related_entity_id,
        "related_entity_type": related_entity_type,
        "created_at": now,
        "created_by": created_by,
        "notes": notes,
    }

    await db[LEARNING_EVENTS].insert_one(record.copy())
    record.pop("_id", None)

    # Update document enrichment
    await _update_document_learning_enrichment(db, document_id)

    await _create_activity(
        db, document_id, "document", "learning_event_generated",
        f"Learning signal: {event_type} on '{field_name or 'classification'}'",
        body=f"Original: {original_value} → Corrected: {corrected_value}",
        metadata={"event_id": event_id, "event_type": event_type},
    )

    return record


async def _update_document_learning_enrichment(db, document_id: str):
    """Update document intelligence with learning metadata."""
    events = await db[LEARNING_EVENTS].find(
        {"document_id": document_id}, {"_id": 0, "event_type": 1}
    ).to_list(100)

    event_types = [e["event_type"] for e in events]
    flags = []
    if len(events) >= 3:
        flags.append("frequent_correction")
    if ET_ENTITY_OVERRIDE in event_types:
        flags.append("entity_override_used")
    if ET_CLASSIFICATION in event_types:
        flags.append("classification_corrected")

    await db[INTELLIGENCE_COLLECTION].update_one(
        {"document_id": document_id},
        {"$set": {
            "learning_events_count": len(events),
            "corrections_applied": len(events),
            "learning_flags": flags,
        }},
    )


# ── Correction Hooks (called from existing services) ────────────────────────

async def on_classification_correction(
    document_id: str,
    original_type: str,
    corrected_type: str,
    confidence_before: float,
    corrected_by: str = "admin",
):
    """Hook: called when document type is manually corrected."""
    await record_learning_event(
        document_id=document_id,
        event_type=ET_CLASSIFICATION,
        field_name="document_type",
        original_value=original_type,
        corrected_value=corrected_type,
        confidence_before=confidence_before,
        confidence_after=1.0,
        correction_source="manual",
        document_type=corrected_type,
        created_by=corrected_by,
    )


async def on_field_correction(
    document_id: str,
    document_type: str,
    field_changes: Dict[str, Dict],
    corrected_by: str = "admin",
    vendor_id: str = "",
):
    """Hook: called when extracted fields are manually corrected."""
    db = get_db()
    for field_name, change in field_changes.items():
        await record_learning_event(
            document_id=document_id,
            event_type=ET_FIELD,
            field_name=field_name,
            original_value=change.get("from"),
            corrected_value=change.get("to"),
            document_type=document_type,
            related_entity_id=vendor_id,
            created_by=corrected_by,
        )

        # Record extraction hint
        await _record_extraction_hint(
            db, document_type, vendor_id, field_name,
            str(change.get("from", "")), str(change.get("to", "")),
        )


async def on_entity_override(
    document_id: str,
    entity_kind: str,
    source_value: str,
    original_entity_id: str,
    original_entity_name: str,
    corrected_entity_id: str,
    corrected_entity_name: str,
    confidence_before: float,
    corrected_by: str = "admin",
):
    """Hook: called when entity resolution is manually overridden."""
    db = get_db()
    await record_learning_event(
        document_id=document_id,
        event_type=ET_ENTITY_OVERRIDE,
        field_name=entity_kind,
        original_value=original_entity_name,
        corrected_value=corrected_entity_name,
        confidence_before=confidence_before,
        confidence_after=1.0,
        related_entity_id=corrected_entity_id,
        related_entity_type=entity_kind,
        entity_context=source_value,
        created_by=corrected_by,
    )

    # Create/update alias
    if entity_kind in ("vendor", "vendor_name", "shipper"):
        await _upsert_alias(db, VENDOR_ALIASES, source_value, corrected_entity_id, corrected_entity_name, corrected_by)
    elif entity_kind in ("customer", "customer_name", "consignee"):
        await _upsert_alias(db, CUSTOMER_ALIASES, source_value, corrected_entity_id, corrected_entity_name, corrected_by)


async def on_transaction_match_override(
    document_id: str,
    match_id: str,
    confirmed: bool,
    candidate_entity_type: str,
    candidate_entity_id: str,
    candidate_display_name: str,
    corrected_by: str = "admin",
):
    """Hook: called when a transaction match is manually confirmed/rejected."""
    await record_learning_event(
        document_id=document_id,
        event_type=ET_MATCH_OVERRIDE,
        field_name="transaction_match",
        original_value=f"{candidate_entity_type}:{candidate_entity_id}",
        corrected_value="confirmed" if confirmed else "rejected",
        related_entity_id=candidate_entity_id,
        related_entity_type=candidate_entity_type,
        entity_context=candidate_display_name,
        created_by=corrected_by,
    )


async def on_bundle_membership_correction(
    document_id: str,
    bundle_id: str,
    action: str,
    updated_by: str = "admin",
):
    """Hook: called when a document is manually added/removed from a bundle."""
    await record_learning_event(
        document_id=document_id,
        event_type=ET_BUNDLE_CORRECTION,
        field_name="bundle_membership",
        original_value=bundle_id,
        corrected_value=action,
        related_entity_id=bundle_id,
        related_entity_type="bundle",
        created_by=updated_by,
    )


# ── Alias Management ─────────────────────────────────────────────────────────

async def _upsert_alias(db, collection: str, alias_text: str, canonical_id: str, canonical_name: str, created_by: str):
    """Create or update a vendor/customer alias."""
    now = datetime.now(timezone.utc).isoformat()
    alias_norm = alias_text.strip().upper()

    existing = await db[collection].find_one(
        {"alias": alias_norm}, {"_id": 0}
    )

    if existing:
        # Don't overwrite high-confidence existing mappings to different entities
        if existing.get("canonical_vendor_id", existing.get("canonical_customer_id", "")) != canonical_id:
            if existing.get("confidence", 0) >= 0.95:
                return  # Don't override high-confidence alias

        new_count = existing.get("correction_count", 0) + 1
        new_conf = min(1.0, existing.get("confidence", 0.5) + 0.05)

        id_field = "canonical_vendor_id" if collection == VENDOR_ALIASES else "canonical_customer_id"
        await db[collection].update_one(
            {"alias": alias_norm},
            {"$set": {
                id_field: canonical_id,
                "canonical_name": canonical_name,
                "confidence": new_conf,
                "correction_count": new_count,
                "last_seen": now,
                "source": "manual_correction",
            }},
        )
    else:
        id_field = "canonical_vendor_id" if collection == VENDOR_ALIASES else "canonical_customer_id"
        record = {
            "alias": alias_norm,
            id_field: canonical_id,
            "canonical_name": canonical_name,
            "confidence": 0.8,
            "source": "manual_correction",
            "last_seen": now,
            "correction_count": 1,
            "created_at": now,
            "created_by": created_by,
        }
        await db[collection].insert_one(record.copy())

        entity_label = "vendor" if collection == VENDOR_ALIASES else "customer"
        await _create_activity(
            db, canonical_id, entity_label, f"{entity_label}_alias_created",
            f"{entity_label.title()} alias created: '{alias_text}' → {canonical_name}",
            metadata={"alias": alias_text, "canonical_id": canonical_id},
        )


# ── Extraction Hints ─────────────────────────────────────────────────────────

async def _record_extraction_hint(db, document_type: str, vendor_id: str, field_name: str, original: str, corrected: str):
    """Record a hint about extraction patterns for a field."""
    now = datetime.now(timezone.utc).isoformat()
    query = {
        "document_type": document_type,
        "field_name": field_name,
    }
    if vendor_id:
        query["vendor_id"] = vendor_id

    existing = await db[EXTRACTION_HINTS].find_one(query, {"_id": 0})
    if existing:
        new_count = existing.get("correction_count", 0) + 1
        new_conf = min(1.0, existing.get("confidence_score", 0.3) + 0.1)
        await db[EXTRACTION_HINTS].update_one(
            query,
            {"$set": {
                "correction_count": new_count,
                "confidence_score": new_conf,
                "last_updated": now,
                "corrected_value_pattern": corrected[:200],
                "observed_original_location": original[:200],
            }},
        )
    else:
        record = {
            "document_type": document_type,
            "vendor_id": vendor_id or "",
            "field_name": field_name,
            "observed_original_location": original[:200],
            "corrected_value_pattern": corrected[:200],
            "correction_count": 1,
            "confidence_score": 0.3,
            "last_updated": now,
        }
        await db[EXTRACTION_HINTS].insert_one(record.copy())

        await _create_activity(
            db, document_type, "extraction", "extraction_hint_recorded",
            f"Extraction hint recorded: {field_name} for {document_type}",
            metadata={"field_name": field_name, "document_type": document_type},
        )


# ── Automation Confidence Metrics ────────────────────────────────────────────

async def update_automation_metrics():
    """Recalculate automation confidence metrics from learning events."""
    db = get_db()
    now = datetime.now(timezone.utc).isoformat()

    # Total processed
    total_processed = await db[INTELLIGENCE_COLLECTION].count_documents({})
    total_corrected = await db[INTELLIGENCE_COLLECTION].count_documents({"manually_corrected": True})

    # By document type
    type_pipeline = [
        {"$group": {
            "_id": "$document_type",
            "total": {"$sum": 1},
            "corrected": {"$sum": {"$cond": [{"$eq": ["$manually_corrected", True]}, 1, 0]}},
        }}
    ]
    type_results = await db[INTELLIGENCE_COLLECTION].aggregate(type_pipeline).to_list(50)
    by_type = {}
    for r in type_results:
        dt = r["_id"] or "unknown"
        by_type[dt] = {
            "total": r["total"],
            "corrected": r["corrected"],
            "correction_rate": round(r["corrected"] / max(r["total"], 1), 4),
        }

    # By vendor (from learning events)
    vendor_pipeline = [
        {"$match": {"related_entity_type": {"$in": ["vendor", "vendor_name", "shipper"]}, "related_entity_id": {"$ne": ""}}},
        {"$group": {"_id": "$related_entity_id", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 10},
    ]
    vendor_results = await db[LEARNING_EVENTS].aggregate(vendor_pipeline).to_list(10)
    top_vendors = [{"vendor_id": v["_id"], "correction_count": v["count"]} for v in vendor_results]

    success_rate = round(1 - (total_corrected / max(total_processed, 1)), 4)

    metrics = {
        "metrics_id": "global",
        "total_processed": total_processed,
        "total_corrected": total_corrected,
        "automation_success_rate": success_rate,
        "correction_rate_by_document_type": by_type,
        "top_corrected_vendors": top_vendors,
        "updated_at": now,
    }

    await db[LEARNING_METRICS].update_one(
        {"metrics_id": "global"}, {"$set": metrics}, upsert=True
    )
    return metrics


# ── Public API ───────────────────────────────────────────────────────────────

async def get_learning_summary() -> Dict[str, Any]:
    """Get learning summary with metrics and stats."""
    db = get_db()

    # Update metrics
    metrics = await update_automation_metrics()

    # Event counts by type
    type_pipeline = [
        {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    by_event_type = {r["_id"]: r["count"] for r in await db[LEARNING_EVENTS].aggregate(type_pipeline).to_list(20)}

    # Top corrected doc types
    doc_type_pipeline = [
        {"$match": {"document_type": {"$ne": ""}}},
        {"$group": {"_id": "$document_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
        {"$limit": 5},
    ]
    top_doc_types = [{"document_type": r["_id"], "count": r["count"]} for r in await db[LEARNING_EVENTS].aggregate(doc_type_pipeline).to_list(5)]

    # Alias counts
    vendor_alias_count = await db[VENDOR_ALIASES].count_documents({})
    customer_alias_count = await db[CUSTOMER_ALIASES].count_documents({})
    hint_count = await db[EXTRACTION_HINTS].count_documents({})

    total_events = await db[LEARNING_EVENTS].count_documents({})

    return {
        "total_learning_events": total_events,
        "corrections_by_type": by_event_type,
        "top_corrected_document_types": top_doc_types,
        "top_corrected_vendors": metrics.get("top_corrected_vendors", []),
        "vendor_aliases_created": vendor_alias_count,
        "customer_aliases_created": customer_alias_count,
        "extraction_hints_recorded": hint_count,
        "automation_success_rate": metrics.get("automation_success_rate", 0),
        "correction_rate_by_document_type": metrics.get("correction_rate_by_document_type", {}),
    }


async def get_learning_events(
    event_type: Optional[str] = None,
    document_type: Optional[str] = None,
    vendor_id: Optional[str] = None,
    entity_type: Optional[str] = None,
    limit: int = 50,
    offset: int = 0,
) -> Dict[str, Any]:
    """Query learning events with filters."""
    db = get_db()
    query = {}
    if event_type:
        query["event_type"] = event_type
    if document_type:
        query["document_type"] = document_type
    if vendor_id:
        query["related_entity_id"] = vendor_id
    if entity_type:
        query["related_entity_type"] = entity_type

    total = await db[LEARNING_EVENTS].count_documents(query)
    events = await db[LEARNING_EVENTS].find(
        query, {"_id": 0}
    ).sort("created_at", -1).skip(offset).limit(limit).to_list(limit)

    return {"total": total, "events": events}


async def get_document_learning_events(doc_id: str) -> List[Dict[str, Any]]:
    """Get all learning events for a specific document."""
    db = get_db()
    return await db[LEARNING_EVENTS].find(
        {"document_id": doc_id}, {"_id": 0}
    ).sort("created_at", -1).to_list(50)
