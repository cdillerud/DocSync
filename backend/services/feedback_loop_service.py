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
    applied = False
    
    if event_type == "vendor_correction":
        applied = await _learn_vendor_alias(db, event)
    
    elif event_type == "classification_correction":
        applied = await _learn_classification_pattern(db, event)
    
    elif event_type == "folder_correction":
        applied = await _learn_folder_routing(db, event)
    
    elif event_type in ("approval", "rejection"):
        applied = await _update_vendor_track_record(db, event)
    
    elif event_type == "po_correction":
        applied = await _learn_po_pattern(db, event)
    
    elif event_type == "amount_correction":
        applied = await _learn_amount_pattern(db, event)
    
    elif event_type == "field_edit":
        applied = await _learn_field_edit(db, event)
    
    elif event_type == "benchmark_mismatch":
        applied = await _learn_from_benchmark(db, event)
    
    # Mark event as applied
    if applied:
        await _mark_applied(db, event)
    else:
        # If the event can't be learned from (e.g., malformed payload),
        # still mark it as applied to prevent infinite replay loops.
        # This covers legacy events with empty or mismatched payloads.
        event_id = event.get("_id")
        if event_id:
            await db[FEEDBACK_COLLECTION].update_one(
                {"_id": event_id},
                {"$set": {"applied": True, "applied_at": datetime.now(timezone.utc).isoformat(), "apply_note": "marked_unlearnable"}}
            )

async def _mark_applied(db, event: Dict):
    """Mark a feedback event as consumed/applied."""
    event_id = event.get("_id")
    if event_id:
        await db[FEEDBACK_COLLECTION].update_one(
            {"_id": event_id},
            {"$set": {"applied": True, "applied_at": datetime.now(timezone.utc).isoformat()}}
        )


async def _learn_vendor_alias(db, event: Dict):
    """
    When a user corrects a vendor name, create/update a vendor alias
    so the system recognizes this name next time.
    """
    before_vendor = (event.get("before") or {}).get("vendor", "")
    after_vendor = (event.get("after") or {}).get("vendor", "")
    vendor_id = event.get("vendor_id", "")
    
    if not before_vendor or not after_vendor or before_vendor == after_vendor:
        return False
    
    # Add to vendor_aliases collection
    normalized = before_vendor.strip().lower().replace(",", "").replace(".", "").replace("  ", " ").strip()
    await db.vendor_aliases.update_one(
        {"normalized_alias": normalized},
        {"$set": {
            "alias": before_vendor.strip(),
            "normalized_alias": normalized,
            "canonical_name": after_vendor,
            "vendor_no": vendor_id,
            "source": "user_correction",
            "learned_at": datetime.now(timezone.utc).isoformat(),
        },
        "$inc": {"correction_count": 1}},
        upsert=True,
    )
    
    logger.info("[FeedbackLearn] Vendor alias: '%s' -> '%s' (%s)", before_vendor, after_vendor, vendor_id)
    return True


async def _learn_classification_pattern(db, event: Dict):
    """
    When a user reclassifies a document, store this as a few-shot example
    that the AI classifier can use in future prompts.
    """
    before_type = (event.get("before") or {}).get("doc_type", "")
    after_type = (event.get("after") or {}).get("doc_type", "")
    doc_id = event.get("document_id", "")
    
    if not before_type or not after_type or before_type == after_type:
        return False
    
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
    doc = await db.hub_documents.find_one({"id": doc_id}, {
        "_id": 0, "file_name": 1, "vendor_canonical": 1,
        "raw_text": 1, "extracted_text": 1, "extracted_fields": 1
    })
    if doc:
        example["file_name"] = doc.get("file_name", "")
        example["vendor"] = doc.get("vendor_canonical", "")
        # Build text_snippet for few-shot examples
        raw_text = doc.get("raw_text") or doc.get("extracted_text") or ""
        if not raw_text:
            ef = doc.get("extracted_fields") or {}
            parts = [str(v) for v in ef.values() if v and not isinstance(v, (list, dict))]
            raw_text = " | ".join(parts)
        example["text_snippet"] = raw_text[:500]
    
    await db.classification_feedback.update_one(
        {"document_id": doc_id},
        {"$set": example},
        upsert=True,
    )
    
    # Also store in classification_corrections for few-shot prompting
    await db.classification_corrections.update_one(
        {"document_id": doc_id},
        {"$set": {
            "document_id": doc_id,
            "doc_id": doc_id,
            "original_type": before_type,
            "corrected_type": after_type,
            "vendor_no": event.get("vendor_id", ""),
            "vendor_canonical": example.get("vendor", ""),
            "file_name": example.get("file_name", ""),
            "text_snippet": example.get("text_snippet", ""),
            "corrected_at": datetime.now(timezone.utc).isoformat(),
            "source": "user_correction",
        }},
        upsert=True,
    )
    
    logger.info("[FeedbackLearn] Classification: %s -> %s (doc=%s)", before_type, after_type, doc_id[:20])
    return True


async def _learn_folder_routing(db, event: Dict):
    """
    When a user moves a document to a different folder, record this
    as a routing correction.
    """
    before_folder = (event.get("before") or {}).get("folder", "")
    after_folder = (event.get("after") or {}).get("folder", "")
    
    if not before_folder or not after_folder or before_folder == after_folder:
        return False
    
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
    return True


async def _update_vendor_track_record(db, event: Dict):
    """
    When a user approves or rejects a document, update the vendor's
    track record AND create a positive/negative reinforcement signal.
    Approvals confirm the current classification is correct.
    """
    vendor_id = event.get("vendor_id", "")
    if not vendor_id:
        return False
    
    is_approval = event["event_type"] == "approval"
    doc_id = event.get("document_id", "")
    
    # Increment the appropriate counter on the vendor profile
    inc_field = "feedback_approvals" if is_approval else "feedback_rejections"
    await db.vendor_intelligence_profiles.update_one(
        {"vendor_no": vendor_id},
        {
            "$inc": {inc_field: 1, "feedback_total": 1},
            "$set": {"last_feedback_at": datetime.now(timezone.utc).isoformat()},
        },
    )
    
    # For approvals: create positive reinforcement — confirm this vendor+type combo
    if is_approval and doc_id:
        doc = await db.hub_documents.find_one(
            {"id": doc_id},
            {"_id": 0, "suggested_job_type": 1, "document_type": 1,
             "vendor_canonical": 1, "file_name": 1, "extracted_fields": 1}
        )
        if doc:
            doc_type = doc.get("suggested_job_type") or doc.get("document_type") or ""
            vendor_name = doc.get("vendor_canonical") or ""
            
            # Store as a confirmed classification (positive example)
            if doc_type:
                await db.classification_corrections.update_one(
                    {"document_id": doc_id, "source": "approval_confirm"},
                    {"$set": {
                        "document_id": doc_id,
                        "original_type": doc_type,
                        "corrected_type": doc_type,  # Same type = confirmed correct
                        "vendor_no": vendor_id,
                        "vendor_canonical": vendor_name,
                        "file_name": doc.get("file_name", ""),
                        "corrected_at": datetime.now(timezone.utc).isoformat(),
                        "source": "approval_confirm",
                        "is_positive": True,
                    }},
                    upsert=True,
                )
            
            # Reinforce the vendor alias mapping
            if vendor_name:
                normalized = vendor_name.strip().lower().replace(",", "").replace(".", "").replace("  ", " ").strip()
                await db.vendor_aliases.update_one(
                    {"normalized_alias": normalized},
                    {
                        "$set": {
                            "canonical_name": vendor_name,
                            "vendor_no": vendor_id,
                            "last_confirmed_at": datetime.now(timezone.utc).isoformat(),
                        },
                        "$inc": {"confirmation_count": 1},
                    },
                )
    
    logger.info("[FeedbackLearn] Vendor %s: %s (doc=%s)", vendor_id, "approved" if is_approval else "rejected", doc_id[:12])
    return True


async def _learn_from_benchmark(db, event: Dict):
    """
    When a benchmark run reveals mismatches, each mismatch is a learning signal.
    """
    metadata = event.get("metadata") or {}
    field = metadata.get("field", "")
    truth = metadata.get("truth", "")
    predicted = metadata.get("predicted", "")
    
    if not field or not truth or not predicted:
        return False
    
    await db.benchmark_feedback.insert_one({
        "field": field,
        "truth": truth,
        "predicted": predicted,
        "vendor_id": event.get("vendor_id", ""),
        "document_id": event.get("document_id", ""),
        "learned_at": datetime.now(timezone.utc).isoformat(),
    })
    
    logger.info("[FeedbackLearn] Benchmark: %s truth='%s' predicted='%s'", field, truth[:20], predicted[:20])
    return True


async def _learn_po_pattern(db, event: Dict):
    """
    When a user corrects a PO number, learn the vendor's PO format.
    """
    before_po = str((event.get("before") or {}).get("po_number", "")).strip()
    after_po = str((event.get("after") or {}).get("po_number", "")).strip()
    vendor_id = event.get("vendor_id", "")
    doc_id = event.get("document_id", "")
    
    if not after_po:
        return False
    
    # Store the corrected PO for pattern analysis
    await db.po_corrections.update_one(
        {"document_id": doc_id},
        {"$set": {
            "document_id": doc_id,
            "vendor_no": vendor_id,
            "ai_extracted": before_po,
            "human_corrected": after_po,
            "po_length": len(after_po),
            "po_is_numeric": after_po.replace("-", "").replace(" ", "").isdigit(),
            "learned_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    
    # Update vendor profile with PO pattern info
    if vendor_id:
        await db.vendor_invoice_profiles.update_one(
            {"vendor_no": vendor_id},
            {
                "$set": {
                    "po_expected": True,
                    "last_po_correction_at": datetime.now(timezone.utc).isoformat(),
                },
                "$addToSet": {"po_examples": {"$each": [after_po]}},
            },
        )
    
    logger.info("[FeedbackLearn] PO correction: '%s' -> '%s' (vendor=%s)", before_po, after_po, vendor_id)
    return True


async def _learn_amount_pattern(db, event: Dict):
    """
    When a user corrects an amount, learn the vendor's typical amount range.
    """
    before_amt = (event.get("before") or {}).get("amount", "")
    after_amt = (event.get("after") or {}).get("amount", "")
    vendor_id = event.get("vendor_id", "")
    doc_id = event.get("document_id", "")
    
    if not after_amt:
        return False
    
    await db.amount_corrections.update_one(
        {"document_id": doc_id},
        {"$set": {
            "document_id": doc_id,
            "vendor_no": vendor_id,
            "ai_extracted": str(before_amt),
            "human_corrected": str(after_amt),
            "learned_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    
    logger.info("[FeedbackLearn] Amount correction: '%s' -> '%s' (vendor=%s)", before_amt, after_amt, vendor_id)
    return True


async def _learn_field_edit(db, event: Dict):
    """
    When a user edits any field, store it as a general correction signal.
    """
    before = event.get("before") or {}
    after = event.get("after") or {}
    vendor_id = event.get("vendor_id", "")
    doc_id = event.get("document_id", "")
    
    # Find which fields changed
    changed_fields = {}
    for key in set(list(before.keys()) + list(after.keys())):
        if str(before.get(key, "")) != str(after.get(key, "")):
            changed_fields[key] = {"before": before.get(key, ""), "after": after.get(key, "")}
    
    if not changed_fields:
        return False
    
    await db.field_corrections.update_one(
        {"document_id": doc_id, "fields": {"$exists": True}},
        {"$set": {
            "document_id": doc_id,
            "vendor_no": vendor_id,
            "changed_fields": changed_fields,
            "field_names": list(changed_fields.keys()),
            "learned_at": datetime.now(timezone.utc).isoformat(),
        }},
        upsert=True,
    )
    
    logger.info("[FeedbackLearn] Field edit: %s (vendor=%s, doc=%s)", list(changed_fields.keys()), vendor_id, doc_id[:12])
    return True


# ═══════════════════════════════════════════════════════════════
# PHASE 3: BUILD CONTEXT — Generate AI prompt context from feedback
# ═══════════════════════════════════════════════════════════════

async def build_feedback_context_for_prompt(db, vendor_id: str = "", doc_type: str = "") -> str:
    """
    Build a context section for the AI extraction prompt that includes
    learned patterns from user feedback.
    
    This is called by the classification pipeline before sending a document
    to the LLM. It enriches the prompt with:
    - Recent corrections for this vendor (from classification_corrections)
    - Classification patterns the AI got wrong before
    - Vendor profile intelligence (amounts, PO patterns, frequency)
    - Vendor aliases learned from corrections AND BC cache
    - General recent corrections
    
    This is HOW the AI gets smarter — every correction becomes a few-shot example,
    and every vendor profile becomes contextual intelligence.
    """
    context_parts = []
    
    # 1. Vendor-specific corrections (from rich classification_corrections)
    if vendor_id:
        vendor_upper = vendor_id.upper().strip()
        
        corrections = await db.classification_corrections.find(
            {"$or": [
                {"vendor_canonical": {"$regex": f"^{vendor_id}$", "$options": "i"}},
                {"vendor_raw": {"$regex": f"^{vendor_id}$", "$options": "i"}},
                {"vendor_canonical": vendor_upper},
                {"vendor_raw": vendor_upper},
                {"vendor_no": vendor_upper},
            ]},
            {"_id": 0}
        ).sort("corrected_at", -1).limit(5).to_list(5)
        
        # Filter out same-type "corrections" (noise)
        corrections = [c for c in corrections if c.get("original_type") != c.get("corrected_type")]
        
        if corrections:
            context_parts.append(f"LEARNED CORRECTIONS for vendor '{vendor_id}':")
            for c in corrections:
                text_hint = f" (text: '{c.get('text_snippet', '')[:80]}...')" if c.get('text_snippet') else ""
                context_parts.append(
                    f"  - File '{c.get('file_name', '?')}' was misclassified as "
                    f"'{c.get('original_type', '?')}', correct type is '{c.get('corrected_type', '?')}'{text_hint}"
                )
    
    # 2. General classification corrections for this doc_type
    if doc_type:
        type_corrections = await db.classification_corrections.find(
            {"original_type": doc_type},
            {"_id": 0, "original_type": 1, "corrected_type": 1, "vendor_canonical": 1}
        ).sort("corrected_at", -1).limit(5).to_list(5)
        
        if type_corrections:
            context_parts.append(f"NOTE: Documents classified as '{doc_type}' are sometimes actually:")
            for c in type_corrections:
                vendor_hint = f" (vendor: {c.get('vendor_canonical', '?')})" if c.get('vendor_canonical') else ""
                context_parts.append(f"  - '{c.get('corrected_type', '?')}'{vendor_hint}")
    
    # 3. Vendor invoice profile intelligence (from BC cache seed)
    if vendor_id:
        vendor_upper = vendor_id.upper().strip()
        profile = await db.vendor_invoice_profiles.find_one(
            {"$or": [{"vendor_no": vendor_id}, {"vendor_no": vendor_upper}, {"vendor_name": {"$regex": f"^{vendor_id}$", "$options": "i"}}]},
            {"_id": 0}
        )
        if profile:
            stats = profile.get("amount_stats", {})
            freq = profile.get("posting_frequency", {})
            context_parts.append(f"VENDOR PROFILE — '{profile.get('vendor_name', vendor_id)}' ({profile.get('vendor_no', '')}):")
            if stats.get("count", 0) > 0:
                context_parts.append(
                    f"  - Historical: {stats['count']} invoices, avg ${stats.get('mean', 0):,.2f}, "
                    f"range ${stats.get('min', 0):,.2f}-${stats.get('max', 0):,.2f}"
                )
            if profile.get("po_expected") is not None:
                context_parts.append(f"  - PO expected: {'YES' if profile['po_expected'] else 'NO (this vendor may not use PO numbers)'}")
            po_patterns = profile.get("po_patterns", {})
            if po_patterns.get("has_patterns"):
                context_parts.append(
                    f"  - PO format: avg length {po_patterns.get('avg_length', '?')}, "
                    f"{po_patterns.get('numeric_only_pct', 0)*100:.0f}% numeric-only"
                )
            if freq.get("frequency") and freq["frequency"] != "unknown":
                context_parts.append(f"  - Posting frequency: {freq['frequency']} ({freq.get('avg_per_month', '?')}/month)")
    
    # 4. Vendor aliases (from ALL sources — BC cache, Spiro, user corrections)
    if vendor_id:
        vendor_upper = vendor_id.upper().strip()
        aliases = await db.vendor_aliases.find(
            {"$or": [
                {"vendor_no": vendor_id},
                {"vendor_no": vendor_upper},
                {"canonical_vendor_id": vendor_id},
                {"canonical_vendor_id": vendor_upper},
            ]},
            {"_id": 0, "alias_string": 1, "alias": 1, "vendor_name": 1, "source": 1}
        ).limit(10).to_list(10)
        
        if aliases:
            context_parts.append("KNOWN VENDOR NAME VARIATIONS:")
            for a in aliases:
                name = a.get("alias_string") or a.get("alias") or "?"
                context_parts.append(f"  - '{name}' → '{a.get('vendor_name', '?')}' (source: {a.get('source', '?')})")
    
    # 5. Routing corrections for this vendor
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
    
    # 6. General recent corrections (always included, even without vendor context)
    # This ensures EVERY LLM call benefits from the feedback loop
    recent = await db.classification_corrections.find(
        {"$expr": {"$ne": ["$original_type", "$corrected_type"]}},
        {"_id": 0, "original_type": 1, "corrected_type": 1, "file_name": 1, "vendor_canonical": 1}
    ).sort("corrected_at", -1).limit(8).to_list(8)
    
    if recent:
        context_parts.append("RECENT SYSTEM-WIDE CORRECTIONS (learn from these):")
        for c in recent:
            vendor_label = c.get("vendor_canonical", "unknown")
            context_parts.append(
                f"  - Vendor '{vendor_label}': '{c.get('original_type', '?')}' → '{c.get('corrected_type', '?')}'"
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
    po_corrections = await db.po_corrections.count_documents({})
    amount_corrections = await db.amount_corrections.count_documents({})
    field_corrections = await db.field_corrections.count_documents({})
    
    return {
        "total_events": total,
        "applied_events": applied,
        "pending_events": total - applied,
        "events_by_type": by_type,
        "learning_signals": {
            "vendor_aliases_learned": aliases_learned,
            "classification_examples": classification_examples,
            "routing_corrections": routing_corrections,
            "po_corrections": po_corrections,
            "amount_corrections": amount_corrections,
            "field_corrections": field_corrections,
        },
    }


async def replay_unapplied_events(db) -> Dict[str, Any]:
    """
    Batch-replay all unapplied feedback events.
    Call this to retroactively apply events that were recorded before
    the handlers were fixed.
    """
    cursor = db[FEEDBACK_COLLECTION].find({"applied": {"$ne": True}})
    events = await cursor.to_list(5000)
    
    results = {"total": len(events), "applied": 0, "skipped": 0, "errors": 0}
    
    for event in events:
        try:
            await _apply_immediate_feedback(db, event)
            results["applied"] += 1
        except Exception as e:
            logger.warning("[FeedbackReplay] Error for event %s: %s", event.get("event_type"), e)
            results["errors"] += 1
    
    logger.info(
        "[FeedbackReplay] Replayed %d events: %d applied, %d errors",
        results["total"], results["applied"], results["errors"],
    )
    return results
