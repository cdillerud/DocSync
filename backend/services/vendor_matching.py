"""
GPI Document Hub - Vendor Matching Logic

Authoritative implementations of vendor alias lookup, BC vendor matching,
and document duplicate detection, extracted from server.py during the
"Orchestration Extraction" remediation pass.

Dependencies:
  - deps.get_db() for database access
  - services.vendor_name_helpers for normalize_vendor_name, calculate_fuzzy_score
  - services.bc_access for search_vendors_by_name, BCLookupStatus
  - server.py config vars (TENANT_ID, BC_READ_ENVIRONMENT, VENDOR_ALIAS_MAP)
    accessed via lazy import — future config-module extraction target
"""

import logging
import re
from datetime import datetime, timezone

import httpx

from deps import get_db

logger = logging.getLogger(__name__)


# ---------------------------------------------------------------------------
# Lazy helpers (avoid circular imports at module level)
# ---------------------------------------------------------------------------

def _vendor_helpers():
    from services.vendor_name_helpers import (
        normalize_vendor_name, calculate_fuzzy_score, VENDOR_ALIAS_MAP,
    )
    return normalize_vendor_name, calculate_fuzzy_score, VENDOR_ALIAS_MAP


def _bc_search():
    from services.bc_access import search_vendors_by_name, BCLookupStatus
    return search_vendors_by_name, BCLookupStatus


def _server_config():
    """Read mutable config vars from server.py (future: centralized config module)."""
    import server
    return server.TENANT_ID, server.BC_READ_ENVIRONMENT, server.VENDOR_ALIAS_MAP


# ---------------------------------------------------------------------------
# Vendor alias / DB matching
# ---------------------------------------------------------------------------

async def lookup_vendor_alias(vendor_normalized: str) -> dict:
    """
    Multi-source vendor lookup.

    Order of resolution:
      1. Vendor aliases collection (manual mappings)
      2. Cached BC vendors (hub_bc_vendors)
      3. Live BC API search (title-case, then first-word fallback)

    Returns dict with keys:
      vendor_canonical, vendor_match_method, vendor_name, vendor_no
    """
    db = get_db()
    search_vendors_by_name, BCLookupStatus = _bc_search()

    if not vendor_normalized:
        return {"vendor_canonical": None, "vendor_match_method": "none"}

    # 1. Check vendor_aliases collection
    alias_doc = await db.vendor_aliases.find_one({
        "$or": [
            {"normalized": vendor_normalized},
            {"normalized_alias": vendor_normalized},
            {"alias_string": {"$regex": f"^{re.escape(vendor_normalized)}$", "$options": "i"}},
        ]
    }, {"_id": 0})

    if alias_doc:
        canonical_id = (
            alias_doc.get("canonical_vendor_id")
            or alias_doc.get("vendor_no")
            or alias_doc.get("vendor_name")
        )
        # Track alias usage
        try:
            await db.vendor_aliases.update_one(
                {"$or": [
                    {"normalized": vendor_normalized},
                    {"normalized_alias": vendor_normalized},
                ]},
                {
                    "$inc": {"usage_count": 1},
                    "$set": {"last_used_at": datetime.now(timezone.utc).isoformat()},
                },
            )
        except Exception:
            pass
        match_method = "alias_match" if alias_doc.get("source") in ("auto_learned", "manual_resolution") else "alias_match"
        return {
            "vendor_canonical": canonical_id,
            "vendor_match_method": match_method,
            "vendor_name": alias_doc.get("vendor_name"),
            "vendor_no": alias_doc.get("vendor_no"),
        }

    # 2. Check cached BC vendors (exact + fuzzy with rapidfuzz)
    bc_vendor = await db.hub_bc_vendors.find_one({
        "$or": [
            {"name_normalized": vendor_normalized},
            {"displayName": {"$regex": f"^{re.escape(vendor_normalized)}$", "$options": "i"}},
        ]
    }, {"_id": 0})

    if bc_vendor:
        return {
            "vendor_canonical": bc_vendor.get("number") or bc_vendor.get("id"),
            "vendor_match_method": "bc_exact_match",
            "vendor_name": bc_vendor.get("displayName"),
            "vendor_no": bc_vendor.get("number"),
        }

    # 2b. Fuzzy match against cached BC vendors using rapidfuzz
    try:
        from rapidfuzz import fuzz as _fuzz
        normalize_vendor_name, _, _ = _vendor_helpers()

        bc_vendors_cursor = db.hub_bc_vendors.find({}, {"_id": 0, "displayName": 1, "number": 1, "id": 1})
        bc_vendors_list = await bc_vendors_cursor.to_list(1000)

        best_match = None
        best_score = 0.0
        for bv in bc_vendors_list:
            bc_display = bv.get("displayName", "")
            bc_norm = normalize_vendor_name(bc_display)
            if not bc_norm:
                continue
            score = _fuzz.token_sort_ratio(vendor_normalized, bc_norm) / 100.0
            if score > best_score:
                best_score = score
                best_match = bv

        if best_match and best_score >= 0.90:
            return {
                "vendor_canonical": best_match.get("number") or best_match.get("id"),
                "vendor_match_method": "fuzzy_match",
                "vendor_name": best_match.get("displayName"),
                "vendor_no": best_match.get("number"),
                "match_score": round(best_score, 3),
            }
    except Exception as e:
        logger.debug("Fuzzy BC vendor match failed: %s", e)

    # 3. Live BC API search
    try:
        vendor_search_term = vendor_normalized.title()
        bc_result = await search_vendors_by_name(vendor_search_term, limit=10)

        if bc_result.status == BCLookupStatus.SUCCESS:
            vendors = bc_result.data.get("vendors", [])

            if vendors:
                # Try exact normalized match
                for vendor in vendors:
                    bc_name = vendor.get("displayName", "").lower()
                    bc_normalized = re.sub(r'\s+', ' ', bc_name.strip())

                    if bc_normalized == vendor_normalized:
                        return {
                            "vendor_canonical": vendor.get("number") or vendor.get("id"),
                            "vendor_match_method": "bc_search",
                            "vendor_name": vendor.get("displayName"),
                            "vendor_no": vendor.get("number"),
                        }

                # Fuzzy matching with rapidfuzz
                best_match = None
                best_score = 0

                normalize_fn, _, _ = _vendor_helpers()

                for vendor in vendors:
                    bc_name = vendor.get("displayName", "")
                    bc_normalized = normalize_fn(bc_name)

                    try:
                        from rapidfuzz import fuzz as _fuzz
                        score = _fuzz.token_sort_ratio(vendor_normalized, bc_normalized) / 100.0
                    except ImportError:
                        # Fallback to token overlap
                        search_words = set(vendor_normalized.split())
                        bc_words = set(bc_normalized.split())
                        overlap = len(search_words & bc_words)
                        total = len(search_words | bc_words)
                        score = overlap / total if total > 0 else 0

                    if score > best_score and score >= 0.6:
                        best_score = score
                        best_match = vendor

                if best_match and best_score >= 0.90:
                    return {
                        "vendor_canonical": best_match.get("number") or best_match.get("id"),
                        "vendor_match_method": "fuzzy_match",
                        "vendor_name": best_match.get("displayName"),
                        "vendor_no": best_match.get("number"),
                        "match_score": round(best_score, 3),
                    }
                elif best_match:
                    return {
                        "vendor_canonical": best_match.get("number") or best_match.get("id"),
                        "vendor_match_method": "fuzzy_match",
                        "vendor_name": best_match.get("displayName"),
                        "vendor_no": best_match.get("number"),
                        "match_score": round(best_score, 3),
                    }

        # Fallback: first-word search
        first_word = vendor_normalized.split()[0] if vendor_normalized else ""
        if first_word and len(first_word) >= 3:
            bc_result2 = await search_vendors_by_name(first_word.title(), limit=10)

            if bc_result2.status == BCLookupStatus.SUCCESS:
                vendors2 = bc_result2.data.get("vendors", [])

                for vendor in vendors2:
                    bc_name = vendor.get("displayName", "")
                    bc_normalized = normalize_fn(bc_name) if 'normalize_fn' in dir() else re.sub(r'\s+', ' ', bc_name.lower().strip())

                    if bc_normalized.startswith(first_word):
                        try:
                            from rapidfuzz import fuzz as _fuzz
                            score = _fuzz.token_sort_ratio(vendor_normalized, bc_normalized) / 100.0
                        except ImportError:
                            search_words = set(vendor_normalized.split())
                            bc_words = set(bc_normalized.split())
                            overlap = len(search_words & bc_words)
                            total = len(search_words | bc_words)
                            score = overlap / total if total > 0 else 0

                        if score >= 0.5:
                            return {
                                "vendor_canonical": vendor.get("number") or vendor.get("id"),
                                "vendor_match_method": "fuzzy_match",
                                "vendor_name": vendor.get("displayName"),
                                "vendor_no": vendor.get("number"),
                                "match_score": round(score, 3),
                            }

    except Exception as e:
        logger.warning("BC vendor search failed: %s", e)

    return {"vendor_canonical": None, "vendor_match_method": "none"}


# ---------------------------------------------------------------------------
# BC multi-strategy vendor matching
# ---------------------------------------------------------------------------

async def match_vendor_in_bc(
    vendor_name: str,
    strategies: list,
    threshold: float,
    token: str,
    company_id: str,
) -> dict:
    """
    Multi-strategy vendor matching against Business Central.

    Strategies tried in order: alias, exact_no, exact_name, normalized, fuzzy.
    Uses server-side OData filtering for efficient matching.

    Returns dict with keys:
      matched, match_method, selected_vendor, vendor_candidates, score
    """
    normalize_vendor_name, calculate_fuzzy_score, _ = _vendor_helpers()
    TENANT_ID, BC_READ_ENVIRONMENT, VENDOR_ALIAS_MAP = _server_config()

    result = {
        "matched": False,
        "match_method": None,
        "selected_vendor": None,
        "vendor_candidates": [],
        "score": 0.0,
    }

    if not vendor_name:
        return result

    normalized_input = normalize_vendor_name(vendor_name)

    # Extract key search terms for server-side filtering
    search_terms = [w for w in normalized_input.split() if len(w) >= 3]
    primary_search_term = max(search_terms, key=len) if search_terms else None

    async with httpx.AsyncClient(timeout=30.0) as c:
        vendors = []

        # Strategy 1: Server-side search with contains() filter
        if primary_search_term and len(primary_search_term) >= 4:
            filter_query = f"contains(displayName, '{primary_search_term}')"
            resp = await c.get(
                f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors",
                headers={"Authorization": f"Bearer {token}"},
                params={"$select": "id,number,displayName", "$filter": filter_query, "$top": "100"},
            )

            if resp.status_code == 200:
                vendors = resp.json().get("value", [])
                logger.info(
                    "BC vendor search for '%s' returned %d candidates (env=%s)",
                    primary_search_term, len(vendors), BC_READ_ENVIRONMENT,
                )

        # Strategy 2: Broader fetch fallback
        if not vendors:
            resp = await c.get(
                f"https://api.businesscentral.dynamics.com/v2.0/{TENANT_ID}/{BC_READ_ENVIRONMENT}/api/v2.0/companies({company_id})/vendors",
                headers={"Authorization": f"Bearer {token}"},
                params={"$select": "id,number,displayName", "$top": "1000"},
            )

            if resp.status_code != 200:
                return result

            vendors = resp.json().get("value", [])

        # Alias map lookup
        if "alias" in strategies:
            alias_target = (
                VENDOR_ALIAS_MAP.get(vendor_name)
                or VENDOR_ALIAS_MAP.get(vendor_name.lower())
                or VENDOR_ALIAS_MAP.get(normalized_input)
            )
            if alias_target:
                for v in vendors:
                    v_display = v.get("displayName", "")
                    v_number = v.get("number", "")
                    if (v_display.lower() == alias_target.lower()
                            or v_number.lower() == alias_target.lower()):
                        result["matched"] = True
                        result["match_method"] = "alias_match"
                        result["selected_vendor"] = v
                        result["score"] = 1.0
                        return result

        # Try each strategy in order
        candidates = []

        for vendor in vendors:
            vendor_display = vendor.get("displayName", "")
            vendor_number = vendor.get("number", "")

            if "exact_no" in strategies:
                if vendor_number.lower() == vendor_name.lower():
                    result["matched"] = True
                    result["match_method"] = "bc_exact_match"
                    result["selected_vendor"] = vendor
                    result["score"] = 1.0
                    return result

            if "exact_name" in strategies:
                if vendor_display.lower() == vendor_name.lower():
                    result["matched"] = True
                    result["match_method"] = "bc_exact_match"
                    result["selected_vendor"] = vendor
                    result["score"] = 1.0
                    return result

            if "normalized" in strategies:
                normalized_bc = normalize_vendor_name(vendor_display)
                if normalized_input and normalized_bc == normalized_input:
                    result["matched"] = True
                    result["match_method"] = "bc_exact_match"
                    result["selected_vendor"] = vendor
                    result["score"] = 0.95
                    return result

            if "fuzzy" in strategies:
                score = calculate_fuzzy_score(vendor_name, vendor_display)
                if score > 0.3:
                    candidates.append({
                        "vendor": vendor,
                        "score": score,
                        "display_name": vendor_display,
                        "vendor_id": vendor.get("id"),
                    })

        candidates.sort(key=lambda x: x["score"], reverse=True)
        result["vendor_candidates"] = candidates[:5]

        if candidates and candidates[0]["score"] >= threshold:
            result["matched"] = True
            result["match_method"] = "fuzzy_match"
            result["selected_vendor"] = candidates[0]["vendor"]
            result["score"] = candidates[0]["score"]
        elif candidates:
            result["matched"] = False
            result["match_method"] = "fuzzy_match"
            result["score"] = candidates[0]["score"] if candidates else 0

    return result


# ---------------------------------------------------------------------------
# Duplicate detection
# ---------------------------------------------------------------------------

async def check_duplicate_document(
    vendor_normalized: str,
    vendor_canonical: str,
    invoice_number_clean: str,
    current_doc_id: str,
) -> dict:
    """
    Check for potential duplicate AP invoice in the Hub.

    A document is a possible duplicate if another non-deleted doc exists with
    the same vendor (canonical or normalized) and same invoice_number_clean.
    """
    db = get_db()

    if not invoice_number_clean:
        return {"possible_duplicate": False, "duplicate_of_document_id": None}

    vendor_match = {}
    if vendor_canonical:
        vendor_match = {"$or": [
            {"vendor_canonical": vendor_canonical},
            {"vendor_normalized": vendor_normalized},
        ]}
    elif vendor_normalized:
        vendor_match = {"vendor_normalized": vendor_normalized}
    else:
        return {"possible_duplicate": False, "duplicate_of_document_id": None}

    query = {
        **vendor_match,
        "invoice_number_clean": invoice_number_clean,
        "id": {"$ne": current_doc_id},
        "status": {"$nin": ["Deleted", "Rejected"]},
    }

    existing = await db.hub_documents.find_one(query, {"id": 1, "_id": 0})

    if existing:
        return {
            "possible_duplicate": True,
            "duplicate_of_document_id": existing.get("id"),
        }

    return {"possible_duplicate": False, "duplicate_of_document_id": None}
