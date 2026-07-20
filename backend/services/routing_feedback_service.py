"""
Routing Feedback Service — the learning layer for folder routing.

Corrections are stored per vendor/document profile and checked before the
hard-coded folder rules. Vendor identity is deliberately alias-aware: a rule
learned from a raw invoice name must still match after the document is resolved
to a BC vendor number or canonical vendor code.
"""

import logging
import re
from datetime import datetime, timezone
from typing import Optional, Dict, Any, List

logger = logging.getLogger(__name__)

COLLECTION = "routing_feedback"
_db = None


def init_feedback_db(db):
    """Initialize with the MongoDB database instance."""
    global _db
    _db = db


def _normalize_vendor(value: Any) -> str:
    """Return the stable comparison form used for feedback keys."""
    if value is None:
        return ""
    raw = str(value).strip()
    if not raw:
        return ""
    try:
        from services.vendor_name_helpers import normalize_vendor_name
        normalized = normalize_vendor_name(raw)
        if normalized:
            return str(normalized).strip().lower()
    except Exception:
        pass
    return re.sub(r"\s+", " ", raw).strip().lower()


def _make_routing_key(vendor: str, doc_type: str, has_po: bool, is_international: bool) -> str:
    """Create a lookup key for feedback matching."""
    v = _normalize_vendor(vendor)
    d = str(doc_type or "").strip()
    return f"{v}|{d}|{'po' if has_po else 'no_po'}|{'intl' if is_international else 'domestic'}"


def _exact_ci(value: str) -> Dict[str, Any]:
    return {"$regex": f"^{re.escape(str(value).strip())}$", "$options": "i"}


def _append_candidate(
    candidates: List[Dict[str, Any]],
    seen: set,
    value: Any,
    *,
    source: str,
    stable: bool = False,
) -> None:
    normalized = _normalize_vendor(value)
    if not normalized or normalized in seen:
        return
    seen.add(normalized)
    candidates.append({
        "value": str(value).strip(),
        "normalized": normalized,
        "source": source,
        "stable": stable,
    })


async def _vendor_candidates(vendor: str) -> List[Dict[str, Any]]:
    """Resolve canonical IDs, names, and historical aliases for a vendor value.

    Sources are intentionally redundant because production records span several
    schema generations: vendor_aliases, cached BC vendors, sender mappings, and
    previously processed Hub documents.
    """
    candidates: List[Dict[str, Any]] = []
    seen = set()
    _append_candidate(candidates, seen, vendor, source="input", stable=False)

    if _db is None or not str(vendor or "").strip():
        return candidates

    raw = str(vendor).strip()
    normalized_input = _normalize_vendor(raw)
    exact = _exact_ci(raw)
    normalized_exact = _exact_ci(normalized_input)

    canonical_ids = set()

    # Alias records can be keyed by raw name, normalized alias, canonical ID,
    # vendor number, or display name depending on when they were created.
    alias_query = {"$or": [
        {"alias_string": exact},
        {"alias": exact},
        {"normalized_alias": normalized_exact},
        {"normalized": normalized_exact},
        {"canonical_vendor_id": exact},
        {"vendor_no": exact},
        {"vendor_id": exact},
        {"vendor_name": exact},
    ]}
    try:
        alias_rows = await _db.vendor_aliases.find(alias_query, {"_id": 0}).to_list(100)
    except Exception:
        alias_rows = []

    for row in alias_rows:
        for key in ("canonical_vendor_id", "vendor_no", "vendor_id"):
            value = row.get(key)
            if value:
                canonical_ids.add(str(value).strip())
                _append_candidate(candidates, seen, value, source=f"vendor_aliases.{key}", stable=True)
        for key in ("vendor_name", "alias_string", "alias", "normalized_alias", "normalized"):
            _append_candidate(candidates, seen, row.get(key), source=f"vendor_aliases.{key}")

    # Once a canonical ID is known, collect every sibling alias attached to it.
    if canonical_ids:
        canonical_values = list(canonical_ids)
        try:
            sibling_rows = await _db.vendor_aliases.find(
                {"$or": [
                    {"canonical_vendor_id": {"$in": canonical_values}},
                    {"vendor_no": {"$in": canonical_values}},
                    {"vendor_id": {"$in": canonical_values}},
                ]},
                {"_id": 0},
            ).to_list(500)
        except Exception:
            sibling_rows = []
        for row in sibling_rows:
            for key in ("canonical_vendor_id", "vendor_no", "vendor_id"):
                _append_candidate(candidates, seen, row.get(key), source=f"vendor_aliases.{key}", stable=True)
            for key in ("vendor_name", "alias_string", "alias", "normalized_alias", "normalized"):
                _append_candidate(candidates, seen, row.get(key), source=f"vendor_aliases.{key}")

    # Cached BC vendor metadata supplies the canonical number/display-name pair.
    try:
        bc_rows = await _db.hub_bc_vendors.find(
            {"$or": [
                {"number": exact},
                {"id": exact},
                {"displayName": exact},
                {"name_normalized": normalized_exact},
            ]},
            {"_id": 0, "number": 1, "id": 1, "displayName": 1, "name_normalized": 1},
        ).to_list(25)
    except Exception:
        bc_rows = []
    for row in bc_rows:
        _append_candidate(candidates, seen, row.get("number") or row.get("id"), source="hub_bc_vendors.number", stable=True)
        _append_candidate(candidates, seen, row.get("displayName"), source="hub_bc_vendors.displayName")
        _append_candidate(candidates, seen, row.get("name_normalized"), source="hub_bc_vendors.name_normalized")

    # Historical Hub documents bridge cases where the raw invoice name was
    # learned first and the canonical BC code was applied later (BALLCOR is the
    # production example that exposed this gap).
    try:
        doc_rows = await _db.hub_documents.find(
            {"$or": [
                {"vendor_canonical": exact},
                {"bc_vendor_number": exact},
                {"vendor_id": exact},
                {"vendor_no": exact},
                {"vendor_raw": exact},
                {"vendor_normalized": normalized_exact},
                {"extracted_fields.vendor": exact},
                {"normalized_fields.vendor": exact},
            ]},
            {
                "_id": 0,
                "vendor_canonical": 1,
                "bc_vendor_number": 1,
                "vendor_id": 1,
                "vendor_no": 1,
                "vendor_raw": 1,
                "vendor_normalized": 1,
                "extracted_fields.vendor": 1,
                "normalized_fields.vendor": 1,
            },
        ).limit(100).to_list(100)
    except Exception:
        doc_rows = []
    for row in doc_rows:
        extracted = row.get("extracted_fields") or {}
        normalized = row.get("normalized_fields") or {}
        for key in ("vendor_canonical", "bc_vendor_number", "vendor_id", "vendor_no"):
            _append_candidate(candidates, seen, row.get(key), source=f"hub_documents.{key}", stable=True)
        for value, source in (
            (row.get("vendor_raw"), "hub_documents.vendor_raw"),
            (row.get("vendor_normalized"), "hub_documents.vendor_normalized"),
            (extracted.get("vendor"), "hub_documents.extracted_fields.vendor"),
            (normalized.get("vendor"), "hub_documents.normalized_fields.vendor"),
        ):
            _append_candidate(candidates, seen, value, source=source)

    # Stable IDs first for new records; exact input remains available for legacy
    # key matching and is preferred when equally confident rules exist.
    candidates.sort(key=lambda item: (not item["stable"], item["source"] != "input"))
    return candidates


def _rule_profile_query(doc_type: str, has_po: bool, is_international: bool) -> Dict[str, Any]:
    return {
        "doc_type": str(doc_type or "").strip(),
        "has_po": bool(has_po),
        "is_international": bool(is_international),
    }


def _rule_vendor_values(rule: Dict[str, Any]) -> List[str]:
    """Return every vendor identity encoded in a legacy or current rule."""
    values: List[str] = []
    for field in ("vendor_pattern", "vendor_canonical_key"):
        value = rule.get(field)
        if value:
            values.append(str(value))

    aliases = rule.get("vendor_aliases") or []
    if isinstance(aliases, str):
        aliases = [aliases]
    values.extend(str(value) for value in aliases if value)

    routing_key = str(rule.get("routing_key") or "")
    if "|" in routing_key:
        values.append(routing_key.split("|", 1)[0])

    return values


def _rule_matches_candidates(rule: Dict[str, Any], candidate_normalized: set) -> bool:
    """Compare legacy stored vendor text after applying today's normalizer.

    Older feedback records stored raw legal suffixes directly in routing_key and
    vendor_pattern. Mongo exact matching cannot bridge a legacy value such as
    ``ball metal beverage container corp`` to today's normalized
    ``ball metal beverage container``. Normalize both sides in Python instead.
    """
    return any(
        normalized in candidate_normalized
        for normalized in (_normalize_vendor(value) for value in _rule_vendor_values(rule))
        if normalized
    )


async def _profile_alias_rules(
    candidates: List[Dict[str, Any]],
    doc_type: str,
    has_po: bool,
    is_international: bool,
    *,
    min_confidence: Optional[int] = None,
) -> List[Dict[str, Any]]:
    """Load profile-compatible rules and retain only alias-equivalent vendors."""
    query: Dict[str, Any] = _rule_profile_query(doc_type, has_po, is_international)
    if min_confidence is not None:
        query["confidence"] = {"$gte": min_confidence}

    rules = await _db[COLLECTION].find(query, {"_id": 0}).to_list(500)
    normalized_candidates = {
        candidate["normalized"]
        for candidate in candidates
        if candidate.get("normalized")
    }
    return [
        rule for rule in rules
        if _rule_matches_candidates(rule, normalized_candidates)
    ]


def _deduplicate_rules(rules: List[Dict[str, Any]]) -> List[Dict[str, Any]]:
    """De-duplicate exact-key and compatibility-query results."""
    deduped: List[Dict[str, Any]] = []
    seen = set()
    for rule in rules:
        identity = (
            str(rule.get("routing_key") or ""),
            str(rule.get("correct_folder") or ""),
            str(rule.get("created_at") or ""),
        )
        if identity in seen:
            continue
        seen.add(identity)
        deduped.append(rule)
    return deduped


async def record_correction(
    vendor: str,
    doc_type: str,
    has_po: bool,
    is_international: bool,
    correct_folder: str,
    file_name: str = "",
    source: str = "benchmark_fix",
) -> dict:
    """Create or strengthen a learned rule without splitting aliases.

    Conflicting rules across any known alias are protected exactly like an
    exact-key conflict; a later minority observation cannot silently replace an
    established route.
    """
    if _db is None:
        return {"status": "no_db"}

    candidates = await _vendor_candidates(vendor)
    if not candidates:
        return {"status": "skipped_no_vendor"}

    keys = [
        _make_routing_key(c["normalized"], doc_type, has_po, is_international)
        for c in candidates
    ]
    now = datetime.now(timezone.utc).isoformat()

    exact_rules = await _db[COLLECTION].find(
        {"routing_key": {"$in": keys}},
        {"_id": 0},
    ).to_list(100)
    legacy_rules = await _profile_alias_rules(
        candidates,
        doc_type,
        has_po,
        is_international,
    )
    existing_rules = _deduplicate_rules(exact_rules + legacy_rules)

    conflicting = [
        rule for rule in existing_rules
        if str(rule.get("correct_folder") or "").strip().lower()
        != str(correct_folder or "").strip().lower()
    ]
    if conflicting:
        strongest = sorted(conflicting, key=lambda r: int(r.get("confidence", 1)), reverse=True)[0]
        return {
            "status": "conflict",
            "key": strongest.get("routing_key"),
            "existing_folder": strongest.get("correct_folder"),
            "new_folder": correct_folder,
            "matched_aliases": [c["value"] for c in candidates],
        }

    matching = sorted(existing_rules, key=lambda r: int(r.get("confidence", 1)), reverse=True)
    alias_values = sorted({c["value"] for c in candidates if c.get("value")})

    if matching:
        existing = matching[0]
        key = existing["routing_key"]
        examples = list(existing.get("examples", []))
        if file_name and file_name not in examples:
            examples.append(file_name)
            examples = examples[-10:]
        confidence = int(existing.get("confidence", 1)) + 1
        await _db[COLLECTION].update_one(
            {"routing_key": key},
            {"$set": {
                "correct_folder": correct_folder,
                "confidence": confidence,
                "examples": examples,
                "vendor_aliases": alias_values,
                "updated_at": now,
            }},
        )
        return {"status": "strengthened", "key": key, "confidence": confidence}

    primary = next((c for c in candidates if c.get("stable")), candidates[0])
    key = _make_routing_key(primary["normalized"], doc_type, has_po, is_international)
    await _db[COLLECTION].insert_one({
        "vendor_pattern": primary["normalized"],
        "vendor_canonical_key": primary["value"],
        "vendor_aliases": alias_values,
        "doc_type": str(doc_type or "").strip(),
        "has_po": bool(has_po),
        "is_international": bool(is_international),
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
    """Return an alias-aware learned folder for this document profile."""
    if _db is None:
        return None

    candidates = await _vendor_candidates(vendor)
    if not candidates:
        return None

    keys = [
        _make_routing_key(c["normalized"], doc_type, has_po, is_international)
        for c in candidates
    ]
    exact_rules = await _db[COLLECTION].find(
        {
            "routing_key": {"$in": keys},
            "confidence": {"$gte": min_confidence},
        },
        {"_id": 0},
    ).to_list(100)
    legacy_rules = await _profile_alias_rules(
        candidates,
        doc_type,
        has_po,
        is_international,
        min_confidence=min_confidence,
    )
    rules = _deduplicate_rules(exact_rules + legacy_rules)

    if not rules:
        return None

    exact_key = _make_routing_key(vendor, doc_type, has_po, is_international)
    rules.sort(key=lambda rule: (
        int(rule.get("confidence", 1)),
        rule.get("routing_key") == exact_key,
        str(rule.get("updated_at") or ""),
    ), reverse=True)

    strongest_confidence = int(rules[0].get("confidence", 1))
    strongest = [r for r in rules if int(r.get("confidence", 1)) == strongest_confidence]
    folders = {str(r.get("correct_folder") or "").strip().lower() for r in strongest}
    if len(folders) > 1:
        exact = next((r for r in strongest if r.get("routing_key") == exact_key), None)
        if exact:
            chosen = exact
        else:
            logger.warning(
                "[Feedback] Alias conflict for vendor=%s type=%s keys=%s folders=%s; falling back to deterministic routing",
                vendor, doc_type, keys, sorted(folders),
            )
            return None
    else:
        chosen = strongest[0]

    logger.info(
        "[Feedback] Alias-aware hit: vendor=%s matched_key=%s -> %s (confidence=%s)",
        vendor,
        chosen.get("routing_key"),
        chosen.get("correct_folder"),
        chosen.get("confidence"),
    )
    return chosen.get("correct_folder")


async def get_all_rules() -> list:
    """Return all learned routing rules."""
    if _db is None:
        return []
    return await _db[COLLECTION].find({}, {"_id": 0}).sort("confidence", -1).to_list(500)


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
