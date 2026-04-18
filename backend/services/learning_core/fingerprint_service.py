"""
GPI Document Hub — Shared Fingerprint Service (U2, v2.5.1)
───────────────────────────────────────────────────────────

Domain-agnostic TF-IDF fingerprint + cosine similarity. Powers both:
  • Customer fingerprints (sales intake — cold-start peer matching)
  • Vendor fingerprints  (AP posting — vendor-alias discovery)

Caches all fingerprints in the unified `scope_fingerprints` collection
with a polymorphic `scope_type` discriminator ("customer" | "vendor")
so one index serves both queries.

This module is the long-term home for the cosine-similarity math that
was prototyped in `cold_start_matcher_service.py` (v2.4.0). The
cold-start matcher now delegates here; the old surface stays
backwards-compatible for existing callers during the migration window.
"""

import logging
import math
import re
import uuid
from collections import Counter
from datetime import datetime, timezone, timedelta
from typing import Any, Dict, List, Optional, Tuple

from deps import get_db

logger = logging.getLogger(__name__)

FINGERPRINTS_COLL = "scope_fingerprints"   # new unified collection
FINGERPRINT_TTL_HOURS = 24
DEFAULT_MIN_SIMILARITY = 0.20
DEFAULT_TOP_K = 3
MIN_TOKENS_IN_QUERY = 3

SCOPE_TYPES = {"customer", "vendor"}

STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "or", "to", "with",
    "on", "in", "at", "by", "from", "is", "are", "be",
    "required", "return", "oi",          # packaging noise
    "inc", "llc", "co", "corp", "ltd",   # vendor-name noise
}

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{1,}")
_INDEXES_CREATED = False


# ─────────────────────────────────────────────────────────────
# Tokenization (same rules as cold_start_matcher — now canonical)
# ─────────────────────────────────────────────────────────────

def tokenize(text: str) -> List[str]:
    if not text:
        return []
    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    return [
        t for t in tokens
        if t not in STOPWORDS and not t.isdigit() and len(t) > 1
    ]


# ─────────────────────────────────────────────────────────────
# Index bootstrap
# ─────────────────────────────────────────────────────────────

async def _ensure_indexes(db) -> None:
    global _INDEXES_CREATED
    if _INDEXES_CREATED:
        return
    try:
        await db[FINGERPRINTS_COLL].create_index(
            [("scope_type", 1), ("scope_value", 1)],
            unique=True, name="scope_unique",
        )
        await db[FINGERPRINTS_COLL].create_index(
            [("scope_type", 1), ("token_count", -1)],
            name="scope_nonempty",
        )
        _INDEXES_CREATED = True
    except Exception as e:
        logger.debug("[Fingerprint] index create skipped: %s", e)


# ─────────────────────────────────────────────────────────────
# Pluggable token extractors per scope_type
# ─────────────────────────────────────────────────────────────

async def _customer_tokens(db, scope_value: str) -> Tuple[List[str], int]:
    """Tokens from all learned order-line patterns (exclude retired lines)."""
    tokens: List[str] = []
    count = 0
    async for p in db.order_line_patterns.find({"customer_no": scope_value}, {"_id": 0}):
        tokens.extend(tokenize(str(p.get("trigger_item_no") or "")))
        for ln in (p.get("associated_lines") or []):
            if ln.get("retired"):
                continue
            tokens.extend(tokenize(str(ln.get("item_no") or "")))
            tokens.extend(tokenize(str(ln.get("description") or "")))
        count += 1
    return tokens, count


async def _vendor_tokens(db, scope_value: str) -> Tuple[List[str], int]:
    """Tokens from posting-pattern profile (top items + GL codes + vendor name)."""
    tokens: List[str] = []
    count = 0
    profile = await db.posting_pattern_analysis.find_one(
        {"vendor_no": scope_value}, {"_id": 0},
    )
    if profile:
        count = 1
        tokens.extend(tokenize(str(profile.get("vendor_name") or "")))
        for it in (profile.get("top_items") or [])[:50]:
            tokens.extend(tokenize(str(it.get("item_no") or "")))
            tokens.extend(tokenize(str(it.get("description") or "")))
        for gl in (profile.get("top_gl_accounts") or [])[:10]:
            tokens.extend(tokenize(str(gl.get("gl_account") or "")))
    return tokens, count


SCOPE_EXTRACTORS = {
    "customer": _customer_tokens,
    "vendor": _vendor_tokens,
}


# ─────────────────────────────────────────────────────────────
# Core API
# ─────────────────────────────────────────────────────────────

async def build_fingerprint(
    scope_type: str, scope_value: str, db=None,
) -> Dict[str, Any]:
    if scope_type not in SCOPE_TYPES:
        return {"error": f"unknown scope_type '{scope_type}'"}
    db = db if db is not None else get_db()
    await _ensure_indexes(db)

    extractor = SCOPE_EXTRACTORS[scope_type]
    tokens, source_count = await extractor(db, scope_value)
    tf = Counter(tokens)
    fp = {
        "scope_type": scope_type,
        "scope_value": scope_value,
        "token_count": len(tokens),
        "unique_tokens": len(tf),
        "tf": dict(tf),
        "source_count": source_count,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db[FINGERPRINTS_COLL].update_one(
        {"scope_type": scope_type, "scope_value": scope_value},
        {"$set": fp},
        upsert=True,
    )
    return fp


async def get_or_build(
    scope_type: str, scope_value: str, db=None,
) -> Dict[str, Any]:
    db = db if db is not None else get_db()
    existing = await db[FINGERPRINTS_COLL].find_one(
        {"scope_type": scope_type, "scope_value": scope_value}, {"_id": 0},
    )
    if existing and existing.get("computed_at"):
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(existing["computed_at"])
            if age < timedelta(hours=FINGERPRINT_TTL_HOURS):
                return existing
        except Exception:
            pass
    return await build_fingerprint(scope_type, scope_value, db=db)


async def invalidate(scope_type: str, scope_value: str, db=None) -> None:
    if not scope_value or scope_type not in SCOPE_TYPES:
        return
    db = db if db is not None else get_db()
    try:
        await db[FINGERPRINTS_COLL].update_one(
            {"scope_type": scope_type, "scope_value": scope_value},
            {"$set": {"computed_at": "1970-01-01T00:00:00+00:00"}},
        )
    except Exception as e:
        logger.debug("[Fingerprint] invalidate failed for %s/%s: %s", scope_type, scope_value, e)


async def rebuild_all(scope_type: str, db=None) -> Dict[str, Any]:
    db = db if db is not None else get_db()
    if scope_type == "customer":
        scopes = await db.order_line_patterns.distinct("customer_no")
    elif scope_type == "vendor":
        scopes = await db.posting_pattern_analysis.distinct("vendor_no")
    else:
        return {"error": f"unknown scope_type '{scope_type}'"}
    built = 0
    for s in scopes:
        if not s:
            continue
        try:
            await build_fingerprint(scope_type, s, db=db)
            built += 1
        except Exception as e:
            logger.warning("[Fingerprint] build %s/%s failed: %s", scope_type, s, e)
    return {
        "scope_type": scope_type,
        "rebuilt": built,
        "at": datetime.now(timezone.utc).isoformat(),
    }


# ─────────────────────────────────────────────────────────────
# Similarity math (identical to v2.4.0 — now shared)
# ─────────────────────────────────────────────────────────────

def _cosine(a: Counter, b: Counter, idf: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    common = set(a.keys()) & set(b.keys())
    if not common:
        return 0.0
    dot = sum(a[t] * b[t] * (idf.get(t, 1.0) ** 2) for t in common)
    norm_a = math.sqrt(sum((c * idf.get(t, 1.0)) ** 2 for t, c in a.items()))
    norm_b = math.sqrt(sum((c * idf.get(t, 1.0)) ** 2 for t, c in b.items()))
    if norm_a == 0 or norm_b == 0:
        return 0.0
    return dot / (norm_a * norm_b)


def _compute_idf(fingerprints: List[Dict[str, Any]]) -> Dict[str, float]:
    n = max(len(fingerprints), 1)
    df: Counter = Counter()
    for fp in fingerprints:
        for token in (fp.get("tf") or {}).keys():
            df[token] += 1
    return {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}


async def find_similar(
    query_tokens: List[str],
    *,
    scope_type: str,
    top_k: int = DEFAULT_TOP_K,
    min_similarity: float = DEFAULT_MIN_SIMILARITY,
    exclude_scope_value: Optional[str] = None,
    db=None,
) -> List[Dict[str, Any]]:
    """Find top-K similar fingerprints of the given scope_type.

    Returns list of {scope_value, similarity, matched_tokens, source_count}.
    """
    if len(query_tokens) < MIN_TOKENS_IN_QUERY:
        return []
    db = db if db is not None else get_db()
    query_tf = Counter(query_tokens)
    q: Dict[str, Any] = {"scope_type": scope_type, "token_count": {"$gt": 0}}
    if exclude_scope_value:
        q["scope_value"] = {"$ne": exclude_scope_value}
    fingerprints = await db[FINGERPRINTS_COLL].find(q, {"_id": 0}).to_list(500)
    if not fingerprints:
        return []

    idf = _compute_idf(fingerprints + [{"tf": dict(query_tf)}])
    scored: List[Tuple[float, Dict[str, Any]]] = []
    for fp in fingerprints:
        sim = _cosine(query_tf, Counter(fp.get("tf") or {}), idf)
        if sim >= min_similarity:
            scored.append((sim, fp))
    scored.sort(key=lambda x: x[0], reverse=True)
    return [
        {
            "scope_type": scope_type,
            "scope_value": fp["scope_value"],
            "similarity": round(sim, 3),
            "matched_tokens": sorted(set(query_tf.keys()) & set((fp.get("tf") or {}).keys()))[:10],
            "source_count": fp.get("source_count", 0),
        }
        for sim, fp in scored[:top_k]
    ]


__all__ = [
    "tokenize",
    "build_fingerprint",
    "get_or_build",
    "invalidate",
    "rebuild_all",
    "find_similar",
    "FINGERPRINTS_COLL",
    "SCOPE_TYPES",
]
