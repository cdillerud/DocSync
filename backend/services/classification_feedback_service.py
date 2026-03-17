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


async def get_few_shot_examples(limit_per_type: int = 2) -> List[Dict]:
    """Get recent corrections grouped by corrected_type for few-shot prompting.
    
    Returns the most recent corrections for each document type,
    which will be injected into the AI classification prompt.
    """
    if _db is None:
        return []

    # Get unique corrected types
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
            }},
        }},
    ]

    results = await _db.classification_corrections.aggregate(pipeline).to_list(50)
    
    examples = []
    for group in results:
        doc_type = group["_id"]
        for ex in group["examples"][:limit_per_type]:
            if ex.get("text_snippet"):
                examples.append(ex)

    return examples


async def get_vendor_type_hint(vendor: str) -> Optional[str]:
    """Get the most common document type for a vendor based on historical corrections.
    
    Returns the dominant type if one vendor consistently sends the same type.
    """
    if not _db or not vendor:
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


async def build_few_shot_prompt_section() -> str:
    """Build the few-shot examples section to inject into the classification prompt."""
    examples = await get_few_shot_examples(limit_per_type=2)
    if not examples:
        return ""

    lines = [
        "\n== LEARNED EXAMPLES (from previous corrections) ==",
        "These are real documents that were initially misclassified and then corrected by a human reviewer.",
        "Use these examples to improve your classification accuracy:\n",
    ]

    for ex in examples:
        snippet = ex.get("text_snippet", "")[:200]
        vendor = ex.get("vendor", "unknown")
        fname = ex.get("file_name", "unknown")
        orig = ex.get("original_type", "?")
        correct = ex.get("corrected_type", "?")
        lines.append(
            f'- File: "{fname}" from vendor "{vendor}"'
            f'\n  Text snippet: "{snippet}..."'
            f"\n  WRONG classification: {orig}"
            f"\n  CORRECT classification: {correct}\n"
        )

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
