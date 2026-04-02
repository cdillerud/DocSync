"""Classification Feedback Service — the learning loop.

When a user corrects a document's classification, we:
1. Store the correction (original → corrected, with doc context)
2. Build vendor→type patterns from historical corrections
3. Generate few-shot examples for the AI prompt from real corrections
4. Track accuracy metrics per doc type
"""
import logging
from datetime import datetime, timezone
from typing import Dict, List, Any, Optional
from collections import defaultdict

logger = logging.getLogger(__name__)

_db = None


def init_classification_feedback(db):
    global _db
    _db = db


async def record_correction(
    doc_id: str,
    original_type: str,
    corrected_type: str,
    corrected_by: str = "user",
    doc_context: Optional[Dict] = None,
) -> Dict:
    """Record a classification correction for learning."""
    if _db is None:
        return {"success": False, "reason": "db_not_initialized"}

    if original_type == corrected_type:
        return {"success": True, "skipped": True, "reason": "no_change"}

    doc_context = doc_context or {}
    record = {
        "doc_id": doc_id,
        "original_type": original_type,
        "corrected_type": corrected_type,
        "corrected_by": corrected_by,
        "corrected_at": datetime.now(timezone.utc).isoformat(),
        # Document context for few-shot examples
        "file_name": doc_context.get("file_name", ""),
        "vendor_raw": doc_context.get("vendor_raw", ""),
        "vendor_canonical": doc_context.get("vendor_canonical", ""),
        "text_snippet": doc_context.get("text_snippet", "")[:500],
        "classification_method": doc_context.get("classification_method", ""),
        "classification_confidence": doc_context.get("classification_confidence", 0),
    }

    await _db.classification_corrections.insert_one(record)

    # Update vendor→type pattern
    vendor = doc_context.get("vendor_canonical") or doc_context.get("vendor_raw") or ""
    if vendor:
        await _db.vendor_type_patterns.update_one(
            {"vendor": vendor.upper().strip()},
            {
                "$inc": {f"type_counts.{corrected_type}": 1, "total_corrections": 1},
                "$set": {"last_updated": datetime.now(timezone.utc).isoformat()},
                "$setOnInsert": {"vendor": vendor.upper().strip(), "created_at": datetime.now(timezone.utc).isoformat()},
            },
            upsert=True,
        )

    logger.info(
        "Classification correction: doc=%s, %s → %s (vendor=%s, by=%s)",
        doc_id, original_type, corrected_type, vendor, corrected_by,
    )
    return {"success": True, "original": original_type, "corrected": corrected_type}



async def record_confirmation(
    doc_id: str,
    confirmed_type: str,
    confirmation_source: str,
    doc_context: Optional[Dict] = None,
) -> Dict:
    """Record an implicit positive confirmation that the AI classification was correct.

    Called when a document completes its lifecycle without the user changing its type:
      - auto_clear: system auto-cleared the doc (high confidence)
      - file_and_clear: user filed to SharePoint without changing type
      - bulk_file_and_clear: same, bulk operation
      - completed: doc reached Completed status without correction
      - posted_to_bc: doc was posted to Business Central

    Unlike record_correction, this does NOT require a type change.
    It reinforces that the current type is correct.
    """
    if _db is None:
        return {"success": False, "reason": "db_not_initialized"}

    if not confirmed_type or confirmed_type in ("Unknown", "Unknown_Document", "", None):
        return {"success": True, "skipped": True, "reason": "unknown_type"}

    # Skip if we already have an entry for this doc (idempotent)
    existing = await _db.classification_corrections.find_one({"doc_id": doc_id}, {"_id": 1})
    if existing:
        return {"success": True, "skipped": True, "reason": "already_recorded"}

    doc_context = doc_context or {}

    # Confidence weight based on source
    confidence_map = {
        "auto_clear": 0.90,
        "file_and_clear": 0.95,
        "bulk_file_and_clear": 0.90,
        "completed": 0.85,
        "posted_to_bc": 0.95,
    }

    record = {
        "doc_id": doc_id,
        "original_type": confirmed_type,
        "corrected_type": confirmed_type,
        "corrected_by": f"confirmed_{confirmation_source}",
        "corrected_at": datetime.now(timezone.utc).isoformat(),
        "file_name": doc_context.get("file_name", ""),
        "vendor_raw": doc_context.get("vendor_raw", ""),
        "vendor_canonical": doc_context.get("vendor_canonical", ""),
        "text_snippet": doc_context.get("text_snippet", "")[:500],
        "classification_method": doc_context.get("classification_method", ""),
        "classification_confidence": confidence_map.get(confirmation_source, 0.80),
        "is_positive_confirmation": True,
    }

    await _db.classification_corrections.insert_one(record)

    # Update vendor→type pattern
    vendor = doc_context.get("vendor_canonical") or doc_context.get("vendor_raw") or ""
    if vendor:
        await _db.vendor_type_patterns.update_one(
            {"vendor": vendor.upper().strip()},
            {
                "$inc": {f"type_counts.{confirmed_type}": 1, "total_corrections": 1},
                "$set": {"last_updated": datetime.now(timezone.utc).isoformat()},
                "$setOnInsert": {"vendor": vendor.upper().strip(), "created_at": datetime.now(timezone.utc).isoformat()},
            },
            upsert=True,
        )

    logger.info(
        "Classification confirmed: doc=%s, type=%s (source=%s, vendor=%s)",
        doc_id, confirmed_type, confirmation_source, vendor,
    )
    return {"success": True, "confirmed_type": confirmed_type, "source": confirmation_source}



def _build_doc_context(doc: Dict) -> Dict:
    """Build doc_context dict from a hub_documents record."""
    raw_text = doc.get("raw_text") or doc.get("extracted_text") or ""
    if not raw_text:
        ef = doc.get("extracted_fields") or {}
        parts = [str(v) for v in ef.values() if v and not isinstance(v, (list, dict))]
        raw_text = " | ".join(parts)
    return {
        "file_name": doc.get("file_name", ""),
        "vendor_raw": doc.get("vendor_raw", ""),
        "vendor_canonical": doc.get("vendor_canonical", ""),
        "text_snippet": raw_text[:500],
        "classification_method": doc.get("classification_method", ""),
        "classification_confidence": doc.get("classification_confidence") or doc.get("ai_confidence") or 0,
    }


async def get_few_shot_examples(limit_per_type: int = 2, vendor_no: str = "") -> List[Dict]:
    """Get recent corrections grouped by corrected_type for few-shot prompting.
    
    Returns the most recent corrections for each document type,
    which will be injected into the AI classification prompt.
    
    Prioritizes:
    1. Corrections for the same vendor (most relevant)
    2. Recent corrections (last 30 days weighted higher)
    3. Corrections with high agreement (same correction made multiple times)
    """
    if _db is None:
        return []

    examples = []

    # Priority 1: Vendor-specific corrections (if vendor_no provided)
    if vendor_no:
        vendor_cursor = _db.classification_corrections.find(
            {"vendor_no": vendor_no},
            {"_id": 0, "file_name": 1, "vendor_canonical": 1, "text_snippet": 1,
             "original_type": 1, "corrected_type": 1, "corrected_at": 1}
        ).sort("corrected_at", -1).limit(3)
        
        vendor_examples = await vendor_cursor.to_list(3)
        for ex in vendor_examples:
            if ex.get("text_snippet"):
                ex["vendor"] = ex.get("vendor_canonical", "")
                ex["priority"] = "vendor_specific"
                examples.append(ex)

    # Priority 2: Recent corrections across all vendors, grouped by type
    pipeline = [
        {"$sort": {"corrected_at": -1}},
        {"$group": {
            "_id": "$corrected_type",
            "examples": {"$push": {
                "file_name": "$file_name",
                "vendor": "$vendor_canonical",
                "text_snippet": "$text_snippet",
                "original_type": "$original_type",
                "corrected_type": "$corrected_type",
                "corrected_at": "$corrected_at",
            }},
            "correction_count": {"$sum": 1},
        }},
        {"$sort": {"correction_count": -1}},
    ]

    results = await _db.classification_corrections.aggregate(pipeline).to_list(50)
    
    for group in results:
        count = group.get("correction_count", 0)
        
        # More examples for frequently corrected types
        type_limit = limit_per_type
        if count >= 10:
            type_limit = 3
        elif count >= 5:
            type_limit = 2

        for ex in group["examples"][:type_limit]:
            # Include examples even without text_snippet — use filename+vendor as context
            if len(examples) < 12:
                # Skip same-type "corrections" (AP_Invoice -> AP_Invoice is noise, not signal)
                if ex.get("original_type") == ex.get("corrected_type"):
                    continue
                if not ex.get("priority"):
                    ex["priority"] = "recent"
                examples.append(ex)

    return examples


async def get_vendor_type_hint(vendor: str) -> Optional[str]:
    """Get the most common document type for a vendor based on historical corrections.
    
    Returns the dominant type if one vendor consistently sends the same type.
    """
    if _db is None or not vendor:
        return None

    pattern = await _db.vendor_type_patterns.find_one(
        {"vendor": vendor.upper().strip()}, {"_id": 0}
    )
    if not pattern:
        return None

    type_counts = pattern.get("type_counts", {})
    if not type_counts:
        return None

    total = sum(type_counts.values())
    if total < 2:
        return None  # Need at least 2 corrections before suggesting

    dominant_type = max(type_counts, key=type_counts.get)
    dominant_pct = type_counts[dominant_type] / total

    if dominant_pct >= 0.7:  # 70%+ of corrections point to this type
        return dominant_type

    return None


async def build_few_shot_prompt_section(vendor_no: str = "") -> str:
    """Build the few-shot examples section to inject into the classification prompt."""
    examples = await get_few_shot_examples(limit_per_type=2, vendor_no=vendor_no)
    if not examples:
        return ""

    lines = [
        "\n== LEARNED EXAMPLES (from previous corrections) ==",
        "These are real documents that were initially misclassified and then corrected by a human reviewer.",
        "Use these examples to improve your classification accuracy:\n",
    ]

    for ex in examples:
        snippet = ex.get("text_snippet", "")[:200]
        vendor = ex.get("vendor") or ex.get("vendor_canonical") or "unknown"
        fname = ex.get("file_name", "unknown")
        orig = ex.get("original_type", "?")
        correct = ex.get("corrected_type", "?")
        
        # Build example line — include text snippet when available
        example_line = f'- File: "{fname}" from vendor "{vendor}"'
        if snippet:
            example_line += f'\n  Text snippet: "{snippet}..."'
        example_line += (
            f"\n  WRONG classification: {orig}"
            f"\n  CORRECT classification: {correct}\n"
        )
        lines.append(example_line)

    return "\n".join(lines)


async def build_vendor_hints_prompt_section(vendor_raw: str) -> str:
    """Build a vendor-specific hint for the classification prompt."""
    if not vendor_raw:
        return ""

    hint_type = await get_vendor_type_hint(vendor_raw)
    if not hint_type:
        return ""

    return (
        f'\n== VENDOR HINT ==\n'
        f'Documents from vendor "{vendor_raw}" are most commonly classified as {hint_type}.\n'
        f'This is based on historical corrections. Still analyze the document content, '
        f'but weight this hint when the content is ambiguous.\n'
    )


async def get_accuracy_metrics() -> Dict[str, Any]:
    """Get classification accuracy metrics."""
    if _db is None:
        return {"error": "db_not_initialized"}

    total_corrections = await _db.classification_corrections.count_documents({})

    # Confusion matrix: original_type → corrected_type counts
    pipeline = [
        {"$group": {
            "_id": {"original": "$original_type", "corrected": "$corrected_type"},
            "count": {"$sum": 1},
        }},
        {"$sort": {"count": -1}},
    ]
    confusion = await _db.classification_corrections.aggregate(pipeline).to_list(100)

    confusion_matrix = {}
    for c in confusion:
        orig = c["_id"]["original"]
        corr = c["_id"]["corrected"]
        key = f"{orig} → {corr}"
        confusion_matrix[key] = c["count"]

    # Most corrected types (worst accuracy)
    type_pipeline = [
        {"$group": {"_id": "$original_type", "correction_count": {"$sum": 1}}},
        {"$sort": {"correction_count": -1}},
        {"$limit": 10},
    ]
    worst_types = await _db.classification_corrections.aggregate(type_pipeline).to_list(10)

    # Vendor patterns
    vendor_patterns = await _db.vendor_type_patterns.find(
        {}, {"_id": 0}
    ).sort("total_corrections", -1).to_list(20)

    return {
        "total_corrections": total_corrections,
        "confusion_matrix": confusion_matrix,
        "most_corrected_types": [
            {"type": t["_id"], "corrections": t["correction_count"]} for t in worst_types
        ],
        "vendor_patterns": vendor_patterns,
    }



# ---------------------------------------------------------------------------
# Bootstrap sweep — mine existing documents for learning data
# ---------------------------------------------------------------------------

_bootstrap_status = {"running": False, "progress": None}


def get_bootstrap_status() -> Dict:
    return dict(_bootstrap_status)


async def bootstrap_from_history() -> Dict[str, Any]:
    """One-time sweep of all existing documents to bootstrap the learning model.

    Confidence tiers (highest → lowest):
      Tier 1: Documents with manual corrections in intel results (gold standard).
      Tier 2: High-AI-confidence (≥0.85) documents that were auto-cleared.
      Tier 3: Completed documents with a valid (non-Unknown/None) type.

    Idempotent — skips documents that already have an entry in classification_corrections.
    Updates vendor_type_patterns for every new entry.
    """
    global _bootstrap_status
    if _db is None:
        return {"success": False, "reason": "db_not_initialized"}

    _bootstrap_status = {"running": True, "progress": "starting"}

    # Gather doc_ids already in corrections to avoid duplicates
    existing_ids = set()
    cursor = _db.classification_corrections.find({}, {"doc_id": 1, "_id": 0})
    async for rec in cursor:
        existing_ids.add(rec["doc_id"])

    stats = {"tier1_manual": 0, "tier2_high_conf": 0, "tier3_completed": 0, "skipped_existing": 0, "skipped_invalid": 0, "total_processed": 0, "vendor_patterns_updated": 0}

    valid_types = {
        "AP_Invoice", "AR_Invoice", "Credit_Memo", "Remittance", "Freight_Document",
        "Sales_Order", "Sales_PO", "Sales_Quote", "Order_Confirmation",
        "Purchase_Order", "Warehouse_Receipt", "Warehouse_Document",
        "Inventory_Report", "Shipping_Document", "Quality_Issue",
        "Return_Request",
    }

    # ---------- Tier 1: Manual corrections from intel results ----------
    _bootstrap_status["progress"] = "tier1_manual_corrections"
    intel_corrected = _db.document_intelligence_results.find(
        {"manually_corrected": True, "correction_history": {"$exists": True, "$ne": []}},
        {"_id": 0},
    )
    async for intel in intel_corrected:
        doc_id = intel.get("document_id", "")
        if doc_id in existing_ids:
            stats["skipped_existing"] += 1
            continue

        history = intel.get("correction_history", [])
        if not history:
            continue

        # Use the final corrected type from correction chain
        final_type = intel.get("document_type", "")
        original_type = history[0].get("changes", {}).get("document_type", {}).get("from", "Unknown")
        if not final_type or final_type not in valid_types:
            stats["skipped_invalid"] += 1
            continue

        # Get the hub document for context
        hub_doc = await _db.hub_documents.find_one({"id": doc_id}, {"_id": 0, "file_name": 1, "vendor_raw": 1, "vendor_canonical": 1})
        hub_doc = hub_doc or {}

        record = {
            "doc_id": doc_id,
            "original_type": original_type,
            "corrected_type": final_type,
            "corrected_by": "bootstrap_tier1_manual",
            "corrected_at": datetime.now(timezone.utc).isoformat(),
            "file_name": hub_doc.get("file_name", ""),
            "vendor_raw": hub_doc.get("vendor_raw") or "",
            "vendor_canonical": hub_doc.get("vendor_canonical") or "",
            "text_snippet": f"[manual correction from intel history] file={hub_doc.get('file_name', '')}",
            "classification_method": "manual_correction",
            "classification_confidence": 1.0,
        }
        await _db.classification_corrections.insert_one(record)
        existing_ids.add(doc_id)
        stats["tier1_manual"] += 1
        await _update_vendor_pattern(hub_doc.get("vendor_canonical") or hub_doc.get("vendor_raw") or "", final_type, stats)

    # ---------- Tier 2: High confidence + auto-cleared ----------
    _bootstrap_status["progress"] = "tier2_high_confidence"
    high_conf_intels = _db.document_intelligence_results.find(
        {"classification_confidence": {"$gte": 0.85}},
        {"_id": 0, "document_id": 1, "document_type": 1, "classification_confidence": 1},
    )
    async for intel in high_conf_intels:
        doc_id = intel.get("document_id", "")
        doc_type = intel.get("document_type", "")
        if doc_id in existing_ids:
            stats["skipped_existing"] += 1
            continue
        if not doc_type or doc_type not in valid_types:
            stats["skipped_invalid"] += 1
            continue

        # Check if auto-cleared in hub
        hub_doc = await _db.hub_documents.find_one(
            {"id": doc_id, "auto_cleared": True},
            {"_id": 0, "file_name": 1, "vendor_raw": 1, "vendor_canonical": 1},
        )
        if not hub_doc:
            continue  # Skip non-auto-cleared docs for tier 2

        record = {
            "doc_id": doc_id,
            "original_type": doc_type,
            "corrected_type": doc_type,
            "corrected_by": "bootstrap_tier2_high_conf",
            "corrected_at": datetime.now(timezone.utc).isoformat(),
            "file_name": hub_doc.get("file_name", ""),
            "vendor_raw": hub_doc.get("vendor_raw") or "",
            "vendor_canonical": hub_doc.get("vendor_canonical") or "",
            "text_snippet": f"[auto-cleared, confidence={intel.get('classification_confidence', 0):.2f}] file={hub_doc.get('file_name', '')}",
            "classification_method": "ai_high_confidence",
            "classification_confidence": intel.get("classification_confidence", 0),
        }
        await _db.classification_corrections.insert_one(record)
        existing_ids.add(doc_id)
        stats["tier2_high_conf"] += 1
        await _update_vendor_pattern(hub_doc.get("vendor_canonical") or hub_doc.get("vendor_raw") or "", doc_type, stats)

    # ---------- Tier 3: Completed documents with valid type ----------
    _bootstrap_status["progress"] = "tier3_completed"
    completed_docs = _db.hub_documents.find(
        {"status": "Completed", "document_type": {"$in": list(valid_types)}},
        {"_id": 0, "id": 1, "document_type": 1, "file_name": 1, "vendor_raw": 1, "vendor_canonical": 1},
    )
    async for doc in completed_docs:
        doc_id = doc.get("id", "")
        doc_type = doc.get("document_type", "")
        if doc_id in existing_ids:
            stats["skipped_existing"] += 1
            continue

        record = {
            "doc_id": doc_id,
            "original_type": doc_type,
            "corrected_type": doc_type,
            "corrected_by": "bootstrap_tier3_completed",
            "corrected_at": datetime.now(timezone.utc).isoformat(),
            "file_name": doc.get("file_name", ""),
            "vendor_raw": doc.get("vendor_raw") or "",
            "vendor_canonical": doc.get("vendor_canonical") or "",
            "text_snippet": f"[completed doc, accepted type] file={doc.get('file_name', '')}",
            "classification_method": "completed_lifecycle",
            "classification_confidence": 0.75,
        }
        await _db.classification_corrections.insert_one(record)
        existing_ids.add(doc_id)
        stats["tier3_completed"] += 1
        await _update_vendor_pattern(doc.get("vendor_canonical") or doc.get("vendor_raw") or "", doc_type, stats)

    stats["total_processed"] = stats["tier1_manual"] + stats["tier2_high_conf"] + stats["tier3_completed"]
    _bootstrap_status = {"running": False, "progress": "done", "stats": stats}
    logger.info("Bootstrap sweep complete: %s", stats)
    return {"success": True, "stats": stats}


async def _update_vendor_pattern(vendor: str, doc_type: str, stats: Dict):
    """Helper to update vendor_type_patterns during bootstrap."""
    if not vendor or _db is None:
        return
    vendor_key = vendor.upper().strip()
    if not vendor_key:
        return
    await _db.vendor_type_patterns.update_one(
        {"vendor": vendor_key},
        {
            "$inc": {f"type_counts.{doc_type}": 1, "total_corrections": 1},
            "$set": {"last_updated": datetime.now(timezone.utc).isoformat()},
            "$setOnInsert": {"vendor": vendor_key, "created_at": datetime.now(timezone.utc).isoformat()},
        },
        upsert=True,
    )
    stats["vendor_patterns_updated"] += 1



async def backfill_classification_corrections() -> Dict[str, Any]:
    """Enrich existing classification_corrections that are missing text_snippet,
    vendor_no, vendor_canonical, or file_name by looking up the source document.
    
    Also removes noise entries (same original_type == corrected_type).
    """
    if _db is None:
        return {"success": False, "reason": "db_not_initialized"}

    stats = {"enriched": 0, "noise_removed": 0, "already_complete": 0, "doc_not_found": 0}

    cursor = _db.classification_corrections.find({}, {"_id": 1, "doc_id": 1, "document_id": 1,
        "original_type": 1, "corrected_type": 1, "text_snippet": 1,
        "vendor_no": 1, "vendor_canonical": 1, "file_name": 1, "source": 1})

    async for corr in cursor:
        corr_id = corr["_id"]
        doc_id = corr.get("doc_id") or corr.get("document_id", "")
        orig = corr.get("original_type", "")
        corrected = corr.get("corrected_type", "")

        # Remove noise: same-type "corrections"
        if orig and corrected and orig == corrected:
            await _db.classification_corrections.delete_one({"_id": corr_id})
            stats["noise_removed"] += 1
            continue

        # Check if already has all fields
        has_snippet = bool(corr.get("text_snippet"))
        has_vendor = bool(corr.get("vendor_no") or corr.get("vendor_canonical"))
        has_file = bool(corr.get("file_name"))
        if has_snippet and has_vendor and has_file:
            stats["already_complete"] += 1
            continue

        # Lookup the source document to enrich
        if not doc_id:
            continue

        hub_doc = await _db.hub_documents.find_one({"id": doc_id}, {
            "_id": 0, "file_name": 1, "vendor_raw": 1, "vendor_canonical": 1,
            "vendor_no": 1, "bc_vendor_number": 1, "raw_text": 1,
            "extracted_text": 1, "extracted_fields": 1,
        })

        if not hub_doc:
            stats["doc_not_found"] += 1
            continue

        updates = {}

        # Enrich text_snippet
        if not has_snippet:
            raw_text = hub_doc.get("raw_text") or hub_doc.get("extracted_text") or ""
            if not raw_text:
                ef = hub_doc.get("extracted_fields") or {}
                parts = [str(v) for v in ef.values() if v and not isinstance(v, (list, dict))]
                raw_text = " | ".join(parts)
            if raw_text:
                updates["text_snippet"] = raw_text[:500]

        # Enrich vendor
        if not has_vendor:
            v_canonical = hub_doc.get("vendor_canonical") or ""
            v_no = hub_doc.get("vendor_no") or hub_doc.get("bc_vendor_number") or ""
            if v_canonical:
                updates["vendor_canonical"] = v_canonical
            if v_no:
                updates["vendor_no"] = v_no

        # Enrich file_name
        if not has_file and hub_doc.get("file_name"):
            updates["file_name"] = hub_doc["file_name"]

        # Set source if missing
        if not corr.get("source"):
            updates["source"] = "backfill_enrichment"

        if updates:
            await _db.classification_corrections.update_one({"_id": corr_id}, {"$set": updates})
            stats["enriched"] += 1
        else:
            stats["already_complete"] += 1

    logger.info("[FeedbackBackfill] Classification corrections enriched: %s", stats)
    return {"success": True, "stats": stats}
