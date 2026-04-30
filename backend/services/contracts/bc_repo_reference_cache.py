"""Phase 4C(d) — Read-only :class:`BCLookupRepository` backed by the live
``bc_reference_cache`` collection.

Wires the existing ``services.bc_reference_cache_service`` cache (already
populated and refreshed by the rest of GPI Hub) into the contract
intelligence matcher so Navigator imports can produce real BC link
candidates instead of always landing as ``party_unmatched`` exceptions.

Strict guarantees:
  * Read-only against MongoDB; no BC API calls; no writes anywhere.
  * Soft-fails when the cache is empty / unavailable — the matcher
    receives an empty list and the orchestrator emits the existing
    ``party_unmatched`` exception flow without regression.
  * Fuzzy match uses the same token-overlap heuristic the in-memory
    test repo uses, so behavior between unit tests and production
    stays aligned.

Cache schema reference (see ``ENTITY_CONFIGS`` in
``bc_reference_cache_service``):
    customers:  ``{entity_type: "customer", bc_customer_no, bc_customer_name, displayName, email, ...}``
    vendors:    no dedicated master sync today; surfaced indirectly via
                purchase orders / invoices (``bc_vendor_no`` /
                ``bc_vendor_name`` fields). We dedupe by
                ``bc_vendor_no`` across those rows.
    items:      no master sync today → always returns ``[]`` and reports
                ``items_unavailable`` once when first asked.
"""

from __future__ import annotations

import logging
import re
from typing import Any, Dict, List, Optional, Set, Tuple

from services.contracts.bc_agreement_matcher import BCCandidate, BCLookupRepository

logger = logging.getLogger(__name__)


_TOKEN_RE = re.compile(r"[a-z0-9]+")
# Suffixes / fillers we ignore so "Bragg Live Food Products LLC" and
# "Bragg Live Food Products" still produce a perfect Jaccard score.
_TRIVIAL_TOKENS = {
    "inc", "llc", "ltd", "co", "corp", "incorporated", "limited",
    "company", "the", "and",
}


def _tokenize(text: Optional[str]) -> Set[str]:
    if not text:
        return set()
    return {
        t for t in _TOKEN_RE.findall(str(text).lower())
        if t not in _TRIVIAL_TOKENS
    }


def _jaccard_score(a: Set[str], b: Set[str]) -> float:
    if not a or not b:
        return 0.0
    intersection = a & b
    union = a | b
    return len(intersection) / len(union)


def _confidence_method(score: float, exact_no: bool = False) -> Tuple[float, str]:
    """Map a raw Jaccard score → (confidence, MatchMethod literal)."""
    if exact_no:
        return 1.0, "exact_no"
    if score >= 0.999:
        return min(0.99, max(0.96, score)), "exact_name"
    if score >= 0.6:
        return score, "fuzzy"
    return score, "fuzzy"


class BCReferenceCacheRepository:
    """Adapter that satisfies :class:`BCLookupRepository` using the local
    BC reference cache. Stateless apart from a one-shot ``items``
    unavailability log to avoid spamming on every import row.

    Construction is cheap; instantiate per request.
    """

    def __init__(self, db: Any) -> None:
        self.db = db
        self._items_unavailable_logged = False
        # ``unavailable`` flips the first time we fail to read the
        # cache (so callers can surface a single warning to the UI).
        self.unavailable: bool = False
        # Last-known counts populated by :meth:`probe`; useful for
        # dry-run diagnostics and the importer summary card.
        self.cache_counts: Dict[str, int] = {}

    # ------------------------------------------------------------------
    # Diagnostic probe — populates ``cache_counts``. Called once per
    # import run so the UI / CLI can show "cache: 3,210 customers /
    # 514 vendors / 0 items".
    # ------------------------------------------------------------------

    async def probe(self) -> Dict[str, int]:
        coll = self.db.bc_reference_cache
        try:
            customers = await coll.count_documents({"entity_type": "customer"})
            vendors_distinct = await coll.distinct(
                "bc_vendor_no", {"bc_vendor_no": {"$nin": [None, ""]}},
            )
            vendor_count = len(vendors_distinct)
            items = await coll.count_documents({"entity_type": "item"})
        except Exception as exc:  # noqa: BLE001
            logger.warning(
                "bc_reference_cache probe failed: %s — falling back to "
                "empty repository", exc,
            )
            self.unavailable = True
            self.cache_counts = {"customers": 0, "vendors": 0, "items": 0}
            return self.cache_counts
        self.cache_counts = {
            "customers": int(customers),
            "vendors": int(vendor_count),
            "items": int(items),
        }
        return self.cache_counts

    # ------------------------------------------------------------------
    # Customers
    # ------------------------------------------------------------------

    async def find_customer_candidates(
        self, *, name: Optional[str], email: Optional[str], limit: int = 5,
    ) -> List[BCCandidate]:
        if self.unavailable or not (name or email):
            return []
        coll = self.db.bc_reference_cache
        query: Dict[str, Any] = {"entity_type": "customer"}
        try:
            cursor = coll.find(
                query,
                {
                    "_id": 0,
                    "bc_customer_no": 1,
                    "bc_customer_name": 1,
                    "displayName": 1,
                    "email": 1,
                    "number": 1,
                },
            )
            rows = await cursor.to_list(length=10000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("bc cache customer query failed: %s", exc)
            self.unavailable = True
            return []
        return self._score_party_rows(rows, name=name, email=email, limit=limit,
                                      no_field=("bc_customer_no", "number"),
                                      name_field=("bc_customer_name", "displayName"))

    # ------------------------------------------------------------------
    # Vendors — surfaced indirectly via PO/SO/invoice cache rows. We
    # build a deduped roster on the fly, keyed by bc_vendor_no.
    # ------------------------------------------------------------------

    async def find_vendor_candidates(
        self, *, name: Optional[str], email: Optional[str], limit: int = 5,
    ) -> List[BCCandidate]:
        if self.unavailable or not (name or email):
            return []
        coll = self.db.bc_reference_cache
        try:
            cursor = coll.aggregate([
                {"$match": {
                    "bc_vendor_no": {"$nin": [None, ""]},
                    "bc_vendor_name": {"$nin": [None, ""]},
                }},
                {"$group": {
                    "_id": "$bc_vendor_no",
                    "bc_vendor_name": {"$first": "$bc_vendor_name"},
                }},
                {"$limit": 5000},
            ])
            rows_raw = await cursor.to_list(length=5000)
        except Exception as exc:  # noqa: BLE001
            logger.warning("bc cache vendor aggregate failed: %s", exc)
            self.unavailable = True
            return []
        # Reshape so the shared scorer can read the same field names.
        rows = [
            {"bc_vendor_no": r["_id"], "bc_vendor_name": r["bc_vendor_name"]}
            for r in rows_raw
        ]
        return self._score_party_rows(rows, name=name, email=email, limit=limit,
                                      no_field=("bc_vendor_no",),
                                      name_field=("bc_vendor_name",))

    # ------------------------------------------------------------------
    # Items
    # ------------------------------------------------------------------

    async def find_item_candidates(
        self, *, label: Optional[str], description: Optional[str], limit: int = 5,
    ) -> List[BCCandidate]:
        # No master items cache yet; emit a single advisory log and
        # let the orchestrator's normal "no candidates → exception"
        # behavior take over.
        if not self._items_unavailable_logged:
            logger.info(
                "bc_reference_cache has no master items collection; "
                "item matching disabled until that cache exists",
            )
            self._items_unavailable_logged = True
        return []

    # ------------------------------------------------------------------
    # Internal scoring — shared by customer + vendor paths.
    # ------------------------------------------------------------------

    def _score_party_rows(
        self,
        rows: List[Dict[str, Any]],
        *,
        name: Optional[str],
        email: Optional[str],
        limit: int,
        no_field: Tuple[str, ...],
        name_field: Tuple[str, ...],
    ) -> List[BCCandidate]:
        query_tokens = _tokenize(name)
        if not query_tokens and not email:
            return []
        # Optional: support ``bc_customer_code`` / ``bc_vendor_code``
        # being stamped onto the agreement (currently consumed via the
        # matcher's exact_no short-circuit). The Navigator row may pass
        # the explicit code via ``email`` field if a future template
        # carries it; for now this path is dormant.
        scored: List[BCCandidate] = []
        for r in rows:
            no = next((str(r.get(f) or "").strip() for f in no_field if r.get(f)), "")
            disp = next((str(r.get(f) or "").strip() for f in name_field if r.get(f)), "")
            if not no:
                continue
            row_tokens = _tokenize(disp)
            score = _jaccard_score(query_tokens, row_tokens)
            if score < 0.3:  # drop weak matches before sort
                continue
            confidence, method = _confidence_method(score)
            scored.append(BCCandidate(
                no=no,
                name=disp,
                score=confidence,
                method=method,  # type: ignore[arg-type]
                extra={"raw_score": score},
            ))
        scored.sort(key=lambda c: c.score, reverse=True)
        return scored[:limit]
