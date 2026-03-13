"""
Item Mapping Service for BC Sales Order Line Creation

Maps extracted document line descriptions to BC item numbers using
multiple strategies: exact match, normalized text, aliases, and
historical reuse. Conservative by default — only assigns an item
number when confidence exceeds a safe threshold.
"""

import re
import logging
from typing import Optional, Dict, Any, List
from datetime import datetime, timezone

logger = logging.getLogger(__name__)

# Confidence thresholds
HIGH_CONFIDENCE = 0.90
MEDIUM_CONFIDENCE = 0.70
MIN_CONFIDENCE = 0.70  # Below this, we fall back instead of mapping

# MongoDB collection name
MAPPINGS_COLLECTION = "bc_item_mappings"
MAPPING_HISTORY_COLLECTION = "bc_item_mapping_history"


def _normalize(text: str) -> str:
    """Normalize text for fuzzy matching: lowercase, collapse whitespace, strip punctuation."""
    text = text.lower().strip()
    text = re.sub(r'[^a-z0-9\s]', ' ', text)
    text = re.sub(r'\s+', ' ', text).strip()
    return text


def _tokenize(text: str) -> set:
    """Split normalized text into word tokens."""
    return set(_normalize(text).split())


async def get_all_mappings(db, customer_no: str = None, active_only: bool = True) -> List[Dict]:
    """Fetch all item mappings, optionally filtered by customer and active status."""
    query = {}
    if active_only:
        query["active"] = True
    mappings = await db[MAPPINGS_COLLECTION].find(query, {"_id": 0}).sort("priority", 1).to_list(1000)

    # Sort: customer-specific first (if customer_no provided), then global
    if customer_no:
        customer_specific = [m for m in mappings if m.get("customer_no") == customer_no]
        global_mappings = [m for m in mappings if not m.get("customer_no")]
        return customer_specific + global_mappings

    return mappings


async def map_line_to_item(
    db,
    description: str,
    extracted_sku: str = "",
    customer_no: str = "",
    doc_id: str = "",
) -> Dict[str, Any]:
    """Attempt to map a line description to a BC item number.

    Returns:
        {
            "matched": bool,
            "item_number": str,
            "line_type": "Item" | "Comment",
            "confidence": float (0-1),
            "method": str,
            "mapping_id": str | None,
            "original_description": str,
        }
    """
    result = {
        "matched": False,
        "item_number": "",
        "line_type": "Comment",
        "confidence": 0.0,
        "method": "none",
        "mapping_id": None,
        "original_description": description,
    }

    if not description and not extracted_sku:
        return result

    norm_desc = _normalize(description)
    desc_tokens = _tokenize(description)

    # Strategy 1: Extracted SKU direct match
    if extracted_sku:
        result["matched"] = True
        result["item_number"] = extracted_sku
        result["line_type"] = "Item"
        result["confidence"] = HIGH_CONFIDENCE
        result["method"] = "extracted_sku"
        return result

    # Get all active mappings
    mappings = await get_all_mappings(db, customer_no=customer_no)

    if not mappings:
        # Try historical match
        hist_result = await _match_historical(db, norm_desc, customer_no, doc_id)
        if hist_result:
            return hist_result
        return result

    best_match = None
    best_confidence = 0.0

    for mapping in mappings:
        conf = _score_mapping(norm_desc, desc_tokens, mapping)
        if conf > best_confidence:
            best_confidence = conf
            best_match = mapping

    # Apply match if above threshold
    if best_match and best_confidence >= MIN_CONFIDENCE:
        result["matched"] = True
        result["item_number"] = best_match["bc_item_number"]
        result["line_type"] = "Item"
        result["confidence"] = round(best_confidence, 3)
        result["method"] = best_match.get("_match_method", "keyword")
        result["mapping_id"] = best_match.get("id")
        return result

    # Strategy: Historical match as last resort
    hist_result = await _match_historical(db, norm_desc, customer_no, doc_id)
    if hist_result:
        return hist_result

    return result


def _score_mapping(norm_desc: str, desc_tokens: set, mapping: Dict) -> float:
    """Score how well a mapping matches the normalized description."""
    keywords = mapping.get("keywords", [])
    aliases = mapping.get("aliases", [])
    norm_phrase = _normalize(mapping.get("keyword_phrase", ""))
    all_phrases = [norm_phrase] + [_normalize(a) for a in aliases] if aliases else [norm_phrase]

    best_score = 0.0
    best_method = "keyword"

    for phrase in all_phrases:
        if not phrase:
            continue

        # Exact phrase match (highest confidence)
        if phrase == norm_desc:
            mapping["_match_method"] = "exact_phrase"
            return 0.98

        # Phrase contained in description
        if phrase in norm_desc:
            score = 0.90 * (len(phrase) / max(len(norm_desc), 1))
            score = max(score, 0.75)  # Floor at 0.75 for contained phrases
            if score > best_score:
                best_score = score
                best_method = "phrase_contained"

        # Description contained in phrase (desc is subset)
        if norm_desc in phrase:
            score = 0.80 * (len(norm_desc) / max(len(phrase), 1))
            if score > best_score:
                best_score = score
                best_method = "desc_in_phrase"

    # Keyword token matching
    if keywords:
        norm_keywords = {_normalize(k) for k in keywords if k}
        if norm_keywords:
            matched_keywords = norm_keywords & desc_tokens
            if matched_keywords:
                ratio = len(matched_keywords) / len(norm_keywords)
                score = 0.85 * ratio
                if score > best_score:
                    best_score = score
                    best_method = "keyword_tokens"

    mapping["_match_method"] = best_method
    return best_score


async def _match_historical(
    db, norm_desc: str, customer_no: str, doc_id: str
) -> Optional[Dict]:
    """Check if we've successfully mapped this exact description before."""
    query = {"normalized_description": norm_desc, "matched": True}
    if customer_no:
        query["customer_no"] = customer_no

    history = await db[MAPPING_HISTORY_COLLECTION].find_one(
        query, {"_id": 0}, sort=[("created_at", -1)]
    )

    if history and history.get("item_number"):
        return {
            "matched": True,
            "item_number": history["item_number"],
            "line_type": "Item",
            "confidence": round(min(history.get("confidence", 0.7) * 0.95, 0.85), 3),
            "method": "historical_reuse",
            "mapping_id": history.get("mapping_id"),
            "original_description": norm_desc,
        }

    return None


async def record_mapping_history(
    db,
    doc_id: str,
    line_index: int,
    description: str,
    mapping_result: Dict,
    customer_no: str = "",
):
    """Store a mapping result for future historical reuse and audit."""
    record = {
        "doc_id": doc_id,
        "line_index": line_index,
        "original_description": description,
        "normalized_description": _normalize(description),
        "customer_no": customer_no,
        "matched": mapping_result.get("matched", False),
        "item_number": mapping_result.get("item_number", ""),
        "confidence": mapping_result.get("confidence", 0),
        "method": mapping_result.get("method", "none"),
        "mapping_id": mapping_result.get("mapping_id"),
        "created_at": datetime.now(timezone.utc).isoformat(),
    }
    await db[MAPPING_HISTORY_COLLECTION].insert_one(record)


# ── CRUD for mapping configuration ──

async def create_mapping(db, data: Dict) -> Dict:
    """Create a new item mapping rule."""
    import uuid as _uuid
    mapping = {
        "id": str(_uuid.uuid4()),
        "keyword_phrase": data.get("keyword_phrase", ""),
        "keywords": data.get("keywords", []),
        "aliases": data.get("aliases", []),
        "bc_item_number": data["bc_item_number"],
        "bc_item_description": data.get("bc_item_description", ""),
        "customer_no": data.get("customer_no", ""),
        "priority": data.get("priority", 100),
        "active": data.get("active", True),
        "created_at": datetime.now(timezone.utc).isoformat(),
        "updated_at": datetime.now(timezone.utc).isoformat(),
    }
    await db[MAPPINGS_COLLECTION].insert_one(mapping)
    mapping.pop("_id", None)
    return mapping


async def update_mapping(db, mapping_id: str, data: Dict) -> Optional[Dict]:
    """Update an existing mapping rule."""
    update_fields = {k: v for k, v in data.items() if k not in ("id", "_id", "created_at")}
    update_fields["updated_at"] = datetime.now(timezone.utc).isoformat()
    result = await db[MAPPINGS_COLLECTION].find_one_and_update(
        {"id": mapping_id},
        {"$set": update_fields},
        return_document=True,
    )
    if result:
        result.pop("_id", None)
    return result


async def delete_mapping(db, mapping_id: str) -> bool:
    """Delete a mapping rule."""
    result = await db[MAPPINGS_COLLECTION].delete_one({"id": mapping_id})
    return result.deleted_count > 0


async def list_mappings(db, customer_no: str = None, active_only: bool = False) -> List[Dict]:
    """List all mapping rules."""
    query = {}
    if customer_no:
        query["customer_no"] = customer_no
    if active_only:
        query["active"] = True
    mappings = await db[MAPPINGS_COLLECTION].find(query, {"_id": 0}).sort("priority", 1).to_list(500)
    return mappings
