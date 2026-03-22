"""
GPI Document Hub — Unified Feedback Loop Service

PRINCIPLE: Every interaction is training data. Every correction makes the system smarter.

This service captures ALL user interactions and applies them as learning signals
back into the AI extraction pipeline. Nothing is wasted.

Architecture:
┌─────────────────┐     ┌──────────────────┐     ┌─────────────────────┐
│  User Actions    │────▶│  Feedback Store   │────▶│  Learning Signals   │
│                  │     │                  │     │                     │
│ • Vendor fix     │     │ feedback_events  │     │ • Few-shot examples │
│ • Reclassify     │     │ collection       │     │ • Vendor aliases    │
│ • Amount edit    │     │                  │     │ • Routing rules     │
│ • Folder move    │     │ Every action     │     │ • Confidence boost  │
│ • Approve/reject │     │ timestamped      │     │ • Prompt tuning     │
│ • PO correction  │     │ attributed       │     │ • Pattern memory    │
│ • Benchmark diff │     │                  │     │                     │
└─────────────────┘     └──────────────────┘     └─────────────────────┘

The feedback loop has two phases:
1. CAPTURE — Record every interaction as a feedback event
2. APPLY — Use accumulated feedback to improve future extractions
"""

import logging
import re
from datetime import datetime, timezone
from typing import Any, Dict, List, Optional

logger = logging.getLogger(__name__)

# ═══════════════════════════════════════════════════════════════
# PHASE 1: CAPTURE — Every interaction is a feedback event
# ═══════════════════════════════════════════════════════════════

FEEDBACK_COLLECTION = "feedback_events"


async def record_feedback(
    db,
    event_type: str,
    document_id: str = "",
    vendor_id: str = "",
    before: Optional[Dict] = None,
    after: Optional[Dict] = None,
    source: str = "user",
    user_id: str = "",
    metadata: Optional[Dict] = None,
):
    """
    Record a feedback event. EVERY user action that touches document data
    should call this function.
    
    Event types:
    - vendor_correction:    User changed vendor name/ID
    - classification_correction: User changed doc type
    - amount_correction:    User changed amount
    - po_correction:        User changed PO number
    - date_correction:      User changed invoice date
    - folder_correction:    User moved doc to different folder
    - approval:             User approved a document
    - rejection:            User rejected a document
    - field_edit:           User edited any extracted field
    - benchmark_mismatch:   Benchmark revealed a routing/classification gap
    """
    event = {
        "event_type": event_type,
        "document_id": document_id,
        "vendor_id": vendor_id,
        "before": before or {},
        "after": after or {},
        "source": source,  # "user", "benchmark", "automation", "bulk_review"
        "user_id": user_id,
        "metadata": metadata or {},
        "created_at": datetime.now(timezone.utc).isoformat(),
        "applied": False,  # Set to True once the learning signal is consumed
    }
    
    await db[FEEDBACK_COLLECTION].insert_one(event)
    event.pop("_id", None)
    
    logger.info(
        "[Feedback] %s: doc=%s vendor=%s source=%s",
        event_type, document_id[:20], vendor_id[:20], source,
    )
    
    # Immediately apply high-priority learning signals
    await _apply_immediate_feedback(db, event)
    
    return event


# ═══════════════════════════════════════════════════════════════
# PHASE 2: APPLY — Use feedback to improve future extractions
# ═══════════════════════════════════════════════════════════════

async def _apply_immediate_feedback(db, event: Dict):
    """
    Apply learning signals that should take effect immediately.
    Some feedback can be applied in real-time; others accumulate
    and are applied in batch.
    """
    event_type = event["event_type"]
    
    if event_type == "vendor_correction":
        await _learn_vendor_alias(db, event)
    
    elif event_type == "classification_correction":
        await _learn_classification_pattern(db, event)
    
    elif event_type == "folder_correction":
        await _learn_folder_routing(db, event)
    
    elif event_type in ("approval", "rejection"):
        await _update_vendor_track_record(db, event)
    
    elif event_type == "benchmark_mismatch":
        await _learn_from_benchmark(db, event)


async def _learn_vendor_alias(db, event: Dict):
    """
    When a user corrects a vendor name, create/update a vendor alias
    so the system recognizes this name next time.
    """
    before_vendor = (event.get("before") or {}).get("vendor", "")
    after_vendor = (event.get("after") or {}).get("vendor", "")
    vendor_id = event.get("vendor_id", "")
    
    if not before_vendor or not after_vendor or before_vendor == after_vendor:
        return
    
    # Add to vendor_aliases collection
    await db.vendor_aliases.update_one(
        {"alias": before_vendor.strip().upper()},
        {"$set": {
            "alias": before_vendor.strip().upper(),
            "canonical_name": after_vendor,
            "vendor_no": vendor_id,
            "source": "user_correction",
            "learned_at": datetime.now(timezone.utc).isoformat(),
            "correction_count": 1,
        },
        "$inc": {"correction_count": 1}},
        upsert=True,
    )
    
    logger.info("[FeedbackLearn] Vendor alias: '%s' -> '%s' (%s)", before_vendor, after_vendor, vendor_id)
    
    await db[FEEDBACK_COLLECTION].update_one(
        {"_id": event.get("_id")},
        {"$set": {"applied": True, "applied_at": datetime.now(timezone.utc).isoformat()}}
    )


async def _learn_classification_pattern(db, event: Dict):
    """
    When a user reclassifies a document, store this as a few-shot example
    that the AI classifier can use in future prompts.
    """
    before_type = (event.get("before") or {}).get("doc_type", "")
    after_type = (event.get("after") or {}).get("doc_type", "")
    doc_id = event.get("document_id", "")
    
    if not before_type or not after_type or before_type == after_type:
        return
    
    # Store as classification example
    example = {
        "document_id": doc_id,
        "ai_predicted": before_type,
        "human_corrected": after_type,
        "vendor_id": event.get("vendor_id", ""),
        "source": "user_correction",
        "learned_at": datetime.now(timezone.utc).isoformat(),
    }
    
    # Also store file metadata for pattern recognition
    doc = await db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "file_name": 1, "vendor_canonical": 1})
    if doc:
        example["file_name"] = doc.get("file_name", "")
        example["vendor"] = doc.get("vendor_canonical", "")
    
    await db.classification_feedback.update_one(
        {"document_id": doc_id},
        {"$set": example},
        upsert=True,
    )
    
    logger.info("[FeedbackLearn] Classification: %s -> %s (doc=%s)", before_type, after_type, doc_id[:20])


async def _learn_folder_routing(db, event: Dict):
    """
    When a user moves a document to a different folder, record this
    as a routing correction. Accumulated corrections can be used to
    adjust routing rules.
    """
    before_folder = (event.get("before") or {}).get("folder", "")
    after_folder = (event.get("after") or {}).get("folder", "")
    
    if not before_folder or not after_folder or before_folder == after_folder:
        return
    
    await db.routing_feedback.update_one(
        {"document_id": event.get("document_id", "")},
        {"$set": {
            "document_id": event.get("document_id", ""),
            "vendor_id": event.get("vendor_id", ""),
            "ai_routed_to": before_folder,
            "human_moved_to": after_folder,
            "learned_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    
    logger.info("[FeedbackLearn] Routing: '%s' -> '%s'", before_folder[:30], after_folder[:30])


async def _update_vendor_track_record(db, event: Dict):
    """
    When a user approves or rejects a document, update the vendor's
    track record. Approvals increase stable vendor score; rejections decrease it.
    """
    vendor_id = event.get("vendor_id", "")
    if not vendor_id:
        return
    
    is_approval = event["event_type"] == "approval"
    
    # Increment the appropriate counter on the vendor profile
    inc_field = "feedback_approvals" if is_approval else "feedback_rejections"
    await db.vendor_intelligence_profiles.update_one(
        {"vendor_no": vendor_id},
        {
            "$inc": {inc_field: 1, "feedback_total": 1},
            "$set": {"last_feedback_at": datetime.now(timezone.utc).isoformat()},
        },
    )
    
    logger.info("[FeedbackLearn] Vendor %s: %s", vendor_id, "approved" if is_approval else "rejected")


async def _learn_from_benchmark(db, event: Dict):
    """
    When a benchmark run reveals mismatches between GPI Hub and ground truth,
    each mismatch is a learning signal.
    """
    metadata = event.get("metadata") or {}
    field = metadata.get("field", "")  # e.g., "folder", "vendor", "doc_type"
    truth = metadata.get("truth", "")
    predicted = metadata.get("predicted", "")
    
    if not field or not truth or not predicted:
        return
    
    await db.benchmark_feedback.insert_one({
        "field": field,
        "truth": truth,
        "predicted": predicted,
        "vendor_id": event.get("vendor_id", ""),
        "document_id": event.get("document_id", ""),
        "learned_at": datetime.now(timezone.utc).isoformat(),
    })
    
    logger.info("[FeedbackLearn] Benchmark: %s truth='%s' predicted='%s'", field, truth[:20], predicted[:20])


# ═══════════════════════════════════════════════════════════════
# PHASE 3: BUILD CONTEXT — Generate AI prompt context from feedback
# ═══════════════════════════════════════════════════════════════

async def build_feedback_context_for_prompt(db, vendor_id: str = "", doc_type: str = "") -> str:
    """
    Build a context section for the AI extraction prompt that includes
    learned patterns from user feedback.
    
    This is called by the classification pipeline before sending a document
    to the LLM. It enriches the prompt with:
    - Recent corrections for this vendor
    - Classification patterns the AI got wrong before
    - Vendor aliases learned from corrections
    - General recent corrections (even without vendor context)
    
    This is HOW the AI gets smarter — every correction becomes a few-shot example.
    """
    context_parts = []
    
    # 1. Vendor-specific corrections
    if vendor_id:
        # Try both exact match and case-insensitive
        vendor_upper = vendor_id.upper().strip()
        corrections = await db.classification_feedback.find(
            {"$or": [
                {"vendor": vendor_id},
                {"vendor": vendor_upper},
                {"vendor_id": vendor_id},
                {"vendor_id": vendor_upper},
            ]},
            {"_id": 0, "ai_predicted": 1, "human_corrected": 1, "file_name": 1}
        ).sort("learned_at", -1).limit(5).to_list(5)
        
        if corrections:
            context_parts.append(f"LEARNED CORRECTIONS for vendor '{vendor_id}':")
            for c in corrections:
                context_parts.append(
                    f"  - File '{c.get('file_name', '?')}' was misclassified as "
                    f"'{c.get('ai_predicted', '?')}', correct type is '{c.get('human_corrected', '?')}'"
                )
    
    # 2. General classification corrections (recent)
    if doc_type:
        type_corrections = await db.classification_feedback.find(
            {"ai_predicted": doc_type},
            {"_id": 0, "ai_predicted": 1, "human_corrected": 1}
        ).sort("learned_at", -1).limit(3).to_list(3)
        
        if type_corrections:
            context_parts.append(f"NOTE: Documents predicted as '{doc_type}' are sometimes actually:")
            for c in type_corrections:
                context_parts.append(f"  - '{c.get('human_corrected', '?')}'")
    
    # 3. Vendor aliases
    if vendor_id:
        vendor_upper = vendor_id.upper().strip()
        aliases = await db.vendor_aliases.find(
            {"$or": [
                {"vendor_no": vendor_id, "source": "user_correction"},
                {"vendor_no": vendor_upper, "source": "user_correction"},
            ]},
            {"_id": 0, "alias": 1, "canonical_name": 1}
        ).limit(10).to_list(10)
        
        if aliases:
            context_parts.append("KNOWN VENDOR NAME VARIATIONS:")
            for a in aliases:
                context_parts.append(f"  - '{a.get('alias', '?')}' = '{a.get('canonical_name', '?')}'")
    
    # 4. Routing corrections for this vendor
    if vendor_id:
        routing = await db.routing_feedback.find(
            {"vendor_id": vendor_id},
            {"_id": 0, "ai_routed_to": 1, "human_moved_to": 1}
        ).sort("learned_at", -1).limit(3).to_list(3)
        
        if routing:
            context_parts.append("ROUTING CORRECTIONS for this vendor:")
            for r in routing:
                context_parts.append(
                    f"  - Was routed to '{r.get('ai_routed_to', '?')}', "
                    f"should be '{r.get('human_moved_to', '?')}'"
                )
    
    # 5. General recent corrections (always included, even without vendor context)
    # This ensures EVERY LLM call benefits from the feedback loop
    recent = await db.classification_feedback.find(
        {},
        {"_id": 0, "ai_predicted": 1, "human_corrected": 1, "file_name": 1, "vendor": 1}
    ).sort("learned_at", -1).limit(5).to_list(5)
    
    if recent:
        context_parts.append("RECENT SYSTEM-WIDE CORRECTIONS (learn from these):")
        for c in recent:
            vendor_label = c.get("vendor", "unknown")
            context_parts.append(
                f"  - Vendor '{vendor_label}': '{c.get('ai_predicted', '?')}' → '{c.get('human_corrected', '?')}'"
                f" (file: {c.get('file_name', '?')})"
            )
    
    if not context_parts:
        return ""
    
    header = "\n== FEEDBACK LOOP — LEARNED PATTERNS FROM USER CORRECTIONS =="
    return header + "\n" + "\n".join(context_parts)


# ═══════════════════════════════════════════════════════════════
# STATS — Feedback loop health metrics
# ═══════════════════════════════════════════════════════════════

async def get_feedback_stats(db) -> Dict[str, Any]:
    """
    Get stats on the feedback loop health.
    Shows how much signal has been captured and applied.
    """
    total = await db[FEEDBACK_COLLECTION].count_documents({})
    applied = await db[FEEDBACK_COLLECTION].count_documents({"applied": True})
    
    by_type = {}
    pipeline = [
        {"$group": {"_id": "$event_type", "count": {"$sum": 1}}},
        {"$sort": {"count": -1}},
    ]
    async for doc in db[FEEDBACK_COLLECTION].aggregate(pipeline):
        by_type[doc["_id"]] = doc["count"]
    
    aliases_learned = await db.vendor_aliases.count_documents({"source": "user_correction"})
    classification_examples = await db.classification_feedback.count_documents({})
    routing_corrections = await db.routing_feedback.count_documents({})
    
    return {
        "total_events": total,
        "applied_events": applied,
        "pending_events": total - applied,
        "events_by_type": by_type,
        "learning_signals": {
            "vendor_aliases_learned": aliases_learned,
            "classification_examples": classification_examples,
            "routing_corrections": routing_corrections,
        },
    }
