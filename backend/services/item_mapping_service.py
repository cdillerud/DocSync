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
    """Attempt to map a line description to a BC item number or G/L account.

    Returns:
        {
            "matched": bool,
            "target_type": "item" | "gl_account" | "comment",
            "target_no": str,          # BC item number or GL account number
            "target_description": str,  # Catalog description of the target
            "line_type": "Item" | "Account" | "Comment",  # BC sales line type
            "confidence": float (0-1),
            "method": str,
            "mapping_id": str | None,
            "catalog_validated": bool,
            "original_description": str,
        }
    """
    result = {
        "matched": False,
        "target_type": "comment",
        "target_no": "",
        "target_description": "",
        "line_type": "Comment",
        "confidence": 0.0,
        "method": "none",
        "mapping_id": None,
        "catalog_validated": False,
        "original_description": description,
    }

    if not description and not extracted_sku:
        return result

    norm_desc = _normalize(description)
    desc_tokens = _tokenize(description)

    # Strategy 1: Extracted SKU direct match → always Item type
    if extracted_sku:
        cat_check = await _validate_target(db, "item", extracted_sku)
        result["matched"] = True
        result["target_type"] = "item"
        result["target_no"] = extracted_sku
        result["target_description"] = cat_check.get("description", "")
        result["line_type"] = "Item"
        result["confidence"] = HIGH_CONFIDENCE
        result["method"] = "extracted_sku"
        result["catalog_validated"] = cat_check.get("valid", False)
        return result

    # Strategy 2: Configured mapping rules
    mappings = await get_all_mappings(db, customer_no=customer_no)

    best_match = None
    best_confidence = 0.0

    for mapping in mappings:
        conf = _score_mapping(norm_desc, desc_tokens, mapping)
        if conf > best_confidence:
            best_confidence = conf
            best_match = mapping

    if best_match and best_confidence >= MIN_CONFIDENCE:
        target_type = best_match.get("target_type", "item")
        target_no = best_match.get("target_no") or best_match.get("bc_item_number", "")

        # Validate the target isn't blocked
        cat_check = await _validate_target(db, target_type, target_no)
        if cat_check.get("reason") == "blocked":
            logger.warning("Mapped target %s/%s is blocked — skipping", target_type, target_no)
        else:
            bc_line_type = "Account" if target_type == "gl_account" else "Item"
            result["matched"] = True
            result["target_type"] = target_type
            result["target_no"] = target_no
            result["target_description"] = cat_check.get("description", best_match.get("bc_item_description", ""))
            result["line_type"] = bc_line_type
            result["confidence"] = round(best_confidence, 3)
            result["method"] = best_match.get("_match_method", "keyword")
            result["mapping_id"] = best_match.get("id")
            result["catalog_validated"] = cat_check.get("valid", False)
            return result

    # Strategy 3: Direct catalog description match (items only)
    if not mappings or not best_match:
        hist_result = await _match_historical(db, norm_desc, customer_no, doc_id)
        if hist_result:
            return hist_result

    catalog_result = await _match_catalog_description(db, norm_desc, desc_tokens)
    if catalog_result:
        return catalog_result

    # Strategy 4: Historical match as last resort
    hist_result = await _match_historical(db, norm_desc, customer_no, doc_id)
    if hist_result:
        return hist_result

    return result


async def _validate_target(db, target_type: str, target_no: str) -> Dict[str, Any]:
    """Validate a mapping target (item or GL account) against the synced catalog."""
    from services.bc_catalog_sync_service import ITEMS_COLLECTION, GL_ACCOUNTS_COLLECTION

    if target_type == "gl_account":
        count = await db[GL_ACCOUNTS_COLLECTION].count_documents({})
        if count == 0:
            return {"valid": True, "reason": "no_catalog", "description": ""}
        acct = await db[GL_ACCOUNTS_COLLECTION].find_one({"account_no": target_no}, {"_id": 0})
        if not acct:
            return {"valid": False, "reason": "not_found", "description": ""}
        if acct.get("blocked"):
            return {"valid": False, "reason": "blocked", "description": acct.get("name", "")}
        return {"valid": True, "reason": "ok", "description": acct.get("name", "")}
    else:
        # Item validation
        count = await db[ITEMS_COLLECTION].count_documents({})
        if count == 0:
            return {"valid": True, "reason": "no_catalog", "description": ""}
        item = await db[ITEMS_COLLECTION].find_one({"item_no": target_no}, {"_id": 0})
        if not item:
            return {"valid": False, "reason": "not_found", "description": ""}
        if item.get("blocked"):
            return {"valid": False, "reason": "blocked", "description": item.get("description", "")}
        return {"valid": True, "reason": "ok", "description": item.get("description", "")}


async def _match_catalog_description(
    db, norm_desc: str, desc_tokens: set
) -> Optional[Dict[str, Any]]:
    """Try to find an exact or near-exact description match in the synced BC item catalog."""
    from services.bc_catalog_sync_service import ITEMS_COLLECTION

    catalog_count = await db[ITEMS_COLLECTION].count_documents({})
    if catalog_count == 0:
        return None  # No catalog synced

    # Strategy A: Exact normalized description match
    items = await db[ITEMS_COLLECTION].find(
        {"blocked": {"$ne": True}}, {"_id": 0}
    ).to_list(5000)

    best_item = None
    best_score = 0.0

    for item in items:
        item_norm = _normalize(item.get("description", ""))
        if not item_norm:
            continue

        # Exact match
        if item_norm == norm_desc:
            return {
                "matched": True,
                "target_type": "item",
                "target_no": item["item_no"],
                "target_description": item.get("description", ""),
                "line_type": "Item",
                "confidence": 0.92,
                "method": "catalog_exact",
                "mapping_id": None,
                "catalog_validated": True,
                "original_description": norm_desc,
            }

        # Token overlap scoring
        item_tokens = _tokenize(item.get("description", ""))
        if item_tokens and desc_tokens:
            overlap = item_tokens & desc_tokens
            if len(overlap) >= 2:
                score = len(overlap) / max(len(item_tokens), len(desc_tokens))
                if score > best_score:
                    best_score = score
                    best_item = item

    # Only accept catalog matches with high token overlap
    if best_item and best_score >= 0.75:
        return {
            "matched": True,
            "target_type": "item",
            "target_no": best_item["item_no"],
            "target_description": best_item.get("description", ""),
            "line_type": "Item",
            "confidence": round(min(best_score * 0.90, 0.88), 3),
            "method": "catalog_description",
            "mapping_id": None,
            "catalog_validated": True,
            "original_description": norm_desc,
        }

    return None


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
            ratio = len(phrase) / max(len(norm_desc), 1)
            score = 0.90 * ratio
            # Only boost short phrases if they're a significant portion of the description
            if ratio >= 0.4:
                score = max(score, 0.75)
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
            "target_type": history.get("target_type", "item"),
            "target_no": history["item_number"],
            "target_description": history.get("target_description", ""),
            "line_type": "Account" if history.get("target_type") == "gl_account" else "Item",
            "confidence": round(min(history.get("confidence", 0.7) * 0.95, 0.85), 3),
            "method": "historical_reuse",
            "mapping_id": history.get("mapping_id"),
            "catalog_validated": False,
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
        "item_number": mapping_result.get("target_no", ""),
        "target_type": mapping_result.get("target_type", "comment"),
        "target_description": mapping_result.get("target_description", ""),
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
        "target_type": data.get("target_type", "item"),
        "target_no": data.get("target_no", data.get("bc_item_number", "")),
        "bc_item_number": data.get("target_no", data.get("bc_item_number", "")),  # backwards compat
        "bc_item_description": data.get("bc_item_description", data.get("target_description", "")),
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
