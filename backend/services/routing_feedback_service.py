"""
Routing Feedback Service — The learning layer for folder routing.

When documents are corrected (via benchmark fixes, manual overrides, or
the fix-truth endpoint), the corrections are stored here. On every future
routing decision, the feedback table is checked FIRST, before the
hardcoded rules in folder_routing_service.py.

Collections:
  routing_feedback — one doc per (vendor, doc_type, routing_key) combo
    {
      vendor_pattern: "tumaloc",
      doc_type: "AP_Invoice",
      routing_key: "tumaloc|AP_Invoice|has_po",
      correct_folder: "Miscellaneous Documents/Misc Invoices - need approval",
      confidence: 3,          # how many corrections confirmed this
      examples: ["0303907.pdf", ...],
      source: "benchmark_fix",
      created_at: "...",
      updated_at: "...",
    }
"""

import logging
from datetime import datetime, timezone
from typing import Optional, Dict, Any

logger = logging.getLogger(__name__)

COLLECTION = "routing_feedback"

_db = None


def init_feedback_db(db):
    """Initialize with the MongoDB database instance."""
    global _db
    _db = db


def _make_routing_key(vendor: str, doc_type: str, has_po: bool, is_international: bool) -> str:
    """Create a lookup key for feedback matching."""
    v = vendor.lower().strip()
    d = doc_type.strip()
    return f"{v}|{d}|{'po' if has_po else 'no_po'}|{'intl' if is_international else 'domestic'}"


async def record_correction(
    vendor: str,
    doc_type: str,
    has_po: bool,
    is_international: bool,
    correct_folder: str,
    file_name: str = "",
    source: str = "benchmark_fix",
) -> dict:
    """
    Record a routing correction. If a matching rule already exists,
    increment its confidence. Otherwise create a new rule.
    """
    if _db is None:
        return {"status": "no_db"}

    key = _make_routing_key(vendor, doc_type, has_po, is_international)
    now = datetime.now(timezone.utc).isoformat()

    existing = await _db[COLLECTION].find_one(
        {"routing_key": key},
        {"_id": 0}
    )

    if existing:
        # Strengthen existing rule
        examples = existing.get("examples", [])
        if file_name and file_name not in examples:
            examples.append(file_name)
            if len(examples) > 10:
                examples = examples[-10:]

        await _db[COLLECTION].update_one(
            {"routing_key": key},
            {"$set": {
                "correct_folder": correct_folder,
                "confidence": existing.get("confidence", 1) + 1,
                "examples": examples,
                "updated_at": now,
            }}
        )
        return {"status": "strengthened", "key": key, "confidence": existing.get("confidence", 1) + 1}
    else:
        await _db[COLLECTION].insert_one({
            "vendor_pattern": vendor.lower().strip(),
            "doc_type": doc_type,
            "has_po": has_po,
            "is_international": is_international,
            "routing_key": key,
            "correct_folder": correct_folder,
            "confidence": 1,
            "examples": [file_name] if file_name else [],
            "source": source,
            "created_at": now,
            "updated_at": now,
        })
        return {"status": "created", "key": key}


async def lookup_feedback(
    vendor: str,
    doc_type: str,
    has_po: bool,
    is_international: bool,
    min_confidence: int = 1,
) -> Optional[str]:
    """
    Check if we have a learned routing rule for this document profile.
    Returns the correct_folder if found, None otherwise.
    """
    if _db is None:
        return None

    key = _make_routing_key(vendor, doc_type, has_po, is_international)

    rule = await _db[COLLECTION].find_one(
        {"routing_key": key, "confidence": {"$gte": min_confidence}},
        {"_id": 0, "correct_folder": 1, "confidence": 1}
    )

    if rule:
        logger.info(f"[Feedback] Hit: {key} → {rule['correct_folder']} (confidence={rule['confidence']})")
        return rule["correct_folder"]

    return None


async def get_all_rules() -> list:
    """Return all learned routing rules."""
    if _db is None:
        return []
    rules = await _db[COLLECTION].find({}, {"_id": 0}).sort("confidence", -1).to_list(500)
    return rules


async def delete_rule(routing_key: str) -> bool:
    """Delete a specific learned rule."""
    if _db is None:
        return False
    result = await _db[COLLECTION].delete_one({"routing_key": routing_key})
    return result.deleted_count > 0


async def clear_all_rules() -> int:
    """Clear all learned rules (for testing/reset)."""
    if _db is None:
        return 0
    result = await _db[COLLECTION].delete_many({})
    return result.deleted_count
