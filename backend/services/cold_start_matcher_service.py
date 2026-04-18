"""
GPI Document Hub — Cold-Start Matcher Service
──────────────────────────────────────────────

When a brand-new customer (or one with no BC posted-order history yet)
sends us their first PO, the Giovanni-style intake learning is cold —
we have nothing to suggest. This service bootstraps that cold start by
finding the most similar *known* customer based on item-description
fingerprints and optionally surfacing their patterns as "inherited
suggestions" that the reviewer can promote into the new customer's
own pattern with a single click.

Algorithm (deliberately transparent, deterministic, no API cost):
  1. For every customer with ≥ 1 learned pattern, build a fingerprint:
       concat of every associated_line's item_no + description
  2. Tokenize → compute TF-IDF weighted token vectors
  3. On cold start, tokenize the inbound PO's line items the same way
     and compute cosine similarity against every customer fingerprint
  4. Return top-K customers with score ≥ MIN_SIMILARITY
  5. Pull the top customer's patterns, tag them `inherited=True`, and
     surface them in the reviewer's UI labelled with the source customer
     + similarity score ("90% similar to Giovanni — review before use")

Fingerprints are cached in `intake_customer_fingerprints` and marked
stale after 24h; when a pattern mutates (new BC learning, reviewer
feedback), the affected fingerprint is invalidated so the next
cold-start lookup recomputes it.

Dataset is small (≤ 200 fingerprints of ~100 tokens each) so we do
everything in-process with collections.Counter + math — no sklearn
dep, no vector DB needed.
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

FINGERPRINTS_COLL = "intake_customer_fingerprints"
PATTERNS_COLL = "order_line_patterns"

MIN_SIMILARITY = 0.20        # below this, we don't surface a match
MIN_TOKENS_IN_QUERY = 3      # need at least this many tokens before we bother
FINGERPRINT_TTL_HOURS = 24   # recompute if older than this
DEFAULT_TOP_K = 3

STOPWORDS = {
    "the", "a", "an", "of", "for", "and", "or", "to", "with",
    "on", "in", "at", "by", "from", "is", "are", "be",
    "required", "return", "oi",  # noise in packaging descriptions
}


# ─────────────────────────────────────────────────────────────
# Tokenization
# ─────────────────────────────────────────────────────────────

_TOKEN_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9\-]{1,}")


def tokenize(text: str) -> List[str]:
    """Lowercase tokenization that also preserves SKU-style tokens
    (e.g. `C-9874`, `OIPALLET`).

    Stopwords and pure numbers are dropped; SKU prefixes like `C-9874`
    are kept whole so `C-9874 → OITIERSHEET` correlations survive.
    """
    if not text:
        return []
    tokens = [t.lower() for t in _TOKEN_RE.findall(text)]
    return [
        t for t in tokens
        if t not in STOPWORDS and not t.isdigit() and len(t) > 1
    ]


def _line_items_to_tokens(line_items: List[Dict[str, Any]]) -> List[str]:
    out: List[str] = []
    for li in line_items or []:
        out.extend(tokenize(str(li.get("item_no") or "")))
        out.extend(tokenize(str(li.get("description") or "")))
    return out


def _pattern_to_tokens(pattern: Dict[str, Any]) -> List[str]:
    tokens: List[str] = []
    tokens.extend(tokenize(str(pattern.get("trigger_item_no") or "")))
    for ln in pattern.get("associated_lines") or []:
        if ln.get("retired"):
            continue  # don't learn from retired lines
        tokens.extend(tokenize(str(ln.get("item_no") or "")))
        tokens.extend(tokenize(str(ln.get("description") or "")))
    return tokens


# ─────────────────────────────────────────────────────────────
# Fingerprint build + cache
# ─────────────────────────────────────────────────────────────

async def build_fingerprint(customer_no: str, db=None) -> Dict[str, Any]:
    """Compute and cache a TF vector for a customer's full pattern set.

    Returns the fingerprint document. If the customer has no patterns,
    returns an empty fingerprint (but still caches it so we don't
    re-compute on every cold-start).
    """
    db = db if db is not None else get_db()
    tokens: List[str] = []
    pattern_count = 0
    async for p in db[PATTERNS_COLL].find({"customer_no": customer_no}, {"_id": 0}):
        tokens.extend(_pattern_to_tokens(p))
        pattern_count += 1

    tf = Counter(tokens)
    fp = {
        "id": str(uuid.uuid4()),
        "customer_no": customer_no,
        "token_count": len(tokens),
        "unique_tokens": len(tf),
        "tf": dict(tf),
        "pattern_count": pattern_count,
        "computed_at": datetime.now(timezone.utc).isoformat(),
    }
    await db[FINGERPRINTS_COLL].update_one(
        {"customer_no": customer_no},
        {"$set": {k: v for k, v in fp.items() if k != "id"}},
        upsert=True,
    )
    return fp


async def get_or_build_fingerprint(customer_no: str, db=None) -> Dict[str, Any]:
    """Return a cached fingerprint if fresh; otherwise rebuild."""
    db = db if db is not None else get_db()
    existing = await db[FINGERPRINTS_COLL].find_one(
        {"customer_no": customer_no}, {"_id": 0},
    )
    if existing and existing.get("computed_at"):
        try:
            age = datetime.now(timezone.utc) - datetime.fromisoformat(existing["computed_at"])
            if age < timedelta(hours=FINGERPRINT_TTL_HOURS):
                return existing
        except Exception:
            pass
    return await build_fingerprint(customer_no, db=db)


async def invalidate_fingerprint(customer_no: str, db=None) -> None:
    """Mark a customer's fingerprint stale (called on pattern mutations)."""
    if not customer_no:
        return
    db = db if db is not None else get_db()
    try:
        await db[FINGERPRINTS_COLL].update_one(
            {"customer_no": customer_no},
            {"$set": {"computed_at": "1970-01-01T00:00:00+00:00"}},
        )
    except Exception as e:
        logger.debug("[ColdStartMatcher] invalidate failed for %s: %s", customer_no, e)


async def rebuild_all_fingerprints(db=None) -> Dict[str, Any]:
    """Force a rebuild of every fingerprint. Safe to call from a backfill."""
    db = db if db is not None else get_db()
    customers = await db[PATTERNS_COLL].distinct("customer_no")
    for cust in customers:
        try:
            await build_fingerprint(cust, db=db)
        except Exception as e:
            logger.warning("[ColdStartMatcher] build failed for %s: %s", cust, e)
    return {"rebuilt": len(customers), "at": datetime.now(timezone.utc).isoformat()}


# ─────────────────────────────────────────────────────────────
# Similarity math (cosine on TF-IDF)
# ─────────────────────────────────────────────────────────────

def _cosine(a: Counter, b: Counter, idf: Dict[str, float]) -> float:
    if not a or not b:
        return 0.0
    # Weighted dot product + norms
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
    """Inverse document frequency across all fingerprints. Common tokens
    like 'pallet' get down-weighted; customer-specific tokens like
    'c-9874' get up-weighted."""
    n = max(len(fingerprints), 1)
    df: Counter = Counter()
    for fp in fingerprints:
        for token in (fp.get("tf") or {}).keys():
            df[token] += 1
    # Smoothed IDF
    return {t: math.log((n + 1) / (c + 1)) + 1.0 for t, c in df.items()}


# ─────────────────────────────────────────────────────────────
# Top-level cold-start lookup
# ─────────────────────────────────────────────────────────────

async def find_similar_customers(
    line_items: List[Dict[str, Any]],
    *,
    top_k: int = DEFAULT_TOP_K,
    exclude_customer_no: Optional[str] = None,
    db=None,
) -> List[Dict[str, Any]]:
    """Return the top-K most similar *known* customers for a cold-start PO.

    Each result includes: customer_no, similarity, matched_tokens,
    pattern_count, suggested_lines (the top 5 frequent lines from that
    customer's patterns, tagged inherited=True).
    """
    db = db if db is not None else get_db()
    query_tokens = _line_items_to_tokens(line_items)
    if len(query_tokens) < MIN_TOKENS_IN_QUERY:
        return []

    query_tf = Counter(query_tokens)

    # Pull all known fingerprints (excluding the target if known)
    q: Dict[str, Any] = {"token_count": {"$gt": 0}}
    if exclude_customer_no:
        q["customer_no"] = {"$ne": exclude_customer_no}
    fingerprints = await db[FINGERPRINTS_COLL].find(q, {"_id": 0}).to_list(500)
    if not fingerprints:
        return []

    # Include the query as a "document" for IDF so query-specific tokens
    # get proper weighting
    idf = _compute_idf(fingerprints + [{"tf": dict(query_tf)}])

    scored: List[Tuple[float, Dict[str, Any]]] = []
    for fp in fingerprints:
        fp_tf = Counter(fp.get("tf") or {})
        sim = _cosine(query_tf, fp_tf, idf)
        if sim >= MIN_SIMILARITY:
            scored.append((sim, fp))

    scored.sort(key=lambda x: x[0], reverse=True)
    scored = scored[:top_k]

    results: List[Dict[str, Any]] = []
    for sim, fp in scored:
        cust = fp["customer_no"]
        # Grab the top frequent associated_lines from this customer as
        # inherited suggestions
        inherited = await _pull_top_inherited_lines(db, cust, limit=5)
        # Token intersection for transparency
        matched = sorted(set(query_tf.keys()) & set((fp.get("tf") or {}).keys()))[:10]
        results.append({
            "customer_no": cust,
            "similarity": round(sim, 3),
            "pattern_count": fp.get("pattern_count", 0),
            "matched_tokens": matched,
            "inherited_suggestions": inherited,
        })
    return results


async def _pull_top_inherited_lines(
    db, source_customer_no: str, *, limit: int = 5,
) -> List[Dict[str, Any]]:
    """Get the top non-retired associated_lines for a source customer,
    ranked by frequency × occurrences. These are what we offer as
    inherited suggestions for a cold-start customer."""
    lines: List[Dict[str, Any]] = []
    async for p in db[PATTERNS_COLL].find(
        {"customer_no": source_customer_no}, {"_id": 0},
    ):
        for ln in (p.get("associated_lines") or []):
            if ln.get("retired"):
                continue
            freq = float(ln.get("frequency") or 0)
            occ = int(ln.get("occurrences") or 0)
            lines.append({
                "item_no": ln.get("item_no") or "",
                "description": ln.get("description") or "",
                "quantity": ln.get("quantity") or 1,
                "frequency": freq,
                "occurrences": occ,
                "source": "inherited_from_peer",
                "inherited_from": source_customer_no,
                "trigger_item": p.get("trigger_item_no"),
                "inherited": True,
            })
    lines.sort(key=lambda x: (x["frequency"], x["occurrences"]), reverse=True)
    return lines[:limit]


# ─────────────────────────────────────────────────────────────
# Promotion — turn an inherited suggestion into an own pattern
# ─────────────────────────────────────────────────────────────

async def promote_inherited_suggestion(
    *,
    target_customer_no: str,
    source_customer_no: str,
    item_no: str,
    trigger_item: Optional[str] = None,
    db=None,
) -> Dict[str, Any]:
    """When a reviewer accepts an inherited suggestion, we seed an
    owned pattern for the target customer containing just that line
    (so next time they'll get their own real suggestion). The event is
    also logged to `intake_learning_events` for audit."""
    db = db if db is not None else get_db()
    # Find the source line
    source_line: Optional[Dict[str, Any]] = None
    async for p in db[PATTERNS_COLL].find({"customer_no": source_customer_no}, {"_id": 0}):
        for ln in (p.get("associated_lines") or []):
            if (ln.get("item_no") or "").strip() == item_no.strip():
                source_line = ln
                if not trigger_item:
                    trigger_item = p.get("trigger_item_no")
                break
        if source_line:
            break

    if not source_line:
        return {"error": "source line not found", "item_no": item_no}

    # Upsert the target customer's pattern
    target_pattern = await db[PATTERNS_COLL].find_one(
        {"customer_no": target_customer_no, "trigger_item_no": trigger_item or "*"},
        {"_id": 0},
    )
    now = datetime.now(timezone.utc).isoformat()

    new_line = {
        "item_no": source_line.get("item_no"),
        "description": source_line.get("description"),
        "quantity": source_line.get("quantity", 1),
        "occurrences": 1,
        "frequency": 1.0,
        "accept_count": 1,
        "reject_count": 0,
        "feedback_count": 1,
        "inherited_from": source_customer_no,
        "promoted_at": now,
    }

    if target_pattern:
        lines = target_pattern.get("associated_lines") or []
        # Skip if already present
        if any((ln.get("item_no") or "") == new_line["item_no"] for ln in lines):
            return {"action": "already_present", "item_no": item_no}
        lines.append(new_line)
        await db[PATTERNS_COLL].update_one(
            {"customer_no": target_customer_no, "trigger_item_no": trigger_item or "*"},
            {"$set": {
                "associated_lines": lines,
                "last_feedback_at": now,
            }},
        )
    else:
        await db[PATTERNS_COLL].insert_one({
            "id": str(uuid.uuid4()),
            "customer_no": target_customer_no,
            "trigger_item_no": trigger_item or "*",
            "total_orders_analyzed": 1,
            "associated_lines": [new_line],
            "created_at": now,
            "last_feedback_at": now,
            "seeded_from": source_customer_no,
        })

    # Audit event
    try:
        await db.intake_learning_events.insert_one({
            "id": str(uuid.uuid4()),
            "event_type": "inherited_suggestion_promoted",
            "customer_no": target_customer_no,
            "item_no": item_no,
            "trigger_item": trigger_item,
            "extra": {"inherited_from": source_customer_no},
            "actor": "user",
            "created_at": now,
        })
    except Exception as e:
        logger.debug("[ColdStart.promote] audit event failed: %s", e)

    # Dual-write to unified learning_events_v2 (U1, v2.4.1)
    try:
        from services.learning_core import record_event
        await record_event(
            domain="sales_intake",
            event_type="inherited_suggestion_promoted",
            scope_type="customer",
            scope_value=target_customer_no,
            target={"item_no": item_no, "trigger_item": trigger_item},
            extra={"inherited_from": source_customer_no},
            actor="user",
            source="cold_start_matcher_service",
            db=db,
        )
    except Exception as e:
        logger.debug("[ColdStart.promote] unified audit failed: %s", e)

    # Invalidate both fingerprints so next cold-start lookup reflects the change
    await invalidate_fingerprint(target_customer_no, db=db)

    logger.info(
        "[ColdStart] promoted inherited item %s from %s → %s",
        item_no, source_customer_no, target_customer_no,
    )
    return {
        "action": "promoted",
        "target_customer_no": target_customer_no,
        "source_customer_no": source_customer_no,
        "item_no": item_no,
        "trigger_item": trigger_item or "*",
    }


__all__ = [
    "tokenize",
    "build_fingerprint",
    "get_or_build_fingerprint",
    "invalidate_fingerprint",
    "rebuild_all_fingerprints",
    "find_similar_customers",
    "promote_inherited_suggestion",
    "MIN_SIMILARITY",
    "DEFAULT_TOP_K",
]
